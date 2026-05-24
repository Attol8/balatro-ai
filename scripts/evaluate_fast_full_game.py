from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.fast.full_game import evaluate_agent


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the fast full-game red-deck agent")
    parser.add_argument("--deck", default="b_red")
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=32)
    args = parser.parse_args()

    seed_range = range(args.seed_start, args.seed_start + args.seeds)
    metrics = evaluate_agent(seed_range, deck_key=args.deck)
    for key, value in metrics.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
