from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from random import Random
from typing import Iterable


class Suit(str, Enum):
    SPADES = "S"
    HEARTS = "H"
    CLUBS = "C"
    DIAMONDS = "D"


class Rank(str, Enum):
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"
    SIX = "6"
    SEVEN = "7"
    EIGHT = "8"
    NINE = "9"
    TEN = "T"
    JACK = "J"
    QUEEN = "Q"
    KING = "K"
    ACE = "A"


RANK_ORDER: dict[Rank, int] = {
    Rank.TWO: 2,
    Rank.THREE: 3,
    Rank.FOUR: 4,
    Rank.FIVE: 5,
    Rank.SIX: 6,
    Rank.SEVEN: 7,
    Rank.EIGHT: 8,
    Rank.NINE: 9,
    Rank.TEN: 10,
    Rank.JACK: 11,
    Rank.QUEEN: 12,
    Rank.KING: 13,
    Rank.ACE: 14,
}

RANK_CHIPS: dict[Rank, int] = {
    Rank.TWO: 2,
    Rank.THREE: 3,
    Rank.FOUR: 4,
    Rank.FIVE: 5,
    Rank.SIX: 6,
    Rank.SEVEN: 7,
    Rank.EIGHT: 8,
    Rank.NINE: 9,
    Rank.TEN: 10,
    Rank.JACK: 10,
    Rank.QUEEN: 10,
    Rank.KING: 10,
    Rank.ACE: 11,
}


@dataclass(frozen=True, slots=True, order=True)
class Card:
    rank: Rank
    suit: Suit

    @property
    def chips(self) -> int:
        return RANK_CHIPS[self.rank]

    def __str__(self) -> str:
        return f"{self.rank.value}{self.suit.value}"


@dataclass(frozen=True, slots=True)
class Deck:
    cards: tuple[Card, ...]

    def shuffle(self, seed: int) -> Deck:
        cards = list(self.cards)
        Random(seed).shuffle(cards)
        return Deck(tuple(cards))

    def draw(self, count: int) -> tuple[tuple[Card, ...], Deck]:
        if count < 0:
            raise ValueError("draw count cannot be negative")
        if count > len(self.cards):
            raise ValueError("cannot draw more cards than remain in deck")
        return self.cards[:count], Deck(self.cards[count:])

    def remove(self, cards_to_remove: Iterable[Card]) -> Deck:
        remaining = list(self.cards)
        for card in cards_to_remove:
            remaining.remove(card)
        return Deck(tuple(remaining))


def standard_deck() -> Deck:
    return Deck(tuple(Card(rank, suit) for suit in Suit for rank in Rank))

