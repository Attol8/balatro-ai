"""Public adjacent-order improvements for a fixed physical play selection.

The caller executes only the reorder, settles, then reassesses. Improvement is
strict for this selection; callers changing selection between calls should bound
reordering or remember visited orders, since that wider process can still cycle.
"""

from dataclasses import dataclass, replace

from balatro_ai_v2.solver.actions import (
    HandSlot, JokerSlot, PlayCards, ReorderHand, ReorderJokers, is_legal,
)
from balatro_ai_v2.solver.public_scoring import score_play
from balatro_ai_v2.solver.public_state import (
    HiddenHandCard, HiddenJokerSlot, Phase, PublicObservation,
)
from balatro_ai_v2.solver.tactical_search import _stochastic_scoring


@dataclass(frozen=True, slots=True)
class OrderingChoice:
    action: ReorderHand | ReorderJokers
    reason: str
    diagnostics: dict


def improve_play_order(observation: PublicObservation, play: PlayCards) -> OrderingChoice | None:
    """Return the largest strict adjacent-swap gain, or no intervention.

    Supply public history-enriched Joker runtime, as for the tactical scorer.
    Ties deterministically prefer Joker ordering, then the leftmost adjacent pair.
    """
    if observation.phase != Phase.SELECTING_HAND or not isinstance(play, PlayCards):
        return None
    if observation.required_hand_slots or not is_legal(observation, play):
        return None
    if any(isinstance(card, HiddenHandCard) for card in observation.hand) or any(
        isinstance(joker, HiddenJokerSlot) for joker in observation.jokers
    ):
        return None
    if _stochastic_scoring(observation):
        return None
    blind = next((blind for blind in observation.blinds if blind.status == "CURRENT"), None)
    if blind is None:
        return None
    # The API selects physical cards; scoring follows their actual hand order,
    # not the order of indices in the RPC payload.
    selected = tuple(sorted(play.cards, key=lambda slot: slot.value))
    try:
        baseline, _ = score_play(observation, selected)
    except ValueError:
        return None
    if baseline >= blind.score - observation.round.chips:
        return None
    best = baseline
    choice = None
    for area, slot_type, action_type in (
        ("jokers", JokerSlot, ReorderJokers), ("hand", HandSlot, ReorderHand),
    ):
        items = getattr(observation, area)
        for index in range(len(items) - 1):
            order = list(range(len(items)))
            order[index], order[index + 1] = order[index + 1], order[index]
            action = action_type(tuple(slot_type(value) for value in order))
            if not is_legal(observation, action):
                continue
            after = replace(observation, **{area: tuple(items[value] for value in order)})
            mapped = selected if area == "jokers" else tuple(
                HandSlot(value) for value in sorted(order.index(slot.value) for slot in selected)
            )
            try:
                score, _ = score_play(after, mapped)
            except ValueError:
                continue
            if score > best:
                best = score
                choice = OrderingChoice(action, f"Adjacent {area} reorder improves the same physical play.", {
                    "baseline_score": float(baseline), "reordered_score": float(score),
                    "score_gain": float(score - baseline), "area": area,
                    "swap": [index, index + 1],
                    "selected_before": [slot.value for slot in selected],
                    "selected_after": [slot.value for slot in mapped],
                })
    return choice
