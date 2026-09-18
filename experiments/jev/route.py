#!/usr/bin/env python3
"""Pre-flight router for the 4p advisory panel.

Reads a diff, asks Jev how many seats the change warrants, then composes the
answer in Python against thresholds defined at the top of this file.

    python3 route.py                    # working tree, else the HEAD commit
    python3 route.py --rev <commit>     # a specific commit
    python3 route.py --diff FILE        # a diff on disk
    python3 route.py --task "..."       # extra task context
    python3 route.py --json             # raw answers, nothing composed
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jev import ask, choice, cost_of, noul  # noqa: E402

# --- thresholds. The part a human should review. ---------------------------

LOW_CONFIDENCE = 0.6  # below this the seat label is noise, so take the safe default
TRIVIAL_AT = 0.8  # above this, one seat is enough
RISK_AT = 0.5  # a trust boundary or one-way door at or above this means the full panel
MAX_DIFF_CHARS = 48000  # Jev's context is 32k tokens; keep the state well inside it

# --- the questions. Also worth reviewing. ----------------------------------

QUESTIONS = {
    "seats": choice(
        "How many advisory seats does this change warrant?",
        {
            "one_reviewer": "Small, local, reversible",
            "reviewer_and_tester": "Needs both review and an empirical check",
            "full_panel": "Risky, cross-cutting, or a load-bearing decision",
        },
    ),
    "is_one_way_door": noul(
        "Would undoing this change be expensive after it ships?",
        true="Requires a migration, a data change, or a public interface change",
        false="Reverting the commit is enough",
    ),
    "touches_trust_boundary": noul(
        "Does this change authentication, authorization, payments, or user data?",
        true="Touches a trust boundary",
        false="Does not touch a trust boundary",
    ),
    "is_trivial": noul(
        "Is this a trivial change that a single reviewer can settle?",
        true="Cosmetic, documentation, or a one-line mechanical fix",
        false="Substantive logic or behavior change",
    ),
}

ROLES = ["contraire", "tester", "reviewer", "bigpicture"]


def git(*args: str) -> tuple[str, str]:
    """Return (stdout, error). error is non-empty when git failed.

    The error must be surfaced. An earlier version returned "" on failure, which
    sent an empty diff to Jev, and Jev answered it at 0.98 confidence.
    """
    proc = subprocess.run(["git", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        return "", proc.stderr.strip() or f"git {' '.join(args)} failed"
    return proc.stdout, ""


def _nonempty(text: str, origin: str) -> str:
    if not text.strip():
        sys.exit(
            f"route: {origin} produced an empty diff.\n"
            "       Not asking Jev about nothing: on an empty state it still returned\n"
            "       a confident answer during testing. Run this inside the repository\n"
            "       under review, or pass --diff <file>."
        )
    return text


def load_diff(rev: str | None, path: str | None) -> tuple[str, str, str]:
    """Return (diff, diffstat, where it came from)."""
    if path:
        try:
            with open(path) as fh:
                text = fh.read()
        except OSError as exc:
            sys.exit(f"route: cannot read {path}: {exc}")
        return _nonempty(text, path), "", path

    inside, err = git("rev-parse", "--is-inside-work-tree")
    if err or inside.strip() != "true":
        sys.exit("route: not inside a git repository. Pass --diff <file>, or run this where the code is.")

    if rev:
        diff, err = git("show", "--format=", rev)
        if err:
            sys.exit(f"route: {err}")
        stat, _ = git("show", "--stat", "--format=", rev)
        return _nonempty(diff, f"git show {rev}"), stat, f"git show {rev}"

    diff, err = git("diff", "HEAD")
    if err:
        sys.exit(f"route: {err}")
    if diff.strip():
        stat, _ = git("diff", "--stat", "HEAD")
        return diff, stat, "git diff HEAD (working tree)"

    diff, err = git("show", "--format=", "HEAD")
    if err:
        sys.exit(f"route: {err}")
    stat, _ = git("show", "--stat", "--format=", "HEAD")
    return _nonempty(diff, "git show HEAD"), stat, "git show HEAD (working tree was clean)"


def decide(answers: dict) -> tuple[int, str]:
    """Compose the seat count in code. Order matters. Returns (seats, reason)."""
    seats = answers["seats"]
    confidence = seats["confidence"]
    trust = answers["touches_trust_boundary"]["noul"]
    one_way = answers["is_one_way_door"]["noul"]
    trivial = answers["is_trivial"]["noul"]

    if confidence < LOW_CONFIDENCE:
        return 4, f"seat label was low confidence ({confidence:.2f}), so take the safe default"
    if trivial >= TRIVIAL_AT:
        return 1, f"trivial change ({trivial:.2f})"
    if trust >= RISK_AT or one_way >= RISK_AT or seats["choice"] == "full_panel":
        return 4, f"risk signal: trust boundary {trust:.2f}, one-way door {one_way:.2f}"
    if seats["choice"] == "reviewer_and_tester":
        return 2, "needs review plus an empirical check"
    return 1, "small, local, reversible"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rev", help="commit to inspect, instead of the working tree")
    ap.add_argument("--diff", help="path to a diff file")
    ap.add_argument("--task", default="", help="extra task context for the router")
    ap.add_argument("--model", default=None, help="override the Jev model id")
    ap.add_argument("--json", action="store_true", help="print raw answers only")
    args = ap.parse_args()

    diff, diffstat, origin = load_diff(args.rev, args.diff)
    truncated = len(diff) > MAX_DIFF_CHARS
    # diffstat carries the complete file list, so it survives diff truncation.
    state = {
        "task": args.task or "(no task description supplied)",
        "diffstat": diffstat[:4000],
        "diff": diff[:MAX_DIFF_CHARS],
        "diff_truncated": truncated,
    }

    questions = dict(QUESTIONS)
    kwargs = {"model": args.model} if args.model else {}
    response = ask(state, questions, **kwargs)
    answers = response["answers"]

    if args.json:
        print(json.dumps(response, indent=2))
        return 0

    seats, reason = decide(answers)
    chosen = ROLES if seats == 4 else (["reviewer", "tester"] if seats == 2 else ["reviewer"])

    print(f"route: {origin}" + (" [diff truncated]" if truncated else ""))
    print(f"model {response['model']}   cost {cost_of(response)}\n")
    print(json.dumps(answers, indent=2))
    print("\ncomposed decision:")
    print(f"  seats:  {seats} ({', '.join(chosen)})")
    print(f"  reason: {reason}")
    if seats == 4:
        print("  launch: 4PP_STRICT_NO_WRITE=1 /4p <task>")
    elif seats < 4:
        print(f"  note:   the launcher spawns all four panes today. Send the task only to: {', '.join(chosen)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
