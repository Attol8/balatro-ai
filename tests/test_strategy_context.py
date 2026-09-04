from __future__ import annotations

from dataclasses import replace

import pytest

from balatro_ai_v2.actions import JokerSlot, LeaveShop, SellJoker
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.strategy_context import derive_public_strategy_context
from balatro_ai_v2.strategy_options import StrategyIntent
from state_factory import state


def test_public_context_summarizes_current_shop_and_incoming_intent() -> None:
    first = to_public_observation(state("SHOP"))
    second = replace(first, money=first.money + 1)
    current = replace(second, money=second.money + 2)
    history = (
        PublicHistoryStep(first, SellJoker(JokerSlot(0)), second),
        PublicHistoryStep(second, LeaveShop(), current),
    )

    context = derive_public_strategy_context(
        current,
        history,
        incoming_intent=StrategyIntent.ECONOMY,
    )

    assert context.current_shop_actions == 2
    assert context.current_shop_has_joker_sale
    assert context.prior_shop_has_joker_sale
    assert context.incoming_intent == StrategyIntent.ECONOMY


def test_public_context_rejects_discontinuous_or_future_history() -> None:
    first = to_public_observation(state("SHOP"))
    second = replace(first, money=first.money + 1)
    future = replace(second, money=second.money + 1)

    with pytest.raises(ValueError, match="does not end"):
        derive_public_strategy_context(
            second,
            (PublicHistoryStep(first, LeaveShop(), future),),
        )
    with pytest.raises(ValueError, match="not contiguous"):
        derive_public_strategy_context(
            future,
            (
                PublicHistoryStep(first, LeaveShop(), second),
                PublicHistoryStep(first, LeaveShop(), future),
            ),
        )
