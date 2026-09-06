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
