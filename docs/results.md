# Results

All numbers here are read from files under `evidence/` by `python -m benchmarks`,
which writes the machine-generated tables to
[`benchmarks/results/results.md`](../benchmarks/results/results.md) and
[`results.json`](../benchmarks/results/results.json). CI rebuilds them and fails if
they change. This page explains what they show. Method and disclosure rules are in
[methodology.md](methodology.md).

Setting throughout: real Balatro through BalatroBot, Red Deck, White Stake,
all-unlocked profile, complete games from Ante 1. A win is clearing the Ante 8 boss.

## Headline

![Ante reached per game by policy](../benchmarks/results/figures/ante-reached-by-policy.svg)

Each dot is one complete game of a non-model policy on the fixed seed panel
D0000000 to D0000019. The two stars are the coached games. The best heuristic
policies cleared Ante 8 in 3 of 20 games and reached Ante 8 or beyond in 7 of 20.
The coached system cleared Ante 8 in both of its recorded games, at high and at low
reasoning effort, on seeds outside the panel. Two games are a demonstration, not a
rate. The unattended win rate of the coached system is unmeasured.

## Table A: real-game results

| System | Games | Ante 8 cleared | Reached Ante 8+ | Median ante | Seeds |
|---|---|---|---|---|---|
| Astra high + tools | 1 | 1 | 1 | 9 | D0001000 |
| Astra low + tools | 1 | 1 | 1 | 11 (endless) | 2K9H9HN |
| search-v4 | 20 | 3 | 7 | 6.5 | D0000000-19 |
| search-v5 | 20 | 3 | 6 | 6.5 | D0000000-19 |
| search-v6 | 20 | 3 | 7 | 6.5 | D0000000-19 |
| search-v7 | 20 | 2 | 5 | 7 | D0000000-19 |
| search-v3 | 20 | 2 | 5 | 6 | D0000000-19 |
| search | 20 | 1 | 4 | 6.5 | D0000000-19 |
| search-planets | 20 | 1 | 4 | 6 | D0000000-19 |
| search-v2 | 20 | 1 | 2 | 6 | D0000000-19 |
| build-first | 20 | 1 | 3 | 5 | D0000000-19 |
| strategic | 20 | 0 | 0 | 5 | D0000000-19 |
| strategic (career profile pilot) | 10 | 0 | 0 | 5 | D0000000-09 |
| baseline-v1 (partial) | 11 | 0 | 0 | 4 | D0000000-10 |

Disclosures that belong with this table:

- **Astra high** (`gpt-6-astra`, high effort): 203 decisions in 1,690 seconds. 175
  were chosen by the model, 5 were delegated by the model to the `search-v6`
  numerical policy for individual hands, and 23 were automatic cashouts. Final hand
  415,042 against a 300,000 requirement, three hands and four discards unused.
- **Astra low** (`gpt-6-astra`, low effort): cleared Ante 8 after 303 decisions,
  then continued in endless mode and lost at Ante 11 with a peak hand of 1,239,454
  against a 10,800,000 requirement. This was a supervised development run: adapter
  fixes, prompt clarifications, reviewed continuations and extended limits were
  applied between the seven recorded segments. No uncertain mutation was replayed.
  The segments and their SHA-256 hashes are in
  `evidence/astra-low-2K9H9HN/segments.json`.
- **Baselines**: ten complete 20-game panels plus two partial ones. One
  `baseline-v1` game ended with an error status and is excluded from ante
  statistics. The `strategic-001` pilot ran on the career profile, not
  all-unlocked. Sources and one-line policy descriptions are in
  [`evidence/baselines/PROVENANCE.md`](../evidence/baselines/PROVENANCE.md).

## Score against the requirement

![Chips scored against the blind requirement](../benchmarks/results/figures/score-vs-requirement.svg)

The grey step is the chip requirement of each blind, which grows roughly
exponentially. Dots are the best single hand scored in that blind. A blind is
cleared by the sum of its hands, so dots below the step are normal in early antes.
In both runs the best hand overtakes the requirement from Ante 3 or 4 onward and
stays there, which is what a scaling build looks like when it works. The Astra-low
run's last two antes show the endless requirement pulling away faster than the
build could follow.

## Scoring-engine exactness

![Predicted against observed hand score](../benchmarks/results/figures/hand-score-parity.svg)

| Run | Plays compared | Exact | Note |
|---|---|---|---|
| Astra high, D0001000 | 54 | 54 | 18 differ from the game by under 1 chip because the game floors the final score. Recomputed from the trajectory; matches `scoring-audit.json`. |
| Astra low, 2K9H9HN | 47 | 46 | Offline replay after a Fortune Teller adapter fix made once the run was over, quoted from [trajectory-review.md](trajectory-review.md). The trajectory stores no per-play prediction, so it cannot be recomputed by the builder. The one miss involves a retriggered Lucky card, whose random Mult the scorer deliberately omits; two hidden-Joker plays were excluded. |

The scorer is the part of the system a reader can check without a model. When
the hand is deterministic and every Joker is visible, it predicts the real game's
score exactly.

## Decision sources in the Astra-high win

| Source | Decisions |
|---|---|
| Model (Astra) | 175 |
| Delegated to search-v6 by the model | 5 |
| Automatic cashout | 23 |
| Total | 203 |

Decisions per ante: 15, 20, 35, 33, 30, 29, 24, 17 for Antes 1 to 8. The
mid-game antes carry the most decisions because that is where shops, packs and
consumables multiply the choices.

## What is not shown, and why

- No win rate for the coached system. Two games on two seeds cannot support one.
- No same-seed comparison between the coached system and search-v6, and no
  model-without-tools control. Neither was run.
- No token or cost figures. The evidence runs did not record them.
- No per-decision latency. Only whole-run wall-clock is recorded.

New games can be added to every table and figure with
`python -m benchmarks --runs DIR...`; see [methodology.md](methodology.md).
