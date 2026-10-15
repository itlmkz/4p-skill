#!/usr/bin/env python3
"""Check the v2 semantic tier candidate file (data/v2/semantic.raw.jsonl).

Usage: python3 data/v2/semantic_check_v2.py data/v2/semantic.raw.jsonl

Checks, per PREREG-v2.md ("Data, all new", "Manipulation checks"):

Schema
- every line is one json object with exactly the v1 fields plus `pair`
- id matches sem2-NNN and is unique; pair matches pNN
- tier is "semantic", kind is one of the five semantic kinds
- label is a bool, true if and only if kind is true_behavior
- label_basis is "double-review", rationale is a non-empty string
- role is one of reviewer, tester, contraire, bigpicture
- evidence is {"kind": "file", "file": str, "line": int}
- source is {"repo": "owner/name", "commit": 40 hex chars}

Pairs
- every pair has exactly two items: one true_behavior and one false kind
- both items share file, line, role, source and diff
- the word counts of the two claims differ by at most 2
- the true item is first in between 30% and 70% of the pairs

Content
- diff is at most 12000 characters
- the cited file appears in the diff and the cited line falls inside a hunk
  of that file (old range or new range)
- claim is at most 30 words and has none of the words true, false, label,
  fabricated, wrong
- no em dash or en dash in any string value

Counts
- at least 10 pairs per false kind
- at least 25 distinct sources (repo, commit)

Shortcut tests (the v1 failure)
- AUROC of claim word count against the label is between 0.40 and 0.60
- AUROC of claim character count against the label is between 0.40 and 0.60
- for each opener (Because, Since, Every, When, If, The change) and each cue
  word (each negation word, the negation group, only, means, and the scope
  words every, all, any, always, each, whenever), the number of true claims
  and of false claims that have it differ by at most 2

Exits 0 when every check passes, 1 otherwise. Stdlib only.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict

FIELDS = {"id", "pair", "tier", "kind", "source", "diff", "finding", "label", "label_basis", "rationale"}
KINDS = {"true_behavior", "false_misread", "false_causality", "false_overclaim", "false_outside_diff"}
FALSE_KINDS = sorted(KINDS - {"true_behavior"})
ROLES = {"reviewer", "tester", "contraire", "bigpicture"}
MAX_DIFF = 12000
MAX_CLAIM_WORDS = 30
MAX_PAIR_WORD_GAP = 2
MIN_PER_FALSE_KIND = 10
MIN_SOURCES = 25
AUROC_LO, AUROC_HI = 0.40, 0.60
MAX_CUE_GAP = 2
BANNED_WORDS = re.compile(r"\b(true|false|label|fabricated|wrong)\b", re.IGNORECASE)
DASHES = ("\u2014", "\u2013")
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
ID_RE = re.compile(r"^sem2-\d{3}$")
PAIR_RE = re.compile(r"^p\d{2,}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

OPENERS = ["because", "since", "every", "when", "if", "the change"]
NEGATIONS = ["not", "no", "never", "none", "nothing", "without", "cannot", "nor", "n't"]
CUES = NEGATIONS + ["only", "means", "every", "all", "any", "always", "each", "whenever"]


def hunks_by_file(diff: str) -> dict:
    """Map each file path in the diff to its hunks as (old_start, old_len, new_start, new_len)."""
    out: dict = {}
    old_path = new_path = None
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            old_path = new_path = None
        elif line.startswith("--- "):
            p = line[4:].strip()
            old_path = p[2:] if p.startswith("a/") else None
        elif line.startswith("+++ "):
            p = line[4:].strip()
            new_path = p[2:] if p.startswith("b/") else None
            for path in {old_path, new_path} - {None}:
                out.setdefault(path, [])
        else:
            m = HUNK.match(line)
            if m:
                os_, ol, ns, nl = m.groups()
                h = (int(os_), int(ol) if ol is not None else 1, int(ns), int(nl) if nl is not None else 1)
                for path in {old_path, new_path} - {None}:
                    out.setdefault(path, []).append(h)
    return out


def line_in_hunks(line: int, hunks: list) -> bool:
    for os_, ol, ns, nl in hunks:
        if os_ <= line < os_ + ol or ns <= line < ns + nl:
            return True
    return False


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)


def words(claim: str) -> list:
    return claim.split()


def tokens(claim: str) -> list:
    """Lowercase word tokens; a contraction like doesn't also yields the token n't."""
    out = []
    for w in re.findall(r"[A-Za-z']+", claim.lower()):
        if w.endswith("n't"):
            out.append("n't")
            w = w[:-3]
        out.append(w.strip("'"))
    return out


def opener(claim: str) -> str | None:
    low = claim.strip().lower()
    for o in OPENERS:
        if re.match(r"^" + re.escape(o) + r"\b", low):
            return o
    return None


def auroc(scores_pos: list, scores_neg: list) -> float:
    """P(score of a true item > score of a false item), ties count half."""
    if not scores_pos or not scores_neg:
        return float("nan")
    wins = 0.0
    for a in scores_pos:
        for b in scores_neg:
            if a > b:
                wins += 1
            elif a == b:
                wins += 0.5
    return wins / (len(scores_pos) * len(scores_neg))


def main(path: str) -> int:
    errors: list = []
    items: list = []
    with open(path, encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            if not raw.strip():
                errors.append(f"line {n}: blank line")
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError as e:
                errors.append(f"line {n}: invalid json: {e}")
                continue
            if not isinstance(obj, dict):
                errors.append(f"line {n}: not an object")
                continue
            items.append((n, obj))

    ids = Counter()
    pairs: dict = defaultdict(list)
    sources = set()

    for n, it in items:
        tag = f"line {n} ({it.get('id', '?')})"
        keys = set(it)
        if keys != FIELDS:
            errors.append(f"{tag}: fields differ, missing {sorted(FIELDS - keys)}, extra {sorted(keys - FIELDS)}")
            continue
        ids[it["id"]] += 1
        if not isinstance(it["id"], str) or not ID_RE.match(it["id"]):
            errors.append(f"{tag}: bad id {it['id']!r}")
        if not isinstance(it["pair"], str) or not PAIR_RE.match(it["pair"]):
            errors.append(f"{tag}: bad pair {it['pair']!r}")
        if it["tier"] != "semantic":
            errors.append(f"{tag}: tier {it['tier']!r}")
        if it["kind"] not in KINDS:
            errors.append(f"{tag}: kind {it['kind']!r}")
        if not isinstance(it["label"], bool):
            errors.append(f"{tag}: label is not a bool")
        elif it["label"] != (it["kind"] == "true_behavior"):
            errors.append(f"{tag}: label {it['label']} does not match kind {it['kind']}")
        if it["label_basis"] != "double-review":
            errors.append(f"{tag}: label_basis {it['label_basis']!r}")
        if not isinstance(it["rationale"], str) or not it["rationale"].strip():
            errors.append(f"{tag}: empty rationale")

        src = it["source"]
        if (
            not isinstance(src, dict)
            or set(src) != {"repo", "commit"}
            or not isinstance(src.get("repo"), str)
            or src["repo"].count("/") != 1
            or not isinstance(src.get("commit"), str)
            or not SHA_RE.match(src["commit"])
        ):
            errors.append(f"{tag}: bad source {src!r}")
        else:
            sources.add((src["repo"], src["commit"]))

        diff = it["diff"]
        if not isinstance(diff, str) or not diff.strip():
            errors.append(f"{tag}: empty diff")
            diff = ""
        elif len(diff) > MAX_DIFF:
            errors.append(f"{tag}: diff is {len(diff)} chars, over {MAX_DIFF}")

        f = it["finding"]
        if not isinstance(f, dict) or set(f) != {"role", "claim", "evidence"}:
            errors.append(f"{tag}: bad finding keys")
            continue
        if f["role"] not in ROLES:
            errors.append(f"{tag}: role {f['role']!r}")
        claim = f["claim"]
        if not isinstance(claim, str) or not claim.strip():
            errors.append(f"{tag}: empty claim")
            continue
        if len(words(claim)) > MAX_CLAIM_WORDS:
            errors.append(f"{tag}: claim has {len(words(claim))} words, over {MAX_CLAIM_WORDS}")
        m = BANNED_WORDS.search(claim)
        if m:
            errors.append(f"{tag}: claim has banned word {m.group(0)!r}")
        ev = f["evidence"]
        if (
            not isinstance(ev, dict)
            or set(ev) != {"kind", "file", "line"}
            or ev.get("kind") != "file"
            or not isinstance(ev.get("file"), str)
            or not isinstance(ev.get("line"), int)
            or isinstance(ev.get("line"), bool)
        ):
            errors.append(f"{tag}: bad evidence {ev!r}")
            continue
        hunks = hunks_by_file(diff)
        if ev["file"] not in hunks:
            errors.append(f"{tag}: cited file {ev['file']!r} is not in the diff")
        elif not line_in_hunks(ev["line"], hunks[ev["file"]]):
            errors.append(f"{tag}: cited line {ev['line']} is outside every hunk of {ev['file']}")

        for s in strings(it):
            if any(d in s for d in DASHES):
                errors.append(f"{tag}: em or en dash in a string value")
                break

        pairs[it["pair"]].append(it)

    for i, c in ids.items():
        if c > 1:
            errors.append(f"duplicate id {i!r} ({c} times)")

    # Pair checks.
    false_kind_pairs = Counter()
    true_first = 0
    order = {it["id"]: k for k, (_, it) in enumerate(items) if isinstance(it, dict) and "id" in it}
    for pid, members in sorted(pairs.items()):
        if len(members) != 2:
            errors.append(f"pair {pid}: has {len(members)} items, needs 2")
            continue
        trues = [m for m in members if m["kind"] == "true_behavior"]
        falses = [m for m in members if m["kind"] != "true_behavior"]
        if len(trues) != 1 or len(falses) != 1:
            errors.append(f"pair {pid}: needs one true_behavior and one false item")
            continue
        t, fz = trues[0], falses[0]
        false_kind_pairs[fz["kind"]] += 1
        te, fe = t["finding"]["evidence"], fz["finding"]["evidence"]
        if (te["file"], te["line"]) != (fe["file"], fe["line"]):
            errors.append(f"pair {pid}: evidence differs, {te['file']}:{te['line']} vs {fe['file']}:{fe['line']}")
        if t["finding"]["role"] != fz["finding"]["role"]:
            errors.append(f"pair {pid}: role differs")
        if t["source"] != fz["source"]:
            errors.append(f"pair {pid}: source differs")
        if t["diff"] != fz["diff"]:
            errors.append(f"pair {pid}: diff differs")
        gap = abs(len(words(t["finding"]["claim"])) - len(words(fz["finding"]["claim"])))
        if gap > MAX_PAIR_WORD_GAP:
            errors.append(f"pair {pid}: claim word counts differ by {gap}, over {MAX_PAIR_WORD_GAP}")
        if order.get(t["id"], 0) < order.get(fz["id"], 0):
            true_first += 1

    n_pairs = sum(false_kind_pairs.values())
    if n_pairs:
        share = true_first / n_pairs
        if not 0.30 <= share <= 0.70:
            errors.append(f"true item comes first in {share:.0%} of pairs, outside 30% to 70%")

    for k in FALSE_KINDS:
        if false_kind_pairs[k] < MIN_PER_FALSE_KIND:
            errors.append(f"{k}: {false_kind_pairs[k]} pairs, needs at least {MIN_PER_FALSE_KIND}")
    if len(sources) < MIN_SOURCES:
        errors.append(f"{len(sources)} distinct sources, needs at least {MIN_SOURCES}")

    # Shortcut tests.
    claims_t = [it["finding"]["claim"] for _, it in items if it.get("label") is True and isinstance(it.get("finding"), dict)]
    claims_f = [it["finding"]["claim"] for _, it in items if it.get("label") is False and isinstance(it.get("finding"), dict)]
    au_words = auroc([len(words(c)) for c in claims_t], [len(words(c)) for c in claims_f])
    au_chars = auroc([len(c) for c in claims_t], [len(c) for c in claims_f])
    if not AUROC_LO <= au_words <= AUROC_HI:
        errors.append(f"AUROC of word count vs label is {au_words:.3f}, outside {AUROC_LO} to {AUROC_HI}")
    if not AUROC_LO <= au_chars <= AUROC_HI:
        errors.append(f"AUROC of char count vs label is {au_chars:.3f}, outside {AUROC_LO} to {AUROC_HI}")

    cue_rows = []
    for o in OPENERS:
        a = sum(1 for c in claims_t if opener(c) == o)
        b = sum(1 for c in claims_f if opener(c) == o)
        cue_rows.append((f"opener '{o}'", a, b))
    tok_t = [set(tokens(c)) for c in claims_t]
    tok_f = [set(tokens(c)) for c in claims_f]
    for w in CUES:
        a = sum(1 for s in tok_t if w in s)
        b = sum(1 for s in tok_f if w in s)
        cue_rows.append((f"word '{w}'", a, b))
    a = sum(1 for s in tok_t if s & set(NEGATIONS))
    b = sum(1 for s in tok_f if s & set(NEGATIONS))
    cue_rows.append(("negation group", a, b))
    for name, a, b in cue_rows:
        if abs(a - b) > MAX_CUE_GAP:
            errors.append(f"cue {name}: {a} true claims vs {b} false claims, gap over {MAX_CUE_GAP}")

    # Report.
    print(f"items: {len(items)}  pairs: {n_pairs}  sources: {len(sources)}  true first: {true_first}/{n_pairs}")
    print("pairs per false kind: " + ", ".join(f"{k}={false_kind_pairs[k]}" for k in FALSE_KINDS))
    wt = [len(words(c)) for c in claims_t]
    wf = [len(words(c)) for c in claims_f]
    if wt and wf:
        print(f"mean words: true {sum(wt) / len(wt):.2f}, false {sum(wf) / len(wf):.2f}")
    print(f"shortcut AUROC word count vs label: {au_words:.3f}  (pass band {AUROC_LO} to {AUROC_HI})")
    print(f"shortcut AUROC char count vs label: {au_chars:.3f}  (pass band {AUROC_LO} to {AUROC_HI})")
    print("cue counts (true claims / false claims): " + "; ".join(f"{n} {a}/{b}" for n, a, b in cue_rows if a or b))

    if errors:
        print(f"FAIL: {len(errors)} problem(s)")
        for e in errors:
            print("  - " + e)
        return 1
    print("PASS: all checks")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
