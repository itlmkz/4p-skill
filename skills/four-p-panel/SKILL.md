---
name: four-p-panel
description: "Drive the 4p four-pane advisory panel: the AMO (assistant contraire), tester, reviewer, and big picture seats. Use when the user asks for the 4p panel, an advisory panel, a second opinion, a devil's advocate, an AMO read on a decision, or asks to convene critics, challenge a plan, or stress-test a decision. Requires a pi session inside Herdr (HERDR_ENV=1)."
---

# The 4p panel

Four advisors in four Herdr panes, each with a fixed personality and one job.
They advise. You write the code.

The panel exists for the personalities, not for a verdict. Four instances of one
model share the same blind spots and converge confidently on the same wrong
answer. Each seat here is a different kind of attention:

| Seat | Label | Job |
| --- | --- | --- |
| **AMO** | `4pp:contraire` | Critical eye and constructive contradiction. The load-bearing assumption, the unmentioned failure mode, the cheapest disconfirming test, the steelman of the rejected path, what would flip its verdict. Blocks on real risk, never on taste. |
| tester | `4pp:tester` | Empirical verification only. Runs the build, the tests, the scripts, the deployed URL. Reports exact commands and observed output. Says "could not verify" and names the blocker instead of guessing. |
| reviewer | `4pp:reviewer` | The real diff against the repo's own standards. Correctness, behavior change, edge cases, security, conventions, test coverage. Findings ranked blocking, should-fix, nit, each with file:line. |
| big picture | `4pp:bigpicture` | Coherence with product and platform decisions. Drift, duplication, one-way doors, scope to cut, audience and access boundaries. |

The **AMO** seat is the reason this tool exists. A role told to contradict will
sometimes manufacture contradiction, so hold it to its own rule: it blocks on
real risk (data loss, security, a broken deploy, an irreversible choice, a silent
behavior change) and it never blocks on taste. When it is right, its objection is
usually the cheapest one to hear before shipping and the most expensive one to
hear after.

## Open the panel

```
/4p                       open the panel, standing by
/4p <task>                open it and fan the task out to all four
/4p --rebrief <task>      re-send the role briefs first
```

The launcher is `panel/4p.py`, reached through the `/4p` extension command. It is
idempotent. Panes are labeled `4pp:<role>` and the panel is recorded in
`/tmp/4pp/<tab>/panel.json`. Re-running reuses the live panel, repairs a drifted
label from that record, and fills in only what is missing. Never close and
recreate a panel merely to reset it.

## Who writes

The coordinator pane is the only writer of repo code. Panel panes are briefed to
leave git state alone, and their write tools are removed at launch. They propose
patches. You apply them.

The flag depends on the agent kind: `pi` gets `--exclude-tools edit,write`, and
`claude` gets `--disallowedTools Write Edit NotebookEdit`. A kind with no known
flag gets none, so its posture is the brief alone. Never describe that as enforced.

This is a contract, not a kernel boundary: bash stays available because panes
need it to run tests. For an enforced version, set `4PP_STRICT_NO_WRITE=1` and
the panes get `read,grep,find,ls` only, at the cost of not being able to run
tests.

## Driving the panel afterwards

```bash
herdr agent prompt <name> "<task>" --wait --timeout 600000   # one pane, blocking
herdr agent prompt <name> "<task>" --timeout 600000          # fire and continue
herdr agent read <name> --source recent-unwrapped --lines 200 \
  | python3 panel/report.py --extract -                      # the pane's report
herdr agent list
```

Give each pane the task it is built for. Hand the decision to the AMO and big
picture seats, the change to reviewer, the runtime behavior to tester. Send one
task to all four only when a full cross-check justifies the cost.

Agent names may carry a numeric suffix when a base name is already live in
another workspace (`tester-2`). Always take real names from the launcher output
or `herdr agent list`. Never assume them.

## Reporting rules

The panes answer in a contract, not in prose. Both directions are structured, so
the coordinator never parses a wall of text.

**In:** the launcher briefs each pane with `4p/brief@1`. It carries the session
facts, the role, the rules, and the output contract, which is rendered from
`panel/report.schema.json` at runtime. The brief cannot describe a shape the
validator will reject.

**Out:** each pane answers with exactly one fenced json block, `4p/report@1`,
and no prose around it. The pane validates its own answer before sending it.

```bash
python3 panel/report.py --contract                 # the contract, derived from the schema
python3 panel/report.py --validate report.json    # validate one report
herdr agent read <name> --source recent-unwrapped --lines 200 \
  | python3 panel/report.py --extract -           # pull the block out of pane output
```

`--extract` tolerates a pane that wraps its answer in prose. It finds the first
json object that parses, so a chatty pane is an inconvenience, not a failure.

Useful fields when you merge:

| Field | Why it matters |
| --- | --- |
| `verdict` | `ship`, `fix_first`, `block`, `hold`, or `could_not_verify` |
| `confidence` | The pane's own certainty. Low is useful information, not noise. |
| `findings[].blocks` | True only for real risk. This is what gates a merge. |
| `findings[].evidence` | `kind=file` needs `file` and `line`. A citation without a line is not checkable, and the validator rejects it. |
| `assumptions[]` | Every assumption the verdict rests on, each with `if_false`. An unstated assumption is the most expensive kind. |
| `questions[]` | Decisions that belong to the owner, each with a `recommendation`. Never presented bare. |
| `could_not_verify[]` | What the pane could not run, and the precise blocker. |

### Language and style, decided

English, in STE100. Panes and coordinator alike. Measured, same three findings:

| Style | Tokens |
| --- | ---: |
| verbose English prose | 173 |
| English ultra terse | 72 |
| English STE100 | 86 |
| modern Chinese | 102 |
| classical Chinese (wenyan) | loses to English by 1.4x to 2.0x |

Brevity is the saving. Language is not. So English it is.

The style is STE100, not ultra terse. Ultra terse saves 16% and drops articles
and words to do it. A missing word that flips a meaning costs more than 16%, so
the words stay. Terseness is not worth ambiguity.

That is also STE100 rule 4.2, so these guards are not extra rules:

- Do not omit words.
- Never drop `not`, `never`, `no`, `only`, `except`.
- Keep numbers, units, paths, and error strings exact.
- One word for one meaning. No synonym rotation.

### What the validator enforces

Two rules are mechanical: a sentence over 20 words (STE100 5.1), and an em dash.
Sentences in Chinese, Japanese, or Korean are measured in characters instead,
with a 45-character budget, because those scripts have no spaces.

Word choice and active voice are not mechanically checkable, so they stay a
request to the pane. Do not claim otherwise.

ASD-STE100 is an English standard, and this tool is English for that reason. If
the owner ever wants another language for the coordinator, the STE100 claim must
be dropped rather than quietly kept.

### What the user reads

Panel output is input to you, not a deliverable. Anything a user or the owner
reads follows house rules:

- Simplified Technical English. Sentences of 20 words maximum. Active voice.
- No em dashes.
- Verdict first, then the evidence. Every claim carries a file:line, a command,
  or observed output.
- Separate blocking findings from nits. Say plainly when something is fine.
- Do not quote pane json verbatim. Rewrite it in Simplified Technical English.

## Environment

| Variable | Effect |
| --- | --- |
| `4PP_MODEL` | Model for the panel panes |
| `4PP_THINKING` | Thinking level for the panel panes |
| `4PP_KIND` | Agent kind, default `pi` |
| `4PP_STRICT_NO_WRITE=1` | Panes get read-only tools, no bash |
| `4PP_COORDINATOR_GRANTS_WRITE=1` | Drop the no-write posture for one approved task. Refused if a panel pane tries to set it for itself. |
| `4PP_TASK` | Task, as an alternative to positional arguments |

## The roster is personal

Which model or agent backs each seat is a matter of taste, and that taste changes
whenever a model ships. Choose your own. There is no recommended roster here on
purpose: a recommendation would read as advice and would age badly.
