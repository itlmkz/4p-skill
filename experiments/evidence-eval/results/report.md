# Evidence Check Eval

Generated 2026-10-15 20:25 UTC. 211 items, arms: jev, haiku, opus, accept_all.

## Verdict

This report scores 4 arms on 211 findings. Each result uses the mechanical plus decoy cut when that cut is computable. H1 passes. Jev ranks supported findings above unsupported ones, AUROC 0.883, lower bound 0.823. H2 passes. The Jev calibration error is 0.087, inside the 0.10 bar. H3 fails. Jev AUROC is 0.883 and opus AUROC is 0.953. Jev costs 1/362.7 of opus per item. Jev falls more than 0.05 below opus. H3 differs between the two cuts. The mechanical plus decoy cut decides it: fail. H4 fails. Jev leads haiku by +0.03 AUROC, but the interval includes 0. H5 passes. Jev gives p of 0.2 or less on each of the 4 empty diffs. Jev passes H1 but fails H3 and H4. Read the failed rows before any product work.

| ID | Hypothesis | Bar | All items | Mechanical + decoy | Decided |
|---|---|---|---|---|---|
| H1 | Jev separates supported from unsupported findings | AUROC >= 0.80 and 95% lower bound >= 0.70 | PASS: AUROC 0.936, 95% CI [0.899, 0.966] | PASS: AUROC 0.883, 95% CI [0.823, 0.933] | PASS |
| H2 | Jev is calibrated enough to threshold | ECE <= 0.10 | PASS: ECE 0.054 | PASS: ECE 0.087 | PASS |
| H3 | Jev is a viable cheap substitute for the coordinator | Jev AUROC no more than 0.05 below opus, at 1/20 of opus cost per item or less | PASS: AUROC jev 0.936 vs opus 0.972 (gap -0.036); cost per item $0.000079 vs $0.0290, cost ratio 1/369.2; n=211 | FAIL: AUROC jev 0.883 vs opus 0.953 (gap -0.069); cost per item $0.000096 vs $0.0348, cost ratio 1/362.7; n=132 | FAIL (cuts differ) |
| H4 | Jev specifically matters | Jev AUROC beats haiku and the 95% CI of the difference excludes 0 | FAIL: AUROC jev minus haiku +0.024, 95% CI [-0.011, +0.060]; n=211 | FAIL: AUROC jev minus haiku +0.030, 95% CI [-0.022, +0.082]; n=132 | FAIL |
| H5 | Jev survives decoys | p <= 0.2 on every empty_diff item | PASS: all 4 empty_diff items at p <= 0.2 (max 0.08) | PASS: all 4 empty_diff items at p <= 0.2 (max 0.08) | PASS |

The mechanical + decoy cut is labeled by a script. PREREG.md says it decides a conflict.

## Per-arm results

| Arm | n | Not answered | AUROC [95% CI], all | AUROC [95% CI], mech + decoy | Brier | ECE | Cost per item | Total cost | p50 latency | Errors |
|---|---|---|---|---|---|---|---|---|---|---|
| jev | 211 | 0 | 0.936 [0.899, 0.966] | 0.883 [0.823, 0.933] | 0.103 | 0.054 | $0.000079 | $0.0166 | 0.56 s | 0 |
| haiku | 211 | 0 | 0.912 [0.870, 0.949] | 0.853 [0.784, 0.911] | 0.120 | 0.091 | $0.000840 | $0.1772 | 5.43 s | 0 |
| opus | 211 | 0 | 0.972 [0.950, 0.989] | 0.953 [0.915, 0.982] | 0.065 | 0.063 | $0.0290 | $6.1204 | 5.90 s | 0 |
| accept_all | 211 | 0 | 0.500 [0.500, 0.500] | 0.500 [0.500, 0.500] | 0.512 | 0.512 | $0.0000 | $0.0000 | 0.00 s | 0 |

n is the number answered. Errors and unanswered items count as p = 0.5. Cost and latency are over the answered items.

## Per tier

| Tier | n (true) | jev: AUROC / acc | haiku: AUROC / acc | opus: AUROC / acc | accept_all: AUROC / acc |
|---|---|---|---|---|---|
| mechanical | 120 (60) | 0.875 / 0.80 | 0.844 / 0.77 | 0.952 / 0.88 | 0.500 / 0.50 |
| semantic | 79 (39) | 1.000 / 0.96 | 0.998 / 0.94 | 1.000 / 0.92 | 0.500 / 0.49 |
| decoy | 12 (4) | 1.000 / 0.92 | 0.969 / 0.92 | 1.000 / 0.83 | 0.500 / 0.33 |

## Per kind

Most kinds hold one label only, so AUROC is not computable there. Accuracy reads p >= 0.5 as supported.

| Tier | Kind | n (true) | jev: acc (mean p) | haiku: acc (mean p) | opus: acc (mean p) | accept_all: acc (mean p) |
|---|---|---|---|---|---|---|
| mechanical | fabricated | 15 (0) | 0.87 (0.18) | 0.93 (0.11) | 1.00 (0.04) | 0.00 (1.00) |
| mechanical | negated | 15 (0) | 0.87 (0.11) | 1.00 (0.04) | 1.00 (0.02) | 0.00 (1.00) |
| mechanical | true_added | 30 (30) | 1.00 (0.89) | 0.90 (0.83) | 0.93 (0.87) | 1.00 (1.00) |
| mechanical | true_removed | 30 (30) | 0.83 (0.70) | 0.57 (0.54) | 0.90 (0.81) | 1.00 (1.00) |
| mechanical | wrong_file | 15 (0) | 0.87 (0.32) | 1.00 (0.20) | 1.00 (0.12) | 0.00 (1.00) |
| mechanical | wrong_line | 15 (0) | 0.13 (0.75) | 0.27 (0.62) | 0.40 (0.54) | 0.00 (1.00) |
| semantic | false_causality | 10 (0) | 0.80 (0.21) | 1.00 (0.04) | 1.00 (0.04) | 0.00 (1.00) |
| semantic | false_misread | 10 (0) | 1.00 (0.09) | 1.00 (0.03) | 1.00 (0.03) | 0.00 (1.00) |
| semantic | false_outside_diff | 10 (0) | 0.90 (0.29) | 0.50 (0.43) | 0.40 (0.43) | 0.00 (1.00) |
| semantic | false_overclaim | 10 (0) | 1.00 (0.11) | 1.00 (0.08) | 1.00 (0.04) | 0.00 (1.00) |
| semantic | true_behavior | 39 (39) | 1.00 (0.90) | 1.00 (0.91) | 1.00 (0.94) | 1.00 (1.00) |
| decoy | empty_diff | 4 (0) | 1.00 (0.06) | 1.00 (0.03) | 1.00 (0.02) | 0.00 (1.00) |
| decoy | right_claim_wrong_line | 4 (4) | 0.75 (0.63) | 0.75 (0.52) | 0.50 (0.50) | 1.00 (1.00) |
| decoy | truncated_evidence | 4 (0) | 1.00 (0.05) | 1.00 (0.04) | 1.00 (0.03) | 0.00 (1.00) |

## Decision cost

Reject when p < t = 1 / (1 + R). Rejecting a true finding costs R; accepting a false finding costs 1. Precision and recall are of reject.

| Arm | R | Threshold t | Mean cost per item | Reject precision | Reject recall | Rejected |
|---|---|---|---|---|---|---|
| jev | 5 | 0.167 | 0.280 | 0.97 | 0.55 | 61 of 211 |
| haiku | 5 | 0.167 | 0.427 | 0.87 | 0.68 | 84 of 211 |
| opus | 5 | 0.167 | 0.171 | 0.98 | 0.76 | 84 of 211 |
| accept_all | 5 | 0.167 | 0.512 | not computable | 0.00 | 0 of 211 |
| jev | 10 | 0.091 | 0.270 | 1.00 | 0.47 | 51 of 211 |
| haiku | 10 | 0.091 | 0.682 | 0.86 | 0.59 | 74 of 211 |
| opus | 10 | 0.091 | 0.190 | 1.00 | 0.63 | 68 of 211 |
| accept_all | 10 | 0.091 | 0.512 | not computable | 0.00 | 0 of 211 |
| jev | 20 | 0.048 | 0.332 | 1.00 | 0.35 | 38 of 211 |
| haiku | 20 | 0.048 | 0.825 | 0.90 | 0.50 | 60 of 211 |
| opus | 20 | 0.048 | 0.223 | 1.00 | 0.56 | 61 of 211 |
| accept_all | 20 | 0.048 | 0.512 | not computable | 0.00 | 0 of 211 |

## Decoy behavior (H5)

H5 needs p <= 0.2 from jev on every empty_diff item.

| Item | Kind | Label | jev | haiku | opus | accept_all | H5 (jev) |
|---|---|---|---|---|---|---|---|
| decoy-001 | empty_diff | false | 0.04 | 0.02 | 0.02 | 1.00 | PASS |
| decoy-002 | empty_diff | false | 0.08 | 0.05 | 0.02 | 1.00 | PASS |
| decoy-003 | empty_diff | false | 0.03 | 0.02 | 0.02 | 1.00 | PASS |
| decoy-004 | empty_diff | false | 0.08 | 0.02 | 0.02 | 1.00 | PASS |
| decoy-005 | truncated_evidence | false | 0.03 | 0.02 | 0.02 | 1.00 | n/a |
| decoy-006 | truncated_evidence | false | 0.06 | 0.02 | 0.03 | 1.00 | n/a |
| decoy-007 | truncated_evidence | false | 0.04 | 0.03 | 0.02 | 1.00 | n/a |
| decoy-008 | truncated_evidence | false | 0.06 | 0.10 | 0.03 | 1.00 | n/a |
| decoy-009 | right_claim_wrong_line | true | 0.58 | 0.62 | 0.45 | 1.00 | n/a |
| decoy-010 | right_claim_wrong_line | true | 0.34 | 0.08 | 0.55 | 1.00 | n/a |
| decoy-011 | right_claim_wrong_line | true | 0.95 | 0.82 | 0.55 | 1.00 | n/a |
| decoy-012 | right_claim_wrong_line | true | 0.65 | 0.55 | 0.45 | 1.00 | n/a |

## Errors

No errors.

## Known threats (from PREREG.md)

- The semantic tier is written and labeled by Claude agents, which share a family with the `opus` arm. That can inflate `opus` on that tier. The mechanical and decoy tiers are labeled by a script, so H1 to H4 are also reported on those tiers alone, and that cut decides a conflict.
- Diffs come from a small number of public repositories. The result says how the arms behave on code like this, not on all code.
- Two known tells, found while building the data and listed before any paid run: a `wrong_file` item that cites a file outside the diff keeps the true line number, which can exceed that file's length, and a `truncated_evidence` diff ends cleanly at a hunk boundary. Both make those items easier than a real mistake. Per-kind results show whether an arm leans on them.
- Four mechanical items (mech-0006, -0054, -0067, -0102) quote a real commit whose diff text contains em dashes. They are kept, because editing them would change the commit.
- The `opus` arm sees a json state, not a live session. A real coordinator also has the repo. So `opus` here is a lower bound on the coordinator.

## Reproduce

```sh
cd experiments/evidence-eval
python3 build_dataset.py            # mechanical and decoy tiers, seed 7
python3 run_eval.py --dry-run       # fake arm, no network, writes results/dry-run
python3 run_eval.py --pilot         # 1 item per tier, spend table, stops above the cap
python3 run_eval.py                 # the paid run into results/runs, budget cap in the runner
python3 report.py
python3 tests/metrics.test.py       # pins every metric to a hand-computed value
```

Inputs:

- `/Users/mm/dev/4p-skill-fix/experiments/evidence-eval/data/mechanical.jsonl` sha256 88487b0e28b6, 120 lines
- `/Users/mm/dev/4p-skill-fix/experiments/evidence-eval/data/decoy.jsonl` sha256 dea182b17046, 12 lines
- `/Users/mm/dev/4p-skill-fix/experiments/evidence-eval/data/semantic.jsonl` sha256 6f02ea1df074, 79 lines
- `/Users/mm/dev/4p-skill-fix/experiments/evidence-eval/results/runs/jev.jsonl` sha256 29a2c1e07341, 211 lines
- `/Users/mm/dev/4p-skill-fix/experiments/evidence-eval/results/runs/haiku.jsonl` sha256 f30f048285b6, 211 lines
- `/Users/mm/dev/4p-skill-fix/experiments/evidence-eval/results/runs/opus.jsonl` sha256 58ac6b532081, 211 lines
- `/Users/mm/dev/4p-skill-fix/experiments/evidence-eval/results/runs/accept_all.jsonl` sha256 0c3d6c7a9e23, 211 lines
