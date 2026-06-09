from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.fast.run import RunPhase
from balatro_ai_v2.learning.imitation import (
    train_linear_policy,
    train_nearest_neighbor_policy,
    train_softmax_linear_policy,
)
from balatro_ai_v2.learning.trajectories import TrajectoryStep


PHASE_FILTERS = {
    "all": None,
    "shop-pack": {int(RunPhase.SHOP), int(RunPhase.PACK)},
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a legal-action imitation policy from fast oracle trajectories")
    parser.add_argument(
        "--data-jsonl",
        type=Path,
        nargs="+",
        default=[Path("runs/fast_oracle_trajectories.jsonl")],
    )
    parser.add_argument("--output-model", type=Path, default=Path("runs/fast_imitation_policy.json"))
    parser.add_argument("--model-type", choices=("linear", "softmax-linear", "nearest"), default="linear")
    parser.add_argument("--phase-filter", choices=tuple(PHASE_FILTERS), default="all")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=0.1)
    args = parser.parse_args()

    steps = []
    for path in args.data_jsonl:
        steps.extend(
            TrajectoryStep.from_jsonable(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    allowed_phases = PHASE_FILTERS[args.phase_filter]
    if allowed_phases is not None:
        steps = [step for step in steps if step.observation and int(step.observation[0]) in allowed_phases]
    if args.model_type == "linear":
        policy, metrics = train_linear_policy(
            steps,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
        )
    elif args.model_type == "softmax-linear":
        policy, metrics = train_softmax_linear_policy(
            steps,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
        )
    else:
        policy, metrics = train_nearest_neighbor_policy(steps)
    policy.save(args.output_model)

    print(f"data_jsonl: {','.join(str(path) for path in args.data_jsonl)}")
    print(f"output_model: {args.output_model}")
    print(f"model_type: {args.model_type}")
    print(f"phase_filter: {args.phase_filter}")
    for key, value in metrics.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
