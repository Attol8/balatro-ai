# Superhuman Balatro AI Rebuild Plan

## Objective

Build an agent that exceeds a declared strong-human benchmark on clean Balatro runs while using only information available through the normal game interface. Fast-environment results, source-rule inventories, and isolated parity checks are supporting diagnostics, never success criteria.

## Execution Status (2026-08-08)

The failed independent simulator, planner, imitation pipeline, rule-presence gate, and their scripts/tests have been removed. The first foundation is implemented: typed public observations and actions, an adversarial information firewall, a strict BalatroBot observed-state backend, stable canonical state, provenance-rich tamper-evident traces, and no-waiver differential replay. The replacement test suite passes. Across 68 retained real-trace files, the canonicalizer accepts all 20,542 snapshots; the firewall accepts all 20,532 settled decisions and rejects only 10 transient `HAND_PLAYED`/`DRAW_TO_HAND` states.

A fresh public-action Red/White seed-1 smoke run completed in real Balatro and its five decisions reproduced exactly in a second real run. Jackdaw is pinned at `dbedc66255fe594cce7b7cccc188c8a11649d9ec`; its upstream suite passes 1,561 tests. Its raw bridge initially had 638 representational differences from BalatroBot. A narrow adapter now derives BalatroBot's representation from Jackdaw's own state. The clean schema-v4 campaign reproduced 765/765 transitions across seeds 9-25; all 17 runs lost. Policy and environment processes are now isolated, the real-game snapshot spike is complete, and public-history recurrent training exists. Jackdaw remains an untrusted candidate and every trained checkpoint still has zero wins. Schema v5 supersedes v4 after strategic exploration exposed previously unrepresented permanent card bonuses. Fresh schema-v5 seed-1 coverage and strategic traces reproduce 25/25 and 23/23 transitions exactly; both are terminal losses and only narrow authority evidence.

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
- Before accepting a sweep, make terminal detection exact at the decision-budget boundary, require every run to terminate normally, record terminal-reason counts, label candidate-only diagnostics explicitly, and verify that the imported Jackdaw tree is the clean pinned revision.
- Commit `4f0d42e` hardened that evidence path. On candidate Red/White seeds 1-100, greedy completed 100/100 with 0 wins and average ante 1.05; deterministic-random completed 100/100 with 0 wins and average ante 1.0. The unchanged seed-1 policies then ran through real Balatro and reproduced in Jackdaw for 18/18 and 11/11 transitions respectively, both terminal losses at ante 1. These controls establish a trustworthy floor and no more.

### Active Increment: Fair Public-Belief Search

- Introduce a backend-free belief surface derived only from `PublicObservation` and public action/observation history. It must not import Jackdaw, BalatroBot, snapshots, seeds, RNG objects, raw states, or private IDs.
- Start with exact without-replacement draw probabilities over the public remaining-deck multiset. This is a chance model, not a clone of the live game and not yet full-run search.
- Require public hidden twins to produce identical beliefs, action rankings, and policy distributions. Malformed counts and unsupported hidden mechanics fail closed.
- Use the public chance model to build a bounded tactical search baseline before introducing learned values or latent particles for future shops and RNG streams.
- Commits `d1866af`, `0a4f323`, and `b8f1759` added exact public hypergeometric beliefs, a bounded one-ply single-card-discard expectimax policy, and a semantics-preserving scoring optimization. The frozen optimized policy completed candidate Red/White seeds 1-100 with 0 wins, average ante 1.23, average round 2.90, and only 2.80 decisions/s. Its unchanged seed-1 run reproduced through real Balatro for 27/27 transitions and lost at ante 1.
- This closes the one-ply baseline as a negative result: it is fair and reproducible, but neither strong nor fast enough for expert iteration. Do not deepen the same Python enumerator.
- Naive rejection sampling over candidate seeds is also rejected as the rollout architecture: matching a public hand makes acceptance exponentially small. A usable particle worker must sample latent states from the correct public-history conditional distribution, including VM-order and RNG latents, without using the live seed or snapshot.

### Active Increment: Policy Process Isolation

- Move the policy callback behind a strict JSON-lines child-process boundary before adding any model or training loop. The parent sends only canonical `PublicObservation`, public legal actions, and bounded public history.
- Reject unknown fields, raw authority state, seed/RNG/snapshot tokens, oversized messages, malformed actions, stale observations, timeouts, crashes, and extra stdout. Revalidate returned actions against the parent observation before execution.
- Keep environment kernels and private candidate state entirely in the parent/evaluator process. The child process must not import Jackdaw or BalatroBot.
- Once isolation passes adversarial hidden-twin tests, choose between public-history recurrent RL and a conditional latent-state worker based on measured feasibility; do not build seed-rejection particles.
- Commits `abebc01`, `1067577`, and `b75831c` moved policy contracts out of the BalatroBot package, added a strict public-state codec and bounded stateful JSON-lines protocol, and made all non-coverage evaluation policies run in the child by default. The parent kills the child on timeout, crash, malformed/oversized output, stale request or digest, extra stdout, out-of-set action, or independently illegal action.
- The process boundary passes 139 tests with 10 candidate-only skips. It deliberately scrubs the child environment down to the repository and basic runtime variables and asserts that neither Jackdaw nor BalatroBot was imported. This is accidental-leak isolation, not a hostile-code filesystem/network sandbox.
- Clean isolated candidate evidence at `b75831c`: greedy 0/100 at 94.50 decisions/s, deterministic-random 0/100 at 90.45 decisions/s, and tactical 0/20 with average ante 1.30, average round 3.05, and 6.95 decisions/s. The isolated tactical seed-1 policy then reproduced through real Balatro for 27/27 transitions and lost at ante 1.
- This closes the process-isolation gate for the current baselines. The next architecture decision must be measured: prototype a public-history recurrent training loop and a conditional latent-state sampler behind the same boundary, then keep only the approach that can produce useful decisions without private-state leakage or rejection-sampling collapse.

### Active Increment: Public Training Environment

- Run the pinned Python 3.12 Jackdaw candidate in a separate environment worker. The Python 3.11 training/orchestration side receives only strict `PublicObservation` frames and sends typed public actions; it never imports Jackdaw or receives raw state, `_gs`, RNG, snapshots, RPC details, or private IDs.
- Reuse the strict public codec, canonical action codec, bounded JSON-lines framing, deadlines, request/digest checks, and process cleanup already proven for policy isolation. Factor shared transport code instead of copying another subprocess implementation.
- The minimum environment protocol is reset, step, and close. Reset configuration belongs to the environment driver; seed values and seed manifests never enter model observations, action features, recurrent state, or rewards.
- Use `sparse_terminal_v1`: +1 for a public terminal win, -1 for a public terminal loss, and 0 otherwise. Any future shaping reward must be declared, public-state-derived, and evaluated separately.
- Benchmark Red/White seeds 1-20 and 1-100 with a frozen public baseline through this reversed boundary. Require the same outcomes as direct candidate evaluation and report steps/s, episodes/s, failures, worker provenance, and config/seed-manifest digests.
- Only after the worker passes should an optional PyTorch recurrent policy/value module be added in Python 3.11: compositional public card/item/set encoders, a GRU public-history state, dynamic legal-action scoring, and masked on-policy training. Behavior cloning of current baselines is a plumbing smoke test only; strength training uses public-history RL or later fair belief targets, never clairvoyant labels.
- Commit `5ddbd88` added the isolated Python 3.12 candidate worker, strict reset/step/close protocol, sparse terminal reward, explicit step-limit truncation, process-group cleanup, and benchmark-grade provenance. A clean Red/White greedy panel matched the frozen direct-candidate result per seed for both 20/20 and 100/100 complete episodes. The 100-seed worker sustained 178.53 decisions/s and reproduced the same zero wins, average ante 1.05, and average round 2.22. This proves boundary and outcome equivalence, not policy strength.
- Commit `f8b4d9a` added the optional Python 3.11 recurrent model: deterministic public feature hashing, a single GRU cell, dynamic legal-action scoring, a value head, strict checkpoint loading, and an initial no-reorder enumerative proposal. Its first frozen 20-seed evaluation failed closed when a 14-card hand produced 6,944 play/discard combinations; raising the bound again was rejected. Model format v2 now chooses play/discard at the top level and selects one to five increasing hand slots autoregressively. The proposal is bounded independently of hand size, sampled action log-probabilities replay exactly, and the 20-seed diagnostic completes without truncation. The model remains untrained in strength terms and has no wins.

### Active Increment: Public On-Policy Training

- Train only through `PublicEnvironmentProcess`; the trainer receives public observations, public rewards, and typed public actions. Environment seeds stay in the driver and never enter model features, recurrent state, advantages, or rewards.
- Use multiple independent candidate workers and batch model inference across them. Environment steps may run concurrently, but one worker remains one mutable episode and every reset/step response keeps the existing strict process contract.
- Start with clipped PPO over bounded `factorized_tactical_no_reorder_v2` decisions, fixed-length contiguous recurrent rollouts, GAE, normalized advantages, gradient clipping, and exact recurrent resets. Truncations bootstrap from their final public observation but never carry advantage into the next episode. Do not backpropagate through private environment state or reconstruct actions from simulator IDs.
- Keep `sparse_terminal_v1` as the promotion objective. The first `public_progress_v1` diagnostic was invalid as useful shaping because public `round_no` advances when a blind starts, so nearly every loss received the same bonus. That schema is deleted. A separately named `public_blind_clear_v1` training reward may add only a bounded bonus on the public `SELECTING_HAND -> ROUND_EVAL` transition; reports separate environment reward from shaped training reward, and final evaluation uses sparse terminal outcomes only.
- Save only model configuration, tensor weights, and a digest. Reports record repository/candidate revisions, reward schema, action-proposal schema, optimizer configuration, seed-manifest digest, episode outcomes, and all truncations/errors. Do not add replay databases, imitation datasets, dashboards, or distributed infrastructure for this smoke increment.
- The trainer is accepted only when a short deterministic smoke run produces finite losses, changes model weights, writes a loadable checkpoint, closes every worker, and the frozen checkpoint executes through the public environment without illegal actions. A strength claim requires a separately frozen evaluation with real wins and later clean Balatro reproduction.
- Commit `99e1e3c` replaced the failed enumerative tactical head with the factorized model. A clean 20,480-step PPO continuation then completed 1,985 training episodes at 122.23 steps/s with zero wins; 1,984 died in round 1, one reached round 2, and frozen held-out evaluation stayed at 0/100 with average round 1.0. This is a kill result for raw random-initialized PPO, not a reason to tune it further.
- The next bounded curriculum step behavior-clones the existing frozen greedy public policy only to initialize legal tactical play and passive control. It then trains with `public_blind_clear_v1` on disjoint environment seeds. Imitation accuracy is a plumbing/curriculum metric, never strength evidence; if the frozen model cannot at least recover the greedy baseline's held-out survival, stop model training and move directly to fair search targets.
- The clean 100-episode bootstrap reached 64.45% sampled exact action accuracy, but the frozen model averaged only round 1.16 on held-out seeds 1-100 versus the greedy controller's 2.22. It therefore fails the curriculum gate; do not tune imitation further.
- The replacement is a hybrid search-first control surface. A frozen public tactical controller owns `SELECTING_HAND`; fixed public flow selects blinds and cashes out. The learned recurrent policy owns only `SHOP` and `PACK`, with all ownership recorded in the artifact schema. PPO policy loss applies only to learned strategic decisions, while the public value loss and GAE span the complete trajectory. This preserves a known tactical floor, reaches strategic states without private information, and avoids teaching a neural network to poorly approximate code that is already exact.
- The first 8-worker hybrid run found an environment-schema defect rather than a training failure: buying Hiker created a visible `perma_bonus`, and canonicalization rejected that valid field once the card entered the discard pile. Schema v5 now records the bonus, the public firewall exposes it without deck-order leakage, the greedy scorer and model encode it, and the exact seed-40096 eight-action regression passes in pinned Jackdaw. A repeated 2,560-step hybrid diagnostic completed 146 episodes at 90.45 steps/s with zero truncations, zero worker failures, and zero wins. This validates the repair and training path only; strategic strength is still absent.

### Active Increment: Public Strategic Baseline

- Establish a fair strategic floor before generating search or model targets. Keep the existing bounded immediate-score tactical controller, but add public-only shop and pack decisions using semantic item keys, visible prices and slot counts, declared economy floors, safe held-Planet use, and bounded rerolls.
- Reuse the existing `PublicObservation`, legal-action iterator, bounded history, and isolated policy process. Do not import Jackdaw/BalatroBot, inspect ability trees, parse locale-dependent tooltip prose, branch the live private state, or receive seed/RNG/snapshot data.
- Support only actions whose public legality is already complete: Joker/Planet purchases, vouchers, boosters, rerolls, safe Planet use, and legal Joker/Planet/playing-card pack picks. Targeted Tarot/Spectral use, replacement sales, and reorder search remain fail-closed.
- Treat the pinned candidate's private-state smart heuristic only as a diagnostic ceiling: it wins 1/100 Red/White seeds and averages 7.67 rounds, but it is not fair evidence and none of its private inputs may be ported.
- Freeze and evaluate the public port on candidate Red/White seeds 1-100. Keep it only if it materially beats the 2.22-round greedy floor without truncations or policy errors, then reproduce the unchanged policy through a fresh real Balatro schema-v5 trace.
- Commit `7a8cc74` passed that retention gate. Its clean isolated candidate panel completed 100/100 episodes without truncation or policy error at 100.84 decisions/s, averaging 6.95 rounds versus greedy's 2.22; it still won 0/100. The unchanged seed-1 policy then reproduced 23/23 schema-v5 transitions in real Balatro and lost at ante 1.
- A 10-card hand exposed noncanonical discard ordering and an out-of-proposal tactical choice; selections are now increasing and strategic tactics optimize strictly within the 512 transported public actions. Commit `9840961` orders the unchanged complete legal set largest-first so the bound includes strategically useful five-card actions. Its clean candidate panel completes 100/100 at 101.50 decisions/s, averages 7.29 rounds and 2.50 ante, and still wins 0/100. The unchanged seed-1 policy reproduces 23/23 real Balatro transitions exactly and loses at ante 1.

### Active Increment: Strategic Value Learning

- Reuse the existing public recurrent model, isolated environment worker, evaluator, and PPO loop. Do not add a second dataset format, replay service, model family, or private simulator callback.
- Bootstrap only `SHOP` and `PACK` decisions from the frozen `PublicStrategicPolicy`; fixed public tactical control continues to own blind flow and hand play because the earlier model failed to recover that deterministic floor.
- Resume the strategic checkpoint with on-policy `public_blind_clear_v1` returns. The learned policy owns only shop and pack actions; episode seeds remain environment-driver inputs and never become observation, history, feature, reward, or recurrent-state fields.
- Training metrics, imitation accuracy, and candidate loss reductions are diagnostics. Keep the learner only if its frozen evaluation on disjoint Red/White seeds beats the 7.29-round strategic floor or records a complete win; validate any retained policy unchanged through real Balatro lockstep.
- Commit `ccca3e4` implements that bounded path. A clean 200-episode strategic bootstrap reaches 86.96% sampled shop/pack imitation accuracy, but its frozen seeds 1-100 evaluation averages only 6.84 rounds with 0 wins. A 20,480-step public-return PPO continuation recovers to 7.03 rounds with 0 wins, still below the 7.29 teacher. This closes imitation and PPO tuning as failed strength paths.

### Active Increment: Public Joker-Aware Tactics

- Fix the public tactical surrogate before training another strategic model. Only cards that actually score contribute card chips, enhancements, and editions; selected kickers no longer create imaginary score.
- Apply deterministic joker effects sequentially in visible joker order using public semantic keys and public state. Start with fixed hand-family effects, visible money/discard/deck-count effects, card-rank/suit effects, and editions. Do not parse locale-dependent tooltip prose or invent hidden scaling counters.
- For scaling jokers whose accumulated value is not yet structured, model only the action-dependent public delta: Runner gains on Straights, Spare Trousers on Two Pair/Full House, and Square Joker on four-card hands. Their unknown current constant must not be guessed.
- Keep the patch only if the frozen Red/White seeds 1-100 panel materially beats 7.29 rounds or produces a complete win, then replay the unchanged policy through real Balatro lockstep.
- Commit `cf324f6` passes the retention threshold: its clean frozen panel completes 100/100 episodes at 96.98 decisions/s, average round rises from 7.29 to 7.86 and average ante from 2.50 to 2.67. Seed 63 reaches ante 7 instead of ante 6. The unchanged seed-1 policy reproduces 23/23 real Balatro transitions exactly and loses at ante 1. This is the new honest floor, not a solve: it still wins 0/100.

### Active Increment: Replacement-Aware Joker Slots

- Fix the smallest directly observed strategic dead end: a full joker area currently makes every better shop Joker disappear from the legal buy set, so the policy never upgrades. On candidate seed 63 it kept Business Card, Blue Joker, Banner, and Runner while passing on The Order at ante 6, then died at ante 7.
- Starting at ante 6, inspect only the visible shop offers and owned public Joker descriptors. If the best affordable visible Joker exceeds the weakest sellable owned Joker by a fixed material margin, sell that owned Joker; on the next public decision the existing buy path purchases the still-visible offer. Permit at most one such replacement per run. Earlier and repeated replacement churn is excluded because the first bounded panel regressed after selling Banner in ante 2, and the seed-63 probe later tried to replace Banner with the build-incompatible Idol after correctly acquiring The Order.
- Count the sale against the existing bounded shop-action budget, require purchase affordability after the visible sell proceeds, and never sell an Eternal Joker. If no material replacement is visible, preserve the current behavior.
- Do not enable selling during an open pack, synthesize a combined sell-and-buy action, reserve a slot speculatively, parse tooltip prose, or add private candidate state. Pack-time selling is still outside the current verified public action contract.
- Keep the patch only if hidden-twin and explicit replacement tests pass and a frozen Red/White seeds 1-100 panel beats the 7.86-round floor or records a complete win. Any retained policy then runs unchanged through a clean real Balatro differential trace that reaches the replacement action when feasible.
- The dirty development panel passes that gate: 100/100 runs complete, average round rises from 7.86 to 7.89, and seed 63 clears ante 8 after replacing Business Card with The Order. This is candidate-only evidence from an unfrozen revision; commit, clean rerun, and exact real Balatro replay remain mandatory.

### Active Increment: Win-Boundary Integrity

- Real public-action evidence fixes the exact contract: beating the ante-8 boss transitions directly from the final play to `GAME_OVER` with `won=true` and `ante=8`; there is no round-eval cash-out action. Jackdaw instead marks `won`, advances to ante 9, and waits in `ROUND_EVAL`, so the unchanged evaluator drives a genuine clear into Endless Mode and can overwrite the flag with a later loss.
- Correct the pinned-candidate compatibility layer, not the authority runner or differential gate. When the win ante boss is beaten, suppress Jackdaw's next-ante setup and expose the engine state as `GAME_OVER` immediately. Exact authority semantics remain mandatory.
- Add focused compatibility regressions for no ante advance and terminal phase conversion, then rerun the unchanged 100-seed panel. Historical candidate reports that continued after `won=true` are outcome-invalid and must not be used as win-rate evidence.
- This repairs candidate outcome accounting only. Any candidate win remains candidate evidence until the exact frozen policy reproduces every public action and canonical state through BalatroBot.
- The corrected dirty panel reports seed 63 as `GAME_OVER`, `won=true`, ante 8, round 24 after 212 decisions. The full development panel records 1/100 candidate wins at 7.89 average rounds. This is the first honest candidate clear in the rebuild, not yet a Balatro solve claim.

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

The public/private contract, no-waiver replay loop, extended-action lane, process isolation, real-kernel snapshot benchmark, and public recurrent-training path are complete. Historical schema-v4 seeds 9-25 reproduced 765/765 transitions; schema v5 supersedes that evidence by adding permanent playing-card bonuses, with two fresh seed-1 policies reproducing 48/48 observed transitions exactly. The fair strategic baseline materially beats the fixed greedy floor but still wins 0/100. The immediate milestone is a public-only strategic value/search teacher that produces real wins; further blind PPO or imitation tuning is explicitly rejected.
