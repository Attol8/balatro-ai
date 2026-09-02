"""Public search-comparison records and losses for expert iteration."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import torch
from torch import Tensor

from balatro_ai_v2.actions import PublicAction, action_from_data, action_to_data
from balatro_ai_v2.public_codec import public_observation_from_data, public_observation_to_data
from balatro_ai_v2.public_model import ModelCandidate, PublicRecurrentPolicyValue
from balatro_ai_v2.public_state import PublicObservation


@dataclass(frozen=True, slots=True)
class SearchComparison:
    observation: PublicObservation
    actions: tuple[PublicAction, ...]
    utilities: tuple[float, ...]
    selected: PublicAction
    previous_action: PublicAction | None = None

    def __post_init__(self) -> None:
        if not self.actions or len(self.actions) != len(self.utilities):
            raise ValueError("search comparison actions and utilities must have equal non-zero length")
        if len(
            {
                json.dumps(action_to_data(action), sort_keys=True)
                for action in self.actions
            }
        ) != len(self.actions):
            raise ValueError("search comparison contains duplicate actions")
        if self.selected not in self.actions:
            raise ValueError("selected search action is absent from comparison")
        if any(
            not isinstance(value, (int, float)) or not math.isfinite(value)
            for value in self.utilities
        ):
            raise ValueError("search utilities must be finite numbers")


def comparison_to_data(comparison: SearchComparison) -> dict[str, object]:
    return {
        "observation": public_observation_to_data(comparison.observation),
        "actions": [action_to_data(action) for action in comparison.actions],
        "utilities": list(comparison.utilities),
        "selected": action_to_data(comparison.selected),
        "previous_action": (
            action_to_data(comparison.previous_action)
            if comparison.previous_action is not None
            else None
        ),
    }


def comparison_from_data(data: object) -> SearchComparison:
    if not isinstance(data, dict) or set(data) != {
        "observation", "actions", "utilities", "selected", "previous_action"
    }:
        raise ValueError("search comparison has invalid fields")
    actions = data["actions"]
    utilities = data["utilities"]
    if not isinstance(actions, list) or not isinstance(utilities, list):
        raise ValueError("search comparison actions and utilities must be arrays")
    return SearchComparison(
        public_observation_from_data(data["observation"]),
        tuple(action_from_data(action) for action in actions),
        tuple(float(value) for value in utilities),
        action_from_data(data["selected"]),
        action_from_data(data["previous_action"]) if data["previous_action"] is not None else None,
    )


def write_comparisons(path: Path, comparisons: tuple[SearchComparison, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        for comparison in comparisons:
            handle.write(json.dumps(comparison_to_data(comparison), sort_keys=True) + "\n")


def read_comparisons(path: Path) -> list[SearchComparison]:
    comparisons: list[SearchComparison] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            comparisons.append(comparison_from_data(json.loads(line)))
    if not comparisons:
        raise ValueError("comparison dataset is empty")
    return comparisons


def distillation_loss(
    model: PublicRecurrentPolicyValue,
    comparisons: tuple[SearchComparison, ...],
    *,
    margin: float = 0.05,
) -> tuple[Tensor, dict[str, float]]:
    """Train action logits to match search utilities and value to best utility."""

    if margin <= 0:
        raise ValueError("distillation margin must be positive")
    losses: list[Tensor] = []
    ranking_losses: list[Tensor] = []
    value_losses: list[Tensor] = []
    for comparison in comparisons:
        candidates: tuple[ModelCandidate, ...] = comparison.actions
        output = model.step(
            (comparison.observation,),
            (candidates,),
            (comparison.previous_action,),
            reset_mask=torch.ones(1, dtype=torch.bool),
        )
        logits = output.logits[0, : len(candidates)]
        utilities = torch.tensor(comparison.utilities, dtype=logits.dtype, device=logits.device)
        target = torch.softmax(utilities / margin, dim=0)
        policy_loss = -(target * torch.log_softmax(logits, dim=0)).sum()
        best = utilities.max().detach()
        value_loss = (output.values[0] - best).square()
        losses.append(policy_loss + value_loss)
        ranking_losses.append(policy_loss)
        value_losses.append(value_loss)
    loss = torch.stack(losses).mean()
    return loss, {
        "loss": float(loss.detach()),
        "policy_loss": float(torch.stack(ranking_losses).mean().detach()),
        "value_loss": float(torch.stack(value_losses).mean().detach()),
    }
