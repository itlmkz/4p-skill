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


# --- v2 (PREREG-v2.md) --------------------------------------------------------------------


def v2item(iid: str, label: bool, tier: str = "mechanical", kind: str = "true_added", commit: str = "", words: int = 6, pair=None) -> dict:
    it = {"id": iid, "tier": tier, "kind": kind, "label": label, "finding": {"claim": " ".join(["w"] * words)}}
    if commit:
        it["source"] = {"repo": "o/r", "commit": commit}
    if pair is not None:
        it["pair"] = pair
    return it


class TestV2Bootstrap(unittest.TestCase):
    # Cluster A = items 0, 1 (T 0.9, F 0.1: ranked right). Cluster B = items 2, 3 (T 0.2, F 0.8: ranked wrong).
    YS, PS, CL = [T, F, T, F], [0.9, 0.1, 0.2, 0.8], ["A", "A", "B", "B"]

    def test_resamples_whole_clusters(self):
        # Every draw holds item 0 as often as item 1, and item 2 as often as item 3.
        for pick in m.cluster_draws(self.CL, n=300, seed=7):
            self.assertEqual(len(pick), 4)
            self.assertEqual(pick.count(0), pick.count(1))
            self.assertEqual(pick.count(2), pick.count(3))
        # Only three resamples exist. AA: AUROC 1.0. BB: 0.0. AB: positives 0.9, 0.2 vs negatives 0.1, 0.8:
        #   0.9 beats both (2), 0.2 beats 0.1 only (1) -> 3 / 4 = 0.75.
        vals = set()
        for pick in m.cluster_draws(self.CL, n=2000, seed=7):
            vals.add(m.auroc([self.YS[i] for i in pick], [self.PS[i] for i in pick]))
        self.assertEqual(vals, {0.0, 0.75, 1.0})
        # AA and BB each come up about 1 in 4, so the 2.5% and 97.5% points are 0.0 and 1.0.
        self.assertEqual(m.cluster_bootstrap_ci(m.auroc, self.YS, self.PS, self.CL), (0.0, 1.0))

    def test_deterministic_and_singletons_match_item_bootstrap(self):
        ys, ps = TestBootstrap.YS, TestBootstrap.PS
        cl = [f"c{i // 2}" for i in range(len(ys))]  # 6 commits of 2 items
        a = m.cluster_bootstrap_ci(m.auroc, ys, ps, cl)
        self.assertEqual(a, m.cluster_bootstrap_ci(m.auroc, ys, ps, cl, n=2000, seed=7))
        # the seed drives the draws: seed 7 and seed 8 give different resamples, seed 7 twice the same
        self.assertEqual(list(m.cluster_draws(cl, n=20, seed=7)), list(m.cluster_draws(cl, n=20, seed=7)))
        self.assertNotEqual(list(m.cluster_draws(cl, n=20, seed=7)), list(m.cluster_draws(cl, n=20, seed=8)))
        # One item per cluster draws the same indices as the v1 item bootstrap.
        single = [f"s{i}" for i in range(len(ys))]
        self.assertEqual(m.cluster_bootstrap_ci(m.auroc, ys, ps, single), m.bootstrap_ci(m.auroc, ys, ps))
        d = m.cluster_paired_diff_ci(ys, ps, ps, cl)
        self.assertEqual(d, (0.0, 0.0, 0.0))
        self.assertIsNone(m.cluster_bootstrap_ci(m.auroc, [T, T], [0.1, 0.2], ["a", "b"]))

    def test_cluster_of(self):
        self.assertEqual(m.cluster_of({"id": "x", "source": {"repo": "o/r", "commit": "abc"}}), ("o/r", "abc"))
        self.assertEqual(m.cluster_of({"id": "x"}), ("item", "x"))


class TestV2Derived(unittest.TestCase):
    def test_split_rule_and_cost(self):
        # cite_script p: 0.95 (pass), 0.05 (fail), 0.50 (pass: the gate is p >= 0.5), item 3 unanswered (0.5, pass).
        # jev p: 0.8, 0.9, 0.3, item 3 unanswered (0.5).
        # cite_jev: 0.8, 0.02, 0.3, 0.5. Cost per item = jev cost per answered item = (1 + 2 + 3) / 3 = 2 (x 0.001).
        items = [v2item(f"i{k}", T) for k in range(4)]
        cite = [pred("i0", .95, "cite_script"), pred("i1", .05, "cite_script"), pred("i2", .5, "cite_script")]
        jev = [pred("i0", .8, cost=.001), pred("i1", .9, cost=.002), pred("i2", .3, cost=.003)]
        out = m.derive_split_arm(items, cite, jev, "cite_jev")
        self.assertEqual([p["p"] for p in out], [0.8, 0.02, 0.3, 0.5])
        for p in out:
            self.assertAlmostEqual(p["cost_usd"], 0.002)
        runs = m.v2_runs({"cite_script": cite, "jev": jev}, items)
        self.assertEqual(list(runs), ["jev", "cite_script", "cite_jev"])  # no haiku, so no cite_haiku
        self.assertEqual(list(m.v2_runs({"jev": jev}, items)), ["jev"])  # no cite_script, no derived arm
        # an errored jev item counts as 0.5 before the rule
        out = m.derive_split_arm(items[:1], cite, [pred("i0", None, error="timeout")], "cite_jev")
        self.assertEqual(out[0]["p"], 0.5)


class TestV2Checks(unittest.TestCase):
    def sem(self, words):
        return [v2item(f"s{k}", y, "semantic", "true_behavior" if y else "false_misread", words=w)
                for k, (y, w) in enumerate(zip([T, T, F, F], words))]

    def test_m1_m2_pass_and_fail(self):
        # M2: claim words, positives 5, 8 vs negatives 6, 7: 8 beats both (2), 5 beats none -> 2 / 4 = 0.5, PASS.
        # M1: opus p 0.9, 0.4 vs 0.6, 0.1: 0.9 beats both (2), 0.4 beats 0.1 (1) -> 3 / 4 = 0.75 <= 0.95, PASS.
        items = self.sem([5, 8, 6, 7])
        opus = [pred(f"s{k}", p, "opus") for k, p in enumerate([.9, .4, .6, .1])]
        c = {r["id"]: r for r in m.v2_checks(items, {"opus": opus})}
        self.assertEqual((c["M1"]["status"], c["M2"]["status"]), (m.PASS, m.PASS))
        self.assertAlmostEqual(c["M1"]["nums"]["auroc"], 0.75)
        self.assertAlmostEqual(c["M2"]["nums"]["auroc"], 0.5)
        # M2 fails: words 9, 8 vs 3, 4 -> length ranks perfectly, AUROC 1.0. M1 fails: opus perfect, 1.0 > 0.95.
        items = self.sem([9, 8, 3, 4])
        opus = [pred(f"s{k}", p, "opus") for k, p in enumerate([.9, .8, .2, .1])]
        c = {r["id"]: r for r in m.v2_checks(items, {"opus": opus})}
        self.assertEqual((c["M1"]["status"], c["M2"]["status"]), (m.FAIL, m.FAIL))
        # no opus results: M1 does not run, M2 still does (it needs no arm)
        c = m.v2_checks(items, {})
        self.assertEqual((c[0]["status"], c[1]["status"]), (m.NOT_RUN, m.FAIL))

    def h1_items(self):
        # mechanical claim-truth: T 0.9 (true_added), T 0.8 (true_removed), F 0.2 (negated), F 0.1 (fabricated).
        # semantic pair, equal claim length: T and F, jev inverts it (T 0.1, F 0.9).
        return [v2item("m1", T), v2item("m2", T, kind="true_removed"), v2item("m3", F, kind="negated"),
                v2item("m4", F, kind="fabricated"), v2item("s1", T, "semantic", "true_behavior", pair="p"),
                v2item("s2", F, "semantic", "false_misread", pair="p")]

    def test_h1_falls_back_to_mechanical_when_m1_fails(self):
        import report
        items = self.h1_items()
        jev = [pred(i, p) for i, p in zip(["m1", "m2", "m3", "m4", "s1", "s2"], [.9, .8, .2, .1, .1, .9])]
        opus_perfect = [pred(i, p, "opus") for i, p in zip(["m1", "m2", "m3", "m4", "s1", "s2"], [.9, .8, .2, .1, .9, .1])]
        v = m.evaluate_v2(items, {"jev": jev, "opus": opus_perfect})
        # M1: opus semantic AUROC 1.0 > 0.95 -> FAIL; H1 then reads mechanical kinds only: jev AUROC 1.0 -> PASS.
        self.assertEqual(v["checks"][0]["status"], m.FAIL)
        self.assertFalse(v["semantic_used"])
        h1 = v["hypotheses"][0]
        self.assertEqual(h1["cut"], "claim-truth, mechanical kinds only")
        self.assertAlmostEqual(h1["nums"]["auroc"], 1.0)
        self.assertEqual(h1["status"], m.PASS)
        ctx = report.compute_v2(items, {"jev": jev, "opus": opus_perfect})
        self.assertIn("H1 and H2 use the mechanical claim-truth kinds alone.", " ".join(report.reading_v2(ctx)))
        # Control: opus inverts the semantic pair (AUROC 0.0 <= 0.95), so M1 passes and the semantic tier counts.
        # positives 0.9, 0.8, 0.1 vs negatives 0.2, 0.1, 0.9:
        #   0.9: beats 0.2 and 0.1, ties 0.9 -> 2.5; 0.8: beats 0.2 and 0.1 -> 2; 0.1: ties 0.1 -> 0.5.
        #   AUROC = 5 / 9 = 0.5556 -> H1 FAIL.
        opus_ok = [pred(i, p, "opus") for i, p in zip(["m1", "m2", "m3", "m4", "s1", "s2"], [.9, .8, .2, .1, .4, .6])]
        v = m.evaluate_v2(items, {"jev": jev, "opus": opus_ok})
        self.assertTrue(v["semantic_used"])
        self.assertAlmostEqual(v["hypotheses"][0]["nums"]["auroc"], 5 / 9)
        self.assertEqual(v["hypotheses"][0]["status"], m.FAIL)


class TestV2Bars(unittest.TestCase):
    def items(self):
        return [v2item("a", T), v2item("b", T, kind="near_line"), v2item("c", F, kind="wrong_line"), v2item("d", F, kind="negated")]

    def runs(self, cite_ps, jev_ps, jev_cost=.001, opus_cost=.05):
        ids = ["a", "b", "c", "d"]
        file_runs = {"cite_script": [pred(i, p, "cite_script") for i, p in zip(ids, cite_ps)],
                     "jev": [pred(i, p, cost=jev_cost) for i, p in zip(ids, jev_ps)],
                     "opus": [pred(i, p, "opus", cost=opus_cost) for i, p in zip(ids, [.9, .9, .1, .1])]}
        return m.v2_runs(file_runs, self.items())

    def bar(self, runs, hid):
        return {r["id"]: r for r in m.evaluate_v2(self.items(), runs)["hypotheses"]}[hid]

    def test_h5_not_run_when_nothing_rejected(self):
        # cite_script passes all, jev p >= 0.5 everywhere: cite_jev never falls below t = 1/11, nothing is rejected.
        h5 = self.bar(self.runs([.95] * 4, [.9, .8, .6, .5]), "H5")
        self.assertEqual(h5["status"], m.NOT_RUN)
        self.assertIn("rejects nothing", h5["value"])
        # cite_script fails c and d only: cite_jev 0.02 on two false items -> precision 1.00, PASS.
        self.assertEqual(self.bar(self.runs([.95, .95, .05, .05], [.9, .8, .6, .5]), "H5")["status"], m.PASS)
        # cite_script also fails b, a true near_line item: one true finding rejected -> FAIL.
        h5 = self.bar(self.runs([.95, .05, .05, .05], [.9, .8, .6, .5]), "H5")
        self.assertEqual(h5["status"], m.FAIL)
        self.assertEqual(h5["nums"]["true_rejected"], 1)

    def test_h3_h4_h6(self):
        # H3 on the citation cut (b true, c false): jev 0.8 reads supported (right), 0.6 reads supported (wrong) -> 0.5.
        runs = self.runs([.95, .95, .05, .05], [.9, .8, .6, .05])
        self.assertAlmostEqual(self.bar(runs, "H3")["nums"]["acc"], 0.5)
        self.assertEqual(self.bar(runs, "H3")["status"], m.FAIL)
        # H4 at R = 10 (t = 1/11): cite_jev p 0.9, 0.8, 0.02, 0.02 -> rejects c, d (false), cost 0.
        # opus 0.9, 0.9, 0.1, 0.1 -> accepts c, d (false), 2 / 4 = 0.5. 0 <= 0.55 and 0.001 <= 0.05 / 20 -> PASS.
        h4 = self.bar(runs, "H4")
        self.assertAlmostEqual(h4["nums"]["dc"], 0.0)
        self.assertAlmostEqual(h4["nums"]["dc_opus"], 0.5)
        self.assertEqual(h4["status"], m.PASS)
        self.assertEqual(self.bar(self.runs([.95, .95, .05, .05], [.9, .8, .6, .05], jev_cost=0.0), "H4")["status"], m.NOT_RUN)
        self.assertEqual(self.bar(self.runs([.95, .95, .05, .05], [.9, .8, .6, .05], jev_cost=0.003), "H4")["status"], m.FAIL)
        # H6: jev on all 4 items. Bins: 0.9 T (bin 9, gap 0.1), 0.8 T (bin 8, gap 0.2), 0.6 F (bin 6, gap 0.6),
        #   0.05 F (bin 0, gap 0.05). ECE = (0.1 + 0.2 + 0.6 + 0.05) / 4 = 0.2375 -> FAIL.
        self.assertAlmostEqual(self.bar(runs, "H6")["nums"]["ece"], 0.2375)


class TestV2Pairs(unittest.TestCase):
    def test_pair_win_rate(self):
        # (p_true, p_false): 0.9 > 0.1 win, 0.4 < 0.6 loss, 0.5 = 0.5 tie (half), 0.7 > 0.2 win -> 2.5 / 4 = 0.625.
        self.assertAlmostEqual(m.pair_win_rate([(.9, .1), (.4, .6), (.5, .5), (.7, .2)]), 0.625)
        self.assertIsNone(m.pair_win_rate([]))

    def test_pairs_from_items_with_commit_ci(self):
        items = [v2item("t1", T, "semantic", pair="p1", commit="c1"), v2item("f1", F, "semantic", pair="p1", commit="c1"),
                 v2item("t2", T, "semantic", pair="p2", commit="c2"), v2item("f2", F, "semantic", pair="p2", commit="c2"),
                 v2item("t3", T, "semantic", pair="p3", commit="c2"), v2item("x3", T, "semantic", pair="p3", commit="c2")]
        pairs, bad = m.semantic_pairs(items)
        self.assertEqual([p["pair"] for p in pairs], ["p1", "p2"])
        self.assertEqual(bad, ["p3"])  # two true items, no false twin
        # jev: p1 win (0.9 vs 0.2), p2 loss (0.3 vs 0.7), rate 0.5. Commits c1, c2 hold one pair each, so a
        # resample is c1c1 (1.0), c2c2 (0.0) or mixed (0.5): the 95% interval is (0.0, 1.0).
        jev = [pred("t1", .9), pred("f1", .2), pred("t2", .3), pred("f2", .7)]
        s = m.pair_summary(pairs, jev)
        self.assertEqual((s["n"], s["rate"], s["ci"]), (2, 0.5, (0.0, 1.0)))
        self.assertEqual(s, m.pair_summary(pairs, jev))


class TestV2Report(unittest.TestCase):
    def test_v2_report_renders_from_fixtures(self):
        v2 = os.path.join(FIX, "v2")
        with tempfile.TemporaryDirectory() as out:
            cmd = [sys.executable, os.path.join(ROOT, "report.py"), "--prereg", "v2", "--data", os.path.join(v2, "items.jsonl"),
                   "--runs", os.path.join(v2, "runs"), "--out", out]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, res.stderr)
            with open(os.path.join(out, "report.md"), encoding="utf-8") as f:
                md = f.read()
            with open(os.path.join(out, "report.html"), encoding="utf-8") as f:
                page = f.read()
        for text in (md, page):
            self.assertIsNone(DASHES.search(text), "en or em dash in report")
        self.assertIn("<title>Evidence Check Eval v2</title>", page)
        self.assertNotIn("<script", page)
        self.assertIn('tabindex="0" role="region"', page)
        self.assertLess(md.index("## Manipulation checks"), md.index("## Verdict"))
        for heading in ("Per-arm results", "Per cut", "Semantic pairs", "Decision cost", "Errors",
                        "What changed from v1", "Known threats (from PREREG-v2.md)", "Reproduce"):
            self.assertIn(heading, md)
        for arm in ("cite_script", "cite_jev", "cite_haiku"):
            self.assertIn(f"| {arm} |", md)

    def test_v2_reading_sentences_are_short(self):
        import report
        v2 = os.path.join(FIX, "v2")
        items = report.load_items([os.path.join(v2, "items.jsonl")])
        runs, _ = report.load_runs(os.path.join(v2, "runs"))
        for r in (runs, {}, {a: p for a, p in runs.items() if a != "haiku"}):
            for s in sentences(report.reading_v2(report.compute_v2(items, r))):
                self.assertLessEqual(len(s.split()), 20, s)
                self.assertIsNone(DASHES.search(s))


# --- v2 review fixes (2026-10-15). Each test failed before its fix. -------------------------


def sentences(parts: list[str]) -> list[str]:
    """Split reading elements into real sentences: a period followed by a space ends one."""
    return [s for p in parts for s in re.split(r"(?<=[.])\s+", p) if s]


def v2_fixture():
    import report
    v2 = os.path.join(FIX, "v2")
    items = report.load_items([os.path.join(v2, "items.jsonl")])
    runs, _ = report.load_runs(os.path.join(v2, "runs"))
    return report, items, runs


class TestV2ReviewFixes(unittest.TestCase):
    def test_v2fix1_not_run_check_is_not_called_a_defect(self):
        report, items, runs = v2_fixture()
        no_opus = {a: p for a, p in runs.items() if a != "opus"}
        ctx = report.compute_v2(items, no_opus)
        self.assertEqual(ctx["checks"][0]["status"], m.NOT_RUN)
        self.assertFalse(ctx["semantic_used"])  # the fallback still applies
        text = " ".join(report.reading_v2(ctx))
        self.assertNotIn("known defect", text)
        self.assertIn("M1 did not run, so the semantic tier is not read.", text)
        self.assertIn("H1 and H2 use the mechanical claim-truth kinds alone.", text)
        md = report.render_md_v2(ctx, {"when": "x", "files": []})
        self.assertNotIn("known defect", md)
        # FAIL keeps the defect wording: opus perfect on the semantic tier -> M1 fails.
        perfect = [dict(p, p=(0.99 if it["label"] else 0.01)) for p, it in zip(runs["opus"], items)]
        ctx = report.compute_v2(items, dict(runs, opus=perfect))
        self.assertEqual(ctx["checks"][0]["status"], m.FAIL)
        self.assertIn("known defect", " ".join(report.reading_v2(ctx)))
        for s in sentences(report.reading_v2(ctx)):
            self.assertLessEqual(len(s.split()), 20, s)

    def test_v2fix2_incomplete_arm_is_not_run(self):
        report, items, runs = v2_fixture()
        sem_ids = [it["id"] for it in items if it["tier"] == "semantic"]  # 24 semantic items
        # opus answers 3 items in all: far more than 10% missing everywhere it is read.
        keep = set(sem_ids[:3])
        opus3 = [p for p in runs["opus"] if p["item_id"] in keep]
        ctx = report.compute_v2(items, dict(runs, opus=opus3))
        rows = {r["id"]: r for r in ctx["checks"] + ctx["hypotheses"]}
        self.assertEqual(rows["M1"]["status"], m.NOT_RUN)
        self.assertEqual(rows["M1"]["value"], "opus answered 3 of 24; incomplete")
        self.assertEqual(rows["H4"]["status"], m.NOT_RUN)
        self.assertEqual(rows["H4"]["value"], "opus answered 3 of 63; incomplete")
        self.assertEqual(rows["H1"]["status"], m.NOT_RUN)
        self.assertIn("incomplete", rows["H1"]["value"])
        self.assertNotIn("M1 passes", " ".join(report.reading_v2(ctx)))
        # 3 of 24 semantic items missing is 12.5%, above 10%: NOT RUN.
        opus21 = [p for p in runs["opus"] if p["item_id"] not in set(sem_ids[:3])]
        m1 = m.v2_checks(items, dict(runs, opus=opus21))[0]
        self.assertEqual((m1["status"], m1["value"]), (m.NOT_RUN, "opus answered 21 of 24; incomplete"))
        # 2 of 24 missing is 8.3%, at most 10%: computed, and the sentence says how many were answered.
        opus22 = [p for p in runs["opus"] if p["item_id"] not in set(sem_ids[:2])]
        ctx = report.compute_v2(items, dict(runs, opus=opus22))
        m1 = ctx["checks"][0]
        self.assertIn(m1["status"], (m.PASS, m.FAIL))
        self.assertIn("(opus 22 of 24 answered)", " ".join(report.reading_v2(ctx)))
        # jev misses 1 of 63 in the fixture (1.6%): H6 is computed and says so.
        self.assertIn("(jev 62 of 63 answered)", " ".join(report.reading_v2(ctx)))
        for s in sentences(report.reading_v2(ctx)):
            self.assertLessEqual(len(s.split()), 20, s)

    def test_v2fix3_derived_rows_show_model_counts(self):
        report, items, runs = v2_fixture()
        ctx = report.compute_v2(items, runs)
        rows = {r[0]: r for r in report.v2_arm_rows(ctx)}
        self.assertEqual(rows["jev"][1:3], ["62", "1"])  # the fixture leaves mech-0030 unanswered
        self.assertEqual(rows["cite_jev"][1:3], ["62", "1"])
        self.assertEqual(rows["cite_haiku"][1:3], rows["haiku"][1:3])

    def test_v2fix4_mixed_prompt_folder_is_refused(self):
        import report
        v2 = os.path.join(FIX, "v2")
        with tempfile.TemporaryDirectory() as tmp:
            runs_dir = os.path.join(tmp, "runs")
            os.makedirs(runs_dir)
            for name in os.listdir(os.path.join(v2, "runs")):
                with open(os.path.join(v2, "runs", name), encoding="utf-8") as f:
                    lines = [json.loads(x) for x in f if x.strip()]
                if name == "jev.jsonl":  # two v1 lines: one says v1, one has no prompt (v1 by default)
                    lines[0]["prompt"] = "v1"
                    del lines[1]["prompt"]
                with open(os.path.join(runs_dir, name), "w", encoding="utf-8") as f:
                    f.writelines(json.dumps(x) + "\n" for x in lines)
            base = [sys.executable, os.path.join(ROOT, "report.py"), "--data", os.path.join(v2, "items.jsonl"),
                    "--runs", runs_dir, "--out", os.path.join(tmp, "out")]
            res = subprocess.run(base + ["--prereg", "v2"], capture_output=True, text=True)
            self.assertEqual(res.returncode, 2)
            self.assertIn("jev: 2 of 62 lines", res.stderr)
            self.assertFalse(os.path.exists(os.path.join(tmp, "out", "report.md")))
            # v1 refuses a folder holding v2 lines
            res = subprocess.run(base + ["--prereg", "v1"], capture_output=True, text=True)
            self.assertEqual(res.returncode, 2)
            self.assertIn("haiku: 63 of 63 lines", res.stderr)
        runs, _ = report.load_runs(os.path.join(v2, "runs"))
        self.assertEqual(report.prompt_mismatches(runs, "v2"), {})
        self.assertEqual(report.prompt_mismatches(runs, "v1")["jev"], (62, 62))

    def test_v2fix5_four_decimals_near_a_bar(self):
        import report
        # 50 false items at p 0.01 .. 0.50; 50 true: 47 at 0.9, two at 0.001, one at 0.265.
        # 0.9 beats all 50 negatives: 47 * 50 = 2350. 0.001 beats none. 0.265 beats 0.01 .. 0.26: 26.
        # AUROC = 2376 / 2500 = 0.9504 > 0.95 -> FAIL, and it must not print as 0.950.
        items, opus = [], []
        for k in range(1, 51):
            items.append(v2item(f"n{k}", F, "semantic", "false_misread", words=3))
            opus.append(pred(f"n{k}", k / 100, "opus"))
        for k, p in enumerate([0.9] * 47 + [0.001, 0.001, 0.265]):
            items.append(v2item(f"p{k}", T, "semantic", "true_behavior", words=3))
            opus.append(pred(f"p{k}", p, "opus"))
        m1 = m.v2_checks(items, {"opus": opus})[0]
        self.assertAlmostEqual(m1["nums"]["auroc"], 2376 / 2500)
        self.assertEqual(m1["status"], m.FAIL)
        self.assertIn("0.9504", m1["value"])
        self.assertIn("0.9504, above the 0.95 ceiling", " ".join(report._v2_sentence(m1)))
        _, fx_items, runs = v2_fixture()
        ctx = report.compute_v2(fx_items, runs)
        rows = {r["id"]: r for r in ctx["checks"] + ctx["hypotheses"]}
        for hid in ("M2", "H6"):
            self.assertRegex(rows[hid]["value"], r"\d\.\d{4}\b", hid)
            self.assertRegex(" ".join(report._v2_sentence(rows[hid])), r"\d\.\d{4}\b", hid)


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
