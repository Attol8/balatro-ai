"""Typed configuration and CMA-ES optimization for the public heuristic."""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass
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

    def canonical_json(self) -> str:
        return json.dumps(
            {name: getattr(self, name) for name in self.names()},
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, encoded: str) -> "StrategyTuning":
        try:
            payload = json.loads(encoded)
        except json.JSONDecodeError as exc:
            raise ValueError("strategy tuning JSON is invalid") from exc
        if not isinstance(payload, dict) or set(payload) != set(cls.names()):
            raise ValueError("strategy tuning JSON must contain exactly the known parameters")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in payload.values()):
            raise ValueError("strategy tuning parameters must be integers")
        try:
            return cls(**payload)
        except (TypeError, ValueError) as exc:
            raise ValueError("strategy tuning JSON is invalid") from exc

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
    sigma: float = 1.0,
    generations: int = 10,
    population: int = 8,
    seed: int = 1,
) -> tuple[StrategyTuning, float]:
    """Maximize paired-seed fitness with real covariance-matrix adaptation."""

    if sigma <= 0 or generations <= 0 or population < 2:
        raise ValueError("invalid CMA-ES bounds")
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="Could not import matplotlib.pyplot",
                category=UserWarning,
            )
            import cma
    except ImportError as exc:  # pragma: no cover - exercised by packaging smoke tests
        raise RuntimeError("CMA-ES tuning requires the declared 'cma' dependency") from exc

    center = initial.vector()
    scales = tuple(max(1.0, value * 0.25) for value in center)
    lower_bounds = [-value / scale for value, scale in zip(center, scales)]
    optimizer = cma.CMAEvolutionStrategy(
        [0.0] * len(center),
        sigma,
        {
            "bounds": [lower_bounds, [None] * len(center)],
            "popsize": population,
            "seed": seed,
            "verbose": -9,
            "verb_disp": 0,
            "verb_log": 0,
        },
    )
    best = initial
    best_score = objective(best)
    for _ in range(generations):
        points = optimizer.ask()
        scores: list[float] = []
        for point in points:
            values = tuple(
                center[index] + scales[index] * float(point[index])
                for index in range(len(center))
            )
            candidate = StrategyTuning.from_vector(values)
            score = objective(candidate)
            scores.append(score)
            if score > best_score:
                best, best_score = candidate, score
        optimizer.tell(points, [-score for score in scores])
    return best, best_score
