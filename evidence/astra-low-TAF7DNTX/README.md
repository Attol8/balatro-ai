# Astra-low headless run: TAF7DNTX

Cleared Ante 8, continued in endless mode, lost at the Ante 13 boss. Peak single
hand 134,231,931,235 chips. Recorded totals over the whole game: 456 decisions,
404 coach requests, 31 chained follow-up actions, 13 forced moves, 8 rejected
replies corrected on the next call, 15 model-call timeouts retried, 5,882.7
active seconds. `won=true` and `ante_8_cleared=true` record the win;
`status=lost`, `reason=endless_game_over` record how endless play ended.

Real Red Deck / White Stake / all-unlocked profile, BalatroBot in fast headless
mode, `gpt-6-astra` at low reasoning effort through the Codex CLI signed into
ChatGPT. The seed was chosen by the game and withheld from the model. The model
selected every strategic action; the runner acted alone only on the 34 automatic
cashouts, the 13 forced moves where a single legal action existed (boss-blind
selection), and the 31 follow-up actions the model spelled out in its own replies.

## What happened

- Ante 1: skipped the small blind for an Investment Tag, then cleared the big
  blind and The Window boss.
- Antes 2 to 5: built Photograph with Hanging Chad and Fortune Teller, cleared The
  Plant at Ante 5 with a 49,794 hand against 22,000.
- Ante 6: bought Brainstorm and Hologram; The Wheel fell to 110,793 against 40,000.
- Ante 8: small blind 936,499 against 50,000, big blind 1,945,681 against 75,000,
  boss Crimson Heart 180,442 against 100,000. Ante 8 cleared.
- Endless: Steel Joker over four Steel cards, then Blueprint replacing Mail-In
  Rebate and Card Sharp replacing Ramen. Ante 10 boss The Fish, Ante 11, Ante 12.
  Peak hand at Ante 13. Lost to The Tooth at 94,000,000,000 required with
  1,026,133,011 scored over four hands and 10 dollars in debt from its penalty.

## Segments

`segments.json` orders the five segments and records SHA-256 hashes of the
uncompressed `trajectory.jsonl`, `manifest.json` and `result.json` in each.
Counters in `result.json` are cumulative across segments. Each trajectory holds
only its own segment's events; the runner rebuilt its history from the previous
segment at every resume (`continuation_of` in the manifests) and the live game
state matched the last recorded transition exactly every time
(`resume_adjusted: false`).

| segment | runner revision | why it ended | ante at end |
|---|---|---|---|
| 00 | 5be6735 | one Codex call exceeded the 180 s cap; the runner then treated that as fatal | 2 |
| 01 | a18c279 | interrupted by the operator during a model call to lower the per-call cap to 60 s | 5 |
| 02 | 90c721e | three consecutive Codex stalls on one decision exhausted the retry budget | 6 |
| 03 | 1d6238a | interrupted by the operator during a model call to deploy hedged calls | 6 |
| 04 | af7d312 | game over in endless at Ante 13 | 13 |

Every stop and resume happened while the runner was waiting for the model, so no
game action was in flight. No game state was edited, no trajectory was edited and
no uncertain mutation was replayed. Between segments the operator changed only
the runner: eight-character request ids after the model dropped two characters
copying a long one (cf3bd63), a reworded prompt paragraph making chained shop
replies the default (23ae329), retry of timed-out model calls and the resume
command itself (a18c279), captured Codex output (90c721e), six retry attempts
with a pause (1d6238a) and hedged calls (af7d312). The strategy library, scorer
and game rules were identical throughout.

## Caveats

- One game on one seed. It is not a win-rate estimate.
- Supervised in the sense above: the operator watched the run and restarted the
  runner process four times. The model was never given hints, corrections or
  extra information, and the game was never paused inside a blind.
- The model's own replies were rejected eight times (one mistyped request id, seven
  illegal actions such as shop slots that did not exist or actions from the wrong
  phase) and corrected on the next call; those calls are included in the totals.
- The Codex service stalled on about one call in ten. Fifteen calls hit the cap
  and were retried. In the final segment the hedge fired sixteen times and the
  second process won fourteen of them. Per-decision latency figures from this run
  reflect those stalls.
