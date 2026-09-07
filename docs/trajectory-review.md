# Learning from seed 2K9H9HN

The Astra-low run cleared Ante 8 and lost at Ante 11's Big Blind. Its final hand
scored **1,239,454**, but five hands totaled **3,350,514 / 10,800,000**. The
7,449,486 shortfall is a build ceiling, not a small ordering error. Baseline
commit **99cf692** preserves the working player and complete original evidence.
This was a supervised development run with interruptions/recoveries, not an
unattended benchmark. The objective changed to endless only after Ante 8;
earlier survival choices should be judged against their original objective.

## What worked

The player built a consistent High Card strategy, used Steel and seals, and
assembled Holographic Stuntman, Fortune Teller, Foil Card Sharp, Ramen and
Polychrome Baseball. It raised High Card to level 8 and preserved four Steel
cards for its final Glass-card play. The final Joker order was sensible:
additive contributions preceded the main multiplicative effects. Card Sharp
and Ramen supplied Baseball's uncommon triggers. Blueprint was never offered.

## A real numerical bug

Fortune Teller's public tooltip showed its current Mult, but the adapter did
not populate its runtime. The scorer already supported generic current Mult;
the missing input understated 22 recorded plays. For example, the final
prediction was approximately 913,100 instead of 1,239,454. Reading the visible
`Currently +47` value fixes this without accessing private state.

Across 49 recorded plays, 47 have visible Joker identities. With the public
Fortune Teller correction, 46 of those match the observed score exactly after
flooring. The remaining hand contains a Lucky card retriggered by Hanging Chad;
random Lucky Mult is deliberately omitted. Two Amber Acorn hands are excluded
because Joker identities were hidden. This validates this trajectory's covered
mechanics, not every Joker or future build. The corrected scorer still cannot
make the final build reach 10.8 million.

## Actual offers worth reconsidering

Locations below are zero-based JSONL event indices in the compressed original
segments under [the evidence bundle](../evidence/astra-low-2K9H9HN/segments).
These are alternatives supported by information visible at the time, not proof
that a different purchase would have won.

| Offer | Recorded location | Public support and tradeoff |
|---|---|---|
| Mime, $5 | 05:95, remained until 05:111; again 05:149 | Five Steel cards already existed. Replacing Holographic Cloud 9 retains an uncommon Baseball trigger and adds held-card retriggers, but loses +10 Mult and $6 income per round. Strongest missed engine. |
| Hanging Chad, free pack choice | 06:43 | Justice was held, so a Glass scoring-card line was available. Replacing a mature Joker costs reliable output; breaking/drawing Glass remains a risk. |
| Baron, $8 | 06:107 and 06:245 | Five Kings including a red-seal Steel King. Offers held-card scaling, but five Kings alone do not guarantee a good draw or justify losing Fortune Teller's reliable Mult. |
| Constellation / Hologram | 03:231 / 04:27 | Uncommon growing multipliers fit Baseball and visible planet/card purchases. They began at X1 and required future investment; less certain than Mime. |
| Photograph, $5 | 05:45–69 | A face High Card could trigger X2, but Chad had already been sold. A possible pivot, not an automatic upgrade. |

The player spent $96 on 14 rerolls in Ante 4 and $42 on 10 in Ante 10.
Searching for a copier/growing multiplier while passing compatible engines is
more actionable than simply asking it to reroll more. Full slots prevented
immediate purchase actions, but should not hide the strategic offer. New advice
surfaces conditional engine opportunities and the need to sell, reobserve, then
buy. It does not choose the sale or fabricate an immediately legal purchase.

Targeted Tarot/Spectral choices shown while a pack's hand was still empty are
not counted as strategic misses: the observed state did not permit targets.
That delayed-draw observation issue is a separate limitation of the saved run.

## How to aim substantially higher

A coherent held-card build combines useful Kings, Steel and retriggers, with
sufficient hand size and reliable draws. Baron/Mime is a conditional direction,
not a mandatory shopping list. This matches the community's
[Baron/Mime build guide](https://balatrolab.com/en/guides/baron-mime-steel-kings).
The run already had part of the deck needed for that direction.

Multiplier timing matters: Steel/Baron trigger before main Joker additive Mult.
Fortune Teller's +47 therefore does not get multiplied by earlier held effects.
Planets and played-card Mult improve that earlier base. Stuntman's reduced hand
size can also become expensive once each additional held card multiplies score.

For an alternative played-card build, Glass or Photograph plus retriggers can
replace a mostly fixed Joker multiplier chain. Photograph on the first scoring
face with two Chad retriggers gives three X2 applications, or X8, before other
effects. This requires the right scoring card, ordering and boss conditions.

Copiers amplify either effects or retriggers. Balance them using the current
inventory: one Steel red-seal King with Baron/Mime/Blueprint receives eight
factors of 1.5 when Blueprint copies Mime, versus nine when it copies Baron.
That specific comparison is explained in a
[player calculation](https://www.reddit.com/r/balatro/comments/1cziphz/does_blueprint_go_next_to_mime_or_baron/);
it is not a universal rule about where Blueprint belongs. Mechanics were also
checked against the installed game's `card.lua` held-card, repetition and Joker
scoring branches. No proprietary game source is included here.

Deck construction is the immediate improvement: duplicate useful enhanced/sealed
cards, remove cards that obstruct the chosen engine, and level the hand actually
played. Starting-deck selection is a separate future comparison. The product
currently validates Red Deck only. Ghost could support enhancement construction;
Abandoned removes the faces required by Baron/Photograph; Plasma changes scoring
and blind scaling and needs explicit adapter/scorer coverage before support.
No alternative deck is claimed tested or enabled by this change.

## Implemented and untested scope

The adapter now reads Fortune Teller's displayed Mult. Public analysis exposes
relevant visible engine offers, including full-slot cases; the coach gets concise
replacement, scoring-phase, retrigger, deck-building and endless guidance.
Astra low remains responsible for every strategic choice through standard Codex.

Offline regression tests use the saved trajectory. No new game, gameplay model
call or live performance evaluation was run. Higher scores remain a hypothesis
until a separately authorized run tests these changes.
