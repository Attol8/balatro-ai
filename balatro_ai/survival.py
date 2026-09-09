"""Public resource and sticker risks; no prediction of future draws or score."""

from balatro_ai.game.state import PublicItem, PublicObservation

# Verified against installed vanilla Balatro.love: game.lua 420/452/470;
# card.lua 2292 (debuff guard), 2903/2945 (round decay), 3571 (hand decay).
# Native round decay precedes rental/perishable processing (state_events.lua 101-109).
_DECAY_RULES = {
    "j_ice_cream": ("current_chips", "chips", 5, "after_played_hand"),
    "j_popcorn": ("current_mult", "mult", 4, "round_end"),
    "j_turtle_bean": ("current_hand_size_bonus", "hand_size_bonus", 1, "round_end"),
}


def _decaying_jokers(visible: list[tuple[int, PublicItem]]) -> list[dict[str, object]]:
    rows = []
    for slot, item in visible:
        rule = _DECAY_RULES.get(item.key)
        if rule is None:
            continue
        field, unit, amount, trigger = rule
        value = getattr(item.runtime, field) if item.runtime is not None else None
        # A missing public value is unknown, never the vanilla starting value.
        known = isinstance(value, int) and not isinstance(value, bool) and value >= 0
        next_value = max(0, value - amount) if known and not item.debuffed else None
        rows.append(
            {
                "slot": slot,
                "key": item.key,
                "current_value": value if known else None,
                "value_unit": unit,
                "debuffed": item.debuffed,
                "current_effect_value": 0 if item.debuffed else value if known else None,
                "decay_amount": amount,
                "decay_trigger": trigger,
                "decays_while_debuffed": False,
                "next_value_if_still_active": next_value,
                "removed_at_next_trigger_if_still_active": next_value == 0
                if next_value is not None
                else None,
                "effect_text": item.effect_text,
                "note": (
                    "Intrinsic vanilla decay only: the effect and its decay pause while debuffed. "
                    "Next value assumes the Joker remains active until its trigger; zero means "
                    "it is removed. Missing runtime leaves the current and next values unknown. "
                    "Round-end decay precedes perishable expiration, which can disable a surviving "
                    "Joker separately. This is not a next-blind score or win forecast."
                ),
            }
        )
    return rows


def survival_context(observation: PublicObservation) -> dict[str, object]:
    visible = [
        (slot, item) for slot, item in enumerate(observation.jokers) if isinstance(item, PublicItem)
    ]
    decaying = _decaying_jokers(visible)
    offers = [
        (zone, slot, item)
        for zone in ("shop", "opened_pack")
        for slot, item in enumerate(getattr(observation, zone))
        if isinstance(item, PublicItem) and item.kind == "JOKER"
    ]
    stickered_offers = [
        {
            "zone": zone,
            "slot": slot,
            "key": item.key,
            "eternal": item.eternal,
            "rental_charge_per_round": 3 if item.rental else 0,
            "perishable_rounds": item.perishable_rounds,
        }
        for zone, slot, item in offers
        if item.eternal or item.rental or item.perishable_rounds is not None
    ]
    if not (
        observation.deck == "BLACK"
        or observation.stake == "GOLD"
        or stickered_offers
        or decaying
        or any(
            item.eternal or item.rental or item.perishable_rounds is not None for _, item in visible
        )
    ):
        return {}
    rent = 3 * sum(item.rental for _, item in visible)
    result = {
        "deck": observation.deck,
        "stake": observation.stake,
        "hands_left": observation.round.hands_left,
        "discards_left": observation.round.discards_left,
        "joker_limit": observation.joker_limit,
        "visible_rental_charge_per_round": rent,
        "money_less_visible_rent_only": observation.money - rent,
        "rental_note": "Rent includes debuffed rentals. This is not a cashout forecast: other income, expenses and hidden Jokers are excluded.",
        "eternal_slots": [slot for slot, item in visible if item.eternal],
        "non_eternal_slots": [slot for slot, item in visible if not item.eternal],
        "replacement_note": "Eternal Jokers cannot be sold. Non-eternal slots are replacement candidates only when sell_joker is legal in this phase; reobserve after selling.",
        "perishables": [
            {
                "slot": slot,
                "key": item.key,
                "rounds_remaining": item.perishable_rounds,
                "expires_at_next_round_end": item.perishable_rounds == 1,
                "expired": item.perishable_rounds == 0,
            }
            for slot, item in visible
            if item.perishable_rounds is not None
        ],
        "perishable_note": "A Joker with one round remaining can help this round but expires at its end. Plan replacement before relying on it for the next blind; do not discard needed survival score early.",
        "stickered_offers": stickered_offers,
    }
    if decaying:
        result["decaying_jokers"] = decaying
    return result
