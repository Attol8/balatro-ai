from __future__ import annotations

from dataclasses import dataclass

from balatro_ai_v2.fast.cards import rank
from balatro_ai_v2.fast.jokers import Joker


@dataclass(frozen=True, slots=True)
class RepetitionContext:
    scoring_indices: tuple[int, ...] = ()
    hands_left: int = 0
    held_card_has_effect: bool = False
    all_cards_are_face: bool = False


RETRIGGER_JOKERS = frozenset(
    {
        "j_dusk",
        "j_hack",
        "j_hanging_chad",
        "j_mime",
        "j_selzer",
        "j_sock_and_buskin",
    }
)


def played_card_repetitions(
    joker: Joker,
    card: int,
    card_index: int,
    context: RepetitionContext,
) -> int:
    if joker.key == "j_sock_and_buskin" and (context.all_cards_are_face or _is_face(card)):
        return 1
    if joker.key == "j_hanging_chad" and context.scoring_indices and card_index == context.scoring_indices[0]:
        return 2
    if joker.key == "j_dusk" and context.hands_left == 0:
        return 1
    if joker.key == "j_selzer":
        return 1
    if joker.key == "j_hack" and rank(card) in {0, 1, 2, 3}:
        return 1
    if joker.key in RETRIGGER_JOKERS:
        return 0
    raise NotImplementedError(f"played-card repetition is not implemented: {joker.key}")


def held_card_repetitions(joker: Joker, context: RepetitionContext) -> int:
    if joker.key == "j_mime" and context.held_card_has_effect:
        return 1
    if joker.key in RETRIGGER_JOKERS:
        return 0
    raise NotImplementedError(f"held-card repetition is not implemented: {joker.key}")


def total_played_card_repetitions(
    jokers: tuple[Joker, ...],
    card: int,
    card_index: int,
    context: RepetitionContext,
) -> int:
    return sum(played_card_repetitions(joker, card, card_index, context) for joker in jokers)


def total_held_card_repetitions(jokers: tuple[Joker, ...], context: RepetitionContext) -> int:
    return sum(held_card_repetitions(joker, context) for joker in jokers)


def _is_face(card: int) -> bool:
    return rank(card) in {9, 10, 11}
