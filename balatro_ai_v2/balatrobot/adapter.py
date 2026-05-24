from __future__ import annotations

from typing import Any

from balatro_ai_v2.fast.cards import NUM_RANKS
from balatro_ai_v2.fast.cards import rank as fast_rank
from balatro_ai_v2.fast.cards import suit as fast_suit

RANK_TO_FAST = {
    "2": 0,
    "3": 1,
    "4": 2,
    "5": 3,
    "6": 4,
    "7": 5,
    "8": 6,
    "9": 7,
    "T": 8,
    "10": 8,
    "J": 9,
    "Q": 10,
    "K": 11,
    "A": 12,
}

SUIT_TO_FAST = {
    "S": 0,
    "Spades": 0,
    "H": 1,
    "Hearts": 1,
    "C": 2,
    "Clubs": 2,
    "D": 3,
    "Diamonds": 3,
}


def card_to_fast_id(card: dict[str, Any]) -> int:
    value = card.get("value") or {}
    rank_value = value.get("rank")
    suit_value = value.get("suit")

    if rank_value is None or suit_value is None:
        key = card.get("key")
        if isinstance(key, str) and "_" in key:
            suit_value, rank_value = key.split("_", 1)

    if rank_value not in RANK_TO_FAST:
        raise ValueError(f"unsupported BalatroBot rank: {rank_value!r}")
    if suit_value not in SUIT_TO_FAST:
        raise ValueError(f"unsupported BalatroBot suit: {suit_value!r}")

    return SUIT_TO_FAST[suit_value] * NUM_RANKS + RANK_TO_FAST[rank_value]


def hand_to_fast_ids(state: dict[str, Any]) -> tuple[int, ...]:
    hand = state.get("hand") or {}
    cards = hand.get("cards") or []
    if not isinstance(cards, list):
        raise ValueError("BalatroBot state hand.cards must be a list")
    return tuple(card_to_fast_id(card) for card in cards)


def balatro_hand_sort_key(card_id: int) -> tuple[int, int]:
    """Balatro keeps visible hands sorted by high rank, then suit order."""
    return (-fast_rank(card_id), fast_suit(card_id))


def sort_balatro_hand(cards: tuple[int, ...]) -> tuple[int, ...]:
    return tuple(sorted(cards, key=balatro_hand_sort_key))
