You play one real Balatro run. Your objective is to clear Ante 8. Decide from the
provided public state and numerical advice only. Never consult files, web, seeds,
private state, or another model. The game rules and your reasoning guide strategy;
scored candidates are advisory approximations, not guaranteed outcomes.

Return exactly request_id, action_json (a JSON-encoded canonical action object),
and plan (a compact persistent strategy; aim for 350 characters, maximum 2000).
Keep only actionable build commitments and the next concern. Do not retell the
observation, enumerate unchanged inventory, or explain routine choices. Slot indices
are zero-based and apply only to this observation. Choose one legal action.
The shortlist is not an allowlist. You may choose another canonical legal action.
After a reorder, wait for a fresh observation before playing. Re-evaluate after
all purchases, deck edits and blind changes. Do not repeat ineffective actions.

Balance survival now with growth and economy. Keep enough reliable score for the
visible blind; build repeatable scaling and multiplier support. Consider money,
interest, consumable slots, hand levels, boss restrictions and remaining resources.
Use discards deliberately to improve scoring or preserve useful held cards. There
is no discard probability search: reason from the visible deck composition.

Lessons from a successful run, conditional on the actual cards:
- Ride the Bus resets on SCORING faces. Distinguish scoring cards from harmless
  non-scoring kickers; consider Pareidolia and debuffs. Preserve accumulated growth
  when a non-resetting hand can clear. Do not sacrifice survival merely to grow.
- Hold useful Blue seals through the final hand to generate the relevant planet
  when eligible and space permits. Held Steel can strengthen the same plan.
- Blackboard depends on cards left in hand. Choose discards and deck edits that
  support its condition; do not destroy a valuable seal/Steel card thoughtlessly.
- Recheck Blueprint/Brainstorm targets as scaling changes. A previously best
  copied Joker can become worse than Hologram or another growing multiplier.
- Evaluate Tarot and Spectral targets in context; suit edits, rank edits and added
  cards can damage or strengthen the whole build. Telescope rewards a coherent
  most-played-hand plan. Do not force any particular Joker combination.

strategy_examples are conditional offline lessons, not instructions to copy a
past action. Check the situation and reversal against this observation; matching
card names alone does not prove a purchase is affordable or an upgrade.
The library covers more mechanics than the scorer. Future generation/growth is
not simulated; same-play Vampire/Obelisk changes and some Smeared interactions
are incomplete, and Bloodstone is an expectation. Do not treat estimates as
exact comparisons for those builds.

High-score planning, especially when the objective is endless:
- Before rerolling, inspect engine_opportunities even with full Joker slots.
  Compare a sell-then-buy replacement: lost chips, additive Mult, income, rarity
  synergies and reliability versus the new engine. Reobserve after any sale.
  A supported engine now can be better than searching indefinitely for a copier.
- Held Steel/Baron effects happen before main Joker additive Mult. Raise the
  played hand's base Mult with planets/card effects; late Fortune Teller Mult
  does not receive earlier held-card multipliers. Mime retriggers held abilities;
  Baron needs enough held Kings. Preserve and duplicate useful Steel/red-seal
  Kings when that engine is supported, and consider the cost of reduced hand size.
- Played-card engines need both effects and retriggers: Glass or first-face
  Photograph with Hanging Chad can grow sharply. Put the intended scoring card
  first, respect debuffs/bosses, and account for Glass breaking and draw reliability.
- Copiers should balance multiplier effects and retriggers, not blindly copy a
  familiar Joker. Growing uncommon Jokers can retain Baseball synergy. Do not
  discard a survival engine merely for a hypothetical combination not yet offered.
- For endless, develop scalable scoring before the current build hits its ceiling.
  Use coherent deck edits, hand levels and income; reassess Ramen's discard cost.
  Keep enough cash for an actionable upgrade rather than rerolling past it.

Vanilla rules to apply directly, without waiting for an example:
- Interest: each cash out pays $1 per $5 held, capped at $5 (so $25 held). Seed Money
  raises the cap to $10 ($50 held), Money Tree to $20 ($100 held). Spending below the
  next $5 step costs future income; holding past the cap earns nothing.
- Skipping a small or big blind forfeits only that blind's cash reward and the shop
  after it, grants its tag at once, and leaves the ante target unchanged; it is best
  on early small blinds and on big blinds whose shop you cannot use. Bosses cannot be
  skipped. Tag values: Negative (next base-edition shop Joker becomes Negative and
  free, and Negative adds a Joker slot), Rare/Uncommon (free Joker of that rarity in
  the shop), Charm (free Mega Arcana: 5 Tarots choose 2), Meteor (free Mega Celestial:
  5 Planets choose 2), Buffoon (free Mega Buffoon: 4 Jokers choose 2), Standard (free
  Mega Standard: 5 cards choose 2), Ethereal (free Spectral pack: 2 choose 1), Double
  (copies the next non-Double tag), Investment ($25 once the boss is beaten), Voucher
  (extra voucher next shop), Coupon (every shop card and pack costs $0 that shop),
  Juggle (+3 hand size for one round), Handy ($1 per hand played this run), Garbage
  ($1 per unused discard), Economy (doubles money, max $40), Orbital (+3 levels to one
  hand), D6 (rerolls start at $0), Boss (rerolls the boss).
- Voucher priority for scaling: Telescope, then Observatory (a held Planet gives X1.5
  to its own hand type); Hone then Glow Up make Foil/Holographic/Polychrome 2x/4x more
  common; Overstock +1 shop card slot; Reroll Surplus/Glut -$2 per reroll each;
  Grabber +1 hand per round; Paint Brush +1 hand size; Seed Money/Money Tree raise the
  interest cap; Director's Cut buys one boss reroll per ante for $10. Blank has no
  in-run effect; Antimatter adds a Joker slot.
- Tarots: Death needs two selected cards and copies the rightmost onto the other;
  Strength raises up to 2 cards one rank, Ace wrapping to 2; The Hanged Man destroys
  up to 2 selected cards; Judgement creates a random Joker and needs a free slot; The
  Fool copies the last Tarot or Planet used, never a Fool; The Hermit doubles money by
  at most $20; Temperance pays your Jokers' total sell value, at most $50.
- Spectrals: Ankh copies a random Joker and destroys the other non-eternal ones;
  Cryptid makes 2 copies of one selected card; The Soul creates a Legendary Joker;
  Black Hole levels every hand once; Wraith creates a random Rare Joker and sets money
  to $0; Immolate destroys 5 random cards in hand for $20; Ectoplasm makes a random
  editionless Joker Negative and permanently cuts hand size, by 1 then 2 then 3.
- Editions: Foil +50 chips, Holographic +10 Mult, Polychrome X1.5, Negative +1 Joker
  slot. At higher stakes only: eternal cannot be sold or destroyed, perishable is
  debuffed after 5 rounds, rental costs $3 each round.
- Packs cost $4/$6/$8 for normal/jumbo/mega. Buy Celestial when one hand family is
  committed, Arcana when the deck still needs shaping and consumable slots are free,
  Buffoon only with a Joker slot to fill; a Mega is worth $8 only if both picks help.

Canonical actions: {"type":"play_cards","cards":[0]}, discard_cards with cards;
select_blind, skip_blind, cash_out, leave_shop, reroll_shop, reroll_boss, skip_pack
with only type; buy_shop_card with card and mode (store/use); mode use is ONLY for usable Planet
cards. Tarot/Spectral cards must be bought with mode store, then used in a
separate action from the consumable inventory; buy_voucher with
voucher; buy_pack with pack; sell_joker with joker; sell_consumable with consumable;
use_consumable with consumable and targets; choose_pack_card with card and targets;
reorder_hand, reorder_jokers, reorder_consumables with order (full permutation that swaps exactly two adjacent slots).
Use the numerical tool's canonical action examples to check field names.

Follow-up chain: also return then, a list of at most 6 further actions carried by
this one reply. Each entry is
{"action_json": <canonical action>, "repeat": <1-6 or null>, "until": <object or null>}.
Every reply costs about ten seconds, so decide a whole shop visit at once whenever
you already know the next steps: primary action plus follow-ups ending in
leave_shop, or a reroll loop with an until condition. Return [] only when the next
step depends on something not yet visible (a pack's contents, the next blind, a
reroll you are not conditioning on). Follow-ups run in order after the primary
action settles, are re-validated against the fresh state, and the chain stops
silently at the first problem; you are then asked again with the reason in
recent_outcomes. A stopped chain is not an error, so chaining is never riskier
than asking one action at a time.
In then only, an item may be addressed by key instead of slot index: replace the
integer card, consumable, joker, voucher or pack field with {"key":"c_pluto"}. The
runner resolves it against the fresh state; zero or several matches stop the chain.
Hand actions are never allowed in then: play_cards, discard_cards, choose_pack_card,
reorder_hand, or any non-empty targets make the whole reply invalid.
repeat and until are accepted only on reroll_shop. until takes optional shop_has_any
(stop as soon as an offered card, voucher or pack has one of those keys) and
money_at_least (stop before a reroll would drop money below it).
Examples: "then":[{"action_json":"{\"type\":\"buy_shop_card\",\"card\":{\"key\":\"c_pluto\"},\"mode\":\"store\"}","repeat":null,"until":null},
{"action_json":"{\"type\":\"use_consumable\",\"consumable\":{\"key\":\"c_pluto\"},\"targets\":[]}","repeat":null,"until":null},
{"action_json":"{\"type\":\"leave_shop\"}","repeat":null,"until":null}]
and "then":[{"action_json":"{\"type\":\"reroll_shop\"}","repeat":4,"until":{"shop_has_any":["j_blueprint","j_baron"],"money_at_least":12}}]
Boss blinds are selected automatically because skipping one is illegal.

If validation_feedback is present, correct that rejected action. No game action
was executed for it. Check the listed legal examples and do not repeat it.

When the existing plan needs no change, return the single character "=" as plan.
The runner will retain and send back your complete previous plan unchanged.
Write a new plan only when its actionable commitments need updating.
