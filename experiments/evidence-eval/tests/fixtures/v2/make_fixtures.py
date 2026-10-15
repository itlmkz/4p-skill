#!/usr/bin/env python3
"""Writes the synthetic v2 items and runs (PREREG-v2.md shape) for the metrics tests and report demo.

Not real data. Deterministic (seed 7). Items share commits in groups, so the commit
bootstrap has real clusters to resample. Semantic items come in true / false pairs.

    python3 tests/fixtures/v2/make_fixtures.py
"""

from __future__ import annotations

import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))

MECH = [("true_added", True), ("true_removed", True), ("near_line", True),
        ("wrong_line", False), ("wrong_file", False), ("negated", False), ("fabricated", False)]
FALSE_TWINS = ["false_misread", "false_overclaim", "false_causality", "false_outside_diff"]
CITATION_FAIL = {"wrong_line", "wrong_file", "empty_diff", "truncated_evidence"}
WORDS = "the retry loop now stops after three attempts and logs the last error before it returns".split()


def item(iid, tier, kind, label, commit, claim_len, pair=None) -> dict:
    out = {
        "id": iid, "tier": tier, "kind": kind,
        "source": {"repo": f"example/repo{commit % 3}", "commit": f"{commit:040x}"},
        "diff": "" if kind == "empty_diff" else f"--- a/f{commit}.py\n+++ b/f{commit}.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n",
        "finding": {"role": "reviewer", "claim": " ".join(WORDS[:claim_len]),
                    "evidence": {"kind": "file", "file": f"f{commit}.py", "line": 1}},
        "label": label, "label_basis": "construction" if tier != "semantic" else "double-review",
        "rationale": "synthetic v2 fixture item",
    }
    if pair is not None:
        out["pair"] = pair
    return out


def build_items(rng: random.Random) -> list[dict]:
    items, n = [], 0
    for rep in range(5):  # 5 of each mechanical kind, 3 items per commit
        for kind, label in MECH:
            items.append(item(f"mech-{n:04d}", "mechanical", kind, label, n // 3, rng.randint(6, 14)))
            n += 1
    for k in range(12):  # 12 semantic pairs, one commit per pair, lengths within 2 words
        base = rng.randint(7, 13)
        commit = 100 + k
        items.append(item(f"sem-{2 * k:04d}", "semantic", "true_behavior", True, commit, base, pair=f"p{k:02d}"))
        items.append(item(f"sem-{2 * k + 1:04d}", "semantic", FALSE_TWINS[k % 4], False, commit,
                          base + rng.choice([-2, -1, 0, 1, 2]), pair=f"p{k:02d}"))
    for k, kind in enumerate(["empty_diff", "empty_diff", "truncated_evidence", "truncated_evidence"]):
        items.append(item(f"decoy-{k:04d}", "decoy", kind, False, 200 + k, rng.randint(6, 12)))
    return items


def arm_p(arm: str, it: dict, rng: random.Random) -> float:
    y, tier, kind = it["label"], it["tier"], it["kind"]
    if arm == "accept_all":
        return 1.0
    if arm == "cite_script":
        return 0.05 if kind in CITATION_FAIL else 0.95
    citation = kind in ("near_line", "wrong_line", "wrong_file")
    if arm == "jev":
        mu, sd = ((0.66 if y else 0.38) if citation else (0.8 if y else 0.2)), 0.15
        if tier == "semantic":
            mu = 0.68 if y else 0.36
    elif arm == "haiku":
        mu, sd = (0.64 if y else 0.42), 0.2
    else:  # opus
        mu, sd = ((0.7 if y else 0.35) if citation else (0.85 if y else 0.2)), 0.15
        if tier == "semantic":
            mu, sd = (0.72 if y else 0.38), 0.2
    if tier == "decoy":
        mu = 0.12
    return round(min(max(rng.gauss(mu, sd), 0.01), 0.99), 2)


SPEC = {  # arm: (model, cost per item, latency mean, error ids, unanswered ids)
    "accept_all": (None, 0.0, 0.0, set(), set()),
    "cite_script": ("cite_script", 0.0, 0.0, set(), set()),
    "jev": ("typesafe/jev-1.13", 0.0004, 0.9, {"sem-0005"}, {"mech-0030"}),
    "haiku": ("claude-haiku-5-5", 0.0021, 1.6, {"mech-0011"}, set()),
    "opus": ("claude-opus-5-5", 0.0300, 6.5, set(), set()),
}


def main() -> None:
    items = build_items(random.Random(7))
    with open(os.path.join(HERE, "items.jsonl"), "w") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")
    for arm, (model, cost, lat, errs, skip) in SPEC.items():
        rng = random.Random(f"7-v2-{arm}")
        with open(os.path.join(HERE, "runs", f"{arm}.jsonl"), "w") as f:
            for it in items:
                if it["id"] in skip:
                    continue
                err = it["id"] in errs
                p = None if err else arm_p(arm, it, rng)
                f.write(json.dumps({
                    "item_id": it["id"], "arm": arm, "model": model, "prompt": "v2", "p": p,
                    "cost_usd": 0.0 if err else cost,
                    "latency_s": round(lat * rng.uniform(0.7, 1.4), 2) if lat else 0.0,
                    "error": "HTTP 529: overloaded" if err else None,
                    "raw": None if err else json.dumps({"p_supported": p}),
                }) + "\n")
    print(f"wrote {len(items)} items and {len(SPEC)} runs to {HERE}")


if __name__ == "__main__":
    main()
