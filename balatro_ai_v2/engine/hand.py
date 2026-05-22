from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum

from balatro_ai_v2.engine.cards import Card, RANK_ORDER, Rank


class HandKind(str, Enum):
    HIGH_CARD = "High Card"
    PAIR = "Pair"
    TWO_PAIR = "Two Pair"
    THREE_OF_A_KIND = "Three of a Kind"
    STRAIGHT = "Straight"
    FLUSH = "Flush"
    FULL_HOUSE = "Full House"
    FOUR_OF_A_KIND = "Four of a Kind"
    STRAIGHT_FLUSH = "Straight Flush"
    FIVE_OF_A_KIND = "Five of a Kind"
    FLUSH_HOUSE = "Flush House"
    FLUSH_FIVE = "Flush Five"


BASE_SCORES: dict[HandKind, tuple[int, int]] = {
    HandKind.HIGH_CARD: (5, 1),
    HandKind.PAIR: (10, 2),
    HandKind.TWO_PAIR: (20, 2),
    HandKind.THREE_OF_A_KIND: (30, 3),
    HandKind.STRAIGHT: (30, 4),
    HandKind.FLUSH: (35, 4),
    HandKind.FULL_HOUSE: (40, 4),
    HandKind.FOUR_OF_A_KIND: (60, 7),
    HandKind.STRAIGHT_FLUSH: (100, 8),
    HandKind.FIVE_OF_A_KIND: (120, 12),
    HandKind.FLUSH_HOUSE: (140, 14),
    HandKind.FLUSH_FIVE: (160, 16),
}


@dataclass(frozen=True, slots=True)
class HandEvaluation:
    kind: HandKind
    scoring_cards: tuple[Card, ...]
    base_chips: int
    base_mult: int


def evaluate_hand(cards: tuple[Card, ...]) -> HandEvaluation:
    if not 1 <= len(cards) <= 5:
        raise ValueError("a played hand must contain between 1 and 5 cards")

    ordered = tuple(sorted(cards, key=_card_sort_key, reverse=True))
    rank_counts = Counter(card.rank for card in ordered)
    count_groups = sorted(rank_counts.values(), reverse=True)
    is_five_card = len(ordered) == 5
    is_flush = is_five_card and len({card.suit for card in ordered}) == 1
    is_straight = is_five_card and _is_straight(tuple(card.rank for card in ordered))

    if is_flush and count_groups == [5]:
        return _evaluation(HandKind.FLUSH_FIVE, ordered)
    if is_flush and count_groups == [3, 2]:
        return _evaluation(HandKind.FLUSH_HOUSE, ordered)
    if count_groups == [5]:
        return _evaluation(HandKind.FIVE_OF_A_KIND, ordered)
    if is_flush and is_straight:
        return _evaluation(HandKind.STRAIGHT_FLUSH, ordered)
    if count_groups[0] == 4:
        return _evaluation(HandKind.FOUR_OF_A_KIND, _cards_with_count(ordered, rank_counts, 4))
    if count_groups == [3, 2]:
        return _evaluation(HandKind.FULL_HOUSE, ordered)
    if is_flush:
        return _evaluation(HandKind.FLUSH, ordered)
    if is_straight:
        return _evaluation(HandKind.STRAIGHT, ordered)
    if count_groups[0] == 3:
        return _evaluation(HandKind.THREE_OF_A_KIND, _cards_with_count(ordered, rank_counts, 3))
    if count_groups.count(2) == 2:
        return _evaluation(HandKind.TWO_PAIR, _cards_with_count(ordered, rank_counts, 2))
    if count_groups[0] == 2:
        return _evaluation(HandKind.PAIR, _cards_with_count(ordered, rank_counts, 2))
    return _evaluation(HandKind.HIGH_CARD, (ordered[0],))


def _evaluation(kind: HandKind, scoring_cards: tuple[Card, ...]) -> HandEvaluation:
    chips, mult = BASE_SCORES[kind]
    return HandEvaluation(kind=kind, scoring_cards=scoring_cards, base_chips=chips, base_mult=mult)


def _cards_with_count(
    ordered: tuple[Card, ...], rank_counts: Counter[Rank], count: int
) -> tuple[Card, ...]:
    return tuple(card for card in ordered if rank_counts[card.rank] == count)


def _is_straight(ranks: tuple[Rank, ...]) -> bool:
    values = sorted({RANK_ORDER[rank] for rank in ranks})
    if len(values) != 5:
        return False
    if values == [2, 3, 4, 5, 14]:
        return True
    return values[-1] - values[0] == 4


def _card_sort_key(card: Card) -> tuple[int, str]:
    return RANK_ORDER[card.rank], card.suit.value

