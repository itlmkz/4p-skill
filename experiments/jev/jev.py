#!/usr/bin/env python3
"""Minimal TypeSafe Jev client over OpenRouter's decisions endpoint.

Stdlib only. No typesafe-sdk, no requests.

    POST https://openrouter.ai/api/alpha/decisions
    {"model": "...", "state": ..., "questions": {...}}

Keys are read from OPENROUTER_API_KEY, else from ~/.pi/agent/auth.json.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_MODEL = "typesafe/jev-1.13"  # verified working; alias form is "~typesafe/jev-latest"

# Homebrew Python ships no CA bundle and certifi is optional here.
_CERT_CANDIDATES = (
    os.environ.get("SSL_CERT_FILE"),
    "/Users/mm/.homebrew/etc/ca-certificates/cert.pem",
    "/etc/ssl/cert.pem",
    "/etc/pki/tls/certs/ca-bundle.crt",
)


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi  # noqa: PLC0415

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    for path in _CERT_CANDIDATES:
        if path and os.path.exists(path):
            return ssl.create_default_context(cafile=path)
    return ssl.create_default_context()


def api_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        return key
    auth = os.path.expanduser("~/.pi/agent/auth.json")
    try:
        with open(auth) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"no key: OPENROUTER_API_KEY unset and {auth} unreadable ({exc})")
    entry = data.get("openrouter")
    found = entry.get("key") if isinstance(entry, dict) else None
    if not found:
        sys.exit(f"no key: no openrouter.key in {auth}")
    return found


# --- question constructors -------------------------------------------------


def noul(instructions, true=None, false=None) -> dict:
    """Yes/no question. Answer comes back as a probability between 0 and 1."""
    q: dict = {"type": "noul", "instructions": instructions}
    if true is not None or false is not None:
        q["criteria"] = {k: v for k, v in (("true", true), ("false", false)) if v is not None}
    return q


def choice(instructions, criteria: dict) -> dict:
    """Pick one option. Answer comes back with probabilities plus confidence."""
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


def score(instructions, criteria: list) -> dict:
    """Rate along an ordered rubric of at least two levels."""
    if len(criteria) < 2:
        raise ValueError("score needs at least two levels")
    return {"type": "score", "instructions": instructions, "criteria": criteria}


# --- transport -------------------------------------------------------------


def ask(
    state,
    questions: dict,
    model: str = DEFAULT_MODEL,
    retries: int = 4,
    timeout: float = 60.0,
) -> dict:
    """One batched request. Every question rides it, so they are evaluated in parallel.

    Returns the raw response: {"model", "answers", "usage", "id", "provider"}.
    """
    payload = json.dumps({"model": model, "state": state, "questions": questions}).encode()
    headers = {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
    }
    delay = 1.0
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(ENDPOINT, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, context=_ssl_context(), timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code in (429, 500, 502, 503, 529) and attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"HTTP {exc.code}: {body[:500]}") from None
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < retries:
                time.sleep(delay)
                delay *= 2
                continue
            raise RuntimeError(f"transport failure: {exc}") from None
    raise RuntimeError("unreachable")


def cost_of(response: dict) -> str:
    usage = response.get("usage") or {}
    usd = usage.get("cost")
    tok = f"{usage.get('input_tokens', '?')}in/{usage.get('output_tokens', '?')}out"
    return f"{tok} ${usd:.8f}" if isinstance(usd, (int, float)) else tok
