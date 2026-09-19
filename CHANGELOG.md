# Changelog

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
