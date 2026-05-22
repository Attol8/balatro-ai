from __future__ import annotations

from dataclasses import dataclass

from balatro_ai_v2.fast.cards import NUM_RANKS, rank, suit
from balatro_ai_v2.fast.modifiers import Edition, Enhancement, Seal


@dataclass(frozen=True, slots=True)
class FastCardState:
    card_id: int
    enhancement: Enhancement = Enhancement.BASE
    edition: Edition = Edition.BASE
    seal: Seal = Seal.NONE
    bonus_chips: int = 0
    bonus_mult: int = 0
    debuffed: bool = False

    @property
    def rank(self) -> int:
        return rank(self.card_id)

    @property
    def suit(self) -> int:
        return suit(self.card_id)


def make_card(rank_value: int, suit_value: int) -> int:
    if not 0 <= rank_value < NUM_RANKS:
        raise ValueError(f"rank must be in [0, {NUM_RANKS - 1}]")
    if not 0 <= suit_value < 4:
        raise ValueError("suit must be in [0, 3]")
    return suit_value * NUM_RANKS + rank_value


def with_rank(card: FastCardState, rank_value: int) -> FastCardState:
    return FastCardState(
        card_id=make_card(rank_value, card.suit),
        enhancement=card.enhancement,
        edition=card.edition,
        seal=card.seal,
        bonus_chips=card.bonus_chips,
        bonus_mult=card.bonus_mult,
        debuffed=card.debuffed,
    )


def with_suit(card: FastCardState, suit_value: int) -> FastCardState:
    return FastCardState(
        card_id=make_card(card.rank, suit_value),
        enhancement=card.enhancement,
        edition=card.edition,
        seal=card.seal,
        bonus_chips=card.bonus_chips,
        bonus_mult=card.bonus_mult,
        debuffed=card.debuffed,
    )
