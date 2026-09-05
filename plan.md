# Fair Superhuman Balatro: Execution Plan

This file is the single active instruction set. An agent picking up this
project reads this file first, then `docs/plan-lab-notes.md` only for
evidence behind a claim made here. Historical stages, rejected ideas, and
run records live in the lab notes, not here. Anything in this file that
contradicts the code is a defect in this file; fix the file.

Rescoped 2026-09-03. The previous plan is preserved in the lab notes under
"Plan before the 2026-09-03 rescope" together with the evidence that
retired it.

## Objective

Build an agent that plays real Balatro better than strong humans using only
information visible through the normal game interface. The final claim covers
all standard decks at Gold Stake on evaluator-secret seeds. Red Deck at White
Stake remains the current development track: it is where architecture and
strength changes are rejected cheaply before graduating to Gold.

Per run, the objective is lexicographic:

1. **Win probability**: before the first win, clearing Ante 8 dominates every
   Endless or score objective.
2. **Endless progression**: after `won=true`, maximize ante reached and then
   `log10(best_hand_score)` without changing the environment semantics.

Every report also keeps lower-tail survival, boss/build failure attribution,
maximum ante, and best-hand score separate. Seeded, filtered, modded, restarted,
or save-scummed high-score demonstrations are research inputs, never mixed with
the fair frozen-agent benchmark.

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
| Panel | A fixed contiguous seed range. Tuning 1-200, replacement gate 701-900, authority is evaluator-secret. Seeds 501-700 are quarantined after prior adaptive use. |

## Where we are (measured 2026-09-04, commit 58a34ca)

| Quantity | Value |
|---|---|
| Control wins, former 501-700 panel | 6/200 |
| Control mean antes cleared, former 501-700 panel | 3.855 |
| Control survival to Ante 6, former 501-700 panel | 52/200 |
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

## Strategy architecture build (2026-09-04)

The elite-play audit changes the next capability increment. The retained
one-ante search is a useful survival teacher, but it cannot by itself express
the multi-shop preparation, deck transformation, phase-specific copying, or
post-win score growth used by strong Gold-stake and Endless players. Build the
following public-only vertical slice before another large seed panel. This
section supersedes the narrower leaf/parameter experiments below where they
conflict.

1. **Engine state.** Derive a typed, immutable `PublicEngineState` from
   `PublicObservation`: scoring roles, trigger/copy relationships, deck
   concentration and modifiers, economy/liabilities, consumable resources,
   hand development, and boss vulnerabilities. It describes state and
   capability; it must not contain private simulator data or hard-coded action
   values.
2. **Goal and intent.** Represent the lexicographic run goal explicitly:
   before the first win, survival and Ante-8 win probability dominate; after
   `won=true`, Endless ante and log-score growth dominate. Infer a bounded set
   of revisable strategic intents such as stabilize, build economy, develop a
   reliable hand, sculpt the deck, assemble a held-card or played-card
   retrigger engine, exploit consumable generation, and prepare for a boss.
3. **Options.** Add public strategy-option candidates above atomic actions.
   An option proposes an intent and a legal first action; subsequent decisions
   revalidate the public state and may continue, revise, or terminate the
   intent. Options never bypass typed legality and never inject state.
4. **Relational model.** Add a compositional public policy/value model over
   card, Joker, consumable, voucher, blind, and action entities. Preserve
   order and target relationships. Produce separate current-blind,
   next-boss, Ante-8 win, Endless-ante, and log-score heads rather than one
   scalar. Do not reuse the retired hashed GRU as the strategy model.
5. **Search integration.** Keep the existing paired determinization and
   fail-closed behavior. Allow search to compare option first actions and
   phase-relevant reorders, carry public intent through continuation, and use
   a lexicographic utility whose Endless terms cannot trade away an unearned
   win. Model leaves are shadow-only until calibration passes on held-out
   complete runs.
6. **Diagnostics and expert fixtures.** Emit engine, intent, goal, boss-risk,
   deck-sculpting, consumable, and option diagnostics. Add constructed
   public-only expert decision vignettes for economy ordering, Blue Seals,
   Tarot targeting, consumable holding, copy/retrigger order, and boss
   preparation. These are capability tests, never promotion evidence.
7. **Evaluation.** Report win rate, lower-tail survival, boss/build failures,
   maximum ante, and `log10(best_hand_score)` separately. Keep seeded,
   filtered, modded, or restart-selected high-score demonstrations outside the
   fair benchmark. No tuning or gate panel runs until focused tests, the full
   suite, firewall tests, and a diff review pass.

Acceptance for this build:

- every new feature is a pure function of typed public state/history;
- hidden twins produce identical engine state, intents, options, model inputs,
  and utility;
- every option first action is present in the public legal-action set;
- the pre-win utility cannot prefer a losing line because of Endless score;
- `won=true` switches the objective without changing environment semantics;
- expert vignettes cover every declared intent and fail on shuffled targets or
  order where the mechanic is order-sensitive;
- existing policy behavior remains available as the unchanged control;
- focused tests and the complete suite pass before any game panel is started.

Implementation status: the public engine projection, option/intent contract,
goal-conditioned paired search mode, relational entity/action model, strict
artifact format, shadow-only model wrapper, best-hand metric, and strategy
diagnostics are built. The retained scalar search remains the default; strategy
options, reorders, and model shadowing are explicit evaluator flags. No learned
strategy artifact is promoted, and no tuning/gate panel may run until the new
model is trained and calibrated on complete development-run splits. The focused
strategy surface passes 120 tests and the complete repository passes 673 tests.
Finite integral scientific-notation scores are retained as arbitrary-size public
integers and encoded with bounded linear/log features; fractional and non-finite
score values fail closed.

### Elite-route capability order (active 2026-09-05)

Do not collect the reserved v12 teacher cohort until the action/state surface
can represent the decisions that create elite Endless engines. Add capabilities
in this order, proving candidate behavior and clean authority-patch replay at
each boundary:

1. **Boss reroll.** Expose one `RerollBoss` action only in Blind Select when a
   Boss is selectable, the public economy can pay the fixed $10 cost, and the
   run owns Retcon or an unused Director's Cut. Export the public
   `boss_rerolled` allowance bit, consume ordinary game RNG, and reveal only
   the resulting visible Boss. Never preview or enumerate replacement bosses.
2. **Route state.** Keep the lexicographic `RunGoal` separate from a persistent,
   revisable route: victory, held-card retrigger, played-card retrigger, or
   consumable duplication. Track absent/assembling/online prerequisites from
   public state and history; search identity includes action, intent, and route.
3. **Public elite observations.** Add a public permanent-deck aggregate and the
   visible runtime target of target-dependent Jokers such as Idol. The aggregate
   may expose remembered deck composition, never draw order or which identity
   occupies a face-down hand slot. Hidden twins must remain identical.
4. **Inventory choreography.** Support shop buy-and-use and legal pack-phase
   use/sell/reorder operations only after exact BalatroBot and Jackdaw semantics
   are established. Capacity and money checks remain centralized typed
   legality; unknown pack behavior fails closed.
5. **Trajectory iteration.** Ingest strong public trajectories for route and
   pivot coverage, then correct them with paired determinized search and
   complete-run terminal labels. Demonstrations are neither authority evidence
   nor an oracle and may not bring seed/private state into the model.

After these capabilities, profile the exact continuation scorer and clone/step
costs again. Optimize measured bottlenecks without changing selected actions on
a frozen development replay. Then freeze source/config/model digests and use
unused development seeds 1975--2274 for a new preregistered collection.

## Relational expert-iteration increment (active 2026-09-04)

The next increment turns the architecture into a measurable candidate without
letting an uncalibrated model affect play. It does not consume the tuning panel
`1-200`, replacement gate panel `701-900`, or evaluator-secret authority seeds.
The former `501-700` gate is quarantined: saved reports show repeated adaptive
candidate screens on `501-550`, including causal tuning on seeds 506 and 541,
so its earlier "fresh gate" designation was false.

1. **Teacher contract.** At each successful strategy-option search, retain the
   canonical public observation, ordered typed option roots, public intent per
   root, the selected root, and per-root/per-sample scalar outcome targets.
   Attach eventual win, ante, and best-hand labels only after the originating
   run completes. Dataset rows contain an opaque run group, never the seed,
   private clone, RNG, raw state, save payload, or hidden identity. Any
   incomplete originating run or rejected/truncated root invalidates its row.
2. **Run-safe splits.** Split by complete opaque run before expanding decisions
   or sibling roots. Use fixed train/calibration/untouched-holdout group lists
   and record their digests. Weight records inversely by decisions in their
   originating run so long trajectories cannot dominate.
3. **Intent-conditioned model.** Encode the declared public strategy intent on
   each option candidate so identical first actions with different continuation
   purposes are distinguishable. Train policy ranking only from the teacher's
   lexicographic decision. Train current-blind and next-boss survival from
   rollout resolution targets, Ante-8 win from complete pre-win run outcomes,
   and Endless ante/log-score only from complete post-win outcomes. Never
   softmax a blended utility across lexicographic components.
4. **Calibration artifact.** Fit temperatures for the three binary heads and
   policy logits, biases/error radii for the two regression heads, and a
   baseline-relative policy margin on calibration groups. Bind model/schema,
   teacher/search/config/backend, dataset, split, trainer, normalizer, metric,
   and calibration digests in the frozen artifact. Missing, extra, mismatched,
   non-finite, or out-of-domain metadata fails closed.
5. **Shadow gate.** On untouched complete runs report per-head Brier/log loss or
   MAE/RMSE, option agreement, baseline-relative coverage, teacher regret, and
   results by phase/ante. An advisor may recommend an action only when it is
   still legal and clears the frozen calibration margin; every exception or
   uncertainty returns the unchanged continuation. Point predictions do not
   enter the lexicographic search value.
6. **Bounded execution.** First prove the collector/trainer on synthetic and
   organic fixtures. Then collect a preregistered pilot on development seeds
   `901-912` using two samples, one-ante horizon, no reorders, and Red/White.
   Split eight/two/two complete run groups. If coverage is sufficient, train
   once and run shadow-only on development seeds `913-916`. The first shadow
   attempt exposed those seeds but failed before report emission because the
   evaluator referenced a retired decision field. Retire that block, repair
   the reporter and its tests, and use fresh development seeds `921-924` for
   the single replacement smoke. Record calibrated value-head predictions as
   well as policy margins. Do not promote or launch a larger panel from this
   pilot.

Acceptance for this increment:

- serialized teacher rows round-trip and contain no seed or private fields;
- hidden twins yield identical model candidates and tensors;
- every recorded candidate action is legal and every intent is an admitted
  `StrategyIntent`;
- no row crosses a run split and no incomplete/rejected row trains the model;
- every loss/head is finite, separately reported, and masked by target
  eligibility;
- calibration parameters are learned on calibration groups only and frozen
  before untouched holdout evaluation;
- shadow recommendations never change the played action;
- full tests, firewall tests, artifact reload, and diff review pass before the
  bounded development pilot.

Bounded-pilot result (2026-09-04): the collector wrote 290 complete-run-grouped
decisions from all 12 development runs with zero rejected rollouts. The frozen
30-epoch relational artifact reloads and is shadow-only. On its untouched
two-run holdout, only next-boss Brier beat the train-only empirical baseline;
policy agreement was 53.85% versus the baseline's 76.92%, and there were no
Endless targets. All 580 selected-root current-blind samples were positive, so
that head also had no class variation. The offline gate therefore failed and
the model is forbidden from action or leaf influence. After retiring the failed `913-916` integration
attempt, the replacement `921-924` shadow completed 4/4 runs, recorded all five
value heads for 222/222 decisions, and had zero unavailable predictions. Its
nine margin-clearing signals remain diagnostics, not playable recommendations.
The next data collection must deliberately cover wins and post-win states and
must improve every held-out head plus policy ranking before this lane can alter
search.

Diff-review correction: that first artifact is diagnostic-only for a stronger
reason. `PublicStrategicPolicy` did not yet implement the option continuation
contract, so different intent labels sharing a first action did not produce
different rollout behavior. Add a stateless, distinct rollout fork and an
intent-filtered public action method; have search use the active intent between
strategic roots; bump the search protocol version; and prove fallback legality,
fork isolation, hidden-twin equality, and multi-step intent use. Preserve the
old dataset/model/report as failed evidence, retire their exposed seeds, and
repeat the same bounded eight/two/two collection on fresh development seeds
`925-936`, followed by shadow-only seeds `937-940` only if the new artifact
reloads. No protected panel is authorized.

The `925-936` v3 attempt failed closed before any rollout step because search
passes the active intent into `fork_for_rollout`, while the new stateless fork
omitted that argument. All 8,248 roots were rejected, the evaluator wrote zero
teacher rows, and the entire panel is invalid. Retire both `925-936` and its
unused companion block `937-940`; fix the exact interface contract and cover it
with a production-continuation rollout test. Preregister fresh `941-952` for
the replacement teacher and `953-956` for its conditional shadow smoke.

The `941-952` replacement executed 86,474 rollout steps but one seed produced
one rejected root, so the panel correctly wrote no teacher rows. A deterministic
diagnostic replay tied it to an Ante-2 `deck_sculpt` pack line reaching a public
selecting-hand state with legal discards but no playable hand; the legacy
strategic heuristic raised instead of taking the legal discard. Fix that
root cause with an organic legal-subset regression test. Retire `941-952` and
unused `953-956`, then use fresh `957-968` and conditional `969-972` once.

The `957-968` block had zero rejected rollouts across 102,420 steps, but only
11/12 runs completed: seed 959 stopped after Jackdaw asserted that an Economy
Tag must award positive dollars. A public diagnostic showed the valid edge
case was `$0 -> $0`; doubling zero pays zero. Accept nonnegative Economy Tag
deltas, surface bounded terminal policy errors in evaluator reports, and turn
backend exceptions inside rollouts into explicit rejected outcomes. The same
seed then completed organically to five antes with 15,892 rollout steps and
zero rejections. Preserve the failed block, train nothing from it, and do not
run its unused `969-972` shadow block. The next session may preregister fresh
development `973-984` for a clean v3 teacher and `985-988` for conditional
shadow; do not splice any prior run.

The preregistered `973-984` v3 collection completed 12/12 runs and 80,517
rollout steps, but the atomic collector discarded it because two seed-983
`deck_sculpt` pack roots reached The Hook with an empty hand and no public
play/discard action. This is the previously observed deck-exhaustion deadlock,
not a malformed root: vanilla's draw function only forces `GAME_OVER` when the
configured hand-size limit is zero, so neither the wrapper nor the continuation
may invent a terminal phase or sell assets to mask it. Represent an observable
selecting-hand deadlock as a resolved losing rollout with zero liveness, while
retaining rejected status for exceptions and simulator faults. This changes
teacher semantics, so bump the protocol to determinized-search-v4. Prove the
distinction with direct rollout regressions and rerun seed 983 diagnostically.
Retire `973-984` and its unused companion `985-988`; after the full suite and
diff review pass, use fresh development `989-1000` for one clean v4 teacher
collection and `1001-1004` for the conditional shadow smoke. No protected panel
is authorized.

Bounded v4 result: the fresh `989-1000` collection completed 12/12 runs with
79,414 rollout steps, zero rejected roots, and 284 teacher decisions in 12
opaque complete-run groups. The dataset SHA-256 is
`aa82c5af5038a6db444e79c60d194ac860fe2f781219172076a18300edb319d7`.
The frozen relational artifact SHA-256 is
`67ae20a24abce0af805eb1898562fd228842807340cfcc060c18e9b7363b62d8`.
Its untouched two-run holdout improves option agreement over the train-only
empirical baseline (61.02% versus 55.56%) and improves next-boss Brier, but all
three margin-clearing recommendations are wrong, the other heads do not beat
their baselines, and the data contain no win or Endless targets. The gate fails;
the artifact is shadow-only and cannot influence options, actions, or leaves.
The preregistered `1001-1004` smoke completed 4/4 with zero rejected rollouts,
finite predictions on 95/95 strategic decisions, zero unavailable predictions,
and nine diagnostic margin signals. It explicitly records
`affects_actions=false` and `authorizes_action_influence=false`. Do not run a
protected panel for this artifact. The next learning collection must add actual
win and post-win coverage before the value heads can be considered for leaf use.

### Success-horizon expert iteration (active)

The v4 result exposed a structural defect rather than merely a small dataset.
Its teacher records carry per-candidate Ante-8, Endless, and score outcomes,
but the trainer reads those heads from the action actually played by the source
run. Buying longer rollouts without repairing that contract would discard the
counterfactual signal. The next slice is therefore a shadow-teacher and
action-conditioned learning correction, not a larger repetition of v4.

Design sketch:

1. **One candidate contract.** Search, teacher collection, and model shadowing
   use one canonical builder for ordered `(public action, public intent)` roots.
   The continuation's active intent and reorder setting are part of that
   contract. Agreement means exact action-and-intent identity; action-only
   agreement is insufficient.
2. **Action-inert teacher.** The organic trajectory continues to use the frozen
   retained behavior choice. At a fixed public-only anchor schedule, a separate
   teacher evaluates every sibling root on paired determinizations and records
   its preferred root without changing the played action or active intent.
   Reports state `teacher_affects_actions=false`, and twin/control tests prove
   byte-identical trajectories with the teacher enabled or disabled.
3. **Success horizons.** Cheap one-ante labels remain available at ordinary
   roots. The success teacher anchors at the first shop in each ante, the first
   pack in each ante from Ante 4, boss selection from Ante 5, and the first
   post-win shop and pack in each ante. Pre-win
   roots from Ante 4 continue to win or death; post-win roots continue two more
   antes or death. All siblings share the same sample blocks and sample count.
   Step-cap and ante-cap endpoints are explicitly censored and never treated as
   exact death or score labels.
4. **Counterfactual heads.** Bump the teacher schema. Store target eligibility
   and endpoint kind per root sample. Produce current-blind, next-boss, Ante-8,
   Endless-ante, and log-score predictions per candidate, not per state. Train
   only resolved targets and normalize each head independently so every
   eligible source run has equal total weight. Policy ranking uses the complete
   paired root outcome ordering instead of silently substituting the played-run
   result.
5. **Honest acquisition.** All rows from a source run share one opaque lineage
   and split. The split rule, teacher nonce, anchor schedule, and fresh
   development block are fixed before outcomes are observed. No losing run is
   omitted and no calibration or holdout cohort is success-conditioned.
   Successful-prefix replay is deferred until ancestor lineage and duplicate
   decision grouping are enforced; this slice obtains more useful labels at
   the original online decisions instead.
6. **Hard gates.** Dataset loading reconciles complete groups, record counts,
   teacher configuration, and zero rejected roots. Calibration/holdout gates
   require both target classes where applicable, winning and losing groups,
   meaningful recommendation coverage, zero high-confidence recommendation
   errors, and non-positive teacher regret. The model remains shadow-only in
   this iteration regardless of diagnostic quality.

Bounded execution order:

- add focused schema, candidate-contract, censoring, action-conditioned-loss,
  run-weighting, and action-inertness tests;
- run the full suite and public-information firewall tests;
- replay reused development seed `207` only as a post-win implementation
  diagnostic, requiring a genuine resolved Endless row and zero rejected roots;
- if that diagnostic passes, collect one complete fresh development tranche on
  preregistered seeds `1005-1054`; retain every completed source run and stop on
  any hidden-twin disagreement, teacher influence, illegal root, rejected
  rollout, lineage discontinuity, or censored target admitted as exact;
- require at least five winning and five losing source groups, 25 resolved
  Endless rows from at least five groups, and 20 late pre-win decisions with
  action-sensitive Ante-8 outcomes before training. Otherwise record the
  coverage failure and improve the organic behavior source rather than buying
  a larger horizon.

Result: the fixed `1005-1054` cohort completed all 50 runs at commit `f180090`
with zero rejected roots, five wins, mean 4.54 antes, and maximum Ante 10. The
atomic public-only dataset contains 369 rows across all 50 opaque run groups;
strict deserialization, the report hash, the single teacher digest, and a
recursive forbidden-key audit pass. It has 45 late action-sensitive Ante-8
rows and resolved Endless targets from all five winning groups, but only 14
resolved Endless rows versus the frozen requirement of 25. The coverage gate
therefore fails. Preserve this as diagnostic data; do not train it, weaken the
threshold, or add seeds after observing the outcome.

Performance continuation after the fixed cohort:

1. Instrument before optimizing. Per terminal anchor record public phase/ante,
   action-kind and intent counts, roots, endpoint histogram, total/max rollout
   steps, wall time, and fallback reason. Report distribution tails separately
   for ordinary and terminal search. Seed `1037` took 4,416 wall seconds and
   exposed 176, 207, then 318 roots at late packs; candidate combinatorics are a
   first-class budget constraint.
2. Apply exact-behavior speedups first: freeze each sampled backend
   serialization once for all sibling clones, compute the public prefix
   best-hand score once per decision, reuse one captured legal-action tuple in
   option construction, and avoid repeated action serialization in the rollout
   loop. Preserve canonical private state, public projection, selected actions,
   and complete trajectories in equivalence tests. Never truncate the first N
   targeted card combinations, which would introduce positional bias.
3. Add an opt-in sparse terminal selector that can replace the retained scalar
   search choice only at exact late success anchors. It computes a pure public
   `(action, intent)` result and commits action plus persistent intent exactly
   once. Fallback is the exact scalar-selected root. Any rejected/censored
   sibling falls back atomically. Early cheap-label anchors never affect play.
   A simulator state with no public progress action remains a conservative
   losing shadow label but is selection-inadmissible until authority establishes
   an exact death.
4. Keep terminal action mode isolated: development provenance only, no teacher
   JSONL, no learned shadow model, and a fully digest-bound selection protocol.
   The selector does not reuse the two-sample collection heuristic. It screens
   every sibling on two paired samples, then races only roots never worse and
   strictly better on the declared terminal component, up to 12 samples. An
   anchor with more than 64 roots fails closed before sampling; this is a
   separate compute bound, not statistical pruning, and the selector never
   truncates or positionally samples the candidate set. An
   override requires zero adverse discordances and the root-count-adjusted
   one-sided sign bound `2^-positive_discordances * (roots - 1) <= 0.05`; ties
   are not evidence and an unattainable bound stops without more samples.
   Victory compares exact win endpoints only. Endless compares the frozen tuple
   of horizon survival, achieved ante, then public log best-hand score. Money
   and short-horizon progress cannot justify an override.
5. Report attempted, completed, unsupported, rejected, censored, action-
   override, and intent-only-override counts. Prove collection action inertness,
   conservative terminal selection, same-action intent selection, hidden-twin
   identity, legal execution, early-anchor non-influence, nonterminal-death
   fallback, and exact fallback identity. Reuse seed `207` only as an
   implementation diagnostic. The fresh screen is interpretable only with at
   least 20 attempted anchors, ten anchors that actually evaluate terminal
   samples, and one executed action-or-intent override; lower coverage fails the
   capability screen regardless of game outcomes.
6. After that diagnostic passes, compare scalar search and terminal action mode
   on the fixed fresh development block `1055-1074`. Freeze exact code,
   source/config digests, selector, budgets, and nonce before seed `1055`.
   Commit a machine-readable single-use preregistration before either report,
   bind both reports to its digest, and publish each report exclusively at its
   declared path. The strict comparator accepts only the exact retained scalar
   budget, default continuation tuning, terminal protocol, and preregistration
   digest; pair equality alone is insufficient.
   Require all 20 paired runs complete, zero rejected roots, at least as many
   wins, a positive paired mean-ante delta, and a run-cluster bootstrap 95%
   lower bound at or above zero. Also require one additional win or at least
   +0.25 paired mean antes. This is capability evidence only and cannot
   authorize tuning, replacement-gate, authority, or model promotion. Failure
   redirects work to a faster leaf value and stronger continuation, not another
   action-mode block.
7. Validate the pair strictly rather than relying only on the generic report
   comparator: identical ordered seeds, all runs complete, the same frozen
   repository/source digest, backend/runtime, scalar budget, root contract,
   nonce, and continuation; only declared terminal-mode fields may differ. Bind
   anchors, samples, endpoint/censor rules, root builder, selection statistic,
   fallback semantics, and nonce into one terminal protocol digest. Mark
   `1055-1074` exposed after this single frozen pair.

Result: retire terminal action selection. The frozen `1055-1074` pair completed
40/40 runs with identical trajectories: both modes won 2/20, cleared a mean
4.60 bosses, and reached Ante 6 on 9/20 seeds. Candidate terminal work added
79,017 rollout steps across 191 scheduled anchors. Ninety-three late anchors
evaluated exact terminal samples, yet every alternative recorded zero positive
win/death or Endless discordances; there were no action or intent overrides.
Seven anchors exceeded the independent 64-root compute ceiling and 35 had only
one root, so the strict coverage/failure gate rejected the report before its
zero outcome delta could be considered. Do not weaken the sign rule, raise the
root ceiling, or rerun these exposed seeds. Keep v6 collection and diagnostics
available, but action mode is not a strength path.

Next design sketch: move the learning target back to the dense paired utility
available at ordinary strategic decisions. Train a contextual public
state/action continuation model, not another terminal selector and not the
killed absolute/residual leaf. Reuse the relational entity representation and
full-rollout teacher schema where sound, but predict each candidate's paired
utility delta against the continuation-selected root. Split only by complete
originating run. Calibrate an abstention margin on held-out groups and require
no positive full-rollout regret, no false override on teacher ties, complete
legal-root mapping, and useful action coverage before any model influences a
rollout. A promoted continuation must still choose through the typed public
action surface, fail atomically to `PublicStrategicPolicy`, and face a fresh
paired development screen before protected panels.

Build this as a staged, auditable increment:

1. **Context and targets.** Bump the teacher schema rather than retrofitting
   the v4 or v5 files. Every admitted sibling sample stores its finite scalar
   search utility, and every row stores a versioned summary derived only from
   typed public history plus the incoming public intent. The first summary
   covers current-shop action/sale state, history-derived Joker counters, and
   public best-hand score. Reject malformed history, unequal paired sample
   counts, failed/censored siblings, duplicate roots, or non-legal actions.
2. **Behavior-inert dense collection.** Reuse the ordinary search's exact
   sampled sibling outcomes and canonical non-reorder roots. Collection never
   changes the selected root. Derive opaque origin-family IDs from a
   precommitted private HMAC key so they cannot be joined to the seed-ordered
   report, and keep every candidate run and all
   descendants in one atomic split. Report coverage by phase, ante, root
   family, and outcome; winners and failures are both training evidence.
3. **Paired objective.** Reuse the relational encoder and treat its per-action
   policy score as relative utility. Fit predicted score difference to the
   sample-paired utility difference from the behavior root with Smooth L1 plus
   ordering loss. Weight run, then decision, then alternative equally so large
   packs do not dominate. Preserve the absolute heads as diagnostics only;
   they cannot authorize an action.
4. **Selective offline gate.** Split by origin family before training.
   Calibration chooses a one-sided overestimation margin without reading the
   holdout. The untouched holdout requires complete root mapping, nonzero
   supported coverage, zero overrides on exact teacher ties, zero overrides
   with an adverse paired mean, non-positive run-weighted regret, and positive
   utility gain over the behavior root. Agreement is only descriptive.
5. **Separate authority.** Training emits a shadow artifact only. A distinct
   digest-bound certificate may authorize rollout continuation after the
   offline gate; old classification artifacts and an edited influence string
   cannot qualify. The wrapper is deterministic and stateless, handles only
   declared strategic strata, and falls back to the exact behavior action on
   abstention, unsupported context, mapping drift, shape/nonfinite output, or
   inference failure.
6. **Split live behavior from simulated continuation.** The root baseline and
   actual fallback remain the frozen `PublicStrategicPolicy`. Only isolated
   simulated future decisions may use a certified learned continuation. Bind
   both configurations into the search digest. This first changes search
   indirectly, so reports declare `affects_actions=true`.
7. **Distribution and evidence.** First prove the complete collector/trainer/
   shadow path on reused development seeds. Then freeze a fresh development
   collection after choosing its run-group counts. Before rollout influence,
   collect or audit support on the counterfactual states the continuation will
   actually see. A single frozen paired behavior-vs-learned-continuation screen
   must have zero invalid/rejected work, useful certified coverage, no win or
   lower-tail regression, and a strictly positive paired progression lower
   bound. Failure quarantines the artifact and exposed seeds; it does not tune
   the margin after the fact.

Acceptance tests cover public-history twin identity, malformed/future history
fallback, legal-action permutation equivariance, exact behavior on tactical or
unsupported states, distinct rollout forks, serial/parallel identity, import
firewalls, split collision rejection, holdout isolation, and artifact/
certificate digest tampering.

Fresh collection protocol, frozen before seed `1075`:

- Six separately atomic 50-run batches cover development seeds `1075-1374`.
  No batch may be extended or selectively rerun. Merge only complete reports
  with identical source, backend, search, teacher, and public schema digests.
- Red Deck, White Stake, pinned Jackdaw candidate, Ante cap 12, six common-random
  samples, one-ante horizon, 200-step cap, `override_z=1`, nonce
  `contextual-continuation-v9-frozen`, six workers. Dense collection is
  behavior-inert relative to that exact search.
- The schema-v4 collector stores the complete deployable root set, capped at
  512 roots. Overflow fails closed and invalidates the batch; outcome-dependent
  root subsetting is forbidden because it cannot be reproduced at inference.
- After all six batches merge, hash-split exactly 182 origin families for
  training, 59 for calibration, and 59 untouched holdout using nonce
  `strategy-split-v3-predeclared`. Calibration and holdout are each large
  enough that zero unsafe recommendations across all 59 independent holdout
  groups has a one-sided 95% upper error bound below 5%. Fewer than 59
  recommendation-bearing holdout groups cannot certify continuation.
- Before training, require at least 2,000 dense decisions, nonzero BLIND_SELECT,
  SHOP, and PACK coverage, at least 40% action-sensitive rows overall, zero
  rejected/censored stored siblings, all 300 complete origin families, at
  least 20 winning source runs, and at least 100 post-win rows across 20 origin
  families. At the first 100 complete groups, kill or redesign if action
  sensitivity is below 40%, victory endpoints occur in fewer than ten source
  families, or rejection/censor accounting is nonzero.
- Training architecture and optimizer remain those committed before the first
  batch. No epoch, margin, feature, root, or split tuning may read calibration
  or holdout results. Failure quarantines the cohort for diagnosis; it does not
  authorize a second split or a threshold adjustment.

No tuning `1-200`, quarantined `501-700`, replacement gate `701-900`, or
authority-secret seed may be used by this increment.

### Contextual v9 result and shop-card recovery (active 2026-09-05)

The frozen v9 collection completed all six preregistered batches and merged
17,004 dense decisions from 300 opaque complete-run groups. Raw-record
validation found 84.02% action-sensitive rows, all three strategic phases, 28
winning source groups, 38 groups with observed victory siblings, 526 post-win
rows across 28 groups, a maximum of 388 stored roots, and zero subsets,
rejections, or censored samples. The dataset SHA-256 is
`c4f268d343338397232e39ce01f56206951a90d57eb2805b619f50aa7f8a74c1` and
the merged report SHA-256 is
`4eb2c99a8d967662ca11099569002f84a83b2173a3db2dc95021d84f5e3e835d`.

Training failed closed before writing a model or report: organic Magic Trick
shops contain visible playing-card offers whose Balatro set is `DEFAULT`, but
`PublicObservation.shop` and the relational tensorizer admitted only generic
`PublicItem` values. This is not an unknown mechanic. The adapter already
represents the same playing cards structurally inside Standard packs, while the
shop path erased their rank, suit, enhancement, seal, and edition and public
legality rejected buying them. The v9 cohort is therefore valuable failed
evidence but cannot produce a promotable artifact: repairing the public/model
schema after seeing its outcomes would violate the frozen architecture
contract.

Recovery design sketch:

1. Add a typed public shop-playing-card offer containing a
   `VisiblePlayingCard` and its visible buy cost. Change the shop observation
   to an exhaustive union of ordinary public items and that offer. Unknown
   shapes, missing prices, and legacy generic `DEFAULT`/`ENHANCED` items remain
   fail-closed.
2. Have BalatroBot/Jackdaw adaptation preserve full visible playing-card
   structure in shops. Update the strict public codec and round-trip tests; do
   not infer hidden or absent modifiers from labels or tooltips.
3. Admit buying a visible shop card through the existing typed
   `BuyShopCard` action with no inventory-capacity requirement. Update the
   relational and retained hashed model encoders, strategy-option classifier,
   baseline filters, exact pre-boss candidate filter, and semantic diagnostics
   to branch explicitly on the shop-offer union. Search may value the new legal
   root through Jackdaw; do not add a hand-written purchase score.
4. Bump every observation-dependent teacher/search/model schema or protocol
   digest. Add organic Magic Trick and Illusion fixtures, codec round trips,
   legal-action tests, hidden-twin equality, tensorization/action-relation
   tests, and fail-closed malformed/legacy tests. Run focused and full suites
   plus diff review before collecting again.
5. Preserve v9 artifacts and hashes as failed evidence. After the corrected
   source is committed, preregister a fresh disjoint development cohort and a
   new private origin mapping before observing outcomes. Do not reuse or splice
   v9 groups, alter the frozen 182/59/59 split, or consume protected panels.

Only a fresh cohort under the corrected public schema may authorize a
continuation certificate. A diagnostic v9 training run, if used to exercise
the trainer, must remain explicitly non-influential and cannot set v10
hyperparameters from calibration or holdout results.

Adversarial review added two pre-freeze requirements. Stone enhancement hides
its underlying base rank and suit, so the public card adapter must replace both
with an explicit opaque sentinel everywhere a Stone card is observed; the
public value type and codec must reject real rank/suit values on Stone cards
and reject the sentinel on every other card. Hidden-twin tests vary the private
Stone base identity and require identical observations and model inputs. Also
exercise an organic Jackdaw shop-card purchase transition before freezing v10,
checking the indexed action, price, deck growth, shop removal, and resulting
public round trip. Synthetic adapter/RPC tests alone are not sufficient.

### Contextual v10/v11 failure and v12 recovery (active 2026-09-05)

The preregistered first-100 checkpoint fails and retires the entire v10 seed
reservation `1375-1674`. Batch 1 completed cleanly, but batch 2 encountered 63
rejected rollout transitions in one source run and therefore discarded its
teacher data atomically. Do not launch batches 3-6, recover the other 49 batch-2
runs, or combine v10 with any later cohort.

Exact replay localizes every rejection to selling Luchador during an active
Cerulean Bell. Jackdaw disables the boss and clears the forced card correctly,
but the public adapter infers that Cerulean remains enabled from name/status
alone and requires a forced slot. The missing value is the player-visible boss
disabled state, not a search threshold or a rollout exception policy.

V11 recovery design, completed before collection:

1. Add a required boolean disabled state to `PublicBlind`. Project it from the
   candidate blind and the authority observation contract. Cerulean requires
   exactly one visibly forced hand slot only while it is current and enabled;
   a disabled boss permits none. Bump every observation-dependent environment,
   policy, teacher, search, and model digest.
2. Add an organic candidate transition that sells Luchador against current
   Cerulean and proves the forced marker disappears, public legality remains
   nonempty, and normal play continues. Add codec, malformed-state,
   hidden-history twin, and relational tensor tests. Do not infer disabled state
   from tooltip prose or a private identifier.
3. Harden the collector before a fresh cohort. Verify the committed source and
   candidate runtime before executing a seed, repeat the check before atomic
   publication, discard the whole batch on incomplete runs, rejected rollouts,
   unavailable searches, censored samples, or searched/teacher count mismatch,
   and retain public rejection-reason diagnostics on failed batches.
4. Independently validate evidence. The merger authenticates the
   preregistration and private origin commitment, reconciles every seed result
   to its opaque group, recomputes exact legal non-reorder roots and the paired
   `z=1` selection, rejects malformed item zones, and proves the first-100 gate
   failed or passed before accepting later components.
5. Bind training separately after a successful merge. Commit a new training
   preregistration containing the merged hashes, actual trainer source, exact
   182/59/59 split, architecture, optimizer, seed, output paths, and fixed
   phase gate before reading calibration or holdout metrics. A phase may be
   certified only with recommendations in all 59 holdout groups, zero unsafe or
   false-tie overrides, strictly positive per-recommendation gains, zero
   run-equal regret, and positive run-equal gain.
6. Remove lightweight rollout JSON parse/serialize work with a private,
   copy-isolated normalized frame. Preserve canonical JSON on normal/authority
   paths and require exact action, public-state, teacher-target, terminal, and
   sampled-branch identity on reused development diagnostics before retaining
   the speedup.
7. Only after these gates pass, preregister six fresh 50-run batches on disjoint
   development seeds `1675-1974` with a new origin key. Protected panels
   `1-200`, `501-700`, `701-900`, and evaluator-secret authority remain sealed.

V11 is now retired before publishing any batch. A read-only authority audit
found that Amber Acorn flips and shuffles the Joker area, BalatroBot marks each
card hidden but still serialized its private key/order, and the Python adapter
dropped the hidden bit while constructing normal `PublicItem` values. Search
failed closed, but baseline and model policies could still observe the shuffled
identities. This violates the information firewall even if no completed v11
seed happened to exploit it. The interrupted batch published no artifact; none
of seeds `1675-1974` may be reused or spliced.

V12 firewall design:

1. Add a dedicated anonymous `HiddenJokerSlot` public value. It contains no
   identity, label, effect, runtime, edition, sticker, cost, or raw object ID;
   its tuple position is the only selectable fact. Joker zones admit either a
   visible `PublicItem` or this anonymous slot. Hidden values are invalid in
   every other area.
2. Strip hidden Joker payloads in the BalatroBot Lua extractor itself and
   independently require the minimal anonymous shape in the Python adapter.
   Normalize Jackdaw to the identical shape. A hidden flag attached to a full
   Joker payload must never reach policy state.
3. Preserve safe play under Amber Acorn: ordinary hand actions remain legal,
   but selling a hidden slot and any score/capacity/search path that requires
   its identity fail closed. Reordering may address anonymous slot positions
   only if both backends prove that action legal. Stateful belief may retain
   the previously observed Joker multiset but must sample all post-shuffle
   identity-to-slot permutations; that is a later capability, not part of this
   repair.
4. Add adversarial private twins that vary every hidden Joker identity,
   ordering, ability, edition, sticker, cost, and object ID while requiring
   byte-identical public observations, policy/model tensors, legal actions, and
   history. Add malformed-zone/payload tests plus an organic candidate Amber
   transition. Audit every other `state.hidden` area and reject any identity
   leak at the shared adapter boundary.
5. Advance observation, environment, policy, teacher, search, and model schema
   digests. Regenerate the authority-readiness patch, verify it against a clean
   upstream tree, run the full suite and source-fidelity checks, then commit the
   implementation separately from a v12 preregistration.
6. Reserve unused development seeds `1975-2274` for six immutable 50-run v12
   batches with a new origin key and the same collection/search gates. Do not
   begin collection until the committed source and runtime hashes agree.

Implementation status: the anonymous Joker type, authority/Jackdaw redaction,
adapter validation, conservative legal-action behavior, exact-model fail-closed
paths, schema advances, and adversarial regression tests are complete. The full
repository suite and lint pass, and the authority patch applies to a clean
BalatroBot archive with the installed serializer/schema files matching exactly.
The live BalatroBot test launcher does not expose its debug state-construction
endpoints, so a naturally reached Amber Acorn remains required authority evidence
before the firewall can be called organically certified.

Do not preregister or collect the reserved v12 cohort yet. It would certify the
same one-ante survival behavior that already cleared the 60-seed screen without
raising the strategic ceiling. Keep `1975-2274` unused while the stronger policy
artifact below is built; assign its final version and nonce only after behavior is
frozen.

### Post-firewall high-score capability program (active 2026-09-05)

The next artifact must optimize for a complete run and then Endless growth, not
only the next blind. Elite play converges on a small set of multiplicative engines:
held-card retriggers (Baron/Mime with red-seal steel Kings), played-card retriggers
(Idol or Triboulet with concentrated enhanced ranks), and consumable duplication
(Perkeo with Cryptid or Observatory). Those routes require deliberate deck
concentration, copying/reordering, boss control, and inventory choreography before
Ante 8. Implement in this order:

1. Close public action/state gaps that block real elite lines: boss-blind rerolls;
   buy-and-use consumables; consumable sale/use while a pack is open; legal
   inventory rearrangement around pack choices; full publicly inspectable deck
   composition; and visible runtime targets/counters used by Joker decisions.
   Every new action must round-trip through Jackdaw and authoritative Balatro.
2. Add a run-goal selector that commits from public evidence to victory,
   held-retrigger, played-retrigger, or consumable-duplication routes. Route state
   must value prerequisites and transitions rather than treating Jokers as an
   independent static tier list. It must preserve an escape path when the shop
   never supplies a route's key components.
3. Expand strategic candidates and continuation behavior for route-conditioned
   buys, rerolls, skips, deck destruction/conversion, seals, editions, copying,
   Joker order, hand order, and consumable timing. Preserve the ordinary baseline
   as a legal fallback for every decision.
4. Learn from good public trajectories only after the action/state surface can
   express those decisions. Ingest expert or high-performing self-play as
   observation/action sequences, label route and pivot decisions, behavior-clone
   for coverage, then use determinized search corrections and outcome targets to
   exceed the demonstrations. Never import seed, hidden draw order, or private
   Joker ordering.
5. Remove search bottlenecks before broad evidence collection. Profile scorer and
   clone costs, replace exact `Fraction` arithmetic with an equivalent integer or
   common-denominator representation where proven, cache repeated public score
   contexts, batch shared determinization prefixes, and add behavior-equivalence
   tests before accepting any optimization.
6. Freeze the improved artifact, then preregister unused development seeds and
   measure victory rate, Ante reached, log best-hand score, route completion, and
   search cost. Only an artifact that advances both survival and upper-tail score
   proceeds to protected authority evaluation.

Implementation checkpoint: the permanent View Deck composition and the Idol's
visible current target are now typed public state. Pure route profiles distinguish
victory, held retrigger, played retrigger, and consumable duplication without
changing actions yet. Idol readiness uses its target only during an active hand,
accounts for Wild/Smeared public semantics, and treats a depleted Seltzer as
unavailable. The next increment makes the route a revisable public-history state,
threads it through candidate identity and the learned context, and retains an
explicit victory fallback.

Revised implementation design after adversarial review: route identity is a
first-class public triple `(action, intent, route)` shared by search, teacher
records, training, shadow inference, and certified rollout continuation. Route is
long-lived context, not an alias for an action's short-lived intent. While a
specialized route is active, every admissible strategic action may retain that
route; an explicit same-action victory sibling is the escape and generic Tarot or
Planet generation does not by itself start the consumable-duplication route. A
`PersistentRoute` advances independently of the victory/Endless objective and
records public pivots. The actual rollout continuation and its fork must preserve
route capability for route-distinct roots, otherwise the decision fails closed.

The relational tensorizer encodes both incoming and candidate route. Oversized
Endless decks compact only untargeted remaining/permanent deck buckets after
retaining rare route payloads such as red-seal Steel Kings and Glass cards; raw
multiplicity controls retention without scaled-count ties, while bounded total
and distinct-count summaries remain available. Every targetable entity and
relation remains exact. Search advances
to v15, strategy context v3, teacher schema v10, relational model format v9, and
strategy diagnostics v5. The current checkout does not reinterpret v14/schema-v9
teacher artifacts; any historical merge must run from its frozen source revision,
and route-aware collection requires a fresh preregistration and merger contract.

This makes elite routes expressible but does not establish that choosing one
improves play. The next measurement is a small, fresh development-only behavior
screen with route diagnostics enabled. It must answer whether specialized routes
are ever selected, retained, completed, or escaped, and whether their extra root
fan-out reduces rollout throughput. Do not reserve or consume a new teacher panel
until that screen shows useful route diversity and no behavior regression.

### Post-route capability order (elite-play refresh, 2026-09-05)

Finish the immutable route-terminal learner exactly as frozen and interpret a
pass narrowly: it can validate long-horizon route identity for an existing first
action, not establish elite live play. The next capability work follows observed
failure data and public expert play rather than increasing the same rollout
budget:

1. Complete and differentially lock the public action surface for buy-and-use
   consumables plus legal pack-phase use, sale, and inventory choreography.
   Add a bounded trigger-checkpoint scheduler for hand, Joker, and consumable
   order at shop exit, blind start, first play/discard, scoring, and end of round;
   do not add every permutation to every strategic root.
2. Replace the self-reinforcing generic hand prior with a persistent typed build
   plan separate from the Endless route: target hand family, enabling-card
   readiness, chips/additive/xMult coverage, scaling source, deck consistency,
   seal support, economy stage, pivot cost, and confidence. The first 40 route
   development runs won only 2; Pair or Two Pair dominated 34 of 38 losing-run
   hand histories, while many deaths retained cash or empty Joker slots.
3. Export and lockstep-test missing visible runtime values before using them:
   current Mail-In Rebate rank, Castle suit, Invisible Joker duplication progress,
   Turtle Bean decay/hand-size bonus, and any Satellite history needed by its
   public rule. Unknown or unavailable values continue to fail closed.
4. Learn multi-round spending and sticker lifecycle value instead of adding more
   fixed reserve constants. Model temporary bridges, Rental liabilities, empty
   slots, pack development, and planned replacement as continuation value.
5. Ingest complete authoritative expert trajectories only after steps 1--3 can
   express their actions. Retain canonical public observations/actions/history,
   strip seed and all private state, validate temporal legality and hidden twins,
   split by complete run, behavior-clone for coverage, then correct demonstrated
   and sibling actions with paired determinized search and DAgger-style expert
   iteration.

For post-win strength, refine the three broad non-Victory routes into explicit
public stages: assemble, stabilize economy, concentrate the deck, duplicate exact
payloads, gain slots/hand size, schedule copy targets, lock late boss/draw setup,
then balance scoring triggers. Represent exact red-seal Steel Kings and trigger/
xMult equivalents rather than broad related-tag counts; add distinct played-card
anchors such as Photograph, Ancient Joker, and Bloodstone; and represent the
Perkeo-plus-Death sculpting stage before Cryptid/Observatory. Deep Endless uses a
learned long-horizon stage value, not brute-force one-Ante particles.

Preregister the first v15 behavior screen on fresh development seeds `2275-2286`
from implementation commit `7fa23ab`. Run two complete Red/White panels with the
same strategic continuation, policy seed `baseline-v1`, nonce
`elite-route-v15-screen`, six determinization samples, one-ante horizon, 200
rollout steps, `z=1`, 1,200 decisions, Ante-20 cap, eight workers, no reorders,
and full decision recording. The control uses ordinary action roots; the
candidate changes only `--strategy-options`. Publish exclusively under
`runs/experiments/elite-route-screen/`. Treat this as capability and cost
evidence, never a protected strength gate. Require 12/12 complete runs in both
arms, reconcile every seed, report paired progression and best-hand score,
specialized route selections/transitions/final stages, root expansion, rejected
rollouts, and rollout steps per second. If no specialized route is selected or
the paired outcomes regress, diagnose the decision records before widening the
panel or collecting trajectories. Preserve seeds `1975-2274` untouched.

The control arm exposed a public-state lifecycle defect on seed `2277` and
published no report. Retire the entire observed block `2275-2286`. The terminal
play lost while Amber Acorn was still the current enabled Boss, so Jackdaw
correctly retained face-down anonymous Joker slots but `PublicObservation`
admitted them only during `SELECTING_HAND` and rejected the `GAME_OVER` state.
Repair the contract narrowly: anonymous slots remain valid during terminal game
over only when every Joker is anonymous and the current enabled Boss is Amber
Acorn. Keep non-Amber, disabled, mixed, and nonterminal out-of-hand states fail
closed. Add adapter/public-codec and organic Jackdaw loss-transition regression
coverage, run the full suite, commit the repair, then preregister a disjoint
replacement behavior screen; do not infer route performance from the 11 surfaced
control outcomes.

With the lifecycle repair frozen at commit `83c84ae`, preregister replacement
development seeds `2287-2298`. Reuse the exact v15 screen settings and report
contract above, changing only the disjoint seed range and output names. The
ordinary-root control must finish and publish before the route-conditioned arm
starts. Apply the same completion, reconciliation, progression, route-diversity,
and normalized-cost analysis; never combine these rows with the retired block.

The replacement control published an invalid 11/12-complete report and exited
2; retire seeds `2287-2298` and do not start its candidate arm. Seed `2288`
cleared a live Cerulean Bell, entered the next shop, then the baseline's
history-derived score probe copied the prior hand's forced slot into a projected
future hand whose new blind row no longer contained a current Cerulean Bell.
This is a heuristic projection bug, not an observation leak or simulator error.
Clear `required_hand_slots` when constructing the next-blind scoring projection;
the selected cards remain the observed representative hand, but a prior Boss's
forced-selection rule must not persist. Add a regression from a genuine
Cerulean-before-play / Round Eval / cash-out history, verify the full suite, and
commit before preregistering another disjoint screen.

Before consuming a third fresh block, replay retired seed `2288` once from the
repair commit with the identical ordinary-root control settings and one worker,
publishing only a post-fix diagnostic under `runs/experiments/elite-route-screen/`.
Ignore its outcome; require a complete trajectory with no forced-slot policy
error. Only that causal replay authorizes a new disjoint paired screen.

The retired seed `2288` replay completed through terminal state with no policy
error, 107 searches, zero rejected rollouts, and 136.6 rollout steps/second; its
win is diagnostic-only. Preregister the third and final small v15 behavior screen
on fresh development seeds `2299-2310`, again with the exact paired settings and
exclusive report contract above. If this block exposes another completeness bug,
repair it but stop consuming fresh panels and replace broad online screening with
targeted lifecycle fuzz/replay until that audit is green.

The complete third screen rejects v15 route selection. The ordinary-root control
finished 12/12 with two wins and mean 5.67 antes; the route arm finished 12/12
with zero wins and mean 3.58 antes. The paired ante delta was -2.08 with bootstrap
95% interval [-3.00, -1.25], and log10 best-hand score fell by 0.55. The route arm
changed 183/495 actions even though 481/495 selected roots were labelled Victory;
only one specialized held-retrigger route ever started. Root expansion rose while
rollout throughput fell. This is decisive development evidence that v15 did not
add a specialist option above control: it replaced the proven ordinary root space,
used lexicographic one-ante economy tie-breaks online, and made even Victory use a
route-filtered continuation. Retain the implementation as rejected evidence, not
as the deployable policy, and do not consume another fresh seed block yet.

The v16 repair must be control-preserving by construction:

1. Build generic roots from every ordinary legal non-reorder action in exactly
   the same order as action-only search. With no active specialist, evaluate those
   roots with ordinary continuation and choose their winner using the unchanged
   paired scalar progress rule.
2. Add only non-Victory specialist route roots as challengers. A specialist may
   replace the ordinary winner only when its paired scalar rollout advantage
   clears the same significance gate. `GoalUtility` remains a teacher/shadow
   target until a calibrated long-horizon leaf value is certified; it does not
   choose live roots.
3. Victory means ordinary policy: never pass it to route-filtered continuation,
   never persist it, and clear active route/intent on an explicit Victory escape.
   While a specialist is active, generic legal actions retain that route and a
   same-action ordinary escape remains available.
4. Record the ordinary winner, specialist challengers, specialist override,
   retention, and escape separately. Advance search/report schema versions rather
   than reinterpreting v15 evidence.
5. Before any game replay, prove exact selected-action parity between v16 strategy
   mode with no admitted specialist and ordinary search over shared samples; test
   no-op Victory behavior, specialist significance gating, active retention, and
   same-action escape. Run focused and full suites plus Ruff and diff review.
6. Reuse `2299-2310` only as a diagnostic causal replay. It must match control up
   to any genuinely selected specialist override. Preregister a disjoint fresh
   screen only after that replay is complete and reconciled; never use the replay
   as strength evidence.

Implementation checkpoint: v16 now runs the ordinary and specialist lanes on the
same frozen public determinization samples. The ordinary prefix uses the supplied
legal-action order, the unchanged non-reorder root filter, plain continuation,
scalar progress, and the existing paired significance selector. It chooses the
ordinary winner before constructing specialists. Victory is normalized to no
route at both policy and rollout boundaries. A retained route contributes one
isolated route-policy challenger rather than every legal action; new non-Victory
route options are deduplicated and capped at 128, with overflow or construction
failure disabling only the overlay. Terminal action selection may label any
specialist but cannot execute one that did not clear the scalar overlay gate.
Diagnostics separate control baseline, ordinary winner, scalar specialist
proposal, effective route transition, generated/admitted roots, best losing
challenger evidence, route escape, route abandonment, and specialist-only
unavailability. The implementation and report protocol are v16; 941 repository
tests and Ruff pass. The next action is the already-observed causal replay, not a
fresh strength panel.

Preregister one v16 causal replay of development seeds `2299-2310`, publishing
only `runs/experiments/elite-route-screen/v16-route-causal-replay-seeds2299-2310.json`.
Use Red/White, strategic continuation, policy seed `baseline-v1`, nonce
`elite-route-v15-screen`, six samples, one-ante horizon, 200 rollout steps,
`z=1`, 1,200 decisions, Ante-20 cap, eight workers, decision recording, and
`--strategy-options`; these exactly match the rejected v15 screen apart from the
frozen v16 source. Require 12/12 complete runs, zero rejected ordinary rollouts,
and reconciliation against
`runs/experiments/elite-route-screen/v15-control-seeds2299-2310.json`. Before the
first specialist override, selected public actions and terminal outcomes must
match control. Every specialist override must name a non-Victory route, have a
strictly positive recorded paired lower bound, and explain any later divergence.
If there are no specialist overrides, require exact per-seed outcome and recorded
action-sequence identity. This replay is repair evidence only and never enters a
strength interval. A mismatch without an admissible specialist retires v16 for
further code diagnosis; a complete match authorizes preregistration of one fresh
small capability/cost screen.

The v16 causal replay passes the repair gate. It completed 12/12 with zero
rejected rollouts, zero specialist overrides, and exactly the v15 control's two
wins, 5.67 mean antes, 8/12 survival to Ante 6, Ante-9 maximum progression,
69,102 best hand, per-seed terminal/final observations, action aggregates, and
decision counts. After filtering the 76 new single-ordinary-root overlay checks,
all 926 multi-root decisions match the control's phase, ante, continuation
baseline, ordinary selected action, ordinary root count, and sample count in
sequence. The overlay generated and evaluated 199 specialist roots across 72
decisions; five best challengers had positive paired means, but none had a
positive lower bound. The closest lower bound was -0.031 for a played-retrigger
pack choice on seed `2309`. Extra work was 22,168 rollout steps (+2.53%), while
normalized throughput was 95.4 versus 96.7 steps/second (-1.37%). The repair is
therefore behaviorally exact and its marginal overhead is bounded.

Do not spend a fresh screen merely to confirm an inert one-ante overlay. The
causal replay shows the next strength bottleneck: specialist routes need a
long-horizon public leaf/terminal value that can recognize engine assembly before
it immediately improves survival. Audit the existing frozen expert-iteration and
success-teacher artifacts next. If their provenance, coverage, and target gates
are valid, train a v16-compatible relational route value and keep it shadow-only
until calibration and counterfactual replay show that it ranks the five near-miss
specialists correctly without displacing ordinary survival. If the artifacts are
invalid or route-poor, repair the collection protocol and collect high-quality
public trajectories/terminal labels on unused development seeds before training.

The audit finds no trainable route artifact: success-teacher v5 is schema 2 and
contextual v10 batch 1 is schema 5, both store only `route=null`, and both are
already frozen as failed diagnostic evidence. Current teacher schema 10 and model
format 9 deliberately reject them. Before designing a fresh cohort, run one
action-inert success-teacher diagnostic on already-observed seed `2309`, whose v16
replay contained the closest specialist near miss. Use the exact v16 replay
behavior settings and add the frozen success-teacher defaults: first shop per
ante, first pack per ante from Ante 4, Boss select from Ante 5, two paired samples,
600-step cap, victory/death before winning and two-ante Endless horizon after it.
Publish exclusively at
`runs/experiments/route-success-diagnostic-v16/seed2309.report.json` and
`runs/experiments/route-success-diagnostic-v16/seed2309.teacher.jsonl`. Require a
complete action-identical source trajectory, zero rejected or censored terminal
work, and at least one non-Victory candidate at a terminal anchor. Measure route
and phase coverage plus action-sensitive Ante-8/Endless/log-score targets. If the
near-miss route is absent or terminally tied, redesign anchor scheduling/value
targets before reserving fresh seeds; do not scale an uninformative collector.

The seed-2309 diagnostic validates the collector but rejects an Ante-8-only route
target. The source trajectory is exactly action/outcome identical to the v16
causal replay and all 17 scheduled anchors completed with zero rejected,
censored, unavailable, or fallback work. The teacher produced 17 schema-10 rows,
269 roots, three route-diverse rows, and 17 same-action/different-route pairs.
Five of those pairs changed paired terminal progress, two positively; one Ante-5
played-retrigger sibling improved mean terminal progress by `+1.217` and cleared
the next Boss in a sample where its identical ordinary sibling failed. No pair
changed the Ante-8 label, and the original target-[4] near miss was terminally
worse. The usable signal is therefore route-conditioned paired Q residual with
survival guards, not a standalone binary victory head. The 154-root Ante-5 pack
also consumed 14,401/21,515 teacher steps, so exact pack-root fan-out is the first
collection-efficiency target.

Build a separate route-terminal expert-iteration protocol; do not loosen or
reinterpret the frozen contextual merger, trainer, or continuation certificate:

1. Report `--strategy-options --success-teacher` collections explicitly as
   `route_terminal_paired_utility`. Bind search v16, teacher schema 11, the exact
   action-inert anchor schedule, paired sample count/order, complete-root cap,
   public origin groups, source/runtime digests, and atomic rejection semantics.
2. Add route coverage computed from the records: route-diverse rows and groups,
   roots by route, exact same-action/different-route pairs, pair sensitivity and
   signed residuals for current blind, next Boss, Ante 8, Endless ante, log score,
   and scalar progress. All-null/Victory-only routes, reordered/substituted
   triples, partial groups, subsets, censored targets, and mixed configurations
   fail closed. Freeze numerical cohort gates only after local fixtures and the
   reused-seed diagnostic exercise the metric contract.
3. Add a distinct preregistration and merger path for exact v16 triples. Preserve
   candidate and incoming routes, sample pairing, original order, behavior and
   ordinary indexes, and configuration digests. The old v14 ordinary merger stays
   byte-for-byte semantically frozen.
4. Train the existing candidate-conditioned value vector first; do not invent a
   no-op terminal leaf. Evaluate paired specialist-minus-matched-ordinary
   residuals by route, goal, phase, and ante, with false-override, regret,
   survival-non-regression, calibration, and positive-support gates. The executed
   source run outcome labels only its factual behavior, never sibling candidates.
5. Shadow-rank an immutable snapshot of the exact v16 searched roots, including
   ordinary winner and admissibility. Record every head for every triple; never
   rebuild generic roots, admit Victory as a specialist, or rank a rejected root.
6. Authorize influence only through a new route-leaf certificate bound to the
   model, dataset, report, comparator, supported routes/phases/antes, root cap,
   calibrated error radii, and v16-or-successor candidate contract. A missing or
   unsupported certificate returns exact v16 behavior. Never add one deterministic
   model delta to every rollout particle as if it were independent evidence.

Implement and test the collection/report contract first, then the merger and
training gates, then exact-root shadow inference and certification. Do not reserve
fresh development seeds or train from the one-seed diagnostic.

Teacher schema 11 must make the v16 comparison self-contained before fresh
collection. Persist `ordinary_index`, `behavior_index`, and `selected_index` as
separate exact-triple indexes; require `baseline_index == ordinary_index` so the
existing paired loss learns against the proven ordinary lane. Terminal selection
also compares against `ordinary_index`. `behavior_index` records the root that
generated the factual trajectory and does not label sibling outcomes. A
route-terminal record is valid only when the accompanying success decision proves
`executed_index == behavior_index` and `affects_actions=false`. Schema-10 records
remain frozen diagnostic evidence and the active reader rejects them; they cannot
enter the new protocol.

Collection/report checkpoint: schema 11 and the action-inert route finalizer are
implemented locally. Every draft now carries mandatory ordinary, behavior, and
teacher-selected indexes; the ordinary root must have null intent and route. The
success-decision report carries all four root identities, and publication rejects
the whole panel unless counters, sample cardinality, uncensored endpoints,
complete candidate space, exact triples, `executed == behavior`, and action
inertness agree. The schema number is part of the teacher configuration digest.
An end-to-end test authenticates a real collector-emitted draft. This is not yet
a collection authorization: the distinct preregistration, merger, and numerical
route-support gates in steps 2-3 remain next.

Route collection v1 design sketch (before implementation): reserve development
seeds 2311-2410 as five immutable 20-run bundles. The exact v16 base search uses
six one-ante samples; the action-inert terminal teacher uses two samples, starts
at Ante 4, continues two Endless antes, and has a 600-step cap. Strategy options
are enabled; terminal action influence, dense collection, reorders, learned
continuations, and shadows are forbidden. A separate
`route_terminal_teacher_preregistration` binds schema 11, the fixed nonce,
candidate/runtime/backend/source digests, tuning, HMAC origin key, batch paths,
and collection-only support gates. The first 20-run bundle is a pilot: later
bundles cannot start until its report and teacher bytes revalidate and show
minimum route support. It can authorize more collection, never training or model
influence.

Move route coverage into one shared public-only module before the evaluator and
new merger consume it. Report aggregate and per-route support across phase, ante,
goal, exact same-action/null-route pairs, sample cardinality, and all six target
residuals. Keep the contextual validator, binding field, merger, gates, and
trainer unchanged. The route evaluator gets independent validation, source-freeze
checks, and crash-atomic two-file publication. Only after that implementation is
committed may the preregistration file bind its revision/digest and reserve the
pilot. The separate merger follows in the next commit and must reconstruct every
HMAC origin family and factual behavior/report identity before merging.

Collection implementation checkpoint: the shared coverage/component validator,
route v1 constants, exact preregistration parser, first-batch kill gate, three
source-freeze checks, distinct report binding, and route-labelled atomic bundle
publisher are implemented and locally exercised. The component validator
reconstructs record-bearing HMAC families from the source rows, preserves
zero-anchor completed runs in the report, requires contiguous decision indexes,
and reauthenticates outcomes plus all four root identities. Every specialist must
have exactly one same-action null-intent/null-route sibling. The pilot gate is
support-only and cannot authorize training. Next: full regression and commit;
then create the preregistration/key against that clean implementation revision,
commit only the preregistration, and run batch 01. Build the separate merger while
that immutable pilot runs.

The retired v11 design remains a pre-win/early-Endless continuation increment,
not the complete high-score policy. Its useful continuation machinery is retained
inside the broader program above, while its collection protocol remains retired.

Route score-cache design sketch (before implementation): the latest profile
attributes almost all tactical best-play time to exact public scoring, while the
existing cache is scoped to one `PublicObservation` object and therefore misses
value-equal observations emitted by independent Jackdaw clones. Retain that
identity cache as the fast front layer and add one bounded, process-local LRU
whose collision-free key is the complete canonical public observation, ordered
selected hand slots, and normalized optional hand statistics. Cache only
successful immutable results after the existing Amber Acorn conservative
projection; never key on or retain private engine state. Prove cold and warm
scores match for every legal ordered selection, preserve order-sensitive and
custom-stat distinctions, test deterministic eviction and failure non-caching,
then replay matched search and route-terminal trajectories. Keep the cache only
if actions, projections, root identities, terminal outcomes, rollout counts, and
failure counters are identical and the six-sample workload gains at least five
percent wall-clock throughput. Otherwise delete it as a rejected optimization.

The cross-observation score cache is rejected and deleted. On the matched
six-sample seed-210 replay, every non-timing report field and all 34,506 rollout
steps were identical, but elapsed time increased from 281.1 to 343.5 seconds,
throughput fell from 124.1 to 101.5 steps/second, and peak RSS increased from
227.9 MB to 241.5 MB. Canonical public serialization costs more than the clone
reuse saves on the real workload; do not revive this key or retain its code.

Route learner design sketch (before batch 05 exists): keep the frozen v14
trainer, model envelope, shadow wrapper, and continuation certificate unchanged.
The route learner gets its own protocol, loss/evaluation module, artifact
envelope, exact-root shadow, trainer, and certificate family while reusing only
the relational network and public tensorizer. Freeze whole authenticated batches
01--03 as train (60 source runs), batch 04 as calibration (20), and batch 05 as
untouched holdout (20); never rebalance opaque groups after labels are visible.
The merger preserves the exact unique opaque-group membership of every canonical
batch. Minimum admission is respectively 12/4/4 record groups, 120/40/40 rows,
60/20/20 matched pairs, 6/2/2 scalar-sensitive pairs, and at least one positive
and one negative pair in every split. A miss produces no model.

Each non-Victory specialist is compared with its unique same-action root whose
intent and route are both null, even when that comparator is not the decision's
global `ordinary_index`. Train differences for scalar search utility and the
five public terminal heads. Arithmetic-mean the paired samples before applying
Smooth-L1 or signed ordering because the public model predicts the sampled
expectation, then weight equally by run, eligible decision, and eligible pair;
each head recomputes those weights after its null mask. Do not train
cross-entropy on `selected_index`, use
`behavior_index` as a target, or apply factual run outcomes to sibling roots.
Null-mismatched head targets are masked and counted; utilities remain
lexicographic rather than blended. Freeze a distinct learner preregistration
before opening batch 05, binding the 3/1/1 split, optimizer, model configuration,
objective, comparator, collection protocol, and numerical gates.

Calibration uses only batch 04 and fits fixed one-sided overprediction radii.
For every head, canonicalize by opaque group, decision, specialist, and sample;
fit the run/decision/pair/sample-equal mean of `target - raw residual` as the
bias, then take the maximum non-negative corrected overprediction as the
empirical radius. Admit a pair/head only when every paired sample is jointly
resolved. This is an empirical envelope, not a statistical coverage claim.
Batch 05 must have at least two safe recommendations from distinct groups;
scalar residual MAE must beat zero, sensitive-pair balanced sign accuracy must
exceed one half, and next-Boss residual MAE must beat zero. Current-blind
residual MAE is diagnostic-only because route-diverse terminal anchors occur
after that blind has cleared and the pilot observed 160/160 exact-zero pairs;
any observed current-blind regression remains a hard failure.
and every recommendation must have positive observed utility with no tie,
survival regression, Victory route, rejected root, or regret against the best
safe same-action specialist. Victory recommendations cannot reduce resolved
Ante-8 outcome; Endless recommendations cannot reduce resolved Endless ante or
log score. A certifiable support cell is the exact `(route, goal, phase, ante)`
tuple with train/calibration/holdout pair and group support, mixed signs before
holdout, and a safe positive holdout recommendation; independent field lists
must never authorize an unseen Cartesian product.

Shadow evaluation consumes an immutable snapshot of the exact v16 roots in
their original order, ordinary count/index, pre-terminal selected index,
per-root admissibility/rejection, candidate-space size, root cap, and candidate
contract digest. It never rebuilds candidates. It scores and reports all six
outputs for every root while executing v16 unchanged; any malformed snapshot,
unsupported cell, non-finite output, model error, trace mismatch, or over-cap
root fails closed. The first certificate may change only intent/route identity
among same-action roots when v16 selected ordinary. It cannot change the current
action, alter an already-selected specialist, authorize rollout continuation,
or add a deterministic model value to individual rollout particles. It binds
the model, merged data/report, learner preregistration, training report, exact
shadow replay, candidate contract, support cells, caps, and calibration radii.

The route trainer is a one-shot, fail-closed evidence producer. It accepts only
the canonical five-component merged bundle and the two frozen preregistrations,
captures a clean source snapshot before reading labels, and verifies every
dataset, report, collection, merger, learner, split, schema, teacher-config, and
source binding before optimization. It checks the preregistered split admission
before constructing the model, trains exactly the frozen 30 full-batch epochs,
fits calibration on batch 04, and evaluates batch 05 once. A failed admission
or holdout gate emits a no-overwrite rejection report and no model. A passing
gate atomically publishes a shadow-only model/report bundle, then reloads and
digest-checks the staged artifact before publication. The report records all
losses, calibration atoms, literal-zero comparisons, support cells,
recommendations, failures, environment versions, exact command, and immutable
input/output digests; neither outcome creates authority or a certificate.

Pre-freeze calibration-admission correction: the real first two components show
that resolved Endless targets are sparse even when scalar pair and group minima
pass. Bind the learner preregistration to at least one fully resolved calibration
pair for every trained residual target, expose the exact per-target counts in the
split-admission report, and reject before model construction when any target has
no calibration support. Keep the fitter's independent no-support rejection as a
second fail-closed check. This converts a predictable one-shot fitter exception
into the already specified atomic `split_admission_failed` evidence report; it
does not impute missing targets, relax calibration, or authorize partial heads.

Pre-freeze component-path portability correction: collection reports preserve
the producer checkout's absolute dataset path, but that machine-local prefix is
not evidence identity. The trainer still reads each original component only from
the preregistered path beneath its explicit repository root and rechecks its
bytes, hashes, HMAC origin families, and report binding. Validate the report's
path as either that exact frozen relative path or an absolute path ending in the
same full frozen batch path. Reject traversal and sibling/name-only matches. This
allows an immutable bundle to be audited in a second clean checkout without
rewriting signed report bytes or weakening component authentication.

Route-terminal v1 outcome: the frozen five-batch collection completed all 100
source runs and merged 825 records from 99 record-bearing groups, but the
one-shot learner is rejected before model construction. Batch 04 calibration
contains zero jointly resolved non-Victory/ordinary pairs for both
`endless_ante` and `log_score`, so the preregistered per-target admission guard
fails exactly as intended. Batch 05 holdout cannot repair calibration and was
not inspected to alter the split. The rejection report contains no training
epochs and no model artifact. Preserve this corpus as negative evidence; do not
impute targets, rebalance batches, train a partial-head model, or recollect the
same behavior under new seeds.

The complete cohort also resolves the next direction. It won only four of 100
runs; Pair or Two Pair was the terminal primary hand in 88 of 96 losses; 71
losses ended with at least $10 and both ordinary consumable slots empty; and
the route specialist overrode 1,208 challenges only ten times. This is a
capability/continuation failure, not a reason to increase the same search
budget. Before another teacher cohort, close the action/state surface, add a
persistent typed build plan, and seed rare route/pivot coverage from validated
public expert trajectories before paired-search correction.

Immediate post-freeze action-contract design: remove the unproved rule that a
generic `SMODS` pack permits hand, Joker, or consumable reordering. Normal
`SELECTING_HAND` hand reorders and `SELECTING_HAND`/`SHOP` Joker/consumable
reorders remain unchanged. A synthetic SMODS pack with at least two entries in
each area must generate none of the three reorder actions and must reject each
direct action through `is_legal`. This is a fail-closed correction only; do not
enable buy-and-use or pack-phase inventory operations until BalatroBot,
Jackdaw, and an organic authority trace establish each exact contract.

First buy-and-use vertical slice: admit `BuyShopCard(mode=use)` only for a
visible affordable Planet whose existing public no-target consumable rule is
usable at the current shop. This action bypasses consumable storage capacity,
matching vanilla's `buy_and_use` button, but does not admit targeted Tarot or
Spectral cards, invent a target, or expose an intermediate hand. The RPC is the
ordinary `buy` endpoint with the explicit string mode `use`. BalatroBot must
select the card's real buy-and-use UI definition and return only after the shop
count and money change exactly once, the Planet is absent from inventory, the
corresponding public hand level changes, and the controller/use locks settle
back in `SHOP`. Missing button/state or any non-Planet use request fails closed.
Jackdaw must mirror vanilla's atomic order behind the evaluator boundary:
remove the offer, add it to deck effects without storing it, fire purchase
context once, charge it, apply its no-target Planet use, and release it only
after the use chain. Roll back the private candidate state atomically if any
step rejects and end with the original consumable capacity. Correct the
existing store-capacity rule at the same boundary: a Negative consumable may
enter a nominally full tray. Add full-slot, Negative, affordability, wrong-kind,
codec/RPC, model-identity, candidate round-trip, Constellation/Satellite, and
authority endpoint tests. Preserve the store action beside the new use action;
neither the baseline nor search may assume one dominates. Organic real-Balatro
Planet buy-and-use plus zero observed-state differential mismatch is required
before the capability is considered authority-certified.

Implementation status: the Planet-only vertical slice is built through the
public action/codec, BalatroBot adapter, real `buy_and_use` authority UI,
Jackdaw compatibility transaction, semantic diagnostics, and both public model
families. The authority endpoint passes a real-Balatro full-tray transition and
invalid-mode/wrong-kind rejections; candidate tests cover a Negative Planet,
Constellation, usage accounting, unknown-key rejection, and in-place rollback
after a forced post-purchase failure under Credit Card. The regenerated
BalatroBot readiness patch now applies cleanly to its pinned upstream tree and
reverse-checks against the installed mod. Keep the capability provisional: the
test fixtures are mutation-assisted and therefore are contract tests, not
promoted evidence. Next commit this vertical slice, then capture a natural
public-policy shop Planet on fresh nonprotected development seeds and require
an exact authority/candidate transition before calling it certified.

Organic coverage protocol: reserve development seeds 2411--2430 as one ordered
authority scan. Add a deterministic `planet_use` coverage mode that never skips
a blind, takes the existing public tactical play/discard path, selects the first
legal `BuyShopCard(mode=use)` in shop order, and otherwise rerolls while its
ordinary per-shop action budget remains before leaving. It may inspect only the
legal public action list and visible history. Report `buy_shop_card_use`
separately and require at least one accepted instance; do not select seeds from
candidate offers. Replay every completed authority trace from the beginning and
stop at the first mismatch. The first attempted seed-2420 trace is diagnostic
only: authority exposed no Planet use and replay mismatched at transition zero
on deck-composition edition representation, so repair that independent parity
defect before promotion.

Parity-repair design: Balatro's JSON wire format omits unset optional
`enhancement`, `edition`, and `seal` fields from permanent-deck rows, while the
Jackdaw projection currently emits them as null. Emit a sparse candidate row
with the four required fields always present and each optional field only when
set; preserve those fields for modified cards. Pin both cases in the Jackdaw
bridge tests, replay the seed-2420 diagnostic to transition equality, and run
the full suite before committing. Then restart the ordered 2411--2430 scan from
a fresh checkout at that commit under `planet_use`; never reuse or normalize
the failed trace.

Implementation status: the sparse wire repair is complete. The immutable
seed-2420 diagnostic now replays all 25 transitions exactly, its base/modified
card regression passes, and the full suite is green at 1,113 tests. Commit this
repair before constructing the fresh checkout for the ordered coverage scan.

Authority certification status: complete at commit `f74e683`. The clean
ordered 2411--2430 lane finished 20/20 runs and replayed all 846 transitions
exactly. It exercised 26 Planet buy-and-use actions on 15 seeds across nine
Planet keys. The checked trace-set digest is
`134680fcf001608b392677fa22dd08d5364fb7169e8e62c7eff906759d7a3bbe`.
The narrow action may now enter public strategy/search; this does not promote
the coverage policy or establish any strength gain.

After that correction, instrument clone, root-step, continuation/scoring, and
allocation/GC time at terminal-teacher anchors. The Arcana tail is valid
exhaustive targeting: 13 decisions with at least 100 roots account for 2,017 of
the first four batches' 6,982 roots. Do not cap targets, roots, samples, or the
terminal horizon. Any memo or batching optimization must retain exact root
identity/order, actions, targets, endpoints, steps, labels, outcomes, and
failure counters on a matched nonprotected replay before a throughput claim.

Terminal-teacher timing design: add one opt-in evaluator flag whose collector
is absent by default and never enters the policy wire, root builder, selector,
teacher record, or model. With `perf_counter_ns`, aggregate count/total/max for
sample-and-freeze, frozen clone, first/root engine step, continuation choice,
later play engine steps, later non-play engine steps, and clone teardown,
separately for ordinary, strategy-ordinary, strategy-specialist, and
success-teacher lanes. Around each success-teacher anchor only, attach a
non-forcing GC callback and snapshot `sys.getallocatedblocks()` before/after;
report actual collection count/time and clearly named net block deltas. Never
call `gc.collect()`, alter thresholds, reset peaks, or enable `tracemalloc`.
Emit opt-in per-run and aggregate diagnostics outside authenticated teacher
content. Unit tests must reconcile timing counts to a synthetic rollout and
prove the disabled report shape is unchanged. First profile reused development
seed 2387, whose frozen batch-04 run contains the complete 367-root Arcana
anchor, then compare all non-timing action, root, endpoint, step, failure, and
terminal fields against its frozen report before choosing an optimization.

Implementation status: the opt-in timing collector and evaluator report path
are built. Synthetic rollouts reconcile clone, root-step, continuation-choice,
later-step, and close counts; GC callbacks are removed after each anchor and
worker summaries merge timing/allocation/GC fields without changing the
default-disabled report shape. Focused tests pass 98/98 and the full suite
passes 1,116 tests. Commit this observational slice before producing a clean
seed-2387 profile.

Profile replan: the evaluator correctly forbids current source from reusing
the frozen route-teacher seeds 2311--2410 without their exact preregistered
implementation, so seed 2387 cannot be run under the new profiler and no guard
will be bypassed. Reserve fresh nonprotected development seeds 2431--2440 for
one clean timing-enabled screen at the same v17 search and terminal-teacher
budgets. Use its widest natural Arcana anchor and aggregate buckets for the
optimization decision. The prior 367-root record remains corpus-shape evidence,
not a matched runtime baseline. After choosing one optimization, compare
timing-disabled and timing-enabled final-code runs on the same newly observed
seed and require exact equality of all non-timing fields.

Fresh profile result: commit `da9cd9d` completed all ten seeds 2431--2440 with
zero rejected/censored rollouts and 657,046 total rollout steps. The widest
current anchor is seed 2439's Ante-4 Arcana pack: 186 roots, 372 evaluations,
19,599 steps, and 156.23 seconds under six-worker contention. Across 82
terminal anchors, continuation choice consumed 512.40 of 640.17 seconds
(80.0%); later non-play/play engine steps consumed 80.24/41.02 seconds;
root steps 2.72, clone 1.57, sample/freeze 0.75, and close 0.15. Actual GC
consumed 85.63 seconds across 212,480 collections, overlapping those stages.
Clone/root-shell work is not eligible for optimization.

Scorer optimization design: `_effective_jokers_for_pass` currently retains
every ordinary active Joker even for played-card, retrigger, and held-card
passes where its key cannot act. Give those prepared passes an explicit effect
set while retaining their narrower copyable set: played-individual is the
existing copyable keys plus ordinary non-copyable Bloodstone; the other three
effect sets equal their existing copyable keys. Preserve source slot order and
the current Blueprint/Brainstorm resolution exactly. Within each played-card
slot, call additive card effects only for their exact keys and x-mult effects
only for Photograph/Ancient/Triboulet/Bloodstone; apply additions before
multiplication and skip only literal `+0` and `*1`. Do not touch main-pass
edition/Baseball semantics or broad Fraction arithmetic. Add regressions for
irrelevant filtering, allowed copies, non-copyable Bloodstone, Joker ordering,
and exact supported scores. Retain only if seed 2439 reproduces every non-timing
field and improves single-worker anchor/runtime throughput by at least 5%
without higher peak RSS; otherwise revert the slice.

Scorer optimization result: commit `d380920` passed the full 1,118-test suite
and matched commit `da9cd9d` on all 111,994 legal plays from 521 organic
selecting-hand observations. On an isolated single-worker replay of development
seed 2439, both versions executed the same 72,071 rollout steps; normalized
result fields were exact, and all five terminal-teacher records were exact
after sorting their nondeterministic output order and replacing the opaque run
group. Wall time fell from 456.24 to 344.04 seconds (24.59%), search throughput
rose from 158.97 to 210.95 steps/second (32.70%), and maximum RSS fell from
228,933,632 to 228,835,328 bytes. The 186-root terminal Arcana anchor fell from
133.62 to 97.70 seconds. Retain the change. The next performance slice must be
chosen from a fresh profile of the retained code; do not optimize the already
small clone path or reduce search coverage.

Boss-filter optimization design: the retained profile still spends most time
inside continuation choice. `_boss_eligible_plays` currently classifies every
candidate play for every known boss, then uses the hand family only for The Eye
(`repeat_hand_restriction`) and The Mouth (`single_hand_family`). Preserve play
order and the existing minimum-card filter, including The Psychic's five-card
rule, but return immediately afterward for every boss without either family
restriction. Keep the existing classification and deterministic Mouth family
tie-break unchanged for Eye/Mouth. Add a call-boundary regression proving an
ordinary boss does not classify, a Psychic regression proving its size filter
still applies without classification, and retain the existing Eye/Mouth
semantic tests. Retain only with exact matched search behavior and measurable
same-seed throughput improvement; otherwise revert it as noise.

Boss-filter optimization result: commit `e0d3bb9` passes 1,120 tests. Against
the retained scorer-only build on the same isolated seed-2439 replay, all
normalized result fields and all five sorted terminal-teacher records are
exact. The workload remains 72,071 rollout steps. Wall time fell from 344.04
to 318.35 seconds (7.47%), throughput rose from 210.95 to 228.10 steps/second
(8.13%), and maximum RSS fell from 228,835,328 to 222,986,240 bytes. Retain the
change. Together, the two exact slices reduce the original 456.24-second
baseline to 318.35 seconds (30.23%) without changing a root, action, endpoint,
label, or outcome.

Strength replan: throughput is no longer the immediate score ceiling. Across
the descriptive frozen v9/v10 trajectories, 340 of 365 losses (93.2%) end on
Pair or Two Pair; 192 of 243 losses with a full Joker row have no xMult, while
352 losses have empty consumables and terminal cash is commonly substantial.
In 64 qualifying late shops with at least $20, a full non-scaling row, and a
legal reroll, the policy left 47 times and rerolled twice. These artifacts are
diagnostic only where their promotion protocols failed, but the repeated shape
justifies one narrow development experiment. Preserve the existing
`needs_upgrade`, legality, and reserve gates; allow exactly the already-budgeted
step-three upgrade reroll (`shop_steps < max_shop_actions - 2`) so two actions
remain for sale and purchase. Do not alter Joker values, search roots, samples,
horizon, shop cap, or economy floor. Compare paired on 20 fresh disjoint
development seeds. Require all runs complete; zero rejected/unavailable roots;
at least eight qualifying interventions across five runs; no more than six
shop actions; no regression in wins or Ante-6 survival; nonnegative paired ante
delta; positive paired log-best-hand delta; and more xMult/scaling acquisitions
in affected candidate runs. Insufficient coverage or any survival regression
kills the slice.

Late-shop screen preregistration: reserve unused development seeds 2441--2460,
nonce `late-shop-engine-v1`, Red Deck/White Stake, six samples, one-Ante
horizon, 200 rollout steps, `z=1`, strategic continuation/options, Ante cap 20,
1,200 decisions, six workers, and recorded search decisions. The retained
control is commit `6a986bf`; freeze its report before committing or running the
candidate. Reports live under `runs/experiments/late-shop-engine-v1/`. Count a
direct intervention only where the candidate continuation baseline is
`RerollShop` at the expanded step-three boundary on a state shared with the
control; downstream trajectory changes are consequences, not additional
qualifying interventions. The predeclared strength and coverage kill rules
above remain unchanged.

Late-shop screen result: reject commit `d251484` despite promising aggregate
movement. Both panels completed 20/20 with zero rejected/unavailable roots.
Mean antes moved 4.35 to 4.45, Ante-6 survivors 7 to 8, and mean log-best-hand
3.9798 to 3.9956. Seed 2441 improved +3 antes and acquired Baseball/Throwback;
seed 2456 regressed -1 ante but remained an Ante-6 survivor. Fourteen otherwise
action/final-state-identical seed trajectories changed deterministic rollout
step counts, establishing at least one direct expanded-boundary continuation
intervention in each and clearing the 8-in-5 coverage lower bound. However,
seed 2441 executed seven non-leave shop actions at Ante 5 before `LeaveShop`.
This violates the six-action acceptance cap: root search can override the
continuation's budget-forced `LeaveShop`. Restore the retained `< 3` reroll
window. Do not reinterpret the positive mean or tune the gate. Diagnose and
enforce the declared shop-action budget at the root-action domain before any
new late-shop experiment.

## Active development loop

The two disjoint 30-seed screens are enough to retain one-ante strategic
search as a provisional baseline. Do not spend the tuning or gate panels
merely to confirm it yet. Improve capability on preregistered development
seeds starting at 901, then run the full tuning and replacement gate panels
only when a
combined candidate materially improves win rate or Endless progression.

The White-stake exact-DAG probe on development seeds 201-210 was killed: all
10 paired trajectories were identical, and all 99 admitted attempts failed
the two-decision horizon before evaluating a root. White Small and Big Blinds
end before that solver becomes eligible. Preserve the Gold solver and its
tests, but do not deploy or widen it for White.

The exhaustive boss-root probe on development seeds 201-210 was also killed:
mean antes fell from 3.9 to 3.8, one seed regressed, none improved, and 45 boss
searches consumed 509,923 rollout steps in 38.8 minutes. Selecting among up to
441 roots with six samples admitted a tiny noisy advantage on the regressing
seed.

The independent two-stage boss allocator passed its tactical-only development
screen, but failed the required interaction check. Strategic-only search on
seeds 206-210 scored `[6, 8, 4, 6, 3]`; the first completed combined run,
seed 206, fell from six antes to three. Stop the panel, delete the boss-search
candidate, and keep the proven strategic path unchanged. A tactical-only gain
does not count when composition destroys strategic value.

Current increment: improve strategic-search throughput before testing another
capability vector. Preserve the 6-sample, 1-ante, `z=1` decision rule and its
public-information boundary. Profile the exact-Fraction continuation scorer,
replace only proven redundant work with behavior-identical caching or integer
arithmetic, and verify action/trajectory identity on reused development seeds.
Do not use tuning or gate seeds yet.

The first full-run profile rules out a broad arithmetic rewrite: exact scoring
dominates, while Fraction construction is only a minority of scorer cost. A
one-table tactical rescore slice preserved seed 210 exactly but was neutral in
wall time (56.6 versus 56.2 seconds), so delete it rather than retain
complexity. Keep the independently necessary custom-hand-stat cache-key fix.

Next slice: remove two engine-side copies that the profile proves redundant in
rollout mode. Reuse Jackdaw's already-established `current_public` when
encoding the next action, and let lightweight observation normalization own
the freshly serialized bridge dictionary instead of deep-copying it. Keep the
normal/authority path copy-isolated. Prove lightweight and normal public
observations plus action RPCs remain identical before benchmarking the same
seed and budget. Do not cache whole policy decisions or anything across public
history.

Retain the engine slice together with prepared per-observation scoring context.
On the matched seed-210 one-sample replay, the stable result is exactly equal:
Ante 3, 6,682 steps, 45 searches, eight overrides, identical terminal state and
action aggregates. The final-code replay cut runtime from 56.2 to 47.1 seconds
and raised rollout throughput from 125.6 to 151.3 steps/s (+20.5%). Normal observation
normalization remains copy-isolated, and all score operations remain exact.

Current capability experiment: spend the recovered throughput on eight final
samples per strategic root, still at one ante and `z=1`, on reused development
seeds 206-210. Compare directly with the current six-sample report on the same
seeds. Retain eight samples only if it preserves the existing win and improves
paired progression without regression; otherwise keep six samples and move to
a learned or analytic leaf value rather than buying more particles.

Eight samples fail the kill rule. Seed 208 stayed at four antes, but seed 206
fell from six antes at six samples to three antes at eight samples. Stop the
other three workers and keep the six-sample artifact. The next strength lever
is a calibrated public leaf value or a better continuation, not more rollout
particles.

Leaf design sketch: do not reuse the existing capacity estimate, whose current
development reports cover only about one quarter of strategic rows and whose
recorded predictive gate lost to ante alone. First shadow-calibrate one bounded
public feature at organic boss clears: achieved public chips relative to the
next visible boss requirement. Map the log ratio monotonically into `(0, 1)`
and scale it below `1 / (4 * samples)`, so no leaf difference can outweigh one
sample's extra round. The feature may apply only to a validated public
boss-clear transition; malformed or unavailable context is neutral for every
sibling in that shared sample.

Before implementation, collect the feature and next-ante-clear label on reused
development control runs. Require broad availability and predictive lift over
ante alone. Kill it without policy code if the next boss is not yet public at
the cutoff, if overkill is not monotone with the next clear, or if it mainly
rewards consumable burn. A learned residual leaf remains the next path after a
failed analytic shadow, with train/holdout splits by complete originating run.

The analytic leaf fails that shadow gate. On complete control runs for reused
development seeds 201--250, all 167 boss clears exposed a positive next-ante
boss requirement, but log clear-score margin had AUC 0.524 for clearing the
following ante versus 0.698 for ante alone. Conditional AUC fell below 0.5 at
Antes 4, 5, and 7, and outcome rate was non-monotone across margin quartiles.
Do not implement or tune this feature.

Do not repeat the existing White exact-DAG probe: its reused development report
already shows 99 of 99 admitted attempts stopped at the certified two-decision
horizon and all ten trajectories matched control. The next capability path is
a learned residual leaf for the retained determinized search, not the deleted
single-intervention action-value probe and not the existing distilled absolute
value head. First add shadow-only collection at a fixed public decision cutoff:
store the cutoff `PublicObservation`, public progress and remaining horizon,
then label it by continuing the same sampled branch to the existing one-ante
endpoint. Never store seed, raw state, RNG, or clone identity. Split by complete
originating run and require selector agreement, zero false overrides on full-
rollout ties, and no positive full-rollout regret before any learned value can
affect play.

The first 8-run collector smoke is schema-valid and all 678 rows are eligible,
but its ordinal schedule put all 22 sibling groups in Antes 1--2. A phase/ante
mean residual reduced held-out MSE from 1.071 to 0.304, yet caused one false
override on a full-rollout tie. Treat this as collection calibration, not leaf
evidence. Replace ordinal scheduling with public Ante 1/3/5 triggers, retain the
unchanged one-step cutoff and full-horizon labels, and calibrate a minimum
paired margin from held-out model error before judging selector agreement.

The corrected 12-run set contains 1,098/1,098 eligible rows in 27 atomic sibling
groups at Ante 1, 3, and 5. A frozen 2,048-hash, 32-unit public MLP improves
held-out residual MSE slightly over the phase/ante baseline and, after a
calibration-group maximum root-delta error margin, creates no false override.
It misses one teacher override in the five-decision Ante-5 slice, for +0.052
mean held-out teacher regret, so it cannot enter policy. Because the miss is in
the explicitly underrepresented stratum while predictive loss improved, allow
one final data-scale test with the architecture, split rule, cutoff, margin
rule, and optimizer frozen on reused seeds 201--250. Any positive held-out
teacher regret kills this residual lane; zero false overrides and non-positive
regret justify one behavior screen.

The final residual test kills the lane. All 50 runs and 4,374 public rows
completed with atomic eligibility. With groups 0--34 for training, 35--41 for
calibration, and 42--49 untouched, the frozen model's holdout MSE was 0.557
versus 0.502 for phase/ante. The calibration maximum root-delta error required
a 1.438 override margin; even then the model missed two of 21 holdout teacher
choices and incurred +0.028 mean teacher regret. Delete the residual collector
and do not run a policy screen.

Next continuation experiment: collect sparse teacher decisions from the
retained six-sample search on reused development seeds only. Each record holds
the root `PublicObservation`, complete typed public history, legal non-reorder
roots, their full-rollout mean utilities, the continuation baseline, and the
search selection. It contains no seed, raw state, RNG, or private clone. Fit
only the existing five `StrategyTuning` integers, maximizing teacher utility
of the continuation-selected root rather than raw agreement. Split by complete
originating run before optimization. Require positive held-out utility versus
the default tuning and no missing candidate action before running the tuned
continuation in games; otherwise kill parameter distillation.

Keep this first fit one-shot and cheap: generate a fixed, digestible set of 64
monotone reserve/threshold vectors from an experiment RNG independent of game
state, include the default vector, and score every vector in shadow while each
scheduled teacher search still has its public history in memory. Use runs
201--235 for selection and 236--250 only for the verdict. The played trajectory
always follows the default continuation plus teacher-selected scheduled roots;
shadow candidates never affect data collection.

The one-shot parameter fit also fails. Across 50 complete development runs and
110 scheduled teacher decisions, the vector selected on runs 201--235 gained
only +0.0164 mean rollout utility over default and then lost -0.0135 on the
untouched runs 236--250. It chose reserves 6/6/6, sell threshold 54, and
replacement margin 2; all actions mapped to searched roots, so the failure is
generalization rather than missing coverage. Delete the harness and do not run
the vector in games. The five current integers cannot express enough of the
search teacher. The next continuation increment needs contextual public
state/action features trained directly on paired root utilities, with a model
class and data volume chosen before another held-out split.

Separately, the open continuation exception has a concrete diagnosis. Replaying
seed 40's saved public search prefix to its first rejected decision reproduces
three identical states: The Hook has forced the last two held cards into a
fully exhausted 52-card discard/play pool, leaving an empty public hand, zero
cards to draw, and one nominal hand. No legal play or discard exists. This is a
Jackdaw missing terminal transition, not a heuristic choice with a safe legal
fallback. Preserve failed-rollout scoring until the empty-deck transition is
checked against real Balatro; do not sell or reorder Jokers to mask it.

Acceptance before retaining the increment:

- focused scorer and search tests preserve exact ordering and fail-closed
  rollout behavior;
- the full suite and information-firewall tests pass;
- a paired development replay produces identical actions and outcomes to the
  retained search artifact;
- measured rollout throughput improves materially without changing the search
  budget, roots, samples, or selector.

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
- **Budget.** The retained provisional vector uses 6 samples, a 1-ante
  horizon, a 200-step cap, and `override_z=1`. Longer horizons wait for a leaf
  value because the measured 2-ante vector was slower and worse.
  Record roots, samples, steps, and seconds per decision in every
  report. Raise the budget only with a recorded measurement.
- **Evaluator.** New `scripts/evaluate_determinized_search.py` emitting
  the same report schema as `evaluate_candidate_baselines.py` so
  `compare_candidate_reports.py` works unchanged. `--workers N` shards
  seeds across processes, one Jackdaw per worker.
- **Order of evidence.** Continue capability work on development seeds. Run
  the full tuning panel only for a materially stronger combined candidate.
  The gate panel is used once for the vector that will be tagged.

Gate: paired antes cleared on the untouched replacement gate 701-900 beats `control-v0` with the
bootstrap lower bound above zero. Tag `control-v1`. Kill: if search with
ten times the starting budget does not beat control, the rollout value
or the continuation is wrong. Inspect the twenty largest per-seed losses
before touching search knobs.

## Stage C: Tactical layer

Bosses kill 64% of runs. In-blind play is where boss counters are won.

- **Boss roots.** Evaluate all legal public actions at the first visible
  decision of each boss blind with determinized Jackdaw rollouts. Measure the
  effect alone and combined with Stage B on development seeds before tuning.
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

- **Targets.** Every eligible strategic search decision is stored with its
  public observation, legal action/intent roots, paired scalar rollout targets,
  chosen root, opaque complete-run group, and teacher-config digest under
  `runs/search_data/`. Incomplete runs and any decision with a failed root are
  discarded atomically.
- **Relational first.** Train the intent-conditioned relational policy/value
  model on whole-run splits using the active increment above. The old CMA-ES
  script and retired hashed recurrent distillation path are not eligible: the
  former is broken and both previously failed contextual generalization.
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
  --seed-provenance tuning \
  --ante-cap 20 --report-json runs/evidence/<name>-tuning-seeds1-200.json

# determinized search
uv run python scripts/evaluate_determinized_search.py \
  --seed-start 1 --seeds 200 --deck RED --stake WHITE --ante-cap 20 \
  --seed-provenance tuning \
  --samples 6 --horizon-antes 1 --override-z 1 --workers 6 \
  --report-json runs/evidence/<name>-tuning-seeds1-200.json

# paired comparison
uv run python scripts/compare_candidate_reports.py \
  runs/evidence/<control>-gate-seeds701-900.json \
  runs/evidence/<candidate>-gate-seeds701-900.json
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
