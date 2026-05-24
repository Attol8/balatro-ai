from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.learning.imitation import train_linear_policy, train_nearest_neighbor_policy
from balatro_ai_v2.learning.trajectories import TrajectoryStep


def main() -> None:
    parser = argparse.ArgumentParser(description="Train a legal-action imitation policy from fast oracle trajectories")
    parser.add_argument("--data-jsonl", type=Path, default=Path("runs/fast_oracle_trajectories.jsonl"))
    parser.add_argument("--output-model", type=Path, default=Path("runs/fast_imitation_policy.json"))
    parser.add_argument("--model-type", choices=("linear", "nearest"), default="linear")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=0.1)
    args = parser.parse_args()

    steps = [
        TrajectoryStep.from_jsonable(json.loads(line))
        for line in args.data_jsonl.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.model_type == "linear":
        policy, metrics = train_linear_policy(
            steps,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
        )
    else:
        policy, metrics = train_nearest_neighbor_policy(steps)
    policy.save(args.output_model)

    print(f"data_jsonl: {args.data_jsonl}")
    print(f"output_model: {args.output_model}")
    print(f"model_type: {args.model_type}")
    for key, value in metrics.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
