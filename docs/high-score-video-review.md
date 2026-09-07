# High-score video comparison

Reviewed 7 September 2026. The main opportunity is to optimize the resources produced by a round and the engine's growth across rounds, alongside immediate scoring. Extending runner limits would not have rescued the reviewed completed losses.

## Evidence and limits

Analyzed timestamped automatic transcripts from five videos: three gameplay trajectories (one spans two videos) and one methods lecture. This is transcript analysis, not frame-by-frame viewing; exact displayed scores and every intervening action were not visually verified. Captions sometimes mistranscribe Joker names. Recommendations below are hypotheses grounded in decisions and current code, not demonstrated score improvements.

### 1. Balatro University: beginner high-score run, part 1

[Beginner's Guide to High Scores and High Antes](https://www.youtube.com/watch?v=-Fnach4gIN8).

- [66:24](https://www.youtube.com/watch?v=-Fnach4gIN8&t=3984s): prefers Gold to Steel while existing scoring suffices.
- [78:49](https://www.youtube.com/watch?v=-Fnach4gIN8&t=4729s): copies Purple seals and uses spare hands to draw, preserving discards for resource generation.
- [133:17](https://www.youtube.com/watch?v=-Fnach4gIN8&t=7997s): counts remaining cards against available draws to establish access to the deck.
- [154:22](https://www.youtube.com/watch?v=-Fnach4gIN8&t=9262s): warns against replacing income with scoring too early; Purple seals can provide generation without occupying Joker slots.

Lesson: winning the round is a constraint; income and deck construction remain objectives once survival is secure.

### 2. Balatro University: same run, endless phase

[Make YOUR number go big](https://www.youtube.com/watch?v=TNuuuu6RTtU). The closing commentary reports Ante 18 on Red Deck. This is a more useful qualitative comparison than a filtered record attempt, though it is not a controlled benchmark against our seeds.

- [45:16](https://www.youtube.com/watch?v=TNuuuu6RTtU&t=2716s): compares Business Card income with copied Faceless income, accounting for cards needed afterward to score.
- [69:05](https://www.youtube.com/watch?v=TNuuuu6RTtU&t=4145s): keeps enough Kings to discard for Mail-In Rebate and still play five; deck thinning has a functional lower bound.
- [106:46](https://www.youtube.com/watch?v=TNuuuu6RTtU&t=6406s): shifts duplication from Purple generation toward Red scoring cards and Glass stock.
- [107:54](https://www.youtube.com/watch?v=TNuuuu6RTtU&t=6474s): compares an approximately 800-fold requirement increase with a specific additional-retrigger route worth 2^10 = 1,024.
- [110:45](https://www.youtube.com/watch?v=TNuuuu6RTtU&t=6645s): counts activations and multiplier effects to allocate copiers.

Lesson: switch investments based on the next scoring requirement, draw reliability and remaining generation capacity.

### 3. Balatro University: record-attempt setup

[A Guide to the Highest Score ever recorded — Part 1](https://www.youtube.com/watch?v=hFnw0vkorrY). This installment ends around Ante 8; it does not establish the completed record. Commentary describes about 7.5 hours of resets yielding two early-Perkeo starts. Treat the setup as selected, not representative of an ordinary run.

- [08:00](https://www.youtube.com/watch?v=hFnw0vkorrY&t=480s): Sixth Sense serves a temporary role finding Cryptid, then becomes expendable.
- [23:00](https://www.youtube.com/watch?v=hFnw0vkorrY&t=1380s): distinguishes spending a Cryptid to improve generation from retaining a copy for Perkeo.
- [35:40](https://www.youtube.com/watch?v=hFnw0vkorrY&t=2140s): changes copier targets between scoring, income, end-of-round effects and leaving the shop.
- [77:40](https://www.youtube.com/watch?v=hFnw0vkorrY&t=4660s): derives a useful deck size from discard capacity plus hand size.
- [87:45](https://www.youtube.com/watch?v=hFnw0vkorrY&t=5265s): preserves accumulated Cryptids until their scoring contribution is needed.

Lesson: temporary bridge Jokers and phase-specific copying create the eventual engine. Finding a legendary alone is insufficient.

### 4. Roffle Lite: Perkeo / Flush Five

[The Perfect Perkeo Flush Five Build](https://www.youtube.com/watch?v=tIMrXgruM_E). This run eventually loses; it supplies useful decisions and a timing failure, not an infallible policy.

- [59:05](https://www.youtube.com/watch?v=tIMrXgruM_E&t=3545s): accumulates Eris before obtaining Observatory.
- [60:26](https://www.youtube.com/watch?v=tIMrXgruM_E&t=3626s): chooses the Idol/Observatory direction over Baron given the available hand-size support.
- [83:36](https://www.youtube.com/watch?v=tIMrXgruM_E&t=5016s): Observatory changes survival margin enough to pass Dusk and continue seeking Brainstorm; without it, Dusk would matter immediately.
- [117:23](https://www.youtube.com/watch?v=tIMrXgruM_E&t=7043s): recognizes that late Brainstorm cannot accumulate planets quickly enough to keep pace. Later acknowledges selling Brainstorm earlier.

Lesson: model when an investment pays off, and learn from the expert's loss as well as their successful moves.

### 5. Balatro University: methods lecture

[“naneinf” explained — ALL methods](https://www.youtube.com/watch?v=6e8-QeANHJU).

- [07:41](https://www.youtube.com/watch?v=6e8-QeANHJU&t=461s): accumulate Cryptids while ordinary scoring is sufficient, then spend as requirements rise.
- [14:09](https://www.youtube.com/watch?v=6e8-QeANHJU&t=849s): describes Gold-to-Steel, Purple-to-Red and copier-target transitions.
- [19:00](https://www.youtube.com/watch?v=6e8-QeANHJU&t=1140s): contrasts persistent Observatory value with consumed Cryptids.

The Chicot/Manacle section at 22:31 explicitly discusses an exploit. Exclude that from ordinary strategy recommendations and fair score comparisons.

## Where our player lacks support

### Priority 1: value safe setup hands and round production

`balatro_ai/analysis.py` selects immediate-score candidates, with limited special alternatives for growth and held-card engines. Its economy preview forecasts interest, not the full income and consumable production of a round. Legal setup plays remain available to the coach, but numerical advice does not compare their future value.

Add a compact round plan: score required, safe setup actions, expected money/Tarots/copies, and the scoring finish. Reuse existing public observations and scoring. Treat interest as an opportunity cost rather than an unconditional floor; productive investments can repay it.

### Priority 1: advise copier targets at the correct event

Current reorder advice explores adjacent swaps that improve immediate hand score. Generic copying lessons already exist, but this does not numerically support copying DNA for a first hand, an income effect during setup, Mime before the final hand, or Perkeo before leaving the shop.

Advise a legal sequence with the relevant trigger attached to each target. Account for automatic transitions: a plan cannot assume a reorder opportunity after the terminal scoring play if cashout has already executed.

### Priority 1: quantify draw reliability and growth requirements

The analysis explicitly says it has no discard outcome search. Public remaining-deck counts are available, but there is no corresponding probability calculation for finding the required ranks, suits, seals or enhancements. Deck shaping therefore relies heavily on prose.

Use public counts, never hidden deck order. Estimate access to the scoring hand after legal draws, then compare duplication/removal choices and the next blind's growth requirement. Avoid universal “make the deck smaller” advice: resource farming may require extra bodies. Conversely, removing cards does not itself reduce hand capacity unless the deck becomes exhausted.

### Priority 2: expose alternate engines and their investment timing

Idol and Triboulet scoring effects are implemented. The opportunity summaries nevertheless omit several relevant engines, and the strategy library has no dedicated Idol entry. Perkeo, Cryptid and Observatory have separate lessons without an accumulation forecast linking them.

Add conditional paths based on owned/offered tools: homogeneous Idol decks, held-card Baron/Mime, and accumulated Observatory planets or Cryptids. Include the cost of transitioning and rounds until payoff. More text alone is insufficient: retrieval currently returns at most three examples, with one per family, and does not rank by strategic urgency.

### Existing guidance must also be applied

In TAF7DNTX's recorded first Tooth hand, the player scored 764,127; a previously identified legal alternative scored about 1.223 billion. Replaying that observation through today's analysis produces a leading candidate of about 1.193 billion and the relevant Glass/copying lessons. We have not rerun the model on it, so this is evidence of available advice, not proof today's coach repeats the old mistake.

Even the stronger single hand was far below that blind's 94 billion requirement. Earlier engine development still matters. The reviewed TAF run lost at Ante 13 before its configured limits; the two other reviewed runs lost at Ante 11. A later stop threshold alone does not address those losses.

Do not assume missing rare Jokers were available: QD3F4XVW's reviewed main segment never offered several of the obvious high-end engine pieces. Evaluate decisions against actual offers.

## Corrections to preserve in future edits

- Retriggering Glass does **not** compound its break probability; the normal chance remains one in four per scored card. Confirmed against installed game logic and the [official clarification](https://bsky.app/profile/playbalatro.com/post/3lp3e5m64l22n). The coach prompt/library currently contain misleading guidance here.
- TAF lost three Glass cards across two relevant hands, but a Glass Jack of Spades remained in the deck at the final observation. Do not describe the failure as losing every Glass face card.
- Boss reroll is already exposed as an action. Advice that boss selection always proceeds automatically is stale; this is not a missing-action feature request.
- Negative consumables can exceed ordinary slot capacity; an Observatory lesson should not treat all accumulated planets as requiring free ordinary slots.

## Small offline acceptance cases

1. **Safe farming:** with ample survival margin and Purple seals, recommend a legal setup sequence that increases resource production and still finishes the blind; reject it when the margin disappears.
2. **Copying phases:** show correct targets for a generation event, a scoring finish and shop exit. Reject sequences requiring an unavailable intermediate action window.
3. **Deck access:** compute a small known public-count draw example exactly; distinguish a homogeneous deck that supports both Rebate discards and scoring from one thinned too far.
4. **Investment timing:** in an otherwise matched Observatory shop example, change survival margin and verify that taking immediate scoring versus continuing the search changes appropriately. Do not encode the particular video's choice unconditionally.
5. **Advice application:** replay the recorded TAF Tooth observation and verify the coach chooses and legally executes an appropriate high-scoring candidate. Check current retrieved advice before adding duplicate lessons.
6. **Mechanics:** verify the corrected Glass probability, Negative capacity and available boss-reroll guidance.

Verification completed: `python -m pytest -q tests/test_analysis.py tests/test_strategy.py tests/test_strategy_exercises.py tests/test_trajectory_audit.py` — **75 passed**. The TAF numerical replay was checked separately. These validate existing behavior; the proposed cases and improvements above have not been implemented or evaluated in new games.

Recommended next implementation: the round-production and copier-phase advice, accompanied by a small offline decision set. Then evaluate matched seeds and budgets for survival and score, keeping filtered record starts separate.
