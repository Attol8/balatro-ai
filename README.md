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
representation from Jackdaw's own state. Historical schema-v4 campaigns cover
1,073 exact transitions, all in losing runs; schema v5 now records permanent
playing-card bonuses, and two fresh seed-1 runs reproduce 48/48 observed
transitions exactly. On Red/White seeds 1-100,
the frozen public greedy and deterministic-random controls both won 0/100 in
the candidate; their seed-1 policies then reproduced in real Balatro for 18/18
and 11/11 transitions respectively. A fair one-ply public draw policy improved
average ante from 1.05 to 1.23 but still won 0/100, ran at only 2.80 decisions/s,
and reproduced its seed-1 terminal loss for 27/27 real transitions. These are
honest strength floors, not a solver. Process-isolated public recurrent training
is operational, but raw PPO, behavior cloning, and the first strategic hybrid
still have zero wins. A frozen public-only strategic baseline improves average
round from 2.22 to 7.29 on the same candidate panel, but also wins 0/100. Its
unchanged seed-1 policy reproduces 23/23 real Balatro transitions exactly and
loses at ante 1. Strategic behavior cloning reaches 6.84 rounds and a bounded
20,480-step public-return PPO continuation reaches 7.03; both win 0/100 and are
below the heuristic, so that tuning lane is closed. The immediate bottleneck is
public tactical scoring that ignores owned-joker synergies, not optimizer
choice. A first public-only scoring repair raises the dirty development panel
from 7.29 to 7.86 average rounds but still wins 0/100. Balatro's in-memory restore is exact
on the tested branch but only modestly faster than file restore, so it will
serve as an oracle/audit worker while Jackdaw carries high-volume training.

Public policies now run in a separate JSON-lines child process. The child sees
only a strict `PublicObservation`, a bounded public legal-action set, and its
own accumulated public history. The parent enforces frame limits and deadlines,
echoes request IDs and observation digests, and independently rejects stale,
noncanonical, out-of-set, or illegal actions. This prevents accidental access
to Jackdaw or BalatroBot objects; it is not an OS sandbox for hostile code.
Clean isolated panels preserved the baseline outcomes: greedy and random both
won 0/100, while tactical won 0/20 with average ante 1.30. The isolated
tactical seed-1 policy reproduced 27/27 transitions in real Balatro and lost.

Jackdaw is pinned in `kernels/jackdaw.lock.json` but is deliberately marked
untrusted. Its optional environment requires Python 3.12:

```bash
python3.12 -m pip install '.[candidate]'
```

The full design and kill criteria are in [plan.md](plan.md).
