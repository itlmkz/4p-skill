#!/usr/bin/env python3
"""Exploratory cuts of the v2 evidence-check eval. NOT preregistered.

    python3 exploratory_v2.py [--runs results/v2/runs] [--out results/v2/exploratory.md]

The v2 dataset audit found three reasons to read the preregistered v2 verdict
with care. This script measures each one. It never changes a bar or the verdict
in results/v2/report.md.

1. Pointer baselines. A rule that reads only the cited file and line, and never
   the claim, is right on about 80% of the citation cut. H3's bar is 0.70. So
   each arm's citation accuracy is shown next to those baselines, and on the
   subset where the pointer alone cannot decide: near_line items plus the
   wrong_line items that cite_script passes.
2. One ambiguous pair. Pair p13 holds its true twin to a looser standard than
   its false twin. The semantic and claim-truth AUROCs are shown with and
   without it.
3. Where H1 and H2 come from. The mechanical claim-truth kinds are solvable by
   exact string search, so H1 and H2 are split by tier.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from arms import changed_lines  # noqa: E402
from metrics import (  # noqa: E402
    accuracy,
    auroc,
    cluster_bootstrap_ci,
    cluster_of,
    cluster_paired_diff_ci,
    effective_p,
    index_preds,
    V2_CUT_CITATION,
    V2_CUT_CLAIM,
    pair_win_rate,
    v2_in_cut,
    v2_runs,
)
from report import load_items, load_runs  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TIER_FILES = [os.path.join(HERE, "data", "v2", f"{t}.jsonl") for t in ("mechanical", "decoy", "semantic")]
ARMS = ["cite_script", "jev", "haiku", "opus", "cite_jev", "cite_haiku"]
MODEL_ARMS = ["jev", "haiku", "opus"]
AMBIGUOUS_PAIRS = {"p13"}


def scores(items: Sequence[dict], preds: Sequence[dict]) -> list[float]:
    by_id = index_preds(preds)
    return [effective_p(by_id[it["id"]]) if it["id"] in by_id else 0.5 for it in items]


def fmt(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def fmt_ci(ci) -> str:
    return "n/a" if not ci else f"[{ci[-2]:.3f}, {ci[-1]:.3f}]"


def in_visible_hunk(item: dict) -> bool:
    """The pointer-only baseline: the cited line is within 2 lines of a changed line of the cited file."""
    ev = item["finding"]["evidence"]
    lines = changed_lines(item["diff"]).get(ev.get("file", ""), set())
    return any(abs(ev.get("line", 0) - n) <= 2 for n in lines)


def auroc_row(name: str, items: Sequence[dict], runs: dict) -> list[str]:
    ys = [bool(it["label"]) for it in items]
    cl = [cluster_of(it) for it in items]
    out = []
    for a in MODEL_ARMS:
        s = scores(items, runs[a])
        out.append(f"{fmt(auroc(ys, s))} {fmt_ci(cluster_bootstrap_ci(auroc, ys, s, cl))}")
    return [name, str(len(items))] + out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", default=os.path.join(HERE, "results", "v2", "runs"))
    ap.add_argument("--out", default=os.path.join(HERE, "results", "v2", "exploratory.md"))
    args = ap.parse_args()

    items = load_items([p for p in TIER_FILES if os.path.exists(p)])
    file_runs, _ = load_runs(args.runs)
    runs = v2_runs(file_runs, items)
    missing = [a for a in ARMS if a not in runs]
    if missing:
        sys.exit(f"exploratory_v2: no results for {', '.join(missing)} in {args.runs}")

    out: list[str] = [
        "# v2 exploratory cuts (not preregistered)",
        "",
        "Chosen after the v2 dataset audit. They are context for the preregistered verdict in "
        "report.md, which does not change.",
        "",
    ]

    # 1. pointer baselines on the citation cut
    cite = [it for it in items if v2_in_cut(it, V2_CUT_CITATION, True)]
    cy = [bool(it["label"]) for it in cite]
    script_pass = scores(cite, runs["cite_script"])
    hard = [it for it, p in zip(cite, script_pass) if it["kind"] == "near_line" or (it["kind"] == "wrong_line" and p >= 0.5)]
    hy = [bool(it["label"]) for it in hard]
    hunk = [1.0 if in_visible_hunk(it) else 0.0 for it in cite]
    out += [
        "## 1. Citation cut against rules that never read the claim",
        "",
        f"Citation cut: n = {len(cite)}, {sum(cy)} true. Claim-required subset (near_line, plus wrong_line items "
        f"that cite_script passes): n = {len(hard)}, {sum(hy)} true.",
        "",
        "| Scorer | Accuracy, citation cut | Accuracy, claim-required subset |",
        "|---|---|---|",
        f"| accept everything | {fmt(accuracy(cy, [1.0] * len(cy)))} | {fmt(accuracy(hy, [1.0] * len(hy)))} |",
        f"| cited line within 2 of a changed line (pointer only) | {fmt(accuracy(cy, hunk))} | "
        f"{fmt(accuracy(hy, [1.0 if in_visible_hunk(it) else 0.0 for it in hard]))} |",
    ]
    for a in ARMS:
        out.append(f"| {a} | {fmt(accuracy(cy, scores(cite, runs[a])))} | {fmt(accuracy(hy, scores(hard, runs[a])))} |")
    out.append("")

    # 2. without the ambiguous pair
    sem = [it for it in items if it["tier"] == "semantic"]
    sem_clean = [it for it in sem if it.get("pair") not in AMBIGUOUS_PAIRS]
    ct = [it for it in items if v2_in_cut(it, V2_CUT_CLAIM, True)]
    ct_clean = [it for it in ct if it.get("pair") not in AMBIGUOUS_PAIRS]
    out += [
        "## 2. With and without the ambiguous pair p13",
        "",
        "AUROC with the commit-bootstrap interval.",
        "",
        "| Cut | n | jev | haiku | opus |",
        "|---|---|---|---|---|",
    ]
    for row in (
        auroc_row("semantic", sem, runs),
        auroc_row("semantic without p13", sem_clean, runs),
        auroc_row("claim-truth", ct, runs),
        auroc_row("claim-truth without p13", ct_clean, runs),
    ):
        out.append("| " + " | ".join(row) + " |")
    out.append("")

    # 3. H1 and H2 split by tier
    mech_ct = [it for it in ct if it["tier"] == "mechanical"]
    out += [
        "## 3. Where H1 and H2 come from",
        "",
        "| Cut | n | jev | haiku | opus |",
        "|---|---|---|---|---|",
    ]
    for row in (auroc_row("mechanical claim-truth kinds", mech_ct, runs), auroc_row("semantic", sem, runs)):
        out.append("| " + " | ".join(row) + " |")
    for name, sub in (("mechanical claim-truth kinds", mech_ct), ("semantic", sem)):
        ys = [bool(it["label"]) for it in sub]
        cl = [cluster_of(it) for it in sub]
        sj = scores(sub, runs["jev"])
        for other in ("opus", "haiku"):
            d = cluster_paired_diff_ci(ys, sj, scores(sub, runs[other]), cl)
            if d:
                out.append(f"\n{name}: jev minus {other} {d[0]:+.3f}, commit CI [{d[1]:+.3f}, {d[2]:+.3f}].")
    out.append("")

    # 4. pair win rate per false kind
    by_pair: dict[str, dict[str, dict]] = {}
    for it in sem:
        by_pair.setdefault(it["pair"], {})["t" if it["label"] else "f"] = it
    kinds = sorted({p["f"]["kind"] for p in by_pair.values() if "f" in p})
    out += [
        "## 4. Pair win rate per false kind",
        "",
        "Share of pairs where the arm gives the true twin a higher p than its false twin. A tie counts half.",
        "",
        "| False kind | pairs | " + " | ".join(MODEL_ARMS) + " |",
        "|---|---|" + "---|" * len(MODEL_ARMS),
    ]
    for kind in kinds:
        pairs = [p for p in by_pair.values() if "t" in p and "f" in p and p["f"]["kind"] == kind]
        cells = []
        for a in MODEL_ARMS:
            idx = index_preds(runs[a])
            pv = [
                (effective_p(idx[p["t"]["id"]]) if p["t"]["id"] in idx else 0.5,
                 effective_p(idx[p["f"]["id"]]) if p["f"]["id"] in idx else 0.5)
                for p in pairs
            ]
            cells.append(fmt(pair_win_rate(pv)))
        out.append(f"| {kind} | {len(pairs)} | " + " | ".join(cells) + " |")
    out.append("")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        fh.write("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
