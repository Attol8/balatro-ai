# Superhuman Balatro at White Stake: Execution Plan

This file is the single active instruction set. An agent picking up this
project reads this file first, then `docs/plan-lab-notes.md` only for
evidence behind a claim made here. Historical stages, rejected ideas, and
run records live in the lab notes, not here. Anything in this file that
contradicts the code is a defect in this file; fix the file.

Rescoped 2026-09-03. The previous plan is preserved in the lab notes under
"Plan before the 2026-09-03 rescope" together with the evidence that
retired it.

## Objective

Build an agent that plays Red Deck at White Stake in real Balatro better
than a strong human, using only information visible through the normal
game interface, and continues into Endless to clear as many antes as it
can.

Two numbers, in priority order:

1. **Win rate**: fraction of runs that clear Ante 8. This is the
   superhuman claim. Strong humans win White Stake most of the time.
2. **Mean antes cleared** on paired evaluator-secret seeds, Endless
   continued until death or the cap. This is the score. It never
   saturates the way win rate does.

Gold Stake is deferred. Nothing in this plan targets stickers, faster
scaling, or fewer discards. When White is beaten, Gold gets its own plan.

## Why the plan was rescoped

Measured on 2026-09-03 (`control-v0`, commit `30e93eb`):

| Quantity | Value |
|---|---|
| Wins, both 200-seed panels | 13/400 |
| Mean antes cleared, tuning / gate | 3.575 / 3.855 |
| Losses with no x-mult Joker at death | 88% |
| Losses still playing Pair or Two Pair at death | 92% |
| Losses killed by a boss blind | 64% |
| Previous Stage 1 coverage gate | 23.8% of shop rows, needed 95% |
| Jokers with exact rules in the public scorer | 16 of 150 |
| Jokers implemented in Jackdaw | 150 of 150 |
| June 2026 rollout planner on Jackdaw (oracle, deleted) | 55 to 75% wins |

The gap to the objective is a factor of thirty in win rate. The retired
plan closed it by writing a second Balatro scorer inside the policy
firewall, one Joker at a time, and forbade any strategic decision from
using capacity until that scorer covered 95% of shop rows. Jackdaw
already implements every Joker, consumable, voucher, and boss. The
strongest artifact this project ever had was rollout search over that
simulator. It was deleted because it read hidden state, not because
search was wrong.

## The thesis

**The simulator is the value function.** A strategic decision is scored
by rolling sampled futures forward in Jackdaw and reading off what
happened. Hidden information in Balatro is exogenous chance (deck order,
future RNG), not an opponent's private state, so sampling it and treating
each sample as a perfect-information game is sound. The policy never
sees a sample; it sees only per-action values.

1. Every strategic decision (shop, pack, skip, voucher, consumable,
   blind select) is evaluated by determinized rollouts in Jackdaw.
2. Rollouts are continued by a public-only continuation policy. Its
   quality bounds search quality, so search results train it in turn.
3. A learned leaf value shortens rollouts only after search with full
   rollouts has shown what the gains are.

Hand-written strategic rules are not a lever. Every rule increment since
August moved wins by at most one on a 50-seed screen.

## Fixed constraints

These do not change. Any change to them is a new plan, not an edit.

- Real Balatro under BalatroBot is the only authority. Jackdaw results
  screen changes; they never count as results.
- The policy child, continuation policy, and value models see only
  `PublicObservation`, typed public history, typed public actions, and
  policy-owned randomness. Hidden deck order, RNG state, seed, raw object
  IDs, and private candidate state never cross the boundary. Unknown
  fields fail closed.
- Determinization runs in the evaluator parent. The parent returns to
  the decision only per-root scalar values and aggregate diagnostics,
  never sampled states, tapes, or hidden identities. A determinized
  state must be a function of public information and policy-owned
  randomness alone; the twin test and the round-trip test below are the
  proof, and they run in the suite.
- Development, tuning, gate, and authority seed panels are disjoint.
  Incomplete, rejected, timed-out, or illegal runs score zero antes.
- Every comparison is paired by seed with a bootstrap 95% interval on the
  per-seed delta. Nothing is retained because of a named seed.
- No timelines or effort estimates in this file.

## Vocabulary

| Term | Meaning |
|---|---|
| Antes cleared | Number of antes whose boss blind was beaten. Win is 8. Endless continues the count. A run that dies in Ante 3 cleared 2. |
| Determinization | A concrete Jackdaw game state whose public projection equals the current observation and whose hidden parts (draw order, RNG, unseen ante voucher) are sampled from policy-owned randomness. |
| Root | A legal public action at a strategic decision, evaluated by rollouts. |
| Sample | One determinization. Sibling roots share the same samples so comparisons are paired. |
| Horizon | Where a rollout stops: the next `horizon_antes` boss clears, game over, or the step cap. |
| Rollout value | Rounds cleared within the horizon, plus the fraction of the failed blind's requirement scored if the rollout died. Alive at the horizon scores the maximum. |
| Continuation policy | The public-only policy that finishes rollouts. Today `PublicStrategicPolicy` in `balatro_ai_v2/baselines.py`. |
| Control | The tagged, frozen policy every candidate is compared against. Today `control-v0`. |
| Panel | A fixed contiguous seed range. Tuning 1-200, gate 501-700, authority is evaluator-secret. |

## Where we are (measured 2026-09-03, commit d085a5f)

| Quantity | Value |
|---|---|
| Control wins, gate panel 501-700 | 6/200 |
| Control mean antes cleared, gate panel | 3.855 |
| Control survival to Ante 6, gate panel | 52/200 |
| Decisions per run, mean / max | 111 / 216 |
| Wall time per run through policy boundary, one worker | 1.5 s |
| Jackdaw clone + step | 3.5 ms |
| Performance cores available | 6 |
| Exact tactical solver on White Stake | Never runs. Gated to Gold in `blind_search.py:202` |
| Determinized search v2, screen seeds 1-30 (2026-09-04) | Mean antes 5.33 vs control 3.93, paired delta +1.40 [0.50, 2.30], 20 vs 11 to Ante 6, 2 vs 1 wins |
| Determinized search v2, replication seeds 31-60 | Mean antes 4.53 vs 3.93, paired delta +0.60 [0.13, 1.10], 30/30 complete, wins 2 vs 2 |
| Search throughput, one worker | 73 to 104 rollout steps/s; about 10 to 16 min per run at 6 samples, 1-ante horizon |

Solid: public-information firewall, isolated policy process, Jackdaw
lockstep replay with hash-chained traces, paired evaluator, Endless
metric, Jackdaw fidelity fixes from organic authority replays. Not solid:
strength.

## Stage A: Determinization

Build the one missing function and prove it leaks nothing.

- **Module.** New `balatro_ai_v2/determinize.py`, parent-only. It may
  import Jackdaw. It must never be importable from the policy child; the
  existing forbidden-prefix check covers it transitively and a test
  asserts that.
- **Contract.** `sample_candidate(backend, observation, history,
  sample_seed) -> JackdawBackend`. Deep-copies the candidate's private
  state and bridge compatibility fields, then scrubs: replaces the seed
  and RNG with `PseudoRandom(sample_seed)`, reshuffles the draw pile with
  the fresh RNG, re-rolls the ante voucher unless it is public (shop open
  now, or a shop was observed this ante in history). Fails closed on any
  face-down hand card, any open pack whose contents are not fully
  visible, and any phase other than the strategic phases and
  `SELECTING_HAND` with a fully visible hand.
- **Round-trip test.** The public projection of the scrubbed state
  equals the input observation. Runs on every sample, in the suite and
  at runtime; a mismatch raises and the decision falls back to the
  continuation policy, counted in diagnostics.
- **Twin test.** Two private states with identical public projection but
  different seed, RNG state, draw order, discard order, ante voucher,
  and object IDs produce identical scrubbed states under the same
  `sample_seed`, compared by canonical serialization of the game state
  with object IDs normalized. Extend `tests/test_information_firewall.py`.
- **Organic coverage.** Instrument the 200-run tuning panel: fraction of
  strategic decisions where determinization is available. Record it.

Gate: both tests pass, organic availability at strategic decisions is
above 99%, and the sample seed is derived only from the observation
digest, the search nonce, and the sample index.

## Stage B: Search at strategic decisions

- **Module.** New `balatro_ai_v2/determinized_search.py`, parent-only.
  `DeterminizedSearchPolicy` implements `PublicPolicy` and holds a
  reference to the live `JackdawBackend`. Tactical phases delegate to
  the continuation policy unchanged.
- **Roots.** All legal public actions at the decision except reorders.
  No pruning until a throughput measurement says it is needed.
- **Rollouts.** For each sample, apply each root to a fresh clone of that
  sample and continue with the continuation policy in-process until the
  horizon. Value as defined in the vocabulary. Aggregate mean over
  samples; ties go to the continuation policy's own choice.
- **Budget.** Start at 8 samples, horizon of 2 antes, 200-step cap.
  Record roots, samples, steps, and seconds per decision in every
  report. Raise the budget only with a recorded measurement.
- **Evaluator.** New `scripts/evaluate_determinized_search.py` emitting
  the same report schema as `evaluate_candidate_baselines.py` so
  `compare_candidate_reports.py` works unchanged. `--workers N` shards
  seeds across processes, one Jackdaw per worker.
- **Order of evidence.** A 50-seed screen on 1-50 against control first,
  to measure throughput and direction. Then the full tuning panel. The
  gate panel only for the vector that will be tagged.

Gate: paired antes cleared on 501-700 beats `control-v0` with the
bootstrap lower bound above zero. Tag `control-v1`. Kill: if search with
ten times the starting budget does not beat control, the rollout value
or the continuation is wrong. Inspect the twenty largest per-seed losses
before touching search knobs.

## Stage C: Tactical layer

Bosses kill 64% of runs. In-blind play is where boss counters are won.

- **Ungate.** Remove the Gold-only condition in `blind_search.py`. Re-pin
  its fixtures to constructed states. Measure the effect alone on the
  tuning panel before combining with Stage B.
- **Discards.** Raise `max_discard_cards` from one to five with a
  hand-type-aware target, or replace the exact enumerator with
  determinized rollouts over draws scoring clear probability. Choose by
  measurement on the same panel.
- **Boss blinds.** Extend whatever wins above from Small and Big to boss
  blinds, with the boss rule set Jackdaw already implements.

Gate: paired antes cleared improves over the current control, lower
bound above zero, with the strategic layer held fixed.

## Stage D: Continuation and expert iteration

Search quality is bounded by the continuation. Improve it from search.

- **Targets.** Every strategic decision search makes is stored with the
  public observation, root values, and the chosen root under
  `runs/search_data/` with the search version that produced it.
- **Cheapest first.** CMA-ES over the continuation policy's parameters,
  objective: agreement with search decisions on the tuning panel, then
  mean antes cleared. Then a boosted leaf on rollout value to shorten
  rollouts, verified by calibration on held-out states.
- **Iterate.** Search with the new continuation is the teacher for the
  next round. Continue while the Stage B gate passes against the
  previous control.

Gate per iteration: held-out paired antes cleared improves, lower bound
above zero. Kill: two iterations without improvement means the public
features or the value definition are missing something. Run attribution
on the worst deltas before continuing.

## Stage E: Endless

Mean antes in the low teens requires scores in the 10^10 to 10^13 range,
which only specific engines reach: steel Kings with Baron and Mime,
Blueprint and Brainstorm copies, retriggers, Glass, Hologram, Obelisk.
Search finds them only if the horizon and value reward them.

- Extend the horizon past Ante 8 for runs that are on track.
- Add growth of log best-hand score across the horizon as a tiebreak
  after rounds cleared.
- Run attribution: which engines appear in the twenty best Endless runs
  and which shops offered them to runs that died at Ante 9 to 11.

Gate: mean antes cleared on the gate panel improves with win rate held
at or above the previous control.

## Stage F: Live budget and authority

- **Determinization in live play.** The live parent has no Jackdaw
  private state. Either run a lockstep Jackdaw shadow, which the
  differential protocol already requires, and scrub it, or build the
  state from the public observation with Jackdaw's own constructors and
  verify by round-trip. The second is the stronger guarantee; adopt it
  before the first authority panel of a search artifact.
- Bring search inside the live budget: multiprocess rollouts, boosted
  leaf, root pruning by leaf value. Raise the budget only with a recorded
  throughput measurement.
- Every promoted artifact runs a paired panel in real Balatro on fresh
  authority seeds, into Endless, replayed through pinned Jackdaw with
  zero observed-state mismatch. Losses and Endless deaths are preserved.

Gate: authoritative paired antes-cleared lower bound above the previous
artifact.

## Stage G: Declare and pass the benchmark

No audited per-run human White Stake statistic exists. Preregister in the
lab notes before the first authority panel of Stage F:

- **The bar.** Win rate: Wilson 95% lower bound above 90%. Mean antes
  cleared: bar to be set from the first search artifact's Endless
  distribution and a written argument from human run data, before any
  candidate is evaluated against it. Do not carry the previous plan's
  unsupported 13.
- **The panel.** At least 300 evaluator-secret seeds, real Balatro,
  frozen artifact, Endless continued until death or the authority cap.
- **The replay requirement.** Every trajectory replays in pinned Jackdaw
  with zero mismatch.

Publish the artifact hash, seeds, and traces with the result.

## Jackdaw fidelity is load-bearing

Search exploits simulator bugs. Mitigations, all of which already exist
or are cheap:

- Lockstep replay of every authority trajectory with zero mismatch.
- Attribution on the twenty worst per-seed deltas after every gate run.
- A differential scoring fuzz: constructed hands and Joker sets scored
  in Jackdaw and in real Balatro through BalatroBot, since scores are
  observable public state. Add when the first search artifact exists.

## How to run a comparison

Every gate uses the same procedure. Do not improvise.

```
# control or a public baseline
uv run python scripts/evaluate_candidate_baselines.py \
  --policy strategic --seed-start 1 --seeds 200 --deck RED --stake WHITE \
  --ante-cap 20 --report-json runs/evidence/<name>-tuning-seeds1-200.json

# determinized search
uv run python scripts/evaluate_determinized_search.py \
  --seed-start 1 --seeds 200 --deck RED --stake WHITE --ante-cap 20 \
  --samples 8 --horizon-antes 2 --workers 6 \
  --report-json runs/evidence/<name>-tuning-seeds1-200.json

# paired comparison
uv run python scripts/compare_candidate_reports.py \
  runs/evidence/<control>-gate-seeds501-700.json \
  runs/evidence/<candidate>-gate-seeds501-700.json
```

A stage passes when the comparison's paired antes-cleared delta has a
bootstrap 95% lower bound above zero. Record the report paths and the
commit hash in the lab notes. Tag the commit.

## Compute

- One Jackdaw worker per performance core for search, tuning, and data.
- Search rollouts run in-process in the parent. The policy child
  process is for the live artifact and the control; do not pay IPC per
  rollout step.
- Boosted models train on CPU. No GPU work until a boosted leaf saturates.
- Do not rebuild a compiled simulator. Jackdaw plus lockstep evidence is
  the asset. Profile `deepcopy` before optimizing anything else.

## What not to do

- Do not add hand-written strategic rules or plan fields.
- Do not write scoring rules for Jokers in the public scorer for search
  purposes. `capacity.py` and `joker_rules.py` are diagnostics.
- Do not put an LLM in the live action loop.
- Do not target Gold, stickers, or other decks until Stage G passes.
- Do not tune search knobs to pass a gate. Fix the value or the
  continuation.
- Do not let the policy child, continuation, or any model import
  `jackdaw` or `balatro_ai_v2.determinize`.

## Supporting notes

Historical experiments, rejected hypotheses, the negative action-value
probe, run records, the research survey, and the pre-rescope plan are in
`docs/plan-lab-notes.md`. They are evidence, not instructions.
