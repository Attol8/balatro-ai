# Superhuman Balatro: Execution Plan

## Objective

Build an agent that beats a declared, preregistered strong-human benchmark
on Red Deck at Gold Stake in real Balatro, using only information available
through the normal game interface. Red/White is the development setting;
Gold is the promotion target; all-deck Gold is a later generalization.

## Fixed constraints

- Real Balatro under BalatroBot is the only authority. Candidate (Jackdaw)
  results screen changes; they never count as wins.
- Policy, search, and rollouts see only `PublicObservation`, typed public
  history, typed public actions, and policy-owned randomness. Hidden deck
  order, RNG state, private candidate state, and raw object IDs never cross
  the boundary. Unknown fields fail closed.
- Development, tuning, gate, and authority seed panels are disjoint.
  Incomplete, rejected, timed-out, or illegal runs count as losses.
- Paired seeds for every comparison. No change is retained because of a
  named seed. Survival through Ante 6 is the development metric; win rate is
  the promotion metric.
- No timelines or effort estimates in this file.

## Where we are (measured, 2026-09-02, commit 1f57153)

| Quantity | Value |
|---|---|
| Frozen `strategic` candidate wins, Red/White seeds 1-200 | 7/200 |
| Average ante / round on that panel | 4.37 / 12.9 |
| Real Balatro wins with exact Jackdaw replay | seeds 63, 44 |
| Candidate throughput through the policy boundary | ~74 decisions/s |
| Jackdaw median clone / step / clone+step | 1.16 / 2.36 / 3.53 ms |
| Test suite (Jackdaw importable) | 526 passed, 14 failed |
| Hardware | M2 Pro, 6P+4E cores, 32 GB, MPS available |

What is solid: the public-information firewall, isolated policy process,
Jackdaw lockstep replay with hash-chained traces, paired evaluator, and
exact in-blind tactical search. What is not: strength. Every hand-written
rule increment since August moved wins by at most one on a 50-seed screen,
which is inside noise at this win rate.

What the research says (see `docs/plan-lab-notes.md` for sources): no
published Balatro agent has any Gold Stake result; the one careful RL
attempt plateaued at 2.35% and diagnosed itself as search-limited; the best
Slay the Spire bot is hand-tuned with no ML and sits at good-human on easy
difficulty; evolution-tuned rule weights reached strong-human level in
Dominion. A neural model is a later speed optimization, not a prerequisite.

## Open defects (fix before any strength claim)

1. **Tuning never reaches the policy.** `tuning_from_environment` runs
   inside the policy child, which is launched with a stripped environment.
   Extreme parameters produce per-run outcomes identical to defaults.
   Fix: pass the tuning payload explicitly (a `--tuning-json` child
   argument or a field on the policy wire request), record it in the
   evaluator manifest, and add a test proving an extreme value changes at
   least one decision on a fixed observation.
2. **Tuner seed panel is ignored.** `tune_strategy.py` sets
   `BALATRO_TUNING_SEEDS_JSON`; the evaluator never reads it. Append
   `--seed-start`/`--seeds` to the evaluator command instead and delete the
   variable.
3. **14 failing tests.** 13 organic Red/Gold blind-search fixtures drive the
   heuristic 100 steps and now hit GAME_OVER before reaching their target
   Joker; one pre-boss test expects a $2 Blue Joker purchase the policy no
   longer makes. Decide whether the frozen control is the parent commit's
   behavior or this one's, re-pin fixtures to constructed states rather than
   organic trajectories, and tag the result.
4. **Jackdaw data files are not packaged.** A fresh venv fails 37 tests on
   a missing `centers.json`. Add a sync step or a startup check that copies
   the six JSON files from the pinned checkout.
5. **The tuner is not CMA-ES.** It is truncation selection with isotropic
   noise and fixed sigma decay. Either rename it or adopt the `cma` package.

## Stage 0: Pin the control

- Fix defects 1-5. Tag the commit as `control-v0`.
- Run `control-v0` on tuning panel seeds 1-200 and gate panel seeds
  501-700. Record survival-to-Ante-6 rate, wins, average ante and round in
  a frozen report. This is the baseline for every later comparison.
- Extend `compare_candidate_reports.py` to report paired survival deltas
  with a bootstrap interval, not just wins.

Gate: control report exists, suite green, tuning propagation test passes.

## Stage 1: Tune the heuristic instead of extending it

The heuristic has roughly 170 hard-coded constants. Expose the ones that
encode judgment, not legality: economy reserves per ante, sell and
replacement thresholds, Joker category values, x-mult acquisition urgency
by ante, reroll budget, pack/voucher reserve floors, build-commitment and
discard thresholds. Target a vector of 20-40 parameters.

- Fitness: survival-to-Ante-6 rate on paired tuning seeds 1-200, with
  wins as a tiebreak. One evaluation is about five minutes on this machine;
  run populations in parallel across cores.
- Optimizer: real CMA-ES. Start from the frozen values; sigma scaled per
  parameter.
- Hold out gate seeds 501-700. Evaluate only the final candidate there.
- Log every evaluated vector and fitness so the surface can be inspected.

Gate: tuned candidate beats `control-v0` on held-out paired survival with a
bootstrap 95% lower bound above zero and no win regression. Then it becomes
`control-v1`, the continuation policy for search. Kill: if the best tuned
vector does not beat the control on held-out seeds, the parameterization
is wrong, not the optimizer. Widen the vector before touching the search.

## Stage 2: Offline rollout search at strategic decisions only

In-blind plays and discards already have the exact tactical solver and are
about 70% of all decisions. Search only at shop, pack, skip, voucher, and
boss-entry decisions.

- Roots: enumerate coherent options (buy/sell/reorder sequences, reroll,
  skip, pack pick) with public legality.
- Rollouts: sample hidden deck order and future RNG from policy-owned
  tapes; share the same samples across sibling options; continue with
  `control-v1` to the next boss or to a fixed decision horizon; score by
  survival.
- Run offline with no 2-second budget, one Jackdaw worker per core.
  Measure decisions per second per core and rollouts per root; treat a drop
  as a regression.
- Calibration check: predicted survival from rollouts versus realized
  survival on held-out states. Fix the mechanics with the largest
  miscalibration first. Do not require exact synthesis of every mechanic
  before measuring.
- Coverage debt: unsupported Jokers fail closed, so search avoids the cards
  strong players build around. Track which exclusions correlate with losses
  and lift them in that order.

Gate: search with generous budget beats `control-v1` on held-out paired
survival, lower bound above zero. Kill: if it cannot with ten times the
live budget, the rollout model or horizon is wrong. Diagnose calibration;
do not tune search knobs.

## Stage 3: Cheap leaf value, then iterate

- Train a gradient-boosted survival model on public features from rollout
  outcomes. Use it as the leaf evaluator so rollouts stop after a few
  decisions. More rollouts per root at the same cost.
- Iterate: search with the new leaf produces a stronger teacher; retune
  the heuristic vector against the teacher's decisions where cheap; refit
  the leaf. Each iteration has the Stage 2 gate against the previous
  control.
- Distill into the existing policy/value network only if the boosted leaf
  saturates below the target. The scaffolding in `search_distillation.py`
  stays; it is not on the critical path.

Gate per iteration: held-out paired survival improves with lower bound
above zero. Kill: two consecutive iterations without improvement means the
public features are missing something; audit loss attribution before
continuing.

## Stage 4: Live deployment and authority

- Bring the search inside the live policy budget: multiprocess rollouts,
  boosted leaf, option pruning by leaf value. Raise the budget only with a
  recorded throughput measurement.
- Every promoted artifact runs a paired panel in real Balatro on fresh
  authority seeds, replayed through pinned Jackdaw with zero observed-state
  mismatch. Losses are preserved as evidence.

Gate: authoritative paired win-rate lower bound above the previous
artifact. Target for leaving White: at least 80% candidate wins and a
positive authoritative paired result.

## Stage 5: Stake curriculum to Gold

Stakes are cumulative. Add them in order and at each step: re-prove Jackdaw
parity on organic authority traces, re-measure rollout calibration, retune
the heuristic vector, refit the leaf, rerun the Stage 2-4 gates.

Gold-specific mechanics to attribute failures to: faster blind scaling,
one fewer discard, no Small Blind reward, Eternal, Perishable, and Rental
stickers. Expect the value model to need retraining, not fine-tuning.

## Stage 6: Declare and pass the benchmark

No credible per-run human Gold Stake win rate exists. Community self-reports
cluster at 30-40% for experienced players and are unaudited. Before Stage 5
finishes, preregister:

- The bar: proposed at least 50% wins on Red Deck / Gold Stake.
- The panel: at least 300 evaluator-secret seeds, real Balatro, frozen
  artifact, normal completion required.
- The statistic: Wilson 95% lower bound above the bar.
- The replay requirement: every trajectory replays in pinned Jackdaw with
  zero mismatch.

Publish the artifact hash, seeds, and traces with the result.

## Compute plan for this machine

- One Jackdaw worker per performance core for search and tuning. Efficiency
  cores run the evaluator and training.
- Boosted models train in seconds on CPU. Do not use MPS for batch-size-one
  inference inside search.
- If Stage 3 needs more than a few hundred thousand labeled roots, rent a
  64-core box for data generation only. Jackdaw scales linearly with cores.
- Do not rebuild a compiled simulator. That was the August deletion; the
  lockstep evidence is the asset.

## Supporting notes

Historical experiments, rejected hypotheses, run records, and the research
survey are in `docs/plan-lab-notes.md`. They are evidence, not active
instructions.
