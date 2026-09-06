# Complete-run baseline

## Goal

Run reproducible Red Deck / White Stake games against real Balatro, preserving
enough evidence to diagnose decisions and measure subsequent policy improvements.
This milestone establishes a baseline, not a claim of strong or superhuman play.

## Design

- Keep the existing simulator and client. Add a live policy and an evaluation runner.
- The policy consumes the public API snapshot and returns a `Decision`: a canonical
  `GameAction`, an explanation, optional approximate score, and model limitations.
- Handle all playable phases with conservative deterministic heuristics. Never use
  the run seed, hidden cards, checkpoint restores, or future outcomes to choose moves.
- Retain full public snapshots in append-only JSONL trajectories, including before/after
  states, RPC actions, explanations, errors, and terminal outcomes. Do not retry an
  ambiguous mutating RPC automatically.
- Separate genuine losses, wins, execution errors, and decision-limit truncations.
  Report win rate, score distribution, ante reached, and loss context by seed split.
- Offer an offline replay command that recomputes policy choices from recorded
  observations without changing the game. This is decision replay, not exact engine
  restoration; checkpoint-based counterfactual evaluation remains future work.
- Batch execution requires a menu state by default. An explicit CLI reset flag
  permits replacing an existing run. Output directories cannot overwrite prior runs.

## Implementation

1. Verify the installed API schema and add the deterministic baseline policy.
2. Implement bounded episode execution, streaming trajectories, batch summaries,
   fixed seed selection, and offline replay.
3. Add meaningful policy and runner regression tests, including rejected actions,
   transport errors, early victory/endless behavior, and truncated episodes.
4. Document commands and limitations. Run tests and a live multi-seed smoke batch;
   inspect its trajectories and fix integration failures.

## Acceptance

- One documented command runs a fixed-seed batch through the actual game.
- Every attempted decision is durable even if the RPC fails.
- Run failures cannot masquerade as game losses or disappear from aggregate results.
- A logged run can be replayed offline to compare deterministic decisions.
- Existing tests and new targeted tests pass; live results are reported honestly.

## Next experiments

Use observed losses to prioritize tactical discard lookahead, validated scoring,
and build-aware purchasing. Evaluate an existing complete simulator before expanding
the local simulator into every rule family.

## Revised direction: pursue actual playing strength

The user authorized continued autonomous work toward a winning bot and explicitly
allows replacing legacy designs. Repository-wide history inspection found that
this worktree starts at the initial scaffold, while local revision
`1c19cccce240222204b1edd0dc8b071875248842` contains later public scoring and strategic
policy work. Historic high simulator win rates did not establish real-game win
rates. The newer public scorer and legal-action model are useful assets.

- Preserve the measured baseline as a comparison policy.
- Import the narrowly required public scorer, typed observations/actions, and
  strategic heuristic into a separate `solver` package from that frozen revision.
  Rewrite only import namespaces initially; record provenance and reuse its tests.
- Adapt those public values to the live runner, including typed whitelisting and
  public history. Seeds, hidden identities, and private order stay outside decisions.
- Compare the stronger existing heuristic on development seeds. Then improve the
  failures with sampled public draw search and scoring-aware shop alternatives.
- Keep real Balatro authoritative. Candidate simulations inform choices and speed
  experiments but their wins are never counted as live wins.
- Reserve new held-out seeds until a policy is frozen. Report operational failures
  independently and do not silently discard failed seed attempts.

First live baseline: three complete losses, reaching antes 2/4/5. The broader batch
completed ten losses before the game process disconnected on seed D0000010; the
failure trace was retained. Runtime restart/diagnosis precedes further live runs.

## Current architecture and experiment contract

```text
Real Balatro → settled public snapshot → typed public state
                                          ├─ exact/estimated hand scorer
                                          ├─ sampled discard search
                                          └─ sampled shop upgrade comparisons
                                      → legal action → real Balatro
Each boundary → append-only evidence → offline replay + batch results
```

The initial target is Red Deck / White Stake, with a fixed all-unlocked profile.
Survival through Ante 8 is the primary objective; peak hand score is secondary.
Policy inputs exclude run seeds, hidden card identities and ordered draw piles.
Draw hypotheses come from unordered public deck counts, not engine checkpoints.
The API adapter alone sees raw engine state and emits the whitelisted policy schema.

Keep numerical execution separate from longer-horizon strategy. Exhaustively score
legal visible hands; sample unknown draws with common random numbers; compare shop
upgrades against identical sample hands. These are bounded approximations, not full
run value estimates. A language model may later help propose build strategies, but
it should not replace arithmetic or certify its own decisions. Revisit full-blind
search and a learned run-value function after trustworthy real-run data exists.

Use one local engine worker initially. Poll for stable public state between actions,
never retry an ambiguous mutation, and stop a batch on execution errors. Before
scaling workers, isolate profile/save paths and ports and verify deterministic runs.
Policy fingerprints and profile metadata belong in every experiment manifest.

### Evidence so far

- Imported strategic policy: 0/20 completed all-unlocked development runs won,
  maximum Ante 7. Many losses retained cash that could have bought strength.
- Numerical search reaches Ante 8 and much higher hand scores, but no confirmed win
  yet. The first batch exposed a premature native victory flag on a losing final
  boss; victories now require a confirmed post-Ante-8 boundary.
- The next diagnostic batch completed nine losses and one intentionally truncated
  run. It exposed asynchronous boss updates causing an unnecessary second joker
  sale. This batch is not a clean policy comparison.
- Stable-state execution is covered by regression tests; the full suite passes
  595 tests. A fresh 20-seed control batch uses the fixed boundary.

### Next decisions

1. Completed frozen search control on development seeds D0000000–D0000019:
   1 win / 19 losses, no errors or truncations; peak-hand median 20,083.5,
   maximum 175,500. The 95% Wilson win-rate interval is approximately 0.9–23.6%.
   This is not reliable performance.
2. Completed the isolated planet-purchase comparison with the same seeds/profile:
   1/20 wins, no errors/truncations, identical winning seed. D0000013 lost at
   Ante 6 instead of 7; no evidence of improvement. Do not promote this variant.
3. Address the largest evidenced remaining failure with one isolated change.
4. Freeze a materially stronger policy before opening held-out H seeds. Report
   confidence intervals, errors, truncations and score distributions with wins.

The stable control has now confirmed a win on development seed D0000001:
Ante 9 / ROUND_EVAL, final boss score 131,820 and peak hand score 165,600.
All 204 recorded decisions replay identically. The fixed execution boundary
preserved Smiley Face after the required Verdant Leaf sale. Control provenance:
revision `4f6bc968f370c7581ba80d4af9d906a3545a56d7`, clean at launch,
Python source SHA-256 `29c40390b9a7b2214d09b42a8a6396e246d1b58d4e13562a7310a7fa41315021`.
Full local evidence is in `runs/search-stable-001/`.

Isolated, default-off follow-ups also cover Green Joker discard updates,
Needle/Flint shop projections, and adjacent hand/joker order improvements. A
bounded history-based hidden-joker belief model is being developed for Amber
Acorn; it must not infer the actual hidden permutation. Shop purchase placement
is under review because appending Blueprint undervalues its available copies.

Now evaluate `search-v2` on the same development suite.
It combines the independently tested Green, boss, ordering, remembered-inventory,
and executable Blueprint-placement changes. This is a package comparison, not
individual causal attribution; isolated switches remain available for regressions.
The scorer's missing deterministic copier targets are also being corrected from
installed source. Record that physics revision explicitly rather than pretending
it is the old control. Planet purchasing remains separate following its negative
development comparison.

The combined run is frozen at clean revision
`a619afc` in `runs/search-v2-001/`. Full suite: 666 passing tests. The isolated
planet evidence is retained in `runs/search-planets-001/`; it is not included
in the combined policy.

V2 completed 1/20 wins, no execution failures: D0000005 won, while the previous
winning D0000001 lost. All 178 decisions in the new win replay exactly. Broad
discretionary-purchase priority caused early divergences: Mail-In Rebate displaced
a pack for a roughly 10% modeled scoring gain, and Bloodstone displaced an early
pack for roughly 15%. These are observed divergences, not isolated proof of cause.

`search-v3` now isolates narrower priority: before packs/vouchers/non-Joker buys,
only Blueprint gets the special placement-aware comparison. Ordinary shop upgrade
comparisons remain unchanged. V3 preserves all 204 actions of the original winning
trace in offline replay. Its live 20-seed batch is running from clean revision
`bb2c77a` in `runs/search-v3-001/`; 673 tests pass.

The Amber belief model was checked against all five actual control-seed D5 plays:
every score matches a consistent permutation. Conditioning on public scores would
narrow 120 hypotheses to six; on the final hand it lowers modeled clear chance
from 70% to 40% without changing the chosen cards. Such a posterior is not yet
implemented; do not treat the unconditioned belief as a calibrated probability.

V3 completed 2/20 wins (D0000001 and D0000005), with no errors/truncations.
The remaining performance is inadequate. Next evaluate `search-v4`:

- Enable six static-debuff bosses after 72/72 recorded public refill transitions
  matched exact card multisets, including 63 drawn debuffed cards.
- Correct the terminal objective: with one hand left, deterministic modeled loss
  and legal modeled discards remaining, do not quit because samples found no outs.
- Preserve baseline early plays with Green Joker: one-next-hand sampling does not
  value its accumulated growth. D6 previously discarded instead of playing 192;
  repeated-hand growth would project 192+240+288 against the remaining 644.
  This is an explicit conservative fallback, not a full-blind rollout model.

The Green guard and static support are opt-in to V4; the terminal correction is
a scorer-objective repair in the new source revision. V3's running artifact was
unchanged. Full suite: 687 tests pass.

V4 is running from clean revision `14a3696` in `runs/search-v4-001/`.
Prepare the separate V5 reroll ablation: V3's final-shop audit found 11/18 losses
already below mean-based pace, with multiple runs retaining $26–$60. An optional
survival budget raises the cap from two to five only when below forecast pace;
the existing reserve plus six dollars for a possible purchase remains protected.
Safe shops retain the old cap. This tests spending under an existing forecast,
not a claim that that forecast is calibrated. Full suite: 693 passing tests.

The milestone remains incomplete until live performance supports reliable wins.

V4 completed 3/20 wins (D1, D5, D6), 17 losses, no errors/truncations.
The new D6 win replays all 178 decisions exactly. V5 is now running from clean
revision `09f943c` in `runs/search-v5-001/`; do not pool its partial results.

### Public-only full-blind planning experiment

The next architectural experiment is shadow evaluation of complete next-blind
outcomes, rather than another hand-capacity heuristic. Reuse the frozen newer
checkout's public-root constructor and pinned Jackdaw compatibility wrapper,
not its private-clone determinization path or large strategy-search framework.
The public-root probe reconstructed all eight D1 first-shop states successfully;
a two-particle, seven-action first-shop rollout rejected no simulations but tied
all actions. Neither result demonstrates real-game strength.

- Input: strict public observation, contiguous public action history, independent
  public-derived particle nonce. Never real seed, hidden order, save, or raw frame.
- Initial scope: shadow-only visible shop purchases versus leaving, followed by a
  fixed public continuation through the next ordinary Small/Big Blind. Stop at
  the blind outcome, before new-shop generation; reject unsupported roots.
- Keep completed wins/losses separate from simulator rejection and step limits.
  Use common particles for paired action comparisons. Do not promote on model
  scores alone; actual paired development runs remain the acceptance evidence.
- Import only the constructor, compatibility wrapper, backend contracts and
  pinned data with provenance. Preserve Python 3.11 live operation; simulation is
  an optional Python 3.12 dependency. A missing candidate cannot break live play.
- Verify reconstruction and wrapper tests, then shadow real recorded shops.
  Bosses, destructive consumables, and generated shops remain outside this first
  evaluation slice. Widen only with explicit transition evidence.

This trades additional candidate maintenance and computation for the ability to
value draw/discard sequences and growth across a blind. Root equality alone is
not transition parity; retained authoritative differential evidence supports only
its exercised cases. In particular, forced-card destruction under Cerulean still
lacks authoritative validation in the frozen source.

The bounded shadow implementation now exists as `solver.blind_rollout` and
`solver.shadow_blind`. The first control D1 shop (decision 4) completed all
three-action/eight-particle comparisons: modeled clear rates 7/8, 8/8, 7/8.
This intentionally buys once then leaves; it does not value continued shopping,
future economy, bosses, or long-run scoring. No live policy was changed.

The V4 failure audit identifies a separate concrete next target: ten of seventeen
losses used unsupported-boss shop projections. D3's club-dependent build was
forecast near 30,956 per hand before The Club but actually totaled 24,512 across
four hands against 40,000. Verdant Leaf forecasts also omit the mandatory sale,
and Crimson Heart forecasts omit the disabled Joker. Static boss-conditioned
valuation is the smallest follow-up; do not attribute these deficits solely to
insufficient sampling or spending. V5 remains a separate running ablation.

Verification for the imported candidate and shadow slice: 800 tests pass under
Python 3.12 with pinned Jackdaw; the dependency-free host passes 731 with 69
candidate-only skips. Namespace-only source diffs were independently inspected.
A second late D3 shop (decision 142, V4 trace) reconstructed and completed eight
LeaveShop branches, six clearing the modeled Big Blind. Evidence lives under
`runs/shadow-next-blind-001/`; neither probe changes live behavior.

### Static boss-conditioned shop valuation

Add an isolated `project_static_bosses` switch: Club/Goad/Head/Window and Plant
transform the sampled public cards before scoring every candidate build. Recompute
from candidate-owned Jokers so Smeared and Pareidolia purchases/sales change the
projection. Wild cards match every suit, Stone cards have no suit; Plant treats
Stone as face only with active Pareidolia. Preserve input state and common sampled
cards, updating both synthetic hand and remaining-deck multisets consistently.
Exclude Pillar (history), random-disabling bosses, and unmodeled activation/sale
interactions. Keep V4/V5 controls unchanged. V6 starts from V4, not the unfinished
V5 spending ablation, so it isolates this forecast correction.

V5 completed 3/20 wins, the same D1/D5/D6 wins as V4, with no execution failures.
Do not promote the larger reroll budget on that result. V6's static forecast
changes the diagnosed D3 final-shop first-hand estimate from 30,956 to 5,803,
and reserve from $23 to $2, against the observed 24,512 total over four hands.

Static projection was checked against 267 visible cards immediately after actual
blind selections in the V4 suite: Club 93, Goad 40, Head 56, Window 48, Plant 30;
all debuff flags matched. This validates the exercised activation slice, not full
future-blind survival. The permanent `full_deck` contract deliberately excludes
transient debuffs; only sampled hands and synthetic Remaining counts carry them.
809 tests pass with the candidate installed (740 plus 69 skips without it).

### Final-hand stochastic survival objective

V6 is running frozen at `8407cdd`. Meanwhile V5's two losses with unused discards
both contain Misprint: D0's last physical play has 10/24 modeled clearing outcomes,
and D8's has 18/24. The current estimated-clear early return ignores that risk.
Add a default-off final-hand Misprint probability comparison. Admit exactly one
active Misprint, no copying or other modeled random scoring, and retain existing
discard-transition guards. Enumerate its 24 public outcomes for each physical
play; optimize one play across all outcomes, not a different play for each roll.
Compare that probability with common sampled refills, accounting for Banner and
other supported discard effects. Preserve all controls; this is not a blanket
force-discard rule or proof either recorded loss was avoidable.

The default-off probability layer is implemented and retains the existing guards.
It compares mean clearing probability across sampled refills, with an explicit
heuristic 1/24 improvement margin (not a statistical confidence bound). D0's
current chance is 41.7% versus 23.4% after its best sampled discard; D8 is 75%
versus 78.1%, below that margin. An offline scan of all eight V5 final-hand states
with active Misprint changed zero actions relative to the same-input control.
Therefore do not schedule a full live promotion batch on this evidence. Keep the
model available for targeted probability diagnostics; redirect the next playing-
strength experiment toward strategic build development, not a forced-discard fix.
Verification: 827 tests pass with the optional candidate installed; the host
passes 758 with 69 optional skips. No registered live policy enables this layer.
At 64 refill samples the two final-loss checks still retain playing: D0's best
refill estimate is 22.2% versus 41.7% now; D8 is 76.7% versus 75% now.

### Next strategic experiment: publicly known current-ante boss readiness

The V6 D3 trace is action-identical to V4 (165 decisions). Corrected forecasts
detect the deficit, but two rerolls are still exhausted before leaving with $51.
D2 exposes a more general horizon problem: at ante8 shop190, Violet's 300,000
requirement is already public and the bot has $68. Shops191–192 optimize for the
50,000 Small Blind; shops197–202 optimize for the 75,000 Big Blind. Only shop209
begins treating 300,000 as the target. Final actual total is 118,130.

Next test current-ante boss readiness from the first shop where that boss is
publicly visible. It should affect candidate build valuation and a bounded
ante-level preparation budget, while protecting immediate-blind survival. This
is not knowledge of an unrevealed future boss and not indiscriminate rerolling.
Do not assume a winning alternative exists in the diagnosed traces; measure a
frozen new policy on the development panel before held-out evaluation.

V7 design: keep immediate and visible-current-ante boss projections separate.
Rank purchases by the weaker normalized pace, rejecting candidates that turn an
apparently adequate immediate build inadequate or further weaken an already
inadequate one. Use the public boss score unchanged. Admit Needle/Flint, five
static bosses, Wall/Violet/Water; Water gets zero projected discards. Exclude
activation interactions and active perishables from future-boss estimates.
These stress-test today's build, freezing intervening growth/decay and upgrades.
They are not future survival probabilities.

When boss readiness is below modeled pace, allow up to four rerolls per shop and
six total per ante, counting every actual reroll from complete contiguous public
history. Pack excursions do not reset the visit. Preserve a purchase cash buffer
and enforce caps on inherited baseline rerolls too. Without complete history,
retain the original budget. V7 builds on V6; Misprint probability remains off.

V6 completed 3/20 wins (D1/D5/D6), no execution failures. D5's peak hand increased
to 157,320 from V4's 97,020; the win-rate result is unchanged. V7's offline D2
shop190 check now reports immediate pace 1.685 versus boss pace 0.281, protects
$2 instead of the old safe-build reserve, and searches before the Small Blind.
This is a changed decision at a recorded state, not a counterfactual win.
The full candidate-enabled suite passes 838 tests, including independent tests
of the new objective, Water counters, budget/history bookkeeping, immediate-
capacity guard, inherited reroll cash protection, and unchanged flag-off behavior.

V7 is running from clean revision `c3af3f2` in `runs/search-v7-001/`.
Public reconstruction coverage was audited across all first shops per ante in
V6: 118/123 roots succeed, median 85ms and p95 250ms; the five failures are
historical skips in D2/D5/D6 late antes. No other constructor failures occurred.

### Multi-blind public rollout outcome experiment

The frozen older search completed a D3 late-shop probe with 10 actions, eight
particles and 995 accepted transitions in 8.5s. It selected Emperor over reroll,
but its reported objective is partial scoring progress, not demonstrated boss
survival. Do not use that result as win evidence or import the whole framework.

Extend the existing shadow evaluator with an opt-in current-ante horizon. Allow
all legal non-reorder shop roots and ordinary public strategic continuation,
including later shops/packs, until the ante boss clears or the run loses. Bound
steps and particles; unfinished/error branches must stay separate from losses.
Use fresh public-root construction and fresh continuation per action/particle.
Report per-action modeled boss-clear rates only when every branch completed;
retain detailed statuses and score/target data. The original one-blind shadow
slice and every registered live policy remain unchanged. This broader candidate
scope is experimental and has only partial authoritative transition coverage.

V7 scope bug found during its running batch: the new inherited-reroll cash floor
also applied when boss readiness was unavailable and even when the reroll cost
was zero. D1d38 blocked an unrelated $5 reroll; D2d31 blocked a free Chaos reroll
that the control used before acquiring Spare Trousers. Re-plan: confine the new
cash restriction to charged preparation rerolls for a modeled boss deficit, and
allow free preparation rerolls within the same actual-action caps. Preserve the
first V7 artifact as confounded evidence; evaluate the correction separately.

The first V7 batch completed 1/20 wins, no execution failures. Its source remains
frozen at `c3af3f2`; correcting a specific scope bug does not explain every loss.
The corrected implementation preserves unrelated baseline rerolls and free
preparation rerolls while retaining charged preparation cash protection and
actual-action caps. All 858 tests pass (789 plus 69 optional skips on the host).

The broader offline evaluator completed all 80 D3 late-shop branches: buying
Emperor cleared the boss in one of eight particles; every other action cleared
zero. This is a weak candidate signal, not a reliable intervention. Detailed
outcomes are retained in `runs/shadow-ante-001/d3-154.json`; no live policy uses
these rollout results yet.

## Low-token teacher pilot (user-approved)

Keep the real game stopped. Build compact public-only shop packets with explicit
legal action IDs; use one fresh low-cost agent call for three cases, without
conversation history, run seeds, future observations or known outcomes. Select
the first ante3 SHOP in each of the first three V6 development traces by a fixed
rule. Record the actual policy action separately, hidden from the teacher.

Validate returned case/action IDs and bounded explanations. Store proposals as
unverified, not correct labels. Compare teacher, alternative and recorded actions
using identical public-derived candidate particles through the current ante.
Any simulator rejection/censoring invalidates a comparison. This tiny diagnostic
pilot does not establish stronger play; no training or live promotion follows
without a larger independent outcome test.

### Pilot result

Completed one fresh `gpt-5.6-luna` low-effort teacher call, three public packets
(14,113 bytes combined), with no paid API client or real-game restart. All three
responses passed case/action validation and remain unverified proposals. Raw
packets, proposals, coordinator provenance and candidate reports are retained in
`runs/teacher-pilot-001/` (local ignored artifacts).

Fixed cases: V6 D0 decision37, D1 decision33, D2 decision53. Eight identical
public-derived particles per legal non-reorder action; all 272 branches completed
without rejection/censoring. Current-ante clear counts:

| Case | Teacher | Recorded choice | Teacher alternative |
|---|---|---|---|
| D0 | Venus use: 7/8 | Voucher: 6/8 | Death store: 7/8 |
| D1 | Juggler: 8/8 | Same Juggler: 8/8 | Earth use: 8/8 |
| D2 | Seed Money: 8/8 | Leave: 8/8 | Spectral pack: 8/8 |

D0 has one teacher-only clear and no recorded-only clears; a different pack
action achieved 8/8. Every D1 action achieved 8/8. This pilot establishes only
that the cheap-teacher plumbing works, not teacher superiority. A short horizon
cannot meaningfully value longer-term economy in these mostly easy positions.
The continuation was the frozen PublicStrategicPolicy, not the best live search
policy; candidate transitions have only partial authoritative coverage. Do not
turn these explanations into training truth or pool the correlated branches as
independent games. Next experiment should use a predeclared harder development
slice and a longer strategic outcome horizon before any distillation decision.

Verification: 866 tests passed with the pinned optional candidate installed.
No live policy changed, no training launched, and the real-game server stayed
stopped. Best completed real-game baseline remains 3/20, not superhuman.

## Two-ante outcome experiment

Extend the existing public-only evaluator with an explicit one/two-ante budget,
capped at the ante8 win condition. Preserve default behavior and rejection /
censoring semantics. Add an opt-in frozen V6 search continuation so comparisons
can use our strongest measured strategy rather than only the weaker baseline.
No live action selection changes in this step. First test the first ante6 shop
in V6 D0..D2 where available, using small paired particle budgets; record missing
cases instead of selecting by favorable outcomes. Bound rollouts at 512 steps.
Compare existing strategic continuation first to establish runtime and coverage;
then test search continuation on the same public case. Longer-term simulation
is still candidate evidence, not proof of real wins. Revisit runtime and model
coverage before promoting this into live shop selection.

### Two-ante results

The fixed selection yielded D1 decision100 and D2 decision137; D0 never reached
ante6 and was recorded as missing, not replaced. Local artifacts are in
`runs/two-ante-001/`. All 140 action/particle branches completed without rejection
or censoring. No API calls or real-game restart occurred.

- Strategic continuation, four particles: D1 only selling Ramen cleared (1/4);
  D2 pack0, selling Scholar, and selling Jolly cleared 1/4 each. Other actions 0/4.
- V6 continuation, D1 two particles: every action 0/2, matching the first two
  strategic particles. This is not a four-particle comparison.
- V6 continuation, D2 four particles: selling Scholar cleared 3/4, pack0 2/4,
  recorded pack1 1/4. Selling Jolly cleared 0/4, reversing its apparent promise
  under the weaker continuation. Strong continuation therefore matters to action
  ranking. These are sparse candidate outcomes, not real win-rate estimates.

No live promotion. The concrete next intervention to independently validate is
D2 selling Scholar versus recorded pack1, with fresh synthetic particles and
then authoritative public-only live evaluation if the advantage survives.
Do not distil a general rule to sell Scholar from this state-specific result.
All-action strong rollouts are too expensive for indiscriminate live use; retain
a bounded candidate shortlist before increasing samples. CLI now records the
continuation and its source hash, snapshots hashes before evaluation, and defaults
two-ante runs to 512 steps. Initial experiment artifacts predate the added
continuation-hash metadata; their continuation options were identical.

Verification: 875 tests passed with optional candidate installed. The live policy
is unchanged; the best measured real baseline remains 3/20.

## Independent intervention check

Freeze D2 decision137 comparison to selling Scholar versus recorded pack1.
Use a new public randomness nonce, 16 paired particles, V6 continuation through
two antes. Explicit validated root subsets avoid irrelevant action computation.
Retain all rejects/censors and report paired wins/losses rather than selecting
the best sampled action. This is development evidence, not held-out real wins.
Only a replicated advantage warrants an authoritative intervention test; an
inconclusive result is not permission to hard-code a seed-specific sale rule.

Fresh particles completed: sale9/16 versus purchase5/16, seven sale-only and three
purchase-only successes. Direction replicated, but evidence is small. Proceed to
one explicitly labelled real-game development intervention, matching only the
exact public observation digest. The policy never sees the seed. It otherwise
uses unchanged V6; report whether the intervention actually fired. This diagnostic
is not registered as a general live policy and cannot establish generalization.

### Authoritative intervention outcome: rejected

`runs/intervention-live-001/`: intervention matched and first action difference
was exactly decision137. The real run lost to The Eye at ante6, scoring37,860 /
40,000, with peak hand16,896. The recorded V6 control reached ante8. Selling
Scholar was followed by buying the same Celestial pack, then an extra reroll and
purchase; subsequent policy trajectory changed. This was not an isolated removal
effect. Reject the intervention for promotion or distillation. One realized loss
does not establish a simulator bug (the candidate also predicted losses), but it
does refute treating the small modeled advantage as a demonstrated improvement.

Added an explicitly diagnostic public-digest, one-shot intervention harness;
it does not expose seeds to policy decisions or register a new general policy.
The harness refuses non-menu games and non-all-unlocked profiles. Existing V6
is untouched. Tests:883 passed. The owned game and launcher were stopped after
the completed run; no training or model API calls occurred.

Next work should evaluate multi-action build changes and check candidate
transition fidelity on these newly divergent real states, not distil isolated
action labels from a handful of rollout successes. Real wins remain the metric.

## Build-first strategic replacement (user requested big bet)

Stop the isolated-intervention loop. Study the full Joker catalogue and expert
build principles, then replace strategic ownership across shops, packs,
consumables and hand play as one coherent policy. Design and evidence are in
`docs/build-first-policy.md`. Reuse public mechanics, legal actions and numerical
scoring; do not construct another simulator/framework. Runtime stays local with
no model API. Basic correctness tests remain, but evaluate the integrated policy
on a complete fixed development panel instead of one experiment per small rule.
This is the next implementation, not a measured improvement yet.

Implementation contract: shared BuildIntent and conditional Joker/planet value;
new BuildFirstPolicy owns shop replacement plans, pack and consumable selection,
and safe growth-preserving plays. Numerical shop capacity supplies a survival
floor, not the whole objective. Revalidate pending purchases and preserve V6 as
control. First version retains conservative fallback for unsupported effects and
does not claim complete advanced-engine support. Freeze before the full20-run
development batch; evaluate the integrated policy without per-Joker ablations.

Build-first prototype frozen at dcba69c completed the full 20-game development panel:
1/20 wins (D5), 19 losses, no errors/truncations. V6 remains 3/20; D1 and D6 winning
seeds regressed, and no new winning seeds appeared. Maximum hand 78,240.
All 903 correctness tests passed before freezing. The integrated prototype is not
promoted. Full evidence: runs/build-first-001/summary.json and public trajectories.
Mechanism-specific valuation remains missing: Throwback stayed X1 in D0/D3;
Red Card stayed +0 in D4/D11 despite the category-based purchase value. Future
growth valuation must require an executable growth plan with resource costs,
not a generic scaling-role bonus. See docs/build-first-policy.md for scope gaps.
