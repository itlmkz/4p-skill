#!/usr/bin/env python3
"""Writes the evidence-check eval report as Markdown and as one standalone HTML page.

Reads items and per-arm predictions, scores them with metrics.py against the
bars in PREREG.md, and writes report.md plus report.html. No network.

    python3 report.py                                   # the three tier files, results/runs, results/
    python3 report.py --data data/mechanical.jsonl data/decoy.jsonl
    python3 report.py --data tests/fixtures/items.jsonl --runs tests/fixtures/runs --out /tmp/r

Items:       data/{mechanical,decoy,semantic}.jsonl by default (the run_eval.py set), one item
             per line (see PREREG.md). Globs work in --data; *.raw.jsonl is always skipped.
Predictions: <runs>/<arm>.jsonl, one {"item_id","arm","model","p","cost_usd","latency_s","error","raw"} per line.
"""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import hashlib
import html
import json
import os
import re
import shlex
import sys
from typing import Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import metrics as m  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PREREG = os.path.join(HERE, "PREREG.md")
ARM_ORDER = ["jev", "haiku", "opus", "accept_all", "fake"]  # fixed order: color follows the arm
TIERS = ["mechanical", "semantic", "decoy"]
DEFAULT_DATA = [os.path.join(HERE, "data", f"{t}.jsonl") for t in ("mechanical", "decoy", "semantic")]
NA = "not computable"
MAX_ERROR_CHARS = 200

# --- loading ----------------------------------------------------------------


def _read_jsonl(path: str) -> tuple[list[dict], int]:
    """Rows of a jsonl file plus the count of lines that did not parse."""
    rows, bad = [], 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            if isinstance(obj, dict):
                rows.append(obj)
            else:
                bad += 1
    return rows, bad


def expand_data(patterns: Sequence[str]) -> list[str]:
    paths: list[str] = []
    for pat in patterns:
        hits = sorted(glob.glob(pat)) if any(c in pat for c in "*?[") else [pat]
        paths += [p for p in hits if not p.endswith(".raw.jsonl")]
    return paths


def load_items(paths: Sequence[str]) -> list[dict]:
    """Items from every file, first occurrence of an id wins. Items without an id or label are dropped."""
    seen, items = set(), []
    for path in paths:
        rows, _ = _read_jsonl(path)
        for it in rows:
            if "id" in it and isinstance(it.get("label"), bool) and it["id"] not in seen:
                seen.add(it["id"])
                items.append(it)
    return items


def arm_sort_key(arm: str) -> tuple[int, str]:
    return (ARM_ORDER.index(arm) if arm in ARM_ORDER else len(ARM_ORDER), arm)


def load_runs(runs_dir: str) -> tuple[dict[str, list[dict]], dict[str, int]]:
    """arm -> predictions, from <runs_dir>/<arm>.jsonl. Also returns bad-line counts per arm."""
    runs: dict[str, list[dict]] = {}
    bad: dict[str, int] = {}
    for path in sorted(glob.glob(os.path.join(runs_dir, "*.jsonl"))):
        arm = os.path.basename(path)[: -len(".jsonl")]
        rows, nbad = _read_jsonl(path)
        runs[arm] = [r for r in rows if "item_id" in r]
        bad[arm] = nbad + len(rows) - len(runs[arm])
    return dict(sorted(runs.items(), key=lambda kv: arm_sort_key(kv[0]))), bad


def file_facts(path: str) -> dict:
    with open(path, "rb") as f:
        data = f.read()
    return {"path": path, "sha": hashlib.sha256(data).hexdigest()[:12], "lines": data.count(b"\n")}


def known_threats() -> list[str]:
    """The bullets under 'Known threats' in PREREG.md, each joined to one line."""
    try:
        with open(PREREG, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ["PREREG.md not found next to report.py."]
    mt = re.search(r"^## Known threats[^\n]*\n(.*?)(?=^## )", text, re.S | re.M)
    if not mt:
        return ["No 'Known threats' section found in PREREG.md."]
    bullets: list[str] = []
    for line in mt.group(1).splitlines():
        if line.startswith("- "):
            bullets.append(line[2:].strip())
        elif line.strip() and bullets:
            bullets[-1] += " " + line.strip()
    return bullets


# --- computing ----------------------------------------------------------------


def compute(items: list[dict], runs: dict[str, list[dict]]) -> dict:
    """Every number the report shows, in one dict. Nothing here formats text."""
    arms = [a for a in runs if runs[a]]
    summaries: dict = {}
    for arm in arms:
        for cut in (m.CUT_ALL, m.CUT_MECH_DECOY):
            summaries[(arm, cut)] = m.arm_summary(items, runs[arm], cut)
    hyps = m.evaluate_hypotheses(runs, items, summaries)
    ids = {it["id"] for it in items}

    per_tier, per_kind, costs, rocs, rel = {}, {}, {}, {}, {}
    tiers = [t for t in TIERS if any(it.get("tier") == t for it in items)]
    tiers += sorted({it.get("tier") for it in items} - set(TIERS) - {None})
    kinds = sorted({(it.get("tier"), it.get("kind")) for it in items}, key=lambda tk: (tiers.index(tk[0]) if tk[0] in tiers else 99, str(tk[1])))
    for arm in arms:
        by = m.index_preds(runs[arm])
        for t in tiers:
            sub = [it for it in items if it.get("tier") == t]
            ys, ps = [bool(it["label"]) for it in sub], m.scores_for(sub, by)
            per_tier[(arm, t)] = {"n": len(sub), "auroc": m.auroc(ys, ps), "acc": m.accuracy(ys, ps)}
        for t, k in kinds:
            sub = [it for it in items if it.get("tier") == t and it.get("kind") == k]
            ys, ps = [bool(it["label"]) for it in sub], m.scores_for(sub, by)
            per_kind[(arm, t, k)] = {"n": len(sub), "acc": m.accuracy(ys, ps), "mean_p": sum(ps) / len(ps) if ps else None}
        _, ys, ps = m.aligned(items, runs[arm])
        for R in m.COST_RATIOS:
            costs[(arm, R)] = m.decision_cost(ys, ps, R)
        rocs[arm] = m.roc_points(ys, ps)
        rel[arm] = m.reliability(ys, ps)

    kind_meta = {}
    for t, k in kinds:
        sub = [it for it in items if it.get("tier") == t and it.get("kind") == k]
        kind_meta[(t, k)] = {"n": len(sub), "n_true": sum(1 for it in sub if it["label"])}
    tier_meta = {t: {"n": sum(1 for it in items if it.get("tier") == t),
                     "n_true": sum(1 for it in items if it.get("tier") == t and it["label"])} for t in tiers}

    decoys = [it for it in items if it.get("tier") == "decoy"]
    errors = []
    for arm in arms:
        for p in runs[arm]:
            if p["item_id"] in ids and m.is_error(p):
                msg = str(p.get("error") or f"no usable p (got {p.get('p')!r})")
                errors.append({"arm": arm, "item_id": p["item_id"], "error": msg[:MAX_ERROR_CHARS]})
        # PREREG: an item the arm never answered counts as p = 0.5 and is listed too
        errors += [{"arm": arm, "item_id": i, "error": "not answered"} for i in m.not_answered(items, runs[arm])]
    orphans = {arm: sum(1 for p in runs[arm] if p["item_id"] not in ids) for arm in arms}
    return {
        "items": items, "runs": runs, "arms": arms, "summaries": summaries, "hypotheses": hyps,
        "tiers": tiers, "kinds": kinds, "tier_meta": tier_meta, "kind_meta": kind_meta,
        "per_tier": per_tier, "per_kind": per_kind, "costs": costs, "rocs": rocs, "rel": rel,
        "decoys": decoys, "errors": errors, "orphans": orphans,
        "cheapest": m.cheapest_passing_arm(runs, items, summaries) if arms else None,
    }


# --- plain-English reading ------------------------------------------------------
# STE100 style: simple words, active voice, 20 words or fewer per sentence.


def _f(x: Optional[float], nd: int = 2) -> str:
    return NA if x is None else f"{x:.{nd}f}"


def _cut_cell(row: dict) -> tuple[dict, str]:
    cut = m.CUT_MECH_DECOY if row[m.CUT_MECH_DECOY]["status"] in (m.PASS, m.FAIL) else m.CUT_ALL
    return row[cut], cut


def _sentence_for(row: dict) -> list[str]:
    cell, _ = _cut_cell(row)
    st, n, hid = cell["status"], cell["nums"], row["id"]
    if st == m.NOT_RUN:
        return [f"{hid} did not run: {cell['value']}."]
    word = "passes" if st == m.PASS else "fails"
    if hid == "H1":
        if st == m.PASS:
            return [f"H1 passes. Jev ranks supported findings above unsupported ones, AUROC {_f(n['auroc'], 3)}, lower bound {_f(n['lo'], 3)}."]
        return [f"H1 fails. Jev AUROC is {_f(n['auroc'], 3)} with lower bound {_f(n['lo'], 3)}. The bar is 0.80 and 0.70."]
    if hid == "H2":
        side = "inside" if st == m.PASS else "above"
        return [f"H2 {word}. The Jev calibration error is {_f(n['ece'], 3)}, {side} the 0.10 bar."]
    if hid == "H3":
        out = [f"H3 {word}. Jev AUROC is {_f(n['auroc'], 3)} and opus AUROC is {_f(n['auroc_opus'], 3)}."]
        ratio = n["ratio"]
        if ratio.startswith("cost ratio "):
            out.append(f"Jev costs {ratio[len('cost ratio '):]} of opus per item.")
        else:
            out.append(f"Jev costs {ratio} per item.")
        if not n["cost_ok"]:
            out.append("Jev cost is above the 1/20 bar.")
        if not n["auroc_ok"]:
            out.append("Jev falls more than 0.05 below opus.")
        return out
    if hid == "H4":
        if st == m.PASS:
            return [f"H4 passes. Jev beats haiku by {n['diff']:+.2f} AUROC, and the interval excludes 0."]
        if n["diff"] <= 0:
            return [f"H4 fails. Jev does not beat haiku. The AUROC difference is {n['diff']:+.2f}."]
        return [f"H4 fails. Jev leads haiku by {n['diff']:+.2f} AUROC, but the interval includes 0."]
    if hid == "H5":
        if st == m.PASS:
            return [f"H5 passes. Jev gives p of 0.2 or less on each of the {n['n']} empty diffs."]
        return [f"H5 fails. Jev gives p above 0.2 on {n['n_bad']} of {n['n']} empty diffs."]
    return [f"{hid} {word}."]


def reading(ctx: dict) -> list[str]:
    """The verdict paragraph as a list of sentences, generated from the numbers."""
    rows = {r["id"]: r for r in ctx["hypotheses"]}
    n_items, n_arms = len(ctx["items"]), len(ctx["arms"])
    out = [f"This report scores {n_arms} arm{'' if n_arms == 1 else 's'} on {n_items} finding{'' if n_items == 1 else 's'}."]
    if not n_arms:
        out.append("No arm has results yet, so every bar shows NOT RUN.")
        return out
    out.append("Each result uses the mechanical plus decoy cut when that cut is computable.")
    for arm in ctx["arms"]:
        k = ctx["summaries"][(arm, m.CUT_ALL)]["not_answered"]
        if k:
            out.append(f"{arm} did not answer {k} of {n_items} items. Each one counts as p = 0.5.")
    for hid in ("H1", "H2", "H3", "H4", "H5"):
        out += _sentence_for(rows[hid])
        if rows[hid]["conflict"]:
            st = rows[hid]["decided"].lower()
            out.append(f"{hid} differs between the two cuts. The mechanical plus decoy cut decides it: {st}.")
    d = {h: rows[h]["decided"] for h in rows}
    if d["H1"] == m.FAIL:
        out += ["The evidence gate stays an experiment.", "No product work follows from this run."]
    elif m.NOT_RUN in (d["H1"], d["H2"], d["H3"]):
        out.append("Some bars did not run, so this run gives no recommendation.")
    elif d["H1"] == d["H2"] == d["H3"] == m.PASS and d["H4"] == m.FAIL:
        out.append("A cheap model is enough here.")
        if ctx["cheapest"]:
            out.append(f"The cheapest arm that passes H1 to H3 is {ctx['cheapest']}. Use it, not Jev by name.")
    else:
        # H1 to H3 are PASS or FAIL here. A NOT RUN row is never read as a failure.
        failed = [h for h in ("H2", "H3", "H4", "H5") if d[h] == m.FAIL]
        topics = {"H4": "Jev against a cheap model", "H5": "decoy safety"}
        if failed:
            out.append(f"Jev passes H1 but fails {' and '.join(failed)}.")
            out.append("Read the failed rows before any product work.")
        elif all(v == m.PASS for v in d.values()):
            out.append("Jev passes all five bars. It can serve as the evidence gate.")
        for h in ("H4", "H5"):
            if d[h] == m.NOT_RUN:
                out.append(f"{h} did not run, so there is no recommendation on {topics[h]}.")
    return out


# --- shared formatting ------------------------------------------------------------


def fmt_ci(v: Optional[float], ci: Optional[tuple[float, float]]) -> str:
    if v is None:
        return NA
    return f"{v:.3f} [{ci[0]:.3f}, {ci[1]:.3f}]" if ci else f"{v:.3f}"


def fmt_usd(x: Optional[float]) -> str:
    if x is None:
        return NA
    return f"${x:.6f}" if 0 < x < 0.01 else f"${x:.4f}"


def fmt_s(x: Optional[float]) -> str:
    return NA if x is None else f"{x:.2f} s"


def arm_rows(ctx: dict) -> list[list[str]]:
    rows = []
    for arm in ctx["arms"]:
        s, md = ctx["summaries"][(arm, m.CUT_ALL)], ctx["summaries"][(arm, m.CUT_MECH_DECOY)]
        rows.append([arm, str(s["n"]), str(s["not_answered"]), fmt_ci(s["auroc"], s["auroc_ci"]), fmt_ci(md["auroc"], md["auroc_ci"]),
                     _f(s["brier"], 3), _f(s["ece"], 3), fmt_usd(s["cost_per_item"]), fmt_usd(s["cost_total"]),
                     fmt_s(s["latency_p50"]), str(s["errors"])])
    return rows


ARM_HEAD = ["Arm", "n", "Not answered", "AUROC [95% CI], all", "AUROC [95% CI], mech + decoy", "Brier", "ECE",
            "Cost per item", "Total cost", "p50 latency", "Errors"]


def tier_rows(ctx: dict) -> tuple[list[str], list[list[str]]]:
    head = ["Tier", "n (true)"] + [f"{a}: AUROC / acc" for a in ctx["arms"]]
    rows = []
    for t in ctx["tiers"]:
        meta = ctx["tier_meta"][t]
        cells = [t, f"{meta['n']} ({meta['n_true']})"]
        for a in ctx["arms"]:
            r = ctx["per_tier"][(a, t)]
            cells.append(f"{_f(r['auroc'], 3)} / {_f(r['acc'])}")
        rows.append(cells)
    return head, rows


def kind_rows(ctx: dict) -> tuple[list[str], list[list[str]]]:
    head = ["Tier", "Kind", "n (true)"] + [f"{a}: acc (mean p)" for a in ctx["arms"]]
    rows = []
    for t, k in ctx["kinds"]:
        meta = ctx["kind_meta"][(t, k)]
        cells = [str(t), str(k), f"{meta['n']} ({meta['n_true']})"]
        for a in ctx["arms"]:
            r = ctx["per_kind"][(a, t, k)]
            cells.append(f"{_f(r['acc'])} ({_f(r['mean_p'])})")
        rows.append(cells)
    return head, rows


COST_HEAD = ["Arm", "R", "Threshold t", "Mean cost per item", "Reject precision", "Reject recall", "Rejected"]


def cost_rows(ctx: dict) -> list[list[str]]:
    rows = []
    for R in m.COST_RATIOS:
        for a in ctx["arms"]:
            c = ctx["costs"][(a, R)]
            if c is None:
                rows.append([a, str(R), NA, NA, NA, NA, NA])
                continue
            rows.append([a, str(R), f"{c['threshold']:.3f}", f"{c['mean_cost']:.3f}", _f(c["precision"]),
                         _f(c["recall"]), f"{c['n_reject']} of {c['n']}"])
    return rows


def decoy_rows(ctx: dict) -> tuple[list[str], list[list[str]]]:
    head = ["Item", "Kind", "Label"] + list(ctx["arms"]) + ["H5 (jev)"]
    by = {a: m.index_preds(ctx["runs"][a]) for a in ctx["arms"]}
    rows = []
    for it in ctx["decoys"]:
        cells = [it["id"], str(it.get("kind")), "true" if it["label"] else "false"]
        for a in ctx["arms"]:
            p = by[a].get(it["id"])
            cells.append("not answered (0.50)" if p is None else "error (0.50)" if m.is_error(p) else f"{m.effective_p(p):.2f}")
        if it.get("kind") != "empty_diff":
            cells.append("n/a")
        elif "jev" not in by:
            cells.append(m.NOT_RUN)
        else:
            cells.append(m.PASS if m.scores_for([it], by["jev"])[0] <= m.H5_MAX_P else m.FAIL)
        rows.append(cells)
    return head, rows


def commands(ctx: dict, args: argparse.Namespace) -> list[str]:
    report_cmd = "python3 report.py " + " ".join(shlex.quote(a) for a in sys.argv[1:])
    return [
        "cd experiments/evidence-eval",
        "python3 build_dataset.py            # mechanical and decoy tiers, seed 7",
        "python3 run_eval.py --dry-run       # fake arm, no network, writes results/dry-run",
        "python3 run_eval.py --pilot         # 1 item per tier, spend table, stops above the cap",
        "python3 run_eval.py                 # the paid run into results/runs, budget cap in the runner",
        report_cmd.strip(),
        "python3 tests/metrics.test.py       # pins every metric to a hand-computed value",
    ]


# --- markdown ------------------------------------------------------------------------


def _md_cell(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def md_table(head: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(_md_cell(h) for h in head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(_md_cell(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def render_md(ctx: dict, meta: dict) -> str:
    L: list[str] = ["# Evidence Check Eval", ""]
    L.append(f"Generated {meta['when']}. {len(ctx['items'])} items, arms: {', '.join(ctx['arms']) or 'none'}.")
    L += ["", "## Verdict", "", " ".join(reading(ctx)), ""]
    hrows = []
    for r in ctx["hypotheses"]:
        hrows.append([r["id"], r["hypothesis"], r["bar"],
                      f"{r['all']['status']}: {r['all']['value']}",
                      f"{r['mech_decoy']['status']}: {r['mech_decoy']['value']}",
                      r["decided"] + (" (cuts differ)" if r["conflict"] else "")])
    L.append(md_table(["ID", "Hypothesis", "Bar", "All items", "Mechanical + decoy", "Decided"], hrows))
    L += ["", "The mechanical + decoy cut is labeled by a script. PREREG.md says it decides a conflict.", ""]
    L += ["## Per-arm results", "", md_table(ARM_HEAD, arm_rows(ctx)), ""]
    L.append("n is the number answered. Errors and unanswered items count as p = 0.5. Cost and latency are over the answered items.")
    if any(ctx["orphans"].values()):
        L.append("Predictions for unknown item ids (ignored): " + ", ".join(f"{a} {n}" for a, n in ctx["orphans"].items() if n) + ".")
    h, rows = tier_rows(ctx)
    L += ["", "## Per tier", "", md_table(h, rows), ""]
    h, rows = kind_rows(ctx)
    L += ["## Per kind", "", "Most kinds hold one label only, so AUROC is not computable there. "
          "Accuracy reads p >= 0.5 as supported.", "", md_table(h, rows), ""]
    L += ["## Decision cost", "", "Reject when p < t = 1 / (1 + R). Rejecting a true finding costs R; "
          "accepting a false finding costs 1. Precision and recall are of reject.", "",
          md_table(COST_HEAD, cost_rows(ctx)), ""]
    h, rows = decoy_rows(ctx)
    L += ["## Decoy behavior (H5)", "", "H5 needs p <= 0.2 from jev on every empty_diff item.", ""]
    L += [md_table(h, rows) if rows else "No decoy items in the data.", ""]
    L += ["## Errors", ""]
    if ctx["errors"]:
        L.append(md_table(["Arm", "Item", "Error"], [[e["arm"], e["item_id"], e["error"]] for e in ctx["errors"]]))
    else:
        L.append("No errors.")
    L += ["", "## Known threats (from PREREG.md)", ""] + [f"- {t}" for t in known_threats()]
    L += ["", "## Reproduce", "", "```sh"] + commands(ctx, meta["args"]) + ["```", ""]
    L += ["Inputs:", ""] + [f"- `{f['path']}` sha256 {f['sha']}, {f['lines']} lines" for f in meta["files"]]
    return "\n".join(L) + "\n"


# --- html ---------------------------------------------------------------------------------

E = html.escape

CSS = """
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --surface-2: #f0efec;
  --ink: #0b0b0b; --ink-2: #52514e; --muted: #6f6d68;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.12);
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #b07800; --s5: #e87ba4; --s6: #008300;
  --good-bg: #e2f3e2; --good-ink: #0b5d0b; --bad-bg: #fbe4e4; --bad-ink: #9b1c1c;
  --nr-bg: #ecebe7; --nr-ink: #52514e; --bar: #86b6ef; --code-bg: #f0efec;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --surface-2: #242422;
    --ink: #f0efec; --ink-2: #c3c2b7; --muted: #9a988f;
    --grid: #2c2c2a; --axis: #4a4a46; --border: rgba(255,255,255,0.12);
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181; --s6: #0ca30c;
    --good-bg: #12301a; --good-ink: #8fe08f; --bad-bg: #3a1616; --bad-ink: #ffa3a3;
    --nr-bg: #2a2a28; --nr-ink: #c3c2b7; --bar: #256abf; --code-bg: #242422;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --surface-2: #242422;
  --ink: #f0efec; --ink-2: #c3c2b7; --muted: #9a988f;
  --grid: #2c2c2a; --axis: #4a4a46; --border: rgba(255,255,255,0.12);
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500; --s5: #d55181; --s6: #0ca30c;
  --good-bg: #12301a; --good-ink: #8fe08f; --bad-bg: #3a1616; --bad-ink: #ffa3a3;
  --nr-bg: #2a2a28; --nr-ink: #c3c2b7; --bar: #256abf; --code-bg: #242422;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1040px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 1.6rem; margin: 0 0 4px; }
h2 { font-size: 1.15rem; margin: 36px 0 10px; padding-top: 8px; border-top: 1px solid var(--grid); }
h3 { font-size: 0.95rem; margin: 0 0 6px; }
p { margin: 8px 0; max-width: 72ch; }
.meta, .note { color: var(--ink-2); font-size: 0.9rem; }
.reading { background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 12px 14px; max-width: none; }
.tw { overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 10px 0;
  border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
/* A wide table scrolls inside its wrapper, so a keyboard user must be able to focus it. */
.tw:focus-visible, pre:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px; }
table { border-collapse: collapse; width: 100%; font-size: 0.86rem; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--grid); vertical-align: top; }
th { color: var(--ink-2); font-weight: 600; background: var(--surface-2); }
tr:last-child td { border-bottom: 0; }
.tw td:first-child { white-space: nowrap; }
td.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
table.verdict td { min-width: 9rem; }
table.verdict td:first-child { min-width: 0; font-weight: 600; }
.badge { display: inline-block; font-weight: 700; font-size: 0.75rem; letter-spacing: 0.02em;
  padding: 1px 7px; border-radius: 999px; white-space: nowrap; }
.PASS { background: var(--good-bg); color: var(--good-ink); }
.FAIL { background: var(--bad-bg); color: var(--bad-ink); }
.NOTRUN { background: var(--nr-bg); color: var(--nr-ink); }
.val { display: block; color: var(--ink-2); margin-top: 3px; }
.charts { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px; min-width: 0; }
.roc { max-width: 460px; }
svg { display: block; width: 100%; height: auto; }
svg text { fill: var(--muted); font: 11px system-ui, -apple-system, "Segoe UI", sans-serif; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin: 8px 0 0; padding: 0; list-style: none; font-size: 0.86rem; }
.legend li { display: flex; align-items: center; gap: 6px; }
.sw { width: 18px; height: 3px; border-radius: 2px; display: inline-block; }
.sw.dash { background: repeating-linear-gradient(90deg, currentColor 0 4px, transparent 4px 7px) !important; }
ul.threats li { margin: 6px 0; max-width: 80ch; }
pre { background: var(--code-bg); border: 1px solid var(--border); border-radius: 8px; padding: 12px;
  overflow-x: auto; font-size: 0.82rem; line-height: 1.45; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.88em; }
p code, li code { background: var(--code-bg); padding: 0 4px; border-radius: 4px; overflow-wrap: anywhere; }
"""


def arm_color(arm: str, arms: list[str]) -> str:
    # The slot follows the arm's place in ARM_ORDER, never its rank, so colors stay put across runs.
    slot = ARM_ORDER.index(arm) if arm in ARM_ORDER else len(ARM_ORDER) + sorted(a for a in arms if a not in ARM_ORDER).index(arm)
    return f"var(--s{slot % 6 + 1})"


def badge(status: str) -> str:
    return f'<span class="badge {status.replace(" ", "")}">{E(status)}</span>'


def h_table(head: list[str], rows: list[list[str]], num_from: int = 1, cls: str = "") -> str:
    """HTML table in a scroll wrapper. Cells are escaped here; columns from num_from on are numeric."""
    th = "".join(f"<th scope=\"col\">{E(h)}</th>" for h in head)
    body = []
    for r in rows:
        tds = []
        for i, c in enumerate(r):
            if c in (m.PASS, m.FAIL, m.NOT_RUN):
                tds.append(f"<td>{badge(c)}</td>")
            else:
                attr = ' class="num"' if i >= num_from else ""
                tds.append(f"<td{attr}>{E(str(c))}</td>")
        body.append("<tr>" + "".join(tds) + "</tr>")
    return f'<div class="tw" tabindex="0" role="region" aria-label="Table, scrolls sideways"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def inline_md(s: str) -> str:
    """Escape, then turn `code` and **bold** from PREREG into tags."""
    s = E(s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)


def svg_axes(x0: float, y0: float, w: float, h: float, xlab: str, ylab: str) -> str:
    """Gridlines at 0, 0.5, 1 with tick labels, for a unit square plot at (x0, y0) of size w x h."""
    parts = []
    for v in (0.0, 0.25, 0.5, 0.75, 1.0):
        x, y = x0 + v * w, y0 + h - v * h
        parts.append(f'<line x1="{x:.1f}" y1="{y0}" x2="{x:.1f}" y2="{y0 + h}" stroke="var(--grid)" stroke-width="1"/>')
        parts.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x0 + w}" y2="{y:.1f}" stroke="var(--grid)" stroke-width="1"/>')
        if v in (0.0, 0.5, 1.0):
            parts.append(f'<text x="{x:.1f}" y="{y0 + h + 14}" text-anchor="middle">{v:g}</text>')
            parts.append(f'<text x="{x0 - 6}" y="{y + 4:.1f}" text-anchor="end">{v:g}</text>')
    parts.append(f'<rect x="{x0}" y="{y0}" width="{w}" height="{h}" fill="none" stroke="var(--axis)" stroke-width="1"/>')
    parts.append(f'<text x="{x0 + w / 2}" y="{y0 + h + 30}" text-anchor="middle">{E(xlab)}</text>')
    parts.append(f'<text transform="translate({x0 - 30} {y0 + h / 2}) rotate(-90)" text-anchor="middle">{E(ylab)}</text>')
    return "".join(parts)


def svg_roc(ctx: dict) -> str:
    x0, y0, w, h = 44, 10, 260, 260
    parts = [f'<svg viewBox="0 0 316 314" role="img" aria-label="ROC curves, all items">',
             svg_axes(x0, y0, w, h, "False positive rate", "True positive rate"),
             f'<line x1="{x0}" y1="{y0 + h}" x2="{x0 + w}" y2="{y0}" stroke="var(--muted)" stroke-dasharray="3 4" stroke-width="1"/>']
    legend = []
    for arm in ctx["arms"]:
        pts = ctx["rocs"].get(arm)
        s = ctx["summaries"][(arm, m.CUT_ALL)]
        color = arm_color(arm, ctx["arms"])
        dash = arm == "accept_all"
        legend.append(f'<li><span class="sw{" dash" if dash else ""}" style="background:{color};color:{color}"></span>'
                      f'{E(arm)} <span class="note">AUROC {E(_f(s["auroc"], 3))}</span></li>')
        if not pts:
            continue
        coords = " ".join(f"{x0 + fx * w:.1f},{y0 + h - ty * h:.1f}" for fx, ty in pts)
        dash_attr = ' stroke-dasharray="6 4"' if dash else ""
        parts.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round"'
                     f'{dash_attr}><title>{E(arm)}: AUROC {E(_f(s["auroc"], 3))}</title></polyline>')
    parts.append("</svg>")
    return ('<div class="card roc"><h3>ROC curves, all items</h3>' + "".join(parts)
            + '<ul class="legend">' + "".join(legend) + '<li><span class="sw dash" style="color:var(--muted)"></span>chance</li></ul></div>')


def svg_reliability(ctx: dict, arm: str) -> str:
    x0, y0, w, h = 44, 10, 200, 200
    table = ctx["rel"].get(arm) or []
    color = arm_color(arm, ctx["arms"])
    parts = [f'<svg viewBox="0 0 256 254" role="img" aria-label="Reliability diagram for {E(arm)}">',
             svg_axes(x0, y0, w, h, "Mean p in bin", "Share supported")]
    for r in table:
        if not r["n"]:
            continue
        bx, bw = x0 + r["lo"] * w + 1, (r["hi"] - r["lo"]) * w - 2
        bh = r["frac_true"] * h
        parts.append(f'<rect x="{bx:.1f}" y="{y0 + h - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="2" fill="{color}" fill-opacity="0.55">'
                     f'<title>p {r["lo"]:.1f} to {r["hi"]:.1f}: n {r["n"]}, mean p {r["mean_p"]:.2f}, share supported {r["frac_true"]:.2f}</title></rect>')
        cx, cy = x0 + r["mean_p"] * w, y0 + h - r["frac_true"] * h
        parts.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.5" fill="{color}" stroke="var(--surface)" stroke-width="1.5"/>')
    parts.append(f'<line x1="{x0}" y1="{y0 + h}" x2="{x0 + w}" y2="{y0}" stroke="var(--ink-2)" stroke-dasharray="3 4" stroke-width="1"/>')
    parts.append("</svg>")
    s = ctx["summaries"][(arm, m.CUT_ALL)]
    return (f'<div class="card"><h3>{E(arm)} <span class="note">ECE {E(_f(s["ece"], 3))}, n {s["n"]}</span></h3>'
            + "".join(parts) + "</div>")


def render_html(ctx: dict, meta: dict) -> str:
    B: list[str] = []
    B.append("<h1>Evidence Check Eval</h1>")
    B.append(f'<p class="meta">Generated {E(meta["when"])}. {len(ctx["items"])} items. '
             f'Arms: {E(", ".join(ctx["arms"]) or "none")}.</p>')

    B.append('<h2 id="verdict">Verdict</h2>')
    B.append(f'<p class="reading">{E(" ".join(reading(ctx)))}</p>')
    rows = []
    for r in ctx["hypotheses"]:
        cells = [f"<td>{E(r['id'])}</td>", f"<td>{E(r['hypothesis'])}<span class=\"val\">Bar: {E(r['bar'])}</span></td>"]
        for cut in (m.CUT_ALL, m.CUT_MECH_DECOY):
            c = r[cut]
            cells.append(f'<td>{badge(c["status"])}<span class="val">{E(c["value"])}</span></td>')
        note = '<span class="val">cuts differ; mech + decoy decides</span>' if r["conflict"] else ""
        cells.append(f"<td>{badge(r['decided'])}{note}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    head = "".join(f'<th scope="col">{h}</th>' for h in ("ID", "Hypothesis", "All items", "Mechanical + decoy", "Decided"))
    B.append(f'<div class="tw" tabindex="0" role="region" aria-label="Table, scrolls sideways"><table class="verdict"><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
    B.append('<p class="note">The mechanical + decoy cut is labeled by a script. PREREG.md says it decides a conflict.</p>')

    B.append('<h2 id="arms">Per-arm results</h2>')
    B.append(h_table(ARM_HEAD, arm_rows(ctx)))
    B.append('<p class="note">n is the number answered. Errors and unanswered items count as p = 0.5. Cost and latency are over the answered items.</p>')
    if any(ctx["orphans"].values()):
        B.append('<p class="note">Predictions for unknown item ids (ignored): '
                 + E(", ".join(f"{a} {n}" for a, n in ctx["orphans"].items() if n)) + ".</p>")
    if ctx["arms"]:
        B.append(svg_roc(ctx))
        B.append("<h3 style=\"margin-top:16px\">Reliability, all items</h3>")
        B.append('<p class="note">Bars show the share of supported findings per p bin. Dots sit at the mean p of the bin. '
                 "A calibrated arm keeps its dots on the dashed line.</p>")
        B.append('<div class="charts">' + "".join(svg_reliability(ctx, a) for a in ctx["arms"]) + "</div>")

    B.append('<h2 id="tiers">Per tier</h2>')
    h, rows = tier_rows(ctx)
    B.append(h_table(h, rows))
    B.append('<h2 id="kinds">Per kind</h2>')
    B.append('<p class="note">Most kinds hold one label only, so AUROC is not computable there. Accuracy reads p &gt;= 0.5 as supported.</p>')
    h, rows = kind_rows(ctx)
    B.append(h_table(h, rows, num_from=2))

    B.append('<h2 id="cost">Decision cost</h2>')
    B.append('<p class="note">Reject when p &lt; t = 1 / (1 + R). Rejecting a true finding costs R; accepting a false finding costs 1. '
             "Precision and recall are of reject.</p>")
    B.append(h_table(COST_HEAD, cost_rows(ctx)))

    B.append('<h2 id="decoys">Decoy behavior (H5)</h2>')
    B.append('<p class="note">H5 needs p &lt;= 0.2 from jev on every empty_diff item.</p>')
    h, rows = decoy_rows(ctx)
    B.append(h_table(h, rows, num_from=3) if rows else "<p>No decoy items in the data.</p>")

    B.append('<h2 id="errors">Errors</h2>')
    if ctx["errors"]:
        B.append(h_table(["Arm", "Item", "Error"], [[e["arm"], e["item_id"], e["error"]] for e in ctx["errors"]], num_from=99))
    else:
        B.append("<p>No errors.</p>")

    B.append('<h2 id="threats">Known threats (from PREREG.md)</h2>')
    B.append('<ul class="threats">' + "".join(f"<li>{inline_md(t)}</li>" for t in known_threats()) + "</ul>")

    B.append('<h2 id="reproduce">Reproduce</h2>')
    B.append('<pre tabindex="0" aria-label="Commands, scrolls sideways"><code>' + E("\n".join(commands(ctx, meta["args"]))) + "</code></pre>")
    B.append('<ul class="threats">' + "".join(
        f"<li><code>{E(f['path'])}</code> sha256 {E(f['sha'])}, {f['lines']} lines</li>" for f in meta["files"]) + "</ul>")

    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<title>Evidence Check Eval</title>\n"
            f"<style>{CSS}</style>\n</head>\n<body>\n<main>\n" + "\n".join(B) + "\n</main>\n</body>\n</html>\n")


# --- main ---------------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Write report.md and report.html for the evidence-check eval.")
    ap.add_argument("--data", nargs="+", default=None,
                    help="item files or globs (default data/mechanical, decoy and semantic .jsonl; *.raw.jsonl is skipped)")
    ap.add_argument("--runs", default=os.path.join(HERE, "results", "runs"), help="directory of <arm>.jsonl files")
    ap.add_argument("--out", default=os.path.join(HERE, "results"), help="directory for report.md and report.html")
    args = ap.parse_args(argv)

    if args.data is None:  # default set: a tier file that does not exist yet is skipped, with a note
        paths = [p for p in DEFAULT_DATA if os.path.isfile(p)]
        for p in DEFAULT_DATA:
            if p not in paths:
                print(f"report.py: {os.path.relpath(p, HERE)} not found, skipped", file=sys.stderr)
        missing = [] if paths else DEFAULT_DATA
    else:
        paths = expand_data(args.data)
        missing = [p for p in paths if not os.path.isfile(p)] or ([] if paths else list(args.data))
    if missing:
        print(f"report.py: no item file at {', '.join(missing)}", file=sys.stderr)
        return 2
    items = load_items(paths)
    runs, bad = load_runs(args.runs) if os.path.isdir(args.runs) else ({}, {})
    for arm, n in bad.items():
        if n:
            print(f"report.py: skipped {n} unreadable lines in {arm}.jsonl", file=sys.stderr)

    ctx = compute(items, runs)
    run_files = [os.path.join(args.runs, f"{a}.jsonl") for a in runs]
    meta = {
        "when": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "args": args,
        "files": [file_facts(p) for p in paths + run_files],
    }
    os.makedirs(args.out, exist_ok=True)
    md_path, html_path = os.path.join(args.out, "report.md"), os.path.join(args.out, "report.html")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_md(ctx, meta))
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_html(ctx, meta))
    print(f"wrote {md_path}")
    print(f"wrote {html_path}")
    for r in ctx["hypotheses"]:
        print(f"  {r['id']}  {r['decided']:<8} {r[m.CUT_MECH_DECOY]['value'] if r[m.CUT_MECH_DECOY]['status'] != m.NOT_RUN else r[m.CUT_ALL]['value']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
