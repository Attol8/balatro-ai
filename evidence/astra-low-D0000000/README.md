# Astra-low visible run on the baseline seed: D0000000

Cleared Ante 8, continued in endless mode, lost at the Ante 10 boss The House.
Peak single hand 1,840,907 chips. Recorded totals over the whole game: 315
decisions, 265 coach requests, 34 chained follow-up actions, 5 forced moves,
0 rejected replies, 5 model-call timeouts retried, 1 game-reply timeout recovered
in place, 3,211.6 active seconds. `won=true` and `ante_8_cleared=true` record the
win; `status=lost`, `reason=endless_game_over` record how endless play ended.

Real Red Deck / White Stake / all-unlocked profile, BalatroBot in fast mode with
the game window visible, `gpt-6-astra` at low reasoning effort through the Codex
CLI signed into ChatGPT. The seed was set by the operator to D0000000, the first
seed of the twenty-seed development panel used by every heuristic baseline in
`evidence/baselines`, and was withheld from the model as always.

## The same seed, other players

Every non-model policy in the baseline panel played this exact seed:

| policy | ante reached | peak hand |
|---|---|---|
| search-v5 | 6 | 14,700 |
| build-first | 5 | 5,775 |
| strategic (both panels) | 5 | 6,162 |
| search-v6 | 4 | 5,872 |
| search, search-v2, search-v3, search-v4, search-planets | 4 | 4,968 |
| search-v7 | 4 | 4,104 |
| baseline-v1 | 2 | 1,158 |
| **Astra low + tools (this run)** | **10, Ante 8 cleared** | **1,840,907** |

Source: the per-game rows for seed D0000000 in `evidence/baselines/*/summary.json`.
One seed is not a rate, but on this seed the gap between the model and the best
heuristic is four antes and two orders of magnitude in peak hand.

## What happened

- Ante 1: skipped the big blind for a tag, cleared The Goad with a 1,920 hand.
- Antes 2 to 5: Raised Fist, Wily Joker, Throwback, then Bootstraps and Rocket
  turned cash into Mult and income; the model held 79 dollars entering Ante 5.
- Ante 7: Zany Joker, Baseball Card, Bull and Blackboard joined; The Mouth boss
  fell to a single 743,580 hand against 70,000.
- Ante 8: cleared, with the run's peak hand of 1,840,907 scored during the ante.
- Endless: Hologram and DNA replaced Throwback and Rocket. Lost to The House at
  Ante 10 with 1,120,000 required and 232,367 scored over four hands.

## Segments

`segments.json` orders the four segments with SHA-256 hashes of the uncompressed
files. Counters in `result.json` are cumulative. Each trajectory holds only its own
segment's events; the runner rebuilt history at every resume (`continuation_of`).

| segment | runner revision | why it ended | ante at end |
|---|---|---|---|
| 00 | f23a1f6 | the mod's reply to a mutation exceeded the client's 5 s limit; the runner stopped as designed | 7 |
| 01 | 03ade6c | the same, at 30 s, on a pack pick from a tag | 9 |
| 02 | e82a6a6 | the operating system killed every background process for low memory, game included; `result.json` was reconstructed from the trajectory on resume and is marked `reconstructed` | 10 |
| 03 | 184e1e0 | game over in endless at Ante 10 | 10 |

Segment 02 ended with the game process itself gone. Balatro had autosaved the run,
and BalatroBot's `load` endpoint restored it from that save file; the restored
state differed from the last recorded transition in money (160 against 154) and a
few shop and hand-level fields, which the resume recorded (`resume_adjusted`,
`resume_diff` in the segment 03 manifest) before continuing. No game state or
trajectory was edited by hand.

Runner changes between segments, all on the transport side: the client allows
60 seconds for a game reply (03ade6c, e82a6a6); a reply timeout is resolved by
reading the live state, re-sending only when it is unchanged (e82a6a6), which
fired once in segment 03 and worked; a missing result is reconstructed on resume
(184e1e0). The strategy library, prompt, scorer and rules were identical
throughout.

## Recording

The whole game was screen-recorded at 1080p with the game window on the left and
the live `balatro watch` dashboard on the right. The full recording is 69 minutes
and is not stored in the repository. `recording-timelapse.mp4` and
`recording-timelapse.gif` are compressed time-lapses of it, and
`dashboard-final.png` is the dashboard at game over.

## Caveats

- One game on one seed. Not a win-rate estimate.
- Supervised in the sense above: the operator watched the run and restarted the
  runner process three times. The model was never given hints, corrections or
  extra information.
- The run includes an operating-system kill and an autosave restore. The restore
  is disclosed above and in the manifests; the reconstructed segment result is
  marked as such.
