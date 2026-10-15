# Evidence-check eval

Can a decision model tell whether a panel finding is supported by its cited
evidence? This experiment answers that for Jev, a cheap generative model
(Haiku 5.5), and a strong one (Opus 5.5, a stand-in for the coordinator).

Read in this order:

1. `PREREG.md`: the question, arms, bars, stop rules, threats and deviations,
   written before any paid call.
2. `results/report.md` (or `report.html`): the preregistered verdict.
3. `results/exploratory.md`: cuts chosen after the dataset audit. Not
   preregistered; read them as hypotheses for the next eval.

## Result, 2026-10-15

211 items, 4 arms, 844 predictions, 0 errors, $6.31 spent of an $8 cap.

| Bar | Decided on the script-labeled cut | |
| --- | --- | --- |
| H1 Jev separates supported from unsupported | AUROC 0.883 [0.823, 0.933] | PASS |
| H2 Jev is calibrated | ECE 0.087 | PASS |
| H3 Jev within 0.05 of Opus at 1/20 of the cost | 0.069 below Opus, at 1/363 of the cost | FAIL |
| H4 Jev beats Haiku | +0.030, CI [-0.022, +0.082] | FAIL |
| H5 Jev gives empty diffs p <= 0.2 | max 0.08 | PASS |

What the exploratory cuts suggest:

- No arm enforces the citation. On a true claim cited more than 5 lines away,
  Jev accepts 87%, Haiku 73%, Opus 60%. The arms were never told the 5-line rule.
- On claim truth alone (no citation-only items), Jev reaches AUROC 0.976 against
  Opus 0.998 and beats Haiku with an interval that excludes 0.
- At a cost ratio of 10, Jev never rejected a true finding (reject precision
  1.00) and halved the decision cost of having no gate (0.27 against 0.51).
  Haiku did worse than no gate (0.68).
- The semantic tier sits at the ceiling for every arm, so it does not separate
  them. The next eval needs harder semantic items.

## Run it

```bash
npm run test:eval                                # offline: arms, metrics, dataset, label proof
python3 run_eval.py --dry-run                    # no network, fake arm
python3 run_eval.py --pilot                      # 1 item per tier, spend table, exits 2 over the cap
python3 run_eval.py                              # full run, resumes from results/runs
python3 report.py && python3 exploratory.py      # results/report.{md,html}, results/exploratory.md
```

The chat arms run through the local `claude` CLI (see PREREG deviation 1). Jev
needs `OPENROUTER_API_KEY`.

## Files

| Path | Role |
| --- | --- |
| `build_dataset.py` | Mechanical and decoy tiers from pinned public commits; `--check` re-proves every label |
| `semantic_merge.py` | Blinds the semantic tier for a second labeler, keeps agreed items |
| `arms.py`, `run_eval.py` | Arms behind one interface; cache, resume, budget cap, pilot |
| `metrics.py`, `report.py` | Preregistered metrics and bars, Markdown and HTML report |
| `exploratory.py` | Post-hoc cuts, labeled as such |
| `data/` | Items; `semantic.raw.jsonl`, `semantic.blind.jsonl`, `semantic.relabel.jsonl` and `semantic.disagreements.jsonl` keep the double-review trail |
| `results/runs/` | Every prediction, one line per item per arm |
