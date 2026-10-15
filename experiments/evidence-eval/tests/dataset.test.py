#!/usr/bin/env python3
"""Tests for the mechanical and decoy tiers of the evidence-check dataset.

    python3 tests/dataset.test.py

Reads data/mechanical.jsonl and data/decoy.jsonl (v1) and data/v2/*.jsonl (v2,
PREREG-v2.md) as built by build_dataset.py.
Checks the schema, label balance, source spread, kind coverage, that no claim
leaks its label, the diff cap, and that `build_dataset.py --check` catches a
deliberately flipped label. No network: the build itself is not rerun here.
"""

from __future__ import annotations

import collections
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
BUILD = os.path.join(ROOT, "build_dataset.py")
sys.path.insert(0, ROOT)
sys.dont_write_bytecode = True

import build_dataset as bd  # noqa: E402

failures = 0


def check(label: str, got, want) -> None:
    global failures
    ok = got == want
    if not ok:
        failures += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        got  {got!r}\n        want {want!r}")


def load(name: str) -> list[dict]:
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run_check(*paths: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, BUILD, "--check", *paths], capture_output=True, text=True)


MECH = load("mechanical.jsonl")
DECOY = load("decoy.jsonl")
ALL = MECH + DECOY

# --- schema ------------------------------------------------------------------

TOP = ["id", "tier", "kind", "source", "diff", "finding", "label", "label_basis", "rationale"]
schema_errors = []
for it in ALL:
    iid = it.get("id")
    if list(it) != TOP:
        schema_errors.append(f"{iid}: keys {list(it)}")
        continue
    src, fnd = it["source"], it["finding"]
    ev = fnd.get("evidence", {})
    if set(src) != {"repo", "commit"} or not re.fullmatch(r"[0-9a-f]{40}", src["commit"]):
        schema_errors.append(f"{iid}: source")
    if set(fnd) != {"role", "claim", "evidence"} or not isinstance(fnd["claim"], str):
        schema_errors.append(f"{iid}: finding")
    if fnd.get("role") not in {"reviewer", "contraire", "tester", "bigpicture"}:
        schema_errors.append(f"{iid}: role")
    if set(ev) != {"kind", "file", "line"} or ev["kind"] != "file" or not isinstance(ev["line"], int):
        schema_errors.append(f"{iid}: evidence")
    if not isinstance(it["label"], bool) or it["label_basis"] != "construction":
        schema_errors.append(f"{iid}: label or label_basis")
    if not isinstance(it["diff"], str) or not it["rationale"]:
        schema_errors.append(f"{iid}: diff or rationale")
check("every item has the PREREG schema", schema_errors, [])
check("mechanical tier field", {it["tier"] for it in MECH}, {"mechanical"})
check("decoy tier field", {it["tier"] for it in DECOY}, {"decoy"})
check("mechanical ids are mech-0001.. in order", [it["id"] for it in MECH],
      [f"mech-{n:04d}" for n in range(1, len(MECH) + 1)])
check("decoy ids are decoy-001.. in order", [it["id"] for it in DECOY],
      [f"decoy-{n:03d}" for n in range(1, len(DECOY) + 1)])
check("ids are unique", len({it["id"] for it in ALL}), len(ALL))

# --- sizes, balance, spread --------------------------------------------------

check("about 120 mechanical items", 100 <= len(MECH) <= 140, True)
check("about 12 decoy items", 10 <= len(DECOY) <= 16, True)
share = sum(it["label"] for it in MECH) / len(MECH)
print(f"      mechanical true share {share:.3f}")
check("mechanical label balance within 40% to 60% true", 0.40 <= share <= 0.60, True)
sources = {(it["source"]["repo"], it["source"]["commit"]) for it in ALL}
print(f"      {len(sources)} distinct (repo, commit) sources")
check("at least 25 distinct (repo, commit) sources", len(sources) >= 25, True)
check("sources come from 3 public repos", len({r for r, _ in sources}) >= 3, True)

mech_kinds = collections.Counter(it["kind"] for it in MECH)
decoy_kinds = collections.Counter(it["kind"] for it in DECOY)
for kind, _ in bd.MECH_KINDS:
    check(f"mechanical kind {kind} present at least 10 times ({mech_kinds[kind]})",
          mech_kinds[kind] >= 10, True)
for kind, _ in bd.DECOY_KINDS:
    check(f"decoy kind {kind} present at least 3 times ({decoy_kinds[kind]})", decoy_kinds[kind] >= 3, True)
check("no unknown kinds", set(mech_kinds) | set(decoy_kinds),
      {k for k, _ in bd.MECH_KINDS} | {k for k, _ in bd.DECOY_KINDS})
kind_label = {(it["kind"], it["label"]) for it in ALL}
want_true = {"true_added", "true_removed", "right_claim_wrong_line"}
check("label follows kind", all((k in want_true) == lab for k, lab in kind_label), True)

# --- no leaks, diff cap --------------------------------------------------------

banned = re.compile(r"\b(true|false|label|wrong|fabricated|decoy)\b", re.IGNORECASE)
leaks = [it["id"] for it in ALL if banned.search(it["finding"]["claim"])]
check("no claim contains true, false, label, wrong, fabricated, decoy", leaks, [])
check("every diff at most 12000 chars", [it["id"] for it in ALL if len(it["diff"]) > 12000], [])
check("empty_diff items have an empty diff",
      {it["diff"] for it in DECOY if it["kind"] == "empty_diff"}, {""})
check("evidence cites a file in the diff, except wrong_file and decoys",
      [it["id"] for it in MECH if it["kind"] != "wrong_file"
       and f"b/{it['finding']['evidence']['file']}" not in it["diff"]
       and f"a/{it['finding']['evidence']['file']}" not in it["diff"]], [])

# --- phrasing variety ----------------------------------------------------------

used = collections.defaultdict(set)
for it in ALL:
    claim = it["finding"]["claim"]
    for op, rx in bd.PHRASING_RES:
        for tail in bd.TAILS:
            body = claim[: len(claim) - len(tail)] if tail and claim.endswith(tail) else claim
            if rx.fullmatch(body):
                used[op].add(rx.pattern)
check("at least 6 phrasings used for added claims", len(used["+"]) >= 6, True)
check("at least 6 phrasings used for removed claims", len(used["-"]) >= 6, True)
check("every claim quotes code in backticks", all("`" in it["finding"]["claim"] for it in ALL), True)

# --- --check ----------------------------------------------------------------

res = run_check()
print("      " + res.stdout.strip().splitlines()[-1])
check("--check passes on the shipped files", res.returncode, 0)

with tempfile.TemporaryDirectory() as tmp:
    for target in ("mech-0001", "decoy-001"):
        src = MECH if target.startswith("mech") else DECOY
        path = os.path.join(tmp, f"{target}.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            for it in src:
                row = dict(it, label=not it["label"]) if it["id"] == target else it
                f.write(json.dumps(row) + "\n")
        res = run_check(path)
        check(f"--check exits non-zero on a flipped label ({target})", res.returncode != 0, True)
        check(f"--check names the flipped item ({target})", f"FAIL  {target}:" in res.stdout, True)

    # A flipped kind with an unchanged label must be caught by the shape checks.
    it = next(i for i in MECH if i["kind"] == "fabricated")
    path = os.path.join(tmp, "kind.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(dict(it, kind="wrong_line")) + "\n")
    check("--check catches a mislabeled kind", run_check(path).returncode != 0, True)

# --- v1 is frozen --------------------------------------------------------------

V1_SHA1 = {
    "mechanical.jsonl": "e9253b78b4bb06cf2adb31a359d0f49e92537c8c",
    "decoy.jsonl": "77089d4782c16a9e04d57b28f307e20f90e48caa",
}
for name, want in V1_SHA1.items():
    with open(os.path.join(DATA, name), "rb") as f:
        check(f"v1 {name} is byte-identical to the merged run", hashlib.sha1(f.read()).hexdigest(), want)

# --- v2 (PREREG-v2.md) -----------------------------------------------------------

DATA_V2 = os.path.join(DATA, "v2")


def load_v2(name: str) -> list[dict]:
    with open(os.path.join(DATA_V2, name), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


MECH2 = load_v2("mechanical.jsonl")
DECOY2 = load_v2("decoy.jsonl")
ALL2 = MECH2 + DECOY2

check("v2 every item has the PREREG schema",
      [it["id"] for it in ALL2 if list(it) != TOP or set(it["finding"]["evidence"]) != {"kind", "file", "line"}], [])
check("v2 mechanical ids are mech2-0001.. in order", [it["id"] for it in MECH2],
      [f"mech2-{n:04d}" for n in range(1, len(MECH2) + 1)])
check("v2 decoy ids are decoy2-001.. in order", [it["id"] for it in DECOY2],
      [f"decoy2-{n:03d}" for n in range(1, len(DECOY2) + 1)])
check("v2 about 120 mechanical items", 100 <= len(MECH2) <= 140, True)
check("v2 about 12 decoy items", 10 <= len(DECOY2) <= 16, True)
share2 = sum(it["label"] for it in MECH2) / len(MECH2)
print(f"      v2 mechanical true share {share2:.3f}")
check("v2 mechanical label balance within 40% to 60% true", 0.40 <= share2 <= 0.60, True)

sources2 = {(it["source"]["repo"], it["source"]["commit"]) for it in ALL2}
print(f"      v2: {len(sources2)} distinct (repo, commit) sources")
check("v2 at least 25 distinct (repo, commit) sources", len(sources2) >= 25, True)
check("v2 uses only its two new repos", {r for r, _ in sources2}, {"encode/starlette", "sindresorhus/execa"})
check("v2 reuses no v1 commit", sources2 & sources, set())

kinds2 = collections.Counter(it["kind"] for it in MECH2)
for kind, _ in bd.MECH_KINDS_V2:
    check(f"v2 mechanical kind {kind} present at least 12 times ({kinds2[kind]})", kinds2[kind] >= 12, True)
dkinds2 = collections.Counter(it["kind"] for it in DECOY2)
check("v2 decoy kinds are empty_diff and truncated_evidence, 6 each", dict(dkinds2),
      {"empty_diff": 6, "truncated_evidence": 6})
check("v2 label follows kind",
      [it["id"] for it in ALL2 if it["label"] != (it["kind"] in bd.TRUE_KINDS_V2)], [])
check("v2 no claim contains true, false, label, wrong, fabricated, decoy",
      [it["id"] for it in ALL2 if banned.search(it["finding"]["claim"])], [])
check("v2 every diff at most 12000 chars", [it["id"] for it in ALL2 if len(it["diff"]) > 12000], [])


def offset_of(it: dict) -> int | None:
    """Distance from the cited line to the line that supports the claim, in the cited file."""
    op, snip, _func, _file = bd.parse_claim(it["finding"]["claim"])
    ev = it["finding"]["evidence"]
    hits = [ln for ln in bd.all_lines(bd.parse_diff(it["diff"]))
            if ln.op == op and snip in ln.text and ln.file == ev["file"]]
    return abs(hits[0].no - ev["line"]) if len(hits) == 1 else None


near = [offset_of(it) for it in MECH2 if it["kind"] == "near_line"]
far = [offset_of(it) for it in MECH2 if it["kind"] == "wrong_line"]
print(f"      v2 near_line offsets {sorted(near)}")
print(f"      v2 wrong_line offsets {sorted(far)}")
check("v2 near_line cited 1 to 5 lines off", all(o is not None and 1 <= o <= 5 for o in near), True)
check("v2 near_line offsets cover 1..5", set(near), {1, 2, 3, 4, 5})
check("v2 wrong_line cited 6 to 15 lines off", all(o is not None and 6 <= o <= 15 for o in far), True)
check("v2 wrong_line has at least 4 items at offset >= 10", sum(o >= 10 for o in far) >= 4, True)
check("v2 wrong_line offsets spread over at least 8 values", len(set(far)) >= 8, True)

wf = [it for it in MECH2 if it["kind"] == "wrong_file"]
lens = [bd.LENGTH_RE.search(it["rationale"]) for it in wf]
check("v2 wrong_file records the cited file's length", all(lens), True)
check("v2 wrong_file cited line <= cited file length",
      [it["id"] for it, m in zip(wf, lens) if m and not 1 <= it["finding"]["evidence"]["line"] <= int(m.group(1))], [])
inside = sum(f"b/{it['finding']['evidence']['file']}" in it["diff"] or f"a/{it['finding']['evidence']['file']}" in it["diff"]
             for it in wf)
print(f"      v2 wrong_file citing a file in the diff: {inside} of {len(wf)}")
check("v2 wrong_file about half cite a file in the diff", 0.35 <= inside / len(wf) <= 0.65, True)


def ends_mid_hunk(diff: str) -> bool:
    hunks = bd.parse_diff(diff)
    if not hunks:
        return False
    m = bd.HUNK_RE.match(diff[hunks[-1].offset:].splitlines()[0])
    old_n = int(m.group(2)) if m.group(2) is not None else 1
    new_n = int(m.group(4)) if m.group(4) is not None else 1
    body = hunks[-1].lines
    return sum(ln.op != "+" for ln in body) < old_n or sum(ln.op != "-" for ln in body) < new_n


cuts = [it for it in DECOY2 if it["kind"] == "truncated_evidence"]
mid = sum(ends_mid_hunk(it["diff"]) for it in cuts)
print(f"      v2 truncated_evidence cut mid-hunk: {mid} of {len(cuts)}")
check("v2 truncated_evidence cuts mid-hunk about half the time", 2 <= mid <= len(cuts) - 2, True)
check("v2 truncated_evidence diffs are not empty", all(it["diff"] for it in cuts), True)

res = run_check(os.path.join(DATA_V2, "mechanical.jsonl"), os.path.join(DATA_V2, "decoy.jsonl"))
print("      " + res.stdout.strip().splitlines()[-1])
check("v2 --check passes on the v2 files", res.returncode, 0)
with tempfile.TemporaryDirectory() as tmp:
    for kind in ("near_line", "wrong_line", "wrong_file"):
        it = next(i for i in MECH2 if i["kind"] == kind)
        path = os.path.join(tmp, f"{kind}.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(dict(it, label=not it["label"])) + "\n")
        res = run_check(path)
        check(f"v2 --check catches a flipped {kind} label", f"FAIL  {it['id']}:" in res.stdout, True)
    # wrong_line pushed to 16 lines off breaks the v2 bound; near_line pushed to 6 breaks its kind.
    for kind, dist in (("wrong_line", 16), ("near_line", 6)):
        it = json.loads(json.dumps(next(i for i in MECH2 if i["kind"] == kind)))
        op, snip, _f, _c = bd.parse_claim(it["finding"]["claim"])
        hit = next(ln for ln in bd.all_lines(bd.parse_diff(it["diff"]))
                   if ln.op == op and snip in ln.text and ln.file == it["finding"]["evidence"]["file"])
        it["finding"]["evidence"]["line"] = hit.no + dist
        path = os.path.join(tmp, f"{kind}-moved.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps(it) + "\n")
        check(f"v2 --check catches {kind} moved {dist} lines off", run_check(path).returncode != 0, True)


# --- derive() on hand-made items ---------------------------------------------

DIFF = (
    "diff --git a/m.py b/m.py\n--- a/m.py\n+++ b/m.py\n@@ -10,3 +10,3 @@ def f():\n"
    "     a = 1\n-    b = old_call(a)\n+    b = new_call(a)\n     return b\n"
)


def toy(claim: str, line: int, file: str = "m.py") -> bool | None:
    it = {"kind": "true_added", "diff": DIFF,
          "finding": {"claim": claim, "evidence": {"kind": "file", "file": file, "line": line}}}
    return bd.derive(it)[0]


check("derive: added line at the cited line", toy("The change adds `b = new_call(a)`.", 11), True)
check("derive: removed line at its old line", toy("The change removes `b = old_call(a)`.", 11), True)
check("derive: within 5 lines is accepted", toy("The change adds `b = new_call(a)`.", 16), True)
check("derive: 6 lines off is rejected", toy("The change adds `b = new_call(a)`.", 17), False)
check("derive: other file is rejected", toy("The change adds `b = new_call(a)`.", 11, "n.py"), False)
check("derive: negated is rejected", toy("The change removes `b = new_call(a)`.", 11), False)
check("derive: absent snippet is rejected", toy("The change adds `b = other(a)`.", 11), False)
check("derive: unparseable claim gives None", toy("Something changed here.", 11), None)

print(f"\n{'all passed' if not failures else f'{failures} failed'}")
sys.exit(1 if failures else 0)
