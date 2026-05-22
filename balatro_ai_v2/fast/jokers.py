from __future__ import annotations

from dataclasses import dataclass, field

from balatro_ai_v2.fast.cards import chips as card_chips, rank, suit
from balatro_ai_v2.fast.hand import (
    FLUSH,
    FLUSH_FIVE,
    FLUSH_HOUSE,
    FOUR_OF_A_KIND,
    FULL_HOUSE,
    FIVE_OF_A_KIND,
    HIGH_CARD,
    PAIR,
    STRAIGHT,
    STRAIGHT_FLUSH,
    THREE_OF_A_KIND,
    TWO_PAIR,
    FastScore,
)


@dataclass(frozen=True, slots=True)
class Joker:
    key: str
    scaling: int = 0
    x_mult: float = 1.0
    sell_value: int = 0
    edition: int = 0


@dataclass(frozen=True, slots=True)
class ScoreContext:
    held_cards: tuple[int, ...] = ()
    money: int = 0
    discards_left: int = 0
    hands_left: int = 0
    deck_count: int = 52
    deck_cards: tuple[int, ...] = ()
    joker_slots: int = 5
    is_final_hand: bool = False
    hands_played_this_round: int = 0
    blinds_skipped: int = 0
    hand_times_played: dict[int, int] = field(default_factory=dict)
    hand_times_played_round: dict[int, int] = field(default_factory=dict)


SUIT_MULT_JOKERS = {
    "j_greedy_joker": (3, 3),
    "j_lusty_joker": (1, 3),
    "j_wrathful_joker": (0, 3),
    "j_gluttenous_joker": (2, 3),
}

TYPE_MULT_JOKERS = {
    "j_jolly": (PAIR, 8),
    "j_zany": (THREE_OF_A_KIND, 12),
    "j_mad": (TWO_PAIR, 10),
    "j_crazy": (STRAIGHT, 12),
    "j_droll": (FLUSH, 10),
}

TYPE_CHIP_JOKERS = {
    "j_sly": (PAIR, 50),
    "j_wily": (THREE_OF_A_KIND, 100),
    "j_clever": (TWO_PAIR, 80),
    "j_devious": (STRAIGHT, 100),
    "j_crafty": (FLUSH, 80),
}

CONTAINED_TYPE_MULT_JOKERS = {
    "j_jolly": (PAIR, 8),
    "j_zany": (THREE_OF_A_KIND, 12),
    "j_mad": (TWO_PAIR, 10),
    "j_crazy": (STRAIGHT, 12),
    "j_droll": (FLUSH, 10),
}

CONTAINED_TYPE_CHIP_JOKERS = {
    "j_sly": (PAIR, 50),
    "j_wily": (THREE_OF_A_KIND, 100),
    "j_clever": (TWO_PAIR, 80),
    "j_devious": (STRAIGHT, 100),
    "j_crafty": (FLUSH, 80),
}

CONTAINED_TYPE_XMULT_JOKERS = {
    "j_duo": (PAIR, 2.0),
    "j_trio": (THREE_OF_A_KIND, 3.0),
    "j_order": (STRAIGHT, 3.0),
    "j_tribe": (FLUSH, 2.0),
}

IMPLEMENTED_JOKERS = frozenset(
    {
        "j_joker",
        "j_half",
        "j_even_steven",
        "j_odd_todd",
        "j_scholar",
        *SUIT_MULT_JOKERS.keys(),
        *TYPE_MULT_JOKERS.keys(),
        *TYPE_CHIP_JOKERS.keys(),
        *CONTAINED_TYPE_XMULT_JOKERS.keys(),
        "j_stencil",
        "j_banner",
        "j_mystic_summit",
        "j_misprint",
        "j_abstract",
        "j_supernova",
        "j_blue_joker",
        "j_bull",
        "j_bootstraps",
        "j_ice_cream",
        "j_runner",
        "j_green_joker",
        "j_ride_the_bus",
        "j_cavendish",
        "j_acrobat",
        "j_family",
        "j_stuntman",
        "j_popcorn",
        "j_constellation",
        "j_ramen",
        "j_throwback",
        "j_swashbuckler",
        "j_baseball",
        "j_blackboard",
        "j_obelisk",
        "j_steel_joker",
        "j_gros_michel",
        "j_vampire",
        "j_glass",
        "j_seeing_double",
        "j_fibonacci",
        "j_scary_face",
        "j_smiley",
        "j_walkie_talkie",
        "j_photograph",
        "j_bloodstone",
        "j_triboulet",
        "j_arrowhead",
        "j_onyx_agate",
    }
)


def apply_additive_jokers(
    score: FastScore,
    sorted_cards: tuple[int, ...],
    selected_count: int,
    jokers: tuple[Joker, ...],
    context: ScoreContext | None = None,
) -> FastScore:
    context = context or ScoreContext()
    chips = score.chips
    mult = float(score.mult)
    x_mult = 1.0

    for joker in jokers:
        if joker.key == "j_joker":
            mult += 4
        elif joker.key == "j_half" and selected_count <= 3:
            mult += 20
        elif joker.key == "j_stencil":
            x_mult *= 1.0 + max(context.joker_slots - len(jokers), 0)
        elif joker.key == "j_banner":
            chips += 30 * context.discards_left
        elif joker.key == "j_mystic_summit" and context.discards_left == 0:
            mult += 15
        elif joker.key == "j_misprint":
            mult += joker.scaling if joker.scaling > 0 else 12
        elif joker.key == "j_abstract":
            mult += 3 * len(jokers)
        elif joker.key == "j_supernova":
            mult += context.hand_times_played.get(score.kind, 0)
        elif joker.key == "j_blue_joker":
            chips += 2 * context.deck_count
        elif joker.key == "j_bull":
            chips += 2 * context.money
        elif joker.key == "j_bootstraps":
            mult += 2 * (context.money // 5)
        elif joker.key == "j_ice_cream":
            chips += joker.scaling
        elif joker.key == "j_runner" and score.kind == STRAIGHT:
            chips += joker.scaling
        elif joker.key == "j_green_joker":
            mult += joker.scaling
        elif joker.key == "j_ride_the_bus" and not _has_face_card(sorted_cards):
            mult += joker.scaling
        elif joker.key == "j_cavendish":
            x_mult *= 3.0
        elif joker.key == "j_acrobat" and context.hands_left == 0:
            x_mult *= 3.0
        elif joker.key == "j_family" and score.kind == FOUR_OF_A_KIND:
            x_mult *= 4.0
        elif joker.key == "j_stuntman":
            chips += 250
        elif joker.key == "j_popcorn":
            mult += joker.scaling
        elif joker.key == "j_constellation":
            x_mult *= joker.x_mult
        elif joker.key == "j_ramen":
            x_mult *= joker.x_mult if joker.x_mult > 0 else 2.0
        elif joker.key == "j_throwback":
            x_mult *= 1.0 + 0.25 * context.blinds_skipped
        elif joker.key == "j_swashbuckler":
            mult += sum(other.sell_value for other in jokers if other is not joker)
        elif joker.key == "j_blackboard" and context.held_cards:
            if all(suit(card) in (0, 2) for card in context.held_cards):
                x_mult *= 3.0
        elif joker.key == "j_obelisk":
            x_mult *= joker.x_mult
        elif joker.key == "j_steel_joker":
            x_mult *= 1.0 + 0.2 * joker.scaling
        elif joker.key == "j_gros_michel":
            mult += 15
        elif joker.key == "j_vampire":
            x_mult *= joker.x_mult
        elif joker.key == "j_glass":
            x_mult *= joker.x_mult
        elif joker.key == "j_seeing_double" and _has_club_and_other_suit(sorted_cards, score.scoring_mask):
            x_mult *= 2.0
        elif joker.key == "j_even_steven":
            mult += _scored_rank_count(sorted_cards, score.scoring_mask, {0, 2, 4, 6, 8}) * 4
        elif joker.key == "j_odd_todd":
            chips += _scored_rank_count(sorted_cards, score.scoring_mask, {1, 3, 5, 7, 12}) * 31
        elif joker.key == "j_scholar":
            aces = _scored_rank_count(sorted_cards, score.scoring_mask, {12})
            chips += aces * 20
            mult += aces * 4
        elif joker.key == "j_fibonacci":
            mult += _scored_rank_count(sorted_cards, score.scoring_mask, {0, 1, 3, 6, 12}) * 8
        elif joker.key == "j_scary_face":
            chips += _scored_face_count(sorted_cards, score.scoring_mask) * 30
        elif joker.key == "j_smiley":
            mult += _scored_face_count(sorted_cards, score.scoring_mask) * 5
        elif joker.key == "j_walkie_talkie":
            count = _scored_rank_count(sorted_cards, score.scoring_mask, {2, 8})
            chips += count * 10
            mult += count * 4
        elif joker.key == "j_photograph" and _scored_face_count(sorted_cards, score.scoring_mask) > 0:
            x_mult *= 2.0
        elif joker.key == "j_bloodstone":
            x_mult *= 1.25 ** _scored_suit_count(sorted_cards, score.scoring_mask, 1)
        elif joker.key == "j_triboulet":
            x_mult *= 2.0 ** _scored_rank_count(sorted_cards, score.scoring_mask, {10, 11})
        elif joker.key in SUIT_MULT_JOKERS:
            target_suit, add_mult = SUIT_MULT_JOKERS[joker.key]
            mult += _scored_suit_count(sorted_cards, score.scoring_mask, target_suit) * add_mult
        elif joker.key == "j_arrowhead":
            chips += _scored_suit_count(sorted_cards, score.scoring_mask, 0) * 50
        elif joker.key == "j_onyx_agate":
            mult += _scored_suit_count(sorted_cards, score.scoring_mask, 2) * 7
        elif joker.key in CONTAINED_TYPE_MULT_JOKERS:
            target_kind, add_mult = CONTAINED_TYPE_MULT_JOKERS[joker.key]
            if _hand_contains(score.kind, target_kind):
                mult += add_mult
        elif joker.key in CONTAINED_TYPE_CHIP_JOKERS:
            target_kind, add_chips = CONTAINED_TYPE_CHIP_JOKERS[joker.key]
            if _hand_contains(score.kind, target_kind):
                chips += add_chips
        elif joker.key in CONTAINED_TYPE_XMULT_JOKERS:
            target_kind, add_xmult = CONTAINED_TYPE_XMULT_JOKERS[joker.key]
            if _hand_contains(score.kind, target_kind):
                x_mult *= add_xmult
        elif joker.key in TYPE_MULT_JOKERS:
            target_kind, add_mult = TYPE_MULT_JOKERS[joker.key]
            if score.kind == target_kind:
                mult += add_mult
        elif joker.key in TYPE_CHIP_JOKERS:
            target_kind, add_chips = TYPE_CHIP_JOKERS[joker.key]
            if score.kind == target_kind:
                chips += add_chips

    return FastScore(
        kind=score.kind,
        chips=chips,
        mult=mult,
        total=int(chips * mult * x_mult),
        scoring_mask=score.scoring_mask,
    )


def _scored_suit_count(cards: tuple[int, ...], scoring_mask: int, target_suit: int) -> int:
    return sum(
        1
        for index, card in enumerate(cards)
        if scoring_mask & (1 << index) and suit(card) == target_suit
    )


def _scored_rank_count(cards: tuple[int, ...], scoring_mask: int, target_ranks: set[int]) -> int:
    return sum(
        1
        for index, card in enumerate(cards)
        if scoring_mask & (1 << index) and rank(card) in target_ranks
    )


def _scored_face_count(cards: tuple[int, ...], scoring_mask: int) -> int:
    return _scored_rank_count(cards, scoring_mask, {9, 10, 11})


def _has_face_card(cards: tuple[int, ...]) -> bool:
    return any(rank(card) in {9, 10, 11} for card in cards)


def _has_club_and_other_suit(cards: tuple[int, ...], scoring_mask: int) -> bool:
    scored_suits = {
        suit(card)
        for index, card in enumerate(cards)
        if scoring_mask & (1 << index)
    }
    return 2 in scored_suits and len(scored_suits) > 1


def _hand_contains(hand_kind: int, contained_kind: int) -> bool:
    if contained_kind == PAIR:
        return hand_kind in {
            PAIR,
            TWO_PAIR,
            THREE_OF_A_KIND,
            FULL_HOUSE,
            FOUR_OF_A_KIND,
            FIVE_OF_A_KIND,
            FLUSH_HOUSE,
            FLUSH_FIVE,
        }
    if contained_kind == TWO_PAIR:
        return hand_kind in {TWO_PAIR, FULL_HOUSE, FLUSH_HOUSE}
    if contained_kind == THREE_OF_A_KIND:
        return hand_kind in {
            THREE_OF_A_KIND,
            FULL_HOUSE,
            FOUR_OF_A_KIND,
            FIVE_OF_A_KIND,
            FLUSH_HOUSE,
            FLUSH_FIVE,
        }
    if contained_kind == STRAIGHT:
        return hand_kind in {STRAIGHT, STRAIGHT_FLUSH}
    if contained_kind == FLUSH:
        return hand_kind in {FLUSH, STRAIGHT_FLUSH, FLUSH_HOUSE, FLUSH_FIVE}
    return hand_kind == contained_kind
