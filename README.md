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
  validation before RPC execution. Consumable actions whose complete public
  legality is not yet encoded are deliberately omitted.
- A strict BalatroBot backend that requires two stable reads at a real decision
  boundary. It never auto-skips, substitutes a poll for a rejected action, or
  force-accepts a changing state.
- Canonical observed-state hashing with stable entity IDs and fail-closed schema
  checks.
- Exclusive, hash-chained traces containing source/config/model/backend
  provenance and an explicit complete/incomplete terminal reason.
- A backend-neutral differential replay harness with no waivers or tolerances.

BalatroBot does not expose its RNG and event queues, so the current claim is
only exact *observed-state lockstep*. Snapshot fidelity and whole-engine parity
remain unproven.

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
representation from Jackdaw's own state. The candidate matches all five
transitions in the seed-1 smoke trace, but remains untrusted beyond that tiny
losing run. The next gate is broad randomized candidate lockstep over the full
action/rule surface. In parallel, BalatroBot needs an in-memory
snapshot/restore and batched rollout extension whose RNG and branch isolation
are proven before it can generate search labels. Search and a learned
policy/value model come only after those gates pass.

Jackdaw is pinned in `kernels/jackdaw.lock.json` but is deliberately marked
untrusted. Its optional environment requires Python 3.12:

```bash
python3.12 -m pip install '.[candidate]'
```

The full design and kill criteria are in [plan.md](plan.md).
