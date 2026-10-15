#!/usr/bin/env python3
"""Hand-computed tests for metrics.py and a smoke test for report.py.

Every expected number below is worked out by hand in the comment above it,
so a change to a metric fails here before it reaches a report.

    python3 tests/metrics.test.py
    python3 tests/metrics.test.py -v
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures")
sys.path.insert(0, ROOT)

import metrics as m  # noqa: E402

T, F = True, False
DASHES = re.compile("[" + chr(0x2013) + chr(0x2014) + "]")  # en dash, em dash


def pred(item_id: str, p, arm: str = "jev", error=None, cost: float = 0.0) -> dict:
    return {"item_id": item_id, "arm": arm, "model": None, "p": p, "cost_usd": cost, "latency_s": 1.0, "error": error, "raw": None}


def item(item_id: str, label: bool, tier: str = "mechanical", kind: str = "true_added") -> dict:
    return {"id": item_id, "tier": tier, "kind": kind, "label": label}


class TestAuroc(unittest.TestCase):
    def test_tie_case(self):
        # labels [T, T, F, F], scores [0.9, 0.4, 0.4, 0.1]. 2 positives x 2 negatives = 4 pairs.
        #   pos 0.9 vs neg 0.4 -> win 1     pos 0.9 vs neg 0.1 -> win 1
        #   pos 0.4 vs neg 0.4 -> tie 0.5   pos 0.4 vs neg 0.1 -> win 1
        # AUROC = (1 + 1 + 0.5 + 1) / 4 = 3.5 / 4 = 0.875.
        # Rank check: sorted 0.1(r1) 0.4,0.4(r2.5 each) 0.9(r4); R_pos = 4 + 2.5 = 6.5;
        # U = 6.5 - 2*3/2 = 3.5; 3.5 / 4 = 0.875.
        self.assertAlmostEqual(m.auroc([T, T, F, F], [0.9, 0.4, 0.4, 0.1]), 0.875)

    def test_perfect_and_inverted(self):
        self.assertEqual(m.auroc([T, T, F, F], [0.9, 0.8, 0.2, 0.1]), 1.0)
        self.assertEqual(m.auroc([T, T, F, F], [0.1, 0.2, 0.8, 0.9]), 0.0)

    def test_all_tied_is_half(self):
        # accept_all: every p = 1.0, every pair ties, AUROC = 0.5.
        self.assertEqual(m.auroc([T, F, T, F, F], [1.0] * 5), 0.5)

    def test_matches_brute_force(self):
        import random
        rng = random.Random(3)
        for _ in range(50):
            n = rng.randint(2, 30)
            ys = [rng.random() < 0.5 for _ in range(n)]
            ps = [round(rng.random(), 1) for _ in range(n)]  # rounding forces ties
            pos = [p for p, y in zip(ps, ys) if y]
            neg = [p for p, y in zip(ps, ys) if not y]
            if not pos or not neg:
                self.assertIsNone(m.auroc(ys, ps))
                continue
            brute = sum(1.0 if a > b else 0.5 if a == b else 0.0 for a in pos for b in neg) / (len(pos) * len(neg))
            self.assertAlmostEqual(m.auroc(ys, ps), brute)

    def test_single_class_is_none(self):
        self.assertIsNone(m.auroc([T, T, T], [0.2, 0.5, 0.9]))
        self.assertIsNone(m.auroc([F, F], [0.2, 0.5]))
        self.assertIsNone(m.auroc([], []))
        self.assertIsNone(m.roc_points([T, T], [0.1, 0.2]))
        self.assertIsNone(m.bootstrap_ci(m.auroc, [T, T], [0.1, 0.2]))
        self.assertIsNone(m.paired_diff_ci([T, T], [0.1, 0.2], [0.3, 0.4]))

    def test_roc_points_tie_case(self):
        # Thresholds high to low on [T 0.9, T 0.4, F 0.4, F 0.1]:
        #   start (0, 0); at 0.9 TP=1 FP=0 -> (0, 0.5); at 0.4 TP=2 FP=1 -> (0.5, 1); at 0.1 -> (1, 1).
        # Trapezoid area: 0 + 0.5 * (0.5 + 1) / 2 + 0.5 * 1 = 0.375 + 0.5 = 0.875 = AUROC.
        pts = m.roc_points([T, T, F, F], [0.9, 0.4, 0.4, 0.1])
        self.assertEqual(pts, [(0.0, 0.0), (0.0, 0.5), (0.5, 1.0), (1.0, 1.0)])
        area = sum((x2 - x1) * (y1 + y2) / 2 for (x1, y1), (x2, y2) in zip(pts, pts[1:]))
        self.assertAlmostEqual(area, 0.875)


class TestBootstrap(unittest.TestCase):
    YS = [T, F, T, T, F, F, T, F, T, F, T, F]
    PS = [0.9, 0.3, 0.7, 0.4, 0.5, 0.2, 0.8, 0.6, 0.65, 0.1, 0.35, 0.45]

    def test_deterministic_with_seed_7(self):
        a = m.bootstrap_ci(m.auroc, self.YS, self.PS, n=2000, seed=7)
        b = m.bootstrap_ci(m.auroc, self.YS, self.PS, n=2000, seed=7)
        self.assertEqual(a, b)
        point = m.auroc(self.YS, self.PS)
        self.assertLessEqual(a[0], point)
        self.assertGreaterEqual(a[1], point)
        self.assertNotEqual(a, m.bootstrap_ci(m.auroc, self.YS, self.PS, n=2000, seed=8))

    def test_defaults_are_prereg(self):
        self.assertEqual(m.bootstrap_ci(m.auroc, self.YS, self.PS), m.bootstrap_ci(m.auroc, self.YS, self.PS, n=2000, seed=7))

    def test_perfect_ranking_interval_is_one(self):
        # Every resample with both classes keeps the perfect ranking, so every value is 1.0.
        self.assertEqual(m.bootstrap_ci(m.auroc, [T, T, F, F], [0.9, 0.8, 0.2, 0.1]), (1.0, 1.0))

    def test_paired_diff(self):
        # b is a perfect ranker (1.0) and a is the tie case (0.875): diff = 0.875 - 1.0 = -0.125.
        ys = [T, T, F, F]
        d = m.paired_diff_ci(ys, [0.9, 0.4, 0.4, 0.1], [0.9, 0.8, 0.2, 0.1])
        self.assertAlmostEqual(d[0], -0.125)
        self.assertLessEqual(d[1], d[0])
        self.assertLessEqual(d[2], 0.0)  # a never beats a perfect ranker
        self.assertEqual(d, m.paired_diff_ci(ys, [0.9, 0.4, 0.4, 0.1], [0.9, 0.8, 0.2, 0.1]))
        # identical arms: every resample diff is exactly 0
        self.assertEqual(m.paired_diff_ci(self.YS, self.PS, self.PS), (0.0, 0.0, 0.0))


class TestCalibration(unittest.TestCase):
    def test_brier_three_items(self):
        # labels [T, F, T], p [0.8, 0.3, 0.5]
        # (0.8 - 1)^2 = 0.04, (0.3 - 0)^2 = 0.09, (0.5 - 1)^2 = 0.25; sum 0.38; / 3 = 0.126667
        self.assertAlmostEqual(m.brier([T, F, T], [0.8, 0.3, 0.5]), 0.38 / 3)
        self.assertIsNone(m.brier([], []))

    def test_ece_hand_case(self):
        # 8 items, 10 equal-width bins:
        #   bin 0 [0.0, 0.1): p 0.05 F             -> conf 0.05, frac 0.00, gap 0.05, n 1
        #   bin 1 [0.1, 0.2): p 0.15 F, 0.15 T     -> conf 0.15, frac 0.50, gap 0.35, n 2
        #   bin 5 [0.5, 0.6): p 0.55 T             -> conf 0.55, frac 1.00, gap 0.45, n 1
        #   bin 9 [0.9, 1.0]: p 0.95 T, T, T, F    -> conf 0.95, frac 0.75, gap 0.20, n 4
        # ECE = (1*0.05 + 2*0.35 + 1*0.45 + 4*0.20) / 8 = (0.05 + 0.70 + 0.45 + 0.80) / 8 = 2.0 / 8 = 0.25
        ys = [F, F, T, T, T, T, F, T]
        ps = [0.05, 0.15, 0.15, 0.95, 0.95, 0.95, 0.95, 0.55]
        self.assertAlmostEqual(m.ece(ys, ps), 0.25)
        table = m.reliability(ys, ps)
        self.assertEqual(len(table), 10)
        self.assertEqual([r["n"] for r in table], [1, 2, 0, 0, 0, 1, 0, 0, 0, 4])
        self.assertAlmostEqual(table[9]["frac_true"], 0.75)
        self.assertAlmostEqual(table[1]["gap"], 0.35)
        self.assertIsNone(table[2]["mean_p"])

    def test_ece_bin_edges(self):
        # 0.3 belongs to [0.3, 0.4), 1.0 to the last bin, 0.0 to the first.
        table = m.reliability([T, T, F], [0.3, 1.0, 0.0])
        self.assertEqual(table[3]["n"], 1)
        self.assertEqual(table[9]["n"], 1)
        self.assertEqual(table[0]["n"], 1)
        # all three bins are perfectly calibrated (p equals the observed rate) except 0.3 T: gap 0.7.
        # ECE = 0.7 / 3
        self.assertAlmostEqual(m.ece([T, T, F], [0.3, 1.0, 0.0]), 0.7 / 3)

    def test_accept_all_ece_is_false_share(self):
        # p = 1.0 everywhere, half the items false: one bin, conf 1.0, frac 0.5, ECE 0.5.
        self.assertAlmostEqual(m.ece([T, F, T, F], [1.0] * 4), 0.5)


class TestDecisionCost(unittest.TestCase):
    def test_r10_four_items(self):
        # R = 10 -> t = 1/11 = 0.0909. Reject when p < t.
        #   item 0: T, p 0.05 -> reject a true finding  -> cost 10
        #   item 1: F, p 0.02 -> reject a false finding -> cost 0
        #   item 2: F, p 0.50 -> accept a false finding -> cost 1
        #   item 3: T, p 0.90 -> accept a true finding  -> cost 0
        # mean cost = 11 / 4 = 2.75. Rejected 2, of which 1 false: precision 0.5.
        # False findings 2, of which 1 rejected: recall 0.5.
        d = m.decision_cost([T, F, F, T], [0.05, 0.02, 0.5, 0.9], 10)
        self.assertAlmostEqual(d["threshold"], 1 / 11)
        self.assertAlmostEqual(d["mean_cost"], 2.75)
        self.assertAlmostEqual(d["precision"], 0.5)
        self.assertAlmostEqual(d["recall"], 0.5)
        self.assertEqual(d["n_reject"], 2)

    def test_nothing_rejected(self):
        # accept_all at R = 5 (t = 1/6): no rejects, precision undefined, recall 0, cost = false share.
        d = m.decision_cost([T, F, F], [1.0, 1.0, 1.0], 5)
        self.assertIsNone(d["precision"])
        self.assertEqual(d["recall"], 0.0)
        self.assertAlmostEqual(d["mean_cost"], 2 / 3)
        self.assertIsNone(m.decision_cost([], [], 10))

    def test_threshold_is_strict(self):
        # p exactly at t is accepted (reject only when p < t). t at R = 1 is 0.5.
        d = m.decision_cost([F], [0.5], 1)
        self.assertEqual(d["n_reject"], 0)
        self.assertEqual(d["mean_cost"], 1.0)


class TestJoining(unittest.TestCase):
    def test_errors_count_as_half(self):
        self.assertEqual(m.effective_p(pred("a", None, error="timeout")), 0.5)
        self.assertEqual(m.effective_p(pred("a", 0.9, error="parse failed")), 0.5)
        self.assertEqual(m.effective_p(pred("a", 0.9)), 0.9)
        self.assertEqual(m.effective_p(pred("a", 1.7)), 1.0)

    def test_arm_with_no_results(self):
        s = m.arm_summary([item("a", T), item("b", F)], [])
        self.assertEqual(s["n"], 0)
        for k in ("auroc", "auroc_ci", "brier", "ece", "cost_total", "cost_per_item", "latency_p50"):
            self.assertIsNone(s[k], k)


def h_items() -> list[dict]:
    return [
        item("m1", T), item("m2", T), item("m3", F, kind="negated"), item("m4", F, kind="fabricated"),
        item("d1", F, tier="decoy", kind="empty_diff"), item("d2", F, tier="decoy", kind="empty_diff"),
        item("s1", T, tier="semantic", kind="true_behavior"), item("s2", F, tier="semantic", kind="false_misread"),
    ]


class TestHypotheses(unittest.TestCase):
    def rows(self, runs, items=None):
        return {r["id"]: r for r in m.evaluate_hypotheses(runs, items or h_items())}

    def test_h5_fails_when_empty_diff_has_p_03(self):
        jev = [pred(i, p) for i, p in [("m1", .9), ("m2", .8), ("m3", .1), ("m4", .2), ("d1", .3), ("d2", .1), ("s1", .7), ("s2", .4)]]
        h5 = self.rows({"jev": jev})["H5"]
        self.assertEqual(h5["all"]["status"], m.FAIL)
        self.assertEqual(h5["mech_decoy"]["status"], m.FAIL)
        self.assertIn("d1 p=0.30", h5["all"]["value"])

    def test_h5_passes_at_02_and_fails_on_error(self):
        base = [("m1", .9), ("m2", .8), ("m3", .1), ("m4", .2), ("s1", .7), ("s2", .4)]
        ok = [pred(i, p) for i, p in base + [("d1", .2), ("d2", .05)]]
        self.assertEqual(self.rows({"jev": ok})["H5"]["decided"], m.PASS)
        err = [pred(i, p) for i, p in base + [("d1", .05)]] + [pred("d2", None, error="timeout")]
        self.assertEqual(self.rows({"jev": err})["H5"]["decided"], m.FAIL)  # error counts as 0.5
        # review fix 1: an unanswered empty_diff item counts as p = 0.5, so H5 fails, not NOT RUN.
        partial = [pred(i, p) for i, p in base + [("d1", .05)]]
        h5 = self.rows({"jev": partial})["H5"]
        self.assertEqual(h5["decided"], m.FAIL)
        self.assertIn("d2", h5["all"]["value"])

    def test_missing_arms_are_not_run(self):
        rows = self.rows({})
        for hid in ("H1", "H2", "H3", "H4", "H5"):
            self.assertEqual(rows[hid]["all"]["status"], m.NOT_RUN, hid)
            self.assertEqual(rows[hid]["decided"], m.NOT_RUN, hid)
        jev = [pred(i, .5) for i in ("m1", "m2", "m3", "m4", "d1", "d2", "s1", "s2")]
        rows = self.rows({"jev": jev})
        self.assertEqual(rows["H3"]["all"]["status"], m.NOT_RUN)
        self.assertIn("opus", rows["H3"]["all"]["value"])
        self.assertEqual(rows["H4"]["all"]["status"], m.NOT_RUN)

    def test_single_class_cut_is_not_run(self):
        items = [item("a", T), item("b", T), item("c", T)]
        rows = self.rows({"jev": [pred(i, .9) for i in "abc"]}, items)
        self.assertEqual(rows["H1"]["all"]["status"], m.NOT_RUN)
        self.assertIn("not computable", rows["H1"]["all"]["value"])

    def test_h1_to_h4_and_conflict(self):
        # jev ranks mechanical + decoy perfectly but inverts semantic.
        # all items: positives m1 .9, m2 .8, s1 .1; negatives m3 .2, m4 .3, d1 .05, d2 .05, s2 .95.
        #   m1 beats 4 of 5 negatives (loses to s2), m2 beats 4, s1 beats d1, d2 only -> 2.
        #   AUROC all = (4 + 4 + 2) / 15 = 0.667 -> H1 FAIL on all items.
        # mech + decoy: positives .9 .8 over negatives .2 .3 .05 .05 -> 8 / 8 = 1.0.
        #   The bootstrap lower bound is 1.0 too, so H1 PASS on that cut, and that cut decides.
        ps = {"m1": .9, "m2": .8, "m3": .2, "m4": .3, "d1": .05, "d2": .05, "s1": .1, "s2": .95}
        jev = [pred(i, p, cost=0.001) for i, p in ps.items()]
        opus = [pred(i, p, "opus", cost=0.05) for i, p in ps.items()]
        haiku = [pred(i, .5, "haiku", cost=0.002) for i in ps]
        rows = self.rows({"jev": jev, "opus": opus, "haiku": haiku})
        self.assertAlmostEqual(rows["H1"]["all"]["nums"]["auroc"], 10 / 15)
        self.assertEqual(rows["H1"]["all"]["status"], m.FAIL)
        self.assertEqual(rows["H1"]["mech_decoy"]["status"], m.PASS)
        self.assertTrue(rows["H1"]["conflict"])
        self.assertEqual(rows["H1"]["decided"], m.PASS)
        # H3: same AUROC as opus (gap 0), cost 0.001 <= 0.05 / 20 = 0.0025 -> PASS.
        self.assertEqual(rows["H3"]["mech_decoy"]["status"], m.PASS)
        # H4 on mech + decoy: jev 1.0 vs haiku 0.5 (all tied), every resample diff is 0.5 -> PASS.
        self.assertEqual(rows["H4"]["mech_decoy"]["status"], m.PASS)
        self.assertAlmostEqual(rows["H4"]["mech_decoy"]["nums"]["diff"], 0.5)
        # H3 cost bar: at 0.003 per item jev costs more than 1/20 of opus -> FAIL.
        jev_pricey = [pred(i, p, cost=0.003) for i, p in ps.items()]
        rows = self.rows({"jev": jev_pricey, "opus": opus, "haiku": haiku})
        self.assertEqual(rows["H3"]["mech_decoy"]["status"], m.FAIL)
        self.assertFalse(rows["H3"]["mech_decoy"]["nums"]["cost_ok"])


class TestCheapModelRule(unittest.TestCase):
    def test_cheapest_passing_arm_when_h4_fails(self):
        # Every arm ranks perfectly (AUROC 1.0, CI [1, 1]) with p 0.95 on true and 0.05 on false.
        # ECE: bin 9 gap |1 - 0.95| = 0.05, bin 0 gap |0 - 0.05| = 0.05 -> ECE 0.05 <= 0.10.
        # H4: jev minus haiku is 0 in every resample -> FAIL. H1 to H3 pass for jev and haiku.
        # Cost per item: haiku 0.0005 < jev 0.001, both <= opus 0.05 / 20 = 0.0025 -> haiku wins.
        items = [item("m1", T), item("m2", T), item("m3", F, kind="negated"), item("d1", F, tier="decoy", kind="empty_diff")]
        ps = {"m1": .95, "m2": .95, "m3": .05, "d1": .05}
        runs = {a: [pred(i, p, a, cost=c) for i, p in ps.items()] for a, c in (("jev", .001), ("haiku", .0005), ("opus", .05))}
        rows = {r["id"]: r for r in m.evaluate_hypotheses(runs, items)}
        self.assertEqual([rows[h]["decided"] for h in ("H1", "H2", "H3", "H4", "H5")], [m.PASS, m.PASS, m.PASS, m.FAIL, m.PASS])
        self.assertAlmostEqual(rows["H2"]["all"]["nums"]["ece"], 0.05)
        self.assertEqual(m.cheapest_passing_arm(runs, items), "haiku")
        import report
        text = " ".join(report.reading(report.compute(items, runs)))
        self.assertIn("A cheap model is enough here.", text)
        self.assertIn("is haiku", text)


# --- review fixes (2026-10-15). Each test failed before its fix. ---------------------------


def review_items() -> list[dict]:
    """80 mechanical items (even k true) and 4 empty_diff decoys, as in the reviewer's repros."""
    items = [item(f"m{k}", k % 2 == 0) for k in range(80)]
    return items + [item(f"e{k}", F, tier="decoy", kind="empty_diff") for k in range(4)]


def review_preds(items, arm: str, cost: float, good: bool = True, ids=None) -> list[dict]:
    out = []
    for it in items:
        if ids is not None and it["id"] not in ids:
            continue
        p = (0.95 if it["label"] else 0.05) if good else (0.6 if it["label"] else 0.4)
        out.append(pred(it["id"], p, arm, cost=cost))
    return out


class TestReviewFixes(unittest.TestCase):
    def test_fix1_unanswered_items_count_as_half_and_are_listed(self):
        # jev answers 34 of 84 items (m0..m29 and the 4 decoys), perfectly. The other 50 count as p = 0.5.
        # Hand count on all 84: positives 40 (m0, m2, ..., m78), negatives 44 (40 odd m + 4 decoys).
        #   Answered positives (15, p 0.95) beat every negative: 15 * 44 = 660.
        #   Unanswered positives (25, p 0.5): beat the 19 answered negatives (p 0.05), tie the 25
        #   unanswered negatives: 25 * (19 + 25 * 0.5) = 25 * 31.5 = 787.5.
        #   AUROC = (660 + 787.5) / (40 * 44) = 1447.5 / 1760 = 0.822443...
        import report
        items = review_items()
        sub = {f"m{k}" for k in range(30)} | {f"e{k}" for k in range(4)}
        runs = {"jev": review_preds(items, "jev", 0.0001, ids=sub), "opus": review_preds(items, "opus", 0.05),
                "haiku": review_preds(items, "haiku", 0.01, good=False)}
        s = m.arm_summary(items, runs["jev"])
        self.assertEqual(s["n"], 34)
        self.assertEqual(s["not_answered"], 50)
        self.assertAlmostEqual(s["auroc"], 1447.5 / 1760)
        _, ys, ps = m.aligned(items, runs["jev"])
        self.assertEqual(len(ps), 84)
        self.assertEqual(ps.count(0.5), 50)
        ctx = report.compute(items, runs)
        self.assertEqual(sum(1 for e in ctx["errors"] if e["arm"] == "jev" and e["error"] == "not answered"), 50)
        text = " ".join(report.reading(ctx))
        self.assertIn("jev did not answer 50 of 84 items", text)
        md = report.render_md(ctx, {"when": "x", "args": None, "files": []})
        self.assertIn("Not answered", md)
        self.assertIn("| jev | 34 | 50 |", md)

    def test_fix2_not_run_rows_do_not_read_as_failed(self):
        import report
        items = review_items()
        # Repro C: haiku has no results, so H4 is NOT RUN while H1, H2, H3, H5 pass.
        runs = {"jev": review_preds(items, "jev", 0.0001), "opus": review_preds(items, "opus", 0.05)}
        ctx = report.compute(items, runs)
        self.assertEqual([r["decided"] for r in ctx["hypotheses"]], [m.PASS, m.PASS, m.PASS, m.NOT_RUN, m.PASS])
        text = " ".join(report.reading(ctx))
        self.assertNotIn("misses", text)
        self.assertNotIn("failed rows", text)
        self.assertIn("H4 did not run, so there is no recommendation on Jev against a cheap model.", text)
        # Repro E: no empty_diff items in the data, so H5 is NOT RUN while H1 to H4 pass.
        items = [it for it in items if it["kind"] != "empty_diff"]
        haiku = review_preds(items, "haiku", 0.01)
        for i, p in enumerate(haiku):
            if i % 4 == 0:  # every 4th item is a true one; haiku now ranks it below the false ones
                p["p"] = 0.02
        runs = {"jev": review_preds(items, "jev", 0.0001), "opus": review_preds(items, "opus", 0.05), "haiku": haiku}
        ctx = report.compute(items, runs)
        self.assertEqual([r["decided"] for r in ctx["hypotheses"]], [m.PASS, m.PASS, m.PASS, m.PASS, m.NOT_RUN])
        text = " ".join(report.reading(ctx))
        self.assertNotIn("but not H5", text)
        self.assertIn("H5 did not run, so there is no recommendation on decoy safety.", text)

    def test_fix3_cost_ratio_text(self):
        import report
        items = review_items()
        # Repro A: jev costs opus / 19.6. That misses the 1/20 bar and must not print as 1/20.
        runs = {"jev": review_preds(items, "jev", 0.05 / 19.6), "opus": review_preds(items, "opus", 0.05),
                "haiku": review_preds(items, "haiku", 0.01, good=False)}
        ctx = report.compute(items, runs)
        h3 = ctx["hypotheses"][2]
        self.assertEqual(h3["decided"], m.FAIL)
        self.assertIn("cost ratio 1/19.6", h3["mech_decoy"]["value"])
        text = " ".join(report.reading(ctx))
        self.assertIn("Jev costs 1/19.6 of opus per item.", text)
        self.assertIn("Jev cost is above the 1/20 bar.", text)
        self.assertNotIn("1/20 of opus", text)
        # Repro B: jev costs 0.09 per item, opus 0.05: 1.8x more, never "1/1".
        runs["jev"] = review_preds(items, "jev", 0.09)
        ctx = report.compute(items, runs)
        h3 = ctx["hypotheses"][2]
        self.assertIn("1.8x more than opus", h3["mech_decoy"]["value"])
        self.assertNotIn("1/1", h3["mech_decoy"]["value"])
        text = " ".join(report.reading(ctx))
        self.assertIn("Jev costs 1.8x more than opus per item.", text)
        self.assertIn("Jev cost is above the 1/20 bar.", text)

    def test_fix4_zero_cost_is_not_run(self):
        items = review_items()
        for jc, oc in ((0.0, 0.0), (0.0, 0.05), (0.001, 0.0)):
            runs = {"jev": review_preds(items, "jev", jc), "opus": review_preds(items, "opus", oc)}
            h3 = {r["id"]: r for r in m.evaluate_hypotheses(runs, items)}["H3"]
            self.assertEqual(h3["decided"], m.NOT_RUN, (jc, oc))
            self.assertIn("cost", h3["all"]["value"])

    def test_fix5_bin_edges(self):
        self.assertEqual(m._bin_of(0.09999999995, 10), 0)
        self.assertEqual(m._bin_of(1.0, 10), 9)
        self.assertEqual(m._bin_of(0.0, 10), 0)
        for k in range(10):  # every edge k/10 opens its own bin
            self.assertEqual(m._bin_of(k / 10, 10), k, k)
            self.assertEqual(m._bin_of(k / 10 - 1e-12, 10), max(k - 1, 0), k)


class TestReport(unittest.TestCase):
    def test_report_renders_from_fixtures(self):
        with tempfile.TemporaryDirectory() as out:
            cmd = [sys.executable, os.path.join(ROOT, "report.py"), "--data", os.path.join(FIX, "items.jsonl"),
                   "--runs", os.path.join(FIX, "runs"), "--out", out]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            with open(os.path.join(out, "report.md"), encoding="utf-8") as f:
                md = f.read()
            with open(os.path.join(out, "report.html"), encoding="utf-8") as f:
                page = f.read()
        for text in (md, page):
            self.assertIsNone(DASHES.search(text), "en or em dash in report")
        self.assertIn("<title>Evidence Check Eval</title>", page)
        self.assertNotIn("<script src", page)
        self.assertIn("prefers-color-scheme: dark", page)
        for heading in ("Verdict", "Per-arm results", "Decision cost", "Decoy behavior", "Errors", "Known threats", "Reproduce"):
            self.assertIn(heading, md)
        self.assertIn("HTTP 529", md)  # the fixture errors are listed

    def test_reading_sentences_are_short(self):
        sys.path.insert(0, ROOT)
        import report
        items = report.load_items([os.path.join(FIX, "items.jsonl")])
        runs, _ = report.load_runs(os.path.join(FIX, "runs"))
        ctx = report.compute(items, runs)
        sentences = report.reading(ctx)
        self.assertGreater(len(sentences), 3)
        for s in sentences:
            self.assertLessEqual(len(s.split()), 20, s)
            self.assertIsNone(DASHES.search(s))
        # an empty run directory still renders, with every bar NOT RUN
        ctx = report.compute(items, {})
        self.assertTrue(all(r["decided"] == m.NOT_RUN for r in ctx["hypotheses"]))
        for s in report.reading(ctx):
            self.assertLessEqual(len(s.split()), 20, s)


if __name__ == "__main__":
    unittest.main()
