#!/usr/bin/env python3
"""Tests for the evidence checks that --collect attaches to each finding.

    python3 tests/evidence.test.py

The checks decide what the coordinator sees next to each claim, and which
files a pane can make the coordinator read. Both are pinned here.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(HERE, "..", "panel")
sys.path.insert(0, PANEL)

import evidence  # noqa: E402

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


def git(cwd: str, *args: str) -> None:
    subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True,
                   env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull})


def file_ev(path: str, line) -> dict:
    return {"kind": "file", "file": path, "line": line}


# --- changed_lines ------------------------------------------------------------

DIFF = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -3,2 +3,3 @@ def f():
 keep
-old
+new
+added
"""
check("changed lines: in current-file numbers, a removal counts where it happened", evidence.changed_lines(DIFF), {"app.py": {4, 5}})
check("changed lines: a CRLF diff numbers like an LF diff", evidence.changed_lines(DIFF.replace("\n", "\r\n")), {"app.py": {4, 5}})
check(
    "changed lines: a form feed inside a context line does not shift numbers",
    evidence.changed_lines(DIFF.replace(" keep", " ke\fep")),
    {"app.py": {4, 5}},
)
check("changed lines: a new file from /dev/null", evidence.changed_lines(
    "--- /dev/null\n+++ b/n.py\n@@ -0,0 +1,2 @@\n+a\n+b\n"), {"n.py": {1, 2}})
check("changed lines: empty diff", evidence.changed_lines(""), {})
check("changed lines: a pure deletion counts at the gap in the current file",
      evidence.changed_lines("--- a/f\n+++ b/f\n@@ -101,10 +100,0 @@\n" + "-x\n" * 10), {"f": {101}})
check("changed lines: a deleted file has no current lines",
      evidence.changed_lines("--- a/f\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-a\n-b\n"), {})


# --- check_evidence on a real repository --------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, "src"))
    body = "".join(f"line {n}\n" for n in range(1, 31))
    with open(os.path.join(repo, "src", "a.py"), "w") as fh:
        fh.write(body)
    with open(os.path.join(repo, "b.py"), "w") as fh:
        fh.write("only\n")
    git(repo, "init", "-q")
    git(repo, "add", ".")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
    # One change in the working tree, at line 20 of src/a.py.
    with open(os.path.join(repo, "src", "a.py"), "w") as fh:
        fh.write(body.replace("line 20\n", "line twenty\n"))
    with open(os.path.join(tmp, "secret.txt"), "w") as fh:
        fh.write("do not read\n")
    os.symlink(os.path.join(tmp, "secret.txt"), os.path.join(repo, "link.txt"))

    diff_lines, err = evidence.git_diff(repo)
    check("git diff: reads the working tree change, and an untracked file counts whole", (diff_lines, err), ({"src/a.py": {20}, "link.txt": None}, ""))

    ok = evidence.check_evidence(file_ev("src/a.py", 10), repo, diff_lines)
    check("ok: status", ok["status"], "ok")
    check("ok: excerpt is lines 8 to 12 with the cited line marked", ok["excerpt"].split("\n"), [
        "    8 | line 8", "    9 | line 9", ">> 10 | line 10", "   11 | line 11", "   12 | line 12",
    ])
    check("ok: a line far from the change is not in the diff", ok["in_diff"], False)
    check("in_diff: a line within 5 of the change is in the diff", evidence.check_evidence(file_ev("src/a.py", 16), repo, diff_lines)["in_diff"], True)
    check("in_diff: 6 lines away is not", evidence.check_evidence(file_ev("src/a.py", 14), repo, diff_lines)["in_diff"], False)
    check("excerpt: clipped at the first line", evidence.check_evidence(file_ev("src/a.py", 1), repo, diff_lines)["excerpt"].split("\n")[0], ">> 1 | line 1")
    check("excerpt: clipped at the last line", evidence.check_evidence(file_ev("src/a.py", 30), repo, diff_lines)["excerpt"].split("\n")[-1], ">> 30 | line 30")

    check("line 0 is out of range", evidence.check_evidence(file_ev("src/a.py", 0), repo, diff_lines)["status"], "line_out_of_range")
    check("line past the end is out of range", evidence.check_evidence(file_ev("src/a.py", 31), repo, diff_lines)["status"], "line_out_of_range")
    check("a final newline does not add a line", evidence.check_evidence(file_ev("b.py", 2), repo, diff_lines)["status"], "line_out_of_range")
    check("a boolean line is not a line", evidence.check_evidence(file_ev("src/a.py", True), repo, diff_lines)["status"], "line_out_of_range")
    check("a missing file", evidence.check_evidence(file_ev("src/nope.py", 1), repo, diff_lines)["status"], "file_missing")
    check("an empty path", evidence.check_evidence(file_ev("", 1), repo, diff_lines)["status"], "file_missing")

    # A pane must not make the coordinator read files outside the working folder.
    for label, cited in (
        ("a parent path", "../secret.txt"),
        ("an absolute path", os.path.join(tmp, "secret.txt")),
        ("a symlink that leaves the folder", "link.txt"),
        ("an absolute system path", "/etc/hosts"),
    ):
        res = evidence.check_evidence(file_ev(cited, 1), repo, diff_lines)
        check(f"outside repo: {label} is not read", (res["status"], "excerpt" in res), ("outside_repo", False))

    for kind in ("command", "output", "url", "none"):
        check(f"kind {kind} is not checked", evidence.check_evidence({"kind": kind}, repo, diff_lines)["status"], "not_checked")
    check("garbage evidence does not raise", evidence.check_evidence("nonsense", repo, diff_lines)["status"], "not_checked")

    not_repo = os.path.join(tmp, "plain")
    os.makedirs(not_repo)
    with open(os.path.join(not_repo, "x.py"), "w") as fh:
        fh.write("a\n")
    lines_none, why = evidence.git_diff(not_repo)
    check("outside a repository, git gives no diff and a reason", (lines_none is None, bool(why)), (True, True))
    check("in_diff is null when git cannot answer", evidence.check_evidence(file_ev("x.py", 1), not_repo, lines_none)["in_diff"], None)

    report = {"findings": [
        {"id": "r1", "evidence": file_ev("src/a.py", 20)},
        {"id": "r2", "evidence": {"kind": "command", "command": "make test"}},
        {"id": "r3", "evidence": file_ev("../secret.txt", 1)},
    ]}
    checks = evidence.check_report(report, repo, diff_lines)
    check("check_report: one check per finding, in order", [(c["finding"], c["status"]) for c in checks],
          [("r1", "ok"), ("r2", "not_checked"), ("r3", "outside_repo")])
    check("check_report: a report without findings gives no checks", evidence.check_report({"x": 1}, repo, diff_lines), [])

    # --- --collect attaches the checks, end to end through a stubbed herdr ---
    REPORT = {
        "schema": "4p/report@1", "role": "reviewer", "verdict": "fix_first", "confidence": 0.8,
        "findings": [{
            "id": "r1", "severity": "blocking", "claim": "Line twenty changed its text.",
            "evidence": {"kind": "file", "file": "src/a.py", "line": 20}, "blocks": True,
        }],
        "next_action": "Check the new text.",
    }

    def fake_herdr(*args: str, check: bool = True) -> dict:
        if args[:2] == ("agent", "read"):
            return {"output": "```json\n" + json.dumps(REPORT) + "\n```\n", "_returncode": 0}
        return {"_returncode": 0}

    state_path = os.path.join(tmp, "panel.json")
    with open(state_path, "w") as fh:
        json.dump({"tab": "ws:1", "cwd": repo, "written_at": time.time(),
                   "roles": {"reviewer": {"pane_id": "p2", "agent": "reviewer"}}}, fh)
    real_herdr, fourp.herdr = fourp.herdr, fake_herdr
    try:
        with contextlib.redirect_stdout(io.StringIO()) as buf:
            code = fourp.collect_reports(state_path, tmp)
    finally:
        fourp.herdr = real_herdr
    out = json.loads(buf.getvalue())
    got = out["reports"]["reviewer"]
    check("collect: the report is ok", (got["status"], code), ("ok", 0))
    check("collect: evidence_checks ride next to the report, not inside it", "evidence_checks" in got["report"], False)
    check("collect: the finding's check is ok and in the diff", (got["evidence_checks"][0]["status"], got["evidence_checks"][0]["in_diff"]), ("ok", True))
    check("collect: the excerpt shows the changed line", ">> 20 | line twenty" in got["evidence_checks"][0]["excerpt"], True)
    check("collect: names the diff it used", out["diff"], "git diff HEAD plus untracked files")
    check("collect: names the repository root", os.path.realpath(out["root"]), os.path.realpath(repo))
    check("collect: each check carries the finding's index", got["evidence_checks"][0]["index"], 0)
    check("collect: names the working folder", out["cwd"], repo)


# --- review fixes: each case reproduces a verified defect ---------------------

import signal  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    repo = os.path.join(tmp, "repo")
    os.makedirs(os.path.join(repo, "sub"))
    with open(os.path.join(repo, "legacy.c"), "wb") as fh:
        fh.write(b"/* caf\xe9 */\nint x;\n")
    with open(os.path.join(repo, "top.py"), "w") as fh:
        fh.write("".join(f"t{n}\n" for n in range(1, 301)))
    git(repo, "init", "-q")
    git(repo, "config", "diff.mnemonicPrefix", "true")
    git(repo, "config", "diff.noprefix", "true")
    git(repo, "add", ".")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
    with open(os.path.join(repo, "legacy.c"), "wb") as fh:
        fh.write(b"/* caf\xe9 au lait */\nint x;\n")
    # Delete old lines 1 to 100 of top.py: current line 50 is old line 150.
    with open(os.path.join(repo, "top.py"), "w") as fh:
        fh.write("".join(f"t{n}\n" for n in range(101, 301)))
    with open(os.path.join(repo, "uni\u00e9.py"), "w") as fh:
        fh.write("a\nb\n")

    lines_d, err_d = evidence.git_diff(repo)
    check("non-UTF-8 bytes in the diff do not crash git_diff", err_d, "")
    check("user diff config (mnemonicPrefix, noprefix) does not change the keys",
          sorted(k for k in lines_d if k.endswith((".py", ".c"))), sorted(["legacy.c", "top.py", "uni\u00e9.py"]))
    check("a deletion is far from an unchanged line 49 lines below it",
          evidence.check_evidence(file_ev("top.py", 50), repo, lines_d)["in_diff"], False)
    check("a deletion is near the line where it happened",
          evidence.check_evidence(file_ev("top.py", 1), repo, lines_d)["in_diff"], True)
    check("a non-ASCII untracked file counts as changed",
          evidence.check_evidence(file_ev("uni\u00e9.py", 2), repo, lines_d)["in_diff"], True)

    sub = os.path.join(repo, "sub")
    check("from a subfolder, the root is the repository top level",
          os.path.realpath(evidence.repo_root(sub)), os.path.realpath(repo))
    check("from a subfolder, a repo-relative citation resolves",
          evidence.check_evidence(file_ev("top.py", 2), evidence.repo_root(sub), lines_d)["status"], "ok")

    sibling = repo + "X"
    os.makedirs(sibling)
    with open(os.path.join(sibling, "s.txt"), "w") as fh:
        fh.write("sibling secret\n")
    check("a sibling folder that shares the prefix is outside",
          evidence.check_evidence(file_ev("../repoX/s.txt", 1), repo, lines_d)["status"], "outside_repo")

    os.mkfifo(os.path.join(repo, "pipe"))
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("blocked on a FIFO")))
    signal.alarm(3)
    try:
        fifo = evidence.check_evidence(file_ev("pipe", 1), repo, lines_d)["status"]
    except TimeoutError as exc:
        fifo = str(exc)
    finally:
        signal.alarm(0)
    check("a FIFO is not opened and does not block", fifo, "file_missing")

    prev = os.path.join(repo, "chain0")
    with open(prev, "w") as fh:
        fh.write("end\n")
    for n in range(1, 1201):
        cur = os.path.join(repo, f"chain{n}")
        os.symlink(prev, cur)
        prev = cur
    chain = evidence.check_evidence(file_ev("chain1200", 1), repo, lines_d)
    check("a long symlink chain does not raise", chain["status"] in ("outside_repo", "file_missing", "ok"), True)

    big = os.path.join(repo, "big.txt")
    with open(big, "wb") as fh:
        fh.seek(evidence.MAX_READ_BYTES + 10)
        fh.write(b"\n")
    res = evidence.check_evidence(file_ev("big.txt", 1), repo, lines_d)
    check("a file over the read cap is not read", (res["status"], "excerpt" in res), ("not_checked", False))

    with open(os.path.join(repo, "cr.txt"), "wb") as fh:
        fh.write(b"one\rtwo\nthree\n")
    check("a lone CR does not start a line, as in git and sed",
          evidence.check_evidence(file_ev("cr.txt", 2), repo, lines_d)["excerpt"].split("\n")[1], ">> 2 | three")

    # The race: a folder swapped for a symlink after the path check. Calling the
    # reader with the unresolved path reproduces the state the swap leaves.
    outside = os.path.join(tmp, "outside")
    os.makedirs(outside)
    with open(os.path.join(outside, "id_rsa"), "w") as fh:
        fh.write("SECRET\n")
    os.symlink(outside, os.path.join(repo, "swapped"))
    status, got_lines = evidence._read_window(os.path.join(repo, "swapped", "id_rsa"), repo, 1)
    check("a folder swapped for a symlink after the check is not read", (status, got_lines), ("outside_repo", None))

    bad_report = {"findings": [{"id": "r1", "evidence": file_ev("top.py", 1)}, "not a finding",
                               {"id": "r1", "evidence": file_ev("top.py", 2)}]}
    got_checks = evidence.check_report(bad_report, repo, lines_d)
    check("duplicate ids stay apart by index", [(c["finding"], c["index"]) for c in got_checks], [("r1", 0), ("r1", 2)])


print()
if failures:
    print(f"{failures} check(s) failed")
    sys.exit(1)
print("all checks passed")
