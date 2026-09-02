"""Small, deterministic CMA-ES tuner for public heuristic parameters."""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, replace
from typing import Callable


@dataclass(frozen=True, slots=True)
class StrategyTuning:
    reserve_ante_1: int = 3
    reserve_ante_2: int = 6
    reserve_ante_3: int = 12
    sell_threshold: int = 65
    replacement_margin: int = 20

    def __post_init__(self) -> None:
        if min(self.reserve_ante_1, self.reserve_ante_2, self.reserve_ante_3,
               self.sell_threshold, self.replacement_margin) < 0:
            raise ValueError("strategy tuning parameters cannot be negative")

    @classmethod
    def names(cls) -> tuple[str, ...]:
        return tuple(cls.__dataclass_fields__)

    def vector(self) -> tuple[float, ...]:
        return tuple(float(getattr(self, name)) for name in self.names())

    @classmethod
    def from_vector(cls, values: tuple[float, ...]) -> "StrategyTuning":
        if len(values) != len(cls.names()):
            raise ValueError("strategy tuning vector has the wrong dimension")
        rounded = tuple(max(0, int(round(value))) for value in values)
        return cls(**dict(zip(cls.names(), rounded)))


def cma_es(
    objective: Callable[[StrategyTuning], float],
    *,
    initial: StrategyTuning = StrategyTuning(),
    sigma: float = 8.0,
    generations: int = 10,
    population: int = 8,
    seed: int = 1,
) -> tuple[StrategyTuning, float]:
    """Optimize a scalar fitness; callers supply paired-seed evaluation."""

    if sigma <= 0 or generations <= 0 or population < 2:
        raise ValueError("invalid CMA-ES bounds")
    rng = random.Random(seed)
    mean = list(initial.vector())
    best = initial
    best_score = objective(best)
    for _ in range(generations):
        candidates = []
        for _ in range(population):
            values = tuple(mean[index] + rng.gauss(0.0, sigma) for index in range(len(mean)))
            candidate = StrategyTuning.from_vector(values)
            score = objective(candidate)
            candidates.append((score, candidate))
            if score > best_score:
                best, best_score = candidate, score
        candidates.sort(key=lambda item: item[0], reverse=True)
        elite = candidates[: max(1, population // 2)]
        mean = [sum(candidate.vector()[index] for _, candidate in elite) / len(elite)
                for index in range(len(mean))]
        sigma *= 0.9
    return best, best_score


def tuning_from_environment() -> StrategyTuning:
    """Load an explicit tuner candidate, otherwise return the frozen default."""

    encoded = os.environ.get("BALATRO_TUNING_JSON")
    if encoded is None:
        return StrategyTuning()
    try:
        payload = json.loads(encoded)
        if not isinstance(payload, dict):
            raise ValueError("tuning payload must be an object")
        return StrategyTuning(**payload)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("BALATRO_TUNING_JSON is invalid") from exc
