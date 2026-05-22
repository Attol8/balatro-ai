from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from balatro_ai_v2.engine.cards import Card
from balatro_ai_v2.engine.hand import HandKind, evaluate_hand


class ScoreEvent(str, Enum):
    HAND_BASE = "hand_base"
    CARD_CHIPS = "card_chips"
    TOTAL = "total"


@dataclass(frozen=True, slots=True)
class ScoreStep:
    event: ScoreEvent
    chips: int
    mult: int
    message: str
    card: Card | None = None


@dataclass(frozen=True, slots=True)
class ScoreResult:
    hand_kind: HandKind
    scoring_cards: tuple[Card, ...]
    chips: int
    mult: int
    total: int
    events: tuple[ScoreStep, ...]


def score_play(cards: tuple[Card, ...]) -> ScoreResult:
    evaluation = evaluate_hand(cards)
    chips = evaluation.base_chips
    mult = evaluation.base_mult
    events: list[ScoreStep] = [
        ScoreStep(
            event=ScoreEvent.HAND_BASE,
            chips=chips,
            mult=mult,
            message=f"{evaluation.kind.value}: +{chips} chips, x{mult} mult",
        )
    ]

    for card in evaluation.scoring_cards:
        chips += card.chips
        events.append(
            ScoreStep(
                event=ScoreEvent.CARD_CHIPS,
                chips=chips,
                mult=mult,
                message=f"{card}: +{card.chips} chips",
                card=card,
            )
        )

    total = chips * mult
    events.append(
        ScoreStep(
            event=ScoreEvent.TOTAL,
            chips=chips,
            mult=mult,
            message=f"{chips} chips x {mult} mult = {total}",
        )
    )
    return ScoreResult(
        hand_kind=evaluation.kind,
        scoring_cards=evaluation.scoring_cards,
        chips=chips,
        mult=mult,
        total=total,
        events=tuple(events),
    )

