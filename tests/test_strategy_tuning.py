from __future__ import annotations

import importlib.util
from pathlib import Path

from balatro_ai_v2.strategy_tuning import StrategyTuning, cma_es


def test_strategy_tuning_vector_round_trip_is_integer_and_bounded() -> None:
    tuning = StrategyTuning(reserve_ante_1=4, replacement_margin=17)

    restored = StrategyTuning.from_vector(tuning.vector())

    assert restored == tuning
    assert len(tuning.vector()) == len(StrategyTuning.names())


def test_cma_es_is_deterministic_for_paired_fitness_callback() -> None:
    def fitness(tuning: StrategyTuning) -> float:
        return -abs(tuning.reserve_ante_1 - 7)

    left = cma_es(fitness, generations=3, population=4, seed=9)
    right = cma_es(fitness, generations=3, population=4, seed=9)

    assert left == right


def test_tuning_cli_exposes_seed_panel_and_evaluator_only() -> None:
    path = Path(__file__).resolve().parents[1] / "scripts" / "tune_strategy.py"
    spec = importlib.util.spec_from_file_location("tune_strategy_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    destinations = {action.dest for action in module.build_parser()._actions}

    assert {"evaluator", "seed_start", "seeds"} <= destinations
    assert "snapshot" not in destinations
