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
D0000000 to D0000019. The stars are the two coached games. The best heuristic
policies cleared Ante 8 in 3 of 20 games and reached Ante 8 or beyond in 7 of 20.
The coached system, GPT-6 Astra at low reasoning effort with exact numerical tools,
cleared Ante 8 in both recorded games on seeds outside the panel and continued in
endless mode to Ante 11 and then Ante 13, the latter with a peak hand of
134,231,931,235 chips. Two games are a demonstration, not a rate. The unattended
win rate of the coached system is unmeasured.

## Table A: real-game results

| System | Games | Ante 8 cleared | Reached Ante 8+ | Median ante | Seeds |
|---|---|---|---|---|---|
| Astra low + tools, headless | 1 | 1 | 1 | 13 (endless) | TAF7DNTX |
| Astra low + tools, supervised | 1 | 1 | 1 | 11 (endless) | QD3F4XVW |
| Astra low + tools, on a panel seed | 1 | 1 | 1 | 10 (endless) | D0000000 |
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

- **Astra low, headless, TAF7DNTX** (`gpt-6-astra`, low effort): skipped the Ante 1
  small blind for an Investment Tag, cleared the Ante 8 boss Crimson Heart with
  180,442 against 100,000, and lost to The Tooth at Ante 13 with 94 billion
  required. 456 decisions from 404 model calls: 378 chosen directly, 31 chained
  follow-ups the model spelled out, 13 forced moves with a single legal action,
  34 automatic cashouts. Eight replies were rejected as illegal and corrected on
  the next call. The Codex service stalled on 15 calls, all retried, and the hedge
  process answered 14 more. The runner process was stopped and resumed four times
  at safe moments, always while waiting for the model, to deploy runner fixes; the
  game state and trajectories were never edited. Details, hashes and the revision
  of each segment: `evidence/astra-low-TAF7DNTX/README.md`.
- **Astra low, QD3F4XVW** (`gpt-6-astra`, low effort, game visible at speed 2 and
  screen recorded in one take): the first game played end to end by
  `balatro supervise`. Cleared Ante 8 against Cerulean Bell with 111,598 against
  100,000; lowered the ante twice with Hieroglyph and Petroglyph to buy rounds;
  lost to The Plant at Ante 11 with 14,400,000 required. 473 decisions from 388
  calls, 50 chained, 6 forced, zero rejected replies, 3 stalls retried. One
  automatic restart after the mod refused a boss reroll the runner had considered
  legal; the supervisor resumed two seconds later with the live state verified.
  Details: `evidence/astra-low-QD3F4XVW/README.md`.
- **Astra low, D0000000** (`gpt-6-astra`, low effort, game window visible and screen
  recorded): the operator set the seed to the first seed of the baseline panel, so
  this is the one game where the model and every heuristic played identical cards.
  Cleared Ante 8 and lost to The House at Ante 10 with 1,120,000 required. 315
  decisions from 265 calls, 34 chained, 5 forced, zero rejected replies, 5 stalls
  retried, 1 game-reply timeout recovered by reading the live state. The runner
  was restarted three times at safe moments, once after the operating system
  killed every process including the game, which Balatro's autosave and
  BalatroBot's `load` restored; the differences the resume accepted are recorded
  in the manifests and the reconstructed segment result is marked. On the same
  seed the best heuristic, search-v5, reached Ante 6 with a 14,700 peak; the
  model's peak was 1,840,907. Details: `evidence/astra-low-D0000000/README.md`.
- **Astra low, 2K9H9HN** (`gpt-6-astra`, low effort): cleared Ante 8 after 303 decisions,
  then continued in endless mode and lost at Ante 11 with a peak hand of 1,239,454
  against a 10,800,000 requirement. 357 model calls covered 384 decisions; the
  other 30 were automatic cashouts. This was a supervised development run: adapter
  fixes, prompt clarifications, reviewed continuations and extended limits were
  applied between the seven recorded segments. No uncertain mutation was replayed.
  The segments and their SHA-256 hashes are in
  `evidence/astra-low-2K9H9HN/segments.json`.
- **Baselines**: ten complete 20-game panels plus two partial ones. One
  `baseline-v1` game ended with an error status and is excluded from ante
  statistics. The `strategic-001` pilot ran on the career profile, not
  all-unlocked. Sources and one-line policy descriptions are in
  [`evidence/baselines/PROVENANCE.md`](../evidence/baselines/PROVENANCE.md).
- An earlier high-effort run of a previous version of this system is kept under
  `evidence/first-win/` and described in [coached-win.md](coached-win.md). It is
  archived evidence and is not part of these results.

## Score against the requirement

![Chips scored against the blind requirement](../benchmarks/results/figures/score-vs-requirement.svg)

The grey step is the chip requirement of each blind, which grows roughly
exponentially. Dots are the best single hand scored in that blind. A blind is
cleared by the sum of its hands, so dots below the step are normal in early antes.
In both games the best hand overtakes the requirement from Ante 4 onward and stays
there, which is what a scaling build looks like when it works. In the headless
run, Blueprint on Hanging Chad, Brainstorm on Photograph, Hologram and Steel Joker
kept pace with the endless curve through Ante 12; at Ante 13 the requirement of
94 billion outran a best hand of 951 million in that blind, even though the
previous blind had produced 134 billion.

## Scoring-engine exactness

| Run | Plays compared | Exact | Note |
|---|---|---|---|
| Astra low, 2K9H9HN | 47 | 46 | Offline replay after a Fortune Teller adapter fix made once the run was over, quoted from [trajectory-review.md](trajectory-review.md). The trajectory stores no per-play prediction, so it cannot be recomputed by the builder. The one miss involves a retriggered Lucky card, whose random Mult the scorer deliberately omits; two hidden-Joker plays were excluded. |

The scorer is the part of the system a reader can check without a model. When
the hand is deterministic and every Joker is visible, it predicts the real game's
score exactly.

## Decision mix in the headless run

| Source | Decisions |
|---|---|
| Model, one action per reply | 378 |
| Model, chained follow-ups | 31 |
| Forced move (single legal action) | 13 |
| Automatic cashout | 34 |
| Total | 456 |

| Phase | Decisions |
|---|---|
| Shop | 241 |
| Selecting a hand | 95 |
| Opening a pack | 47 |
| Choosing a blind | 39 |
| Round end (cashout) | 34 |

The shop is still where the calls go: 73 rerolls, 44 pack purchases, 45 consumable
uses, 40 card purchases and 34 shop exits across 78 visits with a median of 2 and a
maximum of 13 actions each. Hand plays and discards were 73. Follow-up chains
covered 31 of those shop actions and forced moves 13 blind selections, so 404 calls
produced 456 decisions. The earlier run needed 357 calls for 384 decisions. The
generated tables keep the earlier run's mix as a second block.

## What is not shown, and why

- No win rate for the coached system. Four games cannot support one.
- No same-seed comparison between the coached system and search-v6, and no
  model-without-tools control. Neither was run.
- No token or cost figures. The evidence run did not record them.
- Latency only as whole-run totals and per-call seconds inside the trajectories:
  the headless run took 5,883 active seconds for 404 calls, about 14.6 seconds
  each including stalls; calls the service answered promptly took about nine.

New games can be added to every table and figure with
`python -m benchmarks --runs DIR...`; see [methodology.md](methodology.md).
