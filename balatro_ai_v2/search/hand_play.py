from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

from balatro_ai_v2.engine.cards import Card
from balatro_ai_v2.engine.scoring import ScoreResult, score_play


@dataclass(frozen=True, slots=True)
class PlayCandidate:
    cards: tuple[Card, ...]
    score: ScoreResult


def enumerate_plays(hand: tuple[Card, ...], max_cards: int = 5) -> tuple[PlayCandidate, ...]:
    if not hand:
        raise ValueError("hand cannot be empty")
    if max_cards < 1:
        raise ValueError("max_cards must be positive")

    candidates: list[PlayCandidate] = []
    upper = min(max_cards, len(hand))
    for size in range(1, upper + 1):
        for cards in combinations(hand, size):
            candidates.append(PlayCandidate(cards=cards, score=score_play(cards)))
    return tuple(sorted(candidates, key=_candidate_sort_key, reverse=True))


def best_play(hand: tuple[Card, ...], max_cards: int = 5) -> PlayCandidate:
    return enumerate_plays(hand, max_cards=max_cards)[0]


def _candidate_sort_key(candidate: PlayCandidate) -> tuple[int, int, int, tuple[str, ...]]:
    return (
        candidate.score.total,
        candidate.score.chips,
        len(candidate.cards),
        tuple(str(card) for card in candidate.cards),
    )

