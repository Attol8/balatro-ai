# Offline strategy learning

The library covers 92 examples across 56 strategy families, including ones
never encountered in either recorded run. 17 are recorded and 75 constructed. The player retrieves at most three from
[`knowledge/decisions.json`](../balatro_ai/knowledge/decisions.json). Each example
contains a situation, two options, a lesson, a condition that could reverse the
choice, and source references. This is external knowledge for Astra low; no
model weights are trained and no extra model call is made during retrieval.

## What counts as evidence

- **Recorded:** a decision opportunity actually visible in one of our saved
  runs. The counterfactual recommendation is reviewed judgment, not an observed
  winning alternative. `evidence:05:95` means zero-based JSONL event 95 in
  segment 05 of seed 2K9H9HN, the first run. References to any later run name it
  first: `evidence:TAF7DNTX:04:948` is event 948 in segment 04 of the headless
  Ante 13 run. Where the scorer can check a recorded claim, the number in the
  lesson is the scorer's own output on that recorded observation.
- **Constructed:** a deliberately specified mechanics exercise. It does not
  claim that the entire build occurred in a game or can reliably be assembled.
- **Game references:** `game:card.lua:N`, `game:game.lua:N` and `game:tag.lua:N`
  refer to lines of
  the locally installed Balatro source used for verification. These references
  support mechanics, not the strategic recommendation. Game source is not
  distributed. Recheck them when the game version changes; the two snapshots
  recorded below do not share line numbering, so a reference is only meaningful
  against the snapshot the entry was written from.

The original trace is immutable. New lessons are stored separately, with no
future seed routes passed to the player. The complete corpus is inspectable
JSON; gameplay receives only situation/lesson/reversal text and an example ID.

## Tags, vouchers and consumables

Tag, voucher, Tarot and Spectral coverage was added as rule-derived material and
is therefore all `provenance: constructed`. None of it is recorded evidence: the
saved run skipped a blind once in 32 blind selections, so there is no observed
decision to counterfactually review for any tag. Each statement was read out of
the currently installed game source rather than a guide, and the entries stay
conditional, naming the case where the option is wrong as well as the case where
it is right.

Two of those tag entries now have recorded counterparts. The headless TAF7DNTX
run skipped four of its 34 blind selections, so `investment-tag-skip-recorded`
and `negative-tag-slot-recorded` cite observed skips and their observed payouts
(exactly $25 at 00:66, and a free Negative Steel Joker at 04:176) rather than
rule text. The constructed entries stay; they cover tags that run never saw.

Thirty-three entries were added: one general skip-timing lesson plus seven named
tags (Negative, Rare, Charm, Double, Investment, Voucher, Coupon); seven Tarots
(Death, Strength, The Hanged Man, Judgement, The Fool, The Hermit, Temperance);
seven Spectrals (Ankh, Cryptid, The Soul, Black Hole, Wraith, Immolate,
Ectoplasm); and eleven voucher lessons covering the scaling, shop, economy,
capacity and boss-reroll groups.

Tag retrieval is a new fact source. `retrieve_examples` now slugifies
`PublicBlind.tag_name` into a `tag_*` key, but only for a small or big blind whose
status is still `SELECT`, because that is the only state in which skipping can
claim the tag. Two displayed names do not slugify to the game's own key, so
Holographic Tag and D6 Tag are mapped explicitly. The tag key counts as an offer
for ranking, the same way a shop item does. Blind tags are still public state; no
hidden or future tag is read.

The economy claims that appear in the prompt (the interest steps and caps, the
Reroll Surplus break-even) and the edition values have exercises in
`tests/test_strategy_exercises.py`. Claims that the scorer cannot check, such as
what a tag places in the next shop, are asserted only as text and carry a source
reference instead.

## Numerical exercises

`tests/test_strategy_exercises.py` checks exact scoring arithmetic independently
of the lesson wording. For a played 2, High Card base chips 5, no other Jokers,
and n non-debuffed held Steel cards:

- Mime: `7 × base_mult × 1.5^(2n)`.
- Holographic Cloud 9: `7 × (base_mult × 1.5^n + 10)`.

The grid covers n=0..4 and base Mult 1/50. At Mult 1, Mime first wins at four
Steel; at Mult 50, it first wins at one. Cloud 9's income, purchase cost, future
draws and other Jokers are excluded. These thresholds must not be applied to
a different build without recomputing it.

The TAF7DNTX engine has its own group. With Photograph, Blueprint, Hanging Chad
and Brainstorm in the run's final order, Blueprint copies Chad and Brainstorm
copies Photograph, so the first played card scores five times and every effect
on it applies five times: a Glass face lead scores `(5 + 5x10) x 8^5`, a plain
face `x 4^5`, a Glass Ten `x 2^5`. Disabling Photograph removes the Brainstorm
copy with it, which is why one Crimson Heart disable costs 32x twice over.
Steel Joker is checked as X(1 + steel/5) over the whole deck at 0, 2, 4 and 9
Steel cards, and two exercises replay the recorded observations themselves:
04:948 scores 764,127 as played against 1,222,760,448 for a Glass-inclusive
ordering, and 04:290 scores 180,442 with Photograph disabled against 11,548,293
intact. The Tooth's $1 per card and the run's forgone Seed Money interest are
arithmetic checks over the recorded holdings.

Five further exercises verify a scoring face under Photograph/Chad (three X2
applications and repeated card chips), and Blueprint copying Mime versus Baron
with a red-seal Steel King (eight versus nine factors of 1.5), Fibonacci/Hack,
Triboulet/Sock and Buskin, and Four Fingers/Shortcut gapped Straights. These verify the
covered scorer mechanics; they do not simulate a whole run.

Run all checks offline:

```sh
python -m pytest -q
```

## Retrieval

Matching uses the current phase, visible owned/offered items, the tag on a
still-selectable small or big blind, and public hand/deck features. Every required feature must match. Offered items receive
priority, then more specific contexts; at most one example per family is sent.
No network, embedding service, model call, hidden card identity or seed lookup
is used. A feature match is not a purchase recommendation or proof of legality.
The coach must still check draw reliability, price, capacity and survival.

This deliberate bound adds some prompt text but avoids sending the entire
library. No live latency or playing-strength improvement has been measured.

## Online research and its limits

The [Baron/Mime guide](https://balatrolab.com/en/guides/baron-mime-steel-kings)
reinforces that a held-card engine needs enough suitable cards and a way to keep
them held. We verify trigger arithmetic locally rather than trusting a guide's
headline combination.

The public [Balatro Bench lessons journal](https://github.com/Michael-Andrzejewski/balatro-bench/blob/master/bench-lessons.md)
provides another useful failure example: owning Baron did not itself establish
a reliable held-King engine. Its advice about preserving resources is a useful
hypothesis, but seed-specific routes and fixed timing prescriptions are not
imported as universal rules. These external observations inform review; they
are not treated as our own validated trajectories.

[Balatro University](https://www.youtube.com/watch?v=ooudv0Yh--g) is a candidate
for future expert decision extraction. No bulk video/transcript ingestion has
been performed. [Immolate](https://github.com/SpectralPack/Immolate) could find
seeds for targeted practice later, but it is not installed or used here.

## Adding knowledge without accumulating bad advice

Add a distinct decision with explicit prerequisites and a reversal condition.
Record whether its source is an observed decision or a constructed exercise.
Check card rules against the installed game; add numerical regression coverage
when recommending a precise multiplier or score comparison. Test retrieval on
both matching and misleading contexts. Review conflicting lessons together.
Keep losses and unavailable alternatives visible in evidence.

A future authorized evaluation should use unfamiliar seeds and measure survival,
peak score, spending and model calls. A better exercise score or a familiar-seed
result is not sufficient evidence of general improvement. No new game was run
while building this library.

## Scorer coverage is narrower than strategy coverage

| Mechanism | Current numerical boundary |
|---|---|
| Four Fingers / Shortcut | Hand classification is covered. |
| Fibonacci / Hack, Triboulet / Sock | Deterministic examples have exact regression checks. |
| Runner / Castle / Yorick / Hit the Road / Madness | Public current counters are used; future growth, destruction and draw outcomes are not simulated. |
| Bloodstone | Expected value rather than exact random outcome. |
| Glass / Lucky | The X2 and the chip effects score, but the 1-in-4 Glass break and Lucky's random Mult are never rolled, so a Glass-lead engine's own attrition is invisible to any single-hand estimate. |
| Smeared | Flush classification covered; some Joker suit interactions are incomplete. |
| Vampire / Midas | Same-play enhancement stripping/conversion and resulting growth are incomplete. |
| Obelisk | Current multiplier is read; same-play history-dependent growth/reset is incomplete. |
| Observatory / Perkeo | Currently held matching planets contribute; future generated consumables are not forecast. |
| Burnt Joker and deck edits | Observed results feed future packets; action outcomes are not generally simulated. |

The prompt exposes these limitations. Broad strategy knowledge is useful without
pretending that every numerical comparison is already exact. This change does
not add unverified numerical implementations for every new family.

Source snapshots used for mechanics review (SHA256, not distributed). The
original 48 entries were verified against the first snapshot; the tag, voucher,
Tarot and Spectral entries were verified against the second, which has different
line numbering:

- `card.lua`: `5073d834e08119da9516f1795a8c3d93110669aeb409c29ad1b308e0eb0be453`
- `game.lua`: `bbc67bd3fbadd1ea3f3f0aba07ef8596118d89ff1e9758718f9e17c07a96e912`
- `card.lua`: `77738b7ddb02576fa525410e79218f44fb744b0e365b0fb3a45f67809ac15677`
- `game.lua`: `f684681dd67ecf4ecb66857b129aa56b8bb8dae0f34745f73bb553c7eb84953e`
- `tag.lua`: `7080dfcb080285fd6b18ed9c750401c0e0aec7a569226a29f12109ed3aefe58a`

Offline retrieval check across the 766 recorded coach requests in both saved
runs: 0.162 seconds total, 0.21 ms per decision, 697 matched; maximum 1561 bytes
of example text, average 1195 when matched.
This measures local retrieval only, not Codex inference or gameplay performance.
