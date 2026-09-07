# Methodology

How results in this repository are produced, what counts, and what is disclosed.

## The task

A complete game of Balatro on the real game client, Red Deck, White Stake,
all-unlocked profile, driven through the BalatroBot mod. A game is **won** when
the Ante 8 boss blind is cleared; the runner requires observing Ante 9, not only
the game's victory flag. **Ante reached** is the ante in which the game ended,
so a won game reports Ante 9 or more and a game lost in the Ante 5 boss reports
Ante 5. Endless play after a win is recorded separately and never counted as an
extra win.

## Seeds and panels

- Heuristic baselines were run on the fixed development panel D0000000 to
  D0000019: twenty seeds, one game each, all starting from Ante 1.
- The Astra-high win used seed D0001000, outside that panel, as the first game of
  a pilot that was stopped after the win. The Astra-low win used seed 2K9H9HN,
  chosen by the game.
- Seeds live in run manifests only. The model never receives one.

Coached games are therefore single games on different seeds from the panel. They
demonstrate that the system can beat the game; they do not estimate a win rate.
The repository says "unattended win rate unmeasured" wherever that matters.

## Disclosure rules

Every number in the README, `docs/results.md` and `benchmarks/results/` traces to
a file under `evidence/`. Specific disclosures that must accompany the results:

- The Astra-high win delegated 5 of 203 decisions to `search-v6`, the strongest
  heuristic baseline, and executed 23 automatic cashouts. Astra chose the other 175.
- The Astra-low run was supervised: adapter fixes, prompt clarifications, reviewed
  continuations and extended limits were applied between segments. No uncertain
  game mutation was replayed and no trajectory was edited. Segment boundaries and
  SHA-256 hashes are in `evidence/astra-low-2K9H9HN/segments.json`.
- The scoring engine uses approximations for random effects. Its exactness is
  reported on the hands where the outcome is deterministic and visible.
- Baseline manifests carry `git_revision`; the corresponding source is in this
  repository's history before commit `99cf692`, which removed the simulator and
  heuristic policies when the product was rewritten around the coach.

## What the benchmark builder does

`python -m benchmarks` reads `evidence/` and writes `benchmarks/results/`:

- `results.json` and `results.md`: Table A (real-game results per policy),
  Table B (scoring-engine exactness), Table C (decision sources and per-ante
  decision counts for the Astra-high win). Rendering is deterministic and CI
  fails if a rebuild changes either file.
- `figures/`: ante reached per game by policy, chips scored against the blind
  requirement for both coached games, and predicted-versus-actual hand scores.

It performs no model calls and needs no game. The only extra dependency is
matplotlib, installed with `pip install -e '.[bench]'`.

## Adding new real-game results

Play games with the product and point the builder at the output directories.
Each directory already contains the `manifest.json` and `result.json` the builder
needs. For a twenty-seed panel matching the baselines:

```sh
for n in $(seq -w 0 19); do
  balatro play --seed D00000$n --output runs/astra-low-panel/D00000$n
done
python -m benchmarks --runs runs/astra-low-panel/*
```

Rows are grouped by requested model and reasoning effort from the manifests.
Report the panel, the number of games, and whether any run was interrupted or
continued. Do not pool partial panels with complete ones without saying so.

## What is deliberately absent

No game simulator, no training, no policy ensemble, no automatic fallback player,
no retries of uncertain game actions, and no direct model API client. Model
access is the user's own Codex CLI signed into ChatGPT. Per-decision token and
cost accounting was not recorded for the evidence runs, so none is reported.
