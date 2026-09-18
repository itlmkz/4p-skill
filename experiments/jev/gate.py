#!/usr/bin/env python3
"""Merge gate for the 4p advisory panel.

Reads four panel reports plus the diff they were written against, asks one
batched set of typed questions, then composes a decision in Python.

    python3 gate.py examples/panel-example.json
    python3 gate.py report.json --json

Input contract (this is the structured report shape the panel should return):

    {
      "task": "what the panel was asked",
      "diff": "the diff the panel reviewed",
      "panel": {
        "reviewer":   [{"claim": ..., "evidence": ..., "severity": ...}],
        "contraire":  [...],
        "tester":     [...],
        "bigpicture": [...]
      }
    }
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jev import ask, choice, cost_of, noul, score  # noqa: E402

# --- thresholds. The part a human should review. ---------------------------

UNSUPPORTED_BELOW = 0.5  # a finding below this failed its evidence check
CONTRADICTION_AT = 0.5  # at or above this, the panel disagrees with itself
BLOCKING_AT = 0.8  # at or above this, a real risk is confirmed
UNCERTAIN_LOW, UNCERTAIN_HIGH = 0.4, 0.75  # verdict confidence inside this band means escalate
MAX_STATE_CHARS = 30000


def build_questions(panel: dict) -> tuple[dict, list[tuple[str, str, str]]]:
    """One evidence question per finding, plus cross-cutting questions.

    Returns (questions, index) where index maps question id to (role, claim).
    """
    questions: dict = {}
    index: list[tuple[str, str, str]] = []

    for role, findings in panel.items():
        for i, finding in enumerate(findings):
            key = f"finding_{role}_{i}_supported"
            questions[key] = noul(
                f"Does `diff` support the claim in `panel.{role}[{i}].claim`, "
                f"given the evidence in `panel.{role}[{i}].evidence`?",
                true="The evidence exists in the diff and it supports the claim",
                false="The evidence is missing from the diff, or it does not support the claim",
            )
            index.append((key, role, finding.get("claim", "")))

    questions["any_contradiction"] = noul(
        "Do any two panel reports contradict each other?",
        true="Two reports make claims that cannot both be true",
        false="No two reports are irreconcilable",
    )
    questions["blocking_risk"] = noul(
        "Does any finding describe a real risk, such as data loss, a security hole, "
        "a broken deploy, or a silent behavior change?",
        true="A real risk that should block",
        false="Only taste, style, or nits",
    )
    questions["verdict"] = choice(
        "What should the coordinator do with this change?",
        {
            "ship": "No real risk found, the change is sound",
            "fix_first": "A specific fix is required before shipping",
            "hold": "Needs a decision or more evidence before any work continues",
        },
    )
    questions["review_effort"] = score(
        "How much human attention do these reports deserve?",
        [
            "Nothing, the panel agrees and the evidence is verifiable",
            "A quick read, one claim needs a look",
            "Careful reading, the panel disagrees or evidence is missing",
        ],
    )
    return questions, index


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", help="path to the panel report JSON")
    ap.add_argument("--model", default=None, help="override the Jev model id")
    ap.add_argument("--json", action="store_true", help="print raw answers only")
    args = ap.parse_args()

    with open(args.report) as fh:
        doc = json.load(fh)
    for field in ("task", "diff", "panel"):
        if field not in doc:
            sys.exit(f"gate: report is missing the {field!r} field")

    state = {"task": doc["task"], "diff": doc["diff"][:MAX_STATE_CHARS], "panel": doc["panel"]}
    questions, index = build_questions(doc["panel"])

    kwargs = {"model": args.model} if args.model else {}
    response = ask(state, questions, **kwargs)
    answers = response["answers"]

    if args.json:
        print(json.dumps(response, indent=2))
        return 0

    print(f"gate: {args.report}   {len(index)} findings")
    print(f"model {response['model']}   cost {cost_of(response)}\n")
    print(json.dumps(answers, indent=2))

    unsupported = [(role, claim) for key, role, claim in index if answers[key]["noul"] < UNSUPPORTED_BELOW]
    verdict = answers["verdict"]
    confidence = verdict["confidence"]

    print("\ncomposed decision:")
    if unsupported:
        for role, claim in unsupported:
            print(f"  UNSUPPORTED [{role}] {claim}")
    else:
        print("  every finding passed its evidence check")
    if answers["any_contradiction"]["noul"] >= CONTRADICTION_AT:
        print(f"  CONFLICT: the panel disagrees ({answers['any_contradiction']['noul']:.2f}). Read those reports yourself.")
    print(f"  verdict: {verdict['choice']} (confidence {confidence:.2f})")
    if UNCERTAIN_LOW <= confidence <= UNCERTAIN_HIGH:
        print("  ESCALATE: the verdict is not confident enough to act on")
    if answers["blocking_risk"]["noul"] >= BLOCKING_AT:
        print(f"  BLOCK: real risk confirmed ({answers['blocking_risk']['noul']:.2f})")
    print(f"  human attention: {answers['review_effort']['score']:.2f} / 2")
    return 0


if __name__ == "__main__":
    sys.exit(main())
