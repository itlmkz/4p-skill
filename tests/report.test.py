#!/usr/bin/env python3
"""Tests for the report contract.

    python3 tests/report.test.py

Covers both directions of the machine-to-machine contract: a valid report must
pass, and each class of malformed report must fail with a precise message.
"""

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "panel"))

from report import describe, extract, load_schema, validate_report  # noqa: E402

SCHEMA = load_schema()
failures = 0


def check(label: str, got, want) -> None:
    global failures
    ok = got == want
    if not ok:
        failures += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        got  {got!r}\n        want {want!r}")


def errors_of(report) -> list[str]:
    return validate_report(report, SCHEMA)


def mentions(errors: list[str], fragment: str) -> bool:
    return any(fragment in e for e in errors)


# --- a minimal report is enough ---------------------------------------------

MINIMAL = {
    "schema": "4p/report@1",
    "role": "reviewer",
    "verdict": "fix_first",
    "confidence": 0.8,
    "findings": [
        {
            "id": "r1",
            "severity": "blocking",
            "claim": "The effect never runs again after the first render.",
            "evidence": {"kind": "file", "file": "src/gates.tsx", "line": 41},
            "blocks": True,
        }
    ],
    "next_action": "Remove the guard or add the dependency array.",
}

check("minimal report validates", errors_of(MINIMAL), [])


# --- the full report, every optional field present ---------------------------

FULL = {
    "schema": "4p/report@1",
    "role": "contraire",
    "verdict": "block",
    "confidence": 0.25,
    "findings": [
        {
            "id": "amo-1",
            "severity": "blocking",
            "claim": "The change discards in-flight user state on every token expiry.",
            "evidence": {
                "kind": "file",
                "file": "src/gates.tsx",
                "line": 45,
            },
            "confirm_test": "Expire the token and check whether the form still holds input.",
            "blocks": True,
        },
        {
            "id": "amo-2",
            "severity": "nit",
            "claim": "The helper name hides the redirect side effect.",
            "evidence": {"kind": "none"},
            "blocks": False,
        },
    ],
    "assumptions": [
        {
            "statement": "The refresh call always fails when the token has expired.",
            "if_false": "The redirect never fires and the user stays signed in.",
            "verified": False,
        }
    ],
    "questions": [
        {
            "id": "q1",
            "question": "Should a failed refresh sign the user out or retry once?",
            "recommendation": "Retry once, then sign out.",
            "blocks": True,
        }
    ],
    "could_not_verify": [
        {
            "what": "The expiry path in a real browser session.",
            "blocker": "No browser runtime in this pane.",
        }
    ],
    "next_action": "Decide the retry policy before merging this.",
}

check("full report validates", errors_of(FULL), [])
check("command evidence validates", errors_of({**MINIMAL, "findings": [
    {
        "id": "t1",
        "severity": "should-fix",
        "claim": "The build fails on a clean checkout.",
        "evidence": {"kind": "command", "command": "npm ci && npm run build", "observed": "exit code 1"},
        "blocks": False,
    }
]}), [])
check("empty findings list validates", errors_of({**MINIMAL, "findings": []}), [])


# --- each class of malformed report is caught --------------------------------

check("missing findings", mentions(errors_of({k: v for k, v in MINIMAL.items() if k != "findings"}), "missing required field 'findings'"), True)
check("wrong schema id", mentions(errors_of({**MINIMAL, "schema": "4p/report@2"}), "must be '4p/report@1'"), True)
check("bad role", mentions(errors_of({**MINIMAL, "role": "architect"}), "must be one of"), True)
check("bad verdict", mentions(errors_of({**MINIMAL, "verdict": "maybe"}), "must be one of"), True)
check("bad severity", mentions(errors_of({**MINIMAL, "findings": [{**MINIMAL["findings"][0], "severity": "urgent"}]}), "must be one of"), True)
check("unknown field", mentions(errors_of({**MINIMAL, "summary": "prose"}), "unknown field 'summary'"), True)
check("confidence above 1", mentions(errors_of({**MINIMAL, "confidence": 1.5}), "above maximum 1"), True)
check("confidence as a string", mentions(errors_of({**MINIMAL, "confidence": "high"}), "expected number"), True)
check("blocks as a string", mentions(errors_of({**MINIMAL, "findings": [{**MINIMAL["findings"][0], "blocks": "yes"}]}), "expected boolean"), True)
check("line 0 rejected", mentions(errors_of({**MINIMAL, "findings": [{**MINIMAL["findings"][0], "evidence": {"kind": "file", "file": "a.ts", "line": 0}}]}), "below minimum 1"), True)
check("negative line rejected", mentions(errors_of({**MINIMAL, "findings": [{**MINIMAL["findings"][0], "evidence": {"kind": "file", "file": "a.ts", "line": -3}}]}), "below minimum 1"), True)

# the conditional: a file citation without a line is not checkable
check("file evidence needs a line", mentions(errors_of({**MINIMAL, "findings": [{**MINIMAL["findings"][0], "evidence": {"kind": "file", "file": "a.ts"}}]}), "missing required field 'line'"), True)
check("command evidence needs the command", mentions(errors_of({**MINIMAL, "findings": [{**MINIMAL["findings"][0], "evidence": {"kind": "command"}}]}), "missing required field 'command'"), True)
check("url evidence needs the url", mentions(errors_of({**MINIMAL, "findings": [{**MINIMAL["findings"][0], "evidence": {"kind": "url"}}]}), "missing required field 'url'"), True)
check("kind none needs nothing extra", errors_of({**MINIMAL, "findings": [{**MINIMAL["findings"][0], "evidence": {"kind": "none"}}]}), [])

# the question/assumption shapes are enforced too
check("question needs a recommendation", mentions(errors_of({**MINIMAL, "questions": [{"id": "q1", "question": "Which one?"}]}), "missing required field 'recommendation'"), True)
check("assumption needs if_false", mentions(errors_of({**MINIMAL, "assumptions": [{"statement": "It is fine."}]}), "missing required field 'if_false'"), True)
check("too many findings", mentions(errors_of({**MINIMAL, "findings": [MINIMAL["findings"][0]] * 13}), "maximum is 12"), True)


# --- STE100 is enforced, not merely requested --------------------------------

long_sentence = " ".join(["word"] * 21) + "."
check("21-word sentence rejected", mentions(errors_of({**MINIMAL, "next_action": long_sentence}), "STE100 allows 20"), True)
check("20-word sentence accepted", errors_of({**MINIMAL, "next_action": " ".join(["word"] * 20) + "."}), [])
check(
    "two short sentences are fine",
    errors_of({**MINIMAL, "next_action": "The build fails. Fix the import."}),
    [],
)
check("em dash rejected", mentions(errors_of({**MINIMAL, "next_action": "Fix this \u2014 then ship."}), "em dash"), True)
check(
    "STE100 applies inside findings",
    mentions(errors_of({**MINIMAL, "findings": [{**MINIMAL["findings"][0], "claim": long_sentence}]}), "STE100 allows 20"),
    True,
)
check(
    "an unknown field is not silently dropped",
    mentions(errors_of({**MINIMAL, "findings": [{**MINIMAL["findings"][0], "notes": "extra"}]}), "unknown field 'notes'"),
    True,
)


# --- extraction from raw pane output ----------------------------------------

FENCED = 'Here is my answer.\n\n```json\n' + json.dumps(MINIMAL) + "\n```\n\nThat is all."
check("extract a fenced block", extract(FENCED)[0], MINIMAL)
check("extract a bare object", extract("prefix " + json.dumps(MINIMAL) + " suffix")[0], MINIMAL)
check("extract across prose containing braces", extract("Use {curly} braces. " + json.dumps(MINIMAL))[0], MINIMAL)
check("no json at all", extract("I could not complete the task.")[0], None)
check("malformed json is not accepted", extract("```json\n{oops}\n```")[0], None)
check("extracted report still validates", validate_report(extract(FENCED)[0], SCHEMA), [])


# --- the contract description is derived, so it cannot drift -----------------

contract = describe(SCHEMA)
for token in ["4p/report@1", "blocking|should-fix|nit", "file|command|output|url|none", "STE100", "recommendation", "if_false"]:
    check(f"contract mentions {token}", token in contract, True)


print()
if failures:
    print(f"{failures} check(s) failed")
    sys.exit(1)
print("all checks passed")
