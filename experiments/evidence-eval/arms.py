#!/usr/bin/env python3
"""The four arms of the evidence-check eval, behind one interface.

Stdlib only. Every arm sees the same state and answers the same question
(PREREG.md, "Shared state and question"), and returns a Prediction whose `p` is
its probability that the finding is supported.

    from arms import ARMS
    pred = ARMS["jev"].predict(item)

An arm never raises. A failure comes back as p=0.5 with `error` set, which is
how PREREG.md scores an unanswered item.

Arms: accept_all, jev, haiku, opus, plus `fake` (no network, for dry runs).
The jev arm reuses experiments/jev/jev.py. The chat arms (haiku, opus) have two
transports that send the same prompt text (chat_prompt):
  claude-cli   the local `claude -p`, isolated from any session (default)
  openrouter   OpenRouter chat completions, reusing jev.py's key lookup and TLS
ROADMAP.md: do not build a third Jev client.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "jev"))
import jev  # noqa: E402

# --- the shared question. Verbatim from experiments/jev/gate.py. -----------

MAX_DIFF_CHARS = 12000
INSTRUCTIONS = "Does `diff` support the claim in `finding.claim`, given the evidence in `finding.evidence`?"
TRUE_TEXT = "The evidence exists in the diff and it supports the claim"
FALSE_TEXT = "The evidence is missing from the diff, or it does not support the claim"
ANSWER_FORMAT = 'Answer with one json object {"p_supported": <number from 0 to 1>} and nothing else.'

JEV_MODEL = jev.DEFAULT_MODEL  # typesafe/jev-1.13
HAIKU_MODEL = "anthropic/claude-haiku-5.5"
OPUS_MODEL = "anthropic/claude-opus-5.5"
CHAT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"

# Model ids per chat arm and transport.
CHAT_MODELS = {
    "haiku": {"openrouter": HAIKU_MODEL, "claude-cli": "claude-haiku-5-5"},
    "opus": {"openrouter": OPUS_MODEL, "claude-cli": "claude-opus-5-5"},
}
CHAT_EST_COST = {"haiku": 0.01, "opus": 0.05}
TRANSPORTS = ("claude-cli", "openrouter")
DEFAULT_TRANSPORT = "claude-cli"
CLI_TIMEOUT_S = 180.0
CLI_CWD_ENV = "EVIDENCE_EVAL_CLAUDE_CWD"  # optional: an empty folder to run `claude` in

SYSTEM_PROMPT = (
    "You check one code review finding against the diff it was written about. "
    "You estimate the probability that the finding is supported. "
    + ANSWER_FORMAT
)


@dataclass
class Prediction:
    p: float
    cost_usd: float
    latency_s: float
    model: str
    raw: object
    error: str | None


def build_state(item: dict) -> dict:
    """The only thing a model sees. Never label, kind, rationale, tier or id."""
    finding = item.get("finding") or {}
    return {
        "diff": (item.get("diff") or "")[:MAX_DIFF_CHARS],
        "finding": {"claim": finding.get("claim"), "evidence": finding.get("evidence")},
    }


def jev_questions() -> dict:
    return {"supported": jev.noul(INSTRUCTIONS, true=TRUE_TEXT, false=FALSE_TEXT)}


def chat_prompt(state: dict) -> tuple:
    """(system, user) text for the chat arms. Both transports send exactly this."""
    user = "\n".join(
        [
            f"Question: {INSTRUCTIONS}",
            f"True: {TRUE_TEXT}",
            f"False: {FALSE_TEXT}",
            ANSWER_FORMAT,
            "",
            "State:",
            json.dumps(state, ensure_ascii=False),
        ]
    )
    return SYSTEM_PROMPT, user


def chat_messages(state: dict) -> list:
    system, user = chat_prompt(state)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_answer(text) -> float:
    """First json object in `text` carrying a numeric p_supported, clamped to [0, 1].

    Handles plain json, json inside prose, and fenced json. Raises ValueError
    when no such object exists.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty answer")
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            obj, _ = decoder.raw_decode(text, start)
        except ValueError:
            obj = None
        if isinstance(obj, dict) and "p_supported" in obj:
            value = obj["p_supported"]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"p_supported is not a finite number: {value!r}")
            return min(1.0, max(0.0, float(value)))
        start = text.find("{", start + 1)
    raise ValueError(f"no json object with p_supported in answer: {text[:200]!r}")


def _cost(usage) -> float:
    usd = (usage or {}).get("cost")
    return float(usd) if isinstance(usd, (int, float)) and not isinstance(usd, bool) else 0.0


# --- arms ------------------------------------------------------------------


class Arm:
    name = "arm"
    model = "none"
    est_cost_usd = 0.0  # prior per-call cost, used by the budget check before any call has landed

    def predict(self, item: dict) -> Prediction:
        t0 = time.monotonic()
        try:
            p, cost, raw = self._predict(item)
            return Prediction(p=p, cost_usd=cost, latency_s=time.monotonic() - t0, model=self.model, raw=raw, error=None)
        except (Exception, SystemExit) as exc:  # jev.api_key() calls sys.exit when no key is found
            cost = getattr(exc, "cost_usd", 0.0)
            raw = getattr(exc, "raw", None)
            msg = (str(exc) if isinstance(exc, ArmError) else f"{type(exc).__name__}: {exc}")[:500]
            return Prediction(p=0.5, cost_usd=cost, latency_s=time.monotonic() - t0, model=self.model, raw=raw, error=msg)

    def _predict(self, item: dict):
        raise NotImplementedError


class ArmError(RuntimeError):
    """A failure after the provider already billed us; carries cost and raw."""

    def __init__(self, msg: str, cost_usd: float = 0.0, raw=None):
        super().__init__(msg)
        self.cost_usd = cost_usd
        self.raw = raw


class AcceptAllArm(Arm):
    name = "accept_all"
    model = "none"

    def _predict(self, item):
        return 1.0, 0.0, None


class FakeArm(Arm):
    """Deterministic, no network. p comes from a hash of the item id."""

    name = "fake"
    model = "fake"

    def _predict(self, item):
        digest = hashlib.sha256(str(item.get("id", "")).encode()).digest()
        p = int.from_bytes(digest[:8], "big") / float(2**64 - 1)
        return p, 0.0, {"hash": digest[:4].hex()}


class JevArm(Arm):
    name = "jev"
    est_cost_usd = 0.002

    def __init__(self, model: str = JEV_MODEL):
        self.model = model

    def _predict(self, item):
        response = jev.ask(build_state(item), jev_questions(), model=self.model)
        cost = _cost(response.get("usage"))
        raw = {k: response.get(k) for k in ("model", "answers", "usage", "id", "provider")}
        try:
            p = response["answers"]["supported"]["noul"]
        except (KeyError, TypeError):
            raise ArmError("response has no answers.supported.noul", cost, raw) from None
        if isinstance(p, bool) or not isinstance(p, (int, float)) or not math.isfinite(p):
            raise ArmError(f"noul is not a finite number: {p!r}", cost, raw)
        return min(1.0, max(0.0, float(p))), cost, raw


def _post_chat(payload: dict, retries: int = 4, timeout: float = 120.0) -> dict:
    """POST to OpenRouter chat completions. Retries 429 and 5xx like jev.ask."""
    body = json.dumps(payload).encode()
    headers = {"Authorization": f"Bearer {jev.api_key()}", "Content-Type": "application/json"}
    delay = 1.0
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(CHAT_ENDPOINT, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, context=jev._ssl_context(), timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")
            if exc.code in (429, 500, 502, 503, 529) and attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"HTTP {exc.code}: {text[:500]}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"transport failure: {exc}") from None
    raise RuntimeError("unreachable")


class ChatArm(Arm):
    """Chat completion over OpenRouter. Temperature 0, max_tokens 300."""

    def __init__(self, name: str, model: str, est_cost_usd: float):
        self.name = name
        self.api_model = model
        self.model = f"openrouter:{model}"
        self.est_cost_usd = est_cost_usd

    def _predict(self, item):
        payload = {
            "model": self.api_model,
            "messages": chat_messages(build_state(item)),
            "temperature": 0,
            "max_tokens": 300,
            "usage": {"include": True},
        }
        response = _post_chat(payload)
        usage = response.get("usage") or {}
        cost = _cost(usage)
        try:
            content = response["choices"][0]["message"].get("content")
        except (KeyError, IndexError, TypeError, AttributeError):
            content = None
        raw = {"model": response.get("model"), "id": response.get("id"), "content": content, "usage": usage}
        if response.get("error"):
            raise ArmError(f"provider error: {str(response['error'])[:300]}", cost, raw)
        try:
            p = parse_answer(content)
        except ValueError as exc:
            raise ArmError(str(exc), cost, raw) from None
        return p, cost, raw


# --- claude CLI transport ----------------------------------------------------

_cli_cwd_lock = threading.Lock()
_cli_cwd: list = []


def _remove_if_empty(path: str) -> None:
    try:
        os.rmdir(path)
    except OSError:
        pass


def cli_cwd() -> str:
    """An empty folder for `claude` to run in, so no project context leaks in."""
    with _cli_cwd_lock:
        if not _cli_cwd:
            path = os.environ.get(CLI_CWD_ENV)
            if path:
                os.makedirs(path, exist_ok=True)
            else:
                path = tempfile.mkdtemp(prefix="evidence-eval-claude-")
                atexit.register(_remove_if_empty, path)
            _cli_cwd.append(path)
        path = _cli_cwd[0]
    if os.listdir(path):
        raise RuntimeError(f"claude cwd {path} is not empty")
    return path


def claude_cli_argv(model: str, system: str) -> list:
    """`claude -p` with no tools, settings, MCP servers, slash commands or session."""
    return [
        shutil.which("claude") or "claude",
        "-p",
        "--model", model,
        "--system-prompt", system,
        "--tools", "",
        "--setting-sources", "",
        "--strict-mcp-config",
        "--mcp-config", '{"mcpServers":{}}',
        "--disable-slash-commands",
        "--exclude-dynamic-system-prompt-sections",
        "--no-session-persistence",
        "--output-format", "json",
    ]


class ClaudeCliArm(Arm):
    """Chat arm over the local `claude -p`, one process per call, prompt on stdin.

    The CLI has no temperature or max_tokens flag, so neither is set: this
    transport runs at the CLI's default sampling. Cost is the CLI's
    total_cost_usd; a call killed at the timeout records est_cost_usd with
    error "timeout". Latency includes process start-up.
    """

    def __init__(self, name: str, cli_model: str, est_cost_usd: float):
        self.name = name
        self.cli_model = cli_model
        self.model = f"claude-cli:{cli_model}"
        self.est_cost_usd = est_cost_usd

    def _predict(self, item):
        system, user = chat_prompt(build_state(item))
        argv = claude_cli_argv(self.cli_model, system)
        try:
            proc = subprocess.run(
                argv, input=user, capture_output=True, text=True, timeout=CLI_TIMEOUT_S, cwd=cli_cwd()
            )
        except subprocess.TimeoutExpired:
            # The killed call may still be billed and its cost is unknown, so the
            # estimate counts toward the cap.
            raise ArmError("timeout", self.est_cost_usd) from None
        try:
            out = json.loads(proc.stdout)
        except (ValueError, TypeError):
            out = None
        if not isinstance(out, dict):
            tail = (proc.stderr or proc.stdout or "")[-300:]
            raise RuntimeError(f"claude CLI exit {proc.returncode}, output is not json: {tail!r}")
        cost = _cost({"cost": out.get("total_cost_usd")})
        raw = {k: out.get(k) for k in ("result", "is_error", "total_cost_usd", "usage", "duration_ms", "num_turns")}
        if proc.returncode != 0:
            raise ArmError(f"claude CLI exit {proc.returncode}: {str(out.get('result'))[:300]}", cost, raw)
        if out.get("is_error"):
            raise ArmError(f"claude CLI is_error: {str(out.get('result'))[:300]}", cost, raw)
        try:
            p = parse_answer(out.get("result"))
        except ValueError as exc:
            raise ArmError(str(exc), cost, raw) from None
        return p, cost, raw


def make_chat_arm(name: str, transport: str = DEFAULT_TRANSPORT) -> Arm:
    if transport not in TRANSPORTS:
        raise ValueError(f"unknown chat transport {transport!r}; choose from {', '.join(TRANSPORTS)}")
    cls = ClaudeCliArm if transport == "claude-cli" else ChatArm
    return cls(name, CHAT_MODELS[name][transport], est_cost_usd=CHAT_EST_COST[name])


ARMS: dict[str, Arm] = {
    "accept_all": AcceptAllArm(),
    "jev": JevArm(),
    "haiku": make_chat_arm("haiku"),
    "opus": make_chat_arm("opus"),
    "fake": FakeArm(),
}
