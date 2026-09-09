# Black Deck / Gold Stake results

On 9 September 2026, GPT-6 Astra at low reasoning effort cleared Ante 8 on two
fresh random seeds in the native Balatro game. Both used public-information
numerical tools, BalatroBot automation and an all-unlocked profile.

| Run | Final boss score / required | Hands left | Peak hand | Completed actions | Model requests |
|---|---|---|---|---|---|
| [MSVP7ABY](../evidence/astra-black-gold-MSVP7ABY/README.md) | 435,408 / 400,000 | 1 | 247,230 | 264 | 220 |
| [PI4T2AH8](../evidence/astra-black-gold-PI4T2AH8/README.md) | 420,305 / 400,000 | 1 | 227,383 | 270 | 227 |

Each final native observation records `won=true` and eight antes cleared. The
runner stops after the Ante 8 victory, at the cash-out screen; `ROUND_EVAL` and
Ante 9 in the final observation do not mean an endless game was played.

These two successful attempts are not the complete development history or a
win-rate estimate. An earlier policy lost to Ante 5 Needle at 17,958 / 25,000;
that failure motivated general boss-readiness improvements before these wins.
No claim of optimal play, guaranteed wins or exhausted improvement opportunities
is supported. The separate Red/White benchmarks are unchanged.

## Rules played

Black Deck gives one extra Joker slot and one fewer played hand per round:
normally six Joker slots and three hands. Gold Stake includes all lower-stake
penalties: Small Blind has no blind reward money; ante requirements scale faster
from Green and Purple; Blue removes one discard; Black introduces Eternal
Jokers that cannot be sold or destroyed; Orange introduces Perishable Jokers
that become debuffed after five rounds; Gold introduces Rental Jokers costing
$3 per round. Normally this combination starts with two discards. Vouchers and
other legal effects can subsequently change resources. No Small Blind reward
does not remove interest or unused-hand income.

These rules were checked against the installed game's English localization and
the recorded BLACK/GOLD settings. See also the [stake reference](https://balatrowiki.org/w/Stakes?mobileaction=toggle_view_desktop).

## What the fair-play evidence supports

- Each trace begins with exactly one `start` call specifying only BLACK/GOLD,
  with no seed supplied. The game generated the seed; it was withheld from the
  model. No seed search or future-offer inspection was used for these attempts.
- Logged RPCs contain ordinary gameplay actions, with no `set`, `load` or `eval`
  calls. All 534 completed actions across the two games pass the local legality
  audit. Every continuation records `resume_adjusted=false` and an empty diff.
- The information adapter removes seeds and draw order, represents remaining
  cards as unordered counts and hides face-down identities. Coach requests contain
  neither run seed nor RNG-state/draw-order fields. The decision subprocess has
  shell, web, app and other external tools disabled. Numerical advice uses public
  state; the bot is not a vision-only or unaided language-model player.
- The profile bypasses content unlock progression and exposes the full unlocked
  content pool. The inspected unlock function changes discovery/unlock flags,
  not money, cards or hands. Tutorial skipping and rendering/speed settings are
  also enabled as appropriate. Lovely, Steamodded and BalatroBot are installed.
  This is a modded benchmark setup, not an unmodified client or fresh-account
  achievement run.
- The first game has two same-game budget continuations and four recovered
  model timeouts. The recorded game has one same-game transport recovery after
  a slow animation exceeded the original timeout. Increasing the RPC timeout
  and container CPU allowance did not change decisions or reset the game.

These are self-recorded traces and local audits, not tamper-proof external
certification or an exhaustive review of every installed Lua patch. They support
legitimate gameplay under the disclosed setup; they do not prove every possible
implementation defect absent.

## Scoring limitations and recording

The first win's frozen audit contains two fractional score differences; a
post-run correction to final-score flooring produces 34 supported matches, with
three hidden-state plays excluded. Both original and corrected audits are kept.
The recorded win has 44 matching plays and three one-chip overestimates consistent
with native Ramen floating-point decay. Those differences remain visible in its
audit; neither the native scores nor original traces were edited.

The second run was recorded entirely inside a private Docker virtual display.
Its 14:05 silent H.264 export keeps all actions at labelled 6.787× playback with
recorded explanations alongside, followed by a five-second outcome card. The
central cursor is hidden. The full original capture lasts 95:25. Media is kept
locally rather than adding large MP4s to Git; the full compressed traces and
outcome evidence are archived here. [Recording/export workflow](virtual-recording.md).
