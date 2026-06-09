# Current Checkpoint

Date: 2026-06-10

## Architecture: planner core

Strategy now lives in `balatro_ai_v2/planner/` — an online planning agent that
uses the fast simulator as its world model in both evaluation paths:

- `evaluation.py` — `run_value()`: projected best-hand capability (sampled
  deterministically from the persistent deck, scored with current jokers and
  hand levels) against the boss-aware requirement curve of upcoming antes,
  plus economy/scaling/build terms. Replaces all hand-tuned value tables.
- `tactics.py` — in-blind beam search with boss-aware in-beam state.
- `core.py` — shop/pack/blind decisions by rollout expectimax: top-K
  candidates ranked by static run_value delta, rolled forward with a cheap
  policy to a blind horizon, scored by terminal run_value.
- `mirror.py` — mirrors a live BalatroBot state into a `FastFullGameEnv`
  (exact hand/deck/shop/prices; only future RNG is sampled), with the
  live-unsafe purchase rules (unmodeled, probabilistic, float-drift jokers).
- `live_policy.py` — `PlannerPolicy` drives the live game; targeted-tarot
  target attachment, big-hand fallback, canonical joker rearranging.

Run with: `python scripts/run_balatrobot_agent.py --launch-server --planner ...`
Evaluate fast: `python scripts/evaluate_fast_full_game.py --agent planner --workers 8 ...`

## Scoring engine

`apply_additive_jokers` now reproduces Balatro's phased trigger order,
verified transition-by-transition against live traces:

1. card phase — each scoring card fires its enhancement/edition then every
   joker's per-card trigger (Fibonacci, suit mults, Photograph x2 first face,
   Ancient/Idol/Triboulet), left to right;
2. held phase — Shoot the Moon / Raised Fist / Baron, skipping debuffed
   held cards;
3. joker phase — each joker once, left to right, additive and x-mult effects
   applied IN ORDER (Blackboard left of Mad Joker multiplies before the +10),
   edition bonuses at each joker's turn.

Because order matters, x-mult jokers belong rightmost: the env auto-sorts on
acquisition and the live policy issues BalatroBot `rearrange` calls to match
(`canonical_joker_order`).

## Verified results

Fast sim (Red deck, white stake, max 400 steps, seeds 1-20 tune set):

- M0 rollout-oracle baseline: 20% wins (4/20)
- M1 after sim-honesty fixes (joker persistence, boss blinds, skip tags): 30%
- M2 planner (pre-sequential engine): 55% tune / 75% held-out seeds 21-40
- current (sequential engine + canonical order + retuned weights): 45% tune

Live BalatroBot (Red/White, `--planner`): 14 runs over seeds 1-16, best
ante 6, no wins yet. Every completed trace replays through
`scripts/game_parity_gate.py --require-complete` with zero mismatches after
triage; each mismatch found became an engine fix with a regression test:

- sequential trigger order (the big one), Photograph card-phase timing
- The Arm downlevel-before-scoring; Fortune Teller tarot counting (the
  parity replay tracks tarot uses across the run)
- card enhancements/editions on played cards; joker editions on unmodeled
  jokers (mirrored as inert slot-holders)
- scaling-joker ability extraction (current value vs step size keys)
- coupon/edition tag free purchases; tag-pack state flows; async-lag
  tolerance (stale next_round, swallowed retries recorded as polls)

Live-unsafe jokers (never bought live; exact replay impossible):
Bloodstone (1-in-2 roll), Ramen (Lua float drift), Raised Fist (The Hook's
random pre-score discards).

## Known gaps / next work

1. Live win rate trails fast-sim: ~40% of live shop joker offers were
   unbuyable before the economy-joker batch; implementing more jokers
   (exactly) directly raises live build quality.
2. Sequential-engine weight retune is one iteration deep (45%); more tuning
   and possibly deeper rollouts should recover the 55%+ of the old engine.
3. Targeted tarots in packs opened outside a blind are unusable through
   BalatroBot (no targeting hand exposed) — skipped by design.
4. M3 milestone open: 2 live wins with clean gates.

Tests: 295 passing (`python -m pytest`).
