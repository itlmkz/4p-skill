# Roadmap and open decisions

## Roster configuration (planned)

Today every seat runs the same `4PP_KIND` and `4PP_MODEL`. That is wrong: which
model backs which seat is personal, and the choice moves every time a model
ships. The plan is to make the roster data, not code.

```
roster = "default"

[rosters.default]
reviewer   = claude
tester     = codex
contraire  = <your pick>
bigpicture = pi
```

Global default with a per-project override, matching how pi already resolves
`~/.pi/agent` against `.pi/`. A seat carries kind, model, and args, because model
is as personal as kind.

No curated roster ships with this package. On purpose. A recommendation would be
read as advice and would be stale within one release.

Three backend tiers are needed, because "any agent" is not one thing:

| Tier | Example | What you get |
| --- | --- | --- |
| Native Herdr agent kind | pi, claude, codex | Full lifecycle: `agent wait`, `agent read`, `blocked` |
| Raw CLI in a pane | any prompt-accepting tool | Output only, no lifecycle states |
| pi-subagent profile | no Herdr at all | In-process, results collected |

The tiers matter because `herdr agent wait` only works on recognized kinds.
`--seats reviewer,tester` is also planned, so a personal roster can mean "not all
four tonight".

Open question: rosters global plus per-project, or one personal file.

## Structured panel reports (planned)

Panes write prose today. Any automated check over panel output needs records
first: claim, evidence, file:line, severity, as JSON. This is worth doing on its
own merits, because the coordinator stops parsing walls of text. It is also the
prerequisite for anything in `experiments/jev/`.

## experiments/jev

A TypeSafe Jev layer: a pre-flight seat router and a merge gate over panel
reports. Kept out of the product path and not installed by default. It needs an
OpenRouter key.

An honest assessment, recorded so it is not rediscovered later:

- **Jev cannot do the thing this tool is for.** It does not generate text. The
  AMO seat's value is that it *says* the uncomfortable thing. Jev can only score
  whether that thing was already said, and whether its evidence holds.
- **The router is the one clear win.** Deciding how many seats a change deserves
  is a real decision, made badly today, and a Jev call costs about $0.00003. On a
  real 41k-character, 10-file commit it returned `reviewer_and_tester` at 0.62
  confidence; on a one-line commit, `one_reviewer` at 0.98.
- **The merge gate is narrower than it first looks.** It checks whether each
  finding's cited evidence exists and supports the claim. That is real, and it
  caught a planted false citation at 0.19 confidence. But it trades reading four
  reports for owning a question file plus thresholds, and TypeSafe's own docs
  say the questions and thresholds are the part a human must review.
- **One thing it does better than prose.** On a real auth change the seat label
  was `reviewer_and_tester` at 0.50 against `one_reviewer` at 0.49, confidence
  0.25. The label was a coin flip and the confidence said so. Four confident
  prose reports never tell you that.

Verdict: keep it as an experiment. The one place it protects the AMO seat rather
than replacing it is checking that a manufactured objection is actually supported
by the material. That is worth exploring later, not now.
