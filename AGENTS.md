# balatro-ai-v2 Agent Notes

## Non-Negotiable Goal

The fast simulator is only useful if it reproduces clean BalatroBot behavior.
Do not claim that a fast policy, gym agent, or trained model beats ante 8 unless
the same policy also reproduces through BalatroBot on the requested deck and
seed set.

## Clean Evidence Only

- BalatroBot debug/internal mutation endpoints such as `add` or `set` are not
  valid reproduction evidence.
- Do not inject jokers, cards, money, planets, or shop state.
- Clean evidence means starting a normal BalatroBot run, acting only through
  public game actions, and recording the resulting trace.

## Whole-Game Parity Contract

Fast results do not count until full BalatroBot traces pass:

```bash
python scripts/game_parity_gate.py runs/red_deck_full.jsonl
```

`--require-complete` must mean all observed transition types are checked, not
just skipped. It must also require a finished trace with matching `run_start`
and `run_end` events. Missing parity for any state/action pair is simulator
work, not an agent result. The rule coverage gate must also pass; observed-trace
parity alone is not enough because a winning policy can route through unseen
jokers, packs, vouchers, tags, stakes, boss blinds, and consumables.

The parity target includes:

- all tactical scoring, including every implemented joker, card modifier, hand
  level, boss blind, held-card effect, edition, enhancement, seal, and deck
  mutation that can affect score
- exact draw and hand-order behavior
- all blind selection, round, cash-out, money, interest, ante, and win/loss
  transitions
- all visible shop actions: buy card, buy pack, buy voucher, sell joker, sell
  consumable, reroll, next round
- all consumables and pack selections, including target-card effects
- all joker acquisition, sale, slot, edition, scaling, and per-trigger state
  changes
- source-derived coverage for every rule object in the Balatro Lua dump, not
  only objects encountered by a seed trace

The local source dump used for parity is:

```text
~/Library/Application Support/Balatro/Mods/lovely/dump
```

`scripts/rule_coverage_report.py` must read actual source tables from
`game.lua`: `self.P_CENTERS`, `self.P_BLINDS`, `self.P_TAGS`, and
`self.P_STAKES`. Do not use whole-file regex counts as parity evidence because
that accidentally includes unrelated profile/stat keys.

Use source-backed missing-rule output while filling the simulator:

```bash
python scripts/rule_coverage_report.py --show-missing --source-details
```

As of 2026-05-23, source-backed rule coverage is 357/357 (100.0%):
150/150 jokers, 52/52 consumables, 32/32 vouchers, 8/8 enhancements, 5/5
editions, 32/32 boosters, 16/16 decks, 30/30 blinds, 24/24 tags, and 8/8
stakes. This means every source rule object has a local fast-path rule surface.
It does not, by itself, prove every rule surface is wired into the training gym
or that every RNG branch reproduces BalatroBot; clean trace replay remains
mandatory.

## Current Parity Lessons From Live BalatroBot

On 2026-05-23, clean BalatroBot traces exposed a real fast-path bug:

- Fast scoring matched the checked BalatroBot play chip deltas.
- Discard replacement did not match.
- BalatroBot draws replacement cards from the tail of `cards.cards`, then sorts
  the visible hand by high rank and suit order.
- The BalatroBot tactical planner and parity checker now model draw-from-tail
  plus sorted visible hands.

Evidence commands that passed after the fix:

```bash
python scripts/replay_balatrobot_trace.py runs/red_deck_seed1_complete_attempt.jsonl --require-complete
python -m pytest
```

On 2026-05-23, a fresh clean BalatroBot run was captured at
`runs/red_deck_seed1_current_real.jsonl`; replay checked 33 transitions and 17
scores with zero mismatches. It lost at ante 2, so it is parity evidence for
observed transitions only, not solve evidence.

On 2026-05-24, another live BalatroBot retry was captured at
`runs/red_deck_seed1_live_retry.jsonl`; `scripts/game_parity_gate.py` checked
38/38 transitions, 17 scores, and 1 async post-play draw with zero mismatches
and zero unchecked transitions. This run also lost at ante 2. The parity checker
now explicitly verifies delayed `DRAW_TO_HAND` replacement after a play instead
of treating those BalatroBot poll states as unchecked no-ops.

On 2026-05-24, the planner/simulator work moved from "no tarot support" toward
full-action parity coverage:

- BalatroBot pack handling now polls boundedly when a pack has opened but cards
  are not visible yet, and it retries public pack selection while BalatroBot says
  a selection is already in progress before using public pack skip as rescue.
- Shop and pack planning now values Arcana access, no-target tarots, and
  targeted tarots with visible hand targets. Held targeted tarots are considered
  before tactical play when the game is in `SELECTING_HAND`.
- The fast full-game shop now rolls tarot shop cards and Arcana packs, and pack
  selection immediately applies consumables so Mega packs can take two
  consumables instead of being blocked by held consumable slots.
- Joker edition scoring is wired into the BalatroBot tactical scorer, and The
  Flint now applies the source rule of halving base hand chips and base mult
  before card and joker scoring.
- Source review confirmed `j_square`, `j_runner`, `j_green_joker`, and
  `j_trousers` update in `context.before` and score the updated value; Runner's
  current chip total scores on every hand, but only increments on Straights.

Regression status after these changes: `python -m pytest -q` passes locally.
`scripts/game_parity_gate.py runs/red_deck_seed2_visible_fast_current_policy_retry3.jsonl`
still fails while `j_constellation` is present: transitions and draws are fully
checked, but 22 score deltas do not match. Later hands after Constellation is
gone match, so the next parity root-cause should focus on Constellation/X-mult
state timing or BalatroBot trace timing around planet-triggered joker updates.

On 2026-05-25, a visible clean real run with the current heuristic policy on
red deck seed 1 lost at ante 2 but passed parity completely:

```bash
python scripts/run_balatrobot_agent.py --launch-server --fast-server --no-headless-server \
  --port 12347 --deck RED --stake WHITE --seed-start 1 --seeds 1 --max-steps 800 \
  --trace-jsonl runs/red_deck_seed1_real_visible_current_20260525.jsonl
python scripts/game_parity_gate.py runs/red_deck_seed1_real_visible_current_20260525.jsonl
```

The failure was shop/economy, not parity: the planner bought `j_bull`, then
spent all remaining money on a Jumbo Arcana pack with no usable target-card
tarot context, skipped the pack, and entered ante 2 with weak scaling and no
cash. The shop oracle now refuses non-free Arcana packs that leave less than $3
after purchase.

Also on 2026-05-25, the first gym training pass exposed a model bottleneck:

- `scripts/generate_fast_oracle_data.py` now accepts `--beam-width` and
  `--action-beam` so broad light-oracle datasets can be generated without
  runaway runtimes.
- `scripts/train_fast_imitation_policy.py` now accepts multiple `--data-jsonl`
  inputs.
- The linear full-action ranker now includes target item identity features.
- Best smoke model so far:
  `runs/fast_imitation_light8_linear_items_e8_20260525.json`, trained on
  `runs/fast_oracle_light8_20260525.jsonl`.
- Fast eval for that model: seeds 1-8 averaged 5.125 rounds cleared, but
  held-out seeds 9-16 averaged only 2.625 rounds. Do not replay this model in
  real Balatro as a claimed improvement.

Next training bottleneck: the light oracle is too weak and the linear ranker
still generalizes poorly. Improve the oracle/value model before spending more
time on broad real BalatroBot replays of trained models.

Later on 2026-05-25, the training loop was pushed against the stronger rollout
shop oracle:

- `scripts/train_fast_imitation_policy.py` now supports `--phase-filter
  shop-pack` and `--model-type softmax-linear`.
- `balatro_ai_v2.learning.imitation` now has run-context/action interaction
  features and a legal-action softmax SGD trainer. This improved rollout
  shop/pack imitation accuracy from roughly 38% with perceptron training to
  roughly 71% on the 8-seed rollout dataset.
- `scripts/generate_fast_dagger_data.py` collects DAgger labels: the current
  behavior policy visits states, while `RolloutSearchRunAgent` labels those
  same states.
- Direct rollout search remains far stronger than the learned approximation:
  with `shop_rollout_candidates=4` and `shop_rollout_steps=12`, fast eval got
  8.0 average rounds on seeds 1-4 and 14.75 average rounds with 1 win on seeds
  9-12. The best learned hybrid from this pass,
  `runs/fast_imitation_rollout8_shop_pack_softmax_ctx_e80_20260525.json`,
  reached only 4.625 average rounds on seeds 1-8 and 3.0 on seeds 9-16.
- A 16-seed rollout-label model and a first 4-seed DAgger iteration did not
  improve score. Treat this as evidence that the current linear/nearest
  dependency-free policy class is not enough for rollout distillation. The next
  useful step is either deploy rollout search directly through BalatroBot
  parity gates, or add a stronger function approximator/value model rather than
  spending more time tuning linear imitation.

The next rollout-planner improvement on 2026-05-25 made the fast full-game shop
source-shaped instead of tiny-pool shaped:

- Full-game shop, pack, voucher, and item-cost pools now load from
  `load_rule_catalog()` when the local Balatro Lua dump is available. The shop
  joker pool grew from 9 hand-picked jokers to the source-backed non-legendary
  joker pool, currently 145 keys. Tarot/Planet/Spectral pools and all 32
  vouchers are source-backed too.
- Voucher generation now respects upgrade prerequisites, so e.g.
  `v_overstock_plus` is not offered before `v_overstock_norm`.
- The first shop pack now follows the source guarantee of a normal Buffoon pack.
- The full-game env now keeps persistent deck composition between blinds.
  Deterministic int-card consumables such as `c_hanged_man`, `c_death`,
  `c_strength`, suit conversions, `c_sigil`, `c_ouija`, `c_cryptid`, and
  `c_immolate` mutate that composition. Enhancement/seal/joker-edition effects
  are still intentionally deferred until the full-game env migrates from int
  cards to `FastCardState` scoring.
- Source-shaped shops initially tanked rollout quality because the value table
  only understood the old tiny joker pool. Expanding full-game joker purchase
  values over the implemented scorer/run/economy joker surface restored useful
  search behavior.
- Source-shaped fast eval checkpoint before tactical-width tuning:
  `RolloutSearchRunAgent(shop_rollout_candidates=6, shop_rollout_steps=12,
  beam_width=1, action_beam=1)` got 8.0 average rounds on seeds 1-4 and 11.75
  average rounds on seeds 9-12, with no wins in those two 4-seed samples. The
  non-rollout heuristic averaged only 0.5 rounds on seeds 1-4 in the same
  broader shop, so rollout search is now carrying most of the policy strength.
  This is still fast-gym evidence only, not BalatroBot solve evidence.
- The next rollout improvement was tactical-width tuning. Seeds 2 and 4 were
  dying before first shop with `beam_width=1`; `beam_width=2, action_beam=1`
  fixed those first-blind failures without the cost of broad action beams. The
  new `RolloutSearchRunAgent` source-shaped default is therefore
  `beam_width=2`, `action_beam=1`, `shop_rollout_candidates=6`, and
  `shop_rollout_steps=12`.
- With those defaults and `max_steps=320`, seeds 1-4 produced one source-shaped
  fast-gym win: seed 4 cleared ante 8 in 243 steps. Seeds 1 and 3 were still
  alive at the cap, and seed 2 lost at ante 6. Treat this as improved fast-gym
  evidence, not solve evidence. The high step counts and very large money on
  some capped runs mean the next rollout cleanup should penalize excessive
  shop/pack churn and validate the path through BalatroBot parity before
  calling it strategically real.

Those traces are evidence for the checked transitions only. They are not a claim
of whole-game parity or an ante-8 solve. `scripts/game_parity_gate.py` must pass
on fresh clean traces before fast-gym results count.

## Work Direction

Prefer general parity and training infrastructure over one-seed heuristic fixes.
When a BalatroBot trace finds a mismatch, fix the simulator or planner model and
add a regression test. When a trace contains an unchecked transition, add a
parity check or explicitly document why the simulator cannot yet cover it.

Do not use the old flush-first baseline as the main solving strategy. A
flush-ish tactical policy plus simple shop values is only a debugging baseline:
it can expose parity bugs, but it is too narrow to solve Balatro robustly. The
solver direction is search first, model later:

- Tactical choices should score all legal hand families and discard masks, not
  force a suit lane.
- Shop and pack choices should be evaluated from current joker synergies,
  economy, hand levels, observed hand frequencies, scaling potential, and boss
  constraints.
- The fast gym should produce candidate trajectories with a broad evaluator;
  those trajectories can train a model only after they reproduce through
  BalatroBot.
- Use `scripts/generate_fast_oracle_data.py`,
  `scripts/generate_fast_dagger_data.py`,
  `scripts/train_fast_imitation_policy.py`, and
  `scripts/evaluate_fast_imitation_policy.py` as the dependency-free first
  training loop. The fast full-game gym now exposes explicit run actions:
  select/skip blind, cash out, next round, reroll, buy cards/packs/vouchers,
  sell jokers, use consumables, and select/skip opened packs. The default model
  is a linear legal-action ranker; `softmax-linear` is the better current
  dependency-free trainer; nearest-neighbor mode is for memorization/debugging
  only. This loop imitates the current search oracle; improve the oracle and
  policy class before treating model accuracy as strategically meaningful.
- Use `scripts/run_balatrobot_agent.py --full-action-model ...` for real-game
  replay of full-run policies. The older `--imitation-model` path only controls
  tactical play/discard decisions and is not enough to validate fast full-action
  policy strength.
- The explicit fast shop is still a deterministic parity-shaped approximation,
  not exact Balatro shop RNG. It now uses source-backed joker, tarot, planet,
  spectral, voucher, booster, and cost pools when the local Lua dump is
  available; it also models persistent shop vouchers, rerolls, discounts, extra
  hands/discards/slots, economy vouchers, first-shop Buffoon guarantee, and pack
  choices that fit the current 8-card tactical action encoding. Use it to train
  full-action policies, then validate and correct behavior with BalatroBot
  traces.
- Use `scripts/generate_fast_oracle_data.py --shop-rollout` when you want the
  slower `RolloutSearchRunAgent` shop oracle. This clones fast shop states,
  tries legal shop candidates, rolls forward cheaply, and labels the action with
  best future progress. Tune its budget with `--shop-rollout-candidates` and
  `--shop-rollout-steps`; do not broaden seed sweeps blindly if a rollout budget
  is too slow. Current source-shaped default is `beam_width=2`,
  `action_beam=1`, 6 shop candidates, and 12 rollout steps. Older checkpoint: after
  replacement-aware joker sells and
  owned-joker shop/pack filtering, `--shop-rollout --shop-rollout-candidates 4
  --shop-rollout-steps 12 --seed-start 1 --seeds 2 --max-steps 180` produced 1
  win, 22.5 average rounds cleared, and seed 1 cleared ante 8 in the fast gym.
  This is still not solve evidence until the same decisions reproduce through
  clean BalatroBot parity gates.
- Use `scripts/generate_balatrobot_trace_oracle_data.py` to turn full-state
  BalatroBot traces into oracle-labeled `TrajectoryStep` JSONL. This is the
  current DAgger bridge for real hand/shop states. A nearest-neighbor
  full-action model is acceptable for parity/debug replay only; it is not a
  solve strategy. As of 2026-05-24, DAgger nearest replay matched
  `BalatroBotPolicy()` exactly on visible red-deck seed 1 through ante 4
  (`diffs 0`, parity 71/71), but still lost because the planner/oracle itself
  is not strong enough.
- A policy result is not a solve until the exact policy clears ante 8 through
  clean BalatroBot runs on the first deck across multiple seeds and the trace
  passes `scripts/game_parity_gate.py`.

The order of work is:

1. Capture clean full-state BalatroBot traces.
2. Replay them through the parity checker with `--require-complete`.
3. Fill missing rules and joker/shop/pack effects until complete parity passes.
4. Use the fast gym/search loop to generate broad candidate policies; avoid
   fixed hand-family strategies as the shipped baseline.
5. Validate the trained or searched policy back through clean BalatroBot on
   multiple seeds.
