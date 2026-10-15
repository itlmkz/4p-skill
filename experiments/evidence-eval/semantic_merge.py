#!/usr/bin/env python3
"""Double review for the semantic tier: blind the items, then keep the agreed ones.

    python3 semantic_merge.py strip [--dir data/v2]    raw -> semantic.blind.jsonl
    python3 semantic_merge.py merge [--dir data/v2]    raw + relabel -> semantic.jsonl

The second labeler sees only the diff and the finding. Label, kind, rationale and
role are removed. The items are shuffled with seed 7 and get opaque ids, so
neither the order nor the authoring id can leak the kind. Items written on the
same diff would otherwise sit next to each other. An item is kept only when both
labels agree. Every disagreement is written out, so a dropped item is visible,
not silent.

v2 items carry a `pair` id. There a pair is kept only when both of its items
agree, so a kept pair always holds one true and one false claim.
"""

from __future__ import annotations

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def paths(data: str) -> dict[str, str]:
    names = {
        "raw": "semantic.raw.jsonl",
        "blind": "semantic.blind.jsonl",
        "relabel": "semantic.relabel.jsonl",
        "blind_map": "semantic.blindmap.json",
        "final": "semantic.jsonl",
        "disagree": "semantic.disagreements.jsonl",
    }
    return {k: os.path.join(data, v) for k, v in names.items()}


def read_jsonl(path: str) -> list[dict]:
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def write_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, "w") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def strip(P: dict[str, str]) -> int:
    items = read_jsonl(P["raw"])
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
    write_jsonl(P["blind"], blind)
    with open(P["blind_map"], "w") as fh:
        json.dump(blind_map, fh, indent=1)
    print(f"strip: {len(blind)} items -> {P['blind']}")
    return 0


def merge(P: dict[str, str]) -> int:
    items = {it["id"]: it for it in read_jsonl(P["raw"])}
    with open(P["blind_map"]) as fh:
        blind_map = json.load(fh)
    second = {blind_map[row["id"]]: row for row in read_jsonl(P["relabel"])}
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
    # A pair survives only whole: drop the partner of any item that was dropped.
    dropped_pairs = {items[d["id"]].get("pair") for d in disagreements} - {None}
    if dropped_pairs:
        kept = [it for it in kept if it.get("pair") not in dropped_pairs]
        print(f"merge: dropped {len(dropped_pairs)} whole pair(s): {', '.join(sorted(dropped_pairs))}")
    write_jsonl(P["final"], kept)
    write_jsonl(P["disagree"], disagreements)
    agree = (len(items) - len(disagreements)) / len(items) if items else 0.0
    true_n = sum(1 for it in kept if it["label"])
    print(f"merge: kept {len(kept)} of {len(items)} ({agree:.0%} agreement), {true_n} true, {len(kept) - true_n} false")
    print(f"merge: {len(disagreements)} disagreement(s) -> {P['disagree']}")
    return 0


def main() -> int:
    args = sys.argv[1:]
    data = DATA
    if len(args) == 3 and args[1] == "--dir":
        data = os.path.join(HERE, args[2]) if not os.path.isabs(args[2]) else args[2]
        args = args[:1]
    if len(args) != 1 or args[0] not in ("strip", "merge"):
        print(__doc__)
        return 2
    P = paths(data)
    return strip(P) if args[0] == "strip" else merge(P)


if __name__ == "__main__":
    sys.exit(main())
