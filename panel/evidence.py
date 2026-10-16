#!/usr/bin/env python3
"""Evidence checks for panel findings, run by --collect before the merge.

    python3 evidence.py REPORT.json [--cwd DIR]    print the checks for one report

A finding cites `kind=file` evidence as a repo-relative file and a line. This
module checks what a script can check, and leaves the judgment to the
coordinator:

- the cited file exists inside the repository (the git top level, or the panel
  folder outside git),
- the cited line exists in that file,
- whether the line sits within 5 lines of a change, in current-file line
  numbers (untracked files count as changed),
- the cited line with two lines either side, so the coordinator can apply the
  citation rule without opening the file.

The evidence-check eval (experiments/evidence-eval) measured why the split is
this one: a script cannot tell which line supports a claim, and a strong model
told the citation rule can. So the script never rejects a claim. It only marks
citations that cannot be checked at all.

A path that resolves outside the repository is never read. A pane must not be
able to pull ~/.ssh or /etc into the coordinator's context by citing it. The
check holds against a symlink swapped in between the check and the read: the
file is opened without following a final symlink, and the opened file must be
the same file that passed the check. A pane with a shell can read files by
itself, so this is defense in depth, not a sandbox.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess

try:
    import fcntl
except ImportError:  # not on Windows
    fcntl = None
import sys

EXCERPT_RADIUS = 2  # lines either side of the cited line
NEAR_CHANGE = 5  # the citation rule's tolerance, also used for in_diff
MAX_LINE_CHARS = 200
MAX_READ_BYTES = 8 * 1024 * 1024  # a cited file larger than this is not read
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
GIT = ["git", "-c", "core.quotePath=false"]

# Statuses. Only "ok" carries an excerpt.
OK = "ok"
FILE_MISSING = "file_missing"
OUTSIDE_REPO = "outside_repo"
LINE_OUT_OF_RANGE = "line_out_of_range"
NOT_CHECKED = "not_checked"

# A path whose every line counts as changed: an untracked file.
WHOLE_FILE = None


def changed_lines(diff: str) -> dict[str, set[int]]:
    """Map each file in a unified diff to its changed lines, in current-file numbers.

    An added line counts at its own line. A removed line has no line in the
    current file, so it counts at the place it was removed from. Lines are
    split on newline only, so a form feed inside a line cannot shift numbers.
    """
    out: dict[str, set[int]] = {}
    new_path = None
    new_no = 0
    in_hunk = False
    for raw in diff.split("\n"):
        line = raw[:-1] if raw.endswith("\r") else raw
        if line.startswith("+++ ") and not in_hunk:
            new_path = _strip_prefix(line[4:])
            continue
        if line.startswith("--- ") and not in_hunk:
            continue
        m = HUNK.match(line)
        if m:
            new_no = int(m.group(3))
            # A pure deletion hunk names the line before the gap; count the gap itself.
            if m.group(4) == "0":
                new_no += 1
            in_hunk = True
            continue
        if line.startswith("diff --git "):
            in_hunk = False
            continue
        if not in_hunk or not new_path or new_path == "/dev/null":
            continue
        if line.startswith("+"):
            out.setdefault(new_path, set()).add(new_no)
            new_no += 1
        elif line.startswith("-"):
            out.setdefault(new_path, set()).add(new_no)
        elif line.startswith("\\"):
            continue
        else:
            new_no += 1
    return out


def _strip_prefix(path: str) -> str:
    path = path.split("\t", 1)[0].strip()
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def _git(cwd: str, *args: str) -> tuple[str | None, str]:
    try:
        proc = subprocess.run(
            [*GIT, "-C", cwd, *args], capture_output=True, timeout=30,
            encoding="utf-8", errors="replace",
        )
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return None, f"git unavailable: {exc}"
    if proc.returncode != 0:
        return None, proc.stderr.strip() or f"git {args[0]} failed"
    return proc.stdout, ""


def repo_root(cwd: str) -> str:
    """The git top level of cwd, or cwd itself outside a repository."""
    out, _ = _git(cwd, "rev-parse", "--show-toplevel")
    return out.strip() if out and out.strip() else cwd


def git_diff(cwd: str) -> tuple[dict[str, set[int] | None] | None, str]:
    """Changed lines of the working tree against HEAD, keyed by repo-relative path.

    Untracked files map to WHOLE_FILE. Returns (None, reason) when git cannot
    answer, for example outside a repository or before the first commit. Fixed
    prefixes and no quoting keep the paths stable whatever the user's git config.
    """
    root = repo_root(cwd)
    diff, why = _git(root, "diff", "HEAD", "--no-color", "--no-ext-diff", "--no-textconv",
                     "-U0", "--src-prefix=a/", "--dst-prefix=b/")
    if diff is None:
        return None, why
    lines: dict[str, set[int] | None] = dict(changed_lines(diff))
    untracked, _ = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    for path in (untracked or "").split("\0"):
        if path:
            lines[path] = WHOLE_FILE
    return lines, ""


def resolve_inside(root: str, cited: str) -> str | None:
    """Absolute real path of cited under root, or None when it escapes root or cannot resolve."""
    try:
        base = os.path.realpath(root)
        target = os.path.realpath(os.path.join(base, cited))
    except (OSError, ValueError, RecursionError):
        return None
    if target != base and not target.startswith(base + os.sep):
        return None
    return target


def _fd_path(fd: int) -> str | None:
    """Where the kernel says an open file lives, or None when the platform cannot say."""
    if fcntl is not None and hasattr(fcntl, "F_GETPATH"):  # macOS
        try:
            raw = fcntl.fcntl(fd, fcntl.F_GETPATH, bytes(1024))
            return raw.split(b"\0", 1)[0].decode("utf-8", errors="replace")
        except OSError:
            return None
    try:  # Linux
        return os.readlink(f"/proc/self/fd/{fd}")
    except OSError:
        return None


def _read_window(path: str, root: str, line: int) -> tuple[str, list[str] | int | None]:
    """Open path safely and read up to line + EXCERPT_RADIUS.

    Returns (status, lines) where lines is the list read so far, or an int
    line count when the file ended before the cited line.
    """
    try:
        expected = os.stat(path)
    except (OSError, ValueError):
        return FILE_MISSING, None
    if not stat.S_ISREG(expected.st_mode):
        return FILE_MISSING, None
    if expected.st_size > MAX_READ_BYTES:
        return NOT_CHECKED, None
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except (OSError, ValueError):
        return FILE_MISSING, None
    with os.fdopen(fd, "rb") as fh:
        got = os.fstat(fh.fileno())
        # The file that was opened must be the file that passed the check, and
        # the kernel must place it inside the repository. A folder swapped for a
        # symlink after the check fails one of the two.
        if (got.st_dev, got.st_ino) != (expected.st_dev, expected.st_ino) or not stat.S_ISREG(got.st_mode):
            return OUTSIDE_REPO, None
        real = _fd_path(fh.fileno())
        if real is not None and resolve_inside(root, real) is None:
            return OUTSIDE_REPO, None
        data = fh.read(MAX_READ_BYTES + 1)
    if len(data) > MAX_READ_BYTES:
        return NOT_CHECKED, None
    text = data.decode("utf-8", errors="replace")
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in text.split("\n")]
    if lines and lines[-1] == "":
        lines.pop()  # a final newline does not start another line
    if line > len(lines):
        return LINE_OUT_OF_RANGE, len(lines)
    return OK, lines[: line + EXCERPT_RADIUS]


def check_evidence(evidence: dict, root: str, diff_lines: dict | None) -> dict:
    """One check, for one finding's evidence. Never raises on bad input."""
    kind = evidence.get("kind") if isinstance(evidence, dict) else None
    result: dict = {"kind": kind, "status": NOT_CHECKED}
    if kind != "file":
        return result
    cited, line = evidence.get("file"), evidence.get("line")
    result.update({"file": cited, "line": line, "in_diff": None})
    if not isinstance(cited, str) or not cited:
        result.update(status=FILE_MISSING, reason="no cited path")
        return result
    if not isinstance(line, int) or isinstance(line, bool) or line < 1:
        result.update(status=LINE_OUT_OF_RANGE, reason="the cited line is not a positive integer")
        return result
    path = resolve_inside(root, cited)
    if path is None:
        result.update(status=OUTSIDE_REPO, reason="the path resolves outside the repository")
        return result
    status, got = _read_window(path, root, line)
    if status != OK:
        reasons = {
            FILE_MISSING: "not a readable regular file",
            NOT_CHECKED: f"the file is larger than {MAX_READ_BYTES} bytes",
            LINE_OUT_OF_RANGE: f"the file has {got} lines",
            OUTSIDE_REPO: "the file changed between the check and the read",
        }
        result.update(status=status, reason=reasons[status])
        return result
    lines = got
    lo, hi = max(1, line - EXCERPT_RADIUS), min(len(lines), line + EXCERPT_RADIUS)
    width = len(str(hi))
    excerpt = []
    for n in range(lo, hi + 1):
        mark = ">>" if n == line else "  "
        excerpt.append(f"{mark} {n:>{width}} | {lines[n - 1][:MAX_LINE_CHARS]}")
    result["status"] = OK
    result["excerpt"] = "\n".join(excerpt)
    if diff_lines is not None:
        rel = os.path.relpath(path, os.path.realpath(root))
        if rel in diff_lines:
            changed = diff_lines[rel]
            result["in_diff"] = True if changed is WHOLE_FILE else any(abs(line - n) <= NEAR_CHANGE for n in changed)
        else:
            result["in_diff"] = False
    return result


def check_report(report: object, root: str, diff_lines: dict | None) -> list[dict]:
    """Checks for every finding of one report, in finding order. Never raises."""
    if not isinstance(report, dict) or not isinstance(report.get("findings"), list):
        return []
    checks = []
    for index, finding in enumerate(report["findings"]):
        if not isinstance(finding, dict):
            continue
        try:
            check = check_evidence(finding.get("evidence") or {}, root, diff_lines)
        except Exception as exc:  # one odd citation must never cost the panel its reports
            check = {"kind": None, "status": NOT_CHECKED, "reason": f"check failed: {type(exc).__name__}"}
        checks.append({"finding": finding.get("id", ""), "index": index, **check})
    return checks


def main() -> int:
    args = sys.argv[1:]
    cwd = os.getcwd()
    if "--cwd" in args:
        i = args.index("--cwd")
        cwd = args[i + 1]
        args = args[:i] + args[i + 2:]
    if len(args) != 1:
        print(__doc__)
        return 2
    with open(args[0]) as fh:
        report = json.load(fh)
    diff_lines, _ = git_diff(cwd)
    print(json.dumps(check_report(report, repo_root(cwd), diff_lines), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
