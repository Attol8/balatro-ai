# Superhuman Balatro AI Rebuild Plan

## Objective

Build an agent that exceeds a declared strong-human benchmark on clean Balatro runs while using only information available through the normal game interface. The active promotion target is Red Deck at Gold Stake on the declared single-machine compute budget. All-deck Gold remains the later generalization target, not a prerequisite for the first superhuman result. Fast-environment results, source-rule inventories, and isolated parity checks are supporting diagnostics, never success criteria.

## Active Objective (2026-09-01): Single-Machine Red/Gold Solver

The current policy is a fair one-seed White-stake solver, not a generally winning agent. Do not scale the failed hashed-GRU, behavior-cloning, sparse-PPO, or short-horizon action-value lanes. Keep the authority, information firewall, pinned Jackdaw candidate, and exact replay system; replace the intelligence loop with a solver-first hierarchy that spends compute only on consequential uncertainty.

### Fixed constraints

- The development and final artifact run on the repository host class: one Apple M2 Pro with 32 GB memory. External rollout farms and hidden-state oracles are outside this milestone.
- The policy and search receive only `PublicObservation`, typed public actions, bounded public history, and a policy-owned search nonce. The live seed, private clones, actual RNG state, hidden deck order, and future shops never enter search or training labels.
- Jackdaw executes and validates candidate transitions. It does not define policy observations, public legality, belief state, or the learned action representation.
- Real Balatro under the pinned BalatroBot/LÖVE stack remains authoritative. Candidate wins and snapshot branches never count as wins.
- Promotion uses win probability. Average ante, rounds, prediction loss, search visits, and candidate-only outcomes are diagnostics.

### Architecture

1. **Action-sufficient public contract.** Own phase-specific legality in this repository. Represent every visible input needed for Cerulean Bell, targeted held consumables, targeted Arcana/Spectral pack choices, selling and replacement, multi-pick packs, ordering, and Gold-stake stickers/counters. Compile typed primitives independently to BalatroBot and Jackdaw, and revalidate after every primitive in a multi-step option.
2. **Exact tactical solver.** Enumerate or beam-search play/discard/target/order choices with exact public scoring, mechanical-equivalence reduction, transposition caching, and exact without-replacement draw beliefs. The search ends at the current blind boundary and optimizes survival probability rather than raw expected chips.
3. **Strategic option search.** Search coherent public shop/pack options such as sell-then-buy, bounded rerolls, pack multi-picks, consumable use, and build reordering. Pareto-prune on money, interest, guaranteed scoring floor, scaling, slot flexibility, rental liability, perishable lifetime, and Eternal commitment.
4. **Fair uncertainty.** Draws use the exact public deck multiset. Future offers use source-defined public conditional distributions and policy-owned random tapes keyed by public digest, search nonce, and rollout index. Sibling options share tapes; sequential elimination spends additional samples only on close choices. The initial horizon ends at the next boss.
5. **Learning as compression.** Only after learner-free search beats the frozen heuristic, fit a small structured ranking/distributional-value model from belief-averaged sibling comparisons. Encode explicit card/item entities, runtime counters, order, sticker liabilities, hand-family contributions, and low-rank Joker interactions. Search disagreements and uncertain high-impact roots receive priority; raw PPO and imitation remain closed.

### Build and kill gates

- [ ] Close the public action/schema gaps and require hidden twins to produce identical observations, legal options, random tapes, search statistics, and actions.
- [ ] Produce a Red/Gold mechanism-by-phase-by-action coverage matrix with exact complete authority traces and zero waivers. Keep Jackdaw untrusted outside the certified envelope.
- [ ] Implement a cached tactical scorer/solver and show exact agreement with candidate and authority outcomes over the covered mechanics.
- [ ] Implement learner-free one-shop-to-next-boss option search. On a locked paired Red/Gold candidate panel it must produce action-sensitive sibling returns, strictly more wins than the unchanged strategic heuristic, and a positive paired survival lower bound on a separate replication panel.
- [ ] Reject the search target if shuffled action identities or shuffled targets retain ranking performance. Reject the chance model if held-out public transition frequencies are miscalibrated.
- [ ] Transfer the unchanged promoted search artifact through complete Red/Gold authority traces spanning every action family it uses. Any executor rejection, hidden-twin difference, mismatch, or incomplete run kills promotion.
- [ ] Distill only after search passes. The compact artifact must retain most of the paired search gain on disjoint seeds under the declared candidate-transition and decision limits.
- [ ] Freeze the final artifact before generating evaluator-secret seeds. Compare one attempt per seed against a preregistered qualified strong-human Red/Gold cohort under identical rules; failures count as losses and the confidence interval for the paired win-rate advantage must clear the declared material margin.

### First decisive experiment

Build the action-complete Gold public contract and a learner-free one-shop-to-next-boss search slice. Collect naturally reached Red/Gold shop roots with the frozen heuristic, stratified by ante and sticker mix. Generate legal public option beams, compare siblings on shared independently sampled futures, run the selected option organically, and evaluate against the unchanged heuristic on disjoint paired seeds. Include hidden-twin and shuffled-option negatives and replay representative promoted trajectories in real Balatro. If this slice cannot create fair action-sensitive paired improvement, revise the abstraction before adding a value model or increasing compute.

#### Re-plan after the first reachability diagnostic

The pre-boss-only guard failed as a useful primary intervention surface: 50 complete Red/Gold candidate runs produced zero wins, reached only two eligible search roots, and selected one buy. Keep it as a unit-tested fairness slice, but do not scale particles or train on it. Expand the same shared-public-particle comparison to every organically reached shop whose next blind is already visible. Compare the search choice with the frozen baseline's actual directly representable option, permit one search override per shop, and then return control to the baseline instead of forcing an early exit. Record root reachability, baseline/selected sibling returns, and intervention counts. If this broader slice still cannot create paired survival gains, stop extending shop heuristics and move the exact public tactical solver ahead of strategic learning.

The broader 50-seed paired candidate diagnostic created a real but insufficient signal: 23 runs reached a represented search root, six final recorded choices differed from the baseline, five seeds survived farther, none regressed, and the paired total gained 18 rounds and three antes. Both policies still won zero runs. Treat this as permission to keep the public shared-particle abstraction, not as promotion evidence. The existing uncached one-card discard expectimax was stopped after sustained full-core execution because its repeated score enumeration is unsuitable for the single-machine controller. The next tactical slice must gate search on survival relevance, reuse score/transposition results, and prove gain per evaluated state before it is combined with strategic search.

A bounded per-hand survival heuristic also failed its kill gate and was deleted: on 10 paired Red/Gold seeds it improved two runs, regressed four, lost two total rounds, and won none. The failure is conceptual rather than a threshold issue. Averaging the remaining blind target over hands does not correctly price guaranteed chip progress, hand depletion, or future draw opportunity. The replacement must solve the blind as a finite-horizon public belief process with play and discard transitions sharing cached hand-score results; do not revive per-hand pacing or uncached one-draw expectimax.

The first finite-horizon particle beam is also rejected as evidence, despite advancing two of the first five paired candidate seeds from ante one to ante two. It consumed roughly 117 seconds for those five runs versus roughly one second for the heuristic, and its per-particle beam selected continuation branches using unseen tape tails. That strategy fusion is an oracle evaluation, not an executable public policy. Retain shared public particles and root comparison only. The replacement evaluates each root under one deterministic continuation policy that is a function of the simulated public state and uses a deterministic candidate-count budget. Its initial scorer-supported envelope is deliberately tiny: Red/Gold Small and Big Blinds with visible, unmodified base cards and no Observatory. Refill-to-capacity, public-equivalent hand sorting, integer score flooring, and complete hand-stat rows are part of the transition contract. Eleven stateless Jokers (`Bull`, `Crafty Joker`, `Droll Joker`, `Greedy Joker`, `Gluttonous Joker`, `Joker`, `Lusty Joker`, `Mystic Summit`, `Riff-Raff`, `Scary Face`, and `Wily Joker`) were added only after evaluator-only organic candidate states matched all 436 legal play/discard transitions for their observed single-Joker or interacting builds. Each additional mechanic expands only with the same differential proof.

The corrected fixed-continuation search is efficient enough for the declared machine and shows a small honest candidate signal. On the frozen paired Red/Gold seeds 1–30, all 60 runs completed with no illegal actions or policy timeouts under the same source digest. After the shop simulator was restricted to the same certified scoring envelope and deterministic play/discard continuation, with held consumables failing closed, search improved terminal progress on three seeds, regressed none by terminal ante/round, gained seven total rounds and three total antes, and took roughly 46 seconds versus nine seconds for the heuristic. Both policies still won zero runs. This passes the narrow non-regression/relevance check, not the strategic promotion gate: the mechanism envelope and shop option model remain far too small for a winning policy.

#### Re-plan after the checkpoint audit

The pre-commit audit found that `HiddenHandCard.aura_eligible` revealed whether a face-down card already had an edition even though the normal card-back rendering does not expose that fact. Remove the predicate from the public contract and make Aura fail closed on face-down targets. It also found that public affordability retained Credit Card's debt floor while the Joker was debuffed; condition that rule on an active, nondebuffed Credit Card and add a shared-legality regression. These are checkpoint blockers, not tolerated limitations.

The repository-local editable pinned Jackdaw checkout passes the complete candidate suite, but a fresh `uv --all-extras` installation currently loses Jackdaw's JSON data files. Keep the untracked lockfile outside the checkpoint and do not claim clean-install reproducibility until the upstream packaging boundary is repaired. This does not weaken the public search result, but it remains an evidence-infrastructure gap.

### Active Increment: High-Coverage Exact Joker Envelope

- A read-only scan of the frozen Red/Gold seeds 1–30 found 442 Small/Big-Blind decisions. Search admitted 147; 253 were blocked solely by an unsupported owned Joker. Sly Joker, Faceless Joker, Drunkard, Credit Card, and Banner are the smallest low-complexity set with the largest measured reach: together they account for 68 blocked blind decisions across nine seeds and 11 otherwise-compatible shop roots.
- Centralize the certified tactical and pre-blind shop Joker sets. Keep Riff-Raff tactical-only because its blind-setup creation is outside the shop rollout transition. Unknown, debuffed, stateful, stochastic, retrigger, copy, and order-sensitive mechanics continue to fail closed.
- Reuse the existing exact-in-envelope score rules for Sly Joker and Banner. Credit Card and an already-owned Drunkard are scoring-neutral during a blind; when the shop rollout buys Drunkard, add exactly one discard to the next blind unless the boss sets discards to zero.
- Add public money to the simulated blind state. Faceless Joker awards $5 per active copy after a discard containing at least three visible face cards; subsequent observations and score calls receive the updated money so Bull interactions remain exact. The current base-card/no-debuff capability gate avoids Stone, debuff, and face-classification ambiguity.
- Do not expose raw Joker ability trees or add runtime fields for immutable vanilla constants. Source review confirms this slice is determined by existing public keys, cards, counters, money, and Joker order.
- Admit each key only after organically reached Red/Gold states match every legal play/discard transition in pinned Jackdaw, including score, money, resources, hand refill/order, and hand statistics. Add a purchase-to-next-blind Drunkard regression. Synthetic tests remain regressions, not differential evidence.
- Rerun the frozen paired Red/Gold panel with zero illegal actions/timeouts. The wiring gate requires the expected capability reach increase; retention additionally requires actual newly enabled interventions and no terminal-progress regressions. Candidate improvement is not an authoritative Balatro win, and real Joker-bearing traces remain required before promotion.

#### Replication result and correctness re-plan

The frozen seeds 1–30 development panel retained the slice as candidate mechanics: all runs completed, 92 tactical roots contained a new key, 13 changed the baseline action, and search gained eight total rounds and three total antes with no terminal regression. Both policies still won zero games. On the preregistered disjoint seeds 31–60, search improved seed 49 by three rounds and one ante but regressed seed 32 by two rounds and one ante; the net was one round, equal average ante, and zero wins for both. The seed-32 divergence occurred Jokerless, so the certified Joker transition expansion is not the cause. Retain the mechanics and their differential tests, but reject this as a strength or promotion result. The fixed eight-particle root selector remains an uncalibrated tactical heuristic; do not tune it on these panels or scale particles as the next move.

Adversarial review also found that the pre-blind evaluator compared one-purchase counterfactuals while the executed strategic baseline could continue shopping. Restrict search to roots where the baseline would leave, and execute an overriding purchase as the complete option `buy then leave`. Do not use one-card rollout values to override a baseline purchase until coherent multi-action shop continuation exists. Credit Card's debt floor also stacks per active nondebuffed copy; make public legality count copies and retain the debuff regression.

### Active Increment: Exact Public Tactical DAG

- Replace sampled current-blind overrides with a learner-free, memoized public-state DAG. The solver state contains only the visible hand, public remaining-deck count vector, public round resources, chips, money, and hand statistics; the root observation supplies the already-certified blind and Joker mechanics.
- Enumerate refill outcomes as exact multivariate-hypergeometric count selections. Treat draw order as exchangeable only inside the current base-card, order-insensitive certified envelope, and retain exact multiplicities with `Fraction` probabilities.
- Reduce play/discard actions only when selected and retained visible-card multisets make their transition semantics identical. Preserve one concrete legal representative, retain the caller's baseline action on an equivalent tie, and never use raw object IDs or hidden deck order.
- Return `Outcome(clear_probability: Fraction, expected_capped_chips: Fraction, complete: bool)`. A state-budget, transition-budget, chance-branch limit, unsupported mechanic, missing public stat, or any incomplete child makes the root decision incomplete and forces the unchanged strategic baseline. A complete exact tie also keeps the baseline.
- Cache state values, score evaluations, and draw compositions. Begin with a bounded two-decision tactical horizon and the existing exact base-card/stateless-Joker envelope; widen only from measured cache/branch profiles, not by increasing particles or weakening completeness.
- Prove the kernel against an uncached exhaustive oracle on tiny labeled and duplicate-card decks. Add hidden-twin, shuffled remaining-deck/action iteration, semantic-duplicate, fresh/warm-cache, cache-key mutation, exact-probability, budget-incomplete, and tie-to-baseline regressions.
- Retire the sampled tactical selector from the deployed Red/Gold policy while retaining its certified one-step transition model for differential tests. Seeds 1-60 and the organic Joker fixtures are development evidence only. Freeze any widened exact artifact before a new disjoint candidate panel; replay representative promoted decisions and every claimed win through real Balatro.

#### Re-plan after the strict action-complete probe

The first strict all-action implementation completed zero of 27 attempted tactical roots on development seeds 1-5. Most roots correctly failed the two-decision horizon; the one eligible last-hand/last-discard root exhausted 100,000 transitions because every multi-card discard and every exact refill had to feed a complete final-play decision. Do not raise that budget or call partial enumeration exact. Keep the action-complete kernel and tiny oracle as a correctness reference, but deploy the smallest conservative exact improver: compare the actual baseline with every immediate play and every one-card discard, collapse only semantic duplicates, and require every represented action/chance child to complete. A multi-card baseline remains represented and therefore may still make the decision fail closed. An override claims only strict exact improvement over the baseline inside this declared proposal, never global tactical optimality. Record proposal completeness separately from mechanical/draw exactness and widen the proposal only through symbolic reductions or measured cache reuse.

The conservative proposal is implemented and the sampled tactical selector is no longer deployed. Exact count-vector draws, terminal-before-refill absorption, remaining-deck depletion, Faceless-to-Bull money, hand statistics, semantic duplicate actions, per-decision state/score/draw caches, and every deterministic budget are covered by fractional tiny-deck oracles and atomic fallback tests. Two consecutive organic Red/Gold Jackdaw discards match a member of the exact public successor distribution with the correct exact mass; this is candidate evidence, not Balatro authority. The dirty development panels complete without timeouts: on seeds 1-30 the exact policy improves only seed 5, from ante 1/round 2 to ante 2/round 6, moving the average from 4.733 to 4.867 rounds and 1.800 to 1.833 antes with no regressions; seeds 31-60 are identical to the baseline. All policies still win 0/60. Retain the exact mechanism as a safer tactical floor, but do not promote a strength claim or spend a fresh replication panel until a symbolic multi-card-discard reduction creates broader interventions.

#### Re-plan after the first Red/Gold authority transfer

The clean revision-`43a3cd0` Red/Gold seed-5 authority run completed as a loss at ante 1 after 16 decisions, but candidate replay failed at transition 6 before the candidate-only tactical improvement. Balatro generated the first-shop Crafty Joker with a Rental sticker and a $1 buy cost; pinned Jackdaw generated the same Crafty Joker without Rental at $4. The authority policy consequently bought both Crafty Joker and To Do List, while the candidate trajectory could buy only To Do List. The later authority state contained unsupported To Do List and never entered the exact tactical solver. This run neither validates nor contradicts the exact decision; it invalidates seed 5 as a transfer case and exposes a Gold-stake sticker-RNG parity blocker.

Stop policy panels and proposal widening until the first-shop sticker divergence is fixed at its source and regressed. The repair must reproduce the organic Rental assignment and price from the same public action prefix without reading authority state into the candidate, then pass the complete authority trace from transition zero with no mismatch or waiver. After that, rerun the unchanged frozen policy through a fresh exclusive authority trace. Only a mismatch-free trajectory that actually records a complete exact-search decision can validate the mechanism. Do not compensate in the public adapter by copying authority stickers or repricing offers independently of Jackdaw's private simulated state.

The blocker was Jackdaw flag plumbing, not RNG: initialized runs store Eternal, Perishable, and Rental enablement under `game_state["modifiers"]`, while the pinned card factory reads those three booleans from the top level. Seed 5's first two `ssjr1` rolls already exactly predict Rental Crafty Joker followed by plain To Do List. The candidate wrapper now temporarily exposes only those candidate-owned nested booleans at the card-factory boundary, fails closed on inconsistent state, and removes the aliases after every call. It does not copy an authority sticker or independently alter a price. An organic regression reproduces the $1 Rental Crafty Joker and $4 plain To Do List from the original public action prefix.

That repair advanced immutable-trace replay to the terminal transition, where BalatroBot observes `GAME_OVER` before Rental's queued dollar event runs but Jackdaw had deducted the fee synchronously. The wrapper now restores only that terminal queued charge while retaining synchronous end-of-round Joker and Perishable mutations; winning-round Rental charges are unchanged. The complete authority trace now replays exactly for 16/16 transitions. This closes the discovered Red/Gold candidate parity defects, not the tactical authority gate: the real trajectory owns unsupported To Do List, `PublicBlindBeliefSearch` correctly stays inactive, and no exact-search decision is present. Find a natural supported authority root or widen To Do List only after exact scoring and organic differential evidence; do not label this trace mechanism validation.

Correct Gold stickers supersede the earlier seeds 1–60 tactical result: those trajectories were generated by a kernel that never applied organically configured Eternal, Perishable, or Rental stickers. On the corrected dirty development seeds 1–30, the unchanged strategic and exact policies are identical on every seed: both complete 30/30, win 0/30, and average 5.400 rounds and 2.067 antes. A reachability audit explains the null result. Across 640 hand decisions, 459 are in Small or Big Blinds. Of 145 otherwise admitted search attempts, 139 fail closed because more than two play/discard decisions remain; only six complete, and none changes the baseline. Nineteen Small/Big states satisfy the two-decision horizon, but 13 contain at least one unsupported Joker and only six reach the exact proposal. The primary bottleneck is therefore the horizon, not proposal width or any single missing Joker.

Do not respond by raising transition budgets, restoring particles, or adding isolated Joker keys. The next tactical increment must symbolically reduce earlier decisions: compute admissible survival bounds and mechanically dominated play/discard classes from public score histograms and exact remaining-deck counts, expanding a branch only while its upper bound can beat the baseline. It must remain exact inside a declared proposal and fall back atomically when bounds cannot prove completeness. Require a material increase in completed roots and at least one action-sensitive paired improvement before another authority transfer; otherwise stop widening current-blind search and move effort to the action-complete shop contract.

## Execution Status (2026-08-08)

The failed independent simulator, planner, imitation pipeline, rule-presence gate, and their scripts/tests have been removed. The first foundation is implemented: typed public observations and actions, an adversarial information firewall, a strict BalatroBot observed-state backend, stable canonical state, provenance-rich tamper-evident traces, and no-waiver differential replay. The replacement test suite passes. Across 68 retained real-trace files, the canonicalizer accepts all 20,542 snapshots; the firewall accepts all 20,532 settled decisions and rejects only 10 transient `HAND_PLAYED`/`DRAW_TO_HAND` states.

A fresh public-action Red/White seed-1 smoke run completed in real Balatro and its five decisions reproduced exactly in a second real run. Jackdaw is pinned at `dbedc66255fe594cce7b7cccc188c8a11649d9ec`; its upstream suite passes 1,561 tests. Its raw bridge initially had 638 representational differences from BalatroBot. A narrow adapter now derives BalatroBot's representation from Jackdaw's own state. The clean schema-v4 campaign reproduced 765/765 transitions across seeds 9-25; all 17 runs lost. Policy and environment processes are now isolated, the real-game snapshot spike is complete, and public-history recurrent training exists. Jackdaw remains an untrusted candidate and every trained checkpoint still has zero wins. Schema v5 supersedes v4 after strategic exploration exposed previously unrepresented permanent card bonuses. Fresh schema-v5 seed-1 coverage and strategic traces reproduce 25/25 and 23/23 transitions exactly; both are terminal losses and only narrow authority evidence.

The first real solve boundary is now clean. At repository revision `b821b5b`, the frozen public strategic baseline completes candidate Red/White seeds 1-100 with 1 win, 7.89 average rounds, and 2.69 average ante. On real seed 63, the same policy reaches Balatro's `ROUND_EVAL`, `won=true`, ante-9 boundary after 212 decisions; all 212 transitions replay exactly in pinned Jackdaw with no mismatch. This establishes that the rebuilt system can beat one normal run. It remains a handcrafted baseline with a 1% candidate win rate, not a learned model and not a superhuman claim.

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

- Candidate-only evidence originally led to a false compatibility rule that forced an ante-8 clear directly to `GAME_OVER`. The completed real seed-63 trace corrects the contract: Balatro returns `ROUND_EVAL`, increments to ante 9, and sets `won=true`. Cashing out opts into Endless Mode; it is not required to establish the win.
- Remove the candidate-only terminal conversion and the suppression of ante advancement. Make the authority runner treat the first settled public observation with `won=true` as a complete terminal result, before any cash-out or Endless action. Losses remain complete only at `GAME_OVER`.
- Add a runner regression for `ROUND_EVAL` plus `won=true`, replay the completed diagnostic trace through the corrected candidate to verify the winning transition, then capture a fresh trace that closes immediately at the win. A solve trace must end at that boundary and pass exact differential replay; post-win Endless transitions are outside the run being evaluated.
- Historical candidate panels that used the false forced-`GAME_OVER` state are retained only as strategy-development evidence. Rerun the frozen panel under the corrected terminal contract before quoting its outcome metrics at the new revision.
- The corrected candidate now matches the completed diagnostic authority trace through the win transition and 27 further optional Endless transitions: 240 transitions are exact. The next mismatch is an Endless-only deck-capacity difference at transition 241. This is useful simulator work later, but it is outside the declared run endpoint; the next clean trace must stop at the already-exact `won=true` boundary.
- A fresh clean trace does stop at that boundary after 212 decisions, and every recorded transition matches. The differential gate still rejects it only because its final assertion hardcodes `state=GAME_OVER`; update that assertion to accept either `GAME_OVER` or canonical `won=true`, while continuing to require an exact complete authority trace and exact final canonical transition.

### Active Increment: Empty-Shop Authority Settling

- A frozen seed-63 authority replay reached ante 7 twice, then failed deterministically after using a held Planet and attempting to buy the final remaining shop Planet. Both 40-poll and 200-poll runs ended `unsettled` because the backend rejects every shop whose card, pack, and voucher areas are all empty.
- Keep fresh-shop and reroll settling strict: an empty shop can be a transient animation state and must not be accepted merely because two polls match.
- Permit an empty shop only when the preceding canonical state plus public action proves that the last known offer was consumed: buying the sole remaining shop card or voucher while the other offer areas were already empty, or returning from a pack whose persisted shop areas were already empty. Once that empty shop is canonically established, normal use, sell, and leave actions may remain there; rerolls still require visible generated offers.
- Add positive and negative settling regressions, then retry the frozen seed-63 authority run. The two incomplete traces remain failure diagnostics and never count as evidence.

### Active Increment: Vanilla Mega-Pack Endpoint Completion

- The frozen seed-63 authority replay now reaches ante 8 and opens a Mega Standard Pack, but its first public pack selection times out after Balatro accepts the card. The authority log has no Lua error and shows `G.FUNCS.use_card` ran; the endpoint response condition never becomes true.
- Fix the pinned BalatroBot endpoint at the root cause. Capture the public pack state before `G.FUNCS.use_card`; when a multi-choice pack decrements `pack_choices` by one, require the same state to be restored, a live pack area, and `G.STATE_COMPLETE`. This follows Balatro's own `use_card` contract and covers vanilla and SMODS pack states without admitting unrelated states.
- Add a regression that opens a vanilla Mega Standard Pack, verifies the first selection returns in `STANDARD_PACK` with the pack still open, and verifies the second selection closes back to `SHOP`. Do not solve this with a longer transport timeout, an unconditional response, or a policy-side pack skip.
- Regenerate the tracked authority patch digest, commit the authority fix, and rerun the unchanged frozen seed-63 policy. The run counts only if it reaches `run_end` and differential replay reports zero mismatches, zero unchecked transitions, and zero waivers.

### Active Increment: Joker Stencil Runtime State

- The patched authority completed the frozen seed-63 run with `won=true`, but differential replay stopped at transition 71. In the ante-4 shop, Balatro's visible Joker Stencil had runtime `enhancement_x_mult=0`; Jackdaw emitted the same Joker without that field.
- Mirror vanilla `Card:update` in the existing candidate compatibility refresh. For every owned, shop, and pack Joker Stencil, set runtime `ability.x_mult` to `joker_slots - owned_joker_count + owned_stencil_count` before serialization. Preserve zero because it is a real visible runtime value; do not erase it in canonicalization or add a parity waiver.
- Add focused full-slot and owned-Stencil regressions, rerun the project suite, then replay the already-complete authority trace without launching Balatro. Continue stop-on-first-mismatch until the entire winning trace is exact.
- The Stencil runtime correction moves the stop-on-first-mismatch boundary from transition 71 to transition 202.

### Active Increment: Open-Pack Capacity

- With Joker Stencil fixed, the completed seed-63 trace matches through 201 transitions. After the first Mega Standard selection, both kernels retain four offers, but Balatro keeps the pack area's original `limit=5` while the candidate rewrites the limit to the remaining count of four.
- Track the active candidate pack list by object identity and capture its size when the pack opens. Preserve that capacity while selections mutate the same list; clear it when the pack closes, and replace it when a queued/new pack installs a new list. Pass the tracked value into bridge normalization instead of deriving capacity from the shrinking offer count.
- Add a focused normalization/tracking regression, rerun the suite, and replay the same immutable authority trace. Do not canonicalize `limit` away: it is visible UI capacity and affects observation equality.
- Preserving the active pack capacity moves the mismatch boundary from transition 202 to the previously incorrect win-boundary compatibility at transition 212.

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

The public/private contract, no-waiver replay loop, extended-action lane, process isolation, real-kernel snapshot benchmark, and public recurrent-training path are complete. The fair strategic baseline now has one exact real win and a 1/100 clean candidate win rate. The immediate milestone is a public-only action-value/search teacher that turns this isolated solve into broad multi-seed strength; further blind PPO or imitation tuning is explicitly rejected.

### Completed Negative Probe: Quick Action-Value Scalability

- Test the smallest falsifiable version before building the full recurrent action-value trainer. Before each episode, use an experiment RNG independent of the game seed to draw a bounded SHOP/PACK root index and an action nonce, run the frozen `PublicStrategicPolicy`, replay the selected public prefix exactly, randomize one legal action at that root, and then return control to the baseline. This covers both early and late SHOP/PACK states without selecting on the episode's hidden future or cloning live state.
- The sample contains only the public observation, public previous action, public candidates, the frozen base model's public-history hidden tensor, chosen action, behavior probability, and the next three public blind clears; it contains no seed, candidate state, snapshot, RNG state, or counterfactual branch. Stop the branch after three clears or normal terminal so this probe tests a dense short-horizon signal rather than being blocked by unrelated unimplemented late-game public affordances.
- Reuse an existing `PublicRecurrentPolicyValue` checkpoint. Freeze the observation encoder, action encoder, recurrent cell, and value head; reset only `policy_head` from the same training seed for every slice so obsolete PPO logit scale cannot saturate the regression, then train that head against the next-three-clear target divided by three. Do not add a second model family or modify deployed checkpoint semantics for this disposable probe.
- Train from identical initialization on nested sample counts and evaluate every frozen scorer on one untouched paired seed panel, intervening at the same single public decision. Compare average round, average ante, win count, and paired per-seed round deltas against the unchanged baseline.
- The probe succeeds only if held-out outcome improves with additional samples, the largest model beats the baseline on paired average round, all episodes terminate cleanly, and a shuffled-target negative control fails. Prediction loss without policy improvement is a failure.
- Keep the experiment candidate-only and provenance-rich. If it succeeds, replace the probe with the full recurrent public Monte Carlo Q pipeline; if it fails, delete the probe instead of tuning it into another training framework.

The probe is complete and does not pass its scale gate. A candidate-only run collected 1,024 exact public interventions from 1,407 attempted Red/White episodes in 557.9 seconds: 967 SHOP roots, 57 PACK roots, and next-three-clear targets distributed as 154 zero, 116 one, 123 two, and 631 three. Held-out Huber loss on 256 new interventions improved monotonically from 0.0722 at 128 samples to 0.0669 at 1,024, but the shuffled-target control reached 0.0682 because most states clear all three blinds regardless of the selected action. The representation can fit public survival context, but the target is only weakly action-sensitive.

Policy outcomes reject the scaling claim. On seeds 60001-60100, the frozen strategic baseline averaged 7.17 rounds; the 128/256/512/1024 models averaged 3.44/6.85/7.54/7.17, and the shuffled control averaged 3.43. The post-hoc 512 peak had a paired round-delta confidence interval spanning zero. On the untouched replication seeds 61001-61200, the predeclared 1,024-sample model averaged 7.125 rounds versus 7.295 for the baseline, a paired delta of -0.17 with bootstrap 95% interval [-0.74, 0.40]; both won 0/200. Do not scale this frozen-encoder/three-blind objective or call its decreasing prediction loss strategic progress. The disposable probe implementation and tests are deleted after recording the result.

Unbounded exploration also exposed a real public-contract gap before the target was narrowed. Candidate seed 50455, root 9, publicly sold Loyalty Card and later reached Cerulean Bell; the public legal-action surface allowed a five-card play that omitted the visibly forced card, and Jackdaw rejected it with `Forced card (Cerulean Bell) must be in the selection`. The forced public hand slot is currently absent from `PublicObservation`. Fix that schema/action-legality root cause before any full-horizon learner or broader exploratory campaign.
