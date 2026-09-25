# Fast Astra: keep Astra's strength, cut game time

## Outcome

`balatro play --coach astra-fast` plays a complete Black Deck / Gold Stake game.
Astra keeps authority over strategy: shops, packs, build direction and
anything the tools cannot certify. Code makes the in-blind decisions it can
calculate exactly, and executes Astra's shop plans click by click. Target:
Astra-level strength or better, with far fewer Astra calls and a headless fast
client. Astra's strength is the floor; a change that loses to it is rejected.

Evidence behind this design: [experiment log](docs/experiment-log.md). Every
past speedup that removed Astra's authority lost strength. The in-blind losses
of faster choosers were calculable, and about two thirds of Astra's calls are
shop clicks, pack picks and blind selection rather than hard judgment.

## Smallest real example

PI4T2AH8 made 227 Astra calls: 71 in-blind, 105 shop clicks (30 single
rerolls), 28 pack choices, 16 blind selections. Under this plan, the in-blind
moves go to search when it covers the state, each shop visit is one Astra call
returning a plan, and blind selection folds into that call. That leaves one
call per shop and one per pack: about 40–45 instead of 227.

## Reused mechanisms

- The Astra coach, packet, prompt and runner on `main` (the winning path).
- The within-blind transition kernel and bounded expectimax
  (`game/blind.py`, `blind_search.py`, tests) from
  `archive/2026-09-25/jev-balatro`. It has verified arithmetic, public-only
  draws and explicit coverage gaps.
- The runner's follow-up chains: `then`, and `reroll_shop` with
  `repeat`/`until` (`shop_has_any`, `money_at_least`) in `runner.py` and
  `prompts/coach.md`.
- If coverage is too low: the Jackdaw determinization and firewall tests from
  `archive/2026-09-14/route-merger-wip`, instead of writing a new simulator.

## Steps

1. **Measure the client floor (no model calls).** Play one headless `--fast`
   game with a trivial scripted policy. Record per-method RPC time (play,
   discard, buy, reroll, cash_out, select).
2. **Port the kernel onto `main`.** Bring `game/blind.py`, its search and tests
   across unchanged. Add an offline replay over all in-blind decisions in both
   Black/Gold wins, XV2MP8L5 and the pilot Astra runs. Report coverage, how
   often search agrees with Astra, and the clear probability for every
   disagreement.
3. **Route in-blind decisions.** When the kernel covers the state, choose by
   the exact probability of clearing the blind. Break ties by preserving
   resources (hands, discards, held consumables) and by the latest Astra plan's
   `preserve` items. Anything uncovered goes to Astra, as today.
4. **One shop plan per visit.** Astra returns an ordered program: buys, sells,
   Joker order, a reroll search (targets, spend cap, money floor), pack intent
   and the next blind's select/skip. The runner executes it. It hands control
   back to Astra when:
   - a target or another notable offer appears;
   - a step becomes illegal;
   - a pack opens.

   Pack choices stay one Astra call each.
5. **Evaluate against Astra.** Freeze both versions, then play them on
   untouched matched Black/Gold seeds (JBG00003+, the panel defined in
   `archive/2026-09-25/jev-balatro:benchmarks/jev-evaluation.json`), headless
   and serially, with rotated order. Report clears, antes, wall time, Astra
   calls, timeouts and every failed or stopped run.

Later, only after step 5:
- a priced reroll rule (reroll value vs. cost and lost interest,
  conditioned on survival margin);
- Jackdaw coverage for Glass, Lucky and seals;
- more Astra effort on the remaining strategic calls. This is a user decision.

## Acceptance checks

- Step 1: per-method median and p90 client time in headless fast mode.
- Step 2: the replay report exists. Search solves the recorded calculable
  cases:
  - the XV2MP8L5 singleton-Five setup (segment 00, event 454);
  - Saturn before the Straight (fast-repaired event 93);
  - the low pair with 344 chips needed (event 99).

  Every disagreement where search is worse or uncertain is reviewed before
  step 3 goes live.
- Step 3: the firewall tests still pass. No seed, draw order or hidden identity
  reaches search or Astra. The full suite and `ruff check .` pass.
- Step 4: in a fake-game test, a shop program executes, interrupts on a target,
  and stops at an illegal step without retrying a game mutation. Recorded shop
  observations produce valid programs.
- Step 5: the new bot's wall time and Astra call count are measured on the same
  seeds as the Astra arm. Strength is reported as paired outcomes. Four seeds
  are exploratory; no superiority claim follows from them.

## Anti-goals

- Do not give strategic authority to Jev, heuristics or simulator search.
- Do not read hidden state, and do not tune on evaluation seeds.
- Do not count simulator results as native results.
- Do not enable model Fast mode.
