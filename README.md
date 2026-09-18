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
- `python3` on your PATH. The launcher is stdlib-only.

## Install

```bash
pi install git:github.com/itlmkz/4p-skill
```

Not published to npm yet.

## Use

```
/4p                  open the panel and leave it standing by
/4p <task>           open it and fan the task out to all four seats
/4p --rebrief <task> re-send the role briefs first
```

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

Your pi session is the only writer of repo code. Panes start with
`--exclude-tools edit,write` and are briefed to leave git alone. They propose
patches. You apply them.

That is a contract, not a sandbox: panes keep `bash` because they need it to run
tests. For the enforced version, set `4PP_STRICT_NO_WRITE=1` and they get
`read,grep,find,ls` only, at the cost of not being able to run anything.

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
extensions/four-p.ts        registers /4p
skills/four-p-panel/        the contract: seats, driving, reporting rules
panel/4p.py                 the launcher (stdlib only)
experiments/jev/            a separate experiment, not part of the tool
```

## Status

0.1.0. Working, single-machine, unpolished. Not published to npm
(`private: true` in `package.json` blocks an accidental publish).

## License

MIT
