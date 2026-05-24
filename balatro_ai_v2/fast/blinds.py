from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from balatro_ai_v2.fast.card_state import FastCardState


class BlindHandPolicy(StrEnum):
    NONE = "none"
    REPEAT_HAND_FORBIDDEN = "repeat_hand_forbidden"
    ONLY_FIRST_HAND_TYPE = "only_first_hand_type"
    MIN_FIVE_CARDS = "min_five_cards"
    DOWNLEVEL_HAND = "downlevel_hand"
    DRAIN_MONEY_ON_MOST_PLAYED = "drain_money_on_most_played"


class BlindDrawPolicy(StrEnum):
    NONE = "none"
    FIRST_HAND_FACE_DOWN = "first_hand_face_down"
    RANDOM_FACE_DOWN = "random_face_down"
    FACE_CARDS_FACE_DOWN = "face_cards_face_down"
    AFTER_PLAY_FACE_DOWN = "after_play_face_down"
    FORCE_ONE_CARD = "force_one_card"


@dataclass(frozen=True, slots=True)
class BlindRule:
    key: str
    name: str
    order: int
    dollars: int
    score_mult: float
    boss_min_ante: int | None = None
    boss_max_ante: int | None = None
    showdown: bool = False
    debuffed_suit: int | None = None
    debuff_faces: bool = False
    debuff_played_this_ante: bool = False
    debuff_all_non_jokers: bool = False
    hand_policy: BlindHandPolicy = BlindHandPolicy.NONE
    draw_policy: BlindDrawPolicy = BlindDrawPolicy.NONE
    hand_size_delta: int = 0
    discard_delta: int = 0
    hands_delta: int = 0
    halves_base_score: bool = False
    dollar_loss_per_played_card: int = 0

    @property
    def boss(self) -> bool:
        return self.boss_min_ante is not None


SPADES = 0
HEARTS = 1
CLUBS = 2
DIAMONDS = 3

BLIND_RULES: dict[str, BlindRule] = {
    "bl_small": BlindRule("bl_small", "Small Blind", 1, 3, 1),
    "bl_big": BlindRule("bl_big", "Big Blind", 2, 4, 1.5),
    "bl_hook": BlindRule("bl_hook", "The Hook", 3, 5, 2, 1, 10, discard_delta=-2),
    "bl_ox": BlindRule(
        "bl_ox", "The Ox", 4, 5, 2, 6, 10, hand_policy=BlindHandPolicy.DRAIN_MONEY_ON_MOST_PLAYED
    ),
    "bl_house": BlindRule(
        "bl_house", "The House", 5, 5, 2, 2, 10, draw_policy=BlindDrawPolicy.FIRST_HAND_FACE_DOWN
    ),
    "bl_wall": BlindRule("bl_wall", "The Wall", 6, 5, 4, 2, 10),
    "bl_wheel": BlindRule(
        "bl_wheel", "The Wheel", 7, 5, 2, 2, 10, draw_policy=BlindDrawPolicy.RANDOM_FACE_DOWN
    ),
    "bl_arm": BlindRule("bl_arm", "The Arm", 8, 5, 2, 2, 10, hand_policy=BlindHandPolicy.DOWNLEVEL_HAND),
    "bl_club": BlindRule("bl_club", "The Club", 9, 5, 2, 1, 10, debuffed_suit=CLUBS),
    "bl_fish": BlindRule(
        "bl_fish", "The Fish", 10, 5, 2, 2, 10, draw_policy=BlindDrawPolicy.AFTER_PLAY_FACE_DOWN
    ),
    "bl_psychic": BlindRule(
        "bl_psychic", "The Psychic", 11, 5, 2, 1, 10, hand_policy=BlindHandPolicy.MIN_FIVE_CARDS
    ),
    "bl_goad": BlindRule("bl_goad", "The Goad", 12, 5, 2, 1, 10, debuffed_suit=SPADES),
    "bl_water": BlindRule("bl_water", "The Water", 13, 5, 2, 2, 10, discard_delta=-99),
    "bl_window": BlindRule("bl_window", "The Window", 14, 5, 2, 1, 10, debuffed_suit=DIAMONDS),
    "bl_manacle": BlindRule("bl_manacle", "The Manacle", 15, 5, 2, 1, 10, hand_size_delta=-1),
    "bl_eye": BlindRule(
        "bl_eye", "The Eye", 16, 5, 2, 3, 10, hand_policy=BlindHandPolicy.REPEAT_HAND_FORBIDDEN
    ),
    "bl_mouth": BlindRule(
        "bl_mouth", "The Mouth", 17, 5, 2, 2, 10, hand_policy=BlindHandPolicy.ONLY_FIRST_HAND_TYPE
    ),
    "bl_plant": BlindRule("bl_plant", "The Plant", 18, 5, 2, 4, 10, debuff_faces=True),
    "bl_serpent": BlindRule("bl_serpent", "The Serpent", 19, 5, 2, 5, 10),
    "bl_pillar": BlindRule("bl_pillar", "The Pillar", 20, 5, 2, 1, 10, debuff_played_this_ante=True),
    "bl_needle": BlindRule("bl_needle", "The Needle", 21, 5, 1, 2, 10, hands_delta=-99),
    "bl_head": BlindRule("bl_head", "The Head", 22, 5, 2, 1, 10, debuffed_suit=HEARTS),
    "bl_tooth": BlindRule("bl_tooth", "The Tooth", 23, 5, 2, 3, 10, dollar_loss_per_played_card=1),
    "bl_flint": BlindRule("bl_flint", "The Flint", 24, 5, 2, 2, 10, halves_base_score=True),
    "bl_mark": BlindRule(
        "bl_mark", "The Mark", 25, 5, 2, 2, 10, draw_policy=BlindDrawPolicy.FACE_CARDS_FACE_DOWN
    ),
    "bl_final_acorn": BlindRule("bl_final_acorn", "Amber Acorn", 26, 8, 2, 10, 10, showdown=True),
    "bl_final_leaf": BlindRule(
        "bl_final_leaf", "Verdant Leaf", 27, 8, 2, 10, 10, showdown=True, debuff_all_non_jokers=True
    ),
    "bl_final_vessel": BlindRule("bl_final_vessel", "Violet Vessel", 28, 8, 6, 10, 10, showdown=True),
    "bl_final_heart": BlindRule("bl_final_heart", "Crimson Heart", 29, 8, 2, 10, 10, showdown=True),
    "bl_final_bell": BlindRule(
        "bl_final_bell", "Cerulean Bell", 30, 8, 2, 10, 10, showdown=True, draw_policy=BlindDrawPolicy.FORCE_ONE_CARD
    ),
}

IMPLEMENTED_BLINDS = frozenset(BLIND_RULES)


def blind_rule(key: str) -> BlindRule:
    try:
        return BLIND_RULES[key]
    except KeyError as exc:
        raise NotImplementedError(f"blind is not implemented: {key}") from exc


def blind_debuffs_card(key: str, card: FastCardState, *, played_this_ante: bool = False) -> bool:
    rule = blind_rule(key)
    if rule.debuff_all_non_jokers:
        return True
    if rule.debuffed_suit is not None and card.suit == rule.debuffed_suit:
        return True
    if rule.debuff_faces and card.rank in {9, 10, 11}:
        return True
    if rule.debuff_played_this_ante and played_this_ante:
        return True
    return False


def blind_blocks_hand(
    key: str,
    *,
    hand_name: str,
    hand_size: int,
    previous_hand_names: tuple[str, ...] = (),
    first_hand_name: str | None = None,
    most_played_hand_name: str | None = None,
) -> bool:
    rule = blind_rule(key)
    if rule.hand_policy == BlindHandPolicy.MIN_FIVE_CARDS:
        return hand_size < 5
    if rule.hand_policy == BlindHandPolicy.REPEAT_HAND_FORBIDDEN:
        return hand_name in previous_hand_names
    if rule.hand_policy == BlindHandPolicy.ONLY_FIRST_HAND_TYPE:
        return first_hand_name is not None and hand_name != first_hand_name
    if rule.hand_policy == BlindHandPolicy.DRAIN_MONEY_ON_MOST_PLAYED:
        return hand_name == most_played_hand_name
    return False
