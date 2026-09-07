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

# Headless run TAF7DNTX

The second recorded run cleared Ante 8 and continued in endless to the Ante 13
boss. Locations below are `segment:index`, zero-based JSONL event indices in the
compressed segments under [the evidence bundle](../evidence/astra-low-TAF7DNTX/segments);
the bundle's [README](../evidence/astra-low-TAF7DNTX/README.md) records how the run
was supervised. One caveat on reading state: the recorded `ante` counter
increments the moment a boss falls, so a boss blind's own cash out is stamped
with the following ante. Per-ante figures below use that recorded stamp and say
so where it matters.

456 decisions, 404 coach requests, 40 hands played, 33 discards, 73 rerolls,
45 consumables used, 4 blinds skipped, 8 rejected replies, 15 model-call
timeouts.

## Build timeline

| Location | Ante | Change | Cost |
|---|---|---|---|
| 00:34 | 1 | buy Foil Mail-In Rebate | $6 |
| 00:42 | 1 | Buffoon pick Wrathful Joker | $4 pack |
| 00:74, 00:86 | 2 | Buffoon pick Riff-raff, whose own blind-select effect then made Swashbuckler and Foil Fortune Teller | $4 pack |
| 00:119, 00:123 | 2 | sell Riff-raff, buy Hanging Chad | +$2 / $4 |
| 01:16, 01:22 | 2 | sell Swashbuckler, buy Photograph | +$2 / $5 |
| 03:20, 03:24 | 6 | sell Wrathful Joker, buy Brainstorm | +$2 / $10 |
| 03:44 | 6 | buy **Negative** Hologram (Joker limit 5 to 6) | $12 |
| 04:142, 04:146 | 7 | sell Fortune Teller, buy Ramen | +$4 / $6 |
| 04:176 | 8 | buy **Negative** Steel Joker from the Ante 7 Negative Tag (limit 6 to 7) | $0 |
| 04:432, 04:436 | 10 | sell Mail-In Rebate, buy Blueprint | +$3 / $10 |
| 04:914, 04:918 | 13 | sell Ramen, buy Card Sharp | +$3 / $6 |

Copier placement was deliberate and is stated in the plan text on almost every
call from Ante 6 onward ("Blueprint copies Chad; Brainstorm copies Photograph",
first at 03:18 and 03:38, and in 191 later plans). Brainstorm copies the
leftmost Joker, so three adjacent swaps at 03:28-03:36 moved Photograph to slot
0. Blueprint copies its right-hand neighbour, so five more adjacent swaps at
04:440-04:456 walked Blueprint from slot 6 to slot 1, immediately left of
Hanging Chad. The final order was Photograph, Blueprint, Hanging Chad,
Brainstorm, Hologram, Steel Joker, Card Sharp: Chad's two retriggers of the
first played card were themselves doubled by Blueprint, and every one of those
five triggers re-applied Photograph twice through Brainstorm.

Two Negative purchases, not extra slots bought with cash, are what let seven
Jokers coexist. Hologram reached X3.25 (nine cards added to the deck) and Steel
Joker went from two Steel cards at purchase to nine by Ante 13.

## Money

Money held at each cash out, and the payout:

| Ante (recorded stamp) | Cash outs (held to paid) |
|---|---|
| 1-2 | 4→10, 5→39, 35→46, 34→46 |
| 3-4 | 44→57, 43→54, 39→51, 54→67, 70→86, 69→86 |
| 5-6 | 62→80, 95→112, 88→106, 56→72, 51→68 |
| 7-8 | 60→78, 54→70, 56→74, 51→67, 49→65 |
| 9-10 | 47→67, 59→75, 49→64, 43→59, 40→54, 39→53 |
| 11-12 | 30→44, 14→22, 22→33, 40→56, 22→33 |
| 13 | 2→10, 0→6, 6→14 |

Seed Money was bought at 01:172, raising the interest cap to $10 at $50 held.
The plan text kept a "$50 interest floor" from 01:318, softened it to "when
practical" from 04:150 (Ante 7), and stopped naming interest at all after
04:625. The money curve follows the language exactly: the last eight cash outs
were taken on $30, $14, $22, $40, $22, $2, $0 and $6, paying $6+$2+$4+$8+$4+$0+
$0+$1 = $25 of the $80 those eight rounds could have paid.

The collapse is a single shop. After the Ante 12 Big Blind the run had $33
(04:763) and left with $2 (04:827) after five rerolls costing $1+$2+$3+$4+$5,
three shop cards and two packs. Ante 13 therefore opened on $2. Its first shop
spent the entire $10 on the Observatory voucher (04:847), leaving $0. The Tooth
then took $1 per card played: $6 down to $1, -$4, -$9 and -$10 across the four
final hands (04:948 to 04:960).

Total discretionary spend was $874, of which $424 went on 73 rerolls, by
recorded ante stamp: $29, $37, $70, $71, $45, $36, $27, $22, $27, $22, $33, $5
for antes 2-13. The two heaviest reroll antes, 4 and 5 at $70 and $71, are the
same pattern the seed 2K9H9HN review flagged.

## Blinds, Antes 8 to 13

| Ante | Blind | Requirement | Best hand | Hands used |
|---|---|---|---|---|
| 8 | Small | 50,000 | 936,499 | 1 |
| 8 | Big | 75,000 | 1,945,681 | 1 |
| 8 | Crimson Heart | 100,000 | 180,442 | 1 |
| 9 | Small | 110,000 | 1,964,445 | 1 |
| 9 | Big | 165,000 | 154,297 then 77,375 | 2 |
| 9 | The Head | 220,000 | 8,996,448 | 1 |
| 10 | Small | 560,000 | 9,681,408 | 1 |
| 10 | Big | 840,000 | 3,291,678 | 1 |
| 10 | The Fish | 1,120,000 | 19,766,208 | 1 |
| 11 | Small | 7,200,000 | 294,314,803 | 1 |
| 11 | Big | 10,800,000 | 66,656,494 | 1 |
| 11 | The Serpent | 14,400,000 | 816,195,502 | 1 |
| 12 | Big (small skipped) | 450,000,000 | 634,408,879 | 1 |
| 12 | The Ox | 600,000,000 | 2,853,107,712 | 1 |
| 13 | Small | 47,000,000,000 | 125,384,579,763 | 1 |
| 13 | Big | 70,500,000,000 | 134,231,931,235 | 1 |
| 13 | **The Tooth** | 94,000,000,000 | 951,042,624 (1,026,133,011 total) | 4 |

Every blind from Ante 8 to the Ante 13 Big Blind fell to a single hand except
the Ante 9 Big Blind, where the first hand reached 154,297 of 165,000. Rechecking
that draw with the scorer, the single Jack it played was the best play available
(154,297; the best five-card play scores 51,583), so the second hand was the
draw, not a misplay.

## Rejected replies

Eight replies were rejected and re-asked. One was a stale request id: at 00:101
the model echoed a 30-character id after dropping two characters from the
32-character id sent at 00:99, and the run then replayed the same `play_cards` at 00:105 unchanged. The other seven
were illegal actions, and none of them was an out-of-range or unaffordable shop
slot. Five of the seven are one mistake, taking a Joker with 7/7 slots filled:

| Location | Rejected action | Actual cause | What the model did next |
|---|---|---|---|
| 03:107 | `reorder_hand` | phase was PACK, not SELECTING_HAND | chose the pack card (03:111) |
| 04:553 | `buy_shop_card` 3 (Chaos the Clown, $4, $30 held) | 7/7 Joker slots | left the shop (04:557) |
| 04:656 | `use_consumable` with a hand target | phase was PACK | chose the pack card with the target (04:660) |
| 04:671 | `buy_shop_card` 0 (Wrathful Joker, $5, $40 held) | 7/7 Joker slots | left the shop (04:675) |
| 04:702 | `choose_pack_card` 1 (Joker from a Buffoon pack) | 7/7 Joker slots | skipped the pack (04:706) |
| 04:713 | `buy_shop_card` 3 (Acrobat, $6, $37 held) | 7/7 Joker slots | rerolled (04:717) |
| 04:910 | `buy_shop_card` 1 (Card Sharp, $6, $9 held) | 7/7 Joker slots | sold Ramen, then bought it (04:914, 04:918) |

The correction the model found unaided at 04:910, sell first and then buy, is
exactly the sequence it failed to plan four times before. The other two are
actions from the wrong phase while a pack was open.
`analysis.legal_action_types` did not exist in the runner revisions used for
this run; it does now, and recomputing it on the recorded observations shows it
omits the rejected action type in six of the seven cases. Only 04:713 would
still have slipped through, because a Tarot in the same shop kept
`buy_shop_card` legal while the Joker in slot 3 was not.

## Tags, consumables and packs

Four blinds were skipped for their tags. Ante 1 small blind for the Investment
Tag (00:4), which paid exactly $25 at the boss cash out: $5 to $39 at 00:66,
where the blind reward, three unused hands and $1 interest account for the other
$9. Ante 5 for the Economy Tag (01:344), $55 to $95, the $40 cap. Ante 7 for the
Negative Tag (04:152), which made the Ante 8 Steel Joker free and Negative
(04:176). Ante 12 small blind for the D6 Tag (04:739): the next shop's first
reroll cost $0 (04:771), the second $1.

45 consumables were used: The Hermit 8, Pluto 7, Death 6, The Fool 4, The World
4, Jupiter 4, Temperance 3, The Chariot 3, Earth 2, Justice 2, The Emperor 1,
Strength 1. Four were sold. Planets went almost entirely into Flush, which ended
at level 14 with High Card at level 10. 44 packs were bought, 13 of them
Celestial. The single most valuable consumable in the run is the Strength at
04:833: it raised a Glass Ten to a Glass Jack, and the very next hand (04:841)
scored 2,853,107,712 against The Ox's 600,000,000.

## Offers worth reconsidering

Alternatives supported by information visible at the time, scored with the
project's own scorer against the recorded observation. The scorer reproduces
these hands to within 1% (exactly, at 04:290), so the ratios are sound
even where the absolute figures are not.

| Decision | Recorded location | What the scorer says |
|---|---|---|
| Excluding the red-seal Glass Ten from the first Tooth flush and leading with a Steel Ace | 04:948 | The played hand scored 764,127. Leading the Steel King and including the Glass Ten scores 1,222,760,448, about 1,600x more. The plan at 04:945 says to "retain red-seal Glass TS", so this was a deliberate preservation. |
| Excluding it again from the third Tooth flush | 04:956 | 951,035,904 played against 5,355,237,888 for the best ordering of the same eight cards, 5.6x. |
| Selling Justice for $1 to make room for Death | 04:807 | Justice makes a selected card Glass, the exact resource the engine was about to run out of. Death was used at 04:837 to copy a Steel Three, worth far less to a Glass-lead build than another Glass face. |
| Leaving the Ante 12 shop on $2 | 04:775-04:827 | Five rerolls in one shop cost $15; the $9 of cards it found were Scholar, Strength and Death. Holding $50 instead would have paid $10 at each of the next cash outs; the run took $25 across its last eight. |
| Selling Ramen for Card Sharp | 04:914 | This one holds up. Rescoring the four Tooth hands with Ramen at X1.71 in Card Sharp's slot gives 601,159,554 against the 1,026,114,271 actually scored. Card Sharp's X3 on the repeated Flush was worth more than Ramen's decayed X1.71. |
| Brainstorm copying Photograph into Crimson Heart | 04:287 | Also defensible. Disabling Photograph cost 64x (11,548,293 to 180,442) because Brainstorm's copy died with it, the worst of the seven slots; but putting Hanging Chad leftmost instead only raises the worst case to 220,877 while dropping the mean over the seven disables from 4,318,136 to 2,755,599. |

The four buy-with-full-slots rejections belong here too. In each case a sale
first, then a reobservation, then the purchase was legal and available; the run
instead left the shop or rerolled three times out of four.

## What would have been needed at Ante 13

The Tooth required 94,000,000,000. One blind earlier the same build had scored
134,231,931,235 in a single hand. The Tooth debuffs nothing and changes no
draw; its only effect is $1 per card played. So the engine was intact and the
requirement was under the demonstrated peak. Three things account for the gap,
in order of size.

**The engine ate its own ammunition.** Every retrigger of a Glass card rolls its
1-in-4 destruction independently, and the lead card is retriggered five times.
The deck's Glass count fell from seven (04:691) to five after the Ante 13 Small
Blind and to four after the Big Blind (04:877, 04:903). The two cards destroyed
were the Glass King and the Glass Queen: the only Glass faces in the deck apart
from the Jack that Strength had created at 04:833. Both 100B hands were led by a
Glass face; by the boss, one Glass face remained in 57 cards.

**The model played for that one card instead of for the score.** Its plan from
04:945 onward is explicit: "Prioritize finding Glass JS... Lead with Glass JS,
then repeat Flush for Card Sharp." It spent all four boss hands cycling toward a
single named card, keeping the red-seal Glass Ten out of every flush to protect
it. The Glass Jack never appeared. The cost is measurable: 764,127 instead of
1,222,760,448 on the first hand and 951,035,904 instead of 5,355,237,888 on the
third.

**Even the best available play falls short.** Taking the best legal five-card
play on each of the four recorded draws gives 1,222,760,448 + 13,511,680 +
5,355,237,888 + 60,802,560, about 6.65 billion. That is 6.9x better than the
1,026,133,011 actually scored and still 14x short of 94,000,000,000. (The draws
would have differed after a different first play, so this is a bound on those
four observed hands, not a simulation of the blind.)

The honest reading is that the Ante 13 boss was lost in the two blinds before
it, not on it. The build's peak was a lottery on one Glass face card reaching
the lead slot, the supply of that card was consumed by the very hands that
demonstrated the peak, and there was no money left to replace it: $2 entering
the ante, $0 after Observatory, and both consumable slots held by the Jupiters
that made those peak hands possible. The Ante 13 shops did offer The Chariot and
Death at $3 each (04:881), but with two Jupiters held and $6 in hand under
Observatory, buying either meant giving up an X1.5 on every Flush. A run that
had held its $50 interest floor through Antes 10 to 12 would have arrived with
roughly $55 more and a free choice there.

## Scope

Nothing in this section was replayed against a live game. The counterfactual
scores are the project's offline scorer applied to the recorded public
observation for that decision, with the same coverage limits documented in
[the strategy library](strategy-library.md). They show what the visible state
supported, not that a different line would have won.
