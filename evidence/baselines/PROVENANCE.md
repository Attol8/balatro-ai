# Baseline provenance

Twelve real-game runs of non-model policies, recorded on 2026-09-06 with the same
game settings as the coached runs: real Balatro through BalatroBot, Red Deck, White
Stake, all-unlocked profile, one game per seed starting at Ante 1. The one exception
is `strategic-001`, whose manifest records the `career` profile; it is kept as a
labelled pilot and never pooled with the all-unlocked panels. Each directory
holds the original `manifest.json` (settings, policy, `git_revision`, `dirty` flag,
server mod list and profile mode) and `summary.json` (per-game outcomes with seed,
status, ante and round reached, decisions and wall-clock seconds). Trajectories for
these runs are not included; they add nothing to the outcome statistics.

These policies were public-information heuristics and bounded searches developed
before the model-coached product. Their source was removed from the working tree in
commit `99cf692`, which rewrote the repository around the coach. It remains in this
repository's history at the revisions below, under `balatro_ai_v2/live/` (runner,
policy, strategic, build_first) and `balatro_ai_v2/solver/`.

| run | policy | seeds | requested | attempted | Ante-8 clears | source revision | tree |
|---|---|---|---|---|---|---|---|
| strategic-unlocked-001 | strategic | D0000000-19 | 20 | 20 | 0 | a413126 | dirty |
| build-first-001 | build-first | D0000000-19 | 20 | 20 | 1 | dcba69c | clean |
| search-planets-001 | search-planets | D0000000-19 | 20 | 20 | 1 | f272fbc | dirty |
| search-stable-001 | search | D0000000-19 | 20 | 20 | 1 | 4f6bc96 | clean |
| search-v2-001 | search-v2 | D0000000-19 | 20 | 20 | 1 | a619afc | clean |
| search-v3-001 | search-v3 | D0000000-19 | 20 | 20 | 2 | bb2c77a | clean |
| search-v4-001 | search-v4 | D0000000-19 | 20 | 20 | 3 | 14a3696 | clean |
| search-v5-001 | search-v5 | D0000000-19 | 20 | 20 | 3 | 09f943c | clean |
| search-v6-001 | search-v6 | D0000000-19 | 20 | 20 | 3 | 8407cdd | clean |
| search-v7-002 | search-v7 | D0000000-19 | 20 | 20 | 2 | d90b034 | clean |
| live-validation-001 | baseline-v1 | D0000000-19 | 20 | 11 | 0 | a413126 | dirty |
| strategic-001 | strategic | D0000000-09 | 10 | 10 | 0 | a413126 | dirty |

"Dirty" means the manifest recorded uncommitted changes at run time; the manifest's
`python_source_sha256` identifies the exact source that ran. The two partial panels
(`live-validation-001` stopped after eleven games, one of which ended with an error
status; `strategic-001` was a ten-seed pilot on the career profile) are reported separately
in the results and are never pooled with the complete panels.

Policies in one line each:

- **baseline-v1**: deliberately approximate public-information heuristic, the first
  real-game benchmark opponent.
- **strategic**: rule-based public policy with build intent, shop priorities and
  hand selection by exact scoring.
- **search, search-v2 to search-v7**: bounded public-information search over plays,
  discards and shop actions, each version adding one modelled mechanic (Green Joker
  growth, boss projection, card and Joker ordering, hidden-Joker beliefs, Blueprint
  placement, static debuffs, boss readiness). `search-v6` is the policy the
  Astra-high win delegated five hand decisions to.
- **search-planets**: the stable search variant with an isolated planet-purchase
  rule, recorded as a negative ablation.
- **build-first**: integrated policy that derives a build plan from the current
  inventory and values shop offers against it.

Runs from the same period that are **not** included, and why: `search-001` and
`search-002` were mostly unplayed; `known-seed44-001` used a non-panel seed;
shadow, intervention and two-ante directories were rollouts from saved mid-game
states rather than complete games; the teacher pilot was an offline labelling
exercise, not a game.
