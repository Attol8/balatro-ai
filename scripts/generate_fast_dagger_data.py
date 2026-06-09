from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.fast.full_game import FastFullGameEnv, RolloutSearchRunAgent, SearchRunAgent
from balatro_ai_v2.learning.imitation import HybridImitationRunAgent, ImitationRunAgent, load_action_policy
from balatro_ai_v2.learning.trajectories import TrajectoryStep


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect DAgger labels from states visited by a fast policy")
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--deck", default="b_red")
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=32)
    parser.add_argument("--max-steps", type=int, default=600)
    parser.add_argument("--output-jsonl", type=Path, default=Path("runs/fast_dagger_trajectories.jsonl"))
    parser.add_argument("--hybrid-tactical", action="store_true")
    parser.add_argument("--beam-width", type=int, default=SearchRunAgent.beam_width)
    parser.add_argument("--action-beam", type=int, default=SearchRunAgent.action_beam)
    parser.add_argument("--shop-rollout-candidates", type=int, default=RolloutSearchRunAgent.shop_rollout_candidates)
    parser.add_argument("--shop-rollout-steps", type=int, default=RolloutSearchRunAgent.shop_rollout_steps)
    args = parser.parse_args()

    behavior_policy = load_action_policy(args.model)
    tactical_agent = SearchRunAgent()
    tactical_agent.beam_width = args.beam_width
    tactical_agent.action_beam = args.action_beam
    behavior_agent = (
        HybridImitationRunAgent(behavior_policy, tactical_agent)
        if args.hybrid_tactical
        else ImitationRunAgent(behavior_policy)
    )

    oracle = RolloutSearchRunAgent()
    oracle.beam_width = args.beam_width
    oracle.action_beam = args.action_beam
    oracle.shop_rollout_candidates = args.shop_rollout_candidates
    oracle.shop_rollout_steps = args.shop_rollout_steps

    args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    examples = 0
    wins = 0
    with args.output_jsonl.open("w", encoding="utf-8") as handle:
        for seed in range(args.seed_start, args.seed_start + args.seeds):
            env = FastFullGameEnv(deck_key=args.deck)
            env.reset(seed=seed)
            terminated = False
            step = 0
            while not terminated and step < args.max_steps:
                observation = env.observation()
                legal_actions = env.legal_action_ids()
                oracle_action = oracle.act(env)
                if oracle_action not in legal_actions:
                    raise ValueError(f"oracle emitted illegal action {oracle_action} for seed={seed} step={step}")
                behavior_action = behavior_agent.act(env)
                result = env.step(behavior_action)
                terminated = result.terminated
                handle.write(
                    json.dumps(
                        TrajectoryStep(
                            seed=seed,
                            step=step,
                            observation=observation,
                            legal_actions=legal_actions,
                            action=oracle_action,
                            reward=result.reward,
                            terminated=terminated,
                            won=env.won,
                            rounds_cleared=env.rounds_cleared,
                            info=result.info,
                        ).to_jsonable(),
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                    + "\n"
                )
                examples += 1
                step += 1
            wins += int(env.won)

    print(f"model: {args.model}")
    print(f"output_jsonl: {args.output_jsonl}")
    print(f"examples: {examples}")
    print(f"seeds: {args.seeds}")
    print(f"behavior_wins: {wins}")
    print(f"hybrid_tactical: {args.hybrid_tactical}")
    print(f"shop_rollout_candidates: {oracle.shop_rollout_candidates}")
    print(f"shop_rollout_steps: {oracle.shop_rollout_steps}")


if __name__ == "__main__":
    main()
