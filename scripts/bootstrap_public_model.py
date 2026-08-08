#!/usr/bin/env python3
"""Bootstrap the public model from a frozen public baseline policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch

from balatro_ai_v2.actions import (
    DiscardCards,
    PlayCards,
    PublicAction,
    action_to_data,
    iter_legal_actions,
)
from balatro_ai_v2.baselines import build_public_baseline
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.public_env_process import PublicEnvironmentProcess, PublicEpisodeSpec
from balatro_ai_v2.public_model import (
    ModelCandidate,
    PUBLIC_MODEL_ACTION_PROPOSAL_SCHEMA,
    PublicModelConfig,
    PublicRecurrentPolicyValue,
    TacticalCandidate,
    TacticalFamily,
    public_model_candidates,
    save_public_model,
)
from balatro_ai_v2.public_state import Phase, PublicObservation


BOOTSTRAP_POLICIES = ("greedy", "tactical", "strategic")
BOOTSTRAP_SCHEMA = "stateless_public_behavior_v2"


@dataclass(frozen=True, slots=True)
class BehaviorStep:
    observation: PublicObservation
    candidates: tuple[ModelCandidate, ...]
    previous_action: PublicAction | None
    action: PublicAction


def main() -> None:
    args = build_parser().parse_args()
    if min(
        args.episodes,
        args.max_decisions,
        args.epochs,
        args.batch_size,
        args.hidden_size,
        args.accuracy_samples,
        args.learning_rate,
        args.max_gradient_norm,
        args.environment_timeout,
    ) <= 0:
        raise SystemExit("bootstrap, model, and optimizer bounds must be positive")
    torch.manual_seed(args.training_seed)
    device = torch.device(args.device)
    model = PublicRecurrentPolicyValue(
        PublicModelConfig(hidden_size=args.hidden_size)
    ).to(device)
    policy, policy_name = build_public_baseline(args.policy, args.policy_seed)
    steps: list[BehaviorStep] = []
    episode_results: list[dict[str, object]] = []
    started = time.perf_counter()
    with PublicEnvironmentProcess(
        worker_python=args.worker_python,
        candidate_root=args.candidate_root,
        timeout_seconds=args.environment_timeout,
    ) as environment:
        hello = environment.hello
        for seed_number in range(args.seed_start, args.seed_start + args.episodes):
            observation = environment.reset(
                PublicEpisodeSpec(
                    args.deck,
                    args.stake,
                    str(seed_number),
                    args.max_decisions,
                )
            )
            history: list[PublicHistoryStep] = []
            previous_action = None
            terminated = False
            truncated = False
            won = False
            for _ in range(args.max_decisions):
                action = policy.choose_action(
                    observation,
                    lambda: iter_legal_actions(observation),
                    tuple(history),
                )
                candidates = public_model_candidates(observation)
                _require_representable(action, candidates)
                if _include_behavior_step(args.policy, observation):
                    steps.append(BehaviorStep(observation, candidates, previous_action, action))
                transition = environment.step(action)
                history.append(PublicHistoryStep(observation, action, transition.observation))
                previous_action = action
                observation = transition.observation
                if transition.terminated or transition.truncated:
                    terminated = transition.terminated
                    truncated = transition.truncated
                    won = bool(transition.won) if transition.terminated else False
                    break
            episode_results.append(
                {
                    "seed": seed_number,
                    "complete": terminated,
                    "truncated": truncated,
                    "won": won,
                    "ante": observation.ante,
                    "round": observation.round_no,
                    "decisions": len(history),
                }
            )
    if not steps:
        raise RuntimeError(f"bootstrap policy {args.policy!r} produced no trainable public steps")

    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)
    losses: list[float] = []
    model.train()
    for _ in range(args.epochs):
        epoch_losses: list[float] = []
        for indexes in torch.randperm(len(steps)).split(args.batch_size):
            batch = [steps[index] for index in indexes.tolist()]
            output = model.evaluate_actions(
                tuple(step.observation for step in batch),
                tuple(step.candidates for step in batch),
                tuple(step.previous_action for step in batch),
                tuple(step.action for step in batch),
                reset_mask=torch.ones(len(batch), dtype=torch.bool, device=device),
            )
            loss = -output.log_probabilities.mean()
            if not torch.isfinite(loss):
                raise RuntimeError("behavior bootstrap loss became non-finite")
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_gradient_norm)
            optimizer.step()
            epoch_losses.append(float(loss.detach()))
        losses.append(sum(epoch_losses) / len(epoch_losses))

    accuracy = _deterministic_accuracy(model, steps, args.accuracy_samples)
    checkpoint_digest = save_public_model(args.output_model, model)
    elapsed = time.perf_counter() - started
    report = {
        "manifest": {
            "candidate_only": True,
            "command": tuple(sys.argv),
            "repository_revision": hello.repository_revision,
            "repository_dirty": hello.repository_dirty,
            "candidate_revision": hello.candidate_revision,
            "candidate_dirty": hello.candidate_dirty,
            "candidate_config_digest": hello.config_digest,
            "profile_mode": hello.profile_mode,
            "environment_reward_schema": hello.reward_schema,
            "action_proposal_schema": PUBLIC_MODEL_ACTION_PROPOSAL_SCHEMA,
            "bootstrap_schema": BOOTSTRAP_SCHEMA,
            "behavior_scope": _behavior_scope(args.policy),
            "behavior_policy": policy_name,
            "policy_seed": args.policy_seed,
            "deck": args.deck,
            "stake": args.stake,
            "seed_start": args.seed_start,
            "episodes": args.episodes,
            "seed_manifest_digest": _digest(
                list(range(args.seed_start, args.seed_start + args.episodes))
            ),
            "training_seed": args.training_seed,
            "model_config": asdict(model.config),
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "learning_rate": args.learning_rate,
            "max_gradient_norm": args.max_gradient_norm,
            "checkpoint": str(args.output_model),
            "checkpoint_digest": checkpoint_digest,
        },
        "episodes": episode_results,
        "losses": losses,
        "summary": {
            "behavior_steps": len(steps),
            "complete_episodes": sum(bool(result["complete"]) for result in episode_results),
            "behavior_wins": sum(bool(result["won"]) for result in episode_results),
            "average_behavior_ante": sum(int(result["ante"]) for result in episode_results)
            / len(episode_results),
            "average_behavior_round": sum(int(result["round"]) for result in episode_results)
            / len(episode_results),
            "sampled_deterministic_accuracy": accuracy,
            "final_loss": losses[-1],
            "elapsed_seconds": elapsed,
        },
    }
    encoded = json.dumps(report, sort_keys=True)
    print(encoded)
    if args.report_json is not None:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        with args.report_json.open("x", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
    if not all(bool(result["complete"]) for result in episode_results):
        raise SystemExit(2)


def _deterministic_accuracy(
    model: PublicRecurrentPolicyValue,
    steps: list[BehaviorStep],
    maximum: int,
) -> float:
    model.eval()
    sample = steps[: min(maximum, len(steps))]
    correct = 0
    with torch.no_grad():
        for step in sample:
            decision = model.choose_action(
                step.observation,
                step.candidates,
                previous_action=step.previous_action,
                reset=True,
            )
            correct += action_to_data(decision.action) == action_to_data(step.action)
    return correct / len(sample)


def _include_behavior_step(policy: str, observation: PublicObservation) -> bool:
    return policy != "strategic" or observation.phase in {Phase.SHOP, Phase.PACK}


def _behavior_scope(policy: str) -> str:
    return "shop_pack" if policy == "strategic" else "all_public_actions"


def _require_representable(
    action: PublicAction,
    candidates: tuple[ModelCandidate, ...],
) -> None:
    if isinstance(action, PlayCards):
        family = TacticalFamily.PLAY
    elif isinstance(action, DiscardCards):
        family = TacticalFamily.DISCARD
    else:
        if action in candidates:
            return
        raise RuntimeError(f"behavior action {action!r} is absent from the public proposal")
    if not any(
        isinstance(candidate, TacticalCandidate) and candidate.family == family
        for candidate in candidates
    ):
        raise RuntimeError(f"behavior tactical family {family!r} is absent from the public proposal")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-python", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--policy", choices=BOOTSTRAP_POLICIES, default="greedy")
    parser.add_argument("--policy-seed", default="bootstrap-v1")
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="WHITE")
    parser.add_argument("--seed-start", type=int, default=30001)
    parser.add_argument("--episodes", type=int, default=100)
    parser.add_argument("--max-decisions", type=int, default=800)
    parser.add_argument("--training-seed", type=int, default=1)
    parser.add_argument("--hidden-size", type=int, default=64)
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--max-gradient-norm", type=float, default=1.0)
    parser.add_argument("--accuracy-samples", type=int, default=256)
    parser.add_argument("--environment-timeout", type=float, default=5.0)
    parser.add_argument("--device", default="cpu")
    return parser


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    main()
