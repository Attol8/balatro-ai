#!/usr/bin/env python3
"""Train the recurrent public model through isolated candidate workers."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch
from torch import Tensor

from balatro_ai_v2.actions import (
    CashOut,
    PublicAction,
    SelectBlind,
    action_to_data,
    iter_legal_actions,
)
from balatro_ai_v2.baselines import build_public_baseline
from balatro_ai_v2.policy import PublicPolicy
from balatro_ai_v2.public_env_process import (
    PublicEnvironmentProcess,
    PublicEpisodeSpec,
    PublicTransition,
)
from balatro_ai_v2.public_model import (
    ModelCandidate,
    PUBLIC_MODEL_ACTION_PROPOSAL_SCHEMA,
    PublicModelConfig,
    PublicRecurrentPolicyValue,
    load_public_model,
    public_model_candidates,
    save_public_model,
)
from balatro_ai_v2.public_state import Phase, PublicObservation


TRAIN_REWARD_SCHEMAS = ("sparse_terminal_v1", "public_blind_clear_v1")


@dataclass(slots=True)
class WorkerState:
    environment: PublicEnvironmentProcess
    observation: PublicObservation
    candidates: tuple[ModelCandidate, ...]
    hidden: Tensor
    previous_action: PublicAction | None
    seed_number: int
    next_seed_number: int
    episode_steps: int = 0
    environment_return: float = 0.0
    training_return: float = 0.0
    episode_actions: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RolloutRecord:
    observation: PublicObservation
    candidates: tuple[ModelCandidate, ...]
    previous_action: PublicAction | None
    hidden: Tensor
    action: PublicAction
    old_log_probability: float
    episode_start: bool
    policy_trainable: bool


def main() -> None:
    args = build_parser().parse_args()
    _validate_args(args)
    torch.manual_seed(args.training_seed)
    device = torch.device(args.device)
    model = (
        load_public_model(args.resume_model, device=device)
        if args.resume_model is not None
        else PublicRecurrentPolicyValue(
            PublicModelConfig(hidden_size=args.hidden_size)
        ).to(device)
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)
    tactical_controller = (
        None
        if args.tactical_controller == "model"
        else build_public_baseline(args.tactical_controller, "hybrid-controller-v1")[0]
    )
    environments: list[PublicEnvironmentProcess] = []
    started = time.perf_counter()
    episode_results: list[dict[str, object]] = []
    update_results: list[dict[str, float]] = []
    started_seeds: list[int] = []
    try:
        for _ in range(args.workers):
            environments.append(
                PublicEnvironmentProcess(
                    worker_python=args.worker_python,
                    candidate_root=args.candidate_root,
                    timeout_seconds=args.environment_timeout,
                )
            )
        hello = environments[0].hello
        if any(environment.hello != hello for environment in environments[1:]):
            raise RuntimeError("candidate workers reported different provenance")
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            reset_futures = []
            for worker_index, environment in enumerate(environments):
                seed_number = args.seed_start + worker_index
                started_seeds.append(seed_number)
                reset_futures.append(
                    executor.submit(
                        environment.reset,
                        PublicEpisodeSpec(
                            args.deck,
                            args.stake,
                            str(seed_number),
                            args.max_episode_steps,
                        ),
                    )
                )
            states = [
                WorkerState(
                    environment=environment,
                    observation=future.result(),
                    candidates=(),
                    hidden=model.initial_hidden(1).cpu(),
                    previous_action=None,
                    seed_number=args.seed_start + index,
                    next_seed_number=args.seed_start + args.workers + index,
                )
                for index, (environment, future) in enumerate(zip(environments, reset_futures))
            ]
            for state in states:
                state.candidates = public_model_candidates(state.observation)

            for update in range(args.updates):
                records, rewards, terminated, truncated, values, truncation_values = _collect_rollout(
                    model,
                    states,
                    executor,
                    args,
                    episode_results,
                    started_seeds,
                    tactical_controller,
                )
                bootstrap = _bootstrap_values(model, states)
                advantages, returns = generalized_advantage_estimate(
                    rewards,
                    terminated,
                    truncated,
                    values,
                    bootstrap,
                    truncation_values,
                    args.gamma,
                    args.gae_lambda,
                )
                metrics = _ppo_update(model, optimizer, records, advantages, returns, args)
                metrics["update"] = float(update + 1)
                update_results.append(metrics)
    finally:
        for environment in environments:
            environment.close()

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
            "python_version": sys.version.split()[0],
            "worker_python_version": hello.python_version,
            "profile_mode": hello.profile_mode,
            "environment_reward_schema": hello.reward_schema,
            "training_reward_schema": args.training_reward,
            "action_proposal_schema": PUBLIC_MODEL_ACTION_PROPOSAL_SCHEMA,
            "control_schema": _control_schema(args.tactical_controller),
            "deck": args.deck,
            "stake": args.stake,
            "seed_start": args.seed_start,
            "seed_manifest_digest": _digest(started_seeds),
            "training_seed": args.training_seed,
            "workers": args.workers,
            "updates": args.updates,
            "rollout_steps": args.rollout_steps,
            "max_episode_steps": args.max_episode_steps,
            "model_config": asdict(model.config),
            "optimizer": {
                "name": "Adam",
                "learning_rate": args.learning_rate,
                "ppo_epochs": args.ppo_epochs,
                "gamma": args.gamma,
                "gae_lambda": args.gae_lambda,
                "clip_ratio": args.clip_ratio,
                "value_coefficient": args.value_coefficient,
                "entropy_coefficient": args.entropy_coefficient,
                "max_gradient_norm": args.max_gradient_norm,
            },
            "checkpoint": str(args.output_model),
            "checkpoint_digest": checkpoint_digest,
        },
        "episodes": episode_results,
        "updates": update_results,
        "summary": {
            "environment_steps": args.workers * args.updates * args.rollout_steps,
            "episodes_completed": len(episode_results),
            "wins": sum(bool(result["won"]) for result in episode_results),
            "truncations": sum(bool(result["truncated"]) for result in episode_results),
            "elapsed_seconds": elapsed,
            "steps_per_second": args.workers * args.updates * args.rollout_steps / elapsed,
        },
    }
    encoded = json.dumps(report, sort_keys=True)
    print(encoded)
    if args.report_json is not None:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        with args.report_json.open("x", encoding="utf-8") as handle:
            handle.write(encoded + "\n")


def _collect_rollout(
    model: PublicRecurrentPolicyValue,
    states: list[WorkerState],
    executor: ThreadPoolExecutor,
    args: argparse.Namespace,
    episode_results: list[dict[str, object]],
    started_seeds: list[int],
    tactical_controller: PublicPolicy | None,
) -> tuple[list[RolloutRecord], Tensor, Tensor, Tensor, Tensor, Tensor]:
    workers = len(states)
    records: list[RolloutRecord] = []
    rewards = torch.zeros(args.rollout_steps, workers)
    terminated = torch.zeros(args.rollout_steps, workers, dtype=torch.bool)
    truncated = torch.zeros(args.rollout_steps, workers, dtype=torch.bool)
    values = torch.zeros(args.rollout_steps, workers)
    truncation_values = torch.zeros(args.rollout_steps, workers)
    model.eval()
    for time_index in range(args.rollout_steps):
        observations = tuple(state.observation for state in states)
        candidate_sets = tuple(state.candidates for state in states)
        previous_actions = tuple(state.previous_action for state in states)
        hidden_input = torch.cat([state.hidden for state in states]).to(next(model.parameters()).device)
        with torch.no_grad():
            output = model.sample_actions(
                observations,
                candidate_sets,
                previous_actions,
                hidden_input,
            )
        actions = list(output.actions)
        policy_trainable: list[bool] = []
        for worker_index, observation in enumerate(observations):
            controlled = _fixed_control_action(observation, tactical_controller)
            policy_trainable.append(controlled is None)
            if controlled is not None:
                actions[worker_index] = controlled
        futures = [
            executor.submit(state.environment.step, action)
            for state, action in zip(states, actions)
        ]
        transitions = []
        for worker_index, future in enumerate(futures):
            try:
                transitions.append(future.result())
            except Exception as exc:
                action_history = [
                    *states[worker_index].episode_actions,
                    action_to_data(actions[worker_index]),
                ][-64:]
                raise RuntimeError(
                    "public worker failed "
                    f"worker={worker_index} seed={states[worker_index].seed_number} "
                    f"actions={action_history}"
                ) from exc

        reset_work: list[tuple[int, object]] = []
        for worker_index, (state, action, transition) in enumerate(zip(states, actions, transitions)):
            records.append(
                RolloutRecord(
                    observation=state.observation,
                    candidates=state.candidates,
                    previous_action=state.previous_action,
                    hidden=hidden_input[worker_index : worker_index + 1].detach().cpu(),
                    action=action,
                    old_log_probability=float(output.log_probabilities[worker_index]),
                    episode_start=state.previous_action is None,
                    policy_trainable=policy_trainable[worker_index],
                )
            )
            training_reward = _training_reward(
                state.observation,
                transition,
                args.training_reward,
                args.progress_reward,
            )
            rewards[time_index, worker_index] = training_reward
            terminated[time_index, worker_index] = transition.terminated
            truncated[time_index, worker_index] = transition.truncated
            values[time_index, worker_index] = output.values[worker_index].cpu()
            state.episode_steps += 1
            state.episode_actions.append(action_to_data(action))
            state.environment_return += transition.reward
            state.training_return += training_reward
            if transition.truncated:
                final_candidates = public_model_candidates(transition.observation)
                with torch.no_grad():
                    final_output = model.step(
                        (transition.observation,),
                        (final_candidates,),
                        (action,),
                        output.hidden[worker_index : worker_index + 1],
                    )
                truncation_values[time_index, worker_index] = final_output.values[0].cpu()
            if transition.terminated or transition.truncated:
                episode_results.append(
                    {
                        "seed": state.seed_number,
                        "steps": state.episode_steps,
                        "won": bool(transition.won) if transition.terminated else False,
                        "terminated": transition.terminated,
                        "truncated": transition.truncated,
                        "ante": transition.observation.ante,
                        "round": transition.observation.round_no,
                        "environment_return": state.environment_return,
                        "training_return": state.training_return,
                    }
                )
                seed_number = state.next_seed_number
                started_seeds.append(seed_number)
                future = executor.submit(
                    state.environment.reset,
                    PublicEpisodeSpec(
                        args.deck,
                        args.stake,
                        str(seed_number),
                        args.max_episode_steps,
                    ),
                )
                reset_work.append((worker_index, future))
                state.seed_number = seed_number
                state.next_seed_number += workers
                state.episode_steps = 0
                state.environment_return = 0.0
                state.training_return = 0.0
                state.episode_actions.clear()
                state.hidden = model.initial_hidden(1).cpu()
                state.previous_action = None
            else:
                state.observation = transition.observation
                state.candidates = public_model_candidates(state.observation)
                state.hidden = output.hidden[worker_index : worker_index + 1].detach().cpu()
                state.previous_action = action
        for worker_index, future in reset_work:
            states[worker_index].observation = future.result()
            states[worker_index].candidates = public_model_candidates(states[worker_index].observation)
    return records, rewards, terminated, truncated, values, truncation_values


def _bootstrap_values(model: PublicRecurrentPolicyValue, states: list[WorkerState]) -> Tensor:
    model.eval()
    hidden = torch.cat([state.hidden for state in states]).to(next(model.parameters()).device)
    with torch.no_grad():
        output = model.step(
            tuple(state.observation for state in states),
            tuple(state.candidates for state in states),
            tuple(state.previous_action for state in states),
            hidden,
        )
    return output.values.detach().cpu()


def generalized_advantage_estimate(
    rewards: Tensor,
    terminated: Tensor,
    truncated: Tensor,
    values: Tensor,
    bootstrap_values: Tensor,
    truncation_values: Tensor,
    gamma: float,
    gae_lambda: float,
) -> tuple[Tensor, Tensor]:
    if not all(
        tensor.shape == rewards.shape
        for tensor in (terminated, truncated, values, truncation_values)
    ):
        raise ValueError("rollout tensors must have the same shape")
    if torch.any(terminated & truncated):
        raise ValueError("a rollout step cannot terminate and truncate")
    advantages = torch.zeros_like(rewards)
    next_advantage = torch.zeros(rewards.shape[1])
    for time_index in reversed(range(rewards.shape[0])):
        horizon_values = (
            bootstrap_values if time_index == rewards.shape[0] - 1 else values[time_index + 1]
        )
        next_values = torch.where(
            terminated[time_index],
            torch.zeros_like(horizon_values),
            torch.where(truncated[time_index], truncation_values[time_index], horizon_values),
        )
        continuation = (~terminated[time_index] & ~truncated[time_index]).float()
        delta = rewards[time_index] + gamma * next_values - values[time_index]
        next_advantage = delta + gamma * gae_lambda * continuation * next_advantage
        advantages[time_index] = next_advantage
    return advantages, advantages + values


def _ppo_update(
    model: PublicRecurrentPolicyValue,
    optimizer: torch.optim.Optimizer,
    records: list[RolloutRecord],
    advantages: Tensor,
    returns: Tensor,
    args: argparse.Namespace,
) -> dict[str, float]:
    device = next(model.parameters()).device
    flat_advantages = advantages.flatten()
    flat_returns = returns.flatten()
    flat_advantages = (flat_advantages - flat_advantages.mean()) / (
        flat_advantages.std(unbiased=False) + 1e-8
    )
    count = len(records)
    workers = advantages.shape[1]
    rollout_steps = advantages.shape[0]
    if count != flat_advantages.numel():
        raise RuntimeError("rollout record and advantage counts differ")
    totals = {
        "policy_loss": 0.0,
        "value_loss": 0.0,
        "entropy": 0.0,
        "gradient_norm_before_clip": 0.0,
        "approximate_kl": 0.0,
        "clip_fraction": 0.0,
    }
    model.train()
    for _ in range(args.ppo_epochs):
        hidden = torch.cat([record.hidden for record in records[:workers]]).to(device)
        new_log_probability_rows: list[Tensor] = []
        value_rows: list[Tensor] = []
        entropy_rows: list[Tensor] = []
        for time_index in range(rollout_steps):
            batch = records[time_index * workers : (time_index + 1) * workers]
            output = model.evaluate_actions(
                tuple(record.observation for record in batch),
                tuple(record.candidates for record in batch),
                tuple(record.previous_action for record in batch),
                tuple(record.action for record in batch),
                hidden,
                torch.tensor(
                    [record.episode_start for record in batch],
                    dtype=torch.bool,
                    device=device,
                ),
            )
            hidden = output.hidden
            new_log_probability_rows.append(output.log_probabilities)
            value_rows.append(output.values)
            entropy_rows.append(output.entropies)
        new_log_probabilities = torch.cat(new_log_probability_rows)
        new_values = torch.cat(value_rows)
        entropies = torch.cat(entropy_rows)
        old_log_probabilities = torch.tensor(
            [record.old_log_probability for record in records], device=device
        )
        trainable_mask = torch.tensor(
            [record.policy_trainable for record in records],
            dtype=torch.bool,
            device=device,
        )
        ratio = torch.exp(new_log_probabilities - old_log_probabilities)
        normalized_advantages = flat_advantages.to(device)
        unclipped = ratio * normalized_advantages
        clipped = (
            torch.clamp(ratio, 1 - args.clip_ratio, 1 + args.clip_ratio)
            * normalized_advantages
        )
        if torch.any(trainable_mask):
            policy_loss = -torch.minimum(unclipped, clipped)[trainable_mask].mean()
            entropy = entropies[trainable_mask].mean()
        else:
            policy_loss = new_log_probabilities.sum() * 0.0
            entropy = new_log_probabilities.sum() * 0.0
        value_loss = torch.nn.functional.mse_loss(new_values, flat_returns.to(device))
        loss = (
            policy_loss
            + args.value_coefficient * value_loss
            - args.entropy_coefficient * entropy
        )
        if not torch.isfinite(loss):
            raise RuntimeError("PPO loss became non-finite")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        gradient_norm = torch.nn.utils.clip_grad_norm_(model.parameters(), args.max_gradient_norm)
        if not math.isfinite(float(gradient_norm)):
            raise RuntimeError("PPO gradient became non-finite")
        optimizer.step()
        totals["policy_loss"] += float(policy_loss.detach())
        totals["value_loss"] += float(value_loss.detach())
        totals["entropy"] += float(entropy.detach())
        totals["gradient_norm_before_clip"] += float(gradient_norm)
        totals["approximate_kl"] += float(
            (old_log_probabilities - new_log_probabilities)[trainable_mask].mean().detach()
            if torch.any(trainable_mask)
            else 0.0
        )
        totals["clip_fraction"] += float(
            ((ratio - 1.0).abs() > args.clip_ratio)[trainable_mask].float().mean().detach()
            if torch.any(trainable_mask)
            else 0.0
        )
    return {name: value / args.ppo_epochs for name, value in totals.items()}


def _training_reward(
    before: PublicObservation,
    transition: PublicTransition,
    schema: str,
    progress_reward: float,
) -> float:
    reward = float(transition.reward)
    if (
        schema == "public_blind_clear_v1"
        and before.phase == Phase.SELECTING_HAND
        and transition.observation.phase == Phase.ROUND_EVAL
    ):
        reward += progress_reward
    return reward


def _fixed_control_action(
    observation: PublicObservation,
    tactical_controller: PublicPolicy | None,
) -> PublicAction | None:
    if tactical_controller is None:
        return None
    if observation.phase == Phase.BLIND_SELECT:
        return SelectBlind()
    if observation.phase == Phase.SELECTING_HAND:
        return tactical_controller.choose_action(
            observation,
            lambda: iter_legal_actions(observation),
            (),
        )
    if observation.phase == Phase.ROUND_EVAL:
        return CashOut()
    return None


def _control_schema(tactical_controller: str) -> str:
    return (
        "model_all_public_actions_v1"
        if tactical_controller == "model"
        else f"fixed_flow_{tactical_controller}_hands_model_shop_pack_v1"
    )


def _validate_args(args: argparse.Namespace) -> None:
    positive = (
        args.workers,
        args.updates,
        args.rollout_steps,
        args.max_episode_steps,
        args.hidden_size,
        args.ppo_epochs,
        args.environment_timeout,
        args.learning_rate,
        args.max_gradient_norm,
    )
    if any(value <= 0 for value in positive):
        raise SystemExit("worker, rollout, model, timeout, and optimizer bounds must be positive")
    if not 0 <= args.gamma <= 1 or not 0 <= args.gae_lambda <= 1 or not 0 < args.clip_ratio < 1:
        raise SystemExit("gamma, GAE lambda, and clip ratio are outside their bounds")
    if args.progress_reward < 0 or args.value_coefficient < 0 or args.entropy_coefficient < 0:
        raise SystemExit("reward and loss coefficients cannot be negative")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-python", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--resume-model", type=Path)
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="WHITE")
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--updates", type=int, default=10)
    parser.add_argument("--rollout-steps", type=int, default=32)
    parser.add_argument("--max-episode-steps", type=int, default=800)
    parser.add_argument("--training-seed", type=int, default=1)
    parser.add_argument(
        "--tactical-controller",
        choices=("model", "greedy", "tactical"),
        default="greedy",
    )
    parser.add_argument("--training-reward", choices=TRAIN_REWARD_SCHEMAS, default="sparse_terminal_v1")
    parser.add_argument("--progress-reward", type=float, default=0.02)
    parser.add_argument("--hidden-size", type=int, default=128)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--gamma", type=float, default=0.99)
    parser.add_argument("--gae-lambda", type=float, default=0.95)
    parser.add_argument("--clip-ratio", type=float, default=0.2)
    parser.add_argument("--ppo-epochs", type=int, default=4)
    parser.add_argument("--value-coefficient", type=float, default=0.5)
    parser.add_argument("--entropy-coefficient", type=float, default=0.01)
    parser.add_argument("--max-gradient-norm", type=float, default=0.5)
    parser.add_argument("--environment-timeout", type=float, default=5.0)
    parser.add_argument("--device", default="cpu")
    return parser


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    main()
