from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.fast.env import FastBalatroEnv


def run(episodes: int, seed: int, policy: str) -> dict[str, float]:
    env = FastBalatroEnv(required_score=300)
    steps = 0
    wins = 0
    started = time.perf_counter()
    for episode in range(episodes):
        env.reset(seed + episode)
        terminated = False
        while not terminated:
            if policy == "random":
                action = env.sample_legal_action()
            elif policy == "greedy":
                action = env.greedy_play_action()
            else:
                raise ValueError(f"unknown policy: {policy}")
            result = env.step(action)
            steps += 1
            terminated = result.terminated
        wins += int(env.score >= env.required_score)
    elapsed = time.perf_counter() - started
    return {
        "episodes": episodes,
        "steps": steps,
        "seconds": elapsed,
        "episodes_per_second": episodes / elapsed if elapsed else 0.0,
        "steps_per_second": steps / elapsed if elapsed else 0.0,
        "win_rate": wins / episodes if episodes else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the local fast training env")
    parser.add_argument("--episodes", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--policy", choices=("random", "greedy"), default="random")
    args = parser.parse_args()

    metrics = run(args.episodes, args.seed, args.policy)
    print(f"policy: {args.policy}")
    for key, value in metrics.items():
        if isinstance(value, float):
            print(f"{key}: {value:.2f}")
        else:
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
