#!/usr/bin/env python3
"""Run deterministic CMA-ES over the public heuristic's tunable parameters.

The evaluator command must print a JSON object containing numeric ``fitness``.
The candidate vector is supplied in ``BALATRO_TUNING_JSON`` and paired seeds in
``BALATRO_TUNING_SEEDS_JSON``; the evaluator remains responsible for authority
and completion checks.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.strategy_tuning import StrategyTuning, cma_es


def main() -> None:
    args = build_parser().parse_args()
    seeds = tuple(range(args.seed_start, args.seed_start + args.seeds))
    command = tuple(shlex.split(args.evaluator))
    if not command:
        raise SystemExit("--evaluator must not be empty")

    def objective(tuning: StrategyTuning) -> float:
        environment = os.environ.copy()
        environment["BALATRO_TUNING_JSON"] = json.dumps(asdict(tuning), sort_keys=True)
        environment["BALATRO_TUNING_SEEDS_JSON"] = json.dumps(seeds)
        completed = subprocess.run(command, env=environment, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "tuning evaluator failed")
        try:
            result = json.loads(completed.stdout)
            fitness = float(result["fitness"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("tuning evaluator must print JSON with numeric fitness") from exc
        if not 0 <= fitness <= 1:
            raise RuntimeError("tuning fitness must be a survival rate in [0, 1]")
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
        "seeds": seeds,
        "seed_manifest": {"start": args.seed_start, "count": args.seeds},
        "generations": args.generations,
        "population": args.population,
    }
    print(json.dumps(report, sort_keys=True))
    if args.report_json is not None:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluator", required=True)
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=200)
    parser.add_argument("--generations", type=int, default=10)
    parser.add_argument("--population", type=int, default=8)
    parser.add_argument("--sigma", type=float, default=8.0)
    parser.add_argument("--training-seed", type=int, default=1)
    parser.add_argument("--report-json", type=Path)
    return parser


if __name__ == "__main__":
    main()
