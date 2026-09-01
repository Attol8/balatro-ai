"""Exact chance calculations over the policy-visible draw-pile multiset."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from fractions import Fraction
from math import comb
from typing import TypeAlias

from balatro_ai_v2.public_state import DeckCardCount, PublicObservation, VisiblePlayingCard


CardPredicate: TypeAlias = Callable[[VisiblePlayingCard], bool]


class DrawOutcomeLimitExceeded(RuntimeError):
    """The exact public draw distribution is larger than the declared budget."""


@dataclass(frozen=True, slots=True)
class PublicDrawOutcome:
    drawn_cards: tuple[VisiblePlayingCard, ...]
    remaining_deck: tuple[DeckCardCount, ...]
    probability: Fraction


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

    def exact_outcomes(
        self,
        draws: int,
        *,
        max_outcomes: int | None = None,
    ) -> tuple[PublicDrawOutcome, ...]:
        """Enumerate the exact unordered refill distribution.

        Cards with identical public scoring semantics are merged before the
        multivariate-hypergeometric count vectors are enumerated.  No hidden
        draw order is constructed or consulted.
        """

        self._validate_draws(draws)
        if max_outcomes is not None and (
            isinstance(max_outcomes, bool)
            or not isinstance(max_outcomes, int)
            or max_outcomes <= 0
        ):
            raise ValueError("max_outcomes must be a positive integer")
        deck = canonical_remaining_deck(self.remaining_deck)
        if draws == 0:
            return (PublicDrawOutcome((), deck, Fraction(1)),)

        denominator = comb(self.draw_count, draws)
        outcomes: list[PublicDrawOutcome] = []

        def visit(index: int, remaining: int, selected: list[int], weight: int) -> None:
            if max_outcomes is not None and len(outcomes) >= max_outcomes:
                raise DrawOutcomeLimitExceeded(
                    f"exact draw distribution exceeds {max_outcomes} outcomes"
                )
            if index == len(deck):
                if remaining != 0:
                    return
                drawn = tuple(
                    entry.card
                    for entry, count in zip(deck, selected, strict=True)
                    for _ in range(count)
                )
                rest = tuple(
                    DeckCardCount(entry.card, entry.count - count)
                    for entry, count in zip(deck, selected, strict=True)
                    if entry.count > count
                )
                outcomes.append(
                    PublicDrawOutcome(
                        drawn_cards=drawn,
                        remaining_deck=rest,
                        probability=Fraction(weight, denominator),
                    )
                )
                return

            entry = deck[index]
            minimum = max(0, remaining - sum(item.count for item in deck[index + 1 :]))
            maximum = min(entry.count, remaining)
            for count in range(minimum, maximum + 1):
                selected.append(count)
                visit(
                    index + 1,
                    remaining - count,
                    selected,
                    weight * comb(entry.count, count),
                )
                selected.pop()

        visit(0, draws, [], 1)
        if sum((outcome.probability for outcome in outcomes), Fraction(0)) != 1:
            raise ValueError("exact draw probabilities do not sum to one")
        return tuple(outcomes)


def canonical_remaining_deck(
    remaining_deck: tuple[DeckCardCount, ...],
) -> tuple[DeckCardCount, ...]:
    """Merge and sort a public deck multiset without using presentation text."""

    merged: dict[tuple[object, ...], tuple[VisiblePlayingCard, int]] = {}
    for entry in remaining_deck:
        key = visible_card_semantic_key(entry.card)
        card, count = merged.get(key, (canonical_visible_card(entry.card), 0))
        merged[key] = (card, count + entry.count)
    return tuple(
        DeckCardCount(card, count)
        for _, (card, count) in sorted(merged.items(), key=lambda item: item[0])
    )


def visible_card_semantic_key(card: VisiblePlayingCard) -> tuple[object, ...]:
    return (
        card.rank,
        card.suit,
        card.enhancement or "",
        card.edition or "",
        card.seal or "",
        card.debuffed,
        card.permanent_bonus,
    )


def canonical_visible_card(card: VisiblePlayingCard) -> VisiblePlayingCard:
    """Remove presentation-only text from an otherwise complete card value."""

    return replace(card, effect_text="")


def _comb_or_zero(population: int, selections: int) -> int:
    if selections < 0 or selections > population:
        return 0
    return comb(population, selections)
