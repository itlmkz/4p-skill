#!/usr/bin/env python3
"""Tests for the mechanical and decoy tiers of the evidence-check dataset.

    python3 tests/dataset.test.py

Reads data/mechanical.jsonl and data/decoy.jsonl as built by build_dataset.py.
Checks the schema, label balance, source spread, kind coverage, that no claim
leaks its label, the diff cap, and that `build_dataset.py --check` catches a
deliberately flipped label. No network: the build itself is not rerun here.
"""

from __future__ import annotations

import collections
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
