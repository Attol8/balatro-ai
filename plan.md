# Execution plan

## Objective

Build a fair, superhuman Balatro agent. Real Balatro is authoritative; the
policy and search use only public observations, public history, and
policy-owned randomness.

## Current decision

Freeze `strategic` as the Red/White continuation policy. The current
`red_gold_search` implementation is diagnostic only until a search variant
beats this frozen control on paired authoritative runs. There is no 20/200
prerequisite for search work. Neural policy learning is deferred; parameter
tuning and public leaf-value distillation are the active strength path.

## Next work

1. Measure privileged Jackdaw clone construction, public projection, and step
   cost on a representative selecting-hand state, then extend coverage to shop
   and pack roots before sizing the full rollout worker. Keep private state
   and clone objects inside the benchmark process; publish aggregate timings
   only.
2. Use survival through Ante 6 as the primary development metric, with wins,
   average ante, and average round as secondary metrics. Use paired seeds and
   never retain a change because of named seeds alone.
3. Tune the exposed reserve, sell, and replacement parameters with CMA-ES on
   paired survival-to-Ante-6 fitness. Keep the candidate evaluator responsible
   for complete-run and provenance checks.
4. Turn existing public sibling search results into value-learning examples.
   Start with a calibrated survival target and preserve the tuned heuristic as
   the continuation policy. Do not let a learned model prune search until
   held-out paired evidence supports it.
5. Run authoritative paired evaluations before promotion, recording artifact,
   backend, game, compute, and seed provenance.

## Gates

- Public-information firewall and fail-closed action/observation contracts
  remain passing.
- All evaluated runs complete without rejected decisions or hidden-state
  access.
- Search must beat the frozen `strategic` control on held-out paired
  survival-to-Ante-6 and show no unacceptable regression in wins.
- Learned search must beat search alone on held-out authoritative runs before
  it becomes the deployed policy.

## Measurement result

The pinned Jackdaw selecting-hand fixture benchmark completed 25 repetitions
on 2026-09-02. Median clone construction was 1.16 ms, public projection was
0.28 ms, and action step was 2.36 ms; median clone-plus-step was 3.53 ms.
This is sufficient to begin bounded rollout data collection, but not a claim
about full-run throughput or authority parity.

## Supporting notes

Historical experiments, rejected hypotheses, and detailed run records are in
[`docs/plan-lab-notes.md`](docs/plan-lab-notes.md). They are evidence, not
active instructions.
