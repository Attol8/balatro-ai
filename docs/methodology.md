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
- The coached win used seed 2K9H9HN, chosen by the game, outside that panel.
- Seeds live in run manifests only. The model never receives one.

The coached game is therefore a single game on a different seed from the panel. It
demonstrates that the system can beat the game; it does not estimate a win rate.
The repository says "unattended win rate unmeasured" wherever that matters.

## Disclosure rules

Every number in the README, `docs/results.md` and `benchmarks/results/` traces to
a file under `evidence/`. Specific disclosures that must accompany the results:

- The recorded run was supervised: adapter fixes, prompt clarifications, reviewed
  continuations and extended limits were applied between segments. No uncertain
  game mutation was replayed and no trajectory was edited. Segment boundaries and
  SHA-256 hashes are in `evidence/astra-low-2K9H9HN/segments.json`.
- The model chose 353 of 383 recorded decisions; the other 30 were automatic
  cashouts. No decision was delegated to a heuristic policy.
- An earlier high-effort run of a previous version of the system is archived under
  `evidence/first-win/` with its own write-up. It is not part of the results and
  is not used by the benchmark builder.
- The scoring engine uses approximations for random effects. Its exactness is
  reported on the hands where the outcome is deterministic and visible.
- Baseline manifests carry `git_revision`; the corresponding source is in this
  repository's history before commit `99cf692`, which removed the simulator and
  heuristic policies when the product was rewritten around the coach.

## What the benchmark builder does

`python -m benchmarks` reads `evidence/` and writes `benchmarks/results/`:

- `results.json` and `results.md`: Table A (real-game results per policy),
  Table B (scoring-engine exactness), Table C (decision sources, phases and action
  mix of the recorded run). Rendering is deterministic and CI fails if a rebuild
  changes either file.
- `figures/`: ante reached per game by policy, and chips scored against the blind
  requirement in the recorded run.

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

## Speed

Every model call in the recorded run took about ten seconds, and profiling on
recorded states showed the local work (analysis about 15 ms, encoding about 1 ms)
is negligible: the time is the Codex call. Two things drive it, the size of the
packet the model must read and the number of calls per game. Both were reduced
after the recorded run, and both reductions are verified offline; the wall-clock
effect is not measured until a new game is played.

| Measured on the recorded run | Value |
|---|---|
| Packet on the wire, median | 23.3 KB, of which the two deck lists were 62 percent |
| Model calls | 357 for 384 decisions |
| Decisions in the shop | 207, including 72 rerolls and 30 shop exits |
| Boss-blind selections | 10, each a forced move with one legal action |

What changed:

- **Compact card codes.** Deck lists are sent as codes such as `KH+steel*red`
  instead of one dictionary per card. The encoding is lossless and its legend is
  part of the fixed instructions. Re-encoding the 357 recorded packets is a test in
  `tests/test_packet.py`, which prints the before and after sizes.
- **Forced moves.** When exactly one legal action exists, the runner takes it and
  reports it in the next packet. In the recorded run that applies to boss-blind
  selection only.
- **Follow-up chains.** A reply may carry up to six follow-up shop actions, with
  items referenced by key, and a bounded reroll loop with a money floor and a
  stop list of wanted items. Each follow-up is validated against fresh state
  before it runs; the chain stops silently at the first problem and the next
  packet says why. Hand actions are never chained, because the hand changes after
  every play.

The stable instructions come first in every request and are byte-identical within
a run, so the service-side prompt cache can reuse them. Persistent Codex sessions
were tried and rejected because the app-server ignores the isolation flags that
keep personal configuration out of the model's context.

## What is deliberately absent

No game simulator, no training, no policy ensemble, no automatic fallback player,
no retries of uncertain game actions, and no direct model API client. Model
access is the user's own Codex CLI signed into ChatGPT. Per-decision token and
cost accounting was not recorded for the evidence runs, so none is reported.
