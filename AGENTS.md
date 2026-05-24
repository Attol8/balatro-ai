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
  `scripts/train_fast_imitation_policy.py`, and
  `scripts/evaluate_fast_imitation_policy.py` as the dependency-free first
  training loop. The fast full-game gym now exposes explicit run actions:
  select/skip blind, cash out, next round, reroll, buy cards/packs/vouchers,
  sell jokers, use consumables, and select/skip opened packs. The default model is a
  linear legal-action ranker; the nearest neighbor mode is for
  memorization/debugging only. This loop imitates the current search oracle;
  improve the oracle/evaluator before treating model accuracy as strategically
  meaningful.
- Use `scripts/run_balatrobot_agent.py --full-action-model ...` for real-game
  replay of full-run policies. The older `--imitation-model` path only controls
  tactical play/discard decisions and is not enough to validate fast full-action
  policy strength.
- The explicit fast shop is still a deterministic parity-shaped approximation,
  not the real Balatro shop RNG. It currently models weighted joker/planet shop
  cards, booster specs, persistent shop vouchers, rerolls, discounts, extra
  hands/discards/slots, economy vouchers, and pack choices that fit the current
  8-card tactical action encoding. Use it to train full-action policies, then
  validate and correct behavior with BalatroBot traces.
- Use `scripts/generate_fast_oracle_data.py --shop-rollout` when you want the
  slower `RolloutSearchRunAgent` shop oracle. This clones fast shop states,
  tries legal shop candidates, rolls forward cheaply, and labels the action with
  best future progress. Tune its budget with `--shop-rollout-candidates` and
  `--shop-rollout-steps`; do not broaden seed sweeps blindly if a rollout budget
  is too slow. Current checkpoint: after replacement-aware joker sells and
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
