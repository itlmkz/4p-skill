# Evidence Check Eval v2

Generated 2026-10-15 21:34 UTC. 232 items, arms: jev, haiku, opus, accept_all, cite_script, cite_jev, cite_haiku. Preregistration: PREREG-v2.md.

## Manipulation checks

| ID | Check | Cut | Pass when | Result |
|---|---|---|---|---|
| M1 | The semantic tier is not at the ceiling | semantic | opus AUROC on the semantic tier <= 0.95 | FAIL: opus AUROC on the semantic tier 0.9986; n=100 |
| M2 | The length shortcut is gone | semantic | AUROC of claim word count against the label is between 0.35 and 0.65 | PASS: claim word count AUROC 0.5034; n=100 |

Semantic tier used in H1 and H2: no. The semantic tier is a known defect here. H1 and H2 use the mechanical claim-truth kinds alone.

## Verdict

This report scores 7 arms on 232 findings. It follows PREREG-v2.md. Intervals resample whole commits. M1 fails. Opus AUROC on the semantic tier is 0.9986, above the 0.95 ceiling. M2 passes. Claim length predicts the semantic label at AUROC 0.5034, inside 0.35 to 0.65. The semantic tier is a known defect here. H1 and H2 use the mechanical claim-truth kinds alone. H1 passes. Jev AUROC on claim truth is 0.975, and Jev minus Opus is -0.012. H2 fails. Jev leads Haiku by +0.024 AUROC, but the commit interval includes 0. H3 fails. Jev accuracy on the citation cut is 0.68, below the 0.70 bar. H4 fails. At R = 10 the split design has decision cost 0.349, against 0.246 for Opus. cite_jev costs 1/370.3 of opus per item. Its decision cost is more than 0.05 above Opus. H5 fails. The split design rejects 1 true findings at R = 10. H6 passes. Jev calibration error on all items is 0.0929, inside the 0.10 bar. Failed bars: H2, H3, H4, H5. Read those rows before any product work.

| ID | Hypothesis | Cut | Pass when | Result |
|---|---|---|---|---|
| H1 | Jev checks claims about as well as Opus | claim-truth, mechanical kinds only | Jev AUROC >= 0.90 and Jev minus Opus >= -0.05 | PASS: jev AUROC 0.975, commit CI [0.936, 0.998]; opus 0.987; jev minus opus -0.012; n=70 |
| H2 | Jev checks claims better than Haiku | claim-truth, mechanical kinds only | Jev minus Haiku AUROC > 0 and its commit-bootstrap lower bound > 0 | FAIL: jev minus haiku AUROC +0.024, commit CI [-0.015, +0.063]; item CI [-0.011, +0.070]; n=70 |
| H3 | Told the rule, Jev applies it | citation | Jev accuracy (p >= 0.5 read as supported) >= 0.70 | FAIL: jev accuracy on the citation cut 0.680; n=50 |
| H4 | The split design is as good as Opus at a fraction of the cost | all | cite_jev decision cost at R = 10 <= opus + 0.05, and cite_jev costs 1/20 of opus per item or less | FAIL: decision cost at R = 10: cite_jev 0.349 vs opus 0.246; cost per item $0.000065 vs $0.0241, cost ratio 1/370.3 |
| H5 | The split design is a safe gate | all | cite_jev rejects no true finding at R = 10 (reject precision 1.00) | FAIL: reject precision 0.98; 1 true of 52 rejected |
| H6 | Jev stays calibrated | all | Jev ECE <= 0.10 | PASS: jev ECE on all items 0.0929; n=232 |

## Per-arm results

| Arm | n | Not answered | AUROC [commit CI], all | Item CI | Brier | ECE | Cost per item | Total cost | p50 latency | Errors |
|---|---|---|---|---|---|---|---|---|---|---|
| jev | 232 | 0 | 0.898 [0.860, 0.933] | [0.855, 0.936] | 0.139 | 0.093 | $0.000065 | $0.0151 | 2.25 s | 0 |
| haiku | 232 | 0 | 0.950 [0.919, 0.978] | [0.916, 0.977] | 0.078 | 0.066 | $0.000763 | $0.1769 | 8.62 s | 0 |
| opus | 232 | 0 | 0.992 [0.978, 1.000] | [0.978, 1.000] | 0.026 | 0.066 | $0.0241 | $5.5952 | 8.14 s | 0 |
| accept_all | 232 | 0 | 0.500 [0.500, 0.500] | [0.500, 0.500] | 0.526 | 0.526 | $0.0000 | $0.0000 | 0.00 s | 0 |
| cite_script | 232 | 0 | 0.615 [0.578, 0.654] | [0.579, 0.654] | 0.367 | 0.367 | $0.0000 | $0.0000 | 0.00 s | 0 |
| cite_jev | 232 | 0 | 0.919 [0.885, 0.951] | [0.880, 0.951] | 0.124 | 0.071 | $0.000065 | $0.0151 | 2.25 s | see model arm |
| cite_haiku | 232 | 0 | 0.954 [0.926, 0.979] | [0.922, 0.979] | 0.078 | 0.065 | $0.000763 | $0.1769 | 8.62 s | see model arm |

n is the number answered. Errors and unanswered items count as p = 0.5. Derived arms take the model arm's p when cite_script passes, else 0.02, and cost what the model arm costs.

## Per cut

claim-truth: mechanical true_added, true_removed, negated, fabricated, plus the semantic tier. citation: mechanical near_line, wrong_line, wrong_file. Accuracy reads p >= 0.5 as supported.

| Arm | Cut | n | AUROC | Commit CI | Item CI | Accuracy |
|---|---|---|---|---|---|---|
| jev | claim-truth (mechanical only) | 70 | 0.975 | [0.936, 0.998] | [0.937, 0.998] | 0.91 |
| jev | citation | 50 | 0.728 | [0.592, 0.860] | [0.581, 0.864] | 0.68 |
| jev | all | 232 | 0.898 | [0.860, 0.933] | [0.855, 0.936] | 0.80 |
| haiku | claim-truth (mechanical only) | 70 | 0.951 | [0.907, 0.990] | [0.893, 0.990] | 0.89 |
| haiku | citation | 50 | 0.946 | [0.826, 1.000] | [0.839, 1.000] | 0.96 |
| haiku | all | 232 | 0.950 | [0.919, 0.978] | [0.916, 0.977] | 0.90 |
| opus | claim-truth (mechanical only) | 70 | 0.987 | [0.959, 1.000] | [0.953, 1.000] | 0.97 |
| opus | citation | 50 | 0.999 | [0.996, 1.000] | [0.995, 1.000] | 0.98 |
| opus | all | 232 | 0.992 | [0.978, 1.000] | [0.978, 1.000] | 0.97 |
| accept_all | claim-truth (mechanical only) | 70 | 0.500 | [0.500, 0.500] | [0.500, 0.500] | 0.57 |
| accept_all | citation | 50 | 0.500 | [0.500, 0.500] | [0.500, 0.500] | 0.40 |
| accept_all | all | 232 | 0.500 | [0.500, 0.500] | [0.500, 0.500] | 0.47 |
| cite_script | claim-truth (mechanical only) | 70 | 0.500 | [0.500, 0.500] | [0.500, 0.500] | 0.57 |
| cite_script | citation | 50 | 0.800 | [0.712, 0.900] | [0.705, 0.887] | 0.76 |
| cite_script | all | 232 | 0.615 | [0.578, 0.654] | [0.579, 0.654] | 0.59 |
| cite_jev | claim-truth (mechanical only) | 70 | 0.975 | [0.936, 0.998] | [0.937, 0.998] | 0.91 |
| cite_jev | citation | 50 | 0.836 | [0.713, 0.958] | [0.709, 0.938] | 0.76 |
| cite_jev | all | 232 | 0.919 | [0.885, 0.951] | [0.880, 0.951] | 0.81 |
| cite_haiku | claim-truth (mechanical only) | 70 | 0.951 | [0.907, 0.990] | [0.893, 0.990] | 0.89 |
| cite_haiku | citation | 50 | 0.961 | [0.878, 1.000] | [0.878, 1.000] | 0.96 |
| cite_haiku | all | 232 | 0.954 | [0.926, 0.979] | [0.922, 0.979] | 0.90 |

## Semantic pairs

Each semantic pair holds one true claim and one false twin on the same evidence. The share counts pairs where the arm gives the true twin the higher p. Ties count half. Unanswered items count as p = 0.5.

| Arm | Pairs | True twin higher | Commit CI |
|---|---|---|---|
| jev | 50 | 0.960 | [0.898, 1.000] |
| haiku | 50 | 0.980 | [0.950, 1.000] |
| opus | 50 | 1.000 | [1.000, 1.000] |
| accept_all | 50 | 0.500 | [0.500, 0.500] |
| cite_script | 50 | 0.500 | [0.500, 0.500] |
| cite_jev | 50 | 0.960 | [0.898, 1.000] |
| cite_haiku | 50 | 0.980 | [0.950, 1.000] |

## Per tier

| Tier | n (true) | jev: AUROC / acc | haiku: AUROC / acc | opus: AUROC / acc | accept_all: AUROC / acc | cite_script: AUROC / acc | cite_jev: AUROC / acc | cite_haiku: AUROC / acc |
|---|---|---|---|---|---|---|---|---|
| mechanical | 120 (60) | 0.874 / 0.82 | 0.942 / 0.92 | 0.989 / 0.97 | 0.500 / 0.50 | 0.650 / 0.65 | 0.919 / 0.85 | 0.953 / 0.92 |
| semantic | 100 (50) | 0.914 / 0.75 | 0.974 / 0.87 | 0.999 / 0.96 | 0.500 / 0.50 | 0.500 / 0.50 | 0.914 / 0.75 | 0.974 / 0.87 |
| decoy | 12 (0) | not computable / 1.00 | not computable / 0.92 | not computable / 1.00 | not computable / 0.00 | not computable / 0.83 | not computable / 1.00 | not computable / 0.92 |

## Per kind

Most kinds hold one label only, so AUROC is not computable there. Accuracy reads p >= 0.5 as supported.

| Tier | Kind | n (true) | jev: acc (mean p) | haiku: acc (mean p) | opus: acc (mean p) | accept_all: acc (mean p) | cite_script: acc (mean p) | cite_jev: acc (mean p) | cite_haiku: acc (mean p) |
|---|---|---|---|---|---|---|---|---|---|
| mechanical | fabricated | 15 (0) | 0.80 (0.25) | 0.73 (0.24) | 1.00 (0.09) | 0.00 (1.00) | 0.00 (0.95) | 0.80 (0.25) | 0.73 (0.24) |
| mechanical | near_line | 20 (20) | 0.90 (0.74) | 0.90 (0.75) | 0.95 (0.86) | 1.00 (1.00) | 1.00 (0.95) | 0.90 (0.74) | 0.90 (0.75) |
| mechanical | negated | 15 (0) | 1.00 (0.09) | 1.00 (0.08) | 1.00 (0.03) | 0.00 (1.00) | 0.00 (0.95) | 1.00 (0.09) | 1.00 (0.08) |
| mechanical | true_added | 20 (20) | 1.00 (0.91) | 1.00 (0.94) | 1.00 (0.94) | 1.00 (1.00) | 1.00 (0.95) | 1.00 (0.91) | 1.00 (0.94) |
| mechanical | true_removed | 20 (20) | 0.85 (0.72) | 0.80 (0.75) | 0.90 (0.84) | 1.00 (1.00) | 1.00 (0.95) | 0.85 (0.72) | 0.80 (0.75) |
| mechanical | wrong_file | 15 (0) | 1.00 (0.07) | 1.00 (0.03) | 1.00 (0.03) | 0.00 (1.00) | 0.87 (0.17) | 1.00 (0.03) | 1.00 (0.02) |
| mechanical | wrong_line | 15 (0) | 0.07 (0.76) | 1.00 (0.11) | 1.00 (0.10) | 0.00 (1.00) | 0.33 (0.65) | 0.33 (0.51) | 1.00 (0.08) |
| semantic | false_causality | 11 (0) | 0.36 (0.52) | 0.64 (0.36) | 1.00 (0.12) | 0.00 (1.00) | 0.00 (0.95) | 0.36 (0.52) | 0.64 (0.36) |
| semantic | false_misread | 17 (0) | 0.53 (0.41) | 0.82 (0.21) | 1.00 (0.06) | 0.00 (1.00) | 0.00 (0.95) | 0.53 (0.41) | 0.82 (0.21) |
| semantic | false_outside_diff | 11 (0) | 0.64 (0.42) | 0.55 (0.44) | 0.64 (0.36) | 0.00 (1.00) | 0.00 (0.95) | 0.64 (0.42) | 0.55 (0.44) |
| semantic | false_overclaim | 11 (0) | 0.55 (0.47) | 0.91 (0.22) | 1.00 (0.10) | 0.00 (1.00) | 0.00 (0.95) | 0.55 (0.47) | 0.91 (0.22) |
| semantic | true_behavior | 50 (50) | 0.98 (0.85) | 1.00 (0.93) | 1.00 (0.94) | 1.00 (1.00) | 1.00 (0.95) | 0.98 (0.85) | 1.00 (0.93) |
| decoy | empty_diff | 6 (0) | 1.00 (0.05) | 1.00 (0.02) | 1.00 (0.01) | 0.00 (1.00) | 1.00 (0.05) | 1.00 (0.02) | 1.00 (0.02) |
| decoy | truncated_evidence | 6 (0) | 1.00 (0.21) | 0.83 (0.12) | 1.00 (0.07) | 0.00 (1.00) | 0.67 (0.35) | 1.00 (0.10) | 0.83 (0.12) |

## Decision cost

Reject when p < t = 1 / (1 + R). Rejecting a true finding costs R; accepting a false finding costs 1. Precision and recall are of reject. H4 and H5 read R = 10.

| Arm | R | Threshold t | Mean cost per item | Reject precision | Reject recall | Rejected |
|---|---|---|---|---|---|---|
| jev | 5 | 0.167 | 0.319 | 0.98 | 0.43 | 54 of 232 |
| haiku | 5 | 0.167 | 0.272 | 0.94 | 0.69 | 89 of 232 |
| opus | 5 | 0.167 | 0.099 | 0.99 | 0.85 | 105 of 232 |
| accept_all | 5 | 0.167 | 0.526 | not computable | 0.00 | 0 of 232 |
| cite_script | 5 | 0.167 | 0.405 | 1.00 | 0.23 | 28 of 232 |
| cite_jev | 5 | 0.167 | 0.284 | 0.98 | 0.50 | 62 of 232 |
| cite_haiku | 5 | 0.167 | 0.267 | 0.94 | 0.70 | 90 of 232 |
| jev | 10 | 0.091 | 0.397 | 0.98 | 0.33 | 41 of 232 |
| haiku | 10 | 0.091 | 0.401 | 0.95 | 0.57 | 73 of 232 |
| opus | 10 | 0.091 | 0.246 | 0.99 | 0.61 | 76 of 232 |
| accept_all | 10 | 0.091 | 0.526 | not computable | 0.00 | 0 of 232 |
| cite_script | 10 | 0.091 | 0.405 | 1.00 | 0.23 | 28 of 232 |
| cite_jev | 10 | 0.091 | 0.349 | 0.98 | 0.42 | 52 of 232 |
| cite_haiku | 10 | 0.091 | 0.384 | 0.95 | 0.60 | 77 of 232 |
| jev | 20 | 0.048 | 0.427 | 1.00 | 0.19 | 23 of 232 |
| haiku | 20 | 0.048 | 0.664 | 0.92 | 0.39 | 52 of 232 |
| opus | 20 | 0.048 | 0.379 | 0.98 | 0.44 | 55 of 232 |
| accept_all | 20 | 0.048 | 0.526 | not computable | 0.00 | 0 of 232 |
| cite_script | 20 | 0.048 | 0.526 | not computable | 0.00 | 0 of 232 |
| cite_jev | 20 | 0.048 | 0.349 | 1.00 | 0.34 | 41 of 232 |
| cite_haiku | 20 | 0.048 | 0.629 | 0.93 | 0.46 | 60 of 232 |

## Decoy behavior

| Item | Kind | Label | jev | haiku | opus | accept_all | cite_script | cite_jev | cite_haiku |
|---|---|---|---|---|---|---|---|---|---|
| decoy2-001 | empty_diff | false | 0.06 | 0.02 | 0.02 | 1.00 | 0.05 | 0.02 | 0.02 |
| decoy2-002 | empty_diff | false | 0.05 | 0.00 | 0.00 | 1.00 | 0.05 | 0.02 | 0.02 |
| decoy2-003 | empty_diff | false | 0.04 | 0.02 | 0.02 | 1.00 | 0.05 | 0.02 | 0.02 |
| decoy2-004 | empty_diff | false | 0.04 | 0.02 | 0.02 | 1.00 | 0.05 | 0.02 | 0.02 |
| decoy2-005 | empty_diff | false | 0.04 | 0.02 | 0.00 | 1.00 | 0.05 | 0.02 | 0.02 |
| decoy2-006 | empty_diff | false | 0.04 | 0.05 | 0.02 | 1.00 | 0.05 | 0.02 | 0.02 |
| decoy2-007 | truncated_evidence | false | 0.22 | 0.03 | 0.05 | 1.00 | 0.05 | 0.02 | 0.02 |
| decoy2-008 | truncated_evidence | false | 0.20 | 0.02 | 0.03 | 1.00 | 0.95 | 0.20 | 0.02 |
| decoy2-009 | truncated_evidence | false | 0.07 | 0.02 | 0.02 | 1.00 | 0.05 | 0.02 | 0.02 |
| decoy2-010 | truncated_evidence | false | 0.33 | 0.05 | 0.10 | 1.00 | 0.05 | 0.02 | 0.02 |
| decoy2-011 | truncated_evidence | false | 0.12 | 0.03 | 0.05 | 1.00 | 0.05 | 0.02 | 0.02 |
| decoy2-012 | truncated_evidence | false | 0.34 | 0.60 | 0.20 | 1.00 | 0.95 | 0.34 | 0.60 |

## Errors

No errors.

## What changed from v1

- New data: no v1 item, commit or repository is reused.
- Prompt v2: every model arm is told the citation rule, word for word.
- New arms: cite_script (a deterministic citation check) and the derived split arms cite_jev and cite_haiku.
- New cuts: claim-truth and citation, next to all items. The v1 mechanical + decoy cut is gone.
- Commit-level bootstrap is the primary interval, because items share diffs. Item intervals are still shown.
- Manipulation checks M1 and M2 decide if the semantic tier counts in H1 and H2.
- New bars H1 to H6. v1 H1 to H5 do not carry over; read each v2 bar on its own cut.
- The semantic tier comes in true and false pairs, so the report adds a pair-level win rate.

## Known threats (from PREREG-v2.md)

- Items are still written and labeled by Claude agents, which share a family with the `haiku` and `opus` arms. The mechanical tier is labeled by a script.
- `cite_script` checks the citation against any changed line, because it does not read the claim. So it cannot see a citation that points at the wrong changed line. Measured offline on the v2 data before any paid call: it catches 5 of 15 `wrong_line`, 13 of 15 `wrong_file` and 4 of 6 `truncated_evidence`, and passes every true item. An earlier draft of this note said the script was near-perfect on the citation cut by design. That was wrong, and the arm is unchanged. H4 and H5 measure whether the split design works end to end.
- The chat arms keep the v1 transport: the local `claude` CLI with all context stripped. It adds a short identity line and environment message, as v1 deviation 1 records.
- Prompt v2 states the rule; v1 did not. A v1 to v2 change mixes the rule with new data. Only the citation cut isolates the rule.

## Reproduce

```sh
cd experiments/evidence-eval
python3 build_dataset.py --check    # re-derive the mechanical labels
python3 run_eval.py --prompt v2 --pilot    # v2 data, arms, $10 cap and results/v2/runs are the v2 defaults
python3 run_eval.py --prompt v2
python3 report.py --prereg v2
python3 tests/metrics.test.py       # pins every metric to a hand-computed value
```

Inputs:

- `/Users/mm/dev/4p-skill-fix/experiments/evidence-eval/data/v2/mechanical.jsonl` sha256 f0a93977ddaa, 120 lines
- `/Users/mm/dev/4p-skill-fix/experiments/evidence-eval/data/v2/decoy.jsonl` sha256 3d131a7eedc4, 12 lines
- `/Users/mm/dev/4p-skill-fix/experiments/evidence-eval/data/v2/semantic.jsonl` sha256 197503f8d5ac, 100 lines
- `/Users/mm/dev/4p-skill-fix/experiments/evidence-eval/results/v2/runs/jev.jsonl` sha256 71ddaddc5778, 232 lines
- `/Users/mm/dev/4p-skill-fix/experiments/evidence-eval/results/v2/runs/haiku.jsonl` sha256 b497091be21f, 232 lines
- `/Users/mm/dev/4p-skill-fix/experiments/evidence-eval/results/v2/runs/opus.jsonl` sha256 2c9236ae6d38, 232 lines
- `/Users/mm/dev/4p-skill-fix/experiments/evidence-eval/results/v2/runs/accept_all.jsonl` sha256 453abf80a61b, 232 lines
- `/Users/mm/dev/4p-skill-fix/experiments/evidence-eval/results/v2/runs/cite_script.jsonl` sha256 cac8fec2cda4, 232 lines
