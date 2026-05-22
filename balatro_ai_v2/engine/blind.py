from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from balatro_ai_v2.engine.cards import Card, Deck
from balatro_ai_v2.engine.scoring import ScoreResult, score_play


@dataclass(frozen=True, slots=True)
class BlindConfig:
    required_score: int
    hands: int = 4
    discards: int = 3
    hand_size: int = 8

    def __post_init__(self) -> None:
        if self.required_score <= 0:
            raise ValueError("required_score must be positive")
        if self.hands <= 0:
            raise ValueError("hands must be positive")
        if self.discards < 0:
            raise ValueError("discards cannot be negative")
        if self.hand_size <= 0:
            raise ValueError("hand_size must be positive")


@dataclass(frozen=True, slots=True)
class BlindState:
    config: BlindConfig
    deck: Deck
    hand: tuple[Card, ...]
    score: int
    hands_remaining: int
    discards_remaining: int

    @property
    def is_cleared(self) -> bool:
        return self.score >= self.config.required_score

    @property
    def is_failed(self) -> bool:
        return not self.is_cleared and self.hands_remaining == 0

    @property
    def is_over(self) -> bool:
        return self.is_cleared or self.is_failed


def start_blind(deck: Deck, config: BlindConfig) -> BlindState:
    hand, remaining_deck = deck.draw(config.hand_size)
    return BlindState(
        config=config,
        deck=remaining_deck,
        hand=hand,
        score=0,
        hands_remaining=config.hands,
        discards_remaining=config.discards,
    )


def play_cards(state: BlindState, cards: tuple[Card, ...]) -> tuple[BlindState, ScoreResult]:
    if state.is_over:
        raise ValueError("cannot play cards after blind is over")
    if state.hands_remaining <= 0:
        raise ValueError("no hands remaining")
    _assert_cards_in_hand(state.hand, cards)

    result = score_play(cards)
    next_hand, next_deck = _replace_cards(state.hand, state.deck, cards, state.config.hand_size)
    next_state = BlindState(
        config=state.config,
        deck=next_deck,
        hand=next_hand,
        score=state.score + result.total,
        hands_remaining=state.hands_remaining - 1,
        discards_remaining=state.discards_remaining,
    )
    return next_state, result


def discard_cards(state: BlindState, cards: tuple[Card, ...]) -> BlindState:
    if state.is_over:
        raise ValueError("cannot discard after blind is over")
    if state.discards_remaining <= 0:
        raise ValueError("no discards remaining")
    if not 1 <= len(cards) <= 5:
        raise ValueError("a discard must contain between 1 and 5 cards")
    _assert_cards_in_hand(state.hand, cards)

    next_hand, next_deck = _replace_cards(state.hand, state.deck, cards, state.config.hand_size)
    return BlindState(
        config=state.config,
        deck=next_deck,
        hand=next_hand,
        score=state.score,
        hands_remaining=state.hands_remaining,
        discards_remaining=state.discards_remaining - 1,
    )


def _replace_cards(
    hand: tuple[Card, ...],
    deck: Deck,
    removed_cards: tuple[Card, ...],
    hand_size: int,
) -> tuple[tuple[Card, ...], Deck]:
    remaining_hand = _remove_cards(hand, removed_cards)
    draw_count = min(hand_size - len(remaining_hand), len(deck.cards))
    drawn, next_deck = deck.draw(draw_count)
    return remaining_hand + drawn, next_deck


def _remove_cards(hand: tuple[Card, ...], cards: tuple[Card, ...]) -> tuple[Card, ...]:
    counts = Counter(cards)
    remaining: list[Card] = []
    for card in hand:
        if counts[card] > 0:
            counts[card] -= 1
        else:
            remaining.append(card)
    return tuple(remaining)


def _assert_cards_in_hand(hand: tuple[Card, ...], cards: tuple[Card, ...]) -> None:
    if not cards:
        raise ValueError("must choose at least one card")
    if len(cards) > 5:
        raise ValueError("cannot choose more than five cards")
    hand_counts = Counter(hand)
    chosen_counts = Counter(cards)
    missing = chosen_counts - hand_counts
    if missing:
        raise ValueError(f"chosen cards are not in hand: {tuple(missing.elements())}")
