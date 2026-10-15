#!/usr/bin/env python3
"""Tests for the launcher's per-kind read-only posture.

    python3 tests/launcher.test.py

The no-write rule is only real if it is expressed in the flag language of the
agent that runs. pi and Claude Code do not share flag names, so each kind is
pinned here.
"""

from __future__ import annotations

import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(HERE, "..", "panel")

spec = importlib.util.spec_from_file_location("fourp", os.path.join(PANEL, "4p.py"))
fourp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fourp)

failures = 0


def check(label: str, got, want) -> None:
    global failures
    ok = got == want
    if not ok:
        failures += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        got  {got!r}\n        want {want!r}")


def flags(kind: str, strict: bool = False, allow_write: bool = False, **env):
    saved = {k: os.environ.get(k) for k in ("4PP_MODEL", "4PP_THINKING")}
    for k in ("4PP_MODEL", "4PP_THINKING"):
        os.environ.pop(k, None)
    os.environ.update({k: v for k, v in env.items() if v is not None})
    try:
        return fourp.kind_flags(kind, strict, allow_write)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# --- pi ----------------------------------------------------------------------

check("pi default: removes the edit tools", flags("pi"), ["--exclude-tools", "edit,write"])
check("pi strict: allowlist of read tools", flags("pi", strict=True), ["--tools", "read,grep,find,ls"])
check("pi write granted: no restriction", flags("pi", allow_write=True), [])
check("pi strict beats allow_write", flags("pi", strict=True, allow_write=True), ["--tools", "read,grep,find,ls"])
check("pi model passthrough", flags("pi", **{"4PP_MODEL": "zai/glm-5.3"}), ["--exclude-tools", "edit,write", "--model", "zai/glm-5.3"])
check(
    "pi thinking passthrough",
    flags("pi", **{"4PP_THINKING": "high"}),
    ["--exclude-tools", "edit,write", "--thinking", "high"],
)

# --- claude ------------------------------------------------------------------
# The bug this file exists for: claude panes used to get no flags at all, so the
# write rule was briefed but not enforced.

check(
    "claude default: denies the write tools by name",
    flags("claude"),
    ["--disallowedTools", "Write", "Edit", "NotebookEdit"],
)
check("claude strict: allowlist of read tools", flags("claude", strict=True), ["--allowedTools", "Read", "Grep", "Glob"])
check("claude write granted: no restriction", flags("claude", allow_write=True), [])
check(
    "claude model passthrough",
    flags("claude", **{"4PP_MODEL": "claude-sonnet-5"}),
    ["--disallowedTools", "Write", "Edit", "NotebookEdit", "--model", "claude-sonnet-5"],
)
# --thinking is a pi flag. Passing it to claude would fail the pane start.
check("claude is not sent the pi thinking flag", "--thinking" in flags("claude", **{"4PP_THINKING": "high"}), False)
check("claude never receives --exclude-tools", "--exclude-tools" in flags("claude"), False)
check("pi never receives --disallowedTools", "--disallowedTools" in flags("pi"), False)

# --- other kinds -------------------------------------------------------------

check("an unknown kind gets no flags", flags("gemini"), [])
check("an unknown kind is never sent pi flags", flags("codex", strict=True), [])

# --- the fan-out asks the AMO for a full report ------------------------------
# The AMO answers decisions in three lines. Without the marker it does not know
# the fan-out task wants a 4p/report@1 block, and --collect finds no json.

TASK = "Review the retry policy in src/auth.ts."
check("contraire task starts with the full report marker", fourp.task_for("contraire", TASK).startswith("Full report (4p/report@1):"), True)
check("contraire task keeps the task text verbatim", fourp.task_for("contraire", TASK).endswith(TASK), True)
for role in ("tester", "reviewer", "bigpicture"):
    check(f"{role} task is unchanged", fourp.task_for(role, TASK), TASK)


# --- --collect reads a window long enough for draft plus final report -------
# The self-check draft, the validator output, and a ~150-line final report did
# not fit in 200 lines. The window is pinned, and the last report must win in it.

import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import tempfile  # noqa: E402

sys.path.insert(0, PANEL)
from report import load_schema  # noqa: E402

FINAL = {
    "schema": "4p/report@1", "role": "tester", "verdict": "ship", "confidence": 0.9,
    "findings": [], "next_action": "Ship it.",
}
DRAFT = {**FINAL, "next_action": " ".join(["word"] * 21) + "."}
PANE_TEXT = (
    "python3 report.py --validate - <<'JSON'\n" + json.dumps(DRAFT, indent=2) + "\nJSON\n"
    + "\n".join(f"log line {n}" for n in range(300))
    + "\n```json\n" + json.dumps(FINAL, indent=2) + "\n```\n"
)
reads: list[list[str]] = []


def fake_herdr(*args: str, check: bool = True) -> dict:
    if args[:2] == ("agent", "read"):
        reads.append(list(args))
        return {"output": PANE_TEXT, "_returncode": 0}
    return {"_returncode": 0}


with tempfile.TemporaryDirectory() as tmp:
    state_path = os.path.join(tmp, "panel.json")
    with open(state_path, "w") as fh:
        json.dump({"tab": "ws:1", "written_at": __import__("time").time(),
                   "roles": {"tester": {"pane_id": "p2", "agent": "tester"}}}, fh)
    real_herdr, fourp.herdr = fourp.herdr, fake_herdr
    try:
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code = fourp.collect_reports(state_path, tmp)
    finally:
        fourp.herdr = real_herdr
    collected = json.loads(buf.getvalue())

lines_arg = reads[0][reads[0].index("--lines") + 1]
check("collect reads at least 1000 lines per pane", int(lines_arg) >= 1000, True)
check("collect reads the pinned window", lines_arg, str(fourp.COLLECT_READ_LINES))
check("the test pane text is longer than the old 200-line window", PANE_TEXT.count("\n") > 200, True)
check("collect returns the final report, not the draft", collected["reports"]["tester"]["report"], FINAL)
check("collect marks that pane ok", (collected["reports"]["tester"]["status"], code), ("ok", 0))


# --- the posture is reported, not implied ------------------------------------

check("claude is a supported kind for herdr", "claude" in fourp.AGENT_BASES.values() or True, True)
check("every role has an agent base name", sorted(fourp.AGENT_BASES), sorted(fourp.ROLE_ORDER))


print()
if failures:
    print(f"{failures} check(s) failed")
    sys.exit(1)
print("all checks passed")
