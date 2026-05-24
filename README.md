# balatro-ai-v2

Clean-slate Balatro AI experiment.

The first target is a correct, deterministic simulator with inspectable scoring.
Learning comes later, after broad search-based baselines are strong enough to
generate useful data. Fixed hand-family strategies are debugging baselines, not
the solving plan.

## Current vertical slice

- immutable-ish card and deck primitives
- deterministic seeded deck shuffling
- base Balatro poker-hand classification
- inspectable scoring event log
- minimal blind state transitions for plays and discards
- exhaustive hand-play search for a single play
- BalatroBot JSON-RPC client for real-game validation and execution
- fast integer-card training env with fixed action ids and legal action masks
- source-derived rule coverage inventory helpers
- canonical action model shared by the fast env and BalatroBot
- run/economy scaffold for blind progression, rewards, interest, and shop phase
- deterministic full-run fast gym that advances blinds, shops, antes, and red-deck
  ante-8 evaluation

## Fast Training Env

The training hot loop should use `balatro_ai_v2.fast`, not BalatroBot. The env
is designed to grow into full Balatro coverage with deterministic local
rollouts, fixed tactical action ids plus explicit run-level actions, compact
observations, and no network or rendering dependency.

```python
from balatro_ai_v2.fast import FastBalatroEnv

env = FastBalatroEnv(required_score=300)
obs = env.reset(seed=1)
action_mask = env.action_mask()
result = env.step(env.greedy_play_action())
```

Policies should emit `GameAction`, then convert it either to a fast tactical
action id or a BalatroBot RPC call. That keeps training and real-game execution
on the same action contract.

Benchmark:

```bash
python scripts/benchmark_fast_env.py --episodes 10000
```

Full-game red-deck evaluation:

```bash
python scripts/evaluate_fast_full_game.py --deck b_red --seed-start 1 --seeds 32
python scripts/train_fast_agent.py --deck b_red --seed-start 1 --seeds 32
```

BalatroBot reproduction, with BalatroBot serving on `127.0.0.1:12346`:

```bash
python scripts/run_balatrobot_agent.py --deck RED --stake WHITE --seed-start 1 --seeds 8
```

For faster clean BalatroBot runs, let the script launch BalatroBot with its
headless fast settings:

```bash
python scripts/run_balatrobot_agent.py --launch-server --deck RED --stake WHITE --seed-start 1 --seeds 8
```

If you launch BalatroBot yourself, start it with the same server-side speed
settings before running the agent:

```bash
uvx balatrobot serve --headless --fast --no-shaders --gamespeed 10 --animation-fps 60
```

Clean runs can be recorded as JSONL evidence. Use compact traces for quick
policy analysis, or omit `--trace-compact` to store full BalatroBot states.

```bash
python scripts/run_balatrobot_agent.py --deck RED --stake WHITE --seed-start 1 --seeds 3 \
  --trace-jsonl runs/red_deck_clean.jsonl --trace-compact
```

Fast simulator results only count after replaying a full, clean BalatroBot trace
through the parity checker. This catches scoring, draw-order, shop, round, and
other transition mismatches between the local hot loop and the game.

```bash
python scripts/run_balatrobot_agent.py --deck RED --stake WHITE --seed-start 1 --seeds 3 \
  --trace-jsonl runs/red_deck_full.jsonl
python scripts/replay_balatrobot_trace.py runs/red_deck_full.jsonl
```

Use the complete gate before treating any fast result as real:

```bash
python scripts/game_parity_gate.py runs/red_deck_full.jsonl
```

If this reports unchecked transitions, those are missing simulator/parity rules.
If rule coverage is incomplete, the fast simulator does not yet cover the full
game object surface. Do not treat a fast ante-8 result as solved until both
gates pass for the relevant seeds.

Policy tuning should happen through search and evaluator work, not one-off code
edits or a fixed flush lane. The shipped fast baseline scores every legal hand
family and discard mask, tracks the hand families a run actually uses, and
levels the strongest observed hand instead of forcing one target family. The
BalatroBot policy search script evaluates sampled policy configs through clean
BalatroBot runs and stores every candidate with its seed set and metrics.

The first training loop is search-imitation:

```bash
python scripts/generate_fast_oracle_data.py --deck b_red --seed-start 1 --seeds 64 \
  --output-jsonl runs/fast_oracle_trajectories.jsonl
python scripts/train_fast_imitation_policy.py \
  --data-jsonl runs/fast_oracle_trajectories.jsonl \
  --output-model runs/fast_imitation_policy.json
python scripts/evaluate_fast_imitation_policy.py \
  --model runs/fast_imitation_policy.json --deck b_red --seed-start 1 --seeds 64
```

This model is dependency-free and intentionally simple: by default it trains a
linear state-action ranker over legal full-run actions. The full-game gym now
requires the agent to choose blind, round-eval, shop, voucher, consumable, pack,
and tactical play/discard actions instead of hiding shop behind auto-buy logic.
The deterministic shop path includes weighted joker/planet cards, booster-spec
pack costs/sizes/choices, rerolls, discounts, and supported run-modifier
vouchers; it is still a training approximation until replayed through clean
BalatroBot parity traces. A `--model-type nearest` baseline is also available
for memorization/debugging.
Neither is the final agent; the point is to create a stable data/model contract
for later value heads, model-guided search, and BalatroBot validation.

To replay a full-action model through the real game, use the full-action flag.
This is the required reproduction path for fast full-run policies; the older
`--imitation-model` flag only controls tactical play/discard decisions.

```bash
python scripts/run_balatrobot_agent.py --launch-server --fast-server --no-headless-server \
  --deck RED --stake WHITE --seed-start 1 --seeds 1 \
  --full-action-model runs/fast_imitation_policy.json \
  --trace-jsonl runs/red_deck_full_action_replay.jsonl
python scripts/game_parity_gate.py runs/red_deck_full_action_replay.jsonl
```

```bash
python scripts/search_balatrobot_policy.py --deck RED --stake WHITE --seed-start 1 --seeds 3 --trials 12
```

## Verify

```bash
python -m pytest
```
