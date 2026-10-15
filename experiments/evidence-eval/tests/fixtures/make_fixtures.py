#!/usr/bin/env python3
"""Writes the synthetic items and runs that the metrics tests and report demo use.

Not real data. Deterministic (seed 7), so the files only change when this does.

    python3 tests/fixtures/make_fixtures.py
"""

from __future__ import annotations

import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))

TRUE_KINDS = {"mechanical": ["true_added", "true_removed"], "semantic": ["true_behavior"]}
FALSE_KINDS = {
    "mechanical": ["wrong_line", "wrong_file", "negated", "fabricated"],
    "semantic": ["false_misread", "false_causality", "false_overclaim", "false_outside_diff"],
    "decoy": ["empty_diff", "truncated_evidence", "right_claim_wrong_line"],
}


def build_items() -> list[dict]:
    items = []
    plan = [("mechanical", "mech", 6, 3), ("semantic", "sem", 6, 2), ("decoy", "decoy", 0, 2)]
    for tier, prefix, per_true, per_false in plan:
        n = 0
        kinds = [(k, True) for k in TRUE_KINDS.get(tier, []) for _ in range(per_true)]
        kinds += [(k, False) for k in FALSE_KINDS[tier] for _ in range(per_false)]
        for kind, label in kinds:
            n += 1
            empty = kind == "empty_diff"
            items.append({
                "id": f"{prefix}-{n:04d}",
                "tier": tier,
                "kind": kind,
                "source": {"repo": "example/synthetic", "commit": f"{n:040x}"},
                "diff": "" if empty else f"--- a/f{n}.py\n+++ b/f{n}.py\n@@ -1 +1 @@\n-x = {n}\n+x = {n + 1}\n",
                "finding": {"role": "reviewer", "claim": f"synthetic claim {n}",
                            "evidence": {"kind": "file", "file": f"f{n}.py", "line": 1}},
                "label": label,
                "label_basis": "construction",
                "rationale": "synthetic fixture item",
            })
    return items


def arm_p(arm: str, item: dict, rng: random.Random) -> float:
    y, tier = item["label"], item["tier"]
    if arm == "accept_all":
        return 1.0
    if arm == "jev":
        if item["kind"] == "empty_diff":
            return rng.choice([0.08, 0.12])
        mu = (0.78 if y else 0.22) if tier != "semantic" else (0.62 if y else 0.42)
        sd = 0.15
    elif arm == "haiku":
        mu, sd = (0.66 if y else 0.42), 0.2
    else:  # opus
        mu = (0.68 if y else 0.4) if tier != "semantic" else (0.82 if y else 0.25)
        sd = 0.22
    return round(min(max(rng.gauss(mu, sd), 0.01), 0.99), 2)


SPEC = {  # arm: (model, cost per item, latency mean, ids that error)
    "accept_all": (None, 0.0, 0.0, set()),
    "jev": ("typesafe/jev-1.13", 0.0004, 0.9, {"sem-0003"}),
    "haiku": ("anthropic/claude-haiku-5.5", 0.0021, 1.6, {"mech-0020"}),
    "opus": ("anthropic/claude-opus-5.5", 0.0310, 6.5, set()),
}


def main() -> None:
    items = build_items()
    with open(os.path.join(HERE, "items.jsonl"), "w") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")
    for arm, (model, cost, lat, errs) in SPEC.items():
        rng = random.Random(f"7-{arm}")
        with open(os.path.join(HERE, "runs", f"{arm}.jsonl"), "w") as f:
            for it in items:
                err = it["id"] in errs
                p = None if err else arm_p(arm, it, rng)
                f.write(json.dumps({
                    "item_id": it["id"], "arm": arm, "model": model, "p": p,
                    "cost_usd": 0.0 if err else cost,
                    "latency_s": round(lat * rng.uniform(0.7, 1.4), 2) if lat else 0.0,
                    "error": "HTTP 529: overloaded" if err else None,
                    "raw": None if err else json.dumps({"p_supported": p}),
                }) + "\n")
    print(f"wrote {len(items)} items and {len(SPEC)} runs to {HERE}")


if __name__ == "__main__":
    main()
