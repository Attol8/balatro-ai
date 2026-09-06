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
2. Now separately evaluate opt-in planet purchases with the same seeds and engine
   profile; preserve the control policy. Inspect trajectories, not just averages.
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

After the planet ablation, evaluate `search-v2` on the same development suite.
It combines the independently tested Green, boss, ordering, remembered-inventory,
and executable Blueprint-placement changes. This is a package comparison, not
individual causal attribution; isolated switches remain available for regressions.
The scorer's missing deterministic copier targets are also being corrected from
installed source. Record that physics revision explicitly rather than pretending
it is the old control. Planet purchasing remains separate pending its results.

The milestone remains incomplete until live performance supports reliable wins.
