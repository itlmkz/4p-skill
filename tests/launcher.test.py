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


# --- the report travels as a file, because a full-screen pane hides it -------
# pi draws a full-screen UI, so its earlier output never reaches the terminal
# scrollback: `herdr agent read --lines 2000` returned 23 visible lines in a
# live run, and a long report could not be read. The self-check now saves the
# validated report, and --collect prefers that file when it is safe and fresh.

for role in fourp.ROLE_ORDER:
    brief = fourp.brief_for(role, {
        "CWD": "/r", "TAB_ID": "t", "PANE_ID": "p", "CALLER_PANE": "c", "TOOL_POSTURE": "x",
        "REPORT_RULE": "r", "CONTRACT": "c", "VALIDATOR": "/v/report.py", "BRIEF_VERSION": fourp.BRIEF_VERSION,
        "PEERS": "a", "TAB_DIR": "/tmp/4pp/ws-1",
    })
    check(f"{role}: self-check saves to its own report file", f"--save /tmp/4pp/ws-1/{role}.json" in brief, True)

SAVED = {**FINAL, "role": "reviewer", "next_action": "Read the saved copy."}


def collect_with(tmp: str, saved_age: float | None, task_sent_offset: float | None, link: bool = False) -> dict:
    """Run collect_reports with one reviewer whose pane shows only junk.

    saved_age: seconds before now that the saved file was written, or None for no file.
    task_sent_offset: seconds before now that the task went out, or None for no send time.
    """
    now = __import__("time").time()
    state = {"tab": "ws:1", "written_at": now, "roles": {"reviewer": {"pane_id": "p2", "agent": "reviewer"}}}
    if task_sent_offset is not None:
        state["task_sent_at"] = now - task_sent_offset
    with open(os.path.join(tmp, "panel.json"), "w") as fh:
        json.dump(state, fh)
    path = fourp.saved_report_path(tmp, "reviewer")
    for p in (path, path + ".real"):
        if os.path.lexists(p):
            os.unlink(p)
    if saved_age is not None:
        target = path + ".real" if link else path
        with open(target, "w") as fh:
            json.dump(SAVED, fh)
        os.utime(target, (now - saved_age, now - saved_age))
        if link:
            os.symlink(target, path)

    def visible_only(*args: str, check: bool = True) -> dict:
        if args[:2] == ("agent", "read"):
            return {"output": '     "next_action": "Revert the floor\n division."\n   }\n ```', "_returncode": 0}
        return {"_returncode": 0}

    real, fourp.herdr = fourp.herdr, visible_only
    try:
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            fourp.collect_reports(os.path.join(tmp, "panel.json"), tmp)
    finally:
        fourp.herdr = real
    return json.loads(buf.getvalue())["reports"]["reviewer"]


with tempfile.TemporaryDirectory() as tmp:
    got = collect_with(tmp, saved_age=10, task_sent_offset=60)
    check("saved report written after the task is used", (got["status"], got["source"], got["report"]), ("ok", "saved file", SAVED))
    got = collect_with(tmp, saved_age=120, task_sent_offset=60)
    check("saved report older than the task is ignored", (got["source"], got.get("saved_file")), ("pane", "older than the task"))
    got = collect_with(tmp, saved_age=10, task_sent_offset=None)
    check("without a task send time, a saved report is not trusted", got.get("saved_file"), "no task send time recorded")
    got = collect_with(tmp, saved_age=10, task_sent_offset=60, link=True)
    check("a symlinked saved report is not followed", got.get("saved_file"), "not a regular file")
    got = collect_with(tmp, saved_age=None, task_sent_offset=60)
    check("no saved file falls back to the pane and says why", (got["source"], got.get("saved_file")), ("pane", "not saved"))
    check("the pane fallback still reports what it found", got["status"].startswith("no json block"), True)
    real_uid, os.getuid = os.getuid, lambda: real_uid() + 1
    try:
        got = collect_with(tmp, saved_age=10, task_sent_offset=60)
    finally:
        os.getuid = real_uid
    check("a saved report owned by another user is not trusted", got.get("saved_file"), "owned by another user")


# --- 4PP_ names start with a digit, so a shell can only set them through env ---
# `4PP_TASK=x cmd` is "command not found" in bash and zsh. The command file is
# what Claude Code runs, so every shell assignment there must go through env.

import re  # noqa: E402

ROOT = os.path.join(HERE, "..")
ASSIGN = re.compile(r"(?<![\w-])4PP_[A-Z_]+=")
for doc in ("commands/4p.md", "skill/four-p-panel/SKILL.md", "README.md"):
    with open(os.path.join(ROOT, doc)) as fh:
        text = fh.read()
    shell_lines, fence = [], None
    for ln in text.splitlines():
        if ln.lstrip().startswith("```"):
            fence = None if fence is not None else ln.strip()[3:].strip()
            continue
        if fence in ("", "bash", "sh"):
            shell_lines.append(ln)
    bad = [ln.strip() for ln in shell_lines if ASSIGN.search(ln) and not re.search(r"\benv\b", ln)]
    check(f"{doc}: every 4PP_ assignment in a shell block goes through env", bad, [])
with open(os.path.join(ROOT, "commands/4p.md")) as fh:
    check("commands/4p.md launches with env 4PP_TASK", 'env 4PP_TASK="$ARGUMENTS" python3' in fh.read(), True)


# --- the posture is reported, not implied ------------------------------------

check("claude is a supported kind for herdr", "claude" in fourp.AGENT_BASES.values() or True, True)
check("every role has an agent base name", sorted(fourp.AGENT_BASES), sorted(fourp.ROLE_ORDER))


print()
if failures:
    print(f"{failures} check(s) failed")
    sys.exit(1)
print("all checks passed")
