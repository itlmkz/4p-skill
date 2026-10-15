#!/usr/bin/env python3
"""Run the evidence-check arms over the eval items.

Stdlib only. Enforces the stop rules in PREREG.md and PREREG-v2.md: cache and
resume, the budget cap, the pilot gate, and the per-arm error-rate stop.

    python3 run_eval.py --data data/fixture.jsonl --dry-run     # fake arm, no network
    python3 run_eval.py --pilot                                 # 1 item per tier, then a spend table
    python3 run_eval.py --arms jev,haiku --limit 5
    python3 run_eval.py --chat-transport openrouter              # haiku and opus over OpenRouter
    python3 run_eval.py                                         # the full v1 run, all four arms
    python3 run_eval.py --prompt v2                             # the v2 run: v2 data, arms, cap and out

Results: <out>/<arm>.jsonl, one line per item:
    {"item_id", "arm", "model", "prompt", "p", "cost_usd", "latency_s", "error", "raw", "attempts"}
An item already in the arm file with no error is skipped. An item that errored is
tried again; its line then carries the summed cost of every attempt, so the sum
of cost_usd over all files is the real spend. One results folder holds one
prompt version: a run with another version is refused (a line without "prompt"
is v1).

Exit codes: 0 done, 1 refused (mixed prompt versions), 2 the pilot extrapolates
above the cap, 3 a stop rule fired.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import threading
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from arms import ARMS, DEFAULT_PROMPT, DEFAULT_TRANSPORT, PROMPTS, TRANSPORTS, JevArm, make_chat_arm  # noqa: E402

# Defaults per prompt version. Each flag overrides its default.
DEFAULTS = {
    "v1": {
        "data": ["data/mechanical.jsonl", "data/decoy.jsonl", "data/semantic.jsonl"],
        "arms": "accept_all,jev,haiku,opus",
        "out": "results/runs",
        "budget": 8.00,  # PREREG.md
    },
    "v2": {
        "data": ["data/v2/mechanical.jsonl", "data/v2/decoy.jsonl", "data/v2/semantic.jsonl"],
        "arms": "accept_all,cite_script,jev,haiku,opus",
        "out": "results/v2/runs",
        "budget": 10.00,  # PREREG-v2.md
    },
}
DEFAULT_DATA = DEFAULTS["v1"]["data"]
DEFAULT_ARMS = DEFAULTS["v1"]["arms"]
DEFAULT_OUT = DEFAULTS["v1"]["out"]
DRY_RUN_OUT = "results/dry-run"  # keeps fake results out of the files metrics.py reads

# --- stop rules. Fixed in PREREG.md and PREREG-v2.md. -----------------------

BUDGET_USD = DEFAULTS["v1"]["budget"]
ERROR_RATE_MAX = 0.10  # stop an arm above this error rate ...
ERROR_RATE_MIN_ITEMS = 20  # ... once it has answered at least this many items in this run


# --- items -----------------------------------------------------------------


def resolve_data(specs: list, log=print) -> list:
    """Paths for each spec: a file or a glob, tried against cwd then this folder."""
    paths: list = []
    for spec in specs:
        found: list = []
        for base in (os.getcwd(), HERE):
            pattern = spec if os.path.isabs(spec) else os.path.join(base, spec)
            found = sorted(glob.glob(pattern)) if glob.has_magic(spec) else ([pattern] if os.path.isfile(pattern) else [])
            if found:
                break
        if not found:
            log(f"notice: skipping {spec}: no such file")
        for path in found:
            if os.path.abspath(path) not in paths:
                paths.append(os.path.abspath(path))
    return paths


def load_items(paths: list) -> list:
    items: list = []
    seen: set = set()
    for path in paths:
        with open(path) as fh:
            for lineno, line in enumerate(fh, 1):
                if not line.strip():
                    continue
                item = json.loads(line)
                item_id = item.get("id")
                if not item_id:
                    sys.exit(f"run_eval: {path}:{lineno} has no id")
                if item_id in seen:
                    sys.exit(f"run_eval: duplicate item id {item_id!r} ({path}:{lineno})")
                seen.add(item_id)
                items.append(item)
    return items


def limit_per_tier(items: list, n) -> list:
    """First n items of each tier, in file order."""
    if n is None:
        return list(items)
    counts: dict = {}
    kept = []
    for item in items:
        tier = item.get("tier", "")
        if counts.get(tier, 0) < n:
            counts[tier] = counts.get(tier, 0) + 1
            kept.append(item)
    return kept


def pilot_items(items: list) -> list:
    """One item per tier: the first with a non-empty diff, else the tier's first item.
    An empty diff is the cheapest possible call and would bias the spend estimate low."""
    chosen: dict = {}
    for item in items:
        tier = item.get("tier", "")
        has_diff = bool((item.get("diff") or "").strip())
        if tier not in chosen or (has_diff and not chosen[tier][1]):
            chosen[tier] = (item, has_diff)
    return [item for item, _ in chosen.values()]


# --- result files ----------------------------------------------------------


def _scan(path: str) -> tuple:
    """(records, unreadable line count, file ends cleanly)."""
    if not os.path.exists(path):
        return [], 0, True
    with open(path) as fh:
        text = fh.read()
    records, bad = [], 0
    for line in text.splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1  # a torn line from a crash mid-write; that call is redone
    return records, bad, text == "" or text.endswith("\n")


def read_records(path: str) -> list:
    return _scan(path)[0]


def compact(records: list) -> list:
    """One record per item: the latest attempt, carrying the summed cost of all attempts."""
    merged: dict = {}
    for rec in records:
        prev = merged.get(rec["item_id"])
        if prev is not None:
            rec = dict(rec)
            rec["cost_usd"] = (prev.get("cost_usd") or 0.0) + (rec.get("cost_usd") or 0.0)
            rec["attempts"] = prev.get("attempts", 1) + rec.get("attempts", 1)
        merged[rec["item_id"]] = rec
    return list(merged.values())


def write_records(path: str, records: list) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        for rec in records:
            fh.write(json.dumps(rec, default=str) + "\n")
    os.replace(tmp, path)


def load_arm(path: str, log=print) -> dict:
    """item_id -> record. Rewrites the file atomically when it holds repeats,
    an unreadable line, or no final newline, so the next append starts clean."""
    records, bad, clean_end = _scan(path)
    merged = compact(records)
    if bad or not clean_end or len(merged) != len(records):
        write_records(path, merged)
        if bad:
            log(f"notice: {path}: dropped {bad} unreadable line(s) from a torn write; those items are redone")
    return {rec["item_id"]: rec for rec in merged}


def spent_in(out_dir: str) -> float:
    total = 0.0
    for path in glob.glob(os.path.join(out_dir, "*.jsonl")):
        total += sum(rec.get("cost_usd") or 0.0 for rec in read_records(path))
    return total


def prompt_of(rec: dict) -> str:
    return rec.get("prompt") or "v1"  # v1 lines predate the field


def prompt_conflicts(out_dir: str, prompt: str) -> list:
    """Result files in out_dir holding another prompt version. Every *.jsonl
    counts, not only the arms of this run: one folder holds one version."""
    found = []
    for path in sorted(glob.glob(os.path.join(out_dir, "*.jsonl"))):
        other = sorted({prompt_of(rec) for rec in read_records(path)} - {prompt})
        if other:
            found.append(f"{path} holds prompt {', '.join(other)}")
    return found


class Budget:
    """Spend so far plus the estimated cost of calls in flight, under one lock."""

    def __init__(self, cap: float, spent: float = 0.0):
        self.cap = cap
        self.spent = spent
        self.reserved = 0.0
        self.lock = threading.Lock()

    def try_reserve(self, amount: float) -> bool:
        with self.lock:
            if self.spent + self.reserved + amount > self.cap:
                return False
            self.reserved += amount
            return True

    def settle(self, reserved: float, actual: float) -> None:
        with self.lock:
            self.reserved -= reserved
            self.spent += actual


# --- the run ---------------------------------------------------------------


def run_arm(arm, items: list, out_dir: str, budget: Budget, workers: int = 4, log=print, prompt=None) -> dict:
    prompt = prompt or getattr(arm, "prompt", DEFAULT_PROMPT)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{arm.name}.jsonl")
    conflicts = prompt_conflicts(out_dir, prompt)
    if conflicts:
        raise ValueError(f"refusing to mix prompt versions: {conflicts[0]}, this run is {prompt}; use a separate --out")
    done = load_arm(path, log)
    todo = [it for it in items if not (it["id"] in done and done[it["id"]].get("error") is None)]

    # Running mean and max cost per call, seeded with this arm's history.
    history = [rec for rec in done.values() if rec.get("cost_usd")]
    st = {
        "max_cost": max((rec["cost_usd"] / rec.get("attempts", 1) for rec in history), default=0.0),
        "in_flight": 0,
        "next": 0,
        "n": 0,
        "errors": 0,
        "spend": 0.0,
        "latency": 0.0,
        "cost_sum": sum(rec["cost_usd"] for rec in history),
        "cost_calls": sum(rec.get("attempts", 1) for rec in history),
        "stop": None,
    }
    lock = threading.Condition()

    def reserve_cost() -> float:
        """What one call may cost: the largest of the prior, the running mean, the max seen.
        Reserving this per call in flight keeps concurrent calls under the cap."""
        mean = st["cost_sum"] / st["cost_calls"] if st["cost_calls"] else 0.0
        return max(arm.est_cost_usd, mean, st["max_cost"])

    def worker() -> None:
        while True:
            with lock:
                # Until a real cost has landed the estimate is a guess, so one call at a time.
                while not st["stop"] and st["next"] < len(todo) and not st["cost_calls"] and st["in_flight"]:
                    lock.wait()
                if st["stop"] or st["next"] >= len(todo):
                    return
                item = todo[st["next"]]
                est = reserve_cost()
                if not budget.try_reserve(est):
                    st["stop"] = (
                        f"budget: stopping {arm.name} before {item['id']}: spent ${budget.spent:.4f}"
                        f" + in flight ${budget.reserved:.4f} + next ~${est:.4f} would exceed the ${budget.cap:.2f} cap"
                    )
                    return
                st["next"] += 1
                st["in_flight"] += 1
            pred = arm.predict(item)
            rec = {
                "item_id": item["id"],
                "arm": arm.name,
                "model": pred.model,
                "prompt": prompt,
                "p": pred.p,
                "cost_usd": pred.cost_usd,
                "latency_s": round(pred.latency_s, 3),
                "error": pred.error,
                "raw": pred.raw,
            }
            with lock:
                st["in_flight"] -= 1
                lock.notify_all()
                budget.settle(est, pred.cost_usd)
                with open(path, "a") as fh:
                    fh.write(json.dumps(rec, default=str) + "\n")
                st["n"] += 1
                st["errors"] += pred.error is not None
                st["spend"] += pred.cost_usd
                st["latency"] += pred.latency_s
                if pred.cost_usd:
                    st["cost_sum"] += pred.cost_usd
                    st["cost_calls"] += 1
                    st["max_cost"] = max(st["max_cost"], pred.cost_usd)
                if pred.error:
                    log(f"  error  {arm.name}  {item['id']}  {pred.error[:200]}")
                n, errors = st["n"], st["errors"]
                if not st["stop"] and n >= ERROR_RATE_MIN_ITEMS and errors / n > ERROR_RATE_MAX:
                    st["stop"] = f"error rate: stopping {arm.name}: {errors}/{n} items failed (over {ERROR_RATE_MAX:.0%})"

    threads = [threading.Thread(target=worker) for _ in range(max(1, min(workers, len(todo) or 1)))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    load_arm(path, log)  # compact retried items to one line each
    if st["stop"]:
        log(st["stop"])
    summary = {
        "arm": arm.name,
        "n": st["n"],
        "cached": len(items) - len(todo),
        "errors": st["errors"],
        "spend": st["spend"],
        "mean_latency": st["latency"] / st["n"] if st["n"] else 0.0,
        "stop": st["stop"],
    }
    log(
        f"summary  {arm.name:<10}  n={summary['n']}  cached={summary['cached']}  errors={summary['errors']}"
        f"  spend=${summary['spend']:.4f}  mean_latency={summary['mean_latency']:.2f}s"
    )
    return summary


def spend_table(arm_names: list, pilot: list, all_items: list, out_dir: str, log=print) -> float:
    """Extrapolate each arm's pilot cost per tier: the tier's per-item cost times the
    tier's size. A tier with no pilot record uses the arm's pilot mean. Returns the total."""
    sizes: dict = {}
    for item in all_items:
        sizes[item.get("tier", "")] = sizes.get(item.get("tier", ""), 0) + 1
    log(f"\npilot spend table ({len(pilot)} items, extrapolated per tier to {len(all_items)} items)")
    log("  tiers: " + ", ".join(f"{tier or '-'} {n}" for tier, n in sizes.items()))
    log(f"  {'arm':<10}  {'items':>5}  {'per item':>10}  {'full run':>10}")
    total = 0.0
    for name in arm_names:
        records = load_arm(os.path.join(out_dir, f"{name}.jsonl"), log)
        by_tier: dict = {}
        for item in pilot:
            if item["id"] in records:
                by_tier.setdefault(item.get("tier", ""), []).append(records[item["id"]].get("cost_usd") or 0.0)
        costs = [c for cs in by_tier.values() for c in cs]
        mean = sum(costs) / len(costs) if costs else 0.0
        full = sum((sum(by_tier[t]) / len(by_tier[t]) if by_tier.get(t) else mean) * n for t, n in sizes.items())
        total += full
        log(f"  {name:<10}  {len(costs):>5}  ${mean:>9.5f}  ${full:>9.4f}")
    log(f"  {'total':<10}  {'':>5}  {'':>10}  ${total:>9.4f}")
    return total


def _no_network(*args, **kwargs):
    raise RuntimeError("dry run: network access is disabled")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prompt", choices=list(PROMPTS), default=DEFAULT_PROMPT, help="prompt version (v2 adds the citation rule)")
    ap.add_argument("--data", nargs="+", default=None, help="item files or globs (default per prompt version)")
    ap.add_argument("--arms", default=None, help=f"comma list from {','.join(ARMS)} (default per prompt version)")
    ap.add_argument("--limit", type=int, default=None, help="first N items per tier")
    ap.add_argument("--dry-run", action="store_true", help="fake arm only, network disabled")
    ap.add_argument("--pilot", action="store_true", help="1 item per tier (first non-empty diff), then a spend table; exit 2 above the cap")
    ap.add_argument("--budget", type=float, default=None, help="spend cap in USD over all arm files (v1 8.00, v2 10.00)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=None, help=f"results folder (v1 {DEFAULT_OUT}, v2 {DEFAULTS['v2']['out']}, dry run {DRY_RUN_OUT})")
    ap.add_argument("--jev-model", default=None, help="override the jev arm's model id")
    ap.add_argument("--chat-transport", choices=TRANSPORTS, default=DEFAULT_TRANSPORT, help="how haiku and opus are called")
    args = ap.parse_args(argv)
    defaults = DEFAULTS[args.prompt]
    args.data = args.data or defaults["data"]
    args.arms = args.arms or defaults["arms"]
    args.budget = defaults["budget"] if args.budget is None else args.budget

    if args.dry_run:
        urllib.request.urlopen = _no_network
        arm_names = ["fake"]
    else:
        arm_names = [a.strip() for a in args.arms.split(",") if a.strip()]
    unknown = [a for a in arm_names if a not in ARMS]
    if unknown:
        sys.exit(f"run_eval: unknown arm(s) {', '.join(unknown)}; choose from {', '.join(ARMS)}")
    arms = {name: ARMS[name] for name in arm_names}
    if "jev" in arms:
        arms["jev"] = JevArm(model=args.jev_model or ARMS["jev"].model, prompt=args.prompt)
    for name in ("haiku", "opus"):
        if name in arms:
            arms[name] = make_chat_arm(name, args.chat_transport, args.prompt)

    if args.out:
        out_dir = os.path.abspath(args.out)
    elif args.dry_run:
        out_dir = os.path.join(HERE, DRY_RUN_OUT if args.prompt == "v1" else f"results/{args.prompt}/dry-run")
    else:
        out_dir = os.path.join(HERE, defaults["out"])
    conflicts = prompt_conflicts(out_dir, args.prompt)
    if conflicts:
        print(f"run_eval: refusing to mix prompt versions in one results folder (this run is {args.prompt}):")
        for line in conflicts:
            print(f"  {line}")
        print("use a separate --out for each prompt version")
        return 1

    all_items = load_items(resolve_data(args.data))
    if not all_items:
        sys.exit("run_eval: no items to run")
    items = pilot_items(all_items) if args.pilot else limit_per_tier(all_items, args.limit)

    budget = Budget(args.budget, spent_in(out_dir))
    print(
        f"run_eval: prompt {args.prompt}, {len(items)} of {len(all_items)} items, arms {','.join(arms)}, out {out_dir}"
        f", spent so far ${budget.spent:.4f} of ${budget.cap:.2f}"
    )
    stopped = False
    for arm in arms.values():
        summary = run_arm(arm, items, out_dir, budget, workers=args.workers, prompt=args.prompt)
        stopped = stopped or summary["stop"] is not None
    print(f"total spend over all arm files: ${spent_in(out_dir):.4f} of ${budget.cap:.2f}")

    if args.pilot:
        total = spend_table(list(arms), items, all_items, out_dir)
        if total > args.budget:
            print(f"pilot: the full run extrapolates to ${total:.2f}, above the ${args.budget:.2f} cap. Stop.")
            return 2
        print(f"pilot: the full run extrapolates to ${total:.2f}, inside the ${args.budget:.2f} cap.")
    return 3 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
