# balatro-ai-v2

Balatro AI experiments focused on measurable real-game playing strength.
The live runner evaluates public-information policies against actual Balatro;
local scoring and search improve decisions, with real trajectories providing feedback.

## Real-game evaluation

Run complete **Red Deck / White Stake** games against a running BalatroBot server:

```bash
python -m balatro_ai_v2.live run --policy search --episodes 5 --output runs/dev-001
```

The server defaults to `127.0.0.1:12346`. Start it using your installed BalatroBot
launcher if necessary (for example,
`BALATROBOT_ALL_UNLOCKED=1 uvx balatrobot serve --fast --headless`).
The CLI requires the all-unlocked evaluation profile by default. Use
`--profile-mode career` for a separate career-profile experiment; do not pool its
results with all-unlocked runs.
The runner accepts an idle menu or a finished game. Use `--reset` to explicitly
replace an active game. It resets between its own episodes, stops on execution
errors, and never retries a potentially applied action after an RPC timeout.

`--policy baseline` selects the initial simple policy: approximate hand scoring with current
hand levels, basic discards and boss constraints, conservative joker purchases,
supported consumables, and pack selection. It handles all playable phases but
does not implement every strategic action: vouchers, rerolls, and rearrangement
are currently unused. Scoring is **not** simulator parity, and many joker
interactions and boss effects are unmodeled. This is a baseline for improvement,
not a claim of reliable wins.

`--policy strategic` reuses a frozen public strategic policy and broader phased
scorer from later local repository history. It adds typed observations and legal
actions, public history, richer Joker/card effects, ordering, and broader shop and
consumable decisions. See [solver provenance](balatro_ai_v2/solver/README.md).
Historical results do not establish the playing strength of this imported artifact;
new runs measure it directly.

`--policy search` adds bounded public draw lookahead and scoring-based joker
purchases/replacements. Its first settled control won **1/20 development runs**,
including a confirmed real Ante-8 clear on `D0000001`; this is **not reliable**.
The completed imported
strategic comparison lost all 20 development runs. See [the evolving evidence and
experiment plan](plan.md); development results are not held-out performance.

Experimental variants keep that search control unchanged:

- `search-planets`: also compares immediate planet upgrades against shop offers.
- `search-green`: models Green Joker's discard penalty during draw lookahead.
- `search-boss`: projects Needle and Flint into shop scoring estimates.
- `search-order`: checks adjacent hand/joker ordering before a non-clearing play.
- `search-hidden`: remembers a narrowly supported inventory through Amber Acorn,
  comparing hands across every possible joker ordering without revealing positions.
- `search-placement`: values Blueprint in available positions and executes the
  required purchase/reorder plan before discretionary spending.
- `search-v2`: combines Green, boss, ordering, hidden-inventory, and placement changes.
- `search-v3`: restricts purchase priority to Blueprint; its development batch won
  2/20 runs, versus 1/20 for V2 and the initial search control.
- `search-v4`: adds static-debuff refill search and preserves early Green Joker plays;
  its completed development batch won 3/20 runs, with no execution errors.
- `search-v5`: extends the reroll limit from two to five only below forecast pace,
  retaining enough cash for a subsequent purchase; it won the same 3/20 development
  seeds as V4 and is not promoted.
- `search-v6`: adds candidate-specific suit/face boss debuffs to V4's shop forecasts,
  including Wild/Smeared/Pareidolia interactions. It does not include V5's spending
  change. Its completed batch won the same 3/20 seeds. History-dependent and
  random-disabling bosses remain unsupported.
- `search-v7`: adds current-ante boss readiness to V6, balancing it against the
  immediate blind. A visible supported boss deficit permits up to four rerolls
  per shop and six across the ante, with complete public history and purchase
  cash protected. It stress-tests the current build, not future growth or decay.

Each variant is an ablation, not an established improvement. Draw estimates use
eight shared samples; shop estimates use six synthetic hands and approximate
continuations. Unsupported state transitions retain the strategic fallback.
The runner waits for two identical public snapshots between actions to allow
queued effects to settle; this remains bounded polling, not engine synchronization.

Each new output directory contains:

- `manifest.json`: seeds, configuration, policy/source fingerprint, and server metadata.
- `0000-SEED.jsonl`, etc.: public observations, chosen actions, reasoning,
  approximate score estimates, actual score deltas, errors, and results.
- `summary.json`: victory rates, confidence interval, completed-run peak-score
  distribution, ante reached, and losses grouped by blind, with each run's final context.

The raw API exposes private information. Policies and trajectories exclude the
seed, ordered draw/discard piles, private iteration order, and face-down identities.
The seed remains in episode metadata solely for reproducibility. Public unordered
deck composition is retained. The strategic policy additionally receives a typed
whitelisted observation, including unordered public Remaining-view counts that
combine the draw pile with face-down hand cards. It never receives the surrounding
API dictionaries or raw ability trees. No score oracle or checkpoint search is used.

Default development seeds are `D0000000`, `D0000001`, etc. Reserve the separate
held-out series for evaluation, and do not tune against its outcomes:

```bash
python -m balatro_ai_v2.live run --split heldout --episodes 20 --output runs/heldout-001
python -m balatro_ai_v2.live run --seeds D0000000 D0000001 --output runs/comparison-001
```

Use `--seed-offset` to select a different section of a generated series. Explicit
`--seeds` determines batch size instead of `--episodes`; when supplying your own
seeds, you are responsible for keeping development and held-out sets disjoint.
Compare policies on the same seeds, game/mod versions, and unlock profile.

By default, episodes stop on a confirmed victory: the game's flag must be set
and the displayed ante must have advanced past 8. The installed game can set its
flag even on a final-boss loss; traces preserve that as `reported_won` while
`won` records confirmed success. Use `--endless`
to continue until game over, entering ante 17 (adjust with `--max-ante`), or the
decision limit. Ante-eight victory remains recorded even after an endless loss.
Errors and truncations are separate from game losses. The headline attempted-run
win rate includes all attempted episodes; the completed-run metric excludes
errors/truncations, and unattempted seeds are reported explicitly. Score statistics
use completed episodes only. Small batches do not establish playing strength.

Replay the current policy on a recorded trajectory without connecting to the game:

```bash
python -m balatro_ai_v2.live replay runs/dev-001/0000-D0000000.jsonl
```

Replay reports action agreement and differences. It is **offline decision replay**,
not engine restoration or a claim that a changed policy would reach the same
future states. Interrupted traces can replay their intact records. The command
exits nonzero for differences or incomplete traces; batch execution exits nonzero
for errors/truncations, while genuine game losses are successful executions.

## Optional public-only simulation (shadow experiment)

The candidate simulator is **not integrated into live decisions**. It reconstructs
fresh states from typed public observations and history, never from the real
game's seed, hidden order, or save. The frozen compatibility wrapper and its
limits are recorded in [candidate provenance](balatro_ai_v2/solver/CANDIDATE_PROVENANCE.md).

With Python 3.12 and the pinned `candidate` extra installed, compare a recorded
shop decision without connecting to Balatro:

```bash
python -m balatro_ai_v2.solver.shadow_blind \
  --trace runs/search-stable-001/0001-D0000001.jsonl --decision 4 \
  --samples 8 --output runs/shadow-example/d1-4.json
```

This evaluates visible Joker purchases, immediate Planet use, and leaving, then
leaves the shop and plays the next ordinary Small/Big Blind with a fresh fixed
strategic continuation. Each action uses the same public-derived particles. It
stops before cashout and new-shop generation; bosses, generated packs and other
consumable actions are excluded. Step limits and unsupported simulations remain
explicitly inconclusive, never counted as losses or silently dropped from rates.
These are model comparisons, not win-rate evidence or calibrated probabilities.
Python 3.11 live play remains independent of this optional dependency.

See [plan.md](plan.md) for the design and next experiments.

## Legacy simulator experiments

The modules below remain available for comparison and small scoring tests. They
are incomplete game models, not the source of truth for live win rates or the
current training recommendation.

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

The legacy training hot loop uses `balatro_ai_v2.fast`, not BalatroBot. The env
was designed to grow into full Balatro coverage with deterministic local
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
