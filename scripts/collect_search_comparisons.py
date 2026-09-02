#!/usr/bin/env python3
"""Collect public sibling comparisons from the frozen pre-boss search policy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.actions import is_legal, iter_legal_actions
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.preboss_search import PublicPreBossSearchPolicy
from balatro_ai_v2.public_env_process import PublicEnvironmentProcess, PublicEpisodeSpec
from balatro_ai_v2.search_distillation import SearchComparison, write_comparisons


def main() -> None:
    args = build_parser().parse_args()
    if min(args.episodes, args.max_decisions, args.particles) <= 0:
        raise SystemExit("episodes, decisions, and particles must be positive")
    comparisons: list[SearchComparison] = []
    with PublicEnvironmentProcess(
        worker_python=args.worker_python,
        candidate_root=args.candidate_root,
        timeout_seconds=args.environment_timeout,
    ) as environment:
        for seed_number in range(args.seed_start, args.seed_start + args.episodes):
            policy = PublicPreBossSearchPolicy(
                search_nonce=args.search_nonce,
                particles=args.particles,
            )
            observation = environment.reset(
                PublicEpisodeSpec(args.deck, args.stake, str(seed_number), args.max_decisions)
            )
            history: list[PublicHistoryStep] = []
            for _ in range(args.max_decisions):
                action = policy.choose_action(
                    observation, lambda: iter_legal_actions(observation), tuple(history)
                )
                if not is_legal(observation, action):
                    raise RuntimeError(f"public search emitted illegal action {action!r}")
                decision = policy.last_decision
                if decision is not None and len(decision.results) >= 2:
                    target = next(
                        blind for blind in observation.blinds if blind.name == decision.blind_name
                    )
                    comparisons.append(
                        SearchComparison(
                            observation,
                            tuple(result.action for result in decision.results),
                            tuple(
                                result.wins / result.particles
                                + 0.1 * float(result.mean_score / target.score)
                                for result in decision.results
                            ),
                            decision.selected,
                            history[-1].action if history else None,
                        )
                    )
                transition = environment.step(action)
                history.append(PublicHistoryStep(observation, action, transition.observation))
                observation = transition.observation
                if transition.terminated or transition.truncated:
                    break
    if not comparisons:
        raise RuntimeError("search produced no sibling comparisons")
    write_comparisons(args.output_jsonl, tuple(comparisons))
    print(json.dumps({"candidate_only": True, "comparisons": len(comparisons)}))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-python", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--episodes", type=int, default=100)
    parser.add_argument("--max-decisions", type=int, default=800)
    parser.add_argument("--particles", type=int, default=32)
    parser.add_argument("--search-nonce", default="expert-iteration-v1")
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="GOLD")
    parser.add_argument("--environment-timeout", type=float, default=5.0)
    return parser


if __name__ == "__main__":
    main()
