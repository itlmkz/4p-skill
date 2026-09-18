#!/usr/bin/env python3
"""The 4p report contract: validate, extract, and describe.

The panes speak this contract in both directions. The coordinator uses the same
tool, so a malformed report can never reach the merge step.

    report.py --contract                 print the contract, for the pane brief
    report.py --validate FILE            validate one report
    report.py --extract [FILE]           pull the json block out of raw pane text
    report.py --extract FILE --validate  extract, then validate what came out

Reads stdin when FILE is absent or "-". Exits 0 when valid, 1 when not, and
prints one precise line per problem.

The schema is the source of truth. This validator implements the subset of JSON
Schema the contract uses, so the two cannot drift apart.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(HERE, "report.schema.json")

# Simplified Technical English, rule 5.1. Enforced, not merely requested.
# A language without spaces needs a character budget instead of a word budget.
# Measured: ~45 CJK characters carry the same content as one 20-word sentence.
STE100_MAX_WORDS = 20
STE100_MAX_CJK_CHARS = 45
EM_DASH = "\u2014"
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
SENTENCE_SPLIT = re.compile(r"[.!?;]+|[\u3002\uff01\uff1f\uff1b]+")

TYPE_MAP = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
}


def load_schema() -> dict:
    with open(SCHEMA_PATH) as fh:
        return json.load(fh)


def resolve(schema: dict, root: dict) -> dict:
    """Follow a local $ref. Everything in this contract is local."""
    seen = 0
    while "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith("#/"):
            return schema
        node = root
        for part in ref[2:].split("/"):
            node = node[part]
        schema = node
        seen += 1
        if seen > 20:  # cyclic refs are a bug in the schema, not in the report
            return schema
    return schema


def type_ok(value, expected: str) -> bool:
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    return isinstance(value, TYPE_MAP[expected])


def validate(value, schema: dict, root: dict, path: str, errors: list[str]) -> None:
    schema = resolve(schema, root)
    here = path or "$"

    if "type" in schema and not type_ok(value, schema["type"]):
        errors.append(f"{here}: expected {schema['type']}, got {type(value).__name__}")
        return

    if "const" in schema and value != schema["const"]:
        errors.append(f"{here}: must be {schema['const']!r}, got {value!r}")

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{here}: must be one of {'|'.join(map(str, schema['enum']))}, got {value!r}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{here}: shorter than {schema['minLength']} characters")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{here}: longer than {schema['maxLength']} characters")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{here}: does not match {schema['pattern']}")
        if schema.get("x-ste100"):
            check_ste100(value, here, errors)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{here}: below minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{here}: above maximum {schema['maximum']}")

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{here}: missing required field {key!r}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errors.append(f"{here}: unknown field {key!r}")
        for key, sub in props.items():
            if key in value and sub != {}:
                validate(value[key], sub, root, f"{here}.{key}", errors)

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{here}: needs at least {schema['minItems']} item(s)")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{here}: {len(value)} items, maximum is {schema['maxItems']}")
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(value):
                validate(item, item_schema, root, f"{here}[{i}]", errors)

    for sub in schema.get("allOf", []):
        validate(value, sub, root, here, errors)

    # if/then: the condition is satisfied when the instance raises no errors for it.
    if "if" in schema:
        probe: list[str] = []
        validate(value, schema["if"], root, here, probe)
        if not probe and "then" in schema:
            validate(value, schema["then"], root, here, errors)


def check_ste100(text: str, where: str, errors: list[str]) -> None:
    """Enforce the checkable part of ASD-STE100 on free text.

    Rule 5.1 (20 words per sentence) and the house rule against em dashes are
    mechanical. Word choice and voice are not, so they stay a request.

    Chinese, Japanese, and Korean have no spaces, so a word count is meaningless
    there and the rule would silently pass anything. Those scripts get a
    character budget instead, and their own sentence marks are recognised.
    """
    if EM_DASH in text:
        errors.append(f"{where}: contains an em dash. Use a comma or a full stop.")

    dense = bool(CJK.search(text))
    for sentence in SENTENCE_SPLIT.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        if dense:
            length = len(re.sub(r"\s+", "", sentence))
            if length > STE100_MAX_CJK_CHARS:
                errors.append(
                    f"{where}: sentence has {length} characters, the CJK budget is "
                    f"{STE100_MAX_CJK_CHARS}. Split it."
                )
        else:
            words = sentence.split()
            if len(words) > STE100_MAX_WORDS:
                errors.append(
                    f"{where}: sentence has {len(words)} words, STE100 allows "
                    f"{STE100_MAX_WORDS}. Split it."
                )


def validate_report(report, schema: dict) -> list[str]:
    errors: list[str] = []
    validate(report, schema, schema, "$", errors)
    return errors


def extract(text: str) -> tuple[object | None, str]:
    """Pull the report out of raw pane output.

    Panes are asked for one fenced json block. If a pane wraps it in prose, this
    still finds it. Candidates are tried in order, and the first one that parses
    is returned.
    """
    fenced = re.findall(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    candidates = [block.strip() for block in fenced]
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        candidates.append(value)

    for candidate in candidates:
        if isinstance(candidate, str):
            try:
                return json.loads(candidate), "fenced block"
            except json.JSONDecodeError:
                continue
        return candidate, "bare object"

    return None, "no json found"


def describe(schema: dict) -> str:
    """Compact, derived rendering of the contract. Cannot drift from the schema."""
    lines: list[str] = []
    ste100: list[str] = []

    def bits_of(node: dict) -> list[str]:
        node = resolve(node, schema)
        bits: list[str] = []
        if "enum" in node:
            bits.append("|".join(map(str, node["enum"])))
        elif "const" in node:
            bits.append(repr(node["const"]))
        elif "type" in node:
            bits.append(node["type"])
        if node.get("minimum") == 0 and node.get("maximum") == 1:
            bits.append("0..1")
        elif "minimum" in node:
            bits.append(f">={node['minimum']}")
        if node.get("maxItems"):
            bits.append(f"max {node['maxItems']}")
        if node.get("x-ste100"):
            bits.append("STE100")
        return bits

    def emit(node: dict, path: str, depth: int) -> None:
        node = resolve(node, schema)
        pad = "  " * depth
        required = node.get("required", [])
        if required:
            lines.append(f"{pad}required: {' '.join(required)}")
        for key, sub in (node.get("properties") or {}).items():
            sub_r = resolve(sub, schema)
            opt = "" if key in required else "  (optional)"
            field = f"{pad}{key}"
            sub_path = f"{path}.{key}" if path else key
            kind = sub_r.get("type")

            if kind == "object":
                lines.append(f"{field}:{opt}")
                emit(sub_r, sub_path, depth + 1)
                continue
            if kind == "array":
                items = resolve(sub_r.get("items", {}), schema)
                if items.get("type") == "object":
                    lines.append(f"{field}[]: max {sub_r.get('maxItems', '-')}{opt}")
                    emit(items, f"{sub_path}[]", depth + 1)
                else:
                    lines.append(f"{field}[]: {' '.join(bits_of(items))}{opt}")
                    if items.get("x-ste100"):
                        ste100.append(f"{sub_path}[]")
                continue

            lines.append(f"{field}: {' '.join(bits_of(sub_r))}{opt}")
            if sub_r.get("x-ste100"):
                ste100.append(sub_path)

    emit(schema, "", 0)
    out = "\n".join(lines)
    out += (
        "\n\nfree text marked STE100: one sentence, 20 words maximum, active voice,\n"
        "no em dash, one word for one meaning. Do not omit words. Sentences in\n"
        "Chinese, Japanese, or Korean are measured in characters, with a\n"
        "45-character budget, because those scripts have no spaces. The\n"
        "validator enforces sentence length and the em dash. Word choice is your\n"
        "responsibility."
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", default="-", help="report file, or - for stdin")
    ap.add_argument("--contract", action="store_true", help="print the contract")
    ap.add_argument("--validate", action="store_true", help="validate")
    ap.add_argument("--extract", action="store_true", help="pull json out of raw pane text")
    ap.add_argument("--json", action="store_true", help="with --extract, print the report")
    args = ap.parse_args()

    schema = load_schema()

    if args.contract:
        print(describe(schema))
        return 0

    text = sys.stdin.read() if args.file == "-" else open(args.file).read()

    if not args.extract and not args.validate:
        ap.error("choose --contract, --validate, or --extract")

    source = args.file
    report: object
    if args.extract:
        report, how = extract(text)
        if report is None:
            print("report: no json block found in the pane output", file=sys.stderr)
            return 1
        source = f"{args.file} ({how})"
    else:
        try:
            report = json.loads(text)
        except json.JSONDecodeError as exc:
            print(f"{source}: not valid json: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report, indent=2))

    errors = validate_report(report, schema)
    if errors:
        print(f"{source}: {len(errors)} problem(s)", file=sys.stderr)
        for err in errors:
            print(f"  {err}", file=sys.stderr)
        return 1

    print(f"{source}: valid 4p/report@1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
