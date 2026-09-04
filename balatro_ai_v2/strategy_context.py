"""Versioned public-history context for contextual strategy decisions."""

from __future__ import annotations

import math
from dataclasses import dataclass

from balatro_ai_v2.actions import PlayCards, SellJoker
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.public_state import Phase, PublicObservation
from balatro_ai_v2.strategy_options import StrategyIntent


STRATEGY_CONTEXT_VERSION = 1


@dataclass(frozen=True, slots=True)
class PublicStrategyContext:
    """Small, lossless-for-current-policy summary of typed public history."""

    version: int = STRATEGY_CONTEXT_VERSION
    current_shop_actions: int = 0
    current_shop_has_joker_sale: bool = False
    prior_shop_has_joker_sale: bool = False
    loyalty_remaining: int | None = None
    best_hand_log_score: float = 0.0
    incoming_intent: StrategyIntent | None = None

    def __post_init__(self) -> None:
        if self.version != STRATEGY_CONTEXT_VERSION:
            raise ValueError("unsupported public strategy context version")
        if self.current_shop_actions < 0:
            raise ValueError("shop action count must be non-negative")
        if not isinstance(self.current_shop_has_joker_sale, bool) or not isinstance(
            self.prior_shop_has_joker_sale, bool
        ):
            raise ValueError("shop sale context flags must be boolean")
        if self.loyalty_remaining is not None and not 0 <= self.loyalty_remaining <= 5:
            raise ValueError("loyalty remaining must be null or in [0, 5]")
        if not math.isfinite(self.best_hand_log_score) or self.best_hand_log_score < 0:
            raise ValueError("best-hand log score must be finite and non-negative")
        if self.incoming_intent is not None and not isinstance(
            self.incoming_intent, StrategyIntent
        ):
            raise ValueError("incoming strategy intent is unsupported")


def derive_public_strategy_context(
    observation: PublicObservation,
    history: tuple[PublicHistoryStep, ...],
    *,
    incoming_intent: StrategyIntent | None = None,
) -> PublicStrategyContext:
    """Validate a typed prefix and derive only publicly observable context."""

    _validate_history(observation, history)
    current_shop_actions = 0
    current_shop_has_joker_sale = False
    for step in reversed(history):
        if step.before.phase == Phase.ROUND_EVAL and step.after.phase == Phase.SHOP:
            break
        if step.before.phase == Phase.SHOP:
            current_shop_actions += 1
            current_shop_has_joker_sale |= isinstance(step.action, SellJoker)
    prior_shop_has_joker_sale = any(
        step.before.phase == Phase.SHOP and isinstance(step.action, SellJoker)
        for step in history
    )
    best_hand_score = max(
        (
            max(0, step.after.round.chips - step.before.round.chips)
            for step in history
            if isinstance(step.action, PlayCards)
        ),
        default=0,
    )
    return PublicStrategyContext(
        current_shop_actions=current_shop_actions,
        current_shop_has_joker_sale=current_shop_has_joker_sale,
        prior_shop_has_joker_sale=prior_shop_has_joker_sale,
        loyalty_remaining=_loyalty_remaining(observation, history),
        best_hand_log_score=math.log10(max(1, best_hand_score)),
        incoming_intent=incoming_intent,
    )


def _validate_history(
    observation: PublicObservation,
    history: tuple[PublicHistoryStep, ...],
) -> None:
    if not history:
        return
    if history[-1].after != observation:
        raise ValueError("public history does not end at the current observation")
    if any(
        previous.after != following.before
        for previous, following in zip(history, history[1:], strict=False)
    ):
        raise ValueError("public history is not contiguous")


def _loyalty_remaining(
    observation: PublicObservation,
    history: tuple[PublicHistoryStep, ...],
) -> int | None:
    if sum(joker.key == "j_loyalty_card" for joker in observation.jokers) != 1:
        return None
    if not history:
        return None
    for index in range(len(history) - 1, -1, -1):
        step = history[index]
        before_count = sum(
            joker.key == "j_loyalty_card" for joker in step.before.jokers
        )
        after_count = sum(joker.key == "j_loyalty_card" for joker in step.after.jokers)
        if after_count != 1:
            return None
        if before_count == 0:
            if isinstance(step.action, PlayCards):
                return None
            plays = sum(
                isinstance(later.action, PlayCards) for later in history[index + 1 :]
            )
            return (5 - plays) % 6
        if before_count != 1:
            return None
    return None


__all__ = [
    "STRATEGY_CONTEXT_VERSION",
    "PublicStrategyContext",
    "derive_public_strategy_context",
]
