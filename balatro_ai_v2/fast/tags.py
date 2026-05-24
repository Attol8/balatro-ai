from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class TagTrigger(StrEnum):
    EVAL = "eval"
    IMMEDIATE = "immediate"
    NEW_BLIND_CHOICE = "new_blind_choice"
    VOUCHER_ADD = "voucher_add"
    TAG_ADD = "tag_add"
    ROUND_START_BONUS = "round_start_bonus"
    SHOP_START = "shop_start"
    STORE_JOKER_CREATE = "store_joker_create"
    STORE_JOKER_MODIFY = "store_joker_modify"
    SHOP_FINAL_PASS = "shop_final_pass"


@dataclass(frozen=True, slots=True)
class TagRule:
    key: str
    name: str
    order: int
    trigger: TagTrigger
    min_ante: int | None = None
    dollars: int = 0
    dollars_per_hand: int = 0
    dollars_per_discard: int = 0
    money_cap: int = 0
    skip_bonus: int = 0
    hand_levels: int = 0
    hand_size_delta: int = 0
    spawn_jokers: int = 0
    joker_rarity: int | None = None
    joker_edition: str | None = None
    free_pack_keys: tuple[str, ...] = ()
    grants_voucher_slot: bool = False
    duplicates_next_tag: bool = False
    boss_reroll: bool = False
    makes_shop_free: bool = False
    free_reroll: bool = False


TAG_RULES: dict[str, TagRule] = {
    "tag_uncommon": TagRule("tag_uncommon", "Uncommon Tag", 1, TagTrigger.STORE_JOKER_CREATE, joker_rarity=2),
    "tag_rare": TagRule("tag_rare", "Rare Tag", 2, TagTrigger.STORE_JOKER_CREATE, joker_rarity=3),
    "tag_negative": TagRule(
        "tag_negative", "Negative Tag", 3, TagTrigger.STORE_JOKER_MODIFY, min_ante=2, joker_edition="negative"
    ),
    "tag_foil": TagRule("tag_foil", "Foil Tag", 4, TagTrigger.STORE_JOKER_MODIFY, joker_edition="foil"),
    "tag_holo": TagRule("tag_holo", "Holographic Tag", 5, TagTrigger.STORE_JOKER_MODIFY, joker_edition="holo"),
    "tag_polychrome": TagRule(
        "tag_polychrome", "Polychrome Tag", 6, TagTrigger.STORE_JOKER_MODIFY, joker_edition="polychrome"
    ),
    "tag_investment": TagRule("tag_investment", "Investment Tag", 7, TagTrigger.EVAL, dollars=25),
    "tag_voucher": TagRule(
        "tag_voucher", "Voucher Tag", 8, TagTrigger.VOUCHER_ADD, grants_voucher_slot=True
    ),
    "tag_boss": TagRule("tag_boss", "Boss Tag", 9, TagTrigger.NEW_BLIND_CHOICE, boss_reroll=True),
    "tag_standard": TagRule(
        "tag_standard",
        "Standard Tag",
        10,
        TagTrigger.NEW_BLIND_CHOICE,
        min_ante=2,
        free_pack_keys=("p_standard_mega_1",),
    ),
    "tag_charm": TagRule(
        "tag_charm",
        "Charm Tag",
        11,
        TagTrigger.NEW_BLIND_CHOICE,
        free_pack_keys=("p_arcana_mega_1", "p_arcana_mega_2"),
    ),
    "tag_meteor": TagRule(
        "tag_meteor",
        "Meteor Tag",
        12,
        TagTrigger.NEW_BLIND_CHOICE,
        min_ante=2,
        free_pack_keys=("p_celestial_mega_1", "p_celestial_mega_2"),
    ),
    "tag_buffoon": TagRule(
        "tag_buffoon",
        "Buffoon Tag",
        13,
        TagTrigger.NEW_BLIND_CHOICE,
        min_ante=2,
        free_pack_keys=("p_buffoon_mega_1",),
    ),
    "tag_handy": TagRule("tag_handy", "Handy Tag", 14, TagTrigger.IMMEDIATE, min_ante=2, dollars_per_hand=1),
    "tag_garbage": TagRule(
        "tag_garbage", "Garbage Tag", 15, TagTrigger.IMMEDIATE, min_ante=2, dollars_per_discard=1
    ),
    "tag_ethereal": TagRule(
        "tag_ethereal",
        "Ethereal Tag",
        16,
        TagTrigger.NEW_BLIND_CHOICE,
        min_ante=2,
        free_pack_keys=("p_spectral_normal_1",),
    ),
    "tag_coupon": TagRule("tag_coupon", "Coupon Tag", 17, TagTrigger.SHOP_FINAL_PASS, makes_shop_free=True),
    "tag_double": TagRule("tag_double", "Double Tag", 18, TagTrigger.TAG_ADD, duplicates_next_tag=True),
    "tag_juggle": TagRule("tag_juggle", "Juggle Tag", 19, TagTrigger.ROUND_START_BONUS, hand_size_delta=3),
    "tag_d_six": TagRule("tag_d_six", "D6 Tag", 20, TagTrigger.SHOP_START, free_reroll=True),
    "tag_top_up": TagRule("tag_top_up", "Top-up Tag", 21, TagTrigger.IMMEDIATE, min_ante=2, spawn_jokers=2),
    "tag_skip": TagRule("tag_skip", "Skip Tag", 22, TagTrigger.IMMEDIATE, skip_bonus=5),
    "tag_orbital": TagRule("tag_orbital", "Orbital Tag", 23, TagTrigger.IMMEDIATE, min_ante=2, hand_levels=3),
    "tag_economy": TagRule("tag_economy", "Economy Tag", 24, TagTrigger.IMMEDIATE, money_cap=40),
}

EXACT_TAGS = frozenset(TAG_RULES)


def tag_rule(key: str) -> TagRule:
    try:
        return TAG_RULES[key]
    except KeyError as exc:
        raise NotImplementedError(f"tag is not implemented: {key}") from exc


def tag_money_delta(
    tag_key: str,
    *,
    hands_played: int = 0,
    discards_unused: int = 0,
    money: int = 0,
    skips: int = 0,
) -> int:
    rule = tag_rule(tag_key)
    if rule.dollars:
        return rule.dollars
    if rule.dollars_per_hand:
        return hands_played * rule.dollars_per_hand
    if rule.dollars_per_discard:
        return discards_unused * rule.dollars_per_discard
    if rule.skip_bonus:
        return skips * rule.skip_bonus
    if rule.money_cap:
        return min(max(money, 0), rule.money_cap)
    return 0
