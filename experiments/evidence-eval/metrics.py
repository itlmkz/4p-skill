#!/usr/bin/env python3
"""Metrics for the evidence-check eval. Stdlib only.

Every function takes plain lists: `labels` are bools (True = the finding is
supported), `scores` are each arm's probability `p` that it is supported.
Degenerate input (no items, one class only) returns None, never a fake number.

    from metrics import auroc, bootstrap_ci, brier, ece, decision_cost
    auroc([True, True, False, False], [0.9, 0.4, 0.4, 0.1])   # 0.875

    python3 metrics.py      # tiny self-demo on the 4-item tie case

The bars and cuts come from PREREG.md. `evaluate_hypotheses` turns predictions
into the H1 to H5 rows the report prints.
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


if __name__ == "__main__":
    ys, ps = [True, True, False, False], [0.9, 0.4, 0.4, 0.1]
    print("auroc", auroc(ys, ps), "ci", bootstrap_ci(auroc, ys, ps))
    print("brier", brier(ys, ps), "ece", ece(ys, ps))
    print("cost R=10", decision_cost(ys, ps, 10))
