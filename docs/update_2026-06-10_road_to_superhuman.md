# Update: M3 met — distance to superhuman

Date: 2026-06-10

## Where we stand

M3 is met: two ante-8 live wins with clean parity gates (seed 17, seed
38), every active trace seeds 1-39 gating clean with 0 mismatches. The
planner runs at 0.14s mean per decision, 328 tests pass, and source-rule
coverage is 357/357.

Win rate on Red deck / White stake is ~30-45% (n=20 tune seeds,
corrected engine). Calibration against the human ladder:

| Level            | Benchmark                                          |
|------------------|----------------------------------------------------|
| Us today         | ~35% Red/White                                     |
| Competent human  | ~70-90% Red/White                                  |
| Strong human     | near-100% Red/White; wins regularly at Gold stake  |
| Superhuman       | beats top players at Gold stake, across all decks  |

White stake is the easiest setting — experienced players essentially do
not lose it. We are below average-human on the easiest difficulty, and
superhuman is defined at Gold stake (eternal/perishable/rental jokers,
-1 hand, scaled blinds, tighter economy), none of which the evaluator
has seen.

## What we have that matters

The hard engineering is done and is the moat: a parity-proven fast
simulator (zero desyncs across 39 live seeds), sub-second online
planning, a fixed 512-action space with legal masks, and a live
execution loop with async-lag defenses. This is the substrate an
AlphaZero-style approach needs and that Balatro lacks publicly. The
evidence so far also says rollout search is the strength lever: direct
rollout reaches 14.75 rounds where the linear imitation ranker reached
4.6.

## Gaps, in the order they bind

1. **White-stake strength (~35% → 60-70%).** Known lever: `run_value()`
   underprices x-mult acquisition; deaths cluster at ante 5-7 on
   additive-heavy boards. Plus the hidden-info determinization bias —
   the flat 250 penalty is first-order; the proper fix is shared shop
   samples across candidates. Cheapest wins available; weeks, not
   months.
2. **Coverage debt.** 14 jokers excluded (probabilistic triggers,
   per-card state) and enhancement tarots undervalued. A superhuman
   agent exploits Bloodstone and Oops! All 6s rather than banning them
   — probability-stacking is core to top-level play. Requires chance
   nodes and per-card state in the fast env, touching the expectimax
   core.
3. **Learned value function.** The real wall. Linear scaling-rate
   projection cannot see beyond the rollout horizon (build trajectories
   like steel-card economies paying off at ante 7), and the imitation
   result already shows a linear ranker cannot distill the planner. We
   need a neural value head trained on rollout/self-play data; the fast
   env was built precisely so this is feasible. First step where
   success is not guaranteed by effort.
4. **Stake curriculum.** White → Gold adds mechanics that change
   strategy qualitatively, not just numerically. Parity gate must be
   re-proven and the evaluator retrained at each stake, then
   generalized beyond Red deck.

## Distance estimate

- Average human (Red/White ~80%): weeks — evaluator retune + bias
  fixes, all known levers.
- Strong human (Gold-stake competence): months — probabilistic env
  support, learned value model, stake-by-stake validation. The project
  shifts from engineering parity to ML research here.
- Superhuman: unknowable until the value head exists; gap 3 is the
  first unproven step.

## Immediate next steps

1. M4 / Phase 6 cleanup: delete legacy value tables, dedupe tactical
   helpers, deprecate the imitation path (dead weight on this
   trajectory).
2. Retune weights on the corrected engine toward the 50% target,
   x-mult acquisition priority first.
3. Replace the flat hidden-info penalty with shared determinization
   samples.
4. Then begin value-head work on rollout-generated data.
