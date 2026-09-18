#!/usr/bin/env python3
"""Measure whether another language saves tokens, and what it costs.

Uses the Jev endpoint as a token counter: the same one-line probe question is
sent with each variant, so the difference in input_tokens is attributable to the
state alone.

    python3 measure.py

Caveat: Jev's tokenizer is not the pane models' tokenizer. Treat the numbers as
direction and magnitude, not as exact counts for pi, Claude, or Codex.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "jev"))
from jev import ask, cost_of, noul  # noqa: E402

PROBE = {"probe": noul("Does this text describe a problem?")}

# One set of findings, rendered several ways. Same information in each.
EN_VERBOSE = """\
Reviewer findings on the session refresh change. First, the effect never runs a
second time after the first render, because the useRef guard is set to true and is
never reset, which means that a token that expires during an active session will
never be refreshed while the user continues to work. This is blocking. Second, the
call to refreshSession is not awaited and its result is never checked, so a failure
is silently ignored apart from the redirect. This is a should-fix. Third, setting
window.location.href discards any in-flight form state, which is a worse outcome
for the user than the 401 status that the code is trying to handle. This is also
blocking. References: src/auth/gates.tsx line 41, line 44, and line 45.\
"""

EN_STE100 = """\
The guard stops all later refreshes. A token that expires mid-session never
refreshes. Blocking, src/auth/gates.tsx:41.
The refresh call is not awaited. A failure is ignored. Should-fix, src/auth/gates.tsx:44.
The redirect discards form state. That is worse than the 401. Blocking, src/auth/gates.tsx:45.\
"""

ZH = """\
守卫阻止全部后续刷新。会话中过期的令牌不会刷新。阻断，src/auth/gates.tsx:41。
刷新调用未等待。失败被忽略。应修复，src/auth/gates.tsx:44。
重定向丢弃表单状态。这比 401 更糟。阻断，src/auth/gates.tsx:45。\
"""

JA = """\
ガードは以降の更新をすべて止めます。セッション中に期限切れのトークンは更新されません。ブロック、src/auth/gates.tsx:41。
更新呼び出しを待機していません。失敗は無視されます。要修正、src/auth/gates.tsx:44。
リダイレクトはフォーム状態を破棄します。401 より悪いです。ブロック、src/auth/gates.tsx:45。\
"""

FR = """\
Le garde bloque tous les rafraichissements suivants. Un jeton qui expire en
session ne se rafraichit jamais. Bloquant, src/auth/gates.tsx:41.
L'appel de rafraichissement n'est pas attendu. Un echec est ignore. A corriger,
src/auth/gates.tsx:44.
La redirection detruit l'etat du formulaire. C'est pire que le 401. Bloquant,
src/auth/gates.tsx:45.\
"""

ES = """\
El guard bloquea todos los refrescos siguientes. Un token que caduca en sesion
nunca se refresca. Bloqueante, src/auth/gates.tsx:41.
La llamada de refresco no se espera. Un fallo se ignora. Corregir,
src/auth/gates.tsx:44.
La redireccion descarta el estado del formulario. Es peor que el 401.
Bloqueante, src/auth/gates.tsx:45.\
"""

CONTRACT_JSON = """\
{"schema":"4p/report@1","role":"reviewer","verdict":"fix_first","confidence":0.8,
"findings":[
{"id":"r1","severity":"blocking","claim":"The guard stops all later refreshes.",
"evidence":{"kind":"file","file":"src/auth/gates.tsx","line":41},"blocks":true},
{"id":"r2","severity":"should-fix","claim":"The refresh call is not awaited.",
"evidence":{"kind":"file","file":"src/auth/gates.tsx","line":44},"blocks":false},
{"id":"r3","severity":"blocking","claim":"The redirect discards form state.",
"evidence":{"kind":"file","file":"src/auth/gates.tsx","line":45},"blocks":true}],
"next_action":"Fix the guard first."}\
"""

VARIANTS = [
    ("en verbose prose", EN_VERBOSE),
    ("en ste100", EN_STE100),
    ("zh simplified chinese", ZH),
    ("ja japanese", JA),
    ("fr french", FR),
    ("es spanish", ES),
    ("json contract", CONTRACT_JSON),
]


def main() -> int:
    print(f"probe: {' | '.join(PROBE)}\n")
    print(f"{'variant':24} {'chars':>7} {'tokens':>7} {'tok/char':>9}  {'cost':>12}")
    print("-" * 64)

    baseline = ask("x", PROBE)
    base_tokens = baseline["usage"]["input_tokens"]
    results = {}

    for label, text in VARIANTS:
        resp = ask(text, PROBE)
        tokens = resp["usage"]["input_tokens"] - base_tokens
        results[label] = tokens
        ratio = tokens / max(len(text), 1)
        print(f"{label:24} {len(text):>7} {tokens:>7} {ratio:>9.3f}  {cost_of(resp):>12}")

    print(f"\nprobe overhead subtracted: {base_tokens} tokens\n")

    en = results["en verbose prose"]
    print("against verbose English prose (100%):")
    for label, _ in VARIANTS:
        if label == "en verbose prose":
            continue
        pct = results[label] / en * 100
        print(f"  {label:24} {results[label]:>6} tokens  {pct:5.1f}%")

    print(
        "\nNote: the question text is identical in every call, so the differences\n"
        "come from the state. Jev's tokenizer is not the pane models' tokenizer."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
