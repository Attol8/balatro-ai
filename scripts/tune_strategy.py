#!/usr/bin/env python3
"""Run deterministic CMA-ES over the public heuristic's tunable parameters.

The evaluator command must accept the candidate evaluator's seed and tuning
arguments and print a JSON object containing numeric ``fitness``.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import shlex
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.strategy_tuning import StrategyTuning, cma_es


def build_evaluator_command(
    command: tuple[str, ...],
    *,
    seed_start: int,
    seeds: int,
    tuning: StrategyTuning,
) -> tuple[str, ...]:
    return (
        *command,
        "--seed-start",
        str(seed_start),
        "--seeds",
        str(seeds),
        "--tuning-json",
        tuning.canonical_json(),
    )


def main() -> None:
    args = build_parser().parse_args()
    command = tuple(shlex.split(args.evaluator))
    if not command:
        raise SystemExit("--evaluator must not be empty")
    evaluations: list[dict[str, object]] = []

    def objective(tuning: StrategyTuning) -> float:
        evaluator_command = build_evaluator_command(
            command,
            seed_start=args.seed_start,
            seeds=args.seeds,
            tuning=tuning,
        )
        completed = subprocess.run(evaluator_command, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "tuning evaluator failed")
        try:
            result = json.loads(completed.stdout)
            fitness = float(result["fitness"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("tuning evaluator must print JSON with numeric fitness") from exc
        if not math.isfinite(fitness) or fitness < 0:
            raise RuntimeError(
                "tuning fitness must be a finite non-negative mean antes-cleared value"
            )
        evaluations.append(
            {
                "evaluation": len(evaluations),
                "parameters": asdict(tuning),
                "fitness": fitness,
            }
        )
        return fitness

    best, fitness = cma_es(
        objective,
        generations=args.generations,
        population=args.population,
        sigma=args.sigma,
        seed=args.training_seed,
    )
    report = {
        "candidate_only": True,
        "parameters": asdict(best),
        "fitness": fitness,
        "fitness_metric": "survival_to_ante_6_rate",
        "seed_manifest": {"start": args.seed_start, "count": args.seeds},
        "generations": args.generations,
        "population": args.population,
        "sigma": args.sigma,
        "training_seed": args.training_seed,
        "optimizer": {
            "name": "pycma",
            "version": importlib.metadata.version("cma"),
        },
        "evaluator_command": command,
        "python": sys.version,
        "evaluations": evaluations,
    }
    print(json.dumps(report, sort_keys=True))
    if args.report_json is not None:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        with args.report_json.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(report, sort_keys=True) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluator", required=True)
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=200)
    parser.add_argument("--generations", type=int, default=10)
    parser.add_argument("--population", type=int, default=8)
    parser.add_argument("--sigma", type=float, default=1.0)
    parser.add_argument("--training-seed", type=int, default=1)
    parser.add_argument("--report-json", type=Path)
    return parser


if __name__ == "__main__":
    main()
