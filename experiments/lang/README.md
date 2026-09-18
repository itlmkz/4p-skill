# Does another language save tokens?

Short answer: no. Brevity saves tokens. Language mostly does not.

Reproduce with `python3 measure.py`.

## Method

One set of three findings, rendered several ways, sent to the Jev endpoint with an
identical one-line probe question. The question text is constant, so the
difference in `input_tokens` comes from the state. Jev's tokenizer is not the
pane models' tokenizer, so read these as direction and magnitude.

## Results

| Variant | Chars | Tokens | Tokens/char | vs verbose English |
| --- | ---: | ---: | ---: | ---: |
| English, verbose prose | 726 | 173 | 0.238 | 100% |
| English, STE100 | 304 | 87 | 0.286 | **50.3%** |
| Chinese, same content | 136 | 102 | 0.750 | 59.0% |
| Spanish | 327 | 105 | 0.321 | 60.7% |
| French | 345 | 111 | 0.322 | 64.2% |
| Japanese | 182 | 146 | 0.802 | 84.4% |
| JSON contract | 615 | 183 | 0.298 | **105.8%** |

## What the numbers say

**Brevity is the saving, not the language.** STE100 English halves the token
count. Chinese reaches only 59%, and it is measured against *bloated* English.

**Compare like with like.** The Chinese variant carries the same three short
findings as the STE100 English variant. At equal brevity, English wins: 87 tokens
against 102. Chinese is 3.2 times more tokens per character, and needs far fewer
characters, but the two effects do not quite cancel in its favour.

**Japanese is a clear loss.** 0.802 tokens per character and no character saving
worth having.

**The contract costs tokens, and that is the correct trade.** JSON is 5.8% more
than verbose prose, because field names repeat. It buys determinism, not economy.
If tokens were the only goal, terse prose would win and we would be back to
parsing prose, which was the problem the contract exists to solve. A compact wire
form (positional arrays, short keys) could recover the 5.8% later if it ever
matters. It would cost inspectability, so it is not worth it yet.

## The bug this experiment found

A language without spaces breaks a word-count rule. In Chinese, a 63-character
sentence counted as one "word" and passed the STE100 check. The validator
enforced nothing and said nothing.

Fixed in `panel/report.py`. Free text in Chinese, Japanese, or Korean now gets a
45-character budget per sentence instead of a 20-word budget, and CJK sentence
marks are recognised as boundaries. The 45 comes from this measurement: the
Chinese variant carried three sentences at roughly 45 characters each, matching
three 20-word English sentences.

## Tested against caveman

[JuliusBrussee/caveman](https://github.com/JuliusBrussee/caveman) is the popular
version of this idea. 106,424 stars, a proxy, and a skill that reaches 30+ agents.
It changed my mind about one thing and confirmed another.

Reproduce with `python3 caveman.py`. Every string is copied verbatim from their
`skills/caveman/SKILL.md` and `README.md`, so no translation is authored here.

### Their headline claim is real

| | Chars | Tokens | Their claim |
| --- | ---: | ---: | --- |
| Normal agent answer | 316 | 65 | 69 |
| Caveman answer | 88 | 21 | 19 |

That is a 3.1x reduction, and their published figures are honest. Verified.

### The wenyan claim does not survive measurement

Same content, four levels, their own strings:

| Level | Chars | Tokens | Tokens/char | vs best English |
| --- | ---: | ---: | ---: | --- |
| react, `full` | 88 | 21 | 0.239 | |
| react, `ultra` | 47 | **13** | 0.277 | best English |
| react, `wenyan-full` | 28 | 24 | 0.857 | **1.85x worse** |
| react, `wenyan-ultra` | 18 | 14 | 0.778 | 1.08x worse |
| pool, `ultra` | 57 | **10** | 0.175 | best English |
| pool, `wenyan-full` | 20 | 20 | 1.000 | **2.00x worse** |
| pool, `wenyan-ultra` | 14 | 14 | 1.000 | 1.40x worse |

The character reduction is real: 88 characters become 28, and 87 become 20. That
is the 80-90% their spec claims. But tokens per character rise from about 0.24 to
about 0.9, so the two effects almost exactly cancel and then lose.

### Their own spec says so

From `skills/caveman/SKILL.md`, on wenyan-full:

> 80-90% character reduction **chars, not tokens**

That is the same conclusion this experiment reached twice, written by the author
of the project that popularised the idea. Character compression and token
compression are different currencies. Classical Chinese optimises the wrong one.

### What caveman gets right, and what it means here

- **It mixes STE100 in by default.** "Clarity register: mix ASD-STE100 Simplified
  Technical English into caveman, always. One idea per sentence. Sentence short,
  target 20 words max." The most-starred project in this space independently
  arrived at the rule this repo enforces mechanically.
- **It measured, and then refused to claim what it could not measure.** `docs/HONEST-NUMBERS.md`
  states that output reduction is "Not published", that the skill's input
  reduction is 0%, and that earlier releases applied a fixed 65% output ratio
  "without a committed reviewed result". It lists cases where caveman is
  net-negative, including one at 4.3M tokens against 1M without. That is more
  honest than most benchmark pages.
- **It found that abbreviations and arrows save nothing.** Their spec bans
  `cfg`/`impl`/`req` and `→` because the tokenizer splits them the same as the
  full word. Measured, not assumed. This is the same discipline as the numbers
  above.

### Where this leaves 4p

Caveman's 3x win is on verbose prose. The 4p contract already removes verbose
prose from the panel, which is why the contract's own JSON costs 5.8% more than
terse English and is still the right choice. There is little left for the skill
to win on pane reports.

The part worth borrowing is the **proxy**, not the skill. It compresses what the
agent *reads*: test output, logs, diffs, search results. Nothing in 4p addresses
that, and it is where a pane's token bill actually goes.

## Consequence for the main pane

ASD-STE100 is an English standard. It does not apply to French or Chinese. If the
coordinator answers the user in another language, the STE100 rule no longer
means anything, and the validator's sentence-length check has no equivalent
standard to appeal to.

So "keep the main pane in the user's language" and "STE100" cannot both hold,
unless the user's language is English. That is a decision for the owner, not for
this tool.
