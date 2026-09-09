"""Exact, public composition odds for a bounded one-discard flush draw."""

from fractions import Fraction
from math import comb

from balatro_ai.game.actions import DiscardCards, HandSlot, action_to_data, is_legal
from balatro_ai.game.state import Phase, PublicItem, PublicObservation, VisiblePlayingCard

_SUITS = ("S", "H", "C", "D")


def _normal(card: object) -> bool:
    return (
        isinstance(card, VisiblePlayingCard)
        and card.suit in _SUITS
        and card.enhancement is None
        and card.edition is None
        and card.seal is None
        and not card.debuffed
    )


def flush_draws(observation: PublicObservation) -> list[dict[str, object]]:
    """Describe keeping three/four of a suit and discarding every off-suit card.

    This uses unordered remaining-deck counts only. It does not score future
    hands, model multiple discards, or select an action.
    """
    if (
        observation.phase != Phase.SELECTING_HAND
        or observation.round.discards_left <= 0
        or observation.hand_limit != len(observation.hand)
        or any(blind.kind == "BOSS" and blind.status == "CURRENT" for blind in observation.blinds)
        or any(not _normal(card) for card in observation.hand)
        or any(not _normal(entry.card) for entry in observation.remaining_deck)
        or any(
            not isinstance(joker, PublicItem)
            or (not joker.debuffed and joker.key in {"j_four_fingers", "j_smeared"})
            for joker in observation.jokers
        )
    ):
        return []
    total = sum(entry.count for entry in observation.remaining_deck)
    if total != observation.draw_count:
        return []

    rows = []
    for suit in _SUITS:
        held = sum(card.suit == suit for card in observation.hand)
        if held not in (3, 4):
            continue
        slots = tuple(HandSlot(i) for i, card in enumerate(observation.hand) if card.suit != suit)
        if not 1 <= len(slots) <= 5:
            continue
        action = DiscardCards(slots)
        if not is_legal(observation, action):
            continue
        draws = min(len(slots), observation.draw_count)
        matching = sum(
            entry.count for entry in observation.remaining_deck if entry.card.suit == suit
        )
        needed = 5 - held
        favorable = sum(
            comb(matching, hits) * comb(total - matching, draws - hits)
            for hits in range(max(needed, draws - (total - matching)), min(draws, matching) + 1)
        )
        probability = Fraction(favorable, comb(total, draws))
        rows.append(
            {
                "action": action_to_data(action),
                "suit": suit,
                "held_count": held,
                "needed": needed,
                "draw_count": draws,
                "matching_unseen": matching,
                "total_unseen": total,
                "probability": float(probability),
                "probability_numerator": probability.numerator,
                "probability_denominator": probability.denominator,
                "note": (
                    "Assuming a uniformly shuffled unseen deck: chance of holding at least five cards of this literal suit after one discard. "
                    "This is a composition chance, not a winning chance, score forecast, or full "
                    "discard policy; preserving other hands and resources remains model choice."
                ),
            }
        )
    return rows
