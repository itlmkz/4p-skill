# 4p

Four advisors in four terminal panes, each with one fixed personality and one job.

Not a code generator. A second opinion you can watch think. The point is not that
four models agree. The point is that four different kinds of attention disagree
usefully, and one of them is paid to say the thing nobody wants to hear.

| Seat | Job |
| --- | --- |
| **AMO** | Critical eye, constructive contradiction. The load-bearing assumption, the unmentioned failure mode, the cheapest disconfirming test, the steelman of the rejected path. Blocks on real risk, never on taste. |
| tester | Empirical verification only. Runs the build, the tests, the scripts. Reports exact commands and observed output. Says "could not verify" instead of guessing. |
| reviewer | The real diff against this repo's own standards. Findings ranked blocking, should-fix, nit, each with file:line. |
| big picture | Product and platform coherence. Drift, duplication, one-way doors, scope to cut. |

The **AMO** seat is why this exists. A panel of one model is one blind spot
repeated. A role told to contradict will sometimes invent a contradiction, so it
is held to a rule: block on real risk, never on taste.

## Requirements

- [pi](https://pi.dev) running inside a [Herdr](https://github.com/) pane.
- `python3` on your PATH. The launcher is stdlib-only. No dependencies.

Tests need node for the extension suite:

```bash
npm test
```

## Install

One repository, two hosts. The `panel/` launcher and the `skill/` contract are
shared. Only the entry point differs.

**pi**

```bash
pi install git:github.com/itlmkz/4p-skill
```

**Claude Code**

```bash
claude plugin marketplace add itlmkz/4p-skill
claude plugin install 4p@4p
```

Claude Code namespaces plugin commands, so the command is `/4p:4p` there.

Both hosts need [Herdr](https://github.com/), because the panel is four Herdr
panes. Herdr must have the integration for the agent kind you run. Check with
`herdr agent start --help`.

Not published to npm yet.

## Use

**pi**

```
/4p                  open the panel and leave it standing by
/4p <task>           open it and fan the task out to all four seats
/4p --rebrief <task> re-send the role briefs first
```

**Claude Code**

```
/4p:4p                same, with the arguments after the command name
```

Pane kind defaults to the host: `pi` from the pi extension, `claude` from the
Claude Code command. Override either with `4PP_KIND`. Any kind Herdr supports
works, so a Claude Code session can run a panel of pi panes, or the reverse.

The launcher is idempotent. Panes carry a `4pp:<role>` label and the panel is
recorded in `/tmp/4pp/<tab>/panel.json`, so re-running reuses the live panel,
repairs a drifted label, and fills in only what is missing. Your pi session is
the coordinator: it waits for the panes, reads them, and merges the result.

Afterwards, from the same session:

```bash
herdr agent prompt <name> "<task>" --wait --timeout 600000
herdr agent read <name> --source recent-unwrapped --lines 200
herdr agent list
```

## Who writes

Your session is the only writer of repo code. Panes are briefed to leave git
alone, and the write tools are removed from them at launch. They propose patches.
You apply them.

The flag differs by kind, because pi and Claude Code do not share flag names:

| Kind | Default posture | Strict (`4PP_STRICT_NO_WRITE=1`) |
| --- | --- | --- |
| `pi` | `--exclude-tools edit,write` | `--tools read,grep,find,ls` |
| `claude` | `--disallowedTools Write Edit NotebookEdit` | `--allowedTools Read Grep Glob` |
| other kinds | none, the brief alone | none |

An unrecognized kind gets no flags. Its posture is the brief and nothing more,
which is weaker than it looks. Check the table before you trust a new kind.

That is a contract, not a sandbox: panes keep `bash` because they need it to run
tests. For the enforced version, set `4PP_STRICT_NO_WRITE=1` and they get
`read,grep,find,ls` only, at the cost of not being able to run anything.

## The contract

The panes speak json in both directions. The brief in, and one `4p/report@1`
block out. Neither side is prose, so the merge step never parses a wall of text.

```json
{
  "schema": "4p/report@1",
  "role": "contraire",
  "verdict": "block",
  "confidence": 0.72,
  "findings": [
    {
      "id": "amo-1",
      "severity": "blocking",
      "claim": "The redirect discards in-flight form state on each token expiry.",
      "evidence": { "kind": "file", "file": "src/auth/gates.tsx", "line": 45 },
      "confirm_test": "Expire the token with text in the form and check the input.",
      "blocks": true
    }
  ],
  "assumptions": [
    {
      "statement": "A refresh failure always means the session is unrecoverable.",
      "if_false": "The user is signed out while a valid session still exists.",
      "verified": false
    }
  ],
  "questions": [
    {
      "id": "q1",
      "question": "Should a failed refresh retry once before signing the user out?",
      "recommendation": "Retry once, then sign out.",
      "blocks": true
    }
  ],
  "could_not_verify": [
    { "what": "The expiry path in a real browser.", "blocker": "No browser runtime in this pane." }
  ],
  "next_action": "Decide the retry policy first."
}
```

The shape is the point:

- `evidence.kind=file` requires `file` and `line`. A citation without a line is
  not checkable, so the validator rejects it.
- `assumptions[]` carries every assumption the verdict rests on, each with
  `if_false`. An unstated assumption is the most expensive kind.
- `questions[]` carries decisions that belong to the owner, each with a
  `recommendation`. A pane never presents a decision bare. This is the grill
  mechanic: surface the frontier, recommend an answer, let the owner decide.
- `blocks` is true only for real risk: data loss, security, a broken deploy, an
  irreversible choice, a silent behavior change. Never taste.

Validate and extract with the same tool the panes use:

```bash
python3 panel/report.py --contract                # derived from the schema
python3 panel/report.py --validate report.json
herdr agent read <name> --source recent-unwrapped --lines 200 \
  | python3 panel/report.py --extract -
```

Free text is Simplified Technical English. The validator enforces the parts that
are mechanical: a sentence over 20 words, and an em dash. Chinese, Japanese, and
Korean sentences are measured in characters instead, with a 45-character budget,
because those scripts have no spaces. It also rejects unknown fields, so a pane
cannot smuggle in an unagreed shape.

Style is decided and measured. English, in STE100, everywhere. Same three
findings:

| Style | Tokens |
| --- | ---: |
| verbose English prose | 173 |
| English ultra terse | 72 |
| English STE100 | 86 |
| modern Chinese | 102 |
| classical Chinese (wenyan) | loses to English by 1.4x to 2.0x |

Brevity is the saving, language is not, so English it is. STE100 is the style and
not ultra terse: ultra saves 16% by dropping articles and words, and a missing
word that flips a meaning costs more than that.

See [experiments/lang/README.md](experiments/lang/README.md) for the method and
the caveman comparison.

| Variable | Effect |
| --- | --- |
| `4PP_MODEL`, `4PP_THINKING` | Model and thinking level for the panes |
| `4PP_KIND` | Agent kind, default `pi` |
| `4PP_STRICT_NO_WRITE=1` | Read-only tools, no bash |
| `4PP_COORDINATOR_GRANTS_WRITE=1` | Drop the no-write posture for one approved task |
| `4PP_TASK` | Task, instead of positional arguments |

## The roster is personal

Which model or agent backs each seat is your taste, and that taste moves every
time a model ships. There is deliberately no recommended roster here. A
recommendation would read as advice and would be stale within a release. Roster
configuration is not built yet. See `docs/ROADMAP.md`.

## Layout

```
extensions/four-p.ts        pi entry point: registers /4p
commands/4p.md              Claude Code entry point: /4p:4p
.claude-plugin/             Claude Code plugin and marketplace manifests
skill/four-p-panel/         the contract for pi. Named in the singular on purpose:
                            Claude Code auto-scans skills/ at the plugin root, and a
                            second component there would add a second entry to the
                            same /4p: namespace.
panel/4p.py                 the launcher (stdlib only), shared by both hosts
panel/report.schema.json    the report contract, single source of truth
panel/report.py             validate, extract, and describe the contract
tests/                      extension, contract, and brief tests
experiments/jev/            a separate experiment, not part of the tool
```

## Status

0.1.0. Working, single-machine, unpolished. Not published to npm
(`private: true` in `package.json` blocks an accidental publish).

## License

MIT
