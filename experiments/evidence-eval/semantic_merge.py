#!/usr/bin/env python3
"""Double review for the semantic tier: blind the items, then keep the agreed ones.

    python3 semantic_merge.py strip            raw -> data/semantic.blind.jsonl
    python3 semantic_merge.py merge            raw + relabel -> data/semantic.jsonl

The second labeler sees only the diff and the finding. Label, kind, rationale and
role are removed. The items are shuffled with seed 7 and get opaque ids, so
neither the order nor the authoring id can leak the kind. Items written on the
same diff would otherwise sit next to each other. An item is kept only when both
labels agree. Every disagreement is written out, so a dropped item is visible,
not silent.
"""

from __future__ import annotations

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
RAW = os.path.join(DATA, "semantic.raw.jsonl")
BLIND = os.path.join(DATA, "semantic.blind.jsonl")
RELABEL = os.path.join(DATA, "semantic.relabel.jsonl")
BLIND_MAP = os.path.join(DATA, "semantic.blindmap.json")
FINAL = os.path.join(DATA, "semantic.jsonl")
DISAGREE = os.path.join(DATA, "semantic.disagreements.jsonl")


def read_jsonl(path: str) -> list[dict]:
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def strip() -> int:
    items = read_jsonl(RAW)
    order = list(items)
    random.Random(7).shuffle(order)
    blind_map = {f"blind-{n:03d}": it["id"] for n, it in enumerate(order, 1)}
    blind = [
        {
            "id": blind_id,
            "diff": it["diff"],
            "finding": {"claim": it["finding"]["claim"], "evidence": it["finding"]["evidence"]},
        }
        for blind_id, it in zip(blind_map, order)
    ]
    write_jsonl(BLIND, blind)
    with open(BLIND_MAP, "w") as fh:
        json.dump(blind_map, fh, indent=1)
    print(f"strip: {len(blind)} items -> {BLIND}")
    return 0


def merge() -> int:
    items = {it["id"]: it for it in read_jsonl(RAW)}
    with open(BLIND_MAP) as fh:
        blind_map = json.load(fh)
    second = {blind_map[row["id"]]: row for row in read_jsonl(RELABEL)}
    missing = sorted(set(items) - set(second))
    if missing:
        print(f"merge: {len(missing)} item(s) have no second label: {', '.join(missing[:10])}", file=sys.stderr)
        return 1

    kept: list[dict] = []
    disagreements: list[dict] = []
    for item_id in sorted(items):
        item, other = items[item_id], second[item_id]
        if bool(other["label"]) == bool(item["label"]):
            kept.append(item)
        else:
            disagreements.append(
                {
                    "id": item_id,
                    "kind": item["kind"],
                    "first_label": item["label"],
                    "first_rationale": item["rationale"],
                    "second_label": other["label"],
                    "second_reason": other.get("reason", ""),
                }
            )
    write_jsonl(FINAL, kept)
    write_jsonl(DISAGREE, disagreements)
    agree = len(kept) / len(items) if items else 0.0
    true_n = sum(1 for it in kept if it["label"])
    print(f"merge: kept {len(kept)} of {len(items)} ({agree:.0%} agreement), {true_n} true, {len(kept) - true_n} false")
    print(f"merge: {len(disagreements)} disagreement(s) -> {DISAGREE}")
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("strip", "merge"):
        print(__doc__)
        return 2
    return strip() if sys.argv[1] == "strip" else merge()


if __name__ == "__main__":
    sys.exit(main())
