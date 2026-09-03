# Superhuman Balatro at White Stake: Execution Plan

This file is the single active instruction set. An agent picking up this
project reads this file first, then `docs/plan-lab-notes.md` only for
evidence behind a claim made here. Historical stages, rejected ideas, and
run records live in the lab notes, not here. Anything in this file that
contradicts the code is a defect in this file; fix the file.

## Objective

Build an agent that plays Red Deck at White Stake in real Balatro better
than a strong human, using only information visible through the normal
game interface, and continues into Endless to clear as many antes as it
can.

"Better than a strong human" is one number: **mean antes cleared per run**,
on paired evaluator-secret seeds, in real Balatro. Winning is clearing
Ante 8. Extremely high scores are clearing Ante 12, 15, 20 in Endless. One
metric covers both, and it never saturates the way win rate does at 95%.

Gold Stake is deferred. Nothing in this plan targets stickers, faster
scaling, or fewer discards. When White is beaten, Gold gets its own plan.

## The thesis

Blind requirements grow exponentially with ante. A build survives exactly
when the score its engine can produce grows at least as fast. So the
quantity that strong players actually optimize is the **growth rate of
engine capacity**, where capacity is the expected best playable hand score
given current Jokers, deck, and hand levels.

Capacity is computable from public information with the exact scorer that
already exists. Survival is not action-sensitive at short horizons (see the
negative probe in the lab notes: most shop choices do not change whether
the next three blinds are cleared). Capacity is action-sensitive at every
shop, pack, and consumable decision. Therefore:

1. Every strategic decision is evaluated by its effect on the capacity
   trajectory, not by hand-written Joker role values.
2. Search at strategic decisions rolls sampled futures forward with the
   real candidate simulator (Jackdaw) and scores them by capacity margin
   and antes cleared.
3. A learned value function, trained on antes cleared from full-game
   rollouts, makes search affordable. Search then produces better training
   targets. This loop is turned until it saturates.

Hidden information in Balatro is exogenous chance (deck order, future
RNG), not an opponent's private state. Sampling it and searching each
sample as a perfect-information game is sound for single-player games.
Do not import imperfect-information machinery designed for adversaries.

## Fixed constraints

These do not change. Any change to them is a new plan, not an edit.

- Real Balatro under BalatroBot is the only authority. Jackdaw results
  screen changes; they never count as results.
- Policy, search, rollouts, and value models see only `PublicObservation`,
  typed public history, typed public actions, and policy-owned randomness.
  Hidden deck order, RNG state, seed, raw object IDs, and private candidate
  state never cross the boundary. Unknown fields fail closed.
- Development, tuning, gate, and authority seed panels are disjoint.
  Incomplete, rejected, timed-out, or illegal runs score zero antes.
- Every comparison is paired by seed with a bootstrap 95% interval on the
  per-seed delta. Nothing is retained because of a named seed.
- No timelines or effort estimates in this file.

## Vocabulary

| Term | Meaning |
|---|---|
| Antes cleared | Number of antes whose boss blind was beaten. Win is 8. Endless continues the count. A run that dies in Ante 3 cleared 2. |
| Capacity | Expected score of the best legal play from a sampled hand, under the current public Jokers, deck, and hand levels, averaged over belief samples of the hidden draw. |
| Requirement | Chips needed for a given blind. Known from public state and the blind schedule. |
| Log-margin | `log(capacity) - log(requirement of next boss)`. Positive means on track. |
| Growth rate | Change in log-capacity per round, including the projected effect of scaling Jokers. |
| Continuation policy | The frozen heuristic (`PublicStrategicPolicy` in `balatro_ai_v2/baselines.py`) used to finish rollouts. |
| Control | The tagged, frozen policy every candidate is compared against. |
| Panel | A fixed contiguous seed range. Tuning 1-200, gate 501-700, authority is evaluator-secret. |

## Where we are (measured 2026-09-02, commit f3140ba plus working tree)

| Quantity | Value |
|---|---|
| Control survival to Ante 6, gate panel 501-700 | 52/200 |
| Control wins, gate panel | 6/200 |
| Control mean ante / round, gate panel | 4.70 / 13.9 |
| Decisions per run, mean / max | 111 / 216 |
| Wall time per run through policy boundary, one worker | 1.5 s |
| Jackdaw clone + step | 3.5 ms |
| Jokers in catalog / with exact scoring rules for search | 151 / 16 |
| Run boundary | Ends at win. No Endless in public state, Jackdaw bridge, or BalatroBot runner. |

Historical pre-Endless evidence files:
`runs/evidence/control-v0-red-white-gate-seeds501-700.json` and
`...-tuning-seeds1-200.json`. Stage 0 writes distinct
`control-v0-endless-red-white-{tuning,gate}-*.json` files so these records
remain immutable.

Solid: public-information firewall, isolated policy process, Jackdaw
lockstep replay with hash-chained traces, paired evaluator, exact in-blind
tactical solver (`balatro_ai_v2/blind_search.py`). Not solid: strength,
Joker coverage, and the metric itself, which does not yet exist past
Ante 8.

## Open defects

Fix in order. Each has an acceptance check.

1. **Tuning propagation.** `--tuning-json` now reaches the policy child
   (working tree, uncommitted). Accept when a test proves an extreme
   parameter value changes at least one decision on a fixed observation
   and the evaluator manifest records the tuning payload. Commit it.
2. **Tuner seed panel.** `scripts/tune_strategy.py` must pass
   `--seed-start`/`--seeds` to the evaluator. Delete
   `BALATRO_TUNING_SEEDS_JSON`. Accept when the tuner's manifest shows the
   panel it ran.
3. **Failing tests.** Re-pin organic Red/Gold blind-search fixtures to
   constructed states. Accept when `uv run pytest` is green.
4. **Jackdaw data packaging.** Fresh venv must not fail on `centers.json`.
   Accept when a fresh `uv sync && uv run pytest tests/test_jackdaw.py`
   passes.
5. **Tuner is not CMA-ES.** Adopt the `cma` package or rename. Accept when
   the tuner docstring and the code agree.

Gate: suite green, `control-v0` tag on the commit, new
`control-v0-endless-red-white-{tuning,gate}-*.json` evidence files generated
from the tag with byte-identical deterministic outcome summaries.
Elapsed time and decisions per second are recorded but excluded from byte
identity because they are measurements, not deterministic outcomes.

## Stage 0: Make the metric exist

Nothing else is measurable until a run can continue past Ante 8 in both
the candidate and the authority.

- **Public state.** Replace the `won`-terminates-run rule in
  `balatro_ai_v2/public_state.py` with `antes_cleared: int` and a
  terminal that is `GAME_OVER` only. Keep the observed sticky `won` field
  for existing consumers: it cannot be derived from boss-clear count because
  Hieroglyph and Petroglyph can make a run clear more than eight bosses before
  beating the real Ante 8. Derive `antes_cleared` from displayed ante plus
  those two publicly visible used vouchers.
- **Jackdaw bridge.** `balatro_ai_v2/jackdaw.py` reads `win_ante` from
  game state. Verify that Jackdaw continues play past `win_ante` when asked
  to, or raise `win_ante` to a sentinel and verify blind requirements
  follow the real Endless schedule. Lockstep test: an organic authority
  trace that enters Endless replays with zero observed-state mismatch.
- **BalatroBot runner.** `balatro_ai_v2/balatrobot/runner.py` marks the
  run complete at `won`. The pinned BalatroBot already invokes vanilla's
  visible `exit_overlay_menu` Endless control before returning the winning
  `ROUND_EVAL`; this is not a policy decision and has no distinct observed
  phase. Let the existing typed `CashOut` action proceed and verify the
  resulting authority trace enters Ante 9.
- **Evaluator.** `scripts/evaluate_candidate_baselines.py` reports
  `antes_cleared` per run, mean, and distribution deciles.
  `scripts/compare_candidate_reports.py` reports the paired per-seed
  delta of antes cleared with a bootstrap 95% interval. Wins and survival
  to Ante 6 remain as secondary columns.
- **Run cap.** Endless is unbounded. Cap at Ante 20 for development panels
  and treat a cap hit as 20 cleared. Authority panels use a higher cap
  chosen when a candidate first reaches 20.

Gate: `control-v0` re-evaluated on both panels with antes cleared as the
headline number. This is the baseline for everything below.

## Stage 1: Capacity evaluator and minimum exact coverage

Build the quantity the thesis depends on, then check it predicts anything.

- **Contract first.** New `balatro_ai_v2/capacity.py` with a tagged,
  fail-closed `CapacityEstimate` containing mean best-play score, the hand
  that produced it, per-hand aggregate breakdown, sample method/count, and
  an explicit unavailable reason. Reuse `_play_score` from `baselines.py`
  by moving it and its helpers into a shared public-only module; do not
  duplicate the scorer. Generate Monte Carlo hands without replacement
  from `PublicDrawBelief`, seeded only by the public observation digest.
  A visible current hand is scored directly. Hidden cards, unsupported
  Joker/card/boss/voucher mechanics, and invalid contexts are unavailable;
  they never silently contribute zero. Legal plays come only from
  `iter_legal_actions`.
- **Projection.** `project_capacity(observation, rounds) -> ...` for
  scaling Jokers whose public runtime state is known (current x-mult,
  accumulated chips). Only Jokers with catalogued scaling rules project;
  others project flat.
- **Log-margin.** `log_margin(observation) -> float` against the next
  boss requirement from the public blind schedule.
- **Trace.** Every strategic decision writes aggregate capacity, projected
  capacity, log-margin, growth rate, model version, sample method/count,
  and an unavailable reason into the decision trace. Never write sampled
  hands or tapes into the live trace.
- **Coverage before validation.** The 16-Joker tactical exact set cannot
  honestly score most control shops. Instrument the 200-run tuning panel,
  list unsupported mechanics by affected shop rows, and implement exact
  scorer rules in descending frequency until at least 95% of shop rows are
  available. This is the minimum Stage-4 coverage work pulled forward; do
  not substitute the broader heuristic scorer or filter unsupported rows
  after seeing outcomes.
- **Validation.** Once coverage reaches 95%, on the fixed 200 control runs,
  log-margin at each eligible shop must
  predict clearing the next boss better than the ante alone (compare AUC).
  Bootstrap paired AUC deltas by seed, not shop row. Undefined per-seed
  AUCs remain explicit. If coverage is below 95% or the interval does not
  clear zero, capacity remains diagnostic and Stage 2 is blocked. Add a
  checked-in validation script that emits both AUCs, coverage/failure
  counts, and their paired seed-bootstrap interval; this is the executable
  gate.

Gate: capacity module passes constructed exact-score and non-oracle tests,
at least 95% of preregistered shop rows are available, and the predictive
check passes. Until all three hold, no capacity number has purchase authority.

## Stage 2: Marginal valuation replaces role constants

The heuristic values Jokers by fixed role numbers in `_joker_value`. Replace
the number with the measured effect on capacity.

- **Joker value.** For a shop Joker: capacity with it added minus capacity
  without, divided by cost, plus projected growth over the rounds to the
  next boss. Same for a sell: capacity lost. Same for a Planet: capacity
  gained by leveling that hand. Same for pack picks.
- **Build plan.** `BuildPlan` in `balatro_ai_v2/build_strategy.py` keeps
  only the committed primary hand with hysteresis persisted in the policy
  process and reconstructed from typed public history. Delete favored-tag
  bonuses once marginal valuation covers them. Do not add fields for
  commitment level, pivot conditions, temporary Jokers, or economy
  targets; those are outputs of evaluation, not stored intentions.
- **Economy.** Interest is a growth-rate term: dollars held above the
  interest cap have zero marginal value, dollars below it are worth their
  discounted future purchases. Expose this as one tuned parameter, not a
  rule.
- **Tune.** Run the CMA-ES tuner on the remaining parameters against mean
  antes cleared on panel 1-200. Evaluate the final vector once on 501-700.

Gate: tuned marginal-valuation policy beats `control-v0` on held-out
paired antes cleared with the interval's lower bound above zero. Tag as
`control-v1`. Kill: if it does not, the capacity estimate is wrong for the
states that matter. Inspect the twenty largest per-seed losses and fix the
scorer, belief, or projection responsible before touching anything else.

## Stage 3: Search at strategic decisions

Plays and discards keep the exact tactical solver. Search only at shop,
pack, skip, voucher, and blind-select decisions.

- **Roots.** Enumerate coherent action sequences with public legality:
  buy then leave, sell weakest then buy, reroll then reassess (bounded
  depth), buy then reorder, skip blind for tag, open pack and pick. Prune
  to the top K by marginal capacity from Stage 2. Extend
  `balatro_ai_v2/preboss_search.py`; do not start a parallel module.
- **Rollouts.** Sample hidden deck order and future RNG from policy-owned
  tapes. Share the same samples across sibling roots so comparisons are
  paired. Continue with `control-v1` to the next boss. Implement the
  determinization and Jackdaw rollouts in the offline evaluator parent;
  the policy child remains unable to import either backend. The parent may
  return only action values and diagnostics derived from public roots, never
  private sampled states or tapes.
- **Score.** Primary: antes cleared in the rollout horizon. Tiebreak:
  log-margin at the horizon, then projected growth rate. Survival is
  encoded in antes cleared; do not add it as a separate term.
- **Budget.** Offline first, no wall-clock limit, one Jackdaw worker per
  performance core. Record rollouts per root and decisions per second per
  core in every report; a drop is a regression.
- **Calibration.** Predicted antes cleared from rollouts versus realized
  on held-out states. The largest miscalibration names the next mechanic
  to fix.

Gate: search with generous budget beats `control-v1` on held-out paired
antes cleared, lower bound above zero. Kill: if it cannot with ten times
the intended live budget, the rollout model or horizon is wrong. Fix
calibration; do not tune search knobs.

## Stage 4: Coverage for high-ceiling builds

Search cannot find a strategy the simulator refuses to score. Sixteen
Jokers have exact rules today. Endless runs are built on a specific set.

- **Priority list** (add exact rules and catalog projection in this order,
  each with a constructed-state test against known real scores):
  Blueprint, Brainstorm, Hologram, Obelisk, Baron, Mime, Photograph,
  Hanging Chad, Sock and Buskin, Hack, Dusk, Steel-card and Glass-card
  interactions, DNA, Ramen, Vampire, Constellation, Fortune Teller,
  Throwback, Campfire, Castle, Hiker, Ride the Bus, Green Joker, Square
  Joker, Bloodstone, Arrowhead, Onyx Agate, Smeared Joker, Four Fingers,
  Shortcut, Splash, Pareidolia.
- **Attribution.** After every gate run, list the Jokers that appeared in
  shops during the twenty worst per-seed deltas and were excluded. Move
  them to the top of the list.
- **Consumables.** Same treatment for Tarots that change card
  enhancements, Spectrals that add editions or seals, and Planets for
  secret hands.

Gate: none of its own. This stage runs continuously and its output is the
input to every other gate. Track coverage as a number in every report:
fraction of shop Jokers seen on the panel that search could evaluate.

## Stage 5: Learned value, then expert iteration

Rollouts to the next boss are expensive. A leaf value lets rollouts stop
after a few decisions and lets search see more roots.

- **Data.** Every full game the evaluator or search runs emits, per
  strategic decision, the public observation features, capacity, log-
  margin, growth rate, and the eventual antes cleared. Store under
  `runs/value_data/` with the policy version that generated it.
- **Model.** Gradient-boosted regressor on antes cleared with log-margin
  as an auxiliary feature. Trains in seconds on CPU. Neural only if the
  boosted model saturates below the gate.
- **Use.** Replace rollout-to-boss with rollout-to-k-decisions plus the
  leaf. Verify with the calibration check from Stage 3.
- **Iterate.** Search with the leaf is the teacher. Retune `control-v1`
  parameters against the teacher's decisions where cheap. Refit the leaf
  on the teacher's games. Repeat while the Stage 3 gate passes against
  the previous control.

Gate per iteration: held-out paired antes cleared improves, lower bound
above zero. Kill: two consecutive iterations without improvement means
the public features are missing something. Run attribution on the worst
deltas before continuing.

## Stage 6: Live budget and authority

- Bring search inside the live decision budget: multiprocess rollouts,
  boosted leaf, root pruning by leaf value. Raise the budget only with a
  recorded throughput measurement.
- Every promoted artifact runs a paired panel in real Balatro on fresh
  authority seeds, into Endless, replayed through pinned Jackdaw with zero
  observed-state mismatch. Losses and Endless deaths are preserved.

Gate: authoritative paired antes-cleared lower bound above the previous
artifact.

## Stage 7: Declare and pass the benchmark

No audited per-run human White Stake statistic exists. Before Stage 6
completes, preregister in the lab notes:

- **The bar.** Proposed: at least 90% wins and mean antes cleared of at
  least 13 on Red Deck at White Stake. Revise only with a written argument
  from real human run data, before any candidate is evaluated against it.
- **The panel.** At least 300 evaluator-secret seeds, real Balatro, frozen
  artifact, Endless continued until death or the authority cap.
- **The statistic.** Wilson 95% lower bound on win rate above 90%, and a
  bootstrap 95% lower bound on mean antes cleared above 13.
- **The replay requirement.** Every trajectory replays in pinned Jackdaw
  with zero mismatch.

Publish the artifact hash, seeds, and traces with the result.

## How to run a comparison

Every gate uses the same procedure. Do not improvise.

```
# candidate on the tuning panel
uv run python scripts/evaluate_candidate_baselines.py \
  --policy <name> --seed-start 1 --seeds 200 --deck RED --stake WHITE \
  --ante-cap 20 \
  --report-json runs/evidence/<candidate>-tuning-seeds1-200.json

# candidate on the gate panel, only for the final vector of a stage
uv run python scripts/evaluate_candidate_baselines.py \
  --policy <name> --seed-start 501 --seeds 200 --deck RED --stake WHITE \
  --ante-cap 20 \
  --report-json runs/evidence/<candidate>-gate-seeds501-700.json

# paired comparison against the current control
uv run python scripts/compare_candidate_reports.py \
  runs/evidence/<control>-gate-seeds501-700.json \
  runs/evidence/<candidate>-gate-seeds501-700.json
```

A stage passes when the comparison's paired antes-cleared delta has a
bootstrap 95% lower bound above zero. Record the report paths and the
commit hash in the lab notes. Tag the commit.

## Compute

- One Jackdaw worker per performance core for search, tuning, and value
  data. Efficiency cores run the evaluator.
- At 1.5 s per run, six workers produce roughly 300k complete games per
  day. That is the value-data budget before renting anything.
- Boosted models train on CPU. Do not use MPS for batch-size-one inference
  inside search.
- Do not rebuild a compiled simulator. Jackdaw plus lockstep evidence is
  the asset.

## What not to do

- Do not add hand-written strategic rules or plan fields. Every rule
  increment since August moved wins by at most one on a 50-seed screen.
- Do not put an LLM in the live action loop.
- Do not target Gold, stickers, or other decks until Stage 7 passes.
- Do not optimize win rate alone once Stage 0 is done. Antes cleared is
  the metric.
- Do not tune search knobs to pass a gate. Fix calibration.

## Supporting notes

Historical experiments, rejected hypotheses, the negative action-value
probe, run records, and the research survey are in
`docs/plan-lab-notes.md`. They are evidence, not instructions.
