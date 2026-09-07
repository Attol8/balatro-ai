from dataclasses import replace

import pytest

from balatro_ai.game.actions import BuyShopCard, HandSlot, PlayCards, ShopSlot
from balatro_ai.game.adapter import to_public_observation
from balatro_ai.game.history import HistoryStep, enrich_runtime
from balatro_ai.game.scoring import score_play
from balatro_ai.game.state import PublicItem, PublicJokerRuntime
from state_factory import state


def _history(plays: int):
    loyalty = PublicItem(
        "j_loyalty_card", "Loyalty Card", "JOKER",
        runtime=PublicJokerRuntime(loyalty_remaining=5),
    )
    owned = replace(to_public_observation(state("SELECTING_HAND")), jokers=(loyalty,))
    empty = replace(owned, jokers=())
    steps = [HistoryStep(empty, BuyShopCard(ShopSlot(0)), owned)]
    steps.extend(HistoryStep(owned, PlayCards((HandSlot(0),)), owned) for _ in range(plays))
    return owned, tuple(steps)


@pytest.mark.parametrize("plays", range(6))
def test_loyalty_countdown_from_contiguous_public_history(plays: int) -> None:
    observation, history = _history(plays)
    enriched = enrich_runtime(observation, history)
    assert enriched.jokers[0].runtime.loyalty_remaining == (5 - plays) % 6


def test_loyalty_runtime_fails_closed_without_provenance() -> None:
    observation, _ = _history(0)
    stale = replace(
        observation,
        jokers=(replace(observation.jokers[0], runtime=PublicJokerRuntime(loyalty_remaining=0)),),
    )
    assert enrich_runtime(stale, ()).jokers[0].runtime.loyalty_remaining is None


def test_loyalty_sixth_play_scores_x4() -> None:
    observation, history = _history(5)
    selected = (HandSlot(0),)
    scored, _ = score_play(enrich_runtime(observation, history), selected)
    without, _ = score_play(replace(observation, jokers=()), selected)
    assert scored == 4 * without
