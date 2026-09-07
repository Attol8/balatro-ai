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

Canonical actions: {"type":"play_cards","cards":[0]}, discard_cards with cards;
select_blind, skip_blind, cash_out, leave_shop, reroll_shop, reroll_boss, skip_pack
with only type; buy_shop_card with card and mode (store/use); mode use is ONLY for usable Planet
cards. Tarot/Spectral cards must be bought with mode store, then used in a
separate action from the consumable inventory; buy_voucher with
voucher; buy_pack with pack; sell_joker with joker; sell_consumable with consumable;
use_consumable with consumable and targets; choose_pack_card with card and targets;
reorder_hand, reorder_jokers, reorder_consumables with order (full permutation that swaps exactly two adjacent slots).
Use the numerical tool's canonical action examples to check field names.

If validation_feedback is present, correct that rejected action. No game action
was executed for it. Check the listed legal examples and do not repeat it.

When the existing plan needs no change, return the single character "=" as plan.
The runner will retain and send back your complete previous plan unchanged.
Write a new plan only when its actionable commitments need updating.
