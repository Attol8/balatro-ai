from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.fast.full_game import FastFullGameEnv
from balatro_ai_v2.fast.full_game import SearchRunAgent
from balatro_ai_v2.learning.imitation import HybridImitationRunAgent, ImitationRunAgent, load_action_policy


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a trained fast imitation policy")
    parser.add_argument("--model", type=Path, default=Path("runs/fast_imitation_policy.json"))
    parser.add_argument("--deck", default="b_red")
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=32)
    parser.add_argument("--max-steps", type=int, default=600)
    parser.add_argument(
        "--hybrid-tactical",
        action="store_true",
        help="Use deterministic search for tactical hand play and the trained model for shop/pack actions.",
    )
    parser.add_argument("--beam-width", type=int, default=SearchRunAgent.beam_width)
    parser.add_argument("--action-beam", type=int, default=SearchRunAgent.action_beam)
    args = parser.parse_args()

    policy = load_action_policy(args.model)
    if args.hybrid_tactical:
        tactical_agent = SearchRunAgent()
        tactical_agent.beam_width = args.beam_width
        tactical_agent.action_beam = args.action_beam
        agent = HybridImitationRunAgent(policy, tactical_agent)
    else:
        agent = ImitationRunAgent(policy)
    wins = 0
    rounds = 0
    steps_total = 0
    for seed in range(args.seed_start, args.seed_start + args.seeds):
        env = FastFullGameEnv(deck_key=args.deck)
        env.reset(seed=seed)
        terminated = False
        steps = 0
        while not terminated and steps < args.max_steps:
            result = env.step(agent.act(env))
            terminated = result.terminated
            steps += 1
        wins += int(env.won)
        rounds += env.rounds_cleared
        steps_total += steps

    print(f"model: {args.model}")
    print(f"seeds: {args.seeds}")
    print(f"hybrid_tactical: {args.hybrid_tactical}")
    print(f"wins: {wins}")
    print(f"win_rate: {wins / max(args.seeds, 1)}")
    print(f"avg_rounds_cleared: {rounds / max(args.seeds, 1)}")
    print(f"avg_steps: {steps_total / max(args.seeds, 1)}")


if __name__ == "__main__":
    main()
