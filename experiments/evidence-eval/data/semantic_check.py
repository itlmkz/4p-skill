#!/usr/bin/env python3
"""Schema check for the semantic tier candidate file (semantic.raw.jsonl).

Usage: python3 semantic_check.py data/semantic.raw.jsonl

Checks, per PREREG.md:
- every line is one json object with exactly the PREREG fields
- tier is "semantic", kind is one of the five semantic kinds
- label is true if and only if kind is true_behavior
- label_basis is "double-review"
- role is one of reviewer, tester, contraire, bigpicture
- evidence is {"kind": "file", "file": str, "line": int}
- the cited file appears in the item's diff, and the cited line falls inside a
  hunk of that file (old range or new range)
- diff is at most 12000 characters
- claim is at most 30 words and has none of the words true, false, label, fabricated
- no em dash or en dash in any string value
- ids are unique
- counts: 35 to 45 true items, at least 8 items per false kind, at least 20
  distinct sources (repo, commit)

Exits 0 when every check passes, 1 otherwise. Stdlib only.
"""
import json
import re
import sys
from collections import Counter

FIELDS = {"id", "tier", "kind", "source", "diff", "finding", "label", "label_basis", "rationale"}
KINDS = {"true_behavior", "false_misread", "false_causality", "false_overclaim", "false_outside_diff"}
FALSE_KINDS = KINDS - {"true_behavior"}
ROLES = {"reviewer", "tester", "contraire", "bigpicture"}
MAX_DIFF = 12000
MAX_CLAIM_WORDS = 30
BANNED_WORDS = re.compile(r"\b(true|false|label|fabricated)\b", re.IGNORECASE)
DASHES = ("\u2014", "\u2013")
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def hunks_by_file(diff: str) -> dict:
    """Map each file path in the diff to its hunks as (old_start, old_len, new_start, new_len)."""
    out: dict[str, list] = {}
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


def check_item(item, errors: list, where: str) -> None:
    def err(msg):
        errors.append(f"{where}: {msg}")

    if not isinstance(item, dict):
        err("not a json object")
        return
    keys = set(item)
    if keys != FIELDS:
        missing, extra = FIELDS - keys, keys - FIELDS
        if missing:
            err(f"missing fields {sorted(missing)}")
        if extra:
            err(f"unexpected fields {sorted(extra)}")
    if item.get("tier") != "semantic":
        err(f"tier is {item.get('tier')!r}, want 'semantic'")
    kind = item.get("kind")
    if kind not in KINDS:
        err(f"kind {kind!r} not in {sorted(KINDS)}")
    label = item.get("label")
    if not isinstance(label, bool):
        err("label is not a bool")
    elif label != (kind == "true_behavior"):
        err(f"label {label} does not match kind {kind!r}")
    if item.get("label_basis") != "double-review":
        err(f"label_basis is {item.get('label_basis')!r}, want 'double-review'")
    src = item.get("source")
    if not (isinstance(src, dict) and isinstance(src.get("repo"), str) and "/" in src["repo"]
            and isinstance(src.get("commit"), str) and re.fullmatch(r"[0-9a-f]{7,40}", src["commit"])):
        err("source must be {'repo': 'owner/name', 'commit': '<sha>'}")
    rationale = item.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        err("rationale is empty")

    diff = item.get("diff")
    if not isinstance(diff, str) or not diff.strip():
        err("diff is empty")
        diff = ""
    elif len(diff) > MAX_DIFF:
        err(f"diff has {len(diff)} chars, max {MAX_DIFF}")

    finding = item.get("finding")
    if not isinstance(finding, dict):
        err("finding is not an object")
        return
    if set(finding) != {"role", "claim", "evidence"}:
        err(f"finding fields are {sorted(finding)}, want role, claim, evidence")
    if finding.get("role") not in ROLES:
        err(f"role {finding.get('role')!r} not in {sorted(ROLES)}")
    claim = finding.get("claim")
    if not isinstance(claim, str) or not claim.strip():
        err("claim is empty")
    else:
        n = len(claim.split())
        if n > MAX_CLAIM_WORDS:
            err(f"claim has {n} words, max {MAX_CLAIM_WORDS}")
        m = BANNED_WORDS.search(claim)
        if m:
            err(f"claim contains the banned word {m.group(0)!r}")
    ev = finding.get("evidence")
    if not (isinstance(ev, dict) and set(ev) == {"kind", "file", "line"} and ev.get("kind") == "file"
            and isinstance(ev.get("file"), str) and isinstance(ev.get("line"), int)
            and not isinstance(ev.get("line"), bool)):
        err("evidence must be {'kind': 'file', 'file': str, 'line': int}")
    elif diff:
        hunks = hunks_by_file(diff)
        if ev["file"] not in hunks:
            err(f"cited file {ev['file']!r} is not in the diff")
        elif not line_in_hunks(ev["line"], hunks[ev["file"]]):
            err(f"cited line {ev['file']}:{ev['line']} is outside every hunk of that file")

    for s in strings(item):
        if any(d in s for d in DASHES):
            err("contains an em dash or en dash")
            break


def main(argv: list) -> int:
    if len(argv) != 2:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    errors: list[str] = []
    items = []
    with open(argv[1], encoding="utf-8") as fh:
        for n, raw in enumerate(fh, 1):
            if not raw.strip():
                errors.append(f"line {n}: blank line")
                continue
            try:
                item = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(f"line {n}: invalid json ({exc})")
                continue
            where = f"line {n} ({item.get('id', '?') if isinstance(item, dict) else '?'})"
            check_item(item, errors, where)
            items.append(item)

    ids = Counter(i.get("id") for i in items if isinstance(i, dict))
    for i, c in ids.items():
        if c > 1:
            errors.append(f"id {i!r} appears {c} times")
    kinds = Counter(i.get("kind") for i in items if isinstance(i, dict))
    n_true = kinds.get("true_behavior", 0)
    if not 35 <= n_true <= 45:
        errors.append(f"{n_true} true items, want 35 to 45")
    for k in sorted(FALSE_KINDS):
        if kinds.get(k, 0) < 8:
            errors.append(f"{kinds.get(k, 0)} items of kind {k}, want at least 8")
    sources = {(i["source"].get("repo"), i["source"].get("commit")) for i in items
               if isinstance(i, dict) and isinstance(i.get("source"), dict)}
    if len(sources) < 20:
        errors.append(f"{len(sources)} distinct sources, want at least 20")

    roles = Counter(i["finding"].get("role") for i in items
                    if isinstance(i, dict) and isinstance(i.get("finding"), dict))
    print(f"items: {len(items)}")
    print("kinds: " + ", ".join(f"{k}={kinds.get(k, 0)}" for k in sorted(KINDS)))
    print(f"labels: true={n_true} false={len(items) - n_true}")
    print("roles: " + ", ".join(f"{r}={roles.get(r, 0)}" for r in sorted(ROLES)))
    print(f"distinct sources: {len(sources)} across repos {sorted({r for r, _ in sources})}")
    if errors:
        print(f"FAIL: {len(errors)} problem(s)")
        for e in errors:
            print("  " + e)
        return 1
    print("OK: all checks pass")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
