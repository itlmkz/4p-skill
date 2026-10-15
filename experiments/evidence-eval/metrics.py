#!/usr/bin/env python3
"""Metrics for the evidence-check eval. Stdlib only.

Every function takes plain lists: `labels` are bools (True = the finding is
supported), `scores` are each arm's probability `p` that it is supported.
Degenerate input (no items, one class only) returns None, never a fake number.

    from metrics import auroc, bootstrap_ci, brier, ece, decision_cost
    auroc([True, True, False, False], [0.9, 0.4, 0.4, 0.1])   # 0.875

    python3 metrics.py      # tiny self-demo on the 4-item tie case

The bars and cuts come from PREREG.md. `evaluate_hypotheses` turns predictions
into the H1 to H5 rows the report prints. The v2 section at the end follows
PREREG-v2.md: commit-level bootstrap, derived split arms, M1, M2 and H1 to H6
(`evaluate_v2`).
"""

from __future__ import annotations

import math
import random
import statistics
from typing import Callable, Optional, Sequence

# --- settings fixed by PREREG.md. Do not change after a paid run. ----------

BOOT_N = 2000
BOOT_SEED = 7
ECE_BINS = 10
COST_RATIOS = (5, 10, 20)
ERROR_P = 0.5  # an item an arm failed to answer counts as this
ACCURACY_AT = 0.5  # p at or above this reads as "supported" for accuracy

H1_AUROC, H1_LOWER = 0.80, 0.70
H2_ECE = 0.10
H3_MARGIN, H3_COST_FACTOR = 0.05, 20.0
H5_MAX_P = 0.2

CUT_ALL = "all"
CUT_MECH_DECOY = "mech_decoy"
CUT_TIERS = {CUT_ALL: None, CUT_MECH_DECOY: {"mechanical", "decoy"}}
CUT_NAMES = {CUT_ALL: "all items", CUT_MECH_DECOY: "mechanical + decoy"}

PASS, FAIL, NOT_RUN = "PASS", "FAIL", "NOT RUN"

Num = Optional[float]


# --- ranking ----------------------------------------------------------------


def auroc(labels: Sequence[bool], scores: Sequence[float]) -> Num:
    """Area under the ROC curve via Mann-Whitney U, ties counted as half.

    AUROC = (R_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg), where R_pos is
    the sum of mid-ranks of the positive items. Mid-ranks give a tied pair 0.5.
    """
    n = len(labels)
    n_pos = sum(1 for y in labels if y)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    order = sorted(range(n), key=lambda i: scores[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        mid = (i + j) / 2 + 1  # ranks are 1-based
        for k in range(i, j + 1):
            ranks[order[k]] = mid
        i = j + 1
    r_pos = sum(r for r, y in zip(ranks, labels) if y)
    return (r_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def roc_points(labels: Sequence[bool], scores: Sequence[float]) -> Optional[list[tuple[float, float]]]:
    """(fpr, tpr) points from (0, 0) to (1, 1), one step per distinct score.

    Tied scores move in one diagonal step, so the trapezoid area equals auroc().
    """
    n_pos = sum(1 for y in labels if y)
    n_neg = len(labels) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    pairs = sorted(zip(scores, labels), key=lambda t: -t[0])
    points = [(0.0, 0.0)]
    tp = fp = 0
    i = 0
    while i < len(pairs):
        s = pairs[i][0]
        while i < len(pairs) and pairs[i][0] == s:
            if pairs[i][1]:
                tp += 1
            else:
                fp += 1
            i += 1
        points.append((fp / n_neg, tp / n_pos))
    return points


def _quantile(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolation quantile of an already sorted list."""
    pos = q * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def bootstrap_ci(
    fn: Callable[[Sequence[bool], Sequence[float]], Num],
    labels: Sequence[bool],
    scores: Sequence[float],
    n: int = BOOT_N,
    seed: int = BOOT_SEED,
    alpha: float = 0.05,
) -> Optional[tuple[float, float]]:
    """Percentile bootstrap interval of fn(labels, scores).

    Resamples items with replacement. A resample where fn returns None (one
    class only) is skipped. Returns None when no resample is computable.
    """
    if not labels or fn(labels, scores) is None:
        return None
    rng = random.Random(seed)
    idx = range(len(labels))
    vals: list[float] = []
    for _ in range(n):
        pick = rng.choices(idx, k=len(labels))
        v = fn([labels[i] for i in pick], [scores[i] for i in pick])
        if v is not None:
            vals.append(v)
    if not vals:
        return None
    vals.sort()
    return (_quantile(vals, alpha / 2), _quantile(vals, 1 - alpha / 2))


def paired_diff_ci(
    labels: Sequence[bool],
    a: Sequence[float],
    b: Sequence[float],
    fn: Callable[[Sequence[bool], Sequence[float]], Num] = auroc,
    n: int = BOOT_N,
    seed: int = BOOT_SEED,
    alpha: float = 0.05,
) -> Optional[tuple[float, float, float]]:
    """fn(a) - fn(b) on the same items, with a bootstrap that resamples items jointly.

    Returns (diff, lower, upper), or None when the point diff is not computable.
    """
    fa, fb = fn(labels, a), fn(labels, b)
    if fa is None or fb is None:
        return None
    rng = random.Random(seed)
    idx = range(len(labels))
    vals: list[float] = []
    for _ in range(n):
        pick = rng.choices(idx, k=len(labels))
        ys = [labels[i] for i in pick]
        va, vb = fn(ys, [a[i] for i in pick]), fn(ys, [b[i] for i in pick])
        if va is not None and vb is not None:
            vals.append(va - vb)
    if not vals:
        return None
    vals.sort()
    return (fa - fb, _quantile(vals, alpha / 2), _quantile(vals, 1 - alpha / 2))


# --- calibration --------------------------------------------------------------


def brier(labels: Sequence[bool], scores: Sequence[float]) -> Num:
    """Mean squared gap between p and the 0/1 label. Lower is better."""
    if not labels:
        return None
    return sum((p - (1.0 if y else 0.0)) ** 2 for y, p in zip(labels, scores)) / len(labels)


def _bin_of(p: float, bins: int) -> int:
    # Equal-width bins [0, 0.1), [0.1, 0.2), ..., [0.9, 1.0]. p = 1.0 joins the last bin.
    # Floor first, then check p against the real edges, so float error in p * bins
    # can move a value neither up past an edge nor down below one.
    b = min(max(int(p * bins), 0), bins - 1)
    if b > 0 and p < b / bins:
        b -= 1
    elif b < bins - 1 and p >= (b + 1) / bins:
        b += 1
    return b


def reliability(labels: Sequence[bool], scores: Sequence[float], bins: int = ECE_BINS) -> Optional[list[dict]]:
    """Per-bin table for a reliability diagram: one row per bin, empty bins included.

    Row: lo, hi, n, mean_p (confidence), frac_true (observed), gap = |frac_true - mean_p|.
    """
    if not labels:
        return None
    rows = [{"lo": b / bins, "hi": (b + 1) / bins, "n": 0, "sum_p": 0.0, "n_true": 0} for b in range(bins)]
    for y, p in zip(labels, scores):
        r = rows[_bin_of(p, bins)]
        r["n"] += 1
        r["sum_p"] += p
        r["n_true"] += 1 if y else 0
    out = []
    for r in rows:
        if r["n"]:
            mean_p, frac = r["sum_p"] / r["n"], r["n_true"] / r["n"]
            out.append({"lo": r["lo"], "hi": r["hi"], "n": r["n"], "mean_p": mean_p, "frac_true": frac, "gap": abs(frac - mean_p)})
        else:
            out.append({"lo": r["lo"], "hi": r["hi"], "n": 0, "mean_p": None, "frac_true": None, "gap": None})
    return out


def ece(labels: Sequence[bool], scores: Sequence[float], bins: int = ECE_BINS) -> Num:
    """Expected calibration error: sum over bins of (n_bin / N) * |frac_true - mean_p|."""
    table = reliability(labels, scores, bins)
    if table is None:
        return None
    return sum(r["n"] * r["gap"] for r in table if r["n"]) / len(labels)


# --- decisions ----------------------------------------------------------------


def decision_cost(labels: Sequence[bool], scores: Sequence[float], R: float) -> Optional[dict]:
    """Mean cost per item at the Bayes threshold t = 1 / (1 + R). Reject when p < t.

    Rejecting a true finding costs R. Accepting a false finding costs 1.
    Precision and recall are of "reject" (the positive class here is a false
    finding); each is None when its denominator is 0.
    """
    if not labels:
        return None
    t = 1.0 / (1.0 + R)
    total = 0.0
    n_reject = n_false = hits = 0
    for y, p in zip(labels, scores):
        reject = p < t
        n_reject += reject
        n_false += not y
        if reject and not y:
            hits += 1
        if reject and y:
            total += R
        elif not reject and not y:
            total += 1.0
    return {
        "R": R,
        "threshold": t,
        "mean_cost": total / len(labels),
        "precision": hits / n_reject if n_reject else None,
        "recall": hits / n_false if n_false else None,
        "n_reject": n_reject,
        "n": len(labels),
    }


def accuracy(labels: Sequence[bool], scores: Sequence[float], at: float = ACCURACY_AT) -> Num:
    """Share of items where (p >= at) matches the label."""
    if not labels:
        return None
    return sum(1 for y, p in zip(labels, scores) if (p >= at) == bool(y)) / len(labels)


# --- joining items and predictions ---------------------------------------------


def is_error(pred: dict) -> bool:
    """A prediction that failed: an error message, or no usable p."""
    p = pred.get("p")
    return bool(pred.get("error")) or not isinstance(p, (int, float)) or isinstance(p, bool)


def effective_p(pred: dict) -> float:
    """p as scored: errors count as ERROR_P, everything else is clamped to [0, 1]."""
    if is_error(pred):
        return ERROR_P
    return min(max(float(pred["p"]), 0.0), 1.0)


def index_preds(preds: Sequence[dict]) -> dict[str, dict]:
    """item_id to prediction. A later line for the same item wins (a resumed run)."""
    return {p["item_id"]: p for p in preds if "item_id" in p}


def in_cut(item: dict, cut: str) -> bool:
    tiers = CUT_TIERS[cut]
    return tiers is None or item.get("tier") in tiers


def scores_for(sub: Sequence[dict], by_id: dict[str, dict]) -> list[float]:
    """p per item. PREREG: an item the arm did not answer counts as ERROR_P, like an error."""
    return [effective_p(by_id[it["id"]]) if it["id"] in by_id else ERROR_P for it in sub]


def not_answered(items: Sequence[dict], preds: Sequence[dict], cut: str = CUT_ALL) -> list[str]:
    """Ids of items in the cut with no prediction from an arm that has results. Empty for an arm with none."""
    if not preds:
        return []
    by_id = index_preds(preds)
    return [it["id"] for it in items if in_cut(it, cut) and it["id"] not in by_id]


def aligned(items: Sequence[dict], preds: Sequence[dict], cut: str = CUT_ALL) -> tuple[list[str], list[bool], list[float]]:
    """(ids, labels, scores) for every item in the cut. Unanswered items score ERROR_P.

    An arm with no results at all returns empty lists: there is nothing to score.
    """
    if not preds:
        return [], [], []
    by_id = index_preds(preds)
    sub = [it for it in items if in_cut(it, cut)]
    return [it["id"] for it in sub], [bool(it["label"]) for it in sub], scores_for(sub, by_id)


def arm_summary(items: Sequence[dict], preds: Sequence[dict], cut: str = CUT_ALL, boot: bool = True) -> dict:
    """Everything the per-arm table needs for one arm on one cut. Missing values are None.

    Scores cover every item in the cut (unanswered ones at ERROR_P). `n` is the number
    answered; cost and latency are over the answered items only.
    """
    ids, ys, ps = aligned(items, preds, cut)
    by_id = index_preds(preds)
    used = [by_id[i] for i in ids if i in by_id]
    costs = [float(p.get("cost_usd") or 0.0) for p in used]
    lats = [float(p["latency_s"]) for p in used if isinstance(p.get("latency_s"), (int, float))]
    au = auroc(ys, ps)
    return {
        "n": len(used),
        "not_answered": len(ids) - len(used),
        "auroc": au,
        "auroc_ci": bootstrap_ci(auroc, ys, ps) if (boot and au is not None) else None,
        "brier": brier(ys, ps),
        "ece": ece(ys, ps),
        "cost_total": sum(costs) if used else None,
        "cost_per_item": sum(costs) / len(costs) if used else None,
        "latency_p50": statistics.median(lats) if lats else None,
        "errors": sum(1 for p in used if is_error(p)),
    }


# --- hypotheses ---------------------------------------------------------------


def _fmt(x: Num, nd: int = 3) -> str:
    return "not computable" if x is None else f"{x:.{nd}f}"


def _usd(x: Num) -> str:
    return "not computable" if x is None else f"${x:.6f}" if 0 < x < 0.01 else f"${x:.4f}"


def _no_results(missing: list[str]) -> str:
    return " and ".join(missing) + (" have no results" if len(missing) > 1 else " has no results")


def _cell(status: str, value: str, **nums) -> dict:
    return {"status": status, "value": value, "nums": nums}


def cost_ratio_text(cost: float, cost_opus: float) -> str:
    """'cost ratio 1/19.6' when cheaper than opus, '1.8x more than opus' when dearer.

    The 1/N figure rounds down and the Nx figure rounds up, so the text never makes the
    arm look cheaper than it is (19.96 prints as 1/19.9, not 1/20.0). The 1e-6 absorbs
    float noise from averaging, so 0.05 / (0.05 / 19.6) still prints as 1/19.6.
    """
    if cost <= cost_opus:
        return f"cost ratio 1/{math.floor(cost_opus / cost * 10 + 1e-6) / 10:.1f}"
    return f"{math.ceil(cost / cost_opus * 10 - 1e-6) / 10:.1f}x more than opus"


def _h1(items, runs, cut, cache, arm: str = "jev") -> dict:
    if not runs.get(arm):
        return _cell(NOT_RUN, f"{arm} has no results")
    s = cache((arm, cut))
    if s["auroc"] is None or s["auroc_ci"] is None:
        return _cell(NOT_RUN, "AUROC not computable (one class only or no items)")
    lo, hi = s["auroc_ci"]
    ok = s["auroc"] >= H1_AUROC and lo >= H1_LOWER
    return _cell(PASS if ok else FAIL, f"AUROC {_fmt(s['auroc'])}, 95% CI [{_fmt(lo)}, {_fmt(hi)}]",
                 auroc=s["auroc"], lo=lo, hi=hi)


def _h2(items, runs, cut, cache, arm: str = "jev") -> dict:
    if not runs.get(arm):
        return _cell(NOT_RUN, f"{arm} has no results")
    e = cache((arm, cut))["ece"]
    if e is None:
        return _cell(NOT_RUN, "ECE not computable (no items)")
    return _cell(PASS if e <= H2_ECE else FAIL, f"ECE {_fmt(e)}", ece=e)


def _common(items, runs, arms, cut):
    """Every item in the cut, with each arm's scores (unanswered at ERROR_P) and its cost per answered item."""
    by = {a: index_preds(runs[a]) for a in arms}
    common = [it for it in items if in_cut(it, cut)]
    ys = [bool(it["label"]) for it in common]
    scores = {a: scores_for(common, by[a]) for a in arms}
    costs = {}
    for a in arms:
        paid = [float(by[a][it["id"]].get("cost_usd") or 0.0) for it in common if it["id"] in by[a]]
        costs[a] = sum(paid) / len(paid) if paid else 0.0
    return common, ys, scores, costs


def _h3(items, runs, cut, cache, arm: str = "jev") -> dict:
    missing = [a for a in (arm, "opus") if not runs.get(a)]
    if missing:
        return _cell(NOT_RUN, _no_results(missing))
    common, ys, sc, costs = _common(items, runs, (arm, "opus"), cut)
    aj, ao = auroc(ys, sc[arm]), auroc(ys, sc["opus"])
    if aj is None or ao is None:
        return _cell(NOT_RUN, "AUROC not computable on the shared items")
    cj, co = costs[arm], costs["opus"]
    zero = [a for a, c in ((arm, cj), ("opus", co)) if c <= 0]
    if zero:  # a cost of 0 means it was not recorded; the cost bar cannot be judged
        return _cell(NOT_RUN, " and ".join(zero) + " cost is 0 or not recorded, so the cost bar is not computable")
    auroc_ok = aj >= ao - H3_MARGIN
    cost_ok = cj <= co / H3_COST_FACTOR
    ratio = cost_ratio_text(cj, co)
    return _cell(PASS if auroc_ok and cost_ok else FAIL,
                 f"AUROC {arm} {_fmt(aj)} vs opus {_fmt(ao)} (gap {aj - ao:+.3f}); "
                 f"cost per item {_usd(cj)} vs {_usd(co)}, {ratio}; n={len(common)}",
                 auroc=aj, auroc_opus=ao, cost=cj, cost_opus=co, auroc_ok=auroc_ok, cost_ok=cost_ok, n=len(common),
                 ratio=ratio)


def _h4(items, runs, cut, cache, arm: str = "jev") -> dict:
    missing = [a for a in (arm, "haiku") if not runs.get(a)]
    if missing:
        return _cell(NOT_RUN, _no_results(missing))
    common, ys, sc, _ = _common(items, runs, (arm, "haiku"), cut)
    d = paired_diff_ci(ys, sc[arm], sc["haiku"])
    if d is None:
        return _cell(NOT_RUN, "AUROC difference not computable on the shared items")
    ok = d[0] > 0 and d[1] > 0
    return _cell(PASS if ok else FAIL,
                 f"AUROC {arm} minus haiku {d[0]:+.3f}, 95% CI [{d[1]:+.3f}, {d[2]:+.3f}]; n={len(common)}",
                 diff=d[0], lo=d[1], hi=d[2], n=len(common))


def _h5(items, runs, cut, cache, arm: str = "jev") -> dict:
    if not runs.get(arm):
        return _cell(NOT_RUN, f"{arm} has no results")
    targets = [it for it in items if in_cut(it, cut) and it.get("kind") == "empty_diff"]
    if not targets:
        return _cell(NOT_RUN, "no empty_diff items in the data")
    by = index_preds(runs[arm])
    ps = list(zip([it["id"] for it in targets], scores_for(targets, by)))
    bad = [f"{i} p={p:.2f}" + ("" if i in by else " (not answered)") for i, p in ps if p > H5_MAX_P]
    worst = max(p for _, p in ps)
    if bad:
        return _cell(FAIL, f"{len(bad)} of {len(ps)} empty_diff items above {H5_MAX_P}: " + ", ".join(bad),
                     n_bad=len(bad), n=len(ps), worst=worst)
    return _cell(PASS, f"all {len(ps)} empty_diff items at p <= {H5_MAX_P} (max {worst:.2f})",
                 n_bad=0, n=len(ps), worst=worst)


HYPOTHESES = [
    ("H1", "Jev separates supported from unsupported findings", "AUROC >= 0.80 and 95% lower bound >= 0.70", _h1),
    ("H2", "Jev is calibrated enough to threshold", "ECE <= 0.10", _h2),
    ("H3", "Jev is a viable cheap substitute for the coordinator",
     "Jev AUROC no more than 0.05 below opus, at 1/20 of opus cost per item or less", _h3),
    ("H4", "Jev specifically matters", "Jev AUROC beats haiku and the 95% CI of the difference excludes 0", _h4),
    ("H5", "Jev survives decoys", "p <= 0.2 on every empty_diff item", _h5),
]


def decided(row: dict) -> str:
    """The status that counts. PREREG: the mechanical + decoy cut decides a conflict."""
    md, al = row[CUT_MECH_DECOY]["status"], row[CUT_ALL]["status"]
    return md if md in (PASS, FAIL) else al


def evaluate_hypotheses(
    results_by_arm: dict[str, list[dict]],
    items: Sequence[dict],
    summaries: Optional[dict] = None,
    arm: str = "jev",
    only: Optional[Sequence[str]] = None,
) -> list[dict]:
    """H1 to H5 rows. Each row: id, hypothesis, bar, all, mech_decoy, decided, conflict.

    `all` and `mech_decoy` are {"status": PASS | FAIL | NOT RUN, "value": text, "nums": {...}}.
    `summaries` is an optional cache of arm_summary results keyed by (arm, cut).
    `arm` swaps Jev for another arm, used to find the cheapest arm that passes H1 to H3.
    """
    memo = summaries if summaries is not None else {}

    def cache(key):
        if key not in memo:
            memo[key] = arm_summary(items, results_by_arm.get(key[0], []), key[1])
        return memo[key]

    rows = []
    for hid, text, bar, fn in HYPOTHESES:
        if only is not None and hid not in only:
            continue
        row = {"id": hid, "hypothesis": text, "bar": bar}
        for cut in (CUT_ALL, CUT_MECH_DECOY):
            row[cut] = fn(items, results_by_arm, cut, cache, arm)
        row["decided"] = decided(row)
        a, m = row[CUT_ALL]["status"], row[CUT_MECH_DECOY]["status"]
        row["conflict"] = a in (PASS, FAIL) and m in (PASS, FAIL) and a != m
        rows.append(row)
    return rows


def cheapest_passing_arm(results_by_arm: dict[str, list[dict]], items: Sequence[dict], summaries: Optional[dict] = None) -> Optional[str]:
    """PREREG: if H4 fails, the cheapest arm that passes H1 to H3 is the recommendation."""
    best: Optional[tuple[float, str]] = None
    for arm, preds in results_by_arm.items():
        if arm in ("opus", "accept_all") or not preds:
            continue
        rows = evaluate_hypotheses(results_by_arm, items, summaries, arm=arm, only=("H1", "H2", "H3"))
        if all(r["decided"] == PASS for r in rows):
            cost = rows[2][CUT_MECH_DECOY]["nums"].get("cost")
            if cost is None:
                cost = rows[2][CUT_ALL]["nums"].get("cost", 0.0)
            if best is None or cost < best[0]:
                best = (cost, arm)
    return best[1] if best else None



# =====================================================================================
# v2: PREREG-v2.md, the split evidence check. Everything above stays as v1 used it.
# =====================================================================================

V2_CLAIM_MECH_KINDS = {"true_added", "true_removed", "negated", "fabricated"}
V2_CITATION_KINDS = {"near_line", "wrong_line", "wrong_file"}
V2_CUT_CLAIM, V2_CUT_CITATION = "claim_truth", "citation"
V2_CUTS = (V2_CUT_CLAIM, V2_CUT_CITATION, CUT_ALL)
V2_CUT_NAMES = {V2_CUT_CLAIM: "claim-truth", V2_CUT_CITATION: "citation", CUT_ALL: "all"}
V2_FILE_ARMS = ("accept_all", "cite_script", "jev", "haiku", "opus")
V2_DERIVED = {"cite_jev": "jev", "cite_haiku": "haiku"}  # derived arm -> its model arm
V2_ARM_ORDER = ["jev", "haiku", "opus", "accept_all", "cite_script", "cite_jev", "cite_haiku"]

CITE_GATE_AT = 0.5  # cite_script p at or above this passes the citation gate
CITE_REJECT_P = 0.02  # p of a derived arm when the gate fails
M1_MAX_AUROC = 0.95
M2_LO, M2_HI = 0.35, 0.65
V2_H1_AUROC, V2_H1_MARGIN = 0.90, 0.05
V2_H3_ACC = 0.70
V2_R = 10
V2_H4_MARGIN, V2_H4_COST_FACTOR = 0.05, 20.0
V2_H6_ECE = 0.10
V2_INCOMPLETE_ABOVE = 0.10  # a bar reading an arm with more unanswered items than this share in its cut does not run


def v2_in_cut(item: dict, cut: str, semantic: bool = True) -> bool:
    """claim-truth: four mechanical kinds plus the semantic tier (unless dropped). citation: three kinds."""
    tier, kind = item.get("tier"), item.get("kind")
    if cut == CUT_ALL:
        return True
    if cut == V2_CUT_CLAIM:
        return (tier == "mechanical" and kind in V2_CLAIM_MECH_KINDS) or (semantic and tier == "semantic")
    if cut == V2_CUT_CITATION:
        return tier == "mechanical" and kind in V2_CITATION_KINDS
    raise ValueError(f"unknown v2 cut {cut!r}")


def cluster_of(item: dict) -> tuple[str, str]:
    """(repo, commit), the unit the v2 bootstrap resamples. An item without a source is its own cluster."""
    src = item.get("source") or {}
    if src.get("repo") or src.get("commit"):
        return (str(src.get("repo", "")), str(src.get("commit", "")))
    return ("item", str(item.get("id")))


def cluster_draws(clusters: Sequence, n: int = BOOT_N, seed: int = BOOT_SEED):
    """Yields n resamples as index lists. Each one draws whole clusters with replacement.

    Clusters keep their first-seen order. With one item per cluster this is the same
    draw as bootstrap_ci, index for index.
    """
    groups: dict = {}
    for i, c in enumerate(clusters):
        groups.setdefault(c, []).append(i)
    members = list(groups.values())
    rng = random.Random(seed)
    idx = range(len(members))
    for _ in range(n):
        pick = rng.choices(idx, k=len(members))
        yield [i for g in pick for i in members[g]]


def _percentile_ci(vals: list[float], alpha: float) -> Optional[tuple[float, float]]:
    if not vals:
        return None
    vals = sorted(vals)
    return (_quantile(vals, alpha / 2), _quantile(vals, 1 - alpha / 2))


def cluster_stat_ci(stat: Callable[[list[int]], Num], clusters: Sequence, n: int = BOOT_N,
                    seed: int = BOOT_SEED, alpha: float = 0.05) -> Optional[tuple[float, float]]:
    """Percentile interval of stat(indices) over cluster resamples. None results are skipped."""
    vals = [v for v in (stat(pick) for pick in cluster_draws(clusters, n, seed)) if v is not None]
    return _percentile_ci(vals, alpha)


def cluster_bootstrap_ci(fn, labels: Sequence[bool], scores: Sequence[float], clusters: Sequence,
                         n: int = BOOT_N, seed: int = BOOT_SEED, alpha: float = 0.05) -> Optional[tuple[float, float]]:
    """bootstrap_ci, but resampling whole clusters (commits) instead of items."""
    if not labels or fn(labels, scores) is None:
        return None
    return cluster_stat_ci(lambda pick: fn([labels[i] for i in pick], [scores[i] for i in pick]), clusters, n, seed, alpha)


def cluster_paired_diff_ci(labels: Sequence[bool], a: Sequence[float], b: Sequence[float], clusters: Sequence,
                           fn=auroc, n: int = BOOT_N, seed: int = BOOT_SEED,
                           alpha: float = 0.05) -> Optional[tuple[float, float, float]]:
    """paired_diff_ci with cluster resampling: (fn(a) - fn(b), lower, upper), or None."""
    fa, fb = fn(labels, a), fn(labels, b)
    if fa is None or fb is None:
        return None

    def stat(pick):
        ys = [labels[i] for i in pick]
        va, vb = fn(ys, [a[i] for i in pick]), fn(ys, [b[i] for i in pick])
        return None if va is None or vb is None else va - vb

    ci = cluster_stat_ci(stat, clusters, n, seed, alpha)
    return None if ci is None else (fa - fb, ci[0], ci[1])


def claim_words(item: dict) -> int:
    finding = item.get("finding") or {}
    return len(str(finding.get("claim", "") if isinstance(finding, dict) else finding).split())


def pair_win_rate(pairs: Sequence[tuple[float, float]]) -> Num:
    """Share of (p_true, p_false) pairs where the true twin gets the higher p. A tie counts half."""
    if not pairs:
        return None
    return sum(1.0 if t > f else 0.5 if t == f else 0.0 for t, f in pairs) / len(pairs)


def semantic_pairs(items: Sequence[dict]) -> tuple[list[dict], list[str]]:
    """Well-formed semantic pairs [{pair, true_id, false_id, cluster}] and the ids of malformed ones.

    A pair is well formed when it holds exactly two items, one true and one false.
    """
    groups: dict = {}
    for it in items:
        if it.get("tier") == "semantic" and it.get("pair") is not None:
            groups.setdefault(str(it["pair"]), []).append(it)
    good, bad = [], []
    for pid, its in groups.items():
        trues = [it for it in its if it["label"]]
        falses = [it for it in its if not it["label"]]
        if len(its) == 2 and len(trues) == 1 and len(falses) == 1:
            good.append({"pair": pid, "true_id": trues[0]["id"], "false_id": falses[0]["id"], "cluster": cluster_of(trues[0])})
        else:
            bad.append(pid)
    return good, bad


def pair_summary(pairs: Sequence[dict], preds: Sequence[dict]) -> dict:
    """Pair win rate of one arm with its commit-bootstrap interval. Unanswered items count as 0.5."""
    by = index_preds(preds)
    pts = [(scores_for([{"id": p["true_id"]}], by)[0], scores_for([{"id": p["false_id"]}], by)[0]) for p in pairs]
    rate = pair_win_rate(pts)
    ci = None
    if rate is not None:
        ci = cluster_stat_ci(lambda pick: pair_win_rate([pts[i] for i in pick]), [p["cluster"] for p in pairs])
    return {"n": len(pts), "rate": rate, "ci": ci}


def cost_per_answered(items: Sequence[dict], preds: Sequence[dict]) -> Num:
    by = index_preds(preds)
    paid = [float(by[it["id"]].get("cost_usd") or 0.0) for it in items if it["id"] in by]
    return sum(paid) / len(paid) if paid else None


def derive_split_arm(items: Sequence[dict], cite_preds: Sequence[dict], model_preds: Sequence[dict], name: str) -> list[dict]:
    """PREREG-v2 split design: the model p when cite_script passes (p >= 0.5), else 0.02.

    Unanswered or errored items count as 0.5 on both inputs before the rule. Every item
    carries the model arm's cost per answered item, so the derived arm costs what its
    model arm costs. Returns [] when either input has no results.
    """
    if not cite_preds or not model_preds:
        return []
    cby, mby = index_preds(cite_preds), index_preds(model_preds)
    per = cost_per_answered(items, model_preds) or 0.0
    out = []
    for it in items:
        gate = scores_for([it], cby)[0]
        mp = scores_for([it], mby)[0]
        src = mby.get(it["id"]) or {}
        out.append({"item_id": it["id"], "arm": name, "model": f"cite_script + {src.get('model') or V2_DERIVED.get(name)}",
                    "p": mp if gate >= CITE_GATE_AT else CITE_REJECT_P, "cost_usd": per,
                    "latency_s": src.get("latency_s"), "error": None, "raw": None})
    return out


def v2_runs(file_runs: dict[str, list[dict]], items: Sequence[dict]) -> dict[str, list[dict]]:
    """File arms plus the derived arms, in V2_ARM_ORDER. A derived arm appears only when both inputs have results."""
    runs = {a: list(p) for a, p in file_runs.items() if p}
    for name, model in V2_DERIVED.items():
        derived = derive_split_arm(items, runs.get("cite_script", []), runs.get(model, []), name)
        if derived:
            runs[name] = derived
    order = {a: i for i, a in enumerate(V2_ARM_ORDER)}
    return dict(sorted(runs.items(), key=lambda kv: (order.get(kv[0], len(order)), kv[0])))


def coverage(sub: Sequence[dict], runs: dict[str, list[dict]], arms: Sequence[str]) -> tuple[Optional[str], Optional[str]]:
    """(incomplete, note) for the arms a bar reads on its cut.

    incomplete names every arm with more than 10% of the cut unanswered, for example
    "opus answered 3 of 232; incomplete". note names arms with a smaller gap, for
    example "jev 230 of 232 answered". Each is None when there is nothing to say.
    """
    bad, note = [], []
    n = len(sub)
    for a in arms:
        by = index_preds(runs.get(a, []))
        k = sum(1 for it in sub if it["id"] in by)
        if n and (n - k) / n > V2_INCOMPLETE_ABOVE:
            bad.append(f"{a} answered {k} of {n}")
        elif k < n:
            note.append(f"{a} {k} of {n} answered")
    return ("; ".join(bad) + "; incomplete" if bad else None), (", ".join(note) or None)


def _covered(sub, runs, arms, compute) -> dict:
    """Run compute() only when every arm answered enough of the cut; tag the cell with the gap."""
    incomplete, note = coverage(sub, runs, arms)
    if incomplete:
        return _cell(NOT_RUN, incomplete)
    cell = compute()
    if note and cell["status"] != NOT_RUN:
        cell["nums"]["coverage"] = note
    return cell


def _row(hid: str, text: str, cut: str, bar: str, cell: dict) -> dict:
    return {"id": hid, "hypothesis": text, "cut": cut, "bar": bar, **cell}


def _sub(items, cut, semantic=True):
    sub = [it for it in items if v2_in_cut(it, cut, semantic)]
    return sub, [bool(it["label"]) for it in sub], [cluster_of(it) for it in sub]


def v2_checks(items: Sequence[dict], runs: dict[str, list[dict]]) -> list[dict]:
    """M1 and M2, the manipulation checks. Both read the semantic tier only."""
    sem = [it for it in items if it.get("tier") == "semantic"]
    ys = [bool(it["label"]) for it in sem]
    if not runs.get("opus"):
        m1 = _cell(NOT_RUN, "opus has no results")
    elif not sem:
        m1 = _cell(NOT_RUN, "no semantic items")
    else:
        def m1_cell():
            a = auroc(ys, scores_for(sem, index_preds(runs["opus"])))
            if a is None:
                return _cell(NOT_RUN, "opus AUROC on the semantic tier not computable (one class only)")
            return _cell(PASS if a <= M1_MAX_AUROC else FAIL, f"opus AUROC on the semantic tier {a:.4f}; n={len(sem)}", auroc=a)
        m1 = _covered(sem, runs, ["opus"], m1_cell)
    w = auroc(ys, [claim_words(it) for it in sem]) if sem else None
    if w is None:
        m2 = _cell(NOT_RUN, "no semantic items" if not sem else "claim length AUROC not computable (one class only)")
    else:
        m2 = _cell(PASS if M2_LO <= w <= M2_HI else FAIL, f"claim word count AUROC {w:.4f}; n={len(sem)}", auroc=w)
    return [
        _row("M1", "The semantic tier is not at the ceiling", "semantic", "opus AUROC on the semantic tier <= 0.95", m1),
        _row("M2", "The length shortcut is gone", "semantic",
             "AUROC of claim word count against the label is between 0.35 and 0.65", m2),
    ]


def _v2_h1(items, runs, semantic):
    missing = [a for a in ("jev", "opus") if not runs.get(a)]
    if missing:
        return _cell(NOT_RUN, _no_results(missing))
    sub, ys, cl = _sub(items, V2_CUT_CLAIM, semantic)
    return _covered(sub, runs, ["jev", "opus"], lambda: _v2_h1_cell(sub, ys, cl, runs))


def _v2_h1_cell(sub, ys, cl, runs):
    pj, po = scores_for(sub, index_preds(runs["jev"])), scores_for(sub, index_preds(runs["opus"]))
    aj, ao = auroc(ys, pj), auroc(ys, po)
    if aj is None or ao is None:
        return _cell(NOT_RUN, "AUROC not computable on the claim-truth cut")
    ci = cluster_bootstrap_ci(auroc, ys, pj, cl)
    gap = aj - ao
    ok = aj >= V2_H1_AUROC and gap >= -V2_H1_MARGIN
    return _cell(PASS if ok else FAIL, f"jev AUROC {aj:.3f}, commit CI [{ci[0]:.3f}, {ci[1]:.3f}]; opus {ao:.3f}; "
                 f"jev minus opus {gap:+.3f}; n={len(sub)}", auroc=aj, lo=ci[0], hi=ci[1], auroc_opus=ao, gap=gap)


def _v2_h2(items, runs, semantic):
    missing = [a for a in ("jev", "haiku") if not runs.get(a)]
    if missing:
        return _cell(NOT_RUN, _no_results(missing))
    sub, ys, cl = _sub(items, V2_CUT_CLAIM, semantic)
    return _covered(sub, runs, ["jev", "haiku"], lambda: _v2_h2_cell(sub, ys, cl, runs))


def _v2_h2_cell(sub, ys, cl, runs):
    pj, ph = scores_for(sub, index_preds(runs["jev"])), scores_for(sub, index_preds(runs["haiku"]))
    d = cluster_paired_diff_ci(ys, pj, ph, cl)
    di = paired_diff_ci(ys, pj, ph)
    if d is None:
        return _cell(NOT_RUN, "AUROC difference not computable on the claim-truth cut")
    ok = d[0] > 0 and d[1] > 0
    item_txt = f"; item CI [{di[1]:+.3f}, {di[2]:+.3f}]" if di else ""
    return _cell(PASS if ok else FAIL, f"jev minus haiku AUROC {d[0]:+.3f}, commit CI [{d[1]:+.3f}, {d[2]:+.3f}]{item_txt}; n={len(sub)}",
                 diff=d[0], lo=d[1], hi=d[2])


def _v2_h3(items, runs):
    if not runs.get("jev"):
        return _cell(NOT_RUN, "jev has no results")
    sub, ys, _ = _sub(items, V2_CUT_CITATION)
    if not sub:
        return _cell(NOT_RUN, "no citation items in the data")

    def cell():
        acc = accuracy(ys, scores_for(sub, index_preds(runs["jev"])))
        return _cell(PASS if acc >= V2_H3_ACC else FAIL, f"jev accuracy on the citation cut {acc:.3f}; n={len(sub)}", acc=acc)
    return _covered(sub, runs, ["jev"], cell)


def _v2_h4(items, runs):
    missing = [a for a in ("cite_script", "jev", "opus") if not runs.get(a)]
    if missing:
        return _cell(NOT_RUN, _no_results(missing))
    return _covered(items, runs, ["cite_script", "jev", "opus"], lambda: _v2_h4_cell(items, runs))


def _v2_h4_cell(items, runs):
    ys = [bool(it["label"]) for it in items]
    dj = decision_cost(ys, scores_for(items, index_preds(runs["cite_jev"])), V2_R)
    do = decision_cost(ys, scores_for(items, index_preds(runs["opus"])), V2_R)
    if dj is None or do is None:
        return _cell(NOT_RUN, "no items")
    cj, co = cost_per_answered(items, runs["jev"]) or 0.0, cost_per_answered(items, runs["opus"]) or 0.0
    zero = [a for a, c in (("cite_jev", cj), ("opus", co)) if c <= 0]
    if zero:
        return _cell(NOT_RUN, " and ".join(zero) + " cost is 0 or not recorded, so the cost bar is not computable")
    cost_dc_ok = dj["mean_cost"] <= do["mean_cost"] + V2_H4_MARGIN
    cost_ok = cj <= co / V2_H4_COST_FACTOR
    ratio = cost_ratio_text(cj, co)
    return _cell(PASS if cost_dc_ok and cost_ok else FAIL,
                 f"decision cost at R = 10: cite_jev {dj['mean_cost']:.3f} vs opus {do['mean_cost']:.3f}; "
                 f"cost per item {_usd(cj)} vs {_usd(co)}, {ratio}",
                 dc=dj["mean_cost"], dc_opus=do["mean_cost"], dc_ok=cost_dc_ok, cost=cj, cost_opus=co, cost_ok=cost_ok, ratio=ratio)


def _v2_h5(items, runs):
    if not runs.get("cite_jev"):
        missing = [a for a in ("cite_script", "jev") if not runs.get(a)] or ["cite_jev"]
        return _cell(NOT_RUN, _no_results(missing))
    return _covered(items, runs, ["cite_script", "jev"], lambda: _v2_h5_cell(items, runs))


def _v2_h5_cell(items, runs):
    ys = [bool(it["label"]) for it in items]
    d = decision_cost(ys, scores_for(items, index_preds(runs["cite_jev"])), V2_R)
    if d is None:
        return _cell(NOT_RUN, "no items")
    if d["n_reject"] == 0:
        return _cell(NOT_RUN, "cite_jev rejects nothing at R = 10, so reject precision is not defined", n_reject=0)
    t = d["threshold"]
    true_rejected = sum(1 for y, p in zip(ys, scores_for(items, index_preds(runs["cite_jev"]))) if y and p < t)
    ok = true_rejected == 0
    return _cell(PASS if ok else FAIL, f"reject precision {d['precision']:.2f}; {true_rejected} true of {d['n_reject']} rejected",
                 precision=d["precision"], n_reject=d["n_reject"], true_rejected=true_rejected)


def _v2_h6(items, runs):
    if not runs.get("jev"):
        return _cell(NOT_RUN, "jev has no results")
    if not items:
        return _cell(NOT_RUN, "ECE not computable (no items)")

    def cell():
        e = ece([bool(it["label"]) for it in items], scores_for(items, index_preds(runs["jev"])))
        return _cell(PASS if e <= V2_H6_ECE else FAIL, f"jev ECE on all items {e:.4f}; n={len(items)}", ece=e)
    return _covered(items, runs, ["jev"], cell)


def evaluate_v2(items: Sequence[dict], runs: dict[str, list[dict]]) -> dict:
    """M1, M2, then H1 to H6 as written in PREREG-v2.md.

    `runs` must already hold the derived arms (see v2_runs). The semantic tier enters
    H1 and H2 only when M1 and M2 both pass; otherwise they use the mechanical
    claim-truth kinds alone and `semantic_used` is False. A bar reading an arm with more
    than 10% of its cut unanswered does not run (see coverage).
    """
    checks = v2_checks(items, runs)
    semantic = all(c["status"] == PASS for c in checks)
    claim = "claim-truth" if semantic else "claim-truth, mechanical kinds only"
    hyps = [
        _row("H1", "Jev checks claims about as well as Opus", claim, "Jev AUROC >= 0.90 and Jev minus Opus >= -0.05",
             _v2_h1(items, runs, semantic)),
        _row("H2", "Jev checks claims better than Haiku", claim,
             "Jev minus Haiku AUROC > 0 and its commit-bootstrap lower bound > 0", _v2_h2(items, runs, semantic)),
        _row("H3", "Told the rule, Jev applies it", "citation", "Jev accuracy (p >= 0.5 read as supported) >= 0.70",
             _v2_h3(items, runs)),
        _row("H4", "The split design is as good as Opus at a fraction of the cost", "all",
             "cite_jev decision cost at R = 10 <= opus + 0.05, and cite_jev costs 1/20 of opus per item or less",
             _v2_h4(items, runs)),
        _row("H5", "The split design is a safe gate", "all", "cite_jev rejects no true finding at R = 10 (reject precision 1.00)",
             _v2_h5(items, runs)),
        _row("H6", "Jev stays calibrated", "all", "Jev ECE <= 0.10", _v2_h6(items, runs)),
    ]
    return {"checks": checks, "semantic_used": semantic, "hypotheses": hyps}


def v2_cut_summary(items: Sequence[dict], preds: Sequence[dict], cut: str, semantic: bool = True, boot: bool = True) -> dict:
    """n, AUROC with commit and item intervals, and accuracy for one arm on one v2 cut."""
    sub, ys, cl = _sub(items, cut, semantic)
    ps = scores_for(sub, index_preds(preds))
    a = auroc(ys, ps)
    return {
        "n": len(sub), "auroc": a, "acc": accuracy(ys, ps),
        "ci_commit": cluster_bootstrap_ci(auroc, ys, ps, cl) if (boot and a is not None) else None,
        "ci_item": bootstrap_ci(auroc, ys, ps) if (boot and a is not None) else None,
    }

if __name__ == "__main__":
    ys, ps = [True, True, False, False], [0.9, 0.4, 0.4, 0.1]
    print("auroc", auroc(ys, ps), "ci", bootstrap_ci(auroc, ys, ps))
    print("brier", brier(ys, ps), "ece", ece(ys, ps))
    print("cost R=10", decision_cost(ys, ps, 10))
