# Astra-low supervised run, recorded: QD3F4XVW

Cleared Ante 8, continued in endless mode, lost at the Ante 11 boss The Plant.
Peak single hand 7,052,918 chips. Recorded totals: 473 decisions, 388 coach
requests, 50 chained follow-up actions, 6 forced moves, 0 rejected replies, 3
model-call timeouts retried, 0 game-reply timeouts, 6,022.9 active seconds,
1 automatic restart by the supervisor. `won=true` and `ante_8_cleared=true` record
the win; `status=lost`, `reason=endless_game_over` record how endless play ended.

Real Red Deck / White Stake / all-unlocked profile, BalatroBot with the game window
visible at game speed 2 and 60 fps animations, `gpt-6-astra` at low reasoning
effort through the Codex CLI signed into ChatGPT. The seed QD3F4XVW was set by the
operator and withheld from the model. This is the first game played end to end by
`balatro supervise` with no operator intervention, and the first recorded with the
game and the `balatro watch` dashboard side by side for the whole game.

## What happened

- Ante 1 to 3: Onyx Agate and Hack, then Golden Joker and Arrowhead, a Club build.
- Ante 4 to 6: a Negative edition gave a sixth slot; Even Steven, Ceremonial Dagger,
  then Hanging Chad and Burnt Joker came and went; Smeared Joker made Spades count
  as Clubs. The Fish at Ante 6 fell to a 61,557 hand against 40,000.
- Ante 8: Photograph bought in the last shop before the boss; Cerulean Bell, which
  forces a card into every hand, cleared with 111,598 against 100,000.
- Endless: Hieroglyph and later Petroglyph each lowered the ante by one to buy more
  rounds of income; Constellation replaced Hack and grew with every Planet;
  Blackboard replaced Onyx Agate. Peak 7,052,918 at Ante 11. Lost to The Plant at
  14,400,000 required with 7,394,177 scored over five hands, one of them the run's peak.

## Segments

`segments.json` orders the two segments with SHA-256 hashes of the uncompressed
files; `supervisor.json` and `summary.json` are the supervisor's own records.

| segment | why it ended | ante at end |
|---|---|---|
| 00 | the mod refused a boss reroll ("requires Retcon or unused Director's Cut") that the runner's legality had allowed after the ante-lowering vouchers; the runner recorded an error | 11 |
| 01 | resumed automatically two seconds later by the supervisor, live state verified (`resume_adjusted`: round and blinds), played to game over | 11 |

No operator action, no game state edit, no trajectory edit. The refusal was a
legality mismatch on one corner case and has since been turned into a rejected
action that the model is asked to correct, instead of a run-ending error.

## Recording

The whole game was screen-recorded at 1080p with the game window on the left and
the live dashboard on the right, in one continuous take of 101 minutes. The full
recording is kept outside the repository. `recording-timelapse.mp4` and
`recording-timelapse.gif` are compressed time-lapses of it, `final-frame.jpg` is
the last frame with the game-over card beside the dashboard, and
`dashboard-final.png` is the dashboard at game over.

## Caveats

- One game on one seed. Not a win-rate estimate.
- Unattended in play: the operator started the supervisor and watched. The model
  was never given hints, corrections or extra information; the one restart was
  automatic and verified against the live game.
