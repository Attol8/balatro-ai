"""Typed, public-information rules for the 28 vanilla boss blinds.

This is deliberately a small catalog, rather than a parser for Balatro text or
an engine adapter.  A missing name returns ``None`` so callers cannot silently
make up a rule for an unknown blind.
"""

from dataclasses import dataclass
from enum import Enum


PINNED_GAME_MODEL = "Balatro-1.0.1o-model"


class BossConstraint(str, Enum):
    SCORE_MULTIPLIER = "score_multiplier"
    HIGH_TARGET = "high_target"
    FORCED_HANDS = "forced_hands"
    FORCED_DISCARDS = "forced_discards"
    MIN_SELECTED_CARDS = "min_selected_cards"
    REPEAT_HAND_RESTRICTION = "repeat_hand_restriction"
    SINGLE_HAND_FAMILY = "single_hand_family"
    RANK_DEBUFF = "rank_debuff"
    SUIT_DEBUFF = "suit_debuff"
    FACE_DEBUFF = "face_debuff"
    LEVEL_REDUCTION = "level_reduction"
    SCORE_REDUCTION = "score_reduction"
    FORCED_SLOT = "forced_slot"
    JOKER_DEBUFF = "joker_debuff"
    JOKER_ORDER = "joker_order"
    SELL_TO_DISABLE = "sell_to_disable"
    MONEY_PENALTY = "money_penalty"
    HAND_SIZE_REDUCTION = "hand_size_reduction"
    FACE_DOWN = "face_down"
    RANDOM_DISCARD = "random_discard"
    PLAYED_CARD_DEBUFF = "played_card_debuff"
    DRAW_COUNT_OVERRIDE = "draw_count_override"
    MOST_PLAYED_HAND_MONEY_RESET = "most_played_hand_money_reset"
    PER_CARD_MONEY_PENALTY = "per_card_money_penalty"
    NONE = "none"


class FaceDownMode(str, Enum):
    FIRST_HAND = "first_hand"
    AFTER_PLAY = "after_play"
    FACE_RANKS = "face_ranks"
    RANDOM_DRAW = "random_draw"


class JokerDisruption(str, Enum):
    SHUFFLE_FACE_DOWN = "shuffle_face_down"
    RANDOM_DEBUFF = "random_debuff"


@dataclass(frozen=True, slots=True)
class BossRule:
    """Only constraints a policy can act on from public game state."""

    name: str
    constraints: frozenset[BossConstraint] = frozenset({BossConstraint.NONE})
    score_multiplier: int | None = None
    high_target: bool = False
    hands_forced: int | None = None
    discards_forced: int | None = None
    min_selected_cards: int | None = None
    hand_size_delta: int = 0
    repeat_hand_restriction: bool = False
    single_hand_family: bool = False
    rank_debuff: tuple[str, ...] = ()
    suit_debuff: tuple[str, ...] = ()
    face_debuff: bool = False
    level_reduction: int = 0
    score_reduction: bool = False
    forced_slot: bool = False
    joker_debuff: bool = False
    joker_order: bool = False
    sell_to_disable: bool = False
    money_penalty: int | None = None
    face_down_cards: bool = False
    random_discard_count: int | None = None
    played_card_debuff: bool = False
    draw_count_override: int | None = None
    money_reset_on_most_played_hand: bool = False
    money_per_card: int | None = None
    face_down_mode: FaceDownMode | None = None
    joker_disruption: JokerDisruption | None = None


def _rule(name: str, *constraints: BossConstraint, **values: object) -> BossRule:
    return BossRule(name, frozenset(constraints) or frozenset({BossConstraint.NONE}), **values)


# Names and public effects are from the pinned vanilla 1.0.1o model.  Keep
# this table explicit: its size and spelling are useful compatibility checks.
BOSS_RULES: tuple[BossRule, ...] = (
    _rule("The Arm", BossConstraint.LEVEL_REDUCTION, level_reduction=1),
    _rule("The Club", BossConstraint.SUIT_DEBUFF, suit_debuff=("C",)),
    _rule("The Eye", BossConstraint.REPEAT_HAND_RESTRICTION, repeat_hand_restriction=True),
    _rule(
        "Amber Acorn",
        BossConstraint.JOKER_ORDER,
        joker_order=True,
        joker_disruption=JokerDisruption.SHUFFLE_FACE_DOWN,
    ),
    _rule("Cerulean Bell", BossConstraint.FORCED_SLOT, forced_slot=True),
    _rule(
        "Crimson Heart",
        BossConstraint.JOKER_DEBUFF,
        joker_debuff=True,
        joker_disruption=JokerDisruption.RANDOM_DEBUFF,
    ),
    _rule("Verdant Leaf", BossConstraint.SELL_TO_DISABLE, sell_to_disable=True),
    _rule("Violet Vessel", BossConstraint.SCORE_MULTIPLIER, BossConstraint.HIGH_TARGET,
          score_multiplier=6, high_target=True),
    _rule(
        "The Fish",
        BossConstraint.FACE_DOWN,
        face_down_cards=True,
        face_down_mode=FaceDownMode.AFTER_PLAY,
    ),
    _rule("The Flint", BossConstraint.SCORE_REDUCTION, score_reduction=True),
    _rule("The Goad", BossConstraint.SUIT_DEBUFF, suit_debuff=("S",)),
    _rule("The Head", BossConstraint.SUIT_DEBUFF, suit_debuff=("H",)),
    _rule("The Hook", BossConstraint.RANDOM_DISCARD, random_discard_count=2),
    _rule(
        "The House",
        BossConstraint.FACE_DOWN,
        face_down_cards=True,
        face_down_mode=FaceDownMode.FIRST_HAND,
    ),
    _rule("The Manacle", BossConstraint.HAND_SIZE_REDUCTION, hand_size_delta=-1),
    _rule(
        "The Mark",
        BossConstraint.FACE_DOWN,
        face_down_cards=True,
        face_down_mode=FaceDownMode.FACE_RANKS,
    ),
    _rule("The Mouth", BossConstraint.SINGLE_HAND_FAMILY, single_hand_family=True),
    _rule("The Needle", BossConstraint.FORCED_HANDS, hands_forced=1),
    # The Ox removes the run's current money, so no fixed amount is encoded.
    _rule(
        "The Ox",
        BossConstraint.MONEY_PENALTY,
        BossConstraint.MOST_PLAYED_HAND_MONEY_RESET,
        money_reset_on_most_played_hand=True,
    ),
    _rule("The Pillar", BossConstraint.PLAYED_CARD_DEBUFF, played_card_debuff=True),
    _rule("The Plant", BossConstraint.FACE_DEBUFF, face_debuff=True),
    _rule("The Psychic", BossConstraint.MIN_SELECTED_CARDS, min_selected_cards=5),
    _rule(
        "The Serpent",
        BossConstraint.DRAW_COUNT_OVERRIDE,
        draw_count_override=3,
    ),
    _rule(
        "The Tooth",
        BossConstraint.MONEY_PENALTY,
        BossConstraint.PER_CARD_MONEY_PENALTY,
        money_per_card=1,
    ),
    _rule("The Wall", BossConstraint.SCORE_MULTIPLIER, BossConstraint.HIGH_TARGET,
          score_multiplier=4, high_target=True),
    _rule("The Water", BossConstraint.FORCED_DISCARDS, discards_forced=0),
    _rule(
        "The Wheel",
        BossConstraint.FACE_DOWN,
        face_down_cards=True,
        face_down_mode=FaceDownMode.RANDOM_DRAW,
    ),
    _rule("The Window", BossConstraint.SUIT_DEBUFF, suit_debuff=("D",)),
)

_BY_NAME = {rule.name.casefold(): rule for rule in BOSS_RULES}


def boss_rule(public_name: str) -> BossRule | None:
    """Return a rule for a semantic public boss name, or ``None`` unknown."""

    if not isinstance(public_name, str):
        return None
    return _BY_NAME.get(" ".join(public_name.split()).casefold())


def all_boss_rules() -> tuple[BossRule, ...]:
    return BOSS_RULES
