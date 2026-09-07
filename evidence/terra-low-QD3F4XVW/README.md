# Terra-low supervised run: QD3F4XVW

Lost at the Ante 2 boss The Mouth with 356 chips against 1,600. Peak single hand
616 chips. Recorded totals: 36 decisions, 30 coach requests, 1 chained follow-up,
2 forced moves, 0 rejected replies, 0 model-call timeouts, 1 game-reply timeout
recovered by reading the live state, 532.7 active seconds, 0 restarts.
`status=lost`, `reason=endless_game_over`, `won=false`.

Real Red Deck / White Stake / all-unlocked profile, BalatroBot with the game window
visible at game speed 2 and 60 fps animations, `gpt-5.6-terra` at low reasoning
effort through the Codex CLI signed into ChatGPT, selected with the new `--model`
flag. Everything else, prompts, tools, limits and the supervisor, is identical to
the `gpt-6-astra` run on the same seed in `evidence/astra-low-QD3F4XVW`, which
cleared Ante 8 and reached Ante 11. The seed QD3F4XVW was set by the operator and
withheld from the model. Played end to end by `balatro supervise` with no operator
intervention and the `balatro watch` dashboard beside the game; not screen recorded.

## What happened

- Ante 1: skipped the Small Blind for the Charm Tag; the Mega Arcana Pack held The
  Soul, which became Triboulet (Kings and Queens give X2 Mult when scored), and
  Strength was used on two cards. Cleared the Big Blind with 706 and The Hook with 616.
- Ante 2: skipped the Small Blind, cleared the Big Blind with 1,568, bought a
  Standard Pack and a Negative Arrowhead. Against The Mouth, which allows one hand
  type for the round, the first play was a single King for 30 chips, locking the
  round to High Card. Single Kings and Queens through Triboulet then scored 130,
  66 and 130. Game over at 356 of 1,600 with 20 dollars unspent.

Per model call: median 10.9 seconds, p90 18.3 seconds, in line with the astra run
on this seed. The game was quicker only because it was shorter.

## Segments

One segment. `segments.json` records its SHA-256 hashes; `supervisor.json` and
`summary.json` are the supervisor's own records. `dashboard-final.png` is the
dashboard at game over. No operator action, no game state edit, no trajectory edit.

## Earlier attempts on this seed

Two earlier attempts with the same model on the same evening were ended by runner
faults that only appear at visible game speeds, all fixed before this game:

- `evidence/terra-low-QD3F4XVW-attempt1`: lost at the Ante 2 boss The Mouth after
  the runner selected the boss while a skip tag's Mega Buffoon Pack was still
  opening, so that pack was never offered. The loss itself was the model's play.
- A second attempt was stopped by the operator at Ante 1 after the runner forced a
  pack skip on a pack whose cards had not been dealt yet. It has no outcome and is
  not kept as evidence.

## Caveats

- One game on one seed. Not a win rate, and not a model ranking: it is one game per
  model on one seed, at one reasoning effort.
- The model is not the only thing that differs from the astra run: this game ran on
  the runner revision that includes the visible-speed fixes above.
