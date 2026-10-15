# Exploratory cuts (not preregistered)

These cuts were chosen after the dataset audit, so they are hypotheses for the next eval, not results. The preregistered verdict is in report.md and does not change.

## 1. Claim truth, without citation strictness

Mechanical items of kind fabricated, negated, true_added, true_removed: n = 90, 60 true.

| Arm | AUROC | Item CI | Commit CI |
|---|---|---|---|
| jev | 0.976 | [0.944, 0.995] | [0.945, 0.996] |
| haiku | 0.936 | [0.882, 0.977] | [0.873, 0.982] |
| opus | 0.998 | [0.993, 1.000] | [0.993, 1.000] |

Jev minus opus: -0.022, item CI [-0.052, -0.005].

Jev minus haiku: +0.041, item CI [+0.008, +0.085].

## 2. Semantic tier against a length-only baseline

n = 79, 39 true. The baseline scores each claim by its word count and reads no diff.

| Scorer | AUROC | Item CI |
|---|---|---|
| claim length only | 0.809 | [0.708, 0.895] |
| jev | 1.000 | [1.000, 1.000] |
| haiku | 0.998 | [0.991, 1.000] |
| opus | 1.000 | [1.000, 1.000] |

Within short claims (n = 39, 11 true, split at 18 words): jev 1.000, haiku 0.994, opus 1.000.

Within long claims (n = 40, 28 true, split at 18 words): jev 1.000, haiku 1.000, opus 1.000.

## 3. Decision cost at R = 10, with and without false_outside_diff

| Arm | All items | Without false_outside_diff |
|---|---|---|
| jev | 0.270 | 0.239 |
| haiku | 0.682 | 0.672 |
| opus | 0.190 | 0.154 |

## 4. Item bootstrap against commit bootstrap, mechanical plus decoy

| Arm | AUROC | Item CI | Commit CI |
|---|---|---|---|
| jev | 0.883 | [0.823, 0.933] | [0.812, 0.949] |
| haiku | 0.853 | [0.784, 0.911] | [0.778, 0.925] |
| opus | 0.953 | [0.915, 0.982] | [0.911, 0.986] |

