#!/usr/bin/env python3
"""Evaluate a frozen recurrent model through the isolated public environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch

from balatro_ai_v2.actions import CashOut, SelectBlind, iter_legal_actions
from balatro_ai_v2.baselines import build_public_baseline
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.public_env_process import PublicEnvironmentProcess, PublicEpisodeSpec
from balatro_ai_v2.public_model import (
    PUBLIC_MODEL_ACTION_PROPOSAL_SCHEMA,
    load_public_model,
    public_model_candidates,
)
from balatro_ai_v2.public_state import Phase


def main() -> None:
    args = build_parser().parse_args()
    if args.seeds <= 0 or args.max_decisions <= 0 or args.environment_timeout <= 0:
        raise SystemExit("--seeds, --max-decisions, and --environment-timeout must be positive")
    model = load_public_model(args.model, device=args.device)
    model.eval()
    tactical_controller = (
        None
        if args.tactical_controller == "model"
        else build_public_baseline(args.tactical_controller, "hybrid-controller-v1")[0]
    )
    results: list[dict[str, object]] = []
    started = time.perf_counter()
    with PublicEnvironmentProcess(
        worker_python=args.worker_python,
        candidate_root=args.candidate_root,
        timeout_seconds=args.environment_timeout,
    ) as environment:
        hello = environment.hello
        for seed_number in range(args.seed_start, args.seed_start + args.seeds):
            observation = environment.reset(
                PublicEpisodeSpec(
                    args.deck,
                    args.stake,
                    str(seed_number),
                    args.max_decisions,
                )
            )
            hidden = model.initial_hidden(1)
            previous_action = None
            history: list[PublicHistoryStep] = []
            terminal_reason = "decision_limit"
            won = False
            terminated = False
            truncated = False
            decisions = 0
            for _ in range(args.max_decisions):
                candidates = public_model_candidates(observation)
                controlled = _fixed_control_action(
                    observation,
                    tactical_controller,
                    tuple(history),
                )
                if controlled is None:
                    with torch.no_grad():
                        decision = model.choose_action(
                            observation,
                            candidates,
                            previous_action=previous_action,
                            hidden=hidden,
                        )
                    action = decision.action
                    next_hidden = decision.hidden
                else:
                    with torch.no_grad():
                        output = model.step(
                            (observation,),
                            (candidates,),
                            (previous_action,),
                            hidden,
                        )
                    action = controlled
                    next_hidden = output.hidden
                transition = environment.step(action)
                decisions += 1
                history.append(PublicHistoryStep(observation, action, transition.observation))
                observation = transition.observation
                hidden = next_hidden
                previous_action = action
                if transition.terminated or transition.truncated:
                    terminal_reason = transition.terminal_reason or "invalid_terminal"
                    won = bool(transition.won) if transition.terminated else False
                    terminated = transition.terminated
                    truncated = transition.truncated
                    break
            results.append(
                {
                    "seed": seed_number,
                    "complete": terminated,
                    "won": won,
                    "truncated": truncated,
                    "ante": observation.ante,
                    "round": observation.round_no,
                    "decisions": decisions,
                    "terminal_reason": terminal_reason,
                }
            )
    elapsed = time.perf_counter() - started
    terminal_reasons = Counter(str(result["terminal_reason"]) for result in results)
    payload = {
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
            "control_schema": _control_schema(args.tactical_controller),
            "model": str(args.model),
            "model_digest": hashlib.sha256(args.model.read_bytes()).hexdigest(),
            "model_config": asdict(model.config),
            "deck": args.deck,
            "stake": args.stake,
            "seed_start": args.seed_start,
            "seeds": args.seeds,
            "seed_manifest_digest": _digest(
                {
                    "deck": args.deck,
                    "stake": args.stake,
                    "seeds": list(range(args.seed_start, args.seed_start + args.seeds)),
                }
            ),
            "max_decisions": args.max_decisions,
            "device": args.device,
        },
        "results": results,
        "summary": {
            "runs": len(results),
            "complete": sum(bool(result["complete"]) for result in results),
            "wins": sum(bool(result["won"]) for result in results),
            "truncations": sum(bool(result["truncated"]) for result in results),
            "average_ante": sum(int(result["ante"]) for result in results) / len(results),
            "average_round": sum(int(result["round"]) for result in results) / len(results),
            "elapsed_seconds": elapsed,
            "decisions_per_second": sum(int(result["decisions"]) for result in results) / elapsed,
            "terminal_reasons": dict(sorted(terminal_reasons.items())),
        },
    }
    encoded = json.dumps(payload, sort_keys=True)
    print(encoded)
    if args.report_json is not None:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        with args.report_json.open("x", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
    if not all(bool(result["complete"]) for result in results):
        raise SystemExit(2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-python", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="WHITE")
    parser.add_argument("--max-decisions", type=int, default=800)
    parser.add_argument("--environment-timeout", type=float, default=5.0)
    parser.add_argument(
        "--tactical-controller",
        choices=("model", "greedy", "tactical", "strategic"),
        default="model",
    )
    parser.add_argument("--device", default="cpu")
    return parser


def _fixed_control_action(observation, tactical_controller, history):
    if tactical_controller is None:
        return None
    if observation.phase == Phase.BLIND_SELECT:
        return SelectBlind()
    if observation.phase == Phase.SELECTING_HAND:
        return tactical_controller.choose_action(
            observation,
            lambda: iter_legal_actions(observation),
            history,
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


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    main()
