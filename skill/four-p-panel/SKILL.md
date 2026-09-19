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
| **AMO** | `4pp:contraire` | Rapid decision checkpoint. Four-level gate: yes, yes_but, no_but, no_critical. Blocks on real risk (data loss, security, broken deploy, irreversible choice, silent behavior change). Says yes fast when the decision is sound. Full report mode for initial task review only. |
| tester | `4pp:tester` | Empirical verification only. Runs the build, the tests, the scripts, the deployed URL. Reports exact commands and observed output. Says "could not verify" and names the blocker instead of guessing. |
| reviewer | `4pp:reviewer` | The real diff against the repo's own standards. Correctness, behavior change, edge cases, security, conventions, test coverage. Findings ranked blocking, should-fix, nit, each with file:line. |
| big picture | `4pp:bigpicture` | Coherence with product and platform decisions. Drift, duplication, one-way doors, scope to cut, audience and access boundaries. |

The **AMO** seat is the reason this tool exists. It is a rapid checkpoint, not a
slow reviewer. The coordinator prompts it with each decision as it comes up, and
gets back a four-level verdict in three lines. A `no_critical` stops work and
escalates to the user. This catches the cheap-to-hear-now, expensive-to-hear-later
objections before they ship. Reserve the full report contract for the initial
task review; after that, use the rapid checkpoint for every decision.

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

## THE DELEGATION RULE

This is the most important section. Read it before doing anything else.

When a task is given, the panel is the input to your implementation, not an
afterthought. You MUST NOT start coding, editing, or implementing until you have
collected and merged the panel reports.

The mandatory sequence after launching the panel with a task:

1. **Launch**: run the launcher. It fans the task out to all four panes in
   parallel and returns immediately.
2. **Collect**: run `4p.py --collect`. It waits for all four panes in parallel,
   reads their output, extracts the JSON reports, validates them, and prints
   the results as one JSON object to stdout.
3. **Read**: read the JSON output. Each role has a `status` and a `report`.
4. **Merge**: present one merged view to the user (see Merge rules below).
5. **Implement**: only now, apply the findings from the merged report.

You MUST NOT skip step 2. You MUST NOT implement before step 4. The panes exist
to catch what you miss. If you skip them, the panel is wasted.

### The collect command

```bash
python3 panel/4p.py --collect
```

This reads the panel state, waits for all panes in parallel (5 min timeout per
pane), reads each pane's output, extracts and validates the JSON report, and
prints one JSON object:

```json
{
  "tab": "wJ:t3",
  "reports": {
    "contraire": {"status": "ok", "report": {...}, "errors": []},
    "tester":    {"status": "ok", "report": {...}, "errors": []},
    "reviewer":  {"status": "ok", "report": {...}, "errors": []},
    "bigpicture":{"status": "ok", "report": {...}, "errors": []}
  },
  "all_ok": true
}
```

A pane whose `status` is not `"ok"` either failed to produce a report or
produced an invalid one. Report the failure to the user; do not guess what the
pane meant.

## Rapid checkpoint (AMO / contraire)

The contraire is a decision checkpoint, not a slow reviewer. Use it for every
decision and design choice as you work. This is the default interaction mode
after the initial full-panel review.

### When to checkpoint

- Before committing to an architecture choice.
- Before writing more than 20 lines of code for a new approach.
- Before touching auth, data, payments, or anything irreversible.
- When you are unsure whether the user would agree.

### How to checkpoint

Prompt the contraire with the decision, one sentence:

```bash
herdr agent prompt <contraire-name> \
  "Decision: use SQLite for the session store instead of Redis." \
  --wait --timeout 60000
```

Read the response directly. It is three lines, not JSON:

```
verdict: yes_but
reason: SQLite works but has no built-in eviction, so sessions will grow forever.
watch: Add a cron job to prune sessions older than 30 days.
```

### The four verdict levels

| Verdict | Meaning | What you do |
| --- | --- | --- |
| `yes` | Sound, proceed. | Implement. |
| `yes_but` | Proceed, note the watch item. | Implement; flag the watch item to the user at the end. |
| `no_but` | Proceed only after the fix in reason. | Fix the issue, then implement. |
| `no_critical` | Real risk. Stop and ask the user. | Present the reason and ask the user to decide. |

A `no_critical` stops all work. Present the reason to the user with a
recommendation and wait for their decision. Never override a `no_critical`.

### When to use the full report instead

The initial task review uses the full panel (all four panes, full `4p/report@1`
contract). After that, individual decisions use the rapid checkpoint above.
Reserve the full report for:

- The first review of a complete task or feature.
- When the coordinator explicitly asks "full report".
- When the user asks for a deep review.

## Driving the panel manually

For sending follow-up tasks to individual panes after the initial collect:

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

## Merge rules

Present one merged view, not four summaries:

1. **Agreements first.** Where all panes converge, state that plainly.
2. **Blocking findings.** Any finding where `blocks` is true is a real risk:
   data loss, security, a broken deploy, an irreversible choice, or a silent
   behavior change. These gate the merge.
3. **Strongest objection per seat.** One per role, ranked by severity.
4. **Questions for the owner.** Anything in `questions[]` belongs to the user.
   Present each with a recommendation. Never present a decision bare.
5. **Your disposition.** After incorporating the panel's findings, state whether
   you would ship, fix first, or hold.

Use the fields that carry the decision: `verdict`, `confidence`,
`findings[].blocks`, `findings[].severity`, `assumptions`, `questions`, and
`could_not_verify`. A finding whose `blocks` is true is a real risk. Treat
`confidence` below 0.6 as a signal to escalate, not to act.

Anything the panes flagged in `questions` belongs to the owner. Put those
decisions to the user with a recommendation. Never present a decision bare.

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
