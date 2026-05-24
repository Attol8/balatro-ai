from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.fast.full_game import FastFullGameEnv, FlushRunAgent, evaluate_agent
from balatro_ai_v2.fast.hand import FLUSH


def main() -> None:
    parser = argparse.ArgumentParser(description="Reproduce the deterministic fast-agent training sweep")
    parser.add_argument("--deck", default="b_red")
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=32)
    args = parser.parse_args()

    # The current local training surface is a deterministic policy sweep over
    # target hand families. Flush is retained as the shipped baseline because it
    # is the first strategy that clears ante 8 consistently in this gym.
    seeds = range(args.seed_start, args.seed_start + args.seeds)
    metrics = evaluate_agent(seeds, deck_key=args.deck)
    print("agent: FlushRunAgent")
    print(f"target_hand_kind: {FLUSH}")
    for key, value in metrics.items():
        print(f"{key}: {value}")

    env = FastFullGameEnv(deck_key=args.deck)
    env.reset(seed=args.seed_start)
    agent = FlushRunAgent()
    steps = 0
    while not env.run.won and env.run.phase.name != "GAME_OVER":
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
