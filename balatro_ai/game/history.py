"""Public-history enrichment needed for exact deterministic scoring."""

from __future__ import annotations

from dataclasses import dataclass, replace

from balatro_ai.game.actions import PlayCards, PublicAction
from balatro_ai.game.state import (
    HiddenJokerSlot,
    PublicItem,
    PublicJokerRuntime,
    PublicObservation,
)


@dataclass(frozen=True, slots=True)
class HistoryStep:
    before: PublicObservation
    action: PublicAction
    after: PublicObservation


def enrich_runtime(
    observation: PublicObservation,
    history: tuple[HistoryStep, ...],
) -> PublicObservation:
    """Replace stale Loyalty Card state with a public-history countdown."""

    loyalty_indexes = [
        index
        for index, joker in enumerate(observation.jokers)
        if isinstance(joker, PublicItem) and joker.key == "j_loyalty_card"
    ]
    if not loyalty_indexes:
        return observation
    remaining = _loyalty_remaining(observation, history)
    jokers = list(observation.jokers)
    for index in loyalty_indexes:
        joker = jokers[index]
        assert isinstance(joker, PublicItem)
        runtime = joker.runtime
        if remaining is None:
            if runtime is not None and runtime.loyalty_remaining is not None:
                jokers[index] = replace(joker, runtime=replace(runtime, loyalty_remaining=None))
            continue
        jokers[index] = replace(
            joker,
            runtime=(
                PublicJokerRuntime(loyalty_remaining=remaining)
                if runtime is None
                else replace(runtime, loyalty_remaining=remaining)
            ),
        )
    return replace(observation, jokers=tuple(jokers))


def _loyalty_remaining(
    observation: PublicObservation,
    history: tuple[HistoryStep, ...],
) -> int | None:
    if any(isinstance(joker, HiddenJokerSlot) for joker in observation.jokers):
        return None
    if any(
        isinstance(joker, HiddenJokerSlot)
        for step in history
        for seen in (step.before, step.after)
        for joker in seen.jokers
    ):
        return None
    if (
        sum(
            joker.key == "j_loyalty_card"
            for joker in observation.jokers
            if isinstance(joker, PublicItem)
        )
        != 1
    ):
        return None
    if not history or history[-1].after != observation:
        return None
    if any(
        previous.after != following.before
        for previous, following in zip(history, history[1:], strict=False)
    ):
        return None

    for index in range(len(history) - 1, -1, -1):
        step = history[index]
        before_count = sum(
            joker.key == "j_loyalty_card"
            for joker in step.before.jokers
            if isinstance(joker, PublicItem)
        )
        after_count = sum(
            joker.key == "j_loyalty_card"
            for joker in step.after.jokers
            if isinstance(joker, PublicItem)
        )
        if after_count != 1:
            return None
        if before_count == 0:
            if isinstance(step.action, PlayCards):
                return None
            plays_since_creation = sum(
                isinstance(later.action, PlayCards) for later in history[index + 1 :]
            )
            return (5 - plays_since_creation) % 6
        if before_count != 1:
            return None
    return None
