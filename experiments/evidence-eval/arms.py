#!/usr/bin/env python3
"""The four arms of the evidence-check eval, behind one interface.

Stdlib only. Every arm sees the same state and answers the same question
(PREREG.md, "Shared state and question"), and returns a Prediction whose `p` is
its probability that the finding is supported.

    from arms import ARMS
    pred = ARMS["jev"].predict(item)

An arm never raises. A failure comes back as p=0.5 with `error` set, which is
how PREREG.md scores an unanswered item.

Arms: accept_all, cite_script, jev, haiku, opus, plus `fake` (no network, for
dry runs). Model arms take a prompt version from PROMPTS: v1 (PREREG.md) or v2
(PREREG-v2.md, v1 plus the citation rule).
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
import re
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

# --- prompt versions. v1 is PREREG.md; v2 adds the rule from PREREG-v2.md. ---

CITATION_RULE = (
    "A citation supports the claim only when the cited file is in the diff and the "
    "cited line is within 5 lines of the code that supports the claim. Line numbers "
    "count in the new file for added and unchanged lines, and in the old file for "
    "removed lines."
)
PROMPTS = {
    "v1": {"rule": None},
    "v2": {"rule": CITATION_RULE},
}
DEFAULT_PROMPT = "v1"


def _rule(prompt: str):
    if prompt not in PROMPTS:
        raise ValueError(f"unknown prompt version {prompt!r}; choose from {', '.join(PROMPTS)}")
    return PROMPTS[prompt]["rule"]


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


def jev_questions(prompt: str = DEFAULT_PROMPT) -> dict:
    """v2 appends the rule to the noul instructions."""
    rule = _rule(prompt)
    instructions = f"{INSTRUCTIONS} {rule}" if rule else INSTRUCTIONS
    return {"supported": jev.noul(instructions, true=TRUE_TEXT, false=FALSE_TEXT)}


def chat_prompt(state: dict, prompt: str = DEFAULT_PROMPT) -> tuple:
    """(system, user) text for the chat arms. Both transports send exactly this.
    v2 adds the rule as one more line of the user message."""
    rule = _rule(prompt)
    lines = [
        f"Question: {INSTRUCTIONS}",
        f"True: {TRUE_TEXT}",
        f"False: {FALSE_TEXT}",
    ]
    if rule:
        lines.append(rule)
    lines += [ANSWER_FORMAT, "", "State:", json.dumps(state, ensure_ascii=False)]
    return SYSTEM_PROMPT, "\n".join(lines)


def chat_messages(state: dict, prompt: str = DEFAULT_PROMPT) -> list:
    system, user = chat_prompt(state, prompt)
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
    prompt = DEFAULT_PROMPT  # prompt version; only model arms read it
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

    def __init__(self, model: str = JEV_MODEL, prompt: str = DEFAULT_PROMPT):
        _rule(prompt)
        self.model = model
        self.prompt = prompt

    def _predict(self, item):
        response = jev.ask(build_state(item), jev_questions(self.prompt), model=self.model)
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

    def __init__(self, name: str, model: str, est_cost_usd: float, prompt: str = DEFAULT_PROMPT):
        _rule(prompt)
        self.name = name
        self.prompt = prompt
        self.api_model = model
        self.model = f"openrouter:{model}"
        self.est_cost_usd = est_cost_usd

    def _predict(self, item):
        payload = {
            "model": self.api_model,
            "messages": chat_messages(build_state(item), self.prompt),
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

    def __init__(self, name: str, cli_model: str, est_cost_usd: float, prompt: str = DEFAULT_PROMPT):
        _rule(prompt)
        self.name = name
        self.prompt = prompt
        self.cli_model = cli_model
        self.model = f"claude-cli:{cli_model}"
        self.est_cost_usd = est_cost_usd

    def _predict(self, item):
        system, user = chat_prompt(build_state(item), self.prompt)
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


def make_chat_arm(name: str, transport: str = DEFAULT_TRANSPORT, prompt: str = DEFAULT_PROMPT) -> Arm:
    if transport not in TRANSPORTS:
        raise ValueError(f"unknown chat transport {transport!r}; choose from {', '.join(TRANSPORTS)}")
    cls = ClaudeCliArm if transport == "claude-cli" else ChatArm
    return cls(name, CHAT_MODELS[name][transport], est_cost_usd=CHAT_EST_COST[name], prompt=prompt)


# --- cite_script: the citation rule as code, no model ---------------------------

CITE_PASS, CITE_FAIL = 0.95, 0.05
CITE_WINDOW = 5
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _clean_path(path: str):
    path = path.strip().split("\t")[0]
    if path == "/dev/null":
        return None
    if path[:2] in ("a/", "b/"):
        path = path[2:]
    return path[2:] if path.startswith("./") else path


def changed_lines(diff: str) -> dict:
    """path -> line numbers of added lines (new file) and removed lines (old file).

    Line numbers come from hunk headers. A file is keyed under both its old and
    new path, so a rename matches either name. Only "\n" ends a line (a trailing
    "\r" is dropped): str.splitlines would also split on form feeds and other
    separators inside a line and shift every number after them. Inside a hunk,
    any line that is not "+", "-" or "\\" counts as context, as in
    build_dataset.parse_diff, so labels and this check number lines alike.
    """
    files: dict = {}
    keys: list = []
    old_ln = new_ln = old_left = new_left = 0
    lines = (diff or "").split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # the final "\n" ends the last line; it does not start a new one
    for line in lines:
        if line.endswith("\r"):
            line = line[:-1]
        in_hunk = old_left > 0 or new_left > 0
        if line.startswith("diff --git "):
            old_left = new_left = 0
            parts = line.split(" ")
            keys = [p for p in (_clean_path(x) for x in parts[2:4]) if p] if len(parts) >= 4 else []
            for key in keys:
                files.setdefault(key, set())
            continue
        if not in_hunk and line.startswith("--- "):
            old = _clean_path(line[4:])
            keys = [old] if old else []
            continue
        if not in_hunk and line.startswith("+++ "):
            new = _clean_path(line[4:])
            if new and new not in keys:
                keys.append(new)
            for key in keys:
                files.setdefault(key, set())
            continue
        match = _HUNK.match(line)
        if match:
            old_ln, new_ln = int(match.group(1)), int(match.group(3))
            old_left = int(match.group(2)) if match.group(2) is not None else 1
            new_left = int(match.group(4)) if match.group(4) is not None else 1
            continue
        if not in_hunk:
            continue
        if line.startswith("+"):
            for key in keys:
                files[key].add(new_ln)
            new_ln += 1
            new_left -= 1
        elif line.startswith("-"):
            for key in keys:
                files[key].add(old_ln)
            old_ln += 1
            old_left -= 1
        elif not line.startswith("\\"):  # "\ No newline at end of file" is skipped
            old_ln += 1
            new_ln += 1
            old_left -= 1
            new_left -= 1
    return files


def cite_check(state: dict) -> tuple:
    """(passes, detail). Passes when the cited file is in the diff and the cited
    line is within CITE_WINDOW lines of a changed line of that file, on either side."""
    evidence = (state.get("finding") or {}).get("evidence")
    if not isinstance(evidence, dict):
        return False, {"reason": "no evidence"}
    # The cited path is taken as written: only a leading "./" goes. A leading a/ or
    # b/ is a real folder here, not a diff prefix.
    path = str(evidence.get("file") or "")
    if path.startswith("./"):
        path = path[2:]
    line = evidence.get("line")
    if not isinstance(line, int) or isinstance(line, bool):
        return False, {"reason": "cited line is not an integer", "file": path}
    files = changed_lines(state.get("diff") or "")
    if not path or path not in files:
        return False, {"reason": "file not in diff", "file": path}
    nearest = min((abs(line - n) for n in files[path]), default=None)
    if nearest is None or nearest > CITE_WINDOW:
        return False, {"reason": "line too far", "file": path, "nearest": nearest}
    return True, {"file": path, "nearest": nearest}


class CiteScriptArm(Arm):
    """Deterministic citation check, no network, cost 0 (PREREG-v2.md, Arms)."""

    name = "cite_script"
    model = "cite_script"

    def _predict(self, item):
        passes, detail = cite_check(build_state(item))
        return (CITE_PASS if passes else CITE_FAIL), 0.0, detail


ARMS: dict[str, Arm] = {
    "accept_all": AcceptAllArm(),
    "cite_script": CiteScriptArm(),
    "jev": JevArm(),
    "haiku": make_chat_arm("haiku"),
    "opus": make_chat_arm("opus"),
    "fake": FakeArm(),
}
