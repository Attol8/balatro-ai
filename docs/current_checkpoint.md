# Current Checkpoint

Date: 2026-05-24

## Stable State

The fast gym has moved from tactical-only play/discard training to explicit
full-run actions:

- blind select and skip
- cash out and next round
- shop reroll
- buy shop card, pack, and voucher
- sell joker
- use consumable
- pack select and skip

The fast shop is deterministic and training-oriented. It now includes weighted
joker/planet shop cards, booster spec costs/sizes/choices, persistent voucher
offers, rerolls, discounts, extra hands/discards/slots, economy vouchers, and
pack choices that fit the current 8-card tactical action encoding.

## Verified Results

Full test suite:

```bash
python -m pytest
```

Result: 172 passed.

Fast full-action smoke with voucher shop expansion:

The scratch files from this smoke were intentionally removed after recording the
metrics, so these commands are a historical reproduction recipe rather than live
inputs for future runs.

```bash
python scripts/generate_fast_oracle_data.py --deck b_red --seed-start 1 --seeds 4 --max-steps 80 --output-jsonl runs/fast_full_action_voucher_oracle_smoke.jsonl
python scripts/train_fast_imitation_policy.py --data-jsonl runs/fast_full_action_voucher_oracle_smoke.jsonl --output-model runs/fast_full_action_voucher_linear_smoke.json --model-type linear --epochs 2
python scripts/evaluate_fast_imitation_policy.py --model runs/fast_full_action_voucher_linear_smoke.json --deck b_red --seed-start 1 --seeds 4 --max-steps 80
```

Result: 320 examples, 0 terminal wins, 0.7125 training accuracy, 0 real wins,
5.75 average fast-gym rounds cleared.

Visible BalatroBot replay of that trained model:

The trace and smoke model from this run were also intentionally removed after
recording the metrics. Future BalatroBot tests should generate fresh traces from
the current adapter and policy.

```bash
python scripts/run_balatrobot_agent.py --launch-server --fast-server --no-headless-server --deck RED --stake WHITE --seed-start 1 --seeds 1 --max-steps 250 --poll-delay 0.05 --trace-jsonl runs/red_deck_seed1_visible_policy_try.jsonl --imitation-model runs/fast_full_action_voucher_linear_smoke.json
python scripts/game_parity_gate.py runs/red_deck_seed1_visible_policy_try.jsonl
```

Result: 0 wins, ante 1, 18 steps. Parity gate checked 18/18 transitions, 5
scores, and 6 draws with 0 mismatches and 0 unchecked transitions.

## Important Interpretation

The fast trained-policy result did not reproduce as policy strength in
BalatroBot. The reason is not an observed parity mismatch in the visible trace.
The reason is a policy-contract mismatch:

- fast evaluation used a full-action model inside `FastFullGameEnv`
- live BalatroBot used the model only for tactical play/discard decisions
- live blind, shop, voucher, and pack decisions still used the heuristic
  BalatroBot planners

Therefore, fast-gym average rounds are not valid solve evidence until the same
full-action policy is replayed through BalatroBot phase by phase.

## Next Required Work

Implemented full-action model replay through BalatroBot after this checkpoint
was written:

1. Live observations now use the same full-run layout as `FastFullGameEnv`.
2. Legal fast action ids are built for blind, round-eval, shop, pack, and
   tactical phases.
3. Predicted full-action ids are converted into `GameAction` RPCs.
4. `scripts/run_balatrobot_agent.py` accepts `--full-action-model`.
5. Visible BalatroBot replay was run with a scratch full-action model.

Visible full-action replay result:

```bash
python scripts/run_balatrobot_agent.py --launch-server --fast-server --no-headless-server --deck RED --stake WHITE --seed-start 1 --seeds 1 --max-steps 250 --poll-delay 0.05 --trace-jsonl /private/tmp/red_deck_seed1_full_action_visible.jsonl --full-action-model /private/tmp/balatro_full_action_model.json
python scripts/game_parity_gate.py /private/tmp/red_deck_seed1_full_action_visible.jsonl
```

Result: 0 wins, ante 1, 16 steps. The model selected blinds, cashed out, bought
a voucher, advanced to the next round, and chose tactical play/discard actions.
Parity checked 16/16 transitions, 5 scores, and 6 draws with 0 mismatches and 0
unchecked transitions.

The replay contract now exists, but policy quality is still poor. The next
useful work is to compare fast and live action choices on the same seed and fix
remaining observation/action mismatches before improving oracle search or
training quality.

## Fast-vs-Live Policy Gap

A follow-up comparison used the same scratch full-action model on fast seed 1
and visible BalatroBot seed 1.

Fast seed 1 did not fail early. It reached 7 cleared rounds within the 80-step
cap:

```text
FAST seed=1 won=False rounds=7 ante=3 phase=SELECTING_HAND steps=80
```

Visible BalatroBot seed 1 still failed at ante 1 in 16 steps:

```text
LIVE seed=1 won=False ante=1 round_num=2 state=GAME_OVER steps=16
```

The divergence begins at the first hand, before shop logic:

```text
fast first hand: H_A C_K H_K S_Q C_J D_J D_8 C_4
live first hand: S_A S_9 D_8 H_7 S_5 D_3 H_2 C_2
```

Consequences:

- Fast predicted an immediate play on the first hand.
- Live predicted two discards, then a play.
- Fast reached the first shop with $8 and bought `j_mystic_summit`.
- Live reached the first shop with $10, making the voucher legal, and bought
  `v_crystal_ball`, leaving $0.

This explains why the fast 5.75 average did not reproduce: the trained policy is
being evaluated on a fake fast card stream and fake fast shop stream. The
BalatroBot trace itself still passes transition parity for observed actions, but
the fast rollout is not starting from equivalent hidden deck/shop RNG state.

Next root-cause work: make `FastFullGameEnv` consume BalatroBot-compatible deck
order and shop/voucher generation for a seed, or build replay training from
BalatroBot traces instead of treating the current deterministic fast RNG as
reproduction evidence.

## Real-State DAgger Replay

The hand-phase failure was confirmed. On the live seed-1 first hand, the
full-action linear model discarded five cards, while the BalatroBot planner
would play the pair of 2s. A second failure appeared after the first correction:
nearest-neighbor replay fixed that first hand, then drifted on later hand states
and lost even faster.

Implemented a real-state training bridge:

- `balatro_ai_v2.learning.balatrobot_traces` converts full-state BalatroBot
  JSONL traces into the same `TrajectoryStep` JSONL rows used by the existing
  trainer.
- `scripts/generate_balatrobot_trace_oracle_data.py` labels each recorded
  BalatroBot `transition.before` state with the current `BalatroBotPolicy`
  oracle, validates the label against live legal full-action ids, and writes
  training rows.
- `game_action_to_full_fast_action()` maps planner `GameAction`s back to full
  fast action ids so live oracle labels can train the same policy interface.
- Full-action observations now include visible shop pack offers in both fast
  and live BalatroBot adapters.
- State-action features now include target item identity/slot features so shop
  actions can distinguish buying slot 0 from buying slot 1.

Visible real-game DAgger result on seed 1:

```bash
python scripts/run_balatrobot_agent.py --launch-server --fast-server --no-headless-server --deck RED --stake WHITE --seed-start 1 --seeds 1 --max-steps 120 --poll-delay 0.05 --trace-jsonl /private/tmp/balatro_dagger2_live_seed1.jsonl --full-action-model /private/tmp/balatro_dagger2_nearest.json
python scripts/game_parity_gate.py /private/tmp/balatro_dagger2_live_seed1.jsonl
```

Result: 0 wins, ante 4, 71 steps. Parity checked 71/71 transitions, 28 scores,
and 3 draws with 0 mismatches and 0 unchecked transitions. A direct replay diff
against `BalatroBotPolicy()` showed 0 action differences. This means the trained
full-action replay can now reproduce the planner on the real visible path; the
remaining bottleneck is planner/oracle strength past ante 4, not BalatroBot
action replay parity.

Fast smoke after DAgger nearest replay:

```text
seeds 1..8, max_steps=120: 0 wins, 6.5 average rounds cleared
```

Do not treat the nearest-neighbor model as a solve candidate. It is a parity and
data-aggregation tool that proves real trace states can train/replay through the
same full-action policy contract. The next strategic work is improving the
oracle/shop/tactical planner so the labels themselves can clear ante 8 across
multiple real seeds.

## Shop Rollout Oracle

Started the stronger-oracle path by adding an opt-in fast shop rollout agent:

- `RolloutSearchRunAgent` subclasses `SearchRunAgent`.
- The default `SearchRunAgent` remains fast and heuristic.
- `RolloutSearchRunAgent` only performs rollout at shop states.
- For each candidate shop action, it clones the fast environment, applies the
  candidate, rolls forward with cheap greedy/tactical heuristics, and scores
  final progress by rounds cleared, ante, blind progress, money, joker
  portfolio, hand levels, and survival.
- `scripts/generate_fast_oracle_data.py --shop-rollout` generates training rows
  from this slower oracle.
- `scripts/train_fast_agent.py --shop-rollout` evaluates this oracle directly.
- `--shop-rollout-candidates` and `--shop-rollout-steps` make the rollout budget
  explicit for both generation and direct evaluation.
- Shop replacement is now explicit: the heuristic and rollout candidate ranker
  only sell a filled-slot joker when the visible shop/voucher state can pay off
  the replacement.
- Owned jokers are filtered out of generated shop joker offers and buffoon pack
  offers so fast wins cannot rely on non-parity duplicate joker acquisition.

Fast smoke:

```bash
python scripts/train_fast_agent.py --deck b_red --seed-start 1 --seeds 4 --max-steps 40
python scripts/train_fast_agent.py --deck b_red --seed-start 1 --seeds 4 --max-steps 40 --shop-rollout
```

Result:

```text
SearchRunAgent:        0 wins, 5.0 average rounds cleared
RolloutSearchRunAgent: 0 wins, 5.5 average rounds cleared
```

Training smoke:

```bash
python scripts/generate_fast_oracle_data.py --deck b_red --seed-start 1 --seeds 4 --max-steps 40 --shop-rollout --output-jsonl /private/tmp/balatro_rollout_oracle_smoke.jsonl
python scripts/train_fast_imitation_policy.py --data-jsonl /private/tmp/balatro_rollout_oracle_smoke.jsonl --output-model /private/tmp/balatro_rollout_nearest_smoke.json --model-type nearest
python scripts/evaluate_fast_imitation_policy.py --model /private/tmp/balatro_rollout_nearest_smoke.json --deck b_red --seed-start 1 --seeds 4 --max-steps 40
```

Result: 160 examples, nearest-neighbor replay at 5.5 average rounds cleared.
The linear model still failed badly on this data, so the current learning
bottleneck is representation/model capacity, while the strategic bottleneck is
still the oracle itself.

Current stronger-oracle smoke:

```bash
python scripts/train_fast_agent.py --deck b_red --seed-start 1 --seeds 2 --max-steps 180 --shop-rollout --shop-rollout-candidates 4 --shop-rollout-steps 12
```

Result:

```text
RolloutSearchRunAgent: 1 win, 22.5 average rounds cleared
sample_seed: 1
sample_rounds_cleared: 24
sample_won: True
sample_steps: 173
```

This is a fast-gym oracle checkpoint, not a BalatroBot solve. The same policy
still needs clean real-game replay through `scripts/game_parity_gate.py`.

## Live Policy Generalization Checkpoint

The current useful path is not neural training yet. The bottleneck is still the
oracle/live planner: it must make stronger shop, replacement, reroll, blind-skip,
and boss-aware tactical decisions before imitation has labels worth learning.

Implemented after the shop-rollout checkpoint:

- Live shop planning now values modeled non-scoring/economy/run jokers such as
  Rocket, Drunkard, Juggler, Astronomer, and Certificate instead of rejecting
  them only because they do not directly score a hand.
- Late weak builds now suppress marginal planet/standard/arcana purchases and
  prefer rerolling or finding real carry/x-mult.
- Shop planning can sell a weak joker to afford a visible upgrade before joker
  slots are full.
- Blind skipping is stricter: Holographic/Foil tags no longer justify skipping
  a shop in ante 5+ unless the build already has real carry; Negative/Polychrome
  remain worth considering. Unscoped Orbital Tags are no longer skipped because
  visible BalatroBot state does not expose the target hand, and clean same-seed
  runs upgraded different hands after the same skip.
- Abstract Joker and Stencil scoring now count all live joker cards, including
  non-scoring/unimplemented jokers, through `ScoreContext.joker_count`.
- Tactical scoring now models boss hand restrictions such as The Mouth when
  replaying future hands in the beam search.
- Discard ranking is joker-aware for payoff jokers and hand-restriction bosses,
  so it can fish for the build's actual scoring shape instead of only the base
  hand score.

Visible BalatroBot result before removing unscoped Orbital skips:

```bash
python scripts/run_balatrobot_agent.py --launch-server --fast-server --no-headless-server --deck RED --stake WHITE --seed-start 1 --seeds 1 --max-steps 500 --poll-delay 0.05 --trace-jsonl runs/red_deck_seed1_visible_fast_cached_joker_discards.jsonl
python scripts/game_parity_gate.py runs/red_deck_seed1_visible_fast_cached_joker_discards.jsonl
```

Result:

```text
seeds: 1
wins: 0
avg_ante: 7.0
avg_steps: 166.0
parity: 166/166 transitions, 63 scores, 9 draws, 0 mismatches
```

This is still not a solve. It is a clean real-game parity checkpoint showing
the current live planner reaches ante 7 on red deck seed 1 and dies before ante
8. The next generalization test should be visible or trace-backed runs on seeds
1..8 or 1..16, judged by average ante/wins, not by whether seed 1 improves.

Follow-up visible rerun after the speed work exposed a reproducibility problem:
the same seed and same Orbital skip upgraded Three of a Kind in one run and Full
House in another. That later run passed parity but died at ante 4:

```text
seeds: 1
wins: 0
avg_ante: 4.0
avg_steps: 85.0
parity: 85/85 transitions, 35 scores, 4 draws, 0 mismatches
```

The current policy therefore avoids unscoped Orbital skips. Future performance
claims should use fresh traces generated after that change.

Fresh no-Orbital-skip visible runs on seed 1 reproduced exactly:

```bash
python scripts/run_balatrobot_agent.py --launch-server --fast-server --no-headless-server --deck RED --stake WHITE --seed-start 1 --seeds 1 --max-steps 500 --poll-delay 0.05 --trace-jsonl runs/red_deck_seed1_visible_fast_no_orbital_skip.jsonl
python scripts/run_balatrobot_agent.py --launch-server --fast-server --no-headless-server --port 12347 --deck RED --stake WHITE --seed-start 1 --seeds 1 --max-steps 500 --poll-delay 0.05 --trace-jsonl runs/red_deck_seed1_visible_fast_no_orbital_skip_repeat.jsonl
```

Both runs ended at ante 4 in 92 steps, and their transition/action/state
sequences were identical. Both parity gates reported 92/92 transitions, 35
scores, 5 draws, and 0 mismatches.

## Live Score Improvement Checkpoint

After the reproducible ante-4 baseline, the next useful improvement came from
shop replacement values rather than more blind skips:

- Late weak full-slot builds now accept smaller positive replacements for
  implemented scoring jokers instead of spending the same money on blind rerolls
  or leaving the shop.
- Ride the Bus now has an explicit shop value as a scaling joker.
- Type-specific jokers now scale their shop value with the observed hand family
  play count. This made Sly valuable in the Pair-heavy seed-1 route instead of
  treating it as a flat marginal joker.

Visible BalatroBot result:

```bash
python scripts/run_balatrobot_agent.py --launch-server --fast-server --no-headless-server --port 12350 --deck RED --stake WHITE --seed-start 1 --seeds 1 --max-steps 500 --poll-delay 0.05 --trace-jsonl runs/red_deck_seed1_visible_fast_type_joker_values.jsonl
python scripts/run_balatrobot_agent.py --launch-server --fast-server --no-headless-server --port 12352 --deck RED --stake WHITE --seed-start 1 --seeds 1 --max-steps 650 --poll-delay 0.05 --trace-jsonl runs/red_deck_seed1_visible_fast_type_joker_values_repeat.jsonl
```

Both runs reproduced exactly:

```text
seeds: 1
wins: 0
avg_ante: 7.0
avg_steps: 179.0
parity: 179/179 transitions, 65 scores, 11 draws, 0 mismatches
```

The current reproducible bottleneck is ante 7 boss The Mouth. The build reaches
the boss with Rocket, Sly, Abstract, Trio, and Duo, but locks the round into Two
Pair and ends around 21k/70k. The next likely improvement is tactical: The Mouth
planning should reason harder about which first hand type to commit to, probably
favoring Full House/Pair-family lines that exploit Duo/Trio and the existing
Full House levels instead of settling for repeated Two Pair.

Speed note:

- The joker-aware discard search made late decisions too slow because it was
  reranking too many discard outcomes with full joker scoring.
- Exact deterministic base-hand-score caching plus a 72-candidate joker-aware
  discard shortlist preserved all 72 observed hand decisions from
  `runs/red_deck_seed1_visible_fast_cached_joker_discards.jsonl`.
- Offline replay of those 72 hand decisions improved from about 256s to 172s
  with zero action mismatches. This is better but still too slow for broad live
  sweeps; further work should optimize the discard evaluator structurally before
  increasing search budgets.
