# Astra: faster and stronger

## Outcome

`balatro play --coach astra-fast` plays a complete Black Deck / Gold Stake game
in visible fast mode (`balatrobot serve --fast`, no headless). Astra keeps
authority over every strategic decision. Four tracks:

- **Speed:** a much faster visible game and fewer Astra calls, with no loss of
  strength.
- **Strength:** give Astra the numbers it lacked about money and Tarots, the
  two resources most Balatro strategies run on. Money buys the engine and
  earns interest. Tarots build the deck the engine scores with.
- **Evaluation:** frozen versions compared on matched seeds. A faster game
  makes enough seeds affordable to measure strength at all.
- **High scores:** survive deep into endless mode (Track D).

Astra's strength is the floor; a change that loses to it is rejected.

## Status

- **A1 done.** Visible `--fast` cut the client from 59.4 to 2.2 minutes a game;
  Astra is now 86% of wall time.
- **A2 done, A2–A3 dropped** by the rule in step 2: only 14 of 406 recorded
  in-blind decisions (3.4%) were routable, all agreeing with Astra.
- **A4 partly done:** reroll chains stop on notable offers and on forecast
  upgrades (`pace_gain_at_least`); later Mega-pack picks chain by key.
- **B1–B5 done,** plus the next-ante horizon, and the Arcana-pack hand fix
  that had made targeted Tarots illegal on the first pick of nearly every pack.
- **First visible game:** lost the Black/Gold Ante 8 boss (295,956/400,000) in
  28.2 minutes. The build could not grow in time for Ante 8 once its
  Perishables expired, which the horizon now reports an ante ahead.

## Evidence

- [Experiment log](docs/experiment-log.md): every past speedup that removed
  Astra's authority lost strength. About two thirds of Astra's calls are shop
  clicks, pack picks and blind selection rather than hard judgment.
- The wins were played visible at 2× animations. A `play` took 8.7 s median
  in the client, and the client was 59.4 of PI4T2AH8's 95.5 minutes.
  `balatrobot serve` offers `--fast` (10×), `--gamespeed` and `--no-shaders`.
- Astra's two Black/Gold losses (JBG00001–2,
  `archive/2026-09-25/jev-balatro:evidence/hybrid-v6-matched-pilot/`) came
  from strategy, not play. Every in-blind play matched the top candidate. The
  scorer was exact on all 21 checked plays in JBG00001, and missed in JBG00002
  only while Misprint was held. The builds could not reach the targets:
  - JBG00001: best hand 10.5k, against about 9.4k needed on every hand at the
    Ante 5 Big Blind.
  - JBG00002: best case about 17k, against 16.7k needed per hand at The Wheel.
- **Money and Tarots were short in those losses:**
  - JBG00001 never cashed out above $8 and earned about $5 of interest all
    game. It declined two Charm Tags (a free Mega Arcana each).
  - In TAF7DNTX, money was drained before the last shops
    (`docs/trajectory-review.md:168-180`), and Justice, which makes Glass
    cards, was sold for Death.

## Smallest real examples

- **Speed:** PI4T2AH8 made 227 Astra calls: 71 in-blind, 105 shop clicks (30
  single rerolls), 28 pack choices, 16 blind selections. Target: one call per
  shop and one per pack (about 40–45), plus the in-blind states routed to Astra.
- **Money:** JBG00001, Ante 3 Small Blind, $1 (event 162). Astra played the
  blind for "cash and another shop". The Small Blind pays no base reward at
  this stake: the cash-out was $2 and the next shop bought nothing. Skipping
  gave a free Polychrome Joker. The packet showed no blind reward or skip cost.
- **Tarots:** JBG00001 declined the Charm Tags at Ante 4 and Ante 5 (events
  254 and 372). Each skip would have cost about $3 and returned two Tarots out
  of five, with no number in the packet saying what those Tarots would add.

## Reused mechanisms

- The Astra coach, packet, prompt and runner on `main` (the winning path).
- `readiness.py` (`boss_readiness`, the exhaustive `_ceiling`),
  `game/boss_rules.py`, and `analysis.py` (`engine_opportunities`, targeted
  Tarot enumeration). Today readiness quantifies only The Needle
  (`readiness.py:183`).
- The probe harness (`balatro_ai/probe.py`,
  `tests/fixtures/decision_probes.json`, `docs/decision-probes.md`). It asks
  Astra about recorded decisions without a game client, with a hard cap of 8
  calls per batch.
- The within-blind kernel and bounded expectimax (`game/blind.py`,
  `blind_search.py`, tests) from `archive/2026-09-25/jev-balatro`. It has
  verified arithmetic, public-only draws and explicit coverage gaps.
- The runner's follow-up chains: `then`, and `reroll_shop` with
  `repeat`/`until` in `runner.py` and `prompts/coach.md`.

## Track A: speed

1. **Measure visible fast mode (no model calls).** Play one game with a
   trivial scripted policy on `balatrobot serve --fast`. Try `--no-shaders`
   and a higher `--gamespeed` if play is still slow. Record per-method RPC
   time (play, discard, buy, reroll, cash_out, select) against the recorded 2×
   wins. Confirm the runner's animation waits still settle: a pack opening
   after a skip tag (`runner.py:457`), and the timeout noted in
   `docs/black-gold-results.md:87`. This step comes first, because it also
   sets what evaluation costs.
2. **Port the kernel onto `main`.** Bring `game/blind.py`, its search and
   tests across unchanged. Replay every in-blind decision from both Black/Gold
   wins, XV2MP8L5 and the pilot Astra runs. Report:
   - coverage after the routing exclusions in step 3;
   - how often search agrees with Astra;
   - the clear probability for every disagreement.

   If little coverage remains after the exclusions, drop steps 2–3 and keep
   steps 1 and 4.
3. **Route in-blind decisions to search only when clear chance is the whole
   story.** All of these must hold, otherwise Astra decides, as today:
   - the kernel covers the state (`coverage()` is empty);
   - the chosen move's clear probability is exact, not a bound;
   - no held Joker whose value depends on the play beyond this blind, either
     a counter (Green Joker, Runner, Square, Spare Trousers, Ice Cream, Ramen)
     or money (Mail-in Rebate, Delayed Gratification);
   - no held Tarot or Spectral. Consumable use is Astra's decision.

   Choose by exact clear probability. Break ties by preserving hands, discards
   and consumables, then the latest Astra plan's `preserve` items.
4. **One shop plan per visit.** Astra returns an ordered program: buys, sells,
   Joker order, a reroll search (targets, spend cap, money floor), pack intent
   and the next blind's select/skip. The runner executes it. It hands control
   back to Astra when:
   - an offer matches a target;
   - an offer is Rare or Legendary, a Polychrome or Negative edition, or a
     Tarot the forecast (B1) rates above the plan's best target;
   - a step becomes illegal;
   - a pack opens.

   Pack choices stay one Astra call each. The existing `reroll_shop` chains
   get the same interrupt: in JBG00002 a queued reroll dropped a Polychrome
   offer without comment.

## Track B: strength (money and Tarots)

Astra keeps every decision. Changes are information in the packet and prompt
wording, never rules that decide for it.

1. **Build-pace forecast.** Extend `boss_readiness` from The Needle to every
   blind. For the current build it reports:
   - the spread of per-hand scores (the existing scorer over public deck
     draws) against the pace the next Big Blind and boss require, with boss
     constraints applied;
   - each Joker's contribution, so a zero-score Eternal shows as a permanent
     slot cost and a Perishable that expires before the target shows as zero.

   Money and Tarot values below are measured against this pace.
2. **Money.** The packet shows:
   - the interest each purchase gives up;
   - the reroll spend so far this ante;
   - the expected money entering the next shop at the current spend;
   - the value of visible money sources: economy Jokers, Hermit, Temperance,
     Economy and Investment tags.

   Prompt: spending below the next $5 step needs a forecast gain that beats
   the lost interest. A reroll below it needs the build to be short of pace.
3. **Tarots.** For each held or offered Tarot (shop, Arcana pack, Charm Tag),
   the packet shows its best targets and the resulting pace change:
   - enhancements: Empress, Hierophant, Chariot, Justice, Lovers, Tower,
     Devil, Magician;
   - suit changes: Star, Moon, Sun, World;
   - rank and deck changes: Strength, Death, Hanged Man;
   - money: Hermit, Temperance.

   Lucky is scored at its expected value and marked approximate. This also
   brings the docs' deck-construction advice into the packet: duplicate
   useful enhanced or sealed cards, and remove cards that obstruct the engine
   (`docs/trajectory-review.md:89-95`).
4. **Skip value.** The packet shows each blind's cash reward and what skipping
   it costs, next to the tag's money or Tarot value from B2–B3. Prompt: add
   the Polychrome, Holographic and Foil tags to the tag list. Soften "do not
   skip automatically… Early shops matter especially" (`coach.md:145`) into a
   comparison against the shown reward.
5. **Small fixes.**
   - Fill boss-text placeholders (The Wheel reached Astra as "#1# in 7 cards
     get drawn face down").
   - Score the visible cards when some are face-down, instead of returning no
     candidates.
6. **Probe before playing.** Turn recorded decisions into probe fixtures:
   batches of at most 8 calls, one attempt each.
   - Money targets:
     - JBG00001 event 162 (Polychrome Tag at $1);
     - JBG00001's Perishable buys;
     - the TAF7DNTX Ante 12 shop ($33 spent to $2 on rerolls).
   - Tarot targets:
     - JBG00001 events 254 and 372 (Charm Tags);
     - the TAF7DNTX Justice-for-Death sale.
   - Slot target: JBG00002 event 161 (Eternal Chaos the Clown).
   - Controls: the existing fixtures, plus shop and Tarot decisions from the
     two wins.

## Track C: evaluation

Freeze three arms: `astra` (main), `astra` + B, and `astra-fast` + B. Play them
in visible fast mode, serially, with rotated order, on untouched matched
Black/Gold seeds (JBG00003+, the panel in
`archive/2026-09-25/jev-balatro:benchmarks/jev-evaluation.json`).

- B is judged against `astra`, and must gain.
- A is judged against `astra` + B, and must not lose.

Report clears, antes, wall time, Astra calls, timeouts, money at each cash-out,
Tarots used, and every failed or stopped run. The panel size is set once A1
gives game time.

## Track D: high scores in endless

Vanilla targets grow slowly to Ante 8 and then explode: Ante 12 is 3×10⁸ base,
Ante 13 4.7×10¹⁰, Ante 16 8.6×10²⁰ and Ante 20 4.3×10⁴³, a 10³–10⁶ jump per ante
from Ante 14 on. The bot's best is Ante 13 (TAF7DNTX, peak hand 1.3×10¹¹).
Additive Mult and hand levels stop mattering by about Ante 11; only
multipliers that themselves grow each ante keep up:

- held Steel Kings with Baron and Mime, red seals and Blueprint/Brainstorm
  copies, where each extra King multiplies the score;
- Glass or face cards with Hanging Chad, Photograph and retriggers;
- Perkeo with Observatory, where each Negative Planet copy adds X1.5;
- hand size and deck density: thinning, Cryptid copies, Deja Vu red seals.

Ante 20 needs such an engine assembled by about Ante 10 and grown every shop.
It is a stretch; Ante 14–16 is a realistic next target. Steps:

1. **Horizon (done):** `next_ante.growth_needed` and `build_holds_through_ante`
   show, every shop, which ante the current build dies at.
2. **Engine growth values:** per-shop and per-ante multiplier gain for Steel
   Kings, red seals, copies and Observatory Planets, so a +1 King reads as a
   multiplicative gain rather than a small per-hand change.
3. **Endless run limits and time:** about 500–700 calls to Ante 20; raise
   `--max-calls` and `--seconds` for endless runs.
4. **Scorer coverage for long retrigger chains** at 10³⁰+ scores, checked
   against the game on recorded high-score hands.

Acceptance: an endless Red/White run whose recorded horizon matches the ante it
actually dies at, then a run past Ante 13.

## Order

A1 first. Track B runs alongside A2–A3, because it needs no gameplay until its
probes pass. A4's Tarot interrupt depends on B1–B3. Track C runs after both.

## Acceptance checks

- **A1:** per-method median and p90 client time in visible fast mode, next to
  the 2× wins. A scripted game completes with no animation-wait failure.
- **A2:** the replay report exists. Search solves the recorded calculable
  cases:
  - the XV2MP8L5 singleton-Five setup (segment 00, event 454);
  - Saturn before the Straight (fast-repaired event 93);
  - the low pair with 344 chips needed (event 99).

  Every disagreement where search is worse or uncertain is reviewed before A3
  goes live.
- **A3:** a test per exclusion (counter Joker, money Joker, held Tarot or
  Spectral, bound-only result) routes to Astra. The firewall tests still pass:
  no seed, draw order or hidden identity reaches search or Astra. The full
  suite and `ruff check .` pass.
- **A4:** in a fake-game test, a shop program executes, interrupts on a target,
  and stops at an illegal step without retrying a game mutation. Replaying
  JBG00002's pre-boss shop (events 474–479) interrupts on the Polychrome offer
  instead of rerolling past it.
- **B1:** on the recorded observations, the forecast reports JBG00001 short
  before the Ante 5 Big Blind and JBG00002 short before The Wheel. It matches
  the recorded plays wherever the scorer is exact.
- **B2–B3:** on recorded observations, the packet shows JBG00001's lost
  interest per shop, the Justice and Charm Tag values, and a Tarot pace change
  that matches the scorer after the Tarot is applied.
- **B4–B5:** packet tests show blind reward and skip cost. The Wheel text has
  no placeholder, and a face-down hand gets scored candidates.
- **B6:** the target decisions move in the expected direction on public
  information, and no control regresses. Otherwise fix the packet before any
  full game.
- **C:** strength is reported as paired outcomes per arm. Four seeds are
  exploratory; no superiority claim follows from them.

## Later, only after Track C

- Jackdaw coverage for Glass, Lucky and seals.
- Discard value in the forecast (for example Wasteful).
- The docs' alternate-engine timing advice
  (`docs/high-score-video-review.md`, Priority 2).
- Spectral values beyond Deja Vu, on the same pattern as B3.
- More Astra effort on the remaining strategic calls. This is a user decision.

## Anti-goals

- No headless mode in this plan.
- Do not give strategic authority to Jev, heuristics or simulator search.
- Do not add rules that decide for Astra. Strength changes are information.
- Do not read hidden state. JBG00000–2 and the win seeds are for development
  and probes only, never evaluation.
- Do not count simulator results as native results.
- Do not enable model Fast mode.
