# Evidence-check eval

Can a decision model tell whether a panel finding is supported by its cited
evidence? This experiment answers that for Jev, a cheap generative model
(Haiku 5.5), and a strong one (Opus 5.5, a stand-in for the coordinator).

Read in this order:

1. `PREREG.md` and `PREREG-v2.md`: the questions, arms, bars, stop rules,
   threats and deviations, each written before its paid run.
2. `results/report.md` and `results/v2/report.md` (or `.html`): the
   preregistered verdicts.
3. `results/exploratory.md` and `results/v2/exploratory.md`: cuts chosen after
   each dataset audit. Not preregistered.

## Conclusion after v2

For checking panel evidence, use a strong generative model that is told the
citation rule. Jev is not the right tool for this job.

- Told the rule, Opus and Haiku apply it (citation accuracy 0.98 and 0.96). Jev
  does not (0.68), and scores below a rule that reads only the pointer (0.80).
- Jev checks literal claims well (AUROC 0.975, Opus 0.987) but trails Haiku on
  behavior claims (0.914 against 0.974).
- At a cost ratio of 10, Opus has the lowest decision cost (0.246). The split
  design, a script for the citation plus Jev for the claim, reaches 0.349. No
  gate costs 0.526.
- In 4p the coordinator already runs a strong model, so checking each finding
  costs about $0.02. That is cheap at panel scale.

## Result v2, 2026-10-15

Preregistered in `PREREG-v2.md`. New repositories only. The rule is stated in
every prompt. 232 items, 5 file arms plus 2 derived arms, 1160 predictions,
0 errors after one retry of 2 transport failures, $5.79 of a $10 cap. Reports:
`results/v2/report.md` and `results/v2/exploratory.md`.

| Bar | Result | |
| --- | --- | --- |
| M1 The semantic tier is not at the ceiling | Opus 0.9986 | FAIL, so H1 and H2 use the mechanical claim kinds |
| M2 The length shortcut is gone | 0.5034 | PASS |
| H1 Jev checks claims about as well as Opus | 0.975 against 0.987 | PASS |
| H2 Jev beats Haiku | +0.024, commit CI [-0.015, +0.063] | FAIL |
| H3 Told the rule, Jev applies it | accuracy 0.680 against a 0.70 bar | FAIL |
| H4 The split design is near Opus | decision cost 0.349 against 0.246 | FAIL |
| H5 The split design rejects no true finding | 1 of 52 rejections was true | FAIL |
| H6 Jev stays calibrated | ECE 0.0929 | PASS |

## Result v1, 2026-10-15

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
python3 run_eval.py --prompt v2                  # v2: v2 data, arms, $10 cap, results/v2/runs
python3 report.py --prereg v2 && python3 exploratory_v2.py
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
| `exploratory.py`, `exploratory_v2.py` | Post-hoc cuts, labeled as such |
| `data/` | Items; `semantic.raw.jsonl`, `semantic.blind.jsonl`, `semantic.relabel.jsonl` and `semantic.disagreements.jsonl` keep the double-review trail |
| `data/v2/`, `results/v2/` | The v2 items, predictions and reports |
| `results/runs/` | Every v1 prediction, one line per item per arm |
