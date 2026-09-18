#!/usr/bin/env python3
"""Measure caveman's published examples with a real tokenizer.

Uses the exact strings from JuliusBrussee/caveman, so no translation is authored
here. The claim under test is whether classical Chinese (wenyan) compresses
*tokens*, or only characters.

    python3 caveman.py

Caveat: Jev's tokenizer is not Claude's or GPT's. Absolute counts will differ from
caveman's own figures. Ratios are what this measures.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "jev"))
from jev import ask, noul  # noqa: E402

PROBE = {"probe": noul("Is this a coding answer?")}

# --- copied verbatim from skills/caveman/SKILL.md ---------------------------

REACT = [
    ("lite", "Your component re-renders because you create a new object reference each render. Wrap it in `useMemo`."),
    ("full", "New object ref each render. Inline object prop = new ref = re-render. Wrap in `useMemo`."),
    ("ultra", "Inline obj prop, new ref, re-render. `useMemo`."),
    ("wenyan-lite", "組件頻重繪，以每繪新生對象參照故。以 useMemo 包之。"),
    ("wenyan-full", "每繪新生對象參照，故重繪；以 useMemo 包之則免。"),
    ("wenyan-ultra", "新參照則重繪。useMemo 包之。"),
]

POOL = [
    ("full", "Pool reuse open DB connections. No new connection per request. Skip handshake overhead."),
    ("ultra", "Pool reuse open DB connections. No per-request handshake."),
    ("wenyan-full", "池蓄已開之連，不逐請而新開，省握手之費。"),
    ("wenyan-ultra", "池蓄連，免逐請新開，省握手。"),
]

# --- copied verbatim from README.md, the "See it" table ---------------------

README_CLAIM = [
    ("normal (claim: 69 tok)", "The reason your React component is re-rendering is likely because you're "
     "creating a new object reference on each render cycle. When you pass an inline object as a prop, "
     "React's shallow comparison sees it as a different object every time, which triggers a re-render. "
     "I'd recommend using useMemo to memoize the object."),
    ("caveman (claim: 19 tok)", "New object ref each render. Inline object prop = new ref = re-render. Wrap in `useMemo`."),
]


def count(text: str, base: int) -> tuple[int, int]:
    resp = ask(text, PROBE)
    return resp["usage"]["input_tokens"] - base, len(text)


def group(title: str, rows: list[tuple[str, str]], base: int) -> dict[str, int]:
    print(f"\n{title}")
    print(f"  {'level':16} {'chars':>6} {'tokens':>7} {'tok/char':>9}  vs full")
    print("  " + "-" * 52)
    out: dict[str, int] = {}
    ref = None
    for label, text in rows:
        tokens, chars = count(text, base)
        out[label] = tokens
        if label == "full":
            ref = tokens
        ratio = f"{tokens / ref:5.2f}x" if ref else ""
        print(f"  {label:16} {chars:>6} {tokens:>7} {tokens / max(chars, 1):>9.3f}  {ratio}")
    return out


def main() -> int:
    base = ask("x", PROBE)["usage"]["input_tokens"]
    print(f"probe overhead subtracted from every count: {base} tokens")

    print("\n" + "=" * 60)
    print("README headline claim")
    print("=" * 60)
    for label, text in README_CLAIM:
        tokens, chars = count(text, base)
        print(f"  {label:24} {chars:>5} chars  {tokens:>4} tokens")

    react = group("React example (caveman's own strings)", REACT, base)
    pool = group("DB pooling example", POOL, base)

    print("\n" + "=" * 60)
    print("Does wenyan beat telegraphic English, in tokens?")
    print("=" * 60)
    for name, data in (("react", react), ("pool", pool)):
        best_en = min(data["full"], data["ultra"])
        print(f"\n  {name}:")
        print(f"    best English level    {best_en:>4} tokens")
        print(f"    wenyan-lite           {data.get('wenyan-lite', float('nan')):>4}")
        print(f"    wenyan-full           {data['wenyan-full']:>4} tokens"
              f"   {'BEATS English' if data['wenyan-full'] < best_en else 'loses to English'}"
              f"  ({data['wenyan-full'] / best_en:.2f}x)")
        print(f"    wenyan-ultra          {data['wenyan-ultra']:>4} tokens"
              f"   {'BEATS English' if data['wenyan-ultra'] < best_en else 'loses to English'}"
              f"  ({data['wenyan-ultra'] / best_en:.2f}x)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
