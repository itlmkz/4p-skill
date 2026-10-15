# Preregistration: does a decision model check panel evidence well?

Written 2026-10-15, before any paid call. Bars, arms, and stop rules below do not
change after results arrive. A change after that point is reported as a deviation.

## The question

A panel seat reports a finding: a claim plus cited evidence. Before the
coordinator acts on it, one question decides whether to trust it:

> Does the diff support the claim, given the cited evidence?

This is the per-finding check in `experiments/jev/gate.py`. It feeds the Phase M
metric "findings shown false". We measure how well each arm answers it.

## Arms

Every arm sees the same state and answers the same question. Every arm returns
`p`, its probability that the finding is supported.

| Arm | Model | How `p` is produced |
| --- | --- | --- |
| `accept_all` | none | `p = 1.0` for every item. Today's behavior: no gate. |
| `jev` | `typesafe/jev-1.13` | One `noul` question through `experiments/jev/jev.py`. `p = answers.q.noul`. |
| `haiku` | `anthropic/claude-haiku-5.5` | Chat completion, json answer `{"p_supported": <0..1>}`. Temperature 0. |
| `opus` | `anthropic/claude-opus-5.5` | Same prompt as `haiku`. It stands in for the coordinator's own judgment. |

The `haiku` arm exists to answer one question: does Jev matter, or would any
cheap model do?

### Shared state and question

State sent to every arm (Jev gets it as `state`, chat arms get it as json in the
user message):

```json
{"diff": "<unified diff, max 12000 chars>", "finding": {"claim": "...", "evidence": {...}}}
```

Question text, identical for all arms, taken from `gate.py`:

- instructions: ``Does `diff` support the claim in `finding.claim`, given the evidence in `finding.evidence`?``
- true: `The evidence exists in the diff and it supports the claim`
- false: `The evidence is missing from the diff, or it does not support the claim`

Chat arms get these three lines plus: answer with one json object
`{"p_supported": <number from 0 to 1>}` and nothing else.

## Dataset

One item is one finding on one real diff, with a ground-truth label. Diffs come
only from public repositories. Item schema (one json object per line):

```json
{
  "id": "mech-0001",
  "tier": "mechanical | semantic | decoy",
  "kind": "<see below>",
  "source": {"repo": "owner/name", "commit": "<sha>"},
  "diff": "<unified diff text>",
  "finding": {"role": "reviewer", "claim": "...", "evidence": {"kind": "file", "file": "path", "line": 12}},
  "label": true,
  "label_basis": "construction | double-review",
  "rationale": "why the label holds, one or two sentences"
}
```

`label` is true when the diff supports the claim at the cited evidence.

| Tier | Target size | Label basis | Kinds |
| --- | --- | --- | --- |
| mechanical | about 120, half true | construction: a script checks the label against the diff | `true_added`, `true_removed`, `wrong_line`, `wrong_file`, `negated`, `fabricated` |
| semantic | about 60, half true | double review: one agent writes, a second agent labels blind, only agreed items are kept | `true_behavior`, `false_misread`, `false_causality`, `false_overclaim`, `false_outside_diff` |
| decoy | about 12 | construction | `empty_diff`, `truncated_evidence`, `right_claim_wrong_line` |

`wrong_line` means the claim is true somewhere in the diff, but the cited line is
more than 5 lines from it. That is unsupported by definition: a citation that
does not point at the evidence is not checkable.

## Metrics

Per arm, on all items and per tier:

- **AUROC** with a 95% bootstrap interval (2000 resamples, seed 7).
- **Brier score** and **ECE** (10 equal-width bins). Calibration is the claim a
  decision model makes, so it is measured, not assumed.
- **Decision cost** at a cost ratio `R`. Rejecting a true finding costs `R`
  (a missed real risk). Accepting a false finding costs 1 (wasted attention).
  The Bayes threshold for a calibrated `p` is `t = 1 / (1 + R)`: reject when
  `p < t`. We report mean cost per item at `t`, and precision and recall of
  "reject", for `R` in 5, 10, 20.
- **Cost in USD and latency** per item.
- **Errors**: an item an arm failed to answer counts as `p = 0.5` and is listed.

Default `R = 10`. The owner did not set it. 10 sits between the two options
offered (5 and 20), and the report shows all three.

## Bars, set now

| ID | Hypothesis | Pass when |
| --- | --- | --- |
| H1 | Jev separates supported from unsupported findings | AUROC >= 0.80 and its 95% lower bound >= 0.70 |
| H2 | Jev is calibrated enough to threshold | ECE <= 0.10 |
| H3 | Jev is a viable cheap substitute for the coordinator | Jev AUROC within 0.05 of `opus`, at 1/20 of the cost or less |
| H4 | Jev specifically matters | Jev AUROC beats `haiku` and the 95% interval of the difference excludes 0 |
| H5 | Jev survives decoys | `p <= 0.2` on every `empty_diff` item |

If H1 fails, the evidence gate stays an experiment and no product work follows.
If H1 to H3 pass and H4 fails, the finding is "a cheap model is enough", and the
cheapest passing arm is the recommendation, not Jev by name.

## Known threats, stated before the run

- The semantic tier is written and labeled by Claude agents, which share a family
  with the `opus` arm. That can inflate `opus` on that tier. The mechanical and
  decoy tiers are labeled by a script, so H1 to H4 are also reported on those
  tiers alone, and that cut decides a conflict.
- Diffs come from a small number of public repositories. The result says how the
  arms behave on code like this, not on all code.
- Two known tells, found while building the data and listed before any paid run:
  a `wrong_file` item that cites a file outside the diff keeps the true line
  number, which can exceed that file's length, and a `truncated_evidence` diff
  ends cleanly at a hunk boundary. Both make those items easier than a real
  mistake. Per-kind results show whether an arm leans on them.
- Four mechanical items (mech-0006, -0054, -0067, -0102) quote a real commit
  whose diff text contains em dashes. They are kept, because editing them would
  change the commit.
- The `opus` arm sees a json state, not a live session. A real coordinator also
  has the repo. So `opus` here is a lower bound on the coordinator.

## Stop rules

- Budget cap: $8.00 for the full run, enforced in the runner. The run stops when
  the next call would exceed it.
- Pilot first: 3 items per arm. If the pilot extrapolates above the cap, stop.
- If any arm errors on more than 10% of items, stop that arm and report it.
- No item is edited or dropped after a paid run sees it. A bad item is listed as
  a known defect in the report.

## Deviations

Recorded as they happen, with the date. None changes a bar, an arm's model, or
the dataset.

1. **2026-10-15, chat transport.** OpenRouter's chat completions endpoint
   returned HTTP 403, "violation of provider Terms Of Service", for every chat
   model on this account, including a bare "Say ok." prompt. The decisions
   endpoint, which `jev` uses, works with the same key. The `haiku` and `opus`
   arms therefore run through the local `claude` CLI, with the same models and
   the same prompt. The CLI runs from an empty folder with no tools, no settings,
   no MCP servers, no skills, and no CLAUDE.md. Side effects: the CLI has no
   temperature setting, so these arms run at the default temperature, and cost is
   the CLI's reported `total_cost_usd`. Correction found in review: a call is not
   the prompt alone. The CLI adds one identity line ("You are a Claude agent,
   built on Anthropic's Claude Agent SDK.") and a short environment message with
   the working folder, platform, model name and date. The run used the folder
   `scratchpad/claude-arm-cwd`, which does not name the eval. Both chat arms get
   the same additions. Jev does not.
2. **2026-10-15, error-rate stop.** The runner applies the 10% error-rate stop
   only after an arm has tried 20 items in the current run, so a single early
   failure cannot stop an arm. The rule above did not state that minimum.

## Files

| File | Role |
| --- | --- |
| `PREREG.md` | This file. |
| `build_dataset.py` | Builds the mechanical and decoy tiers from public commits. Deterministic, seed 7. |
| `data/*.jsonl` | Items. `semantic.jsonl` holds only items that passed double review. |
| `arms.py` | The four arms behind one `predict(item) -> Prediction` interface. |
| `run_eval.py` | Runs arms over items: cache, resume, budget cap, `--dry-run`, `--limit`. |
| `metrics.py` | AUROC, bootstrap, Brier, ECE, decision cost. Stdlib only. |
| `report.py` | Writes `results/report.md` and `results/report.html`. |
