# Changelog

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
