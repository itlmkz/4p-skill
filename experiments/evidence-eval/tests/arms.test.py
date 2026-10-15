#!/usr/bin/env python3
"""Tests for the eval arms and the runner. Offline: the network is disabled.

    python3 tests/arms.test.py

Covers answer parsing, the state never leaking labels, the jev and chat arms
over stubbed transports (OpenRouter and the claude CLI), cache and resume, the budget stop, the error-rate stop,
the pilot table, and fake-arm determinism.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))


def _no_network(*args, **kwargs):
    raise AssertionError("a test tried to reach the network")


def _no_subprocess(*args, **kwargs):
    raise AssertionError("a test tried to start a real process")


urllib.request.urlopen = _no_network
real_subprocess_run = subprocess.run
subprocess.run = _no_subprocess

import arms  # noqa: E402
import run_eval  # noqa: E402
from arms import ARMS, Arm, Prediction, build_state, make_chat_arm, parse_answer  # noqa: E402

failures = 0
FIXTURE = os.path.join(HERE, "..", "data", "fixture.jsonl")


def check(label: str, got, want) -> None:
    global failures
    ok = got == want
    if not ok:
        failures += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        got  {got!r}\n        want {want!r}")


def parse_error(text) -> bool:
    try:
        parse_answer(text)
    except ValueError:
        return True
    return False


def make_items(n: int, tier: str = "mechanical") -> list:
    return [
        {
            "id": f"t-{i}",
            "tier": tier,
            "kind": "true_added",
            "diff": "+x = 1\n",
            "finding": {"role": "reviewer", "claim": "c", "evidence": {"kind": "file", "file": "a.py", "line": 1}},
            "label": True,
            "rationale": "r",
        }
        for i in range(n)
    ]


def quiet(fn, *args, **kwargs):
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = fn(*args, **kwargs)
    return result, buf.getvalue()


# --- answer parsing --------------------------------------------------------

check("plain json", parse_answer('{"p_supported": 0.73}'), 0.73)
check("json inside prose", parse_answer('I think so. {"p_supported": 0.2} That is my answer.'), 0.2)
check("fenced json", parse_answer('```json\n{"p_supported": 0.9}\n```'), 0.9)
check("integer value", parse_answer('{"p_supported": 1}'), 1.0)
check("clamp above 1", parse_answer('{"p_supported": 1.7}'), 1.0)
check("clamp below 0", parse_answer('{"p_supported": -0.3}'), 0.0)
check("skips an earlier object without the field", parse_answer('{"note": "x"} {"p_supported": 0.4}'), 0.4)
check("missing field is an error", parse_error('{"probability": 0.8}'), True)
check("garbage is an error", parse_error("yes, definitely supported"), True)
check("empty answer is an error", parse_error(""), True)
check("None is an error", parse_error(None), True)
check("string value is an error", parse_error('{"p_supported": "0.8"}'), True)
check("bool value is an error", parse_error('{"p_supported": true}'), True)
check("broken json is an error", parse_error('{"p_supported": 0.8'), True)

# --- state building never leaks --------------------------------------------

SECRET_ITEM = {
    "id": "LEAKID-77",
    "tier": "LEAKTIER",
    "kind": "LEAKKIND",
    "label": False,
    "label_basis": "LEAKBASIS",
    "rationale": "LEAKRATIONALE",
    "source": {"repo": "LEAKREPO/x", "commit": "abc"},
    "diff": "+" + "y" * 20000,
    "finding": {"role": "LEAKROLE", "claim": "the claim", "evidence": {"kind": "file", "file": "a.py", "line": 3}},
}
LEAK_MARKERS = ["LEAKID", "LEAKTIER", "LEAKKIND", "LEAKBASIS", "LEAKRATIONALE", "LEAKREPO", "LEAKROLE", '"label"', '"tier"', '"kind": "LEAK', '"rationale"', '"id"']

state = build_state(SECRET_ITEM)
check("state has exactly diff and finding", sorted(state), ["diff", "finding"])
check("finding has exactly claim and evidence", sorted(state["finding"]), ["claim", "evidence"])
check("diff is cut to 12000 chars", len(state["diff"]), 12000)
dumped = json.dumps(state)
check("state json carries no label, kind, rationale, tier, id", [m for m in LEAK_MARKERS if m in dumped], [])

# --- jev arm over a stubbed jev.ask ----------------------------------------

sent: dict = {}


def fake_ask(state, questions, model):
    sent.update(state=state, questions=questions, model=model)
    return {"model": model, "answers": {"supported": {"noul": 0.81}}, "usage": {"cost": 0.0004}, "id": "x"}


real_ask = arms.jev.ask
arms.jev.ask = fake_ask
pred = ARMS["jev"].predict(SECRET_ITEM)
check("jev p from answers.supported.noul", pred.p, 0.81)
check("jev cost from usage.cost", pred.cost_usd, 0.0004)
check("jev model is typesafe/jev-1.13", sent["model"], "typesafe/jev-1.13")
check("jev asks one noul question keyed supported", (list(sent["questions"]), sent["questions"]["supported"]["type"]), (["supported"], "noul"))
check(
    "jev question wording matches gate.py",
    sent["questions"]["supported"],
    {
        "type": "noul",
        "instructions": "Does `diff` support the claim in `finding.claim`, given the evidence in `finding.evidence`?",
        "criteria": {
            "true": "The evidence exists in the diff and it supports the claim",
            "false": "The evidence is missing from the diff, or it does not support the claim",
        },
    },
)
check("jev payload carries no label, kind, rationale, tier, id", [m for m in LEAK_MARKERS if m in json.dumps(sent["state"])], [])

arms.jev.ask = lambda state, questions, model: (_ for _ in ()).throw(RuntimeError("HTTP 500: boom"))
pred = ARMS["jev"].predict(SECRET_ITEM)
check("jev failure returns p=0.5 with an error", (pred.p, pred.error is not None, "boom" in (pred.error or "")), (0.5, True, True))
arms.jev.ask = lambda state, questions, model: {"answers": {}, "usage": {"cost": 0.0003}}
pred = ARMS["jev"].predict(SECRET_ITEM)
check("jev malformed answer is an error that keeps its cost", (pred.p, pred.error is not None, pred.cost_usd), (0.5, True, 0.0003))
arms.jev.ask = real_ask

# --- chat arms over a stubbed OpenRouter transport -------------------------

OR_HAIKU = make_chat_arm("haiku", "openrouter")
OR_OPUS = make_chat_arm("opus", "openrouter")

posted: dict = {}
reply = {"content": '{"p_supported": 0.35}'}


def fake_post(payload):
    posted.clear()
    posted.update(payload)
    return {"model": payload["model"], "choices": [{"message": {"content": reply["content"]}}], "usage": {"cost": 0.0021}}


real_post = arms._post_chat
arms._post_chat = fake_post
pred = OR_HAIKU.predict(SECRET_ITEM)
check("haiku parses p", (pred.p, pred.error, pred.cost_usd), (0.35, None, 0.0021))
check("haiku request shape", (posted["model"], posted["temperature"], posted["max_tokens"], posted["usage"]), ("anthropic/claude-haiku-5.5", 0, 300, {"include": True}))
check("chat messages are system then user", [m["role"] for m in posted["messages"]], ["system", "user"])
user_msg = posted["messages"][1]["content"]
check("user message carries the question lines", all(s in user_msg for s in (arms.INSTRUCTIONS, arms.TRUE_TEXT, arms.FALSE_TEXT, arms.ANSWER_FORMAT)), True)
check("chat payload carries no label, kind, rationale, tier, id", [m for m in LEAK_MARKERS if m in json.dumps(posted)], [])
OR_OPUS.predict(SECRET_ITEM)
check("opus uses the same prompt", (posted["model"], posted["messages"][1]["content"] == user_msg), ("anthropic/claude-opus-5.5", True))
reply["content"] = "I cannot tell."
pred = OR_OPUS.predict(SECRET_ITEM)
check("unparseable chat answer is an error that keeps its cost", (pred.p, pred.error is not None, pred.cost_usd), (0.5, True, 0.0021))
arms._post_chat = real_post

# The real transport with no network must still not raise out of predict.
check("openrouter model field records the transport", OR_HAIKU.model, "openrouter:anthropic/claude-haiku-5.5")
pred = OR_HAIKU.predict(SECRET_ITEM)
check("haiku with the network down returns an error, no raise", (pred.p, pred.error is not None), (0.5, True))


# --- chat arms over a stubbed claude CLI -------------------------------------


class FakeProc:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


cli_calls: list = []
cli_reply: dict = {}


def fake_run(argv, **kwargs):
    cli_calls.append((argv, kwargs))
    if cli_reply.get("timeout"):
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
    return FakeProc(cli_reply.get("stdout", ""), cli_reply.get("returncode", 0), cli_reply.get("stderr", ""))


def cli_json(result, is_error=False, cost=0.00014):
    return json.dumps({"type": "result", "result": result, "is_error": is_error, "total_cost_usd": cost, "usage": {"input_tokens": 653}})


subprocess.run = fake_run
CLI_HAIKU, CLI_OPUS = ARMS["haiku"], ARMS["opus"]
check("default transport is claude-cli", (CLI_HAIKU.model, CLI_OPUS.model), ("claude-cli:claude-haiku-5-5", "claude-cli:claude-opus-5-5"))

cli_reply.update(stdout=cli_json('{"p_supported": 0.42}'))
pred = CLI_HAIKU.predict(SECRET_ITEM)
check("cli good json parses p and total_cost_usd", (pred.p, pred.cost_usd, pred.error), (0.42, 0.00014, None))
argv, kwargs = cli_calls[-1]
check("cli runs without a shell, prompt on stdin, 180 s timeout", (isinstance(argv, list), kwargs.get("shell", False), kwargs["timeout"]), (True, False, 180.0))
check("cli runs in an empty folder", os.path.isdir(kwargs["cwd"]) and os.listdir(kwargs["cwd"]) == [], True)
for flag in ["-p", "--tools", "--setting-sources", "--strict-mcp-config", "--mcp-config", "--disable-slash-commands",
             "--exclude-dynamic-system-prompt-sections", "--no-session-persistence", "--output-format", "--system-prompt", "--model"]:
    check(f"cli argv has {flag}", flag in argv, True)
check("cli --tools is empty", argv[argv.index("--tools") + 1], "")
check("cli --setting-sources is empty", argv[argv.index("--setting-sources") + 1], "")
check("cli --mcp-config is an empty server map", json.loads(argv[argv.index("--mcp-config") + 1]), {"mcpServers": {}})
check("cli --output-format json", argv[argv.index("--output-format") + 1], "json")
check("cli --model is the haiku id", argv[argv.index("--model") + 1], "claude-haiku-5-5")
check("cli argv never skips permissions", any("dangerously" in a for a in argv), False)
or_system, or_user = arms.chat_prompt(build_state(SECRET_ITEM))
check("cli system prompt matches the chat system message", argv[argv.index("--system-prompt") + 1], or_system)
check("cli stdin matches the chat user message, same as openrouter", kwargs["input"], user_msg)
check("cli payload carries no label, kind, rationale, tier, id", [m for m in LEAK_MARKERS if m in json.dumps([argv, kwargs["input"]])], [])

CLI_OPUS.predict(SECRET_ITEM)
check("cli opus uses the opus id", cli_calls[-1][0][cli_calls[-1][0].index("--model") + 1], "claude-opus-5-5")

cli_reply.clear()
cli_reply.update(stdout=cli_json("rate limited", is_error=True, cost=0.0))
pred = CLI_HAIKU.predict(SECRET_ITEM)
check("cli is_error gives p=0.5 with an error", (pred.p, pred.error is not None and "is_error" in pred.error), (0.5, True))

cli_reply.clear()
cli_reply.update(stdout="", stderr="boom", returncode=1)
pred = CLI_HAIKU.predict(SECRET_ITEM)
check("cli non-zero exit gives p=0.5 with an error", (pred.p, pred.error is not None and "exit 1" in pred.error), (0.5, True))

cli_reply.clear()
cli_reply.update(stdout=cli_json('{"p_supported": 0.9}'), returncode=2)
pred = CLI_HAIKU.predict(SECRET_ITEM)
check("cli non-zero exit with json output is still an error", (pred.p, pred.error is not None), (0.5, True))

cli_reply.clear()
cli_reply.update(timeout=True)
pred = CLI_HAIKU.predict(SECRET_ITEM)
check("cli timeout records est_cost_usd as cost with error timeout", (pred.p, pred.error, pred.cost_usd), (0.5, "timeout", CLI_HAIKU.est_cost_usd))

cli_reply.clear()
cli_reply.update(stdout=cli_json("Supported, I would say."))
pred = CLI_HAIKU.predict(SECRET_ITEM)
check("cli garbage result is an error that keeps its cost", (pred.p, pred.error is not None, pred.cost_usd), (0.5, True, 0.00014))

cli_reply.clear()
cli_reply.update(stdout="not json at all")
pred = CLI_HAIKU.predict(SECRET_ITEM)
check("cli non-json stdout is an error", (pred.p, pred.error is not None), (0.5, True))

with tempfile.TemporaryDirectory() as tmp:
    cli_reply.clear()
    cli_reply.update(stdout=cli_json('{"p_supported": 0.5}', cost=0.001))
    summary, _ = quiet(run_eval.run_arm, CLI_HAIKU, make_items(8), tmp, run_eval.Budget(8.0), workers=4)
    recs = run_eval.read_records(os.path.join(tmp, "haiku.jsonl"))
    check("cli arm runs under 4 workers, budget uses total_cost_usd", (summary["n"], round(summary["spend"], 6), recs[0]["model"]), (8, 0.008, "claude-cli:claude-haiku-5-5"))

with tempfile.TemporaryDirectory() as tmp:
    code, out = quiet(run_eval.main, ["--data", FIXTURE, "--arms", "haiku", "--limit", "1", "--chat-transport", "openrouter", "--out", tmp, "--workers", "1"])
    recs = run_eval.read_records(os.path.join(tmp, "haiku.jsonl"))
    check("--chat-transport openrouter swaps the transport", {r["model"] for r in recs}, {"openrouter:anthropic/claude-haiku-5.5"})

subprocess.run = _no_subprocess

# --- fake and accept_all ---------------------------------------------------

a = ARMS["fake"].predict({"id": "fix-1"})
b = ARMS["fake"].predict({"id": "fix-1"})
c = ARMS["fake"].predict({"id": "fix-2"})
check("fake arm is deterministic", a.p, b.p)
check("fake arm varies by id", a.p != c.p, True)
check("fake p in [0, 1] and free", (0.0 <= a.p <= 1.0, a.cost_usd, a.error), (True, 0.0, None))
check("accept_all is 1.0 and free", (ARMS["accept_all"].predict({"id": "x"}).p, ARMS["accept_all"].predict({"id": "x"}).cost_usd), (1.0, 0.0))
check("ARMS keys", sorted(ARMS), ["accept_all", "fake", "haiku", "jev", "opus"])
check("every arm has name and model", all(isinstance(x.name, str) and isinstance(x.model, str) for x in ARMS.values()), True)

# --- runner: limit, cache and resume ---------------------------------------


class CountingArm(Arm):
    def __init__(self, name="counting", cost=0.0, fail=False):
        self.name = name
        self.model = "stub"
        self.cost = cost
        self.fail = fail
        self.calls = 0
        self.est_cost_usd = cost

    def _predict(self, item):
        self.calls += 1
        if self.fail:
            raise RuntimeError("stubbed failure")
        return 0.6, self.cost, None


mixed = make_items(3, "mechanical") + [dict(it, id=f"d-{i}", tier="decoy") for i, it in enumerate(make_items(3))]
check("limit_per_tier keeps the first N per tier in order", [it["id"] for it in run_eval.limit_per_tier(mixed, 1)], ["t-0", "d-0"])

with tempfile.TemporaryDirectory() as tmp:
    items = run_eval.load_items([FIXTURE])
    arm = CountingArm()
    s1, _ = quiet(run_eval.run_arm, arm, items, tmp, run_eval.Budget(8.0), workers=4)
    lines = run_eval.read_records(os.path.join(tmp, "counting.jsonl"))
    check("first run answers 5 items", (s1["n"], arm.calls, len(lines)), (5, 5, 5))
    check(
        "record shape",
        sorted(lines[0]),
        sorted(["item_id", "arm", "model", "p", "cost_usd", "latency_s", "error", "raw"]),
    )
    s2, _ = quiet(run_eval.run_arm, arm, items, tmp, run_eval.Budget(8.0), workers=4)
    check("second run skips all 5", (s2["n"], s2["cached"], arm.calls), (0, 5, 5))

    # An errored item is retried, then compacted to one line with summed cost.
    path = os.path.join(tmp, "retry.jsonl")
    with open(path, "w") as fh:
        fh.write(json.dumps({"item_id": "fix-1", "arm": "retry", "model": "stub", "p": 0.5, "cost_usd": 0.01, "latency_s": 1, "error": "x", "raw": None}) + "\n")
    retry = CountingArm("retry", cost=0.02)
    quiet(run_eval.run_arm, retry, items[:1], tmp, run_eval.Budget(8.0), workers=1)
    recs = run_eval.read_records(path)
    check("errored item is retried and compacted", (retry.calls, len(recs), recs[0]["error"], round(recs[0]["cost_usd"], 6), recs[0]["attempts"]), (1, 1, None, 0.03, 2))
    check("spent_in sums every arm file", round(run_eval.spent_in(tmp), 6), 0.03)

# --- runner: budget stop ---------------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    arm = CountingArm("pricey", cost=0.4)
    summary, out = quiet(run_eval.run_arm, arm, make_items(10), tmp, run_eval.Budget(1.0), workers=1)
    check("budget stop: 2 calls fit under $1.00 at $0.40", (arm.calls, summary["n"]), (2, 2))
    check("budget stop is reported", summary["stop"] is not None and "budget" in summary["stop"] and "budget" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    arm = CountingArm("pricey", cost=0.4)
    summary, _ = quiet(run_eval.run_arm, arm, make_items(10), tmp, run_eval.Budget(1.0), workers=4)
    check("budget stop holds with 4 workers", arm.calls <= 2, True)

with tempfile.TemporaryDirectory() as tmp:
    with open(os.path.join(tmp, "older.jsonl"), "w") as fh:
        fh.write(json.dumps({"item_id": "z", "cost_usd": 0.9}) + "\n")
    arm = CountingArm("pricey", cost=0.4)
    budget = run_eval.Budget(1.0, run_eval.spent_in(tmp))
    summary, _ = quiet(run_eval.run_arm, arm, make_items(10), tmp, budget, workers=1)
    check("budget counts spend already in other arm files", arm.calls, 0)

# --- runner: a torn last line from a crash (review finding 1) ---------------


class PaidFake(Arm):
    name = "paid"
    model = "paid"
    est_cost_usd = 0.01

    def _predict(self, item):
        return 0.7, 0.03, None


with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, "paid.jsonl")
    torn_items = [{"id": f"i{k}", "tier": "mechanical"} for k in range(3)]
    good = {"item_id": "i0", "arm": "paid", "model": "paid", "p": 0.7, "cost_usd": 0.03, "latency_s": 0.1, "error": None, "raw": None}
    with open(path, "w") as fh:
        fh.write(json.dumps(good) + "\n" + json.dumps(dict(good, item_id="i1"))[:40])  # crash mid-write: no newline
    s, out = quiet(run_eval.run_arm, PaidFake(), torn_items, tmp, run_eval.Budget(8.0), workers=1)
    check("torn last line: resume keeps every record readable", sorted(r["item_id"] for r in run_eval.read_records(path)), ["i0", "i1", "i2"])
    check("torn last line: spent_in counts every paid call", round(run_eval.spent_in(tmp), 6), 0.09)
    check("torn last line: dropped lines are reported", "dropped 1" in out, True)
    s2, _ = quiet(run_eval.run_arm, PaidFake(), torn_items, tmp, run_eval.Budget(8.0), workers=1)
    check("torn last line: second resume re-runs nothing", s2["n"], 0)

# --- runner: concurrent calls and the cap (review finding 2) -----------------


class SlowPricey(Arm):
    """est_cost_usd 0.05 like opus, real cost 0.12 per call."""

    name = "slowpricey"
    model = "stub"
    est_cost_usd = 0.05

    def __init__(self):
        self.lock = threading.Lock()
        self.started = 0
        self.finished = 0
        self.started_before_first_finish = 0

    def _predict(self, item):
        with self.lock:
            self.started += 1
            if self.finished == 0:
                self.started_before_first_finish = self.started
        time.sleep(0.05)
        with self.lock:
            self.finished += 1
        return 0.5, 0.12, None


with tempfile.TemporaryDirectory() as tmp:
    arm = SlowPricey()
    summary, _ = quiet(run_eval.run_arm, arm, make_items(20), tmp, run_eval.Budget(0.50), workers=4)
    check("budget with 4 workers stays under the cap when real cost exceeds the estimate", run_eval.spent_in(tmp) <= 0.50 + 1e-9, True)
    check("budget: one call at a time until the first real cost lands", arm.started_before_first_finish, 1)
    check("budget: the stop is reported", summary["stop"] is not None and "budget" in summary["stop"], True)

# --- runner: error-rate stop -----------------------------------------------

with tempfile.TemporaryDirectory() as tmp:
    arm = CountingArm("broken", fail=True)
    summary, out = quiet(run_eval.run_arm, arm, make_items(40), tmp, run_eval.Budget(8.0), workers=1)
    check("error stop after 20 items", (arm.calls, summary["errors"]), (20, 20))
    check("error stop is reported", summary["stop"] is not None and "error rate" in summary["stop"] and "error rate" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    arm = CountingArm("broken", fail=True)
    summary, _ = quiet(run_eval.run_arm, arm, make_items(15), tmp, run_eval.Budget(8.0), workers=1)
    check("no error stop before 20 items", (arm.calls, summary["stop"]), (15, None))

# --- pilot spend table and the CLI dry run ---------------------------------

with tempfile.TemporaryDirectory() as tmp:
    arm = CountingArm("pilotarm", cost=0.01)
    pilot = make_items(3)
    quiet(run_eval.run_arm, arm, pilot, tmp, run_eval.Budget(8.0), workers=1)
    total, out = quiet(run_eval.spend_table, ["pilotarm"], pilot, make_items(200), tmp)
    check("pilot extrapolates per-item cost to the full count", round(total, 6), 2.0)


class TierPriced(Arm):
    name = "tierpriced"
    model = "stub"

    def _predict(self, item):
        return 0.5, {"a": 0.01, "b": 0.03}[item["tier"]], None


tiered = [
    {"id": "a-0", "tier": "a", "diff": ""},
    {"id": "a-1", "tier": "a", "diff": "+x\n"},
    {"id": "b-0", "tier": "b", "diff": "+y\n"},
    {"id": "b-1", "tier": "b", "diff": "+y\n"},
    {"id": "b-2", "tier": "b", "diff": "+y\n"},
    {"id": "b-3", "tier": "b", "diff": "+y\n"},
]
check("pilot picks the first non-empty diff per tier", [it["id"] for it in run_eval.pilot_items(tiered)], ["a-1", "b-0"])
check("pilot falls back to the first item when a tier has only empty diffs", [it["id"] for it in run_eval.pilot_items([{"id": "e-0", "tier": "e", "diff": ""}])], ["e-0"])
with tempfile.TemporaryDirectory() as tmp:
    pilot = run_eval.pilot_items(tiered)
    quiet(run_eval.run_arm, TierPriced(), pilot, tmp, run_eval.Budget(8.0), workers=1)
    total, out = quiet(run_eval.spend_table, ["tierpriced"], pilot, tiered, tmp)
    check("pilot extrapolates per tier (tier cost x tier size)", round(total, 6), round(0.01 * 2 + 0.03 * 4, 6))

with tempfile.TemporaryDirectory() as tmp:
    code, out = quiet(run_eval.main, ["--data", FIXTURE, "--dry-run", "--out", tmp])
    check("dry run exits 0 and writes 5 fake results", (code, len(run_eval.read_records(os.path.join(tmp, "fake.jsonl")))), (0, 5))
    code, out = quiet(run_eval.main, ["--data", FIXTURE, "--dry-run", "--out", tmp, "--arms", "opus"])
    check("dry run forces the fake arm and skips cached items", ("cached=5" in out, os.path.exists(os.path.join(tmp, "opus.jsonl"))), (True, False))

print(f"\n{'all passed' if not failures else f'{failures} failed'}")
sys.exit(1 if failures else 0)
