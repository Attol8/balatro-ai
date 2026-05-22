from __future__ import annotations

from random import Random

NUM_CARDS = 52
NUM_RANKS = 13
NUM_SUITS = 4

RANK_CHIPS = (2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11)
RANK_LABELS = ("2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A")
SUIT_LABELS = ("S", "H", "C", "D")


def rank(card: int) -> int:
    return card % NUM_RANKS


def suit(card: int) -> int:
    return card // NUM_RANKS


def chips(card: int) -> int:
    return RANK_CHIPS[rank(card)]


def label(card: int) -> str:
    return f"{RANK_LABELS[rank(card)]}{SUIT_LABELS[suit(card)]}"


def shuffled_deck(seed: int) -> list[int]:
    deck = list(range(NUM_CARDS))
    Random(seed).shuffle(deck)
    return deck

