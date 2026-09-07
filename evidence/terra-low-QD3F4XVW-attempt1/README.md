# Terra-low supervised run, first attempt: QD3F4XVW

Lost at the Ante 2 boss The Mouth with 496 chips against 1,600. Peak single hand
1,440 chips. Recorded totals: 19 decisions, 67 coach requests, 31 rejected replies,
2 forced moves, 0 model-call timeouts, 1 game-reply timeout recovered, 599.0 active
seconds, 1 operator interruption and resume. Same setup as
`evidence/terra-low-QD3F4XVW`: `gpt-5.6-terra` at low reasoning effort, game
visible at speed 2, `balatro supervise`, seed withheld from the model.

This game is kept because its outcome is real but confounded by a runner fault.
Read it with the caveats below; `evidence/terra-low-QD3F4XVW` is the clean game.

## What happened

- Ante 1: skipped the Small Blind for the Charm Tag. The runner observed the
  blind-select screen before the Mega Arcana Pack had opened and re-asked the
  same stale observation 31 times while the game refused every reply (segment 00).
  The operator interrupted the runner, fixed it to re-read the live state after a
  refusal, and resumed; the resume adopted the open pack (segment 01). The model
  took The Soul, which became Triboulet, and Strength, skipped the Big Blind too,
  and cleared The Hook with a 1,440 hand.
- Ante 2: skipped both the Small and the Big Blind. The Big Blind's tag opens a
  Mega Buffoon Pack; the runner again observed blind-select before the pack opened,
  and with only the boss left it selected the boss as the sole legal action while
  the pack was opening. The pack stayed open on screen, unplayable, and the model
  never saw it. Against The Mouth the model opened with a 496 two pair, then played
  single cards, which score nothing once another hand type is locked, until the
  hands ran out.

## Segments

| segment | why it ended | ante at end |
|---|---|---|
| 00 | operator interruption during the stale-observation loop | 1 |
| 01 | resumed from 00 with the live pack adopted (`resume_adjusted`), played to game over | 2 |

No game state edit, no trajectory edit. The runner was changed between the segments.

## Caveats

- The Mega Buffoon Pack the model earned at Ante 2 was never offered to it, so it
  faced the boss with one joker where it could have had up to three.
- The Ante 2 plays after the first hand were the model's decisions: the boss effect
  was in every observation and the model's own plan named the constraint.
- Both faults are fixed in the runner: a skip whose tag opens a pack now waits for
  the pack, a pack is never treated as settled while its cards are being dealt, and
  a refusal re-reads the live state before asking again.
