# balatro-ai-v2

This repository is rebuilding toward a fair, superhuman Balatro agent. It does
not currently contain a trained model or a solved policy.

The previous independent simulator, heuristic planner, imitation pipeline, and
parity gate were removed because they could report success without reproducing
the same policy and transitions in Balatro. The rebuild starts with the two
contracts that cannot be compromised:

- Balatro under BalatroBot/LÖVE is the authority.
- A policy receives only information visible to a normal player.

## What exists

- Frozen typed public observations. Seed, raw IDs, draw order, face-down card
  identity, internal ability trees, RNG, and event state cannot cross the
  policy boundary.
- Typed public actions with verified phase, capacity, affordability, and slot
  validation before RPC execution. Safe no-target Planets are encoded; targeted
  consumables whose complete public legality is unknown remain fail-closed.
- A strict BalatroBot backend that requires two stable reads at a real decision
  boundary. It never auto-skips, substitutes a poll for a rejected action, or
  force-accepts a changing state.
- Canonical observed-state hashing with stable entity IDs and fail-closed schema
  checks.
- Exclusive, hash-chained traces containing source/config/model/backend
  provenance and an explicit complete/incomplete terminal reason.
- A backend-neutral differential replay harness with no waivers or tolerances.

BalatroBot does not expose its RNG and event queues, so the current claim is
only exact *observed-state lockstep*. Game-native file and in-memory snapshots
have replayed one eight-action branch exactly, but complete Lua-state fidelity
and whole-engine parity remain unproven.

## Verify

```bash
python -m pytest -q
```

Run the deliberately weak public-information integration policy against a
BalatroBot server:

```bash
python scripts/run_authority_smoke.py \
  --seed 17 \
  --balatrobot-version <exact-version-or-revision> \
  --game-version <exact-game-build> \
  --runtime-version <exact-love-luajit-build> \
  --trace-jsonl runs/evidence/red-white-seed17.jsonl
```

Add `--launch-server` to let the script start and stop BalatroBot. Evidence
files are created exclusively; an existing path is never appended or
overwritten. Version flags are mandatory when writing evidence because the
current BalatroBot health endpoint may report only `status=ok`.

Reproduce every recorded public action in a fresh real run and compare the full
canonical observed state after each decision:

```bash
python scripts/replay_observed_lockstep.py \
  runs/evidence/red-white-seed17.jsonl \
  --launch-server
```

## What comes next

Jackdaw is pinned. Its raw bridge initially differed from BalatroBot in 638
initial-state fields; a narrow adapter now derives the equivalent BalatroBot
representation from Jackdaw's own state. Clean schema-v4 campaigns currently
cover 1,017 exact transitions, all in losing runs. The next gate is broader
randomized action/rule lockstep plus fair public-only baselines. Balatro's
in-memory restore is exact on the tested branch but only modestly faster than
file restore, so it will serve as an oracle/audit worker while Jackdaw carries
high-volume search and training. A learned policy/value model follows search,
not the other way around.

Jackdaw is pinned in `kernels/jackdaw.lock.json` but is deliberately marked
untrusted. Its optional environment requires Python 3.12:

```bash
python3.12 -m pip install '.[candidate]'
```

The full design and kill criteria are in [plan.md](plan.md).
