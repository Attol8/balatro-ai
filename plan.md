# Superhuman Balatro AI Rebuild Plan

## Objective

Build an agent that exceeds a declared strong-human benchmark on clean Balatro runs while using only information available through the normal game interface. Fast-environment results, source-rule inventories, and isolated parity checks are supporting diagnostics, never success criteria.

## Execution Status (2026-08-08)

The failed independent simulator, planner, imitation pipeline, rule-presence gate, and their scripts/tests have been removed. The first foundation is implemented: typed public observations and actions, an adversarial information firewall, a strict BalatroBot observed-state backend, stable canonical state, provenance-rich tamper-evident traces, and no-waiver differential replay. The replacement test suite passes. Across 68 retained real-trace files, the canonicalizer accepts all 20,542 snapshots; the firewall accepts all 20,532 settled decisions and rejects only 10 transient `HAND_PLAYED`/`DRAW_TO_HAND` states.

A fresh public-action Red/White seed-1 smoke run completed in real Balatro and its five decisions reproduced exactly in a second real run. Jackdaw is pinned at `dbedc66255fe594cce7b7cccc188c8a11649d9ec`; its upstream suite passes 1,561 tests. Its raw bridge initially had 638 representational differences from BalatroBot. A narrow adapter now derives BalatroBot's representation from Jackdaw's own state. The clean schema-v4 campaign reproduced 765/765 transitions across seeds 9-25; all 17 runs lost. Jackdaw remains an untrusted candidate, and this is not yet a trained agent: OS-process isolation for the policy, broader action and randomized candidate lockstep, and the real-game snapshot extension remain open. No learned model should be built until those gates pass.

### Active Increment: Deterministic Differential Campaign

- Add a deterministic coverage policy driven only by `PublicObservation`, public history, and an explicit policy seed.
- Keep action selection bounded and family-aware; never enumerate the factorial reorder tail or enable actions whose public legality is incomplete.
- Record one exclusive authority trace per game, replay it immediately through pinned Jackdaw, and stop at the first exact mismatch.
- Run repeated fresh authority processes for the same run and deterministic policy before candidate replay. Compare canonical states exactly and report the first authority self-divergence; any process-specific runtime input must then be modeled explicitly and kept private from the policy.
- The benchmark mod set is Lovely, Steamodded, and BalatroBot only. UI/preview mods are disabled because they are not part of the game authority. Health reports the active mod IDs and every evidence script rejects an undeclared or missing mod.
- Begin with a small Red/White development panel. A terminal loss is acceptable coverage evidence but never policy-strength evidence.
- Promote neither the candidate nor policy work until the panel is complete and mismatch-free; every divergence becomes a candidate/adapter regression test.
- Schema-v1 seed-1 and seed-2 traces found and regressed real transport and candidate bugs, but are no longer promotion evidence after the canonical schema changed. The authority now requires a cash-out button owned by the current `G.round_eval`, defensively enforces that precondition in `cash_out`, and waits for the Tarot/Spectral hand. Candidate regressions cover round-target timing, split ante setup, Standard-card deck insertion, Spectral hand dealing, voucher activation, and pack/shop persistence.
- Seed 3 showed that numbered vanilla Booster suffixes are artwork variants chosen from presentation-sensitive global Lua RNG. Canonical schema v2 preserves the raw suffix but compares and exposes the known vanilla variants by their semantic Booster key. The adapter's attempted global-RNG emulation has been deleted.
- The next seed-3 divergence exposed an undeclared environment input: the local career profile had Mr. Bones unlocked and Seeing Double locked while Jackdaw assumes a fully unlocked profile. Benchmark authority launches now use a transient `all_unlocked` mode equivalent to Balatro's normal profile action, report it through health, and seal it in the trace manifest. Scripts fail closed on a missing or different profile mode; career-profile runs are diagnostics only. Under schema v2, clean seed 1 (skip), seed 2 (pick), and seed 3 (mixed) traces passed 91/91 transitions. Schema v3 supersedes that evidence by recording another private runtime input, so those traces are now historical regressions and must be regenerated before promotion.
- Seed 5 exposed two authority defects before candidate work could continue. Blind-skip tag packs return to `BLIND_SELECT`, not always `SHOP`, and To Do List's visible live target is `card.ability.to_do_poker_hand`, not its prototype `extra.poker_hand`.
- Repeated probes proved the remaining To Do variation is vanilla LuaJIT behavior, not extra RNG consumption: the source builds the chance pool with `pairs(G.GAME.hands)`, fresh VMs produced different visible-hand iteration orders, and both selected index 3 from the named RNG stream. Canonical schema v3 records that order as private runtime state. Candidate replay receives it before reset and uses it for the same To Do List/Orbital Tag pools; the policy firewall discards it. A fresh minimal-mod seed-5 trace then replayed exactly for 19/19 transitions. This is parity evidence from a dirty development revision, not promotion evidence or a win.
- The clean schema-v3 panel then reached seeds 1-8: 250/250 transitions reproduced exactly through public actions. Those are losing engineering traces, not policy evidence, and schema v4 now supersedes them.
- Seed 9 proved the full 12-entry LuaJIT hand-table order is semantic, not only its nine currently visible entries. Vanilla's boss-advance tie loop never updates its order sentinel, so the last tied maximum in `pairs(G.GAME.hands)` wins. Schema v4 records the full private iteration order, keeps it behind the policy firewall, and normalizes floats to Lua JSON's 14 significant digits. The schema-v4 seed-9 development trace passes 35/35 transitions.
- Seed 10 made the discard pile part of the exact private state. That exposed three source-level candidate defects: The Hook's forced discards must be sorted by hand position before effects and pile insertion; Standard-pack playing cards must be repriced after an edition is assigned; and blind-select UI consumes and stores three Orbital choices every ante before a tag fires. With those rules modeled, the schema-v4 seed-10 development trace passes 61/61 transitions. Fresh clean schema-v4 traces are required after commit before this becomes promotion evidence.
- Commit `b145c9b` produced the first clean schema-v4 evidence: seed 9 passes 35/35 transitions and seed 10 passes 61/61. Seed 11 then exposed Swashbuckler's per-frame `Card:update` state: its displayed mult is the sell-value sum of the other owned jokers even when the Swashbuckler itself is only a shop or pack offer. Updating that persistent ability field from candidate state makes the clean seed-11 authority trace replay 63/63. All three runs lost.
- Commit `d29094e` then produced clean exact traces for seed 11 (63/63), seed 12 (35/35), and seed 13 (43/43). Seed 14 exposed a shared affordability bug: Jackdaw updated `bankrupt_at` when Credit Card was acquired, but card, voucher, pack, and reroll handlers still compared costs to cash alone. Applying the source debt floor at that shared boundary makes seed 14 replay 121/121 through terminal loss at ante 4.
- Commit `9ea19ab` cleanly reproduced seed 14 (121/121), seed 15 (16/16), seed 16 (27/27), and seed 17 (18/18). Seed 18 received Voucher Tag and exposed an obsolete adapter constant that forced the voucher area limit to one even though Jackdaw had correctly created and serialized two offers. Deleting that override makes seed 18 replay 29/29. All runs remain terminal losses.
- Commit `c2d592f` then cleanly reproduced seed 18 (29/29) and seed 19 (27/27). Seed 20 bought its only voucher and exposed the inverse capacity case: an empty voucher list still has a one-card shop area. Candidate shops now persist a base capacity of one, raised by temporary Voucher Tag offers and unchanged by purchases; seed 20 replays 25/25. All runs remain terminal losses.
- Commit `7a054ad` completed the clean schema-v4 Red/White panel through seed 25. Exactly one clean trace per seed 9-25 gives 17 complete terminal losses and 765/765 exact transitions; the deepest runs reached ante 4 (seed 14, 121 transitions) and ante 5 (seed 21, 116 transitions). This is candidate-fidelity evidence only: there are zero wins and no trained model.

### Active Increment: Public Action Coverage

- The clean seed 9-25 corpus covers every decision phase and 11 action families, including both pack outcomes, blind skips, vouchers, and purchases.
- It never exercises rerolls, held-consumable use, selling, or reorder actions. Do not manufacture coverage by destructively selling useful state or enumerating factorial reorder tails.
- Add one explicit extended coverage mode. In that mode, reroll once at the start of a shop when publicly affordable, then follow the existing bounded purchase policy.
- Encode and exercise only held Planet use first. Planets are visible, no-target consumables with a source-defined legal use in `SELECTING_HAND` and `SHOP`; all targeted Tarot/Spectral rules remain fail-closed.
- Extended coverage is complete only when both `reroll_shop` and `use_consumable` occur in addition to the existing mixed-pack contract. Run a separate clean lane so the original seed 9-25 corpus remains immutable.
- Commit `75669b4` added that mode without opening targeted consumables, selling, or reorder actions. A clean seed 26-35 lane then reproduced 230/230 transitions across 10 terminal losses. It exercised 18 rerolls, one held-Planet use, three pack choices, and two pack skips. This closes the narrow extended-action gate; it does not show policy strength.

### Active Increment: Real-Kernel Snapshot Benchmark

- Prove the existing game-native file save/load path before adding a second persistence mechanism. Save one settled parent, explore a bounded suffix chosen only from public observations, restore the parent repeatedly, and replay the exact public actions.
- Require exact branch-local canonical equality at the restored parent and after every replayed action. Report the first mismatch; never reduce this to public-digest equality or tolerate RNG drift.
- Record snapshot bytes, SHA-256, save latency, restore latencies, replay depth, versions, mods, and run configuration. Keep the blob and filesystem path private and ephemeral.
- Do not add snapshot methods to the shared `GameBackend` protocol or advertise snapshot/restore capability yet. The first harness is privileged evaluation infrastructure, not a policy feature.
- Only after the file path passes should BalatroBot store the game's packed `save_run` representation in a private in-memory registry. Snapshot IDs and blobs never enter `PublicObservation`, public history, or the deployed policy process.
- Remove inactive debug/mutation and disabled-mod scoring endpoints from the benchmark authority registration when the authority patch is next revised; they are not part of the clean public-action or snapshot contract.
- Commit `48a1cce` produced a clean file-path baseline on Red/White seed 26: a 7,558-byte save restored in 61.9 ms median and replayed an eight-action suffix exactly five times (40/40 transitions). The suffix crossed draws, scoring, cash-out, shop generation, pack opening, and pack choice. This proves exact observed continuation for that checkpoint, not complete Lua-state capture.
- The in-memory spike reuses the same packed `save_run` representation, unpacks a fresh table on every restore, caps storage at 64 explicit entries, and clears stale entries on menu/start/file-load. The evaluator receives only an opaque ID and byte count. The authority registration drops screenshot, debug mutation, and disabled-DV scoring endpoints instead of carrying them into the benchmark runtime.
- Commit `eddae29` passed the same seed-26 branch through in-memory restore for 40/40 exact transitions: 2.9 ms capture and 56.5 ms median restore. The refactored file path then passed 24/24 at 59.1 ms median, and a fresh extended-policy seed-28 run passed candidate lockstep 22/22. Rebuilding the actual run/UI dominates restore, so the real kernel is an oracle/audit worker rather than the high-volume training kernel. Snapshot/restore capabilities remain unadvertised until broader checkpoints and uncaptured mod/global-state risks are tested.

### Active Increment: Honest Strength Baselines

- Add a bounded deterministic-random public policy and a greedy immediate-score public policy. Both consume only `PublicObservation`, legal public actions, and public history; neither receives a simulator handle or seed.
- Random excludes factorial reorder actions from its bounded sample. Greedy selects blinds, plays the highest visible immediate-score hand, cashes out, leaves shops, and skips packs; it intentionally has no strategic economy so later search has a clear floor.
- Evaluate fixed development seed ranges in pinned Jackdaw for throughput and outcome diagnostics, then run representative policies unchanged through clean BalatroBot differential traces. Fast results alone are not strength evidence.
- Freeze baseline name, code revision, policy seed, deck/stake, and seed range in every report. Report all losses and incomplete runs; never tune on the claimed comparison range.

## Design

Use a two-kernel architecture. Actual Balatro under a pinned BalatroBot/LÖVE build is the authority. A pinned, independently audited Jackdaw fork is the candidate high-throughput training/search kernel. Expose the same typed state/action contract from both and continuously compare organic trajectories. In parallel, prototype in-memory snapshot/restore and batch rollouts inside real Balatro; use the real kernel directly wherever its measured throughput permits.

Keep privileged state behind a process boundary. The deployed policy and online search receive only `PublicObservation` plus public action/observation history. They never receive the run seed, shuffled deck order, future RNG, private object identifiers, or a clone of the live hidden state. Fair search creates belief particles consistent with public history and samples unknown events from the correct conditional distribution.

The system has five layers:

1. Public/private contract: an observation firewall, typed visible action candidates, public history, private canonical state, and adversarial hidden-state-twin tests.
2. Dual environment: real Balatro authority plus a differentially certified fast candidate, both exposing reset, action, settle, observation, terminal outcome, and event trace.
3. Search: belief-state planning over hidden information, exhaustive tactical action generation where affordable, and sampled strategic rollouts for shops, packs, skips, and consumables.
4. Learning: policy and distributional value networks trained by expert iteration from belief-averaged search targets, with item/card/joker instances represented compositionally rather than by one flat linear ranker.
5. Evaluation: frozen agents, evaluator-secret seeds generated after freeze, immutable traces, confidence intervals, and direct comparison with human and program baselines across decks and stakes.

## Acceptance Standard

- No debug mutation endpoints and no injected state.
- Policy input and search contain no seed, hidden deck order, future shop contents, actual RNG state, or hidden-state-dependent legal-action leak.
- Every reported agent is identified by code revision, configuration, model digest, game/mod versions, and seed manifest.
- Every benchmark declares its profile mode. The canonical benchmark uses the normal fully-unlocked card pool; ambient career-profile unlock history is never an implicit input.
- Promotion metrics come only from authoritative-engine or clean live runs of that exact frozen artifact.
- The final superhuman claim requires a predeclared benchmark over all 15 standard decks at Gold stake, evaluator-secret seeds, enough games for simultaneous confidence bounds, and performance exceeding a preregistered elite-human reference under the same rules and information.

## Build Order

### 1. Prove the information boundary and environments

- Implement explicit `PublicObservation`, `PrivateState`, `PublicActionCandidate`, and public-history types before policy work.
- Add public-twins tests: changing only inaccessible hidden state must not change policy input, visible legal candidates, or the action distribution.
- Pin and audit Jackdaw instead of building another independent simulator from scratch.
- Prototype BalatroBot in-memory snapshots and batched real-game rollouts using the game's own save representation; verify snapshot/RNG fidelity before using it for search.
- Build an organic differential corpus from real public-action traces and require exact next-state agreement for the complete canonical semantic state, not a hand-selected projection.
- Make unsupported actions or state fields fail closed. There are no waivers in acceptance traces.

Exit criterion: randomized action-sequence differential tests pass on a broad source-derived state/action coverage matrix, including stochastic branches and persistent card/joker state; the observation firewall passes adversarial leakage tests; throughput is measured under the intended belief-search workload.

### 2. Establish honest baselines

- Random legal agent.
- Greedy immediate-score tactical agent.
- Handcrafted search baseline with no learned value.
- Human-reference benchmark collected under the same observation and seed rules.

Exit criterion: every baseline is reproducible from a frozen artifact and evaluated on separate development and test seed manifests.

### 3. Build search before learning

- Enumerate or beam-search tactical play/discard actions with the authoritative kernel.
- Use root-sampled POMCP, stochastic MCTS, or sampled expectimax for hidden shops, packs, tags, and draws.
- Share determinizations across sibling actions to avoid optimism bias.
- Recondition the particle belief after every public observation; never clone or inspect the actual live hidden state for a deployed decision.
- Search complete run actions, including selling, ordering, targeting, rerolling, skipping, and multi-pick packs.

Exit criterion: search materially beats the handcrafted baseline on held-out authoritative runs and transfers unchanged to clean live execution.

### 4. Add learned policy and value models

- Encode card and joker instances, consumables, vouchers, blinds, tags, and typed action candidates with embeddings, modifiers, counters, order, targets, and set/graph structure. Include Gold-stake mechanics in the schema from the start.
- Train a policy prior from belief-averaged search visit counts and a calibrated distributional survival/win head from authoritative outcomes.
- Use expert iteration/self-generated play; retain hard states from live and authoritative evaluations for regression and targeted replay.
- Calibrate the value model by ante, stake, deck, and build archetype before allowing it to prune search aggressively.

Exit criterion: the learned-search agent beats search alone on a locked held-out suite without increasing live/authoritative disagreement.

### 5. Curriculum and final evaluation

- Red/White is an engineering smoke test, then train across decks and stakes; do not treat White success as strategic promotion evidence.
- Increase each stake's training weight only after its authoritative coverage exists; Gold-stake mechanics remain present in the observation and model schema from the start.
- Lock architecture and hyperparameters before the final Gold-stake benchmark.
- Generate the sealed final seed manifest only after the artifact is frozen, run one attempt per condition, and publish all traces, failures, model metadata, compute limits, and confidence intervals.

Exit criterion: the frozen agent clears the predeclared superhuman benchmark across all decks at Gold stake.

## Kill Criteria

- Stop policy work if authoritative and live outcomes diverge for any agent-relevant transition.
- Stop if changing only private state changes a deployed decision.
- Stop if search receives the live seed, hidden deck order, actual future RNG, or a private clone.
- Stop training if improvements appear only in a surrogate environment.
- Reject a milestone if the evaluated policy changed during the seed sweep.
- Reject parity or coverage metrics based only on identifier presence, shape checks, tolerated mismatches, or waived behavior.
- Replace the environment approach if it cannot clone/step fast enough for useful search without changing game semantics.

## First Milestone

The public/private contract, no-waiver replay loop, and first clean schema-v4 Red/White panel are complete. Seeds 9-25 reproduce 765/765 transitions, including shops, packs, tags, vouchers, stochastic joker state, boss transitions, and ordered discard state. The immediate milestone is a separate extended public-action lane covering rerolls and safe held-Planet use, followed by randomized action/rule coverage and the real-kernel snapshot benchmark. Learned policy work begins only after those environment gates pass.
