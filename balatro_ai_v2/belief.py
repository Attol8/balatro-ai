"""Exact chance calculations over the policy-visible draw-pile multiset."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from math import comb
from typing import TypeAlias

from balatro_ai_v2.public_state import DeckCardCount, PublicObservation, VisiblePlayingCard


CardPredicate: TypeAlias = Callable[[VisiblePlayingCard], bool]


@dataclass(frozen=True, slots=True)
class PublicDrawBelief:
    """Exchangeable public belief; it contains composition, never draw order."""

    remaining_deck: tuple[DeckCardCount, ...]
    draw_count: int

    def __post_init__(self) -> None:
        if isinstance(self.draw_count, bool) or not isinstance(self.draw_count, int):
            raise ValueError("draw_count must be an integer")
        if self.draw_count < 0:
            raise ValueError("draw_count must be non-negative")
        for entry in self.remaining_deck:
            if isinstance(entry.count, bool) or not isinstance(entry.count, int) or entry.count <= 0:
                raise ValueError("remaining-deck counts must be positive integers")
        if sum(entry.count for entry in self.remaining_deck) != self.draw_count:
            raise ValueError("remaining-deck counts must sum to draw_count")

    @classmethod
    def from_observation(cls, observation: PublicObservation) -> PublicDrawBelief:
        return cls(observation.remaining_deck, observation.draw_count)

    def matching_count(self, predicate: CardPredicate) -> int:
        return sum(entry.count for entry in self.remaining_deck if predicate(entry.card))

    def expected_matches(self, predicate: CardPredicate, draws: int) -> Fraction:
        self._validate_draws(draws)
        if self.draw_count == 0:
            return Fraction(0)
        return Fraction(draws * self.matching_count(predicate), self.draw_count)

    def probability_at_least(
        self,
        predicate: CardPredicate,
        draws: int,
        minimum_matches: int = 1,
    ) -> Fraction:
        self._validate_draws(draws)
        if (
            isinstance(minimum_matches, bool)
            or not isinstance(minimum_matches, int)
            or minimum_matches < 0
        ):
            raise ValueError("minimum_matches must be a non-negative integer")
        if minimum_matches == 0:
            return Fraction(1)
        if minimum_matches > draws:
            return Fraction(0)

        matching = self.matching_count(predicate)
        non_matching = self.draw_count - matching
        numerator = sum(
            _comb_or_zero(matching, selected) * _comb_or_zero(non_matching, draws - selected)
            for selected in range(minimum_matches, min(matching, draws) + 1)
        )
        return Fraction(numerator, comb(self.draw_count, draws))

    def _validate_draws(self, draws: int) -> None:
        if isinstance(draws, bool) or not isinstance(draws, int):
            raise ValueError("draws must be an integer")
        if not 0 <= draws <= self.draw_count:
            raise ValueError("draws must be between zero and draw_count")


def _comb_or_zero(population: int, selections: int) -> int:
    if selections < 0 or selections > population:
        return 0
    return comb(population, selections)
