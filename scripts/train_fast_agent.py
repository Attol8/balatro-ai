from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.fast.full_game import FastFullGameEnv, SearchRunAgent, evaluate_agent


def main() -> None:
    parser = argparse.ArgumentParser(description="Reproduce the deterministic fast-agent training sweep")
    parser.add_argument("--deck", default="b_red")
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=32)
    parser.add_argument("--max-steps", type=int, default=600)
    args = parser.parse_args()

    # This is a deterministic search baseline, not a trained model. It is meant
    # to generate broad trajectories without forcing one hand family.
    seeds = range(args.seed_start, args.seed_start + args.seeds)
    metrics = evaluate_agent(seeds, deck_key=args.deck, max_steps=args.max_steps)
    print("agent: SearchRunAgent")
    for key, value in metrics.items():
        print(f"{key}: {value}")

    env = FastFullGameEnv(deck_key=args.deck)
    env.reset(seed=args.seed_start)
    agent = SearchRunAgent()
    steps = 0
    while steps < args.max_steps and not env.run.won and env.run.phase.name != "GAME_OVER":
        result = env.step(agent.act(env))
        steps += 1
        if result.terminated:
            break
    print(f"sample_seed: {args.seed_start}")
    print(f"sample_rounds_cleared: {env.rounds_cleared}")
    print(f"sample_won: {env.won}")
    print(f"sample_steps: {steps}")


if __name__ == "__main__":
    main()
