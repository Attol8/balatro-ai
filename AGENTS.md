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

The order of work is:

1. Capture clean full-state BalatroBot traces.
2. Replay them through the parity checker with `--require-complete`.
3. Fill missing rules and joker/shop/pack effects until complete parity passes.
4. Only then use the fast gym/search loop to train or tune a policy.
5. Validate the trained policy back through clean BalatroBot on multiple seeds.
