# Changelog

## 0.5.0

The coordinator checks each finding's evidence before it acts on it. Panel
reports from a pi pane now reach the coordinator.

### Evidence check

A pane can cite a file and line that do not support its claim. The coordinator
used to act on such a finding unread. The evidence-check eval
(`experiments/evidence-eval/`, results in `docs/ROADMAP.md`) measured who should
check it. Told the citation rule, Opus reached 0.98 citation accuracy, and Jev
reached 0.68. A script plus Jev, the split design, had a decision cost of 0.349,
against 0.246 for Opus alone. So the check belongs to the coordinator, which
already is a strong model.

- `--collect` adds `evidence_checks` to every role result. It is an empty list
  when no report was found. Otherwise it has one entry for each finding, in
  finding order.
- Each entry has `index` (the 0-based position of the finding) and `finding`
  (its id). A duplicate id is still unambiguous. It also has `kind`, `status`,
  `file`, `line`, `in_diff`, `excerpt`, and an optional `reason` for a status
  that is not `ok`.
- Only `kind=file` is checked. The path is repo-relative. It resolves against
  `git rev-parse --show-toplevel`, or the panel folder outside git, and never
  outside that root.
- The statuses are `ok`, `file_missing`, `outside_repo`, `line_out_of_range`,
  and `not_checked`. `file_missing` also covers a directory, a FIFO, an
  unreadable file, and an empty path. `line_out_of_range` also covers a missing
  or non-integer line. `not_checked` covers other evidence kinds and a file over
  8 MB.
- An `ok` entry carries the cited line with two lines either side. Context
  lines read `   41 | text` and the cited line reads `>> 42 | text`.
- `in_diff` is true when the cited line is within 5 lines of a change in
  `git diff HEAD`. Line numbers count in the current file. A deletion counts at its place
  in the current file. An untracked file counts as changed. It is null when git
  cannot answer or the status is not `ok`.
- `commands/4p.md` has a new mandatory step: check each finding before you act
  on it. It states the citation rule word for word. A missing file, an outside
  path, or a missing line makes a finding unsupported. A blocking finding the
  coordinator judges unsupported goes to the user as "unsupported", with the
  reason. An unsupported non-blocking finding gets one line. Nothing is dropped
  silently, and the merged view marks each finding acted on as checked.
- The skill documents `evidence_checks` and the rule, and the merge rules now
  start with the evidence check.
- Brief rule 4 tells each pane to give a repo-relative path and the exact line
  for `kind=file`. The line is a number in the current file, within 5 lines of
  the supporting code. `tests/brief.test.py` checks that every role carries it.

### Report transport

A live panel in a separate Herdr tab showed two transport bugs.

- The launch never worked from Claude Code. `4PP_TASK="..." python3 ...` is not
  valid shell, because a name that starts with a digit cannot be assigned. Bash
  and zsh answer "command not found". `commands/4p.md`, the skill, and the
  README now set every `4PP_` variable with `env`. A launcher test forbids the
  bare form.
- pi draws a full-screen UI, so its earlier output never reaches the terminal
  scrollback. `herdr agent read --lines 2000` returned only the 23 visible lines.
  Every report in a 5-way split was unreadable, and pi also wrapped lines inside
  json strings.
- The fix: the self-check is now `report.py --validate - --save
  /tmp/4pp/<tab>/<role>.json`. It writes the report only when it is valid, as
  an atomic write with mode 0600.
- The launcher removes old saved reports and records `task_sent_at` when it fans
  out a task.
- `--collect` prefers the saved file when it is newer than `task_sent_at`. It
  must also be a regular file, owned by you, and under 1 MB. Otherwise it falls back to the pane.
  Each role result has `source`, `"saved file"` or `"pane"`. When the file was
  not used, `saved_file` says why.
- A panel briefed before 0.5.0 does not know the save step. Run `--rebrief` once
  after the upgrade.
- After the fix, the live run returned all four reports with `all_ok` true. The
  evidence checks pointed at the planted bug.

## 0.4.1

`/4p` collects the panel reliably again.

Three commits on 2026-09-19 changed the launcher and the skill but not
`commands/4p.md`. The command still waited on each pane in series, the AMO seat
got two contradictory output orders, and `--extract` could return a broken draft.

- `commands/4p.md` collects with one `4p.py --collect` call and reads its json.
  A role whose status is not `ok` is reported as failed, never guessed. The
  command now carries the delegation rule and the AMO rapid checkpoint, with the
  four verdict levels and the `no_critical` stop.
- The fan-out sends the AMO its task marked `Full report (4p/report@1):`. The
  brief header says json is for full reports, and the AMO answers a decision
  checkpoint in three lines. The other three seats are unchanged.
- `report.py --extract` takes the last candidate that carries
  `"schema": "4p/report@1"`, and falls back to the last object that parses. A
  self-check draft or stray json in tool output no longer wins over the final
  answer. Nested objects are no longer candidates of their own.
- The AMO brief lost its em dashes and a stray space in the verdict format, so
  `tests/brief.test.py` passes again.
- `--collect` reads the last 2000 lines of each pane, not 200. A self-check
  draft plus a pretty-printed report could push the final block out of the
  window. Safe now, because the last marked report wins.
- New tests pin the extraction order, the fan-out marker, and the AMO output scope.

## 0.4.0

One `/4p` in Claude Code, and pi panes by default.

The plugin exposed two components, `4p` from `commands/4p.md` and `four-p-panel`
from `skills/`. Both sat under the `/4p:` namespace, so typing `/4p` showed two
entries. The skill also cost about 160 always-on tokens for knowledge the command
already carries.

- Moved the shared skill to `skill/`, which Claude Code does not auto-scan. The
  plugin now exposes exactly one component, so there is one `/4p:4p`. pi reads
  the same skill through the `pi.skills` manifest path, so nothing is duplicated.
- The Claude Code command no longer overrides the pane kind. Panes are pi, which
  is the launcher's own default and the kind whose write tools are removed at
  launch. Set `4PP_KIND` to choose another.

## 0.3.0

Enforce the no-write posture for Claude Code panes.

Claude Code panes used to receive no flags at all, so the "panes advise, the
coordinator writes" rule was briefed but not enforced. Their default tool set
includes Write and Edit.

- `kind_flags()` gives each agent kind the flags its own CLI understands.
  `pi` keeps `--exclude-tools edit,write`. `claude` now gets
  `--disallowedTools Write Edit NotebookEdit`, and `--allowedTools Read Grep
  Glob` in strict mode.
- `4PP_MODEL` now reaches Claude Code panes. `4PP_THINKING` is not sent to them,
  because `--thinking` is a pi flag and would fail the pane start.
- A kind with no known flags gets none. The launcher and the docs no longer
  imply otherwise.
- `tests/launcher.test.py` pins all of it. 4 suites, 133 checks.

## 0.2.0

Claude Code support. One repository, two hosts.

- Claude Code plugin and marketplace. Install with
  `claude plugin marketplace add itlmkz/4p-skill` then `claude plugin install 4p@4p`.
  The command is `/4p:4p`, because Claude Code namespaces plugin commands.
- The plugin source is the repository root, so `panel/` and `skills/` are shared
  with the pi package instead of copied.
- Pane kind defaults to the host: `pi` from the pi extension, `claude` from the
  Claude Code command. Override with `4PP_KIND`.

## 0.1.0

First release.

- `AMO`, `tester`, `reviewer`, and `big picture` as live Herdr panes.
- `4p/brief@1` in, one `4p/report@1` json block out, validated by the pane itself.
- English, in STE100. Brevity measured, other languages rejected, ultra terse rejected.
- 116 checks across extension, contract, and brief.
