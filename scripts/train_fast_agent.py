from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.fast.full_game import FastFullGameEnv, RolloutSearchRunAgent, SearchRunAgent, evaluate_agent


def main() -> None:
    parser = argparse.ArgumentParser(description="Reproduce the deterministic fast-agent training sweep")
    parser.add_argument("--deck", default="b_red")
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=32)
    parser.add_argument("--max-steps", type=int, default=600)
    parser.add_argument("--shop-rollout", action="store_true")
    parser.add_argument("--shop-rollout-candidates", type=int, default=RolloutSearchRunAgent.shop_rollout_candidates)
    parser.add_argument("--shop-rollout-steps", type=int, default=RolloutSearchRunAgent.shop_rollout_steps)
    args = parser.parse_args()

    # This is a deterministic search baseline, not a trained model. It is meant
    # to generate broad trajectories without forcing one hand family.
    seeds = range(args.seed_start, args.seed_start + args.seeds)
    agent = RolloutSearchRunAgent() if args.shop_rollout else SearchRunAgent()
    if args.shop_rollout:
        agent.shop_rollout_candidates = args.shop_rollout_candidates
        agent.shop_rollout_steps = args.shop_rollout_steps
    metrics = evaluate_agent(seeds, deck_key=args.deck, max_steps=args.max_steps, agent=agent)
    print(f"agent: {type(agent).__name__}")
    if args.shop_rollout:
        print(f"shop_rollout_candidates: {agent.shop_rollout_candidates}")
        print(f"shop_rollout_steps: {agent.shop_rollout_steps}")
    for key, value in metrics.items():
        print(f"{key}: {value}")

    env = FastFullGameEnv(deck_key=args.deck)
    env.reset(seed=args.seed_start)
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
