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

## Rule-by-rule audit of the recorded win

A second independent trace review and direct inspection of the Downloads 2× video
confirmed the following for PI4T2AH8. Video timestamps below refer to
`black-deck-gold-reddit-2x.mp4`; sticker offers pass quickly at this speed.

| Rule | Recorded evidence |
|---|---|
| Black Deck: +1 Joker slot, −1 hand | At 00:02.1 the native HUD shows six slots, three hands, two discards and the Black Deck back. All 270 transitions retain BLACK/GOLD. |
| Red: no Small Blind reward | At 00:10 cashout pays only $2 for two unused hands. Trace money increases $4 → $6, with no blind prize. |
| Green/Purple: increased targets | All eight Small Blind targets match native highest-stake scaling: 300; 1,000; 3,200; 9,000; 25,000; 60,000; 110,000; 200,000. Final boss requires 400,000. |
| Black: Eternal Jokers | At 00:18.5 the pack offers Eternal/Rental 8 Ball; the trace also records Eternal The Tribe in a shop. |
| Blue: −1 discard | Opening HUD and ordinary blind starts have two discards. The Water correctly removes both. |
| Orange: Perishable Jokers | At 01:04.7 the pack offers Ice Cream with a Perishable sticker; the trace records five rounds remaining. Diet Cola later appears with the same penalty. |
| Gold: Rental Jokers | Rental Stencil costs $1 and charges $3 on each of ten completed rounds (rounds 4–13), stopping after sale. First charge changes $11 → $8 before cashout. |

The bot never acquired an Eternal or Perishable Joker. Their offers confirm the
mechanics were present; this run does not demonstrate unsellability or expiration.
Avoiding those offers is legal. Gold does not require buying every sticker type.

The fourth hand later in the video comes from purchasing Grabber; increased hand
size comes from Paint Brush. Chicot legally disables Amber Acorn's special effect,
while its 400,000 target remains. The native final score is 420,305, with one hand
unused. These changes do not waive the deck or stake rules.

The additional 2× export lasts 422.5 seconds. Its embedded speed label still says
6.787× from the original export; actual gameplay playback is approximately
13.575×. This is a presentation-label discrepancy, not a change to gameplay.

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
