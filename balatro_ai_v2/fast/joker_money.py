from __future__ import annotations

from dataclasses import dataclass

from balatro_ai_v2.fast.cards import rank, suit
from balatro_ai_v2.fast.hand import FastScore
from balatro_ai_v2.fast.jokers import Joker


@dataclass(frozen=True, slots=True)
class DollarBonusContext:
    deck_cards: tuple[int, ...] = ()
    discards_used: int = 0
    discards_left: int = 0
    planets_used: frozenset[str] = frozenset()


DOLLAR_BONUS_JOKERS = frozenset(
    {
        "j_cloud_9",
        "j_delayed_grat",
        "j_golden",
        "j_rocket",
        "j_satellite",
    }
)

MONEY_EVENT_JOKERS = frozenset(
    {
        "j_business",
        "j_faceless",
        "j_mail",
        "j_matador",
        "j_reserved_parking",
        "j_rough_gem",
        "j_ticket",
        "j_todo_list",
        "j_trading",
    }
)


@dataclass(frozen=True, slots=True)
class MoneyEventContext:
    all_cards_are_face: bool = False
    probability_success: bool = False
    card_has_gold_enhancement: bool = False
    current_mail_rank: int | None = None
    blind_triggered: bool = False
    discards_used: int = 0
    selected_count: int = 0
    discarded_face_count: int = 0
    todo_hand_kind: int | None = None


def joker_dollar_bonus(joker: Joker, context: DollarBonusContext | None = None) -> int:
    context = context or DollarBonusContext()
    if joker.key == "j_golden":
        return 4
    if joker.key == "j_cloud_9":
        return sum(1 for card in context.deck_cards if rank(card) == 7)
    if joker.key == "j_rocket":
        return joker.scaling if joker.scaling > 0 else 1
    if joker.key == "j_satellite":
        return len(context.planets_used)
    if joker.key == "j_delayed_grat" and context.discards_used == 0 and context.discards_left > 0:
        return context.discards_left * 2
    if joker.key in DOLLAR_BONUS_JOKERS:
        return 0
    raise NotImplementedError(f"joker dollar bonus is not implemented: {joker.key}")


def total_joker_dollar_bonus(
    jokers: tuple[Joker, ...],
    context: DollarBonusContext | None = None,
) -> int:
    return sum(joker_dollar_bonus(joker, context) for joker in jokers)


def scored_card_money_delta(joker: Joker, card: int, context: MoneyEventContext | None = None) -> int:
    context = context or MoneyEventContext()
    if joker.key == "j_business" and context.probability_success and _is_face(card, context.all_cards_are_face):
        return 2
    if joker.key == "j_reserved_parking" and context.probability_success and _is_face(
        card,
        context.all_cards_are_face,
    ):
        return 1
    if joker.key == "j_rough_gem" and suit(card) == 3:
        return 1
    if joker.key == "j_ticket" and context.card_has_gold_enhancement:
        return 4
    if joker.key in MONEY_EVENT_JOKERS:
        return 0
    raise NotImplementedError(f"scored-card money event is not implemented: {joker.key}")


def discard_money_delta(joker: Joker, card: int | None = None, context: MoneyEventContext | None = None) -> int:
    context = context or MoneyEventContext()
    if joker.key == "j_mail" and card is not None and context.current_mail_rank == rank(card):
        return 5
    if joker.key == "j_faceless" and context.discarded_face_count >= 3:
        return 5
    if joker.key == "j_trading" and context.discards_used == 0 and context.selected_count == 1:
        return 3
    if joker.key in MONEY_EVENT_JOKERS:
        return 0
    raise NotImplementedError(f"discard money event is not implemented: {joker.key}")


def hand_money_delta(joker: Joker, score: FastScore, context: MoneyEventContext | None = None) -> int:
    context = context or MoneyEventContext()
    if joker.key == "j_matador" and context.blind_triggered:
        return 8
    if joker.key == "j_todo_list" and context.todo_hand_kind == score.kind:
        return 4
    if joker.key in MONEY_EVENT_JOKERS:
        return 0
    raise NotImplementedError(f"hand money event is not implemented: {joker.key}")


def _is_face(card: int, all_cards_are_face: bool) -> bool:
    return all_cards_are_face or rank(card) in {9, 10, 11}
