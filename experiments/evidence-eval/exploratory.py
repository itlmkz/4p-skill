#!/usr/bin/env python3
"""Exploratory cuts of the evidence-check eval. NOT preregistered.

    python3 exploratory.py [--runs results/runs] [--out results/exploratory.md]

The dataset audit found three reasons to read the preregistered verdict with
care. This script measures each one. It never changes a bar or the verdict in
report.md; it only adds cuts that PREREG.md did not plan.

1. Claim truth. wrong_line and wrong_file items are true claims with a bad
   citation, judged by a 5-line rule and a line-side convention the arms are
   never told. The claim-truth cut keeps true_added, true_removed, negated and
   fabricated, so it measures whether an arm checks the claim itself.
2. Length shortcut. In the semantic tier, claim length alone predicts the label
   at an AUROC near 0.81. An arm must beat that baseline to show it reads the diff.
3. Outside knowledge. Some false_outside_diff items are true in the real code.
   Decision cost is shown with and without that kind.
4. Clustering. Items share diffs. A bootstrap over commits gives wider, more
   honest intervals than the item bootstrap.
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from typing import Callable, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics import auroc, bootstrap_ci, decision_cost, effective_p, index_preds, paired_diff_ci  # noqa: E402
from report import load_items, load_runs  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TIER_FILES = [os.path.join(HERE, "data", f"{t}.jsonl") for t in ("mechanical", "decoy", "semantic")]
CLAIM_TRUTH = {"true_added", "true_removed", "negated", "fabricated"}
ARMS = ["jev", "haiku", "opus"]
SEED = 7
BOOT_N = 2000


def scores(items: Sequence[dict], preds: Sequence[dict]) -> list[float]:
    by_id = index_preds(preds)
    return [effective_p(by_id[it["id"]]) if it["id"] in by_id else 0.5 for it in items]


def fmt(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def fmt_ci(ci: Optional[tuple[float, float]]) -> str:
    return "n/a" if ci is None else f"[{ci[0]:.3f}, {ci[1]:.3f}]"


def cluster_ci(
    items: Sequence[dict], score: list[float], fn: Callable[[Sequence[bool], Sequence[float]], Optional[float]]
) -> Optional[tuple[float, float]]:
    """Percentile bootstrap that resamples whole commits, not items."""
    groups: dict[tuple[str, str], list[int]] = {}
    for i, it in enumerate(items):
        key = (it["source"]["repo"], it["source"]["commit"])
        groups.setdefault(key, []).append(i)
    keys = sorted(groups)
    rng = random.Random(SEED)
    vals: list[float] = []
    for _ in range(BOOT_N):
        pick = [i for k in rng.choices(keys, k=len(keys)) for i in groups[k]]
        v = fn([items[i]["label"] for i in pick], [score[i] for i in pick])
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    vals.sort()
    return vals[int(0.025 * (len(vals) - 1))], vals[int(0.975 * (len(vals) - 1))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", default=os.path.join(HERE, "results", "runs"))
    ap.add_argument("--out", default=os.path.join(HERE, "results", "exploratory.md"))
    args = ap.parse_args()

    items = load_items([p for p in TIER_FILES if os.path.exists(p)])
    runs, _ = load_runs(args.runs)
    missing = [a for a in ARMS if a not in runs]
    if missing:
        sys.exit(f"exploratory: no results for {', '.join(missing)} in {args.runs}")

    out: list[str] = [
        "# Exploratory cuts (not preregistered)",
        "",
        "These cuts were chosen after the dataset audit, so they are hypotheses for the next eval, "
        "not results. The preregistered verdict is in report.md and does not change.",
        "",
    ]

    # 1. claim truth
    cut = [it for it in items if it["tier"] == "mechanical" and it["kind"] in CLAIM_TRUTH]
    labels = [it["label"] for it in cut]
    s = {a: scores(cut, runs[a]) for a in ARMS}
    out += [
        "## 1. Claim truth, without citation strictness",
        "",
        f"Mechanical items of kind {', '.join(sorted(CLAIM_TRUTH))}: n = {len(cut)}, {sum(labels)} true.",
        "",
        "| Arm | AUROC | Item CI | Commit CI |",
        "|---|---|---|---|",
    ]
    for a in ARMS:
        out.append(
            f"| {a} | {fmt(auroc(labels, s[a]))} | {fmt_ci(bootstrap_ci(auroc, labels, s[a]))} "
            f"| {fmt_ci(cluster_ci(cut, s[a], auroc))} |"
        )
    for other in ("opus", "haiku"):
        d = paired_diff_ci(labels, s["jev"], s[other])
        if d:
            out.append(f"\nJev minus {other}: {d[0]:+.3f}, item CI [{d[1]:+.3f}, {d[2]:+.3f}].")
    out.append("")

    # 2. length shortcut
    sem = [it for it in items if it["tier"] == "semantic"]
    sl = [it["label"] for it in sem]
    length = [float(len(it["finding"]["claim"].split())) for it in sem]
    out += [
        "## 2. Semantic tier against a length-only baseline",
        "",
        f"n = {len(sem)}, {sum(sl)} true. The baseline scores each claim by its word count and reads no diff.",
        "",
        "| Scorer | AUROC | Item CI |",
        "|---|---|---|",
        f"| claim length only | {fmt(auroc(sl, length))} | {fmt_ci(bootstrap_ci(auroc, sl, length))} |",
    ]
    for a in ARMS:
        sa = scores(sem, runs[a])
        out.append(f"| {a} | {fmt(auroc(sl, sa))} | {fmt_ci(bootstrap_ci(auroc, sl, sa))} |")
    # Within one length band the shortcut cannot help, so AUROC there reads the diff.
    mid = sorted(length)[len(length) // 2]
    for name, keep in (("short claims", lambda n: n < mid), ("long claims", lambda n: n >= mid)):
        band = [i for i, n in enumerate(length) if keep(n)]
        bl = [sl[i] for i in band]
        row = [f"{a} {fmt(auroc(bl, [scores(sem, runs[a])[i] for i in band]))}" for a in ARMS]
        out.append(f"\nWithin {name} (n = {len(band)}, {sum(bl)} true, split at {mid:.0f} words): {', '.join(row)}.")
    out.append("")

    # 3. outside knowledge
    out += [
        "## 3. Decision cost at R = 10, with and without false_outside_diff",
        "",
        "| Arm | All items | Without false_outside_diff |",
        "|---|---|---|",
    ]
    rest = [it for it in items if it["kind"] != "false_outside_diff"]
    for a in ARMS:
        full = decision_cost([it["label"] for it in items], scores(items, runs[a]), 10)
        part = decision_cost([it["label"] for it in rest], scores(rest, runs[a]), 10)
        out.append(f"| {a} | {fmt(full['mean_cost'])} | {fmt(part['mean_cost'])} |")
    out.append("")

    # 4. clustering, on the cut that decides the preregistered bars
    md = [it for it in items if it["tier"] in ("mechanical", "decoy")]
    ml = [it["label"] for it in md]
    out += [
        "## 4. Item bootstrap against commit bootstrap, mechanical plus decoy",
        "",
        "| Arm | AUROC | Item CI | Commit CI |",
        "|---|---|---|---|",
    ]
    for a in ARMS:
        sa = scores(md, runs[a])
        out.append(f"| {a} | {fmt(auroc(ml, sa))} | {fmt_ci(bootstrap_ci(auroc, ml, sa))} | {fmt_ci(cluster_ci(md, sa, auroc))} |")
    out.append("")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        fh.write("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
