from __future__ import annotations

from dataclasses import dataclass, replace
from random import Random

from balatro_ai_v2.fast.card_state import FastCardState
from balatro_ai_v2.fast.cards import NUM_RANKS, shuffled_deck
from balatro_ai_v2.fast.tags import EXACT_TAGS, tag_money_delta as _tag_money_delta


@dataclass(frozen=True, slots=True)
class RunModifiers:
    money: int = 4
    hands: int = 4
    discards: int = 3
    hand_size: int = 8
    joker_slots: int = 5
    consumable_slots: int = 2
    shop_slots: int = 2
    interest_cap: int = 25
    interest_amount: int = 1
    base_reroll_cost: int = 5
    free_rerolls: int = 0
    shop_discount: float = 1.0
    blind_requirement_multiplier: float = 1.0
    tarot_rate: float = 4.0
    planet_rate: float = 4.0
    spectral_rate: float = 0.0
    playing_card_rate: float = 0.0
    edition_rate: float = 1.0
    arcana_pack_spectral_chance: float = 0.0
    telescope_guarantees_most_played_planet: bool = False
    observatory_xmult: float = 1.0
    boss_reroll_cost: int | None = None
    boss_reroll_once_per_ante: bool = False
    bankrupt_at: int = 0
    probability_multiplier: float = 1.0
    planets_are_free: bool = False
    celestial_packs_are_free: bool = False
    earns_interest: bool = True
    earns_hand_money: bool = True
    earns_discard_money: bool = False
    playing_cards_in_shop: bool = False
    enhanced_playing_cards_in_shop: bool = False
    spectral_cards_in_shop: bool = False
    double_tags: bool = False
    starting_consumables: tuple[str, ...] = ()


VOUCHERS = frozenset(
    {
        "v_overstock_norm",
        "v_overstock_plus",
        "v_clearance_sale",
        "v_liquidation",
        "v_hone",
        "v_glow_up",
        "v_reroll_surplus",
        "v_reroll_glut",
        "v_crystal_ball",
        "v_omen_globe",
        "v_telescope",
        "v_observatory",
        "v_grabber",
        "v_nacho_tong",
        "v_wasteful",
        "v_recyclomancy",
        "v_tarot_merchant",
        "v_tarot_tycoon",
        "v_planet_merchant",
        "v_planet_tycoon",
        "v_seed_money",
        "v_money_tree",
        "v_blank",
        "v_antimatter",
        "v_magic_trick",
        "v_illusion",
        "v_hieroglyph",
        "v_petroglyph",
        "v_directors_cut",
        "v_retcon",
        "v_paint_brush",
        "v_palette",
    }
)

EXACT_VOUCHERS = frozenset(
    VOUCHERS
)

DECKS = frozenset(
    {
        "b_red",
        "b_blue",
        "b_yellow",
        "b_green",
        "b_black",
        "b_magic",
        "b_nebula",
        "b_ghost",
        "b_abandoned",
        "b_checkered",
        "b_zodiac",
        "b_painted",
        "b_anaglyph",
        "b_plasma",
        "b_erratic",
        "b_challenge",
    }
)

EXACT_DECKS = frozenset(
    DECKS
)

TAGS = frozenset(
    {
        "tag_uncommon",
        "tag_rare",
        "tag_negative",
        "tag_foil",
        "tag_holo",
        "tag_polychrome",
        "tag_investment",
        "tag_voucher",
        "tag_boss",
        "tag_standard",
        "tag_charm",
        "tag_meteor",
        "tag_buffoon",
        "tag_handy",
        "tag_garbage",
        "tag_ethereal",
        "tag_coupon",
        "tag_double",
        "tag_juggle",
        "tag_d_six",
        "tag_top_up",
        "tag_orbital",
        "tag_economy",
    }
)

def apply_deck(modifiers: RunModifiers, deck_key: str) -> RunModifiers:
    if deck_key == "b_red":
        return replace(modifiers, discards=modifiers.discards + 1)
    if deck_key == "b_blue":
        return replace(modifiers, hands=modifiers.hands + 1)
    if deck_key == "b_yellow":
        return replace(modifiers, money=modifiers.money + 10)
    if deck_key == "b_green":
        return replace(
            modifiers,
            earns_interest=False,
            earns_hand_money=False,
            earns_discard_money=True,
        )
    if deck_key == "b_black":
        return replace(modifiers, joker_slots=modifiers.joker_slots + 1, hands=modifiers.hands - 1)
    if deck_key == "b_magic":
        return replace(
            apply_voucher(modifiers, "v_crystal_ball"),
            starting_consumables=modifiers.starting_consumables + ("c_fool", "c_fool"),
        )
    if deck_key == "b_nebula":
        return replace(apply_voucher(modifiers, "v_telescope"), consumable_slots=modifiers.consumable_slots - 1)
    if deck_key == "b_ghost":
        return replace(
            modifiers,
            spectral_cards_in_shop=True,
            spectral_rate=2,
            starting_consumables=modifiers.starting_consumables + ("c_hex",),
        )
    if deck_key == "b_zodiac":
        out = apply_voucher(modifiers, "v_tarot_merchant")
        out = apply_voucher(out, "v_planet_merchant")
        return apply_voucher(out, "v_overstock_norm")
    if deck_key == "b_painted":
        return replace(modifiers, hand_size=modifiers.hand_size + 2, joker_slots=modifiers.joker_slots - 1)
    if deck_key == "b_anaglyph":
        return replace(modifiers, double_tags=True)
    if deck_key == "b_plasma":
        return replace(modifiers, blind_requirement_multiplier=2.0)
    if deck_key in {"b_abandoned", "b_checkered", "b_erratic", "b_challenge"}:
        return modifiers
    raise NotImplementedError(f"deck is not implemented: {deck_key}")


def apply_voucher(modifiers: RunModifiers, voucher_key: str) -> RunModifiers:
    if voucher_key in {"v_overstock_norm", "v_overstock_plus"}:
        return replace(modifiers, shop_slots=modifiers.shop_slots + 1)
    if voucher_key == "v_clearance_sale":
        return replace(modifiers, shop_discount=modifiers.shop_discount * 0.75)
    if voucher_key == "v_liquidation":
        return replace(modifiers, shop_discount=modifiers.shop_discount * 0.5)
    if voucher_key in {"v_reroll_surplus", "v_reroll_glut"}:
        return replace(modifiers, base_reroll_cost=max(0, modifiers.base_reroll_cost - 2))
    if voucher_key == "v_crystal_ball":
        return replace(modifiers, consumable_slots=modifiers.consumable_slots + 1)
    if voucher_key in {"v_grabber", "v_nacho_tong"}:
        return replace(modifiers, hands=modifiers.hands + 1)
    if voucher_key in {"v_wasteful", "v_recyclomancy"}:
        return replace(modifiers, discards=modifiers.discards + 1)
    if voucher_key == "v_seed_money":
        return replace(modifiers, interest_cap=50)
    if voucher_key == "v_money_tree":
        return replace(modifiers, interest_cap=100)
    if voucher_key == "v_antimatter":
        return replace(modifiers, joker_slots=modifiers.joker_slots + 1)
    if voucher_key == "v_magic_trick":
        return replace(modifiers, playing_cards_in_shop=True)
    if voucher_key == "v_illusion":
        return replace(modifiers, playing_cards_in_shop=True, enhanced_playing_cards_in_shop=True)
    if voucher_key == "v_hieroglyph":
        return replace(modifiers, hands=modifiers.hands - 1)
    if voucher_key == "v_petroglyph":
        return replace(modifiers, discards=modifiers.discards - 1)
    if voucher_key in {"v_paint_brush", "v_palette"}:
        return replace(modifiers, hand_size=modifiers.hand_size + 1)
    if voucher_key == "v_tarot_merchant":
        return replace(modifiers, tarot_rate=9.6)
    if voucher_key == "v_tarot_tycoon":
        return replace(modifiers, tarot_rate=32.0)
    if voucher_key == "v_planet_merchant":
        return replace(modifiers, planet_rate=9.6)
    if voucher_key == "v_planet_tycoon":
        return replace(modifiers, planet_rate=32.0)
    if voucher_key == "v_hone":
        return replace(modifiers, edition_rate=2.0)
    if voucher_key == "v_glow_up":
        return replace(modifiers, edition_rate=4.0)
    if voucher_key == "v_omen_globe":
        return replace(modifiers, arcana_pack_spectral_chance=0.2)
    if voucher_key == "v_telescope":
        return replace(modifiers, telescope_guarantees_most_played_planet=True)
    if voucher_key == "v_observatory":
        return replace(modifiers, observatory_xmult=1.5)
    if voucher_key == "v_directors_cut":
        return replace(modifiers, boss_reroll_cost=10, boss_reroll_once_per_ante=True)
    if voucher_key == "v_retcon":
        return replace(modifiers, boss_reroll_cost=10, boss_reroll_once_per_ante=False)
    if voucher_key == "v_blank":
        return modifiers
    raise NotImplementedError(f"voucher is not implemented: {voucher_key}")


def starting_deck(deck_key: str, seed: int = 0) -> tuple[FastCardState, ...]:
    if deck_key == "b_abandoned":
        return tuple(
            FastCardState(suit * NUM_RANKS + rank)
            for suit in range(4)
            for rank in range(NUM_RANKS)
            if rank not in {9, 10, 11}
        )
    if deck_key == "b_checkered":
        return tuple(
            FastCardState(suit * NUM_RANKS + rank)
            for suit in (0, 1)
            for _ in range(2)
            for rank in range(NUM_RANKS)
        )
    if deck_key == "b_erratic":
        rng = Random(seed)
        return tuple(
            FastCardState(rng.randrange(4) * NUM_RANKS + rng.randrange(NUM_RANKS))
            for _ in range(52)
        )
    if deck_key in DECKS:
        return tuple(FastCardState(card_id) for card_id in shuffled_deck(seed))
    raise NotImplementedError(f"deck is not implemented: {deck_key}")


def tag_money_delta(tag_key: str, *, hands_played: int = 0, discards_unused: int = 0, money: int = 0) -> int:
    return _tag_money_delta(
        tag_key,
        hands_played=hands_played,
        discards_unused=discards_unused,
        money=money,
    )
