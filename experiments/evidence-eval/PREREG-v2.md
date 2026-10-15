# Preregistration v2: the split evidence check

Written 2026-10-15, after v1 and before any v2 paid call. v1 is in `PREREG.md`
and `results/report.md`. Bars, arms and stop rules below do not change after v2
results arrive. A change after that point is reported as a deviation.

## Why a v2

v1 passed H1, H2 and H5 and failed H3 and H4. Its post-hoc cuts suggested three
things, which v2 tests as preregistered hypotheses:

1. The failures came from citation strictness. No arm was told the citation
   rule, and no arm enforced it.
2. On claim truth alone, Jev nearly matched Opus and beat Haiku.
3. The v1 semantic tier was at the ceiling for every arm, and claim length
   alone predicted its label at AUROC 0.81.

v2 therefore tells every arm the rule, tests the split design directly (a script
checks the citation, a model checks the claim), and uses a semantic tier built
to be hard and free of the length shortcut.

## Data, all new

No v1 item, commit or repository is reused, so v2 also tests whether v1
generalizes. Diffs come only from public repositories, at most 12000 chars.

| Tier | Target | Label basis | Kinds |
| --- | --- | --- | --- |
| mechanical | about 120, half true | construction, re-proven by `build_dataset.py --check` | `true_added`, `true_removed`, `near_line` (true, cited 1 to 5 lines off), `wrong_line` (false, cited 6 to 15 lines off), `wrong_file`, `negated`, `fabricated` |
| semantic | about 100, in pairs | double review, blind second labeler, only agreed pairs kept | each pair is one `true_behavior` claim and one false twin on the same evidence: `false_misread`, `false_overclaim`, `false_causality`, `false_outside_diff` |
| decoy | about 12 | construction | `empty_diff`, `truncated_evidence` |

Semantic pairs are built to remove the v1 shortcut: the two claims of a pair cite
the same line and differ in length by at most 2 words. A claim opener such as
"Because", "Since", "Every", or "X means Y" appears equally often in true and
false claims, or not at all.

Files: `data/v2/mechanical.jsonl`, `data/v2/decoy.jsonl`, `data/v2/semantic.jsonl`.
Item schema is the v1 schema plus `pair` (semantic only, the shared pair id).

## The question, now with the rule

Prompt version `v2`. Every model arm gets the v1 question plus this rule, word
for word:

> A citation supports the claim only when the cited file is in the diff and the
> cited line is within 5 lines of the code that supports the claim. Line numbers
> count in the new file for added and unchanged lines, and in the old file for
> removed lines.

For Jev, the rule is appended to the `noul` instructions. For chat arms, it is
one more line in the user message. Prompt `v1` stays available for
reproduction.

## Arms

| Arm | Calls | `p` |
| --- | --- | --- |
| `accept_all` | none | 1.0 |
| `cite_script` | none | Deterministic. 0.95 when the cited file is in the diff and the cited line is within 5 lines of a changed line in that file, on either side. 0.05 otherwise. |
| `jev` | `typesafe/jev-1.13`, prompt v2 | `noul` |
| `haiku` | `claude-haiku-5-5` via the claude CLI, prompt v2 | `p_supported` |
| `opus` | `claude-opus-5-5` via the claude CLI, prompt v2 | `p_supported` |
| `cite_jev` | none, derived | `jev` p when `cite_script` passes, else 0.02 |
| `cite_haiku` | none, derived | `haiku` p when `cite_script` passes, else 0.02 |

The two derived arms are the split design. They cost exactly what their model
arm costs.

## Cuts

- **claim-truth**: mechanical kinds `true_added`, `true_removed`, `negated`,
  `fabricated`, plus the whole semantic tier. It measures whether an arm checks
  the claim.
- **citation**: mechanical kinds `near_line`, `wrong_line`, `wrong_file`. It
  measures whether an arm applies the stated rule.
- **all**: every item.

Intervals are 95% percentile bootstraps over commits (2000 resamples, seed 7),
because items share diffs. Item bootstraps are also reported.

## Manipulation checks, evaluated first

The semantic results are read only if both pass. If either fails, the semantic
tier is reported as a known defect and H1 and H2 use the mechanical claim-truth
kinds alone.

| ID | Check | Pass when |
| --- | --- | --- |
| M1 | The semantic tier is not at the ceiling | `opus` AUROC on the semantic tier <= 0.95 |
| M2 | The length shortcut is gone | AUROC of claim word count against the label on the semantic tier is between 0.35 and 0.65 |

## Bars, set now

| ID | Hypothesis | Cut | Pass when |
| --- | --- | --- | --- |
| H1 | Jev checks claims about as well as Opus | claim-truth | Jev AUROC >= 0.90 and Jev minus Opus >= -0.05 |
| H2 | Jev checks claims better than Haiku | claim-truth | Jev minus Haiku > 0 and its commit-bootstrap lower bound > 0 |
| H3 | Told the rule, Jev applies it | citation | Jev accuracy (p >= 0.5 read as supported) >= 0.70 |
| H4 | The split design is as good as Opus at a fraction of the cost | all | `cite_jev` decision cost at R = 10 is no more than `opus` decision cost + 0.05, and `cite_jev` costs 1/20 of `opus` per item or less |
| H5 | The split design is a safe gate | all | `cite_jev` rejects no true finding at R = 10 (reject precision = 1.00) |
| H6 | Jev stays calibrated | all | Jev ECE <= 0.10 |

R = 10 is the default from v1. Decision cost at R = 5 and 20 is reported too.

## Known threats, stated before the run

- Items are still written and labeled by Claude agents, which share a family
  with the `haiku` and `opus` arms. The mechanical tier is labeled by a script.
- `cite_script` checks the citation against any changed line, because it does
  not read the claim. So it cannot see a citation that points at the wrong
  changed line. Measured offline on the v2 data before any paid call: it catches
  5 of 15 `wrong_line`, 13 of 15 `wrong_file` and 4 of 6 `truncated_evidence`,
  and passes every true item. An earlier draft of this note said the script was
  near-perfect on the citation cut by design. That was wrong, and the arm is
  unchanged. H4 and H5 measure whether the split design works end to end.
- The chat arms keep the v1 transport: the local `claude` CLI with all context
  stripped. It adds a short identity line and environment message, as v1
  deviation 1 records.
- Prompt v2 states the rule; v1 did not. A v1 to v2 change mixes the rule with
  new data. Only the citation cut isolates the rule.

## Deviations

1. **2026-10-15, two transport errors retried.** In the full run, `jev` failed
   on 2 of 232 items with a read timeout (mech2-0118) and a connection reset
   (sem2-089). Before any analysis, the runner's resume retried only those two
   items once. Both answered, for $0.0001. No other item was rerun.

## Stop rules

- Budget cap: $10.00 for the v2 paid run, enforced in the runner. v1 cost $6.31
  for 211 items, almost all of it Opus.
- Pilot first: 1 item with a non-empty diff per tier. Stop if the per-tier
  extrapolation exceeds the cap.
- The error-rate stop applies after 20 items per arm: stop an arm above 10%.
- No item is edited or dropped after a paid run sees it.
