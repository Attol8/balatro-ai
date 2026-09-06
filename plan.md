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
