#!/usr/bin/env python3
"""Build the mechanical and decoy tiers of the evidence-check dataset.

Every label is set by construction and proven by `--check`, which re-derives it
from the item's own diff text. See PREREG.md for the item schema and kinds.

    python3 build_dataset.py --cache-dir DIR      # build data/mechanical.jsonl, data/decoy.jsonl
    python3 build_dataset.py --check              # re-derive every label, exit 1 on a mismatch
    python3 build_dataset.py --check FILE ...     # same, on other jsonl files

Sources are pinned public commits (SOURCES below). itlmkz/4p-skill is read from
the local checkout when it has the commit; the other repos are cloned with
`git clone --filter=blob:none --no-checkout` into --cache-dir when missing.
Cloned repos are data: nothing from them is run, imported or built; only git
output is read. Deterministic: seed 7, sorted inputs, fixed git options, so two
runs give byte-identical files.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SEED = 7
MAX_DIFF_CHARS = 12000
NEAR = 5  # a citation within this many lines of the evidence is accepted

# --- sizes. Mechanical is half true: 60 true, 60 false. --------------------

MECH_KINDS = [
    ("true_added", 30),
    ("true_removed", 30),
    ("wrong_line", 15),
    ("wrong_file", 15),
    ("negated", 15),
    ("fabricated", 15),
]
DECOY_KINDS = [("empty_diff", 4), ("truncated_evidence", 4), ("right_claim_wrong_line", 4)]
TRUE_KINDS = {"true_added", "true_removed", "right_claim_wrong_line"}

# --- pinned public sources. Order inside a repo is irrelevant; it is sorted. -

SOURCES: dict[str, dict] = {
    "itlmkz/4p-skill": {
        "url": "https://github.com/itlmkz/4p-skill.git",
        "local": True,
        "commits": [
            "0408fe4a77b926114d65264761d3cc2c88099b18",
            "24e81ca731e2ce9e666090d6bf3aa1b229c19a3e",
            "a128b8991131b27700339f466b1ea82c4a01d878",
            "a4ba3ce65d5e39b9fca3912a68f9cb8ca657e473",
            "b78340b1d7811a8a0d010e7d91616038ebf373e8",
            "b8d62b5a00fdd3764e9a9027e304293c9e15cff8",
            "e7705c4f81c170ba5ec7cd7e477c32eb610bb9dc",
        ],
    },
    "pallets/click": {
        "url": "https://github.com/pallets/click.git",
        "commits": [
            "051725fa7e0c69effc9107066d8791c5b99242c3",
            "051bb0f30b545cf7426deef819811815297c2798",
            "0585f456baa6eeb2edbaab7c85fa796a004aef86",
            "05f6fd0df4ecbd104eb7a229f9f185c2484dee69",
            "07c909f23f0f83b5ca137c167b9a134d66201f67",
            "22177f857a34e3c35ba957553853a37f23feb37e",
            "405a5481e4dbd5022799993d787bd8446137d9a3",
            "9207bdc073181b0699938a7d7b4d0b7dde23fe4f",
            "9835b0f7612d1b1ea180a975fd6d24cf16791ba8",
            "b7e5fd4cc7de70280eccd39f2bb956df617e5519",
            "f67c2bb6c2f055c1c7a57cd46c3697fc26a7742e",
        ],
    },
    "sindresorhus/ky": {
        "url": "https://github.com/sindresorhus/ky.git",
        "commits": [
            "0a9cbb1a3f09f67f69cc4b45057fb38988881f49",
            "16b5936d6a275ce380c710e52e56c60f88850a3a",
            "33462fcbf8f9001fc3d7a08576992098e571c5ff",
            "4cc6698cf35873f288177f4073cbc0bdbbf83374",
            "619c42765fa22b02966f39443fbc28167b707caa",
            "6e275943bf7635e49f28d3b96e804ccd2c58f156",
            "74224d8b277147371ed6a6321e21c775dd941c71",
            "d4ce7b12c5864a4af1427c573ce31a3c3d9a809b",
            "f3b1f7d9c688ca5d450475c8f57b1e92543cf7b6",
            "fa0eac4cee101ed15649f09c4cd7a58aedb0be6d",
        ],
    },
}
CODE_EXTS = (".py", ".ts", ".tsx", ".js", ".mjs", ".cjs")

# --- words a claim must never contain: they would leak the label or kind. --

BANNED = ("true", "false", "label", "wrong", "fabricated", "decoy")
BANNED_RE = re.compile(r"\b(" + "|".join(BANNED) + r")\b", re.IGNORECASE)

# --- claim phrasings. {where} is "", " in `func`", " in path" or both. ------
# Every phrasing keeps the snippet in backticks, so --check can parse it back.

PHRASINGS: dict[str, list[str]] = {
    "+": [
        "The change adds `{snip}`{where}.",
        "New line{where}: `{snip}`.",
        "This patch introduces `{snip}`{where}, which was not there before.",
        "`{snip}` is new code{where}.",
        "The diff inserts `{snip}`{where} as part of this commit.",
        "Looking at the patch, `{snip}` now appears{where} as an added line.",
        "The author added `{snip}`{where}.",
        "A fresh `{snip}` shows up{where} after this change.",
    ],
    "-": [
        "The change removes `{snip}`{where}.",
        "Deleted line{where}: `{snip}`.",
        "This patch drops `{snip}`{where}, so that line is gone after the commit.",
        "`{snip}` is deleted{where}.",
        "The diff takes out `{snip}`{where}.",
        "Looking at the patch, `{snip}` disappears{where} as a removed line.",
        "The author deleted `{snip}`{where}.",
        "After this commit the line `{snip}` has been removed{where}.",
    ],
}
TAILS = [
    "",
    " Worth a second look.",
    " Flagging it so the next seat can verify.",
    " Raising it before merge.",
    " Noting it for the coordinator.",
]
ROLES = ["bigpicture", "contraire", "reviewer", "tester"]
WHERE_RE = r"(?P<where>(?: in `(?P<func>[^`]+)`)?(?: in (?P<file>[^\s`]+?))?)"


def _phrasing_regex(text: str) -> re.Pattern:
    parts = re.split(r"(\{snip\}|\{where\})", text)
    out = []
    for p in parts:
        if p == "{snip}":
            out.append(r"(?P<snip>[^`]+)")
        elif p == "{where}":
            out.append(WHERE_RE)
        else:
            out.append(re.escape(p))
    return re.compile("".join(out))


PHRASING_RES = [(op, _phrasing_regex(t)) for op in ("+", "-") for t in PHRASINGS[op]]

# --- git, with user config switched off so output is the same everywhere. --

GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0"}
DIFF_OPTS = [
    "--format=",
    "--no-color",
    "--no-ext-diff",
    "--no-textconv",
    "--no-renames",
    "--diff-algorithm=myers",
    "-U3",
    "--src-prefix=a/",
    "--dst-prefix=b/",
]


def git(repo: str, *args: str) -> str:
    env = dict(os.environ, **GIT_ENV)
    cmd = ["git", "-c", "core.quotepath=false", "-c", "core.fsmonitor=false", "-C", repo, *args]
    res = subprocess.run(cmd, capture_output=True, env=env, check=True)
    return res.stdout.decode("utf-8", errors="replace")


def has_commit(repo: str, sha: str) -> bool:
    env = dict(os.environ, **GIT_ENV)
    res = subprocess.run(
        ["git", "-C", repo, "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True, env=env
    )
    return res.returncode == 0


def repo_dir(name: str, spec: dict, cache_dir: str) -> str:
    """Local checkout for 4p-skill when it has every commit, else a clone in the cache."""
    if spec.get("local"):
        try:
            top = git(HERE, "rev-parse", "--show-toplevel").strip()
            if all(has_commit(top, c) for c in spec["commits"]):
                return top
        except subprocess.CalledProcessError:
            pass
    dest = os.path.join(cache_dir, name.replace("/", "__"))
    if not os.path.isdir(dest):
        os.makedirs(cache_dir, exist_ok=True)
        env = dict(os.environ, **GIT_ENV)
        subprocess.run(
            ["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", spec["url"], dest],
            env=env,
            check=True,
        )
    missing = [c for c in spec["commits"] if not has_commit(dest, c)]
    if missing:
        sys.exit(f"{name}: commits missing from {dest}: {', '.join(missing)}")
    return dest


# --- diff parsing ----------------------------------------------------------

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


@dataclass
class Line:
    file: str
    op: str  # "+", "-" or " "
    old: int | None
    new: int | None
    text: str
    hunk: int  # global hunk index in the diff
    offset: int  # char offset of the hunk header in the diff text

    @property
    def no(self) -> int:
        """The line number a citation uses: new file for added, old file for removed."""
        return self.old if self.op == "-" else self.new  # type: ignore[return-value]


@dataclass
class Hunk:
    file: str
    header: str
    offset: int  # char offset of the "@@" line
    file_offset: int  # char offset of the file's "diff --git" line
    first_in_file: bool
    lines: list[Line] = field(default_factory=list)


def parse_diff(diff: str) -> list[Hunk]:
    hunks: list[Hunk] = []
    path = ""
    file_offset = 0
    first = True
    old_rem = new_rem = 0
    old_no = new_no = 0
    pos = 0
    for raw in diff.splitlines(keepends=True):
        line = raw.rstrip("\n")
        start = pos
        pos += len(raw)
        if old_rem > 0 or new_rem > 0:
            op = line[:1] if line[:1] in "+- " else " "
            if line.startswith("\\"):
                continue
            text = line[1:]
            h = hunks[-1]
            if op == "+":
                h.lines.append(Line(path, "+", None, new_no, text, len(hunks) - 1, h.offset))
                new_no += 1
                new_rem -= 1
            elif op == "-":
                h.lines.append(Line(path, "-", old_no, None, text, len(hunks) - 1, h.offset))
                old_no += 1
                old_rem -= 1
            else:
                h.lines.append(Line(path, " ", old_no, new_no, text, len(hunks) - 1, h.offset))
                old_no += 1
                new_no += 1
                old_rem -= 1
                new_rem -= 1
            continue
        if line.startswith("diff --git "):
            path = line.rsplit(" b/", 1)[-1]
            file_offset = start
            first = True
        elif line.startswith("--- ") and line[4:] != "/dev/null":
            path = line[6:] if line.startswith("--- a/") else line[4:]
        elif line.startswith("+++ ") and line[4:] != "/dev/null":
            path = line[6:] if line.startswith("+++ b/") else line[4:]
        else:
            m = HUNK_RE.match(line)
            if m:
                old_no, new_no = int(m.group(1)), int(m.group(3))
                old_rem = int(m.group(2)) if m.group(2) is not None else 1
                new_rem = int(m.group(4)) if m.group(4) is not None else 1
                hunks.append(Hunk(path, m.group(5).strip(), start, file_offset, first))
                first = False
    return hunks


def all_lines(hunks: list[Hunk]) -> list[Line]:
    return [ln for h in hunks for ln in h.lines]


# --- scope: the function or class a changed line sits in -------------------

SCOPE_RES = [
    re.compile(r"^(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\("),
    re.compile(r"^class\s+([A-Za-z_]\w*)\b"),
    re.compile(r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)\s*[(<]"),
    re.compile(r"^(?:export\s+)?(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"),
]


def indent(text: str) -> int:
    return len(text) - len(text.lstrip(" \t"))


def scope_name(text: str) -> str | None:
    s = text.strip()
    for rx in SCOPE_RES:
        m = rx.match(s)
        if m:
            return m.group(1)
    return None


def scope_of(source: list[str], lineno: int) -> str | None:
    """Nearest enclosing def/class/function of a 1-based line in the full file text."""
    if not 1 <= lineno <= len(source):
        return None
    cur = indent(source[lineno - 1])
    if cur == 0 or not source[lineno - 1].strip():
        return None
    for text in reversed(source[: lineno - 1]):
        if not text.strip():
            continue
        lvl = indent(text)
        if lvl < cur:
            if text.strip()[:1] in ")]}":  # tail of a multi-line signature or call
                continue
            name = scope_name(text)
            if name:
                return name
            if lvl == 0:
                return None
            cur = lvl
    return None


# --- candidate snippets ----------------------------------------------------

COMMENT_STARTS = ("#", "//", "/*", "*", '"""', "'''", "..", ":", ">>>")


STRING_START = re.compile(r"""^[rbfuRBFU]{0,2}["'`]""")
CODE_SIGNAL = re.compile(
    r"[(\[{]|\s=\s|==|!=|=>|->|\w\.\w+\s*[:=]|^(?:if|elif|for|while|return|def|class|const|let|await"
    r"|import|from|assert|yield|raise|throw)\b"
)
PROSE_SKIP = {
    "if", "elif", "else", "for", "while", "in", "is", "not", "and", "or", "return", "def", "class",
    "const", "let", "await", "async", "import", "from", "assert", "yield", "raise", "throw", "None",
    "null", "new", "of", "as", "with", "lambda", "typeof", "instanceof", "self", "this",
}


def looks_like_prose(snip: str) -> bool:
    """Lines inside prompt strings and docstrings read as words, not code."""
    words = [w for w in snip.split() if re.fullmatch(r"[A-Za-z]+[,.:;]?", w)]
    return sum(1 for w in words if w.rstrip(",.:;") not in PROSE_SKIP) >= 4


def usable_snippet(snip: str, diff: str) -> bool:
    if not 12 <= len(snip) <= 80 or "`" in snip or not snip.isascii():
        return False
    if snip.startswith(COMMENT_STARTS) or STRING_START.match(snip) or snip.endswith("\\"):
        return False
    if any(w in snip.lower() for w in BANNED):
        return False
    if not re.search(r"[A-Za-z_]{3,}", snip) or not CODE_SIGNAL.search(snip) or looks_like_prose(snip):
        return False
    return diff.count(snip) == 1  # unique in the whole diff text, headers included


@dataclass
class Unit:
    """One diff: a commit restricted to its code files."""

    repo: str
    commit: str
    diff: str
    hunks: list[Hunk]
    tree: list[str]  # code files in the repo at that commit, for wrong_file
    cands: dict[str, list[Line]]  # op -> usable changed lines
    sources: dict[tuple[str, str], list[str]]  # (op, file) -> full file text on that side

    @property
    def files(self) -> list[str]:
        return sorted({h.file for h in self.hunks})


def load_unit(repo: str, path: str, sha: str) -> Unit:
    names = git(path, "diff-tree", "--no-commit-id", "--name-only", "-r", "--no-renames", sha)
    code = sorted(n for n in names.splitlines() if n.endswith(CODE_EXTS))
    # Keep whole files, in path order, while the diff fits the cap.
    diff = ""
    for name in code:
        part = git(path, "show", *DIFF_OPTS, sha, "--", name)
        if len(diff) + len(part) <= MAX_DIFF_CHARS:
            diff += part
    hunks = parse_diff(diff)
    tree = sorted(
        n for n in git(path, "ls-tree", "-r", "--name-only", sha).splitlines() if n.endswith(CODE_EXTS)
    )
    cands: dict[str, list[Line]] = {"+": [], "-": []}
    for ln in all_lines(hunks):
        if ln.op in cands and usable_snippet(ln.text.strip(), diff):
            if not any(w in ln.file.lower() for w in BANNED):
                cands[ln.op].append(ln)
    # Full file text on each side, so a claim names the real enclosing function.
    sources: dict[tuple[str, str], list[str]] = {}
    for op, lines in sorted(cands.items()):
        for file in sorted({ln.file for ln in lines}):
            rev = f"{sha}:{file}" if op == "+" else f"{sha}^:{file}"
            sources[(op, file)] = git(path, "show", rev).splitlines()
        for ln in lines:  # the hunk arithmetic must land on the same text
            if sources[(op, ln.file)][ln.no - 1] != ln.text:
                sys.exit(f"{repo}@{sha[:8]} {ln.file}:{ln.no}: line number does not match the file")
    return Unit(repo, sha, diff, hunks, tree, cands, sources)


# --- claims ----------------------------------------------------------------


def make_claim(rng: random.Random, op: str, snip: str, func: str | None, file: str | None) -> str:
    where = ""
    if func:
        where += f" in `{func}`"
    if file:
        where += f" in {file}"
    text = rng.choice(PHRASINGS[op]).format(snip=snip, where=where)
    return text + rng.choice(TAILS)


def parse_claim(claim: str) -> tuple[str, str, str | None, str | None] | None:
    """(op, snippet, func, file) for a claim written by make_claim, else None."""
    matches = set()
    for tail in TAILS:
        if tail and not claim.endswith(tail):
            continue
        body = claim[: len(claim) - len(tail)] if tail else claim
        for op, rx in PHRASING_RES:
            m = rx.fullmatch(body)
            if m:
                matches.add((op, m.group("snip"), m.group("func"), m.group("file")))
    return matches.pop() if len(matches) == 1 else None


# --- fabricated snippets: plausible edits that appear nowhere in the diff --

COMMON_SWAPS = [(" < ", " <= "), (" > ", " >= "), (" <= ", " < "), (" >= ", " > ")]
SWAPS = {
    "py": COMMON_SWAPS + [
        (" == ", " != "),
        (" != ", " == "),
        (" is None", " is not None"),
        (" is not None", " is None"),
        (" and ", " or "),
        (" or ", " and "),
        ("if not ", "if "),
        ("if ", "if not "),
    ],
    "ts": COMMON_SWAPS + [
        (" === ", " !== "),
        (" !== ", " === "),
        (" && ", " || "),
        (" || ", " && "),
        ("if (!", "if ("),
        ("if (", "if (!"),
        ("await ", ""),
        ("const ", "let "),
    ],
}
KEYWORDS = {
    "self", "None", "def", "return", "await", "async", "const", "let", "this", "import", "from",
    "class", "with", "else", "elif", "while", "for", "not", "and", "lambda", "function", "typeof",
    "new", "throw", "raise", "yield", "pass", "void", "null", "undefined", "export", "default",
    "assert", "instanceof", "test", "expect", "True", "False", "print",
}


NAME_KINDS = {
    "attr": re.compile(r"(?<=\.)([A-Za-z_]\w{2,})\b"),
    "call": re.compile(r"(?<![.\w])([A-Za-z_]\w{2,})(?=\()"),
    "name": re.compile(r"(?<![.\w])([A-Za-z]+(?:_[A-Za-z0-9]+)+|[a-z]+(?:[A-Z][a-z0-9]+)+)\b(?!\()"),
}


def plain_name(tok: str) -> bool:
    return (
        tok not in KEYWORDS
        and re.search(r"[A-Za-z]{3}", tok) is not None
        and not any(w in tok.lower() for w in BANNED)
    )


def name_style(tok: str) -> str:
    """UPPER_CASE, Capitalized, snake_case, camelCase or lower: a rename keeps the style."""
    if tok.upper() == tok:
        return "upper"
    if tok[0].isupper():
        return "capital"
    if "_" in tok.strip("_"):
        return "snake"
    return "camel" if any(c.isupper() for c in tok) else "lower"


def in_string(text: str, pos: int) -> bool:
    head = text[:pos]
    return head.count('"') % 2 == 1 or head.count("'") % 2 == 1


def lang_of(path: str) -> str:
    return "py" if path.endswith(".py") else "ts"


def diff_names(diff: str) -> dict[str, list[str]]:
    """Code-shaped names by role (attribute, called name, compound name) from changed and context lines."""
    body = "\n".join(ln.text for ln in all_lines(parse_diff(diff)))
    return {k: sorted({t for t in rx.findall(body) if plain_name(t)}) for k, rx in NAME_KINDS.items()}


def fabricate(rng: random.Random, snip: str, diff: str, names: dict[str, list[str]], lang: str) -> str | None:
    """A plausible edit of snip that appears nowhere in the diff."""
    ops: set[str] = set()
    for a, b in SWAPS[lang]:
        if a in snip:
            ops.add(snip.replace(a, b, 1))
    m = re.search(r"\b(\d+)\b", snip)
    if m:
        ops.add(snip[: m.start()] + str(int(m.group(1)) + 1) + snip[m.end():])
    renames: set[str] = set()
    for kind, rx in NAME_KINDS.items():
        for m in rx.finditer(snip):
            tok = m.group(1)
            if not plain_name(tok) or in_string(snip, m.start(1)):
                continue
            for other in names[kind]:
                if other != tok and other not in snip and name_style(other) == name_style(tok):
                    renames.add(snip[: m.start(1)] + other + snip[m.end(1):])

    def keep(opts: set[str]) -> list[str]:
        return sorted(
            o for o in opts
            if o != snip and o.strip() and o not in diff and "`" not in o
            and not any(w in o.lower() for w in BANNED)
        )

    ops_ok, renames_ok = keep(ops), keep(renames)
    if ops_ok and (not renames_ok or rng.random() < 0.5):
        return rng.choice(ops_ok)
    return rng.choice(renames_ok) if renames_ok else None


# --- item construction -----------------------------------------------------


def hunk_of(unit: Unit, ln: Line) -> Hunk:
    return unit.hunks[ln.hunk]


def where_parts(rng: random.Random, unit: Unit, ln: Line, file_ok: bool) -> tuple[str | None, str | None]:
    func = scope_of(unit.sources[(ln.op, ln.file)], ln.no)
    if func and (any(w in func.lower() for w in BANNED) or rng.random() < 0.4):
        func = None
    file = ln.file if file_ok and rng.random() < 0.45 else None
    return func, file


def item(
    iid: str, tier: str, kind: str, unit: Unit, diff: str, rng: random.Random,
    claim: str, file: str, line: int, rationale: str,
) -> dict:
    return {
        "id": iid,
        "tier": tier,
        "kind": kind,
        "source": {"repo": unit.repo, "commit": unit.commit},
        "diff": diff,
        "finding": {
            "role": rng.choice(ROLES),
            "claim": claim,
            "evidence": {"kind": "file", "file": file, "line": line},
        },
        "label": kind in TRUE_KINDS,
        "label_basis": "construction",
        "rationale": rationale,
    }


def far_line(rng: random.Random, unit: Unit, ln: Line) -> int:
    """A cited line 6 to 40 lines from ln, on a line the diff shows when possible."""
    side = [x.old if ln.op == "-" else x.new for x in all_lines(unit.hunks)
            if x.file == ln.file and x.op in (" ", ln.op)]
    seen = sorted({n for n in side if n is not None and NEAR < abs(n - ln.no) <= 40})
    if seen:
        return rng.choice(seen)
    up = [ln.no + d for d in range(NEAR + 1, 41)]
    down = [ln.no - d for d in range(NEAR + 1, 41) if ln.no - d >= 1]
    return rng.choice(up + down)


def other_file(rng: random.Random, unit: Unit, ln: Line) -> str:
    inside = [f for f in unit.files if f != ln.file]
    outside = [f for f in unit.tree if f not in unit.files and not any(w in f.lower() for w in BANNED)]
    pool = inside if inside and (not outside or rng.random() < 0.5) else outside
    return rng.choice(pool)


def build_mech(units: list[Unit], rng: random.Random, used: set) -> list[dict]:
    slots = [k for k, n in MECH_KINDS for _ in range(n)]
    rng.shuffle(slots)
    count = {id(u): 0 for u in units}
    names = {id(u): diff_names(u.diff) for u in units}
    out: list[dict] = []
    for kind in slots:
        ops = {"true_added": ["+"], "true_removed": ["-"]}.get(kind, ["+", "-"])

        def free(u: Unit, op: str) -> list[Line]:
            lines = [ln for ln in u.cands[op] if (u.commit, ln.file, ln.op, ln.no) not in used]
            if kind == "fabricated":  # only lines that admit a plausible edit
                probe = random.Random(0)
                lines = [ln for ln in lines if fabricate(probe, ln.text.strip(), u.diff, names[id(u)], lang_of(ln.file))]
            return lines

        feasible = [u for u in units if any(free(u, op) for op in ops)]
        low = min(count[id(u)] for u in feasible)
        unit = rng.choice([u for u in feasible if count[id(u)] == low])
        op = rng.choice([o for o in ops if free(unit, o)])
        ln = rng.choice(free(unit, op))
        snip = ln.text.strip()
        n = len(out) + 1
        iid = f"mech-{n:04d}"
        side = "new" if op == "+" else "old"
        verb = "added" if op == "+" else "removed"
        if kind in ("true_added", "true_removed"):
            func, file = where_parts(rng, unit, ln, True)
            claim = make_claim(rng, op, snip, func, file)
            cite_file, cite_line = ln.file, ln.no
            why = f"`{snip}` is an {verb} line at {side} line {ln.no} of {ln.file}, exactly where the evidence points."
        elif kind == "wrong_line":
            func, file = where_parts(rng, unit, ln, True)
            claim = make_claim(rng, op, snip, func, file)
            cite_file, cite_line = ln.file, far_line(rng, unit, ln)
            why = (f"The claim holds at {side} line {ln.no} of {ln.file}, but the evidence cites line "
                   f"{cite_line}, {abs(cite_line - ln.no)} lines away.")
        elif kind == "wrong_file":
            func, _ = where_parts(rng, unit, ln, False)
            claim = make_claim(rng, op, snip, func, None)
            cite_file, cite_line = other_file(rng, unit, ln), ln.no
            where = "another file in the diff" if cite_file in unit.files else "a file outside the diff"
            why = f"The claim holds in {ln.file}, but the evidence cites {cite_file}, {where}."
        elif kind == "negated":
            func, file = where_parts(rng, unit, ln, True)
            flip = "-" if op == "+" else "+"
            claim = make_claim(rng, flip, snip, func, file)
            cite_file, cite_line = ln.file, ln.no
            said = "removed" if flip == "-" else "added"
            why = f"`{snip}` is {verb} at {side} line {ln.no} of {ln.file}; the claim says it is {said}."
        else:  # fabricated
            fake = fabricate(rng, snip, unit.diff, names[id(unit)], lang_of(ln.file))
            if fake is None:
                raise SystemExit(f"no fabrication for {unit.repo}@{unit.commit[:8]}: {snip}")
            func, file = where_parts(rng, unit, ln, True)
            claim = make_claim(rng, op, fake, func, file)
            cite_file, cite_line = ln.file, ln.no
            why = (f"The quoted `{fake}` appears nowhere in the diff; the cited line {ln.no} of "
                   f"{ln.file} actually reads `{snip}`.")
        used.add((unit.commit, ln.file, ln.op, ln.no))
        count[id(unit)] += 1
        out.append(item(iid, "mechanical", kind, unit, unit.diff, rng, claim, cite_file, cite_line, why))
    return out


def build_decoy(units: list[Unit], rng: random.Random, used: set) -> list[dict]:
    slots = [k for k, n in DECOY_KINDS for _ in range(n)]
    out: list[dict] = []
    pool = sorted(units, key=lambda u: (u.repo, u.commit))
    taken: set[str] = set()
    for kind in slots:
        picks = []
        for u in pool:
            for op in ("+", "-"):
                for ln in u.cands[op]:
                    if (u.commit, ln.file, ln.op, ln.no) in used:
                        continue
                    if kind == "truncated_evidence" and ln.hunk == 0:
                        continue
                    picks.append((u, ln))
        fresh = [p for p in picks if p[0].commit not in taken] or picks
        unit, ln = rng.choice(fresh)
        taken.add(unit.commit)
        used.add((unit.commit, ln.file, ln.op, ln.no))
        snip = ln.text.strip()
        op = ln.op
        func, file = where_parts(rng, unit, ln, True)
        claim = make_claim(rng, op, snip, func, file)
        iid = f"decoy-{len(out) + 1:03d}"
        cite_line = ln.no
        if kind == "empty_diff":
            diff = ""
            why = "The diff is empty, so no evidence can support the claim."
        elif kind == "truncated_evidence":
            h = hunk_of(unit, ln)
            cut = h.file_offset if h.first_in_file else h.offset
            diff = unit.diff[:cut]
            why = f"The diff is cut before the hunk holding line {ln.no} of {ln.file}, so the evidence is missing."
        else:  # right_claim_wrong_line
            diff = unit.diff
            step = rng.choice([d for d in (-3, -2, -1, 1, 2, 3) if ln.no + d >= 1])
            cite_line = ln.no + step
            why = (f"The claim holds at line {ln.no} of {ln.file}; the citation is {abs(step)} line(s) off, "
                   f"inside the {NEAR}-line tolerance, so it counts as supported.")
        out.append(item(iid, "decoy", kind, unit, diff, rng, claim, ln.file, cite_line, why))
    return out


def build(cache_dir: str) -> None:
    units: list[Unit] = []
    for name in sorted(SOURCES):
        spec = SOURCES[name]
        path = repo_dir(name, spec, cache_dir)
        for sha in sorted(spec["commits"]):
            units.append(load_unit(name, path, sha))
    rng = random.Random(SEED)
    used: set = set()
    mech = build_mech(units, rng, used)
    decoy = build_decoy(units, rng, used)
    os.makedirs(DATA, exist_ok=True)
    for fname, items in (("mechanical.jsonl", mech), ("decoy.jsonl", decoy)):
        with open(os.path.join(DATA, fname), "w", encoding="utf-8", newline="\n") as f:
            for it in items:
                f.write(json.dumps(it, ensure_ascii=True) + "\n")
    bad = check_files([os.path.join(DATA, "mechanical.jsonl"), os.path.join(DATA, "decoy.jsonl")])
    print(f"wrote {len(mech)} mechanical, {len(decoy)} decoy items from {len(units)} diffs")
    if bad:
        for b in bad:
            print(f"CHECK FAIL  {b}")
        sys.exit(1)


# --- check: re-derive every label from the item's own text -----------------


def derive(it: dict) -> tuple[bool | None, list[str]]:
    """(supported, problems). supported is None when the claim cannot be parsed."""
    problems: list[str] = []
    diff = it.get("diff", "")
    finding = it.get("finding") or {}
    ev = finding.get("evidence") or {}
    claim = finding.get("claim", "")
    if len(diff) > MAX_DIFF_CHARS:
        problems.append(f"diff is {len(diff)} chars, over {MAX_DIFF_CHARS}")
    if BANNED_RE.search(claim):
        problems.append("claim contains a banned word")
    if ev.get("kind") != "file" or not isinstance(ev.get("line"), int) or not ev.get("file"):
        problems.append("evidence is not {kind: file, file, line}")
        return None, problems
    parsed = parse_claim(claim)
    if parsed is None:
        problems.append("claim does not parse to one (op, snippet)")
        return None, problems
    op, snip, _func, cfile = parsed
    if cfile is not None and cfile != ev["file"]:
        problems.append(f"claim names {cfile} but evidence cites {ev['file']}")
    lines = all_lines(parse_diff(diff))
    hits = [ln for ln in lines if ln.op == op and snip in ln.text]
    supported = any(ln.file == ev["file"] and abs(ln.no - ev["line"]) <= NEAR for ln in hits)

    # Kind-specific shape, so a mislabeled kind is caught too.
    kind = it.get("kind")
    in_file = [ln for ln in hits if ln.file == ev["file"]]
    if kind in ("true_added", "true_removed"):
        want = "+" if kind == "true_added" else "-"
        if op != want or not any(ln.no == ev["line"] for ln in in_file):
            problems.append(f"{kind}: no {want} line with the snippet at the cited line")
    elif kind == "wrong_line":
        if not in_file or any(abs(ln.no - ev["line"]) <= NEAR for ln in in_file):
            problems.append("wrong_line: snippet not in the cited file, or citation within 5 lines")
    elif kind == "wrong_file":
        if not hits or in_file:
            problems.append("wrong_file: claim does not hold elsewhere, or holds in the cited file")
    elif kind == "negated":
        flip = "-" if op == "+" else "+"
        opp = [ln for ln in lines if ln.op == flip and snip in ln.text and ln.file == ev["file"]]
        if hits or not any(abs(ln.no - ev["line"]) <= NEAR for ln in opp):
            problems.append("negated: snippet is not on the opposite side at the citation")
    elif kind == "fabricated":
        if snip in diff:
            problems.append("fabricated: quoted snippet occurs in the diff")
        cited = [ln for ln in lines if ln.file == ev["file"] and ln.op == op and ln.no == ev["line"]]
        if not cited:
            problems.append("fabricated: citation is not a changed line")
    elif kind == "empty_diff":
        if diff != "":
            problems.append("empty_diff: diff is not empty")
    elif kind == "truncated_evidence":
        if not diff or hits:
            problems.append("truncated_evidence: diff is empty or still holds the snippet")
    elif kind == "right_claim_wrong_line":
        if not any(1 <= abs(ln.no - ev["line"]) <= 3 for ln in in_file):
            problems.append("right_claim_wrong_line: citation is not 1 to 3 lines off")
    else:
        problems.append(f"unknown kind {kind!r}")
    return supported, problems


def check_files(paths: list[str]) -> list[str]:
    bad: list[str] = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for n, raw in enumerate(f, 1):
                if not raw.strip():
                    continue
                it = json.loads(raw)
                iid = it.get("id", f"{os.path.basename(path)}:{n}")
                supported, problems = derive(it)
                if supported is not None and supported != it.get("label"):
                    problems.insert(0, f"stored label {it.get('label')} but the diff gives {supported}")
                bad += [f"{iid}: {p}" for p in problems]
    return bad


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache-dir", help="where public repos are cloned when missing")
    ap.add_argument("--check", nargs="*", metavar="FILE", help="re-derive labels (default: both data files)")
    args = ap.parse_args()
    if args.check is not None:
        paths = args.check or [os.path.join(DATA, "mechanical.jsonl"), os.path.join(DATA, "decoy.jsonl")]
        bad = check_files(paths)
        total = sum(1 for p in paths for raw in open(p, encoding="utf-8") if raw.strip())
        for b in bad:
            print(f"FAIL  {b}")
        print(f"checked {total} items in {len(paths)} file(s): {len(bad)} problem(s)")
        sys.exit(1 if bad else 0)
    if not args.cache_dir:
        ap.error("--cache-dir is required to build")
    build(os.path.abspath(args.cache_dir))


if __name__ == "__main__":
    main()
