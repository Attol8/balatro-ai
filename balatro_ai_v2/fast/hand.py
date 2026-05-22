from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from balatro_ai_v2.fast.card_state import FastCardState
from balatro_ai_v2.fast.cards import chips, rank, suit
from balatro_ai_v2.fast.modifiers import (
    Edition,
    Enhancement,
    Seal,
    edition_chip_bonus,
    edition_mult_bonus,
    edition_xmult,
    enhancement_chip_bonus,
    enhancement_mult_bonus,
    enhancement_xmult,
)

HIGH_CARD = 0
PAIR = 1
TWO_PAIR = 2
THREE_OF_A_KIND = 3
STRAIGHT = 4
FLUSH = 5
FULL_HOUSE = 6
FOUR_OF_A_KIND = 7
STRAIGHT_FLUSH = 8
FIVE_OF_A_KIND = 9
FLUSH_HOUSE = 10
FLUSH_FIVE = 11

HAND_KIND_NAMES = (
    "High Card",
    "Pair",
    "Two Pair",
    "Three of a Kind",
    "Straight",
    "Flush",
    "Full House",
    "Four of a Kind",
    "Straight Flush",
    "Five of a Kind",
    "Flush House",
    "Flush Five",
)

BASE_CHIPS = (5, 10, 20, 30, 30, 35, 40, 60, 100, 120, 140, 160)
BASE_MULT = (1, 2, 2, 3, 4, 4, 4, 7, 8, 12, 14, 16)
LEVEL_CHIPS = (10, 15, 20, 20, 30, 15, 25, 30, 40, 35, 40, 50)
LEVEL_MULT = (1, 1, 1, 2, 3, 2, 2, 3, 4, 3, 4, 3)


@dataclass(frozen=True, slots=True)
class FastScore:
    kind: int
    chips: int
    mult: float
    total: int
    scoring_mask: int


@dataclass(frozen=True, slots=True)
class FastStateScore:
    score: FastScore
    scoring_indices: tuple[int, ...]
    money_delta: int = 0


def score_cards(cards: tuple[int, ...]) -> FastScore:
    if not 1 <= len(cards) <= 5:
        raise ValueError("a played hand must contain between 1 and 5 cards")
    kind, hand_chips, mult, total, scoring_mask = _score_values_sorted(tuple(sorted(cards)))
    return FastScore(
        kind=kind,
        chips=hand_chips,
        mult=mult,
        total=total,
        scoring_mask=scoring_mask,
    )


def score_cards_with_levels(cards: tuple[int, ...], hand_levels: tuple[int, ...]) -> FastScore:
    if len(hand_levels) != len(HAND_KIND_NAMES):
        raise ValueError(f"hand_levels must contain {len(HAND_KIND_NAMES)} values")
    base = score_cards(cards)
    level = max(hand_levels[base.kind], 1)
    chips_with_level = base.chips + (level - 1) * LEVEL_CHIPS[base.kind]
    mult_with_level = base.mult + (level - 1) * LEVEL_MULT[base.kind]
    return FastScore(
        kind=base.kind,
        chips=chips_with_level,
        mult=mult_with_level,
        total=chips_with_level * mult_with_level,
        scoring_mask=base.scoring_mask,
    )


def score_cards_with_modifiers(
    cards: tuple[int, ...],
    hand_levels: tuple[int, ...],
    enhancements: tuple[Enhancement, ...],
    editions: tuple[Edition, ...],
) -> FastScore:
    if len(cards) != len(enhancements) or len(cards) != len(editions):
        raise ValueError("cards, enhancements, and editions must have matching lengths")
    if any(enhancement == Enhancement.LUCKY for enhancement in enhancements):
        raise NotImplementedError("Lucky Card scoring is probabilistic and needs min/exact/max support")
    if any(enhancement == Enhancement.STEEL for enhancement in enhancements):
        raise NotImplementedError("Steel Card scoring applies while held in hand, not as a played card")

    indexed_cards = tuple(sorted(enumerate(cards), key=lambda item: item[1]))
    sorted_cards = tuple(card for _, card in indexed_cards)
    base = score_cards_with_levels(sorted_cards, hand_levels)

    hand_chips = base.chips
    mult = float(base.mult)
    for sorted_index, (original_index, _) in enumerate(indexed_cards):
        if not base.scoring_mask & (1 << sorted_index):
            continue
        enhancement = enhancements[original_index]
        edition = editions[original_index]
        hand_chips += enhancement_chip_bonus(enhancement)
        hand_chips += edition_chip_bonus(edition)
        mult += enhancement_mult_bonus(enhancement)
        mult += edition_mult_bonus(edition)
        mult *= enhancement_xmult(enhancement)
        mult *= edition_xmult(edition)

    return FastScore(
        kind=base.kind,
        chips=hand_chips,
        mult=mult,
        total=int(hand_chips * mult),
        scoring_mask=base.scoring_mask,
    )


def score_card_states(
    cards: tuple[FastCardState, ...],
    hand_levels: tuple[int, ...],
    held_cards: tuple[FastCardState, ...] = (),
) -> FastStateScore:
    if not 1 <= len(cards) <= 5:
        raise ValueError("a played hand must contain between 1 and 5 cards")
    if len(hand_levels) != len(HAND_KIND_NAMES):
        raise ValueError(f"hand_levels must contain {len(HAND_KIND_NAMES)} values")
    if any(card.enhancement == Enhancement.LUCKY for card in cards):
        raise NotImplementedError("Lucky Card scoring is probabilistic and needs min/exact/max support")

    stone_indices = tuple(
        index for index, card in enumerate(cards) if card.enhancement == Enhancement.STONE
    )
    non_stone = tuple(
        (index, card.card_id)
        for index, card in enumerate(cards)
        if card.enhancement != Enhancement.STONE
    )

    if non_stone:
        sorted_non_stone = tuple(sorted(non_stone, key=lambda item: item[1]))
        sorted_card_ids = tuple(card_id for _, card_id in sorted_non_stone)
        base = score_cards_with_levels(sorted_card_ids, hand_levels)
        scoring_indices = tuple(
            original_index
            for sorted_index, (original_index, _) in enumerate(sorted_non_stone)
            if base.scoring_mask & (1 << sorted_index)
        )
    else:
        level = max(hand_levels[HIGH_CARD], 1)
        hand_chips = BASE_CHIPS[HIGH_CARD] + (level - 1) * LEVEL_CHIPS[HIGH_CARD]
        mult = BASE_MULT[HIGH_CARD] + (level - 1) * LEVEL_MULT[HIGH_CARD]
        base = FastScore(
            kind=HIGH_CARD,
            chips=hand_chips,
            mult=mult,
            total=hand_chips * mult,
            scoring_mask=0,
        )
        scoring_indices = ()

    scoring_set = set(scoring_indices) | set(stone_indices)
    scoring_in_play_order = tuple(index for index in range(len(cards)) if index in scoring_set)

    hand_chips = base.chips
    mult = float(base.mult)
    money_delta = 0
    for index in scoring_in_play_order:
        card = cards[index]
        repeat_count = 2 if card.seal == Seal.RED else 1
        for _ in range(repeat_count):
            if card.enhancement != Enhancement.STONE:
                hand_chips += card.bonus_chips
                mult += card.bonus_mult
            hand_chips += enhancement_chip_bonus(card.enhancement)
            hand_chips += edition_chip_bonus(card.edition)
            mult += enhancement_mult_bonus(card.enhancement)
            mult += edition_mult_bonus(card.edition)
            mult *= enhancement_xmult(card.enhancement)
            mult *= edition_xmult(card.edition)
            if card.seal == Seal.GOLD:
                money_delta += 3

    for held_card in held_cards:
        if held_card.enhancement == Enhancement.STEEL:
            mult *= 1.5
        if held_card.edition == Edition.POLYCHROME:
            mult *= 1.5

    final_score = FastScore(
        kind=base.kind,
        chips=hand_chips,
        mult=mult,
        total=int(hand_chips * mult),
        scoring_mask=sum(1 << index for index in scoring_in_play_order),
    )
    return FastStateScore(
        score=final_score,
        scoring_indices=scoring_in_play_order,
        money_delta=money_delta,
    )


def held_card_end_money(cards: tuple[FastCardState, ...]) -> int:
    return sum(3 for card in cards if card.enhancement == Enhancement.GOLD)


def score_cards_with_jokers(
    cards: tuple[int, ...],
    hand_levels: tuple[int, ...],
    joker_keys: tuple[str, ...],
) -> FastScore:
    from balatro_ai_v2.fast.jokers import Joker, apply_additive_jokers

    sorted_cards = tuple(sorted(cards))
    base = score_cards_with_levels(sorted_cards, hand_levels)
    jokers = tuple(Joker(key) for key in joker_keys)
    return apply_additive_jokers(base, sorted_cards, len(cards), jokers)


def best_score(hand: tuple[int, ...], action_ids: tuple[int, ...]) -> tuple[int, FastScore]:
    best_action = -1
    best_values = (HIGH_CARD, 0, 0, -1, 0)
    for action_id in action_ids:
        values = _score_values_sorted(tuple(sorted(_cards_from_mask(hand, action_id))))
        if values[3] > best_values[3]:
            best_action = action_id
            best_values = values
    kind, hand_chips, mult, total, scoring_mask = best_values
    return best_action, FastScore(
        kind=kind,
        chips=hand_chips,
        mult=mult,
        total=total,
        scoring_mask=scoring_mask,
    )


@lru_cache(maxsize=250_000)
def _score_values_sorted(cards: tuple[int, ...]) -> tuple[int, int, int, int, int]:
    ranks = [rank(card) for card in cards]
    suits = [suit(card) for card in cards]
    counts = [0] * 13
    for card_rank in ranks:
        counts[card_rank] += 1
    groups = sorted((count for count in counts if count), reverse=True)

    is_five = len(cards) == 5
    is_flush = is_five and suits.count(suits[0]) == 5
    unique_ranks = sorted(rank_value for rank_value, count in enumerate(counts) if count)
    is_straight = is_five and _is_straight(unique_ranks)

    if is_flush and groups == [5]:
        return _score(FLUSH_FIVE, cards, 0b11111)
    if is_flush and groups == [3, 2]:
        return _score(FLUSH_HOUSE, cards, 0b11111)
    if groups == [5]:
        return _score(FIVE_OF_A_KIND, cards, 0b11111)
    if is_flush and is_straight:
        return _score(STRAIGHT_FLUSH, cards, 0b11111)
    if groups[0] == 4:
        return _score_matching_count(FOUR_OF_A_KIND, cards, counts, 4)
    if groups == [3, 2]:
        return _score(FULL_HOUSE, cards, 0b11111)
    if is_flush:
        return _score(FLUSH, cards, 0b11111)
    if is_straight:
        return _score(STRAIGHT, cards, 0b11111)
    if groups[0] == 3:
        return _score_matching_count(THREE_OF_A_KIND, cards, counts, 3)
    if groups.count(2) == 2:
        return _score_matching_count(TWO_PAIR, cards, counts, 2)
    if groups[0] == 2:
        return _score_matching_count(PAIR, cards, counts, 2)

    best_index = max(range(len(cards)), key=lambda index: rank(cards[index]))
    return _score(HIGH_CARD, cards, 1 << best_index)


def _score(kind: int, cards: tuple[int, ...], scoring_mask: int) -> tuple[int, int, int, int, int]:
    hand_chips = BASE_CHIPS[kind]
    for index, card in enumerate(cards):
        if scoring_mask & (1 << index):
            hand_chips += chips(card)
    mult = BASE_MULT[kind]
    return kind, hand_chips, mult, hand_chips * mult, scoring_mask


def _score_matching_count(
    kind: int, cards: tuple[int, ...], counts: list[int], target_count: int
) -> tuple[int, int, int, int, int]:
    scoring_mask = 0
    for index, card in enumerate(cards):
        if counts[rank(card)] == target_count:
            scoring_mask |= 1 << index
    return _score(kind, cards, scoring_mask)


def _is_straight(unique_ranks: list[int]) -> bool:
    if len(unique_ranks) != 5:
        return False
    if unique_ranks == [0, 1, 2, 3, 12]:
        return True
    return unique_ranks[-1] - unique_ranks[0] == 4


def _cards_from_mask(hand: tuple[int, ...], mask: int) -> tuple[int, ...]:
    return tuple(card for index, card in enumerate(hand) if mask & (1 << index))
