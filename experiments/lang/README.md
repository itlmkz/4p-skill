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

## Consequence for the main pane

ASD-STE100 is an English standard. It does not apply to French or Chinese. If the
coordinator answers the user in another language, the STE100 rule no longer
means anything, and the validator's sentence-length check has no equivalent
standard to appeal to.

So "keep the main pane in the user's language" and "STE100" cannot both hold,
unless the user's language is English. That is a decision for the owner, not for
this tool.
