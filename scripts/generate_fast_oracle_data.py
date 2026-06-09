from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.fast.full_game import RolloutSearchRunAgent
from balatro_ai_v2.fast.full_game import SearchRunAgent
from balatro_ai_v2.learning.trajectories import collect_oracle_trajectories


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate fast-gym oracle-search imitation data")
    parser.add_argument("--deck", default="b_red")
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=32)
    parser.add_argument("--max-steps", type=int, default=600)
    parser.add_argument("--output-jsonl", type=Path, default=Path("runs/fast_oracle_trajectories.jsonl"))
    parser.add_argument(
        "--shop-rollout",
        action="store_true",
        help="Use the slower rollout-search shop oracle instead of the default heuristic shop oracle.",
    )
    parser.add_argument("--shop-rollout-candidates", type=int, default=RolloutSearchRunAgent.shop_rollout_candidates)
    parser.add_argument("--shop-rollout-steps", type=int, default=RolloutSearchRunAgent.shop_rollout_steps)
    parser.add_argument("--beam-width", type=int, default=SearchRunAgent.beam_width)
    parser.add_argument("--action-beam", type=int, default=SearchRunAgent.action_beam)
    args = parser.parse_args()

    seed_range = range(args.seed_start, args.seed_start + args.seeds)
    agent = RolloutSearchRunAgent() if args.shop_rollout else SearchRunAgent()
    agent.beam_width = args.beam_width
    agent.action_beam = args.action_beam
    if args.shop_rollout:
        agent.shop_rollout_candidates = args.shop_rollout_candidates
        agent.shop_rollout_steps = args.shop_rollout_steps
    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    wins = 0
    last_seed = None
    with args.output_jsonl.open("w", encoding="utf-8") as handle:
        for step in collect_oracle_trajectories(seed_range, deck_key=args.deck, max_steps=args.max_steps, agent=agent):
            handle.write(json.dumps(step.to_jsonable(), separators=(",", ":"), sort_keys=True) + "\n")
            count += 1
            if step.terminated:
                wins += int(step.won)
                last_seed = step.seed

    print(f"output_jsonl: {args.output_jsonl}")
    print(f"examples: {count}")
    print(f"seeds: {args.seeds}")
    print(f"shop_rollout: {bool(args.shop_rollout)}")
    print(f"beam_width: {agent.beam_width}")
    print(f"action_beam: {agent.action_beam}")
    if args.shop_rollout:
        print(f"shop_rollout_candidates: {agent.shop_rollout_candidates}")
        print(f"shop_rollout_steps: {agent.shop_rollout_steps}")
    print(f"terminal_wins: {wins}")
    if last_seed is not None:
        print(f"last_terminal_seed: {last_seed}")


if __name__ == "__main__":
    main()
