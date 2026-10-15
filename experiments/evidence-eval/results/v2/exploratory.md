# v2 exploratory cuts (not preregistered)

Chosen after the v2 dataset audit. They are context for the preregistered verdict in report.md, which does not change.

## 1. Citation cut against rules that never read the claim

Citation cut: n = 50, 20 true. Claim-required subset (near_line, plus wrong_line items that cite_script passes): n = 30, 20 true.

| Scorer | Accuracy, citation cut | Accuracy, claim-required subset |
|---|---|---|
| accept everything | 0.400 | 0.667 |
| cited line within 2 of a changed line (pointer only) | 0.800 | 0.700 |
| cite_script | 0.760 | 0.667 |
| jev | 0.680 | 0.600 |
| haiku | 0.960 | 0.933 |
| opus | 0.980 | 0.967 |
| cite_jev | 0.760 | 0.600 |
| cite_haiku | 0.960 | 0.933 |

## 2. With and without the ambiguous pair p13

AUROC with the commit-bootstrap interval.

| Cut | n | jev | haiku | opus |
|---|---|---|---|---|
| semantic | 100 | 0.914 [0.858, 0.962] | 0.974 [0.948, 0.998] | 0.999 [0.995, 1.000] |
| semantic without p13 | 98 | 0.910 [0.853, 0.962] | 0.973 [0.947, 0.998] | 0.999 [0.994, 1.000] |
| claim-truth | 170 | 0.930 [0.892, 0.962] | 0.953 [0.924, 0.983] | 0.990 [0.973, 1.000] |
| claim-truth without p13 | 168 | 0.928 [0.890, 0.962] | 0.953 [0.923, 0.981] | 0.990 [0.973, 1.000] |

## 3. Where H1 and H2 come from

| Cut | n | jev | haiku | opus |
|---|---|---|---|---|
| mechanical claim-truth kinds | 70 | 0.975 [0.936, 0.998] | 0.951 [0.907, 0.990] | 0.987 [0.959, 1.000] |
| semantic | 100 | 0.914 [0.858, 0.962] | 0.974 [0.948, 0.998] | 0.999 [0.995, 1.000] |

mechanical claim-truth kinds: jev minus opus -0.012, commit CI [-0.050, +0.020].

mechanical claim-truth kinds: jev minus haiku +0.024, commit CI [-0.015, +0.063].

semantic: jev minus opus -0.085, commit CI [-0.140, -0.038].

semantic: jev minus haiku -0.060, commit CI [-0.126, -0.001].

## 4. Pair win rate per false kind

Share of pairs where the arm gives the true twin a higher p than its false twin. A tie counts half.

| False kind | pairs | jev | haiku | opus |
|---|---|---|---|---|
| false_causality | 11 | 1.000 | 1.000 | 1.000 |
| false_misread | 17 | 0.941 | 0.941 | 1.000 |
| false_outside_diff | 11 | 1.000 | 1.000 | 1.000 |
| false_overclaim | 11 | 0.909 | 1.000 | 1.000 |

