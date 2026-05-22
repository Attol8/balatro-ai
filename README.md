# balatro-ai-v2

Clean-slate Balatro AI experiment.

The first target is a correct, deterministic simulator with inspectable scoring.
Learning comes later, after search-based baselines are strong enough to generate
useful data.

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

## Fast Training Env

The training hot loop should use `balatro_ai_v2.fast`, not BalatroBot. The env
is designed to grow into full Balatro coverage with deterministic local
rollouts, fixed 512-action tactical encoding, compact observations, and no
network or rendering dependency.

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

## Verify

```bash
python -m pytest
```
