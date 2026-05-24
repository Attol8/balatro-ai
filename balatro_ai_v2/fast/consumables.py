from __future__ import annotations

from dataclasses import dataclass

from balatro_ai_v2.fast.card_state import FastCardState, with_rank, with_suit
from balatro_ai_v2.fast.hand import (
    FIVE_OF_A_KIND,
    FLUSH,
    FLUSH_FIVE,
    FLUSH_HOUSE,
    FOUR_OF_A_KIND,
    FULL_HOUSE,
    HIGH_CARD,
    PAIR,
    STRAIGHT,
    STRAIGHT_FLUSH,
    THREE_OF_A_KIND,
    TWO_PAIR,
)
from balatro_ai_v2.fast.modifiers import Enhancement, Seal


@dataclass(frozen=True, slots=True)
class ConsumableResult:
    cards: tuple[FastCardState, ...]
    hand_levels: tuple[int, ...]
    money_delta: int = 0
    created_keys: tuple[str, ...] = ()
    created_kinds: tuple[str, ...] = ()
    destroyed_indices: tuple[int, ...] = ()
    hand_size_delta: int = 0
    joker_edition_key: str | None = None
    duplicated_joker: bool = False
    destroy_other_jokers: bool = False


TAROT_SUIT_CONVERSIONS = {
    "c_world": 0,  # Spades
    "c_sun": 1,  # Hearts
    "c_moon": 2,  # Clubs
    "c_star": 3,  # Diamonds
}

TAROT_ENHANCEMENTS = {
    "c_heirophant": Enhancement.BONUS,
    "c_empress": Enhancement.MULT,
    "c_lovers": Enhancement.WILD,
    "c_justice": Enhancement.GLASS,
    "c_chariot": Enhancement.STEEL,
    "c_tower": Enhancement.STONE,
    "c_devil": Enhancement.GOLD,
    "c_magician": Enhancement.LUCKY,
}

TAROT_TARGET_LIMITS = {
    "c_world": 3,
    "c_sun": 3,
    "c_moon": 3,
    "c_star": 3,
    "c_heirophant": 2,
    "c_empress": 2,
    "c_lovers": 1,
    "c_justice": 1,
    "c_chariot": 1,
    "c_tower": 1,
    "c_devil": 1,
    "c_magician": 2,
    "c_strength": 2,
    "c_hanged_man": 2,
    "c_death": 2,
}

PLANET_HANDS = {
    "c_pluto": HIGH_CARD,
    "c_mercury": PAIR,
    "c_uranus": TWO_PAIR,
    "c_venus": THREE_OF_A_KIND,
    "c_saturn": STRAIGHT,
    "c_jupiter": FLUSH,
    "c_earth": FULL_HOUSE,
    "c_mars": FOUR_OF_A_KIND,
    "c_neptune": STRAIGHT_FLUSH,
    "c_planet_x": FIVE_OF_A_KIND,
    "c_ceres": FLUSH_HOUSE,
    "c_eris": FLUSH_FIVE,
}

SPECTRAL_SEALS = {
    "c_talisman": Seal.GOLD,
    "c_deja_vu": Seal.RED,
    "c_trance": Seal.BLUE,
    "c_medium": Seal.PURPLE,
}

DETERMINISTIC_CONSUMABLES = frozenset(
    {
        *TAROT_SUIT_CONVERSIONS.keys(),
        *TAROT_ENHANCEMENTS.keys(),
        *TAROT_TARGET_LIMITS.keys(),
        *PLANET_HANDS.keys(),
        *SPECTRAL_SEALS.keys(),
        "c_hermit",
        "c_temperance",
        "c_cryptid",
        "c_immolate",
        "c_black_hole",
        "c_ankh",
        "c_aura",
        "c_ectoplasm",
        "c_emperor",
        "c_familiar",
        "c_fool",
        "c_grim",
        "c_hex",
        "c_high_priestess",
        "c_incantation",
        "c_judgement",
        "c_ouija",
        "c_sigil",
        "c_soul",
        "c_wheel_of_fortune",
        "c_wraith",
    }
)


def apply_consumable(
    key: str,
    cards: tuple[FastCardState, ...],
    targets: tuple[int, ...] = (),
    hand_levels: tuple[int, ...] | None = None,
    *,
    money: int = 0,
    joker_sell_total: int = 0,
    last_consumable_key: str | None = None,
    chosen_edition: str | None = None,
    chosen_rank: int | None = None,
    chosen_suit: int | None = None,
    created_cards: tuple[FastCardState, ...] = (),
    probability_success: bool = False,
) -> ConsumableResult:
    levels = hand_levels or (1,) * 12
    _validate_unique_targets(cards, targets)

    if key in TAROT_SUIT_CONVERSIONS:
        _validate_target_limit(key, targets)
        return ConsumableResult(
            cards=_replace_targets(cards, targets, lambda card: with_suit(card, TAROT_SUIT_CONVERSIONS[key])),
            hand_levels=levels,
        )
    if key in TAROT_ENHANCEMENTS:
        _validate_target_limit(key, targets)
        enhancement = TAROT_ENHANCEMENTS[key]
        return ConsumableResult(
            cards=_replace_targets(cards, targets, lambda card: _with_enhancement(card, enhancement)),
            hand_levels=levels,
        )
    if key == "c_strength":
        _validate_target_limit(key, targets)
        return ConsumableResult(
            cards=_replace_targets(cards, targets, lambda card: with_rank(card, min(card.rank + 1, 12))),
            hand_levels=levels,
        )
    if key == "c_hanged_man":
        _validate_target_limit(key, targets)
        target_set = set(targets)
        return ConsumableResult(
            cards=tuple(card for index, card in enumerate(cards) if index not in target_set),
            hand_levels=levels,
            destroyed_indices=tuple(sorted(targets)),
        )
    if key == "c_death":
        _validate_target_limit(key, targets)
        if len(targets) != 2:
            raise ValueError("c_death requires exactly two selected cards")
        dest_index, source_index = targets
        out = list(cards)
        out[dest_index] = cards[source_index]
        return ConsumableResult(cards=tuple(out), hand_levels=levels)
    if key in PLANET_HANDS:
        hand_kind = PLANET_HANDS[key]
        updated = list(levels)
        updated[hand_kind] += 1
        return ConsumableResult(cards=cards, hand_levels=tuple(updated))
    if key == "c_black_hole":
        return ConsumableResult(cards=cards, hand_levels=tuple(level + 1 for level in levels))
    if key == "c_hermit":
        return ConsumableResult(cards=cards, hand_levels=levels, money_delta=min(money, 20))
    if key == "c_temperance":
        return ConsumableResult(cards=cards, hand_levels=levels, money_delta=min(joker_sell_total, 50))
    if key in SPECTRAL_SEALS:
        _validate_single_target(key, targets)
        seal = SPECTRAL_SEALS[key]
        return ConsumableResult(
            cards=_replace_targets(cards, targets, lambda card: _with_seal(card, seal)),
            hand_levels=levels,
        )
    if key == "c_cryptid":
        _validate_single_target(key, targets)
        target = cards[targets[0]]
        return ConsumableResult(cards=cards + (target, target), hand_levels=levels)
    if key == "c_immolate":
        if len(targets) > 5:
            raise ValueError("c_immolate can destroy at most five cards")
        target_set = set(targets)
        return ConsumableResult(
            cards=tuple(card for index, card in enumerate(cards) if index not in target_set),
            hand_levels=levels,
            money_delta=20,
            destroyed_indices=tuple(sorted(targets)),
        )
    if key == "c_fool":
        if last_consumable_key is None:
            raise ValueError("c_fool requires last_consumable_key")
        return ConsumableResult(cards=cards, hand_levels=levels, created_keys=(last_consumable_key,))
    if key == "c_emperor":
        return ConsumableResult(cards=cards, hand_levels=levels, created_kinds=("Tarot", "Tarot"))
    if key == "c_high_priestess":
        return ConsumableResult(cards=cards, hand_levels=levels, created_kinds=("Planet", "Planet"))
    if key == "c_judgement":
        return ConsumableResult(cards=cards, hand_levels=levels, created_kinds=("Joker",))
    if key == "c_soul":
        return ConsumableResult(cards=cards, hand_levels=levels, created_kinds=("Legendary Joker",))
    if key == "c_wraith":
        return ConsumableResult(cards=cards, hand_levels=levels, money_delta=-money, created_kinds=("Rare Joker",))
    if key == "c_aura":
        _validate_single_target(key, targets)
        if chosen_edition is None:
            raise ValueError("c_aura requires chosen_edition")
        return ConsumableResult(
            cards=_replace_targets(cards, targets, lambda card: _with_edition_key(card, chosen_edition)),
            hand_levels=levels,
        )
    if key == "c_sigil":
        if chosen_suit is None:
            raise ValueError("c_sigil requires chosen_suit")
        return ConsumableResult(
            cards=tuple(with_suit(card, chosen_suit) for card in cards),
            hand_levels=levels,
        )
    if key == "c_ouija":
        if chosen_rank is None:
            raise ValueError("c_ouija requires chosen_rank")
        return ConsumableResult(
            cards=tuple(with_rank(card, chosen_rank) for card in cards),
            hand_levels=levels,
            hand_size_delta=-1,
        )
    if key in {"c_familiar", "c_grim", "c_incantation"}:
        if not created_cards:
            raise ValueError(f"{key} requires created_cards with resolved source RNG output")
        target_set = set(targets)
        return ConsumableResult(
            cards=tuple(card for index, card in enumerate(cards) if index not in target_set) + created_cards,
            hand_levels=levels,
            destroyed_indices=tuple(sorted(targets)),
        )
    if key == "c_ankh":
        return ConsumableResult(cards=cards, hand_levels=levels, duplicated_joker=True, destroy_other_jokers=True)
    if key == "c_hex":
        return ConsumableResult(
            cards=cards,
            hand_levels=levels,
            joker_edition_key="e_polychrome",
            destroy_other_jokers=True,
        )
    if key == "c_ectoplasm":
        return ConsumableResult(
            cards=cards,
            hand_levels=levels,
            hand_size_delta=-1,
            joker_edition_key="e_negative",
        )
    if key == "c_wheel_of_fortune":
        return ConsumableResult(
            cards=cards,
            hand_levels=levels,
            joker_edition_key=chosen_edition if probability_success else None,
        )

    raise NotImplementedError(f"consumable is not implemented: {key}")


def _replace_targets(
    cards: tuple[FastCardState, ...],
    targets: tuple[int, ...],
    transform,
) -> tuple[FastCardState, ...]:
    target_set = set(targets)
    return tuple(transform(card) if index in target_set else card for index, card in enumerate(cards))


def _with_enhancement(card: FastCardState, enhancement: Enhancement) -> FastCardState:
    return FastCardState(
        card_id=card.card_id,
        enhancement=enhancement,
        edition=card.edition,
        seal=card.seal,
        bonus_chips=card.bonus_chips,
        bonus_mult=card.bonus_mult,
        debuffed=card.debuffed,
    )


def _with_seal(card: FastCardState, seal: Seal) -> FastCardState:
    return FastCardState(
        card_id=card.card_id,
        enhancement=card.enhancement,
        edition=card.edition,
        seal=seal,
        bonus_chips=card.bonus_chips,
        bonus_mult=card.bonus_mult,
        debuffed=card.debuffed,
    )


def _with_edition_key(card: FastCardState, edition_key: str) -> FastCardState:
    from balatro_ai_v2.fast.modifiers import Edition

    editions = {
        "e_base": Edition.BASE,
        "e_foil": Edition.FOIL,
        "e_holo": Edition.HOLOGRAPHIC,
        "e_polychrome": Edition.POLYCHROME,
        "e_negative": Edition.NEGATIVE,
    }
    if edition_key not in editions:
        raise ValueError(f"unknown edition key: {edition_key}")
    return FastCardState(
        card_id=card.card_id,
        enhancement=card.enhancement,
        edition=editions[edition_key],
        seal=card.seal,
        bonus_chips=card.bonus_chips,
        bonus_mult=card.bonus_mult,
        debuffed=card.debuffed,
    )


def _validate_unique_targets(cards: tuple[FastCardState, ...], targets: tuple[int, ...]) -> None:
    if len(set(targets)) != len(targets):
        raise ValueError("targets must be unique")
    for target in targets:
        if not 0 <= target < len(cards):
            raise ValueError(f"target index out of range: {target}")


def _validate_target_limit(key: str, targets: tuple[int, ...]) -> None:
    limit = TAROT_TARGET_LIMITS[key]
    if len(targets) > limit:
        raise ValueError(f"{key} accepts at most {limit} targets")


def _validate_single_target(key: str, targets: tuple[int, ...]) -> None:
    if len(targets) != 1:
        raise ValueError(f"{key} requires exactly one selected card")
