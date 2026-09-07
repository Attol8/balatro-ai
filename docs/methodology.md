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
- The coached wins used seeds 2K9H9HN and TAF7DNTX, chosen by the game, outside
  that panel.
- Seeds live in run manifests only. The model never receives one.

The coached games are therefore two single games on different seeds from the
panel. They demonstrate that the system can beat the game; they do not estimate a
win rate.
The repository says "unattended win rate unmeasured" wherever that matters.

## Disclosure rules

Every number in the README, `docs/results.md` and `benchmarks/results/` traces to
a file under `evidence/`. Specific disclosures that must accompany the results:

- The recorded run was supervised: adapter fixes, prompt clarifications, reviewed
  continuations and extended limits were applied between segments. No uncertain
  game mutation was replayed and no trajectory was edited. Segment boundaries and
  SHA-256 hashes are in `evidence/astra-low-2K9H9HN/segments.json`.
- In the 2K9H9HN run the model chose 353 of 383 recorded decisions; the other 30
  were automatic cashouts. In the TAF7DNTX run it chose 409 of 456, 31 of them as
  chained follow-ups; 34 were automatic cashouts and 13 forced moves with a single
  legal action. No decision was ever delegated to a heuristic policy.
- The TAF7DNTX run was played headless and the runner process was stopped and
  resumed four times while waiting for the model, to deploy the retry, resume and
  hedging fixes described below. Every resume verified that the live game matched
  the last recorded transition. The model received no hints or corrections.
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
BALATROBOT_ALL_UNLOCKED=1 uvx balatrobot serve --fast --headless --logs-path runs/logs
for n in $(seq -w 0 19); do
  balatro play --seed D00000$n --output runs/astra-low-panel/D00000$n \
    --max-calls 450 --max-actions 750 --seconds 7200 --call-seconds 60
done
python -m benchmarks --runs runs/astra-low-panel/*
```

Those are the shipped defaults and cover a full endless game; an Ante 8 win needs
fewer. A run stopped part-way is continued with `balatro play --resume DIR
--output NEWDIR`, which rebuilds the history from the recorded trajectory and
verifies the live game against the last recorded transition before acting.

Rows are grouped by requested model and reasoning effort from the manifests.
Report the panel, the number of games, and whether any run was interrupted or
continued. Restarts are part of the result, not a detail to tidy away: say how
many segments a game took, why each restart happened, and report each manifest's
`resume_adjusted` so a reader knows whether any resume had to adopt a live state
that had moved on. Do not pool partial panels with complete ones without saying so.

## Speed

Every model call in the first recorded run took about ten seconds, and profiling
on recorded states showed the local work (analysis about 15 ms, encoding about
1 ms) is negligible: the time is the Codex call. A trivial one-word Codex call
takes about 4.6 seconds on its own, so roughly half of each decision is fixed
round-trip cost. Two things remain to work on: the size of the packet and the
number of calls per game. The headless TAF7DNTX run measured the result: calls the
service answered promptly took about nine seconds, and 404 calls covered 456
decisions.

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

Service stalls turned out to matter more than packet size. In the headless run the
Codex service intermittently never started answering, on roughly one call in ten,
with the process idle and no error. Three mechanisms now keep a game alive
through that, all on the model-call side and never touching the game:

- **Retry.** A timed-out model call is re-asked with a fresh request id, up to six
  attempts per decision with a pause from the second retry, within the run budget.
- **Hedging.** If a call has not answered after twenty seconds, a second identical
  process starts and the first valid answer wins. In the headless run the hedge
  fired sixteen times and the second process won fourteen.
- **Private Codex home.** The child runs from an empty home linked only to the
  login file, so the CLI never scans the user's session history at startup.

`balatro play --resume DIR` continues an interrupted game from its recorded
trajectory after verifying the live state, which is how the headless run was
carried across runner restarts without touching the game.

## What is deliberately absent

No game simulator, no training, no policy ensemble, no automatic fallback player,
no retries of uncertain game actions, and no direct model API client. Model
access is the user's own Codex CLI signed into ChatGPT. Per-decision token and
cost accounting was not recorded for the evidence runs, so none is reported.
