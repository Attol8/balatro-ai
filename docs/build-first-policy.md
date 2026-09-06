# Build-first policy: the next substantial bet

Status: first prototype implemented at `dcba69c` and evaluated on 20 real
development games: 1/20 wins versus V6's 3/20. Not promoted. Best measured real
development result remains 3/20. The design below remains the broader target;
the prototype does not fulfill all of its mechanism-specific planning requirements.

## First prototype result and limitations

`--policy build-first` shares a public intent and heuristic valuation across shop
offers, replacement plans, packs and safe growth plays. Pending purchases are
revalidated; V6 remains unchanged. Correctness verification: 903 tests passed.
The complete real panel is `runs/build-first-001/summary.json`: D5 won, the other
19 runs lost, with no errors or truncations. No new winning seeds relative to
V6; D1 and D6 regressed from wins to losses. Peak hand score was 78,240.

The prototype still assigns broad role/tag-based acquisition values. Actual
growth-aware hand preference covers only a subset of scaling mechanisms; advanced
route labels are not complete executable plans, and consumable handling during
hands largely retains the inherited fallback. This is not the full architecture
described below, nor evidence that the full architecture cannot work.

Concrete observed weakness: D0/D3 ended with Throwback at X1, and D4/D11 ended
with Red Card at +0. Generic growth preference can even conflict with these
mechanisms: avoiding blind skips does not grow Throwback. These facts do not
explain every loss, but establish that role labels are insufficient for valuing
an executable build. Future investment value must be conditional on a supported
sequence of growth events, its costs, and retained immediate scoring power.
Do not patch this evidence into a universal blacklist or call it a proven causal
explanation of the whole panel. No training labels or live promotion follow.

## Game model

Treat Jokers as conditional effects with trigger timing, resource requirements,
growth events and reset conditions—not as isolated tier-list entries. Our existing
catalogue contains all 150 vanilla Jokers: 24 flat-Mult, 17 chips, 23 xMult,
34 utility, 6 retrigger, 21 economy and 25 scaling primary roles. These labels
overlap mechanically: Scholar supplies chips and Mult, copy Jokers can multiply
scoring engines, and planets can supply growth without scaling Jokers.

| Build family | Strength | Decisions that must agree |
|---|---|---|
| Repeatable small hands | Reliable Joker scoring and growth | Purchases, hand family, discards, growth preservation |
| Planet-driven hands | Increasing base chips and Mult | Planets, draw consistency, deck edits, utility slots |
| Played-card retriggers | Repeated card-triggered effects | Ordering, enhancement/duplication targets, copies |
| Held-card engines | Valuable cards retained while another hand scores | Plays, discards, deck sculpting, hand size |
| Consumable/economy engines | Resources converted into scoring growth | Cash policy, inventory space, packs, buying/selling sequences |

Examples include Green/Supernova/Spare Trousers growth, Photograph with Hanging
Chad, Baron with Mime and appropriate held cards, and Hologram with deck growth.
These are conditional relationships, not instructions to force rare combinations.
Card-triggered multipliers and later additive Joker Mult are not interchangeable.

Money provides interest and access to future upgrades. Extra hands can provide
growth or resources, but cost unused-hand income and may endanger survival.
Never farm growth without a survival margin; never preserve cash mechanically
when spending is needed to survive. Before the first win, build a resilient
Ante-8 engine without forcing an endless combination. After a confirmed win,
shift toward scalable copy/retrigger/deck/consumable engines. Visible bosses can
require an alternate hand or escape resource.

## Architectural failure

`live/strategic.py` gets a baseline action, then independently overrides shops and
hands. `build_strategy.py` infers a hand through votes, not a growth plan.
`shop_search.py` primarily compares current synthetic-hand capacity; future
scaling and early economy enter as fixed 0.08 and 0.06 bonuses. Purchases and
subsequent play therefore need not express the same strategy.

`strategy_engine.py` already describes economy, scoring relations, boss conflicts
and advanced route stages. Reuse it, but its probability-valued utility is not a
trained estimator: do not label arbitrary heuristic numbers as win probabilities.

A descriptive V6 trace check found no primary-role scaling Joker in 8/12 first
ante6 shop inventories and no primary-role economy Joker in 11/12. This is not
proof of mistakes: planets, previous income and secondary effects matter. It
motivates examining growth and spending together rather than counting roles.

## Replacement contract

One controller maintains a revisable public BuildIntent across phases: working
hand families, present scoring engine, growth source and costs, reset conditions,
useful acquisition categories, expendable components, cash policy and boss risk.

Public observation/history → competing build intents → legal action sequences →
numerical immediate checks plus conservative growth/economy valuation → one
action → revalidate the intent against the resulting actual state.

A separate build-first live policy replaces shop, pack/consumable and play/discard
preference together. Existing tactical search supplies candidate plays and safety
checks; it cannot silently overwrite strategic intent afterward. Use existing
engine-state/options structures rather than creating another ontology or a stack
of V6 flags. An available major upgrade can justify changing the plan.

Evaluate coherent sequences: replacing a Joker to buy an available component,
not selling speculatively in isolation. Revalidate each step against actual
offers, inventory and cash. Unsupported mechanics stay explicit. No imagined
shops, seed access or runtime LLM calls. Long rollouts remain diagnostics, not
the sole authority: the last promising simulated sale regressed in the real game.

## Execution

Implement the integrated policy as one bet. Check legality/scoring contracts and
representative cross-phase builds; no full experiment per Joker. Freeze the
configuration and run the existing 20-seed development panel, comparing wins,
early deaths and resulting builds against V6. Judge the panel, not the best run.
Any promising policy then gets an untouched panel before generalization claims.
No training pipeline, new simulator, external model API or massive tournament
in this first implementation. Strategic valuation is the major uncertainty.

## Study sources and version caution

- [Player account: Chips and Influence Mult](https://www.reddit.com/r/balatro/comments/1bbh75a/how_to_win_chips_and_influence_mult_a_thorough/): repeatable scoring, growth and economy; reliable wins versus endless play. Some balance/stake values are historical.
- [Player account: A Guide to Scaling](https://www.reddit.com/r/balatro/comments/1cjyigp/a_guide_to_scaling/): complementary scoring sources and changing marginal value.
- Local `solver/joker_catalog.py`, `public_scoring.py` and pinned candidate data: mechanics references, not proof of complete authoritative parity.

Guides provide hypotheses, not an optimal-policy proof. Do not turn historical
anti-flush advice into rejecting strong flush/straight builds available in a run.
Verify exact mechanics against installed authority code when implementing them.
