"""Backend-neutral policy contracts containing public information only."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Protocol

from balatro_ai_v2.actions import PublicAction
from balatro_ai_v2.public_state import PublicObservation


ActionSource = Callable[[], Iterator[PublicAction]]


@dataclass(frozen=True, slots=True)
class PublicHistoryStep:
    before: PublicObservation
    action: PublicAction
    after: PublicObservation


class PublicPolicy(Protocol):
    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction: ...
