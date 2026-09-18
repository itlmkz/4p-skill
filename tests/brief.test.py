#!/usr/bin/env python3
"""Tests for the pane brief, the input half of the contract.

    python3 tests/brief.test.py

The brief is generated, so it can drift from the schema or ship an unsubstituted
placeholder. Both are caught here.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(HERE, "..", "panel")
sys.path.insert(0, PANEL)

spec = importlib.util.spec_from_file_location("fourp", os.path.join(PANEL, "4p.py"))
fourp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fourp)

from report import describe, load_schema  # noqa: E402

failures = 0


def check(label: str, got, want) -> None:
    global failures
    ok = got == want
    if not ok:
        failures += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        got  {got!r}\n        want {want!r}")


CONTRACT, VALIDATOR = fourp.load_contract()
CTX = {
    "CWD": "/repo/x",
    "TAB_ID": "ws:1",
    "PANE_ID": "pane-2",
    "CALLER_PANE": "pane-1",
    "TOOL_POSTURE": "read-only tools",
    "REPORT_RULE": "Answer in your pane only.",
    "CONTRACT": CONTRACT,
    "VALIDATOR": VALIDATOR,
    "BRIEF_VERSION": fourp.BRIEF_VERSION,
    "PEERS": "a=1, b=2",
}

BRIEFS = {role: fourp.brief_for(role, CTX) for role in fourp.ROLE_ORDER}

# --- shape -------------------------------------------------------------------

check("every ordered role has a brief", sorted(BRIEFS), sorted(fourp.ROLE_ORDER))
check("ordered roles match the briefs dict", sorted(fourp.ROLE_ORDER), sorted(fourp.ROLE_BRIEFS))
check("version tag is 4p/brief@1", fourp.BRIEF_VERSION, "4p/brief@1")

for role, brief in BRIEFS.items():
    check(f"{role}: carries the version tag", fourp.BRIEF_VERSION in brief, True)
    check(f"{role}: names its own role", f"role={role}" in brief, True)
    check(f"{role}: names its seat label", f"seat={fourp.LABEL_PREFIX}{role}" in brief, True)
    check(f"{role}: states the write rule", "only writer" in brief, True)
    check(f"{role}: forbids prose outside the block", "Write no prose before it" in brief, True)
    check(f"{role}: gives the self-check command", "--validate -" in brief, True)
    check(f"{role}: states STE100", "Simplified Technical English" in brief, True)
    check(f"{role}: states the 20-word limit", "20 words maximum" in brief, True)
    check(f"{role}: forbids the em dash", "no em dash" in brief, True)
    check(f"{role}: forbids manufactured objections", "manufacture objections" in brief, True)
    check(f"{role}: has no em dash itself", "\u2014" not in brief, True)
    check(f"{role}: under 6 KB", len(brief) < 6000, True)
    # An unsubstituted Template placeholder is a silent briefing bug.
    leftovers = re.findall(r"\$[A-Z_]{3,}", brief)
    check(f"{role}: no unsubstituted placeholders", leftovers, [])

# --- the contract in the brief is the contract in the schema -----------------

check("brief contract is derived from the schema", CONTRACT, describe(load_schema()))
check("validator path exists", os.path.isfile(VALIDATOR), True)
for role, brief in BRIEFS.items():
    check(f"{role}: brief embeds the contract verbatim", CONTRACT in brief, True)

# --- the roles stay distinct -------------------------------------------------

check("AMO asks for assumptions", "assumptions[]" in BRIEFS["contraire"], True)
check("AMO asks for owner decisions with a recommendation", "questions[]" in BRIEFS["contraire"], True)
check("AMO blocks only on real risk", "Never block on taste" in BRIEFS["contraire"], True)
check("tester maps outcomes to verdicts", "verified gives ship" in BRIEFS["tester"], True)
check("tester must not claim unobserved results", "did not observe" in BRIEFS["tester"], True)
check("reviewer must read the real diff", "Read the real diff" in BRIEFS["reviewer"], True)
check("reviewer has a severity ladder", "blocking, should-fix, or nit" in BRIEFS["reviewer"], True)
check("big picture grounds claims in files", "Ground each claim in a repo file" in BRIEFS["bigpicture"], True)
check(
    "roles are not clones of each other",
    len({BRIEFS[r].split("[ROLE]")[1] for r in fourp.ROLE_ORDER}),
    len(fourp.ROLE_ORDER),
)

# --- AMO seat naming ---------------------------------------------------------

check("the AMO seat is named in the brief header", "AMO" in BRIEFS["contraire"], True)
check("the launcher keeps the 4pp label for idempotency", fourp.LABEL_PREFIX, "4pp:")


print()
if failures:
    print(f"{failures} check(s) failed")
    sys.exit(1)
print("all checks passed")
