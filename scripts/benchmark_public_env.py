#!/usr/bin/env python3
"""Benchmark a public-only policy through the isolated candidate environment."""

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

from balatro_ai_v2.actions import is_legal, iter_legal_actions
from balatro_ai_v2.baselines import PUBLIC_BASELINE_NAMES, build_public_baseline
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.public_env_process import (
    PublicEnvironmentProcess,
    PublicEpisodeSpec,
)


def main() -> None:
    args = build_parser().parse_args()
    if args.seeds < 1 or args.max_decisions < 1 or args.environment_timeout <= 0:
        raise SystemExit("--seeds, --max-decisions, and --environment-timeout must be positive")

    policy, implementation_name = build_public_baseline(args.policy, args.policy_seed)
    started = time.perf_counter()
    results: list[dict[str, object]] = []
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
            history: list[PublicHistoryStep] = []
            terminal_reason = "policy_error"
            complete = False
            won = False
            for _ in range(args.max_decisions):
                action = policy.choose_action(
                    observation,
                    lambda: iter_legal_actions(observation),
                    tuple(history),
                )
                if not is_legal(observation, action):
                    raise RuntimeError(f"public policy emitted illegal action {action!r}")
                transition = environment.step(action)
                history.append(PublicHistoryStep(observation, action, transition.observation))
                observation = transition.observation
                if transition.terminated or transition.truncated:
                    terminal_reason = transition.terminal_reason or "invalid_terminal"
                    complete = transition.terminated
                    won = bool(transition.won) if transition.terminated else False
                    break
            else:  # the worker must truncate exactly at the declared step limit
                raise RuntimeError("public environment did not terminate or truncate at max_decisions")
            results.append(
                {
                    "seed": seed_number,
                    "complete": complete,
                    "won": won,
                    "ante": observation.ante,
                    "round": observation.round_no,
                    "decisions": len(history),
                    "terminal_reason": terminal_reason,
                }
            )

    elapsed = time.perf_counter() - started
    expected_match = _compare_expected(args.expected_report_json, results)
    terminal_reasons = Counter(str(result["terminal_reason"]) for result in results)
    seed_manifest = {
        "deck": args.deck,
        "stake": args.stake,
        "seeds": list(range(args.seed_start, args.seed_start + args.seeds)),
    }
    manifest = {
        "candidate_only": True,
        "command": tuple(sys.argv),
        "policy_name": f"{implementation_name}:public-env-v1",
        "policy_seed": args.policy_seed,
        "deck": args.deck,
        "stake": args.stake,
        "seed_start": args.seed_start,
        "seeds": args.seeds,
        "seed_manifest_digest": _digest(seed_manifest),
        "max_decisions": args.max_decisions,
        "environment_timeout_seconds": args.environment_timeout,
        "worker": asdict(hello),
        "expected_report": str(args.expected_report_json) if args.expected_report_json else None,
        "expected_report_digest": (
            hashlib.sha256(args.expected_report_json.read_bytes()).hexdigest()
            if args.expected_report_json
            else None
        ),
    }
    payload = {
        "manifest": manifest,
        "results": results,
        "summary": {
            "runs": len(results),
            "complete": sum(bool(result["complete"]) for result in results),
            "wins": sum(bool(result["won"]) for result in results),
            "average_ante": sum(int(result["ante"]) for result in results) / len(results),
            "average_round": sum(int(result["round"]) for result in results) / len(results),
            "elapsed_seconds": elapsed,
            "decisions_per_second": sum(int(result["decisions"]) for result in results) / elapsed,
            "episodes_per_second": len(results) / elapsed,
            "terminal_reasons": dict(sorted(terminal_reasons.items())),
            "expected_outcomes_match": expected_match,
        },
    }
    encoded = json.dumps(payload, sort_keys=True)
    print(encoded)
    if args.report_json is not None:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        with args.report_json.open("x", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
    if not all(bool(result["complete"]) for result in results) or expected_match is False:
        raise SystemExit(2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker-python", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--policy", choices=PUBLIC_BASELINE_NAMES, required=True)
    parser.add_argument("--policy-seed", default="baseline-v1")
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="WHITE")
    parser.add_argument("--max-decisions", type=int, default=800)
    parser.add_argument("--environment-timeout", type=float, default=5.0)
    parser.add_argument("--expected-report-json", type=Path)
    parser.add_argument("--report-json", type=Path)
    return parser


def _compare_expected(path: Path | None, results: list[dict[str, object]]) -> bool | None:
    if path is None:
        return None
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read expected report {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise RuntimeError("expected report has no result list")
    expected_rows = payload["results"]
    result_seeds = {result["seed"] for result in results}
    matching = [
        row
        for row in expected_rows
        if isinstance(row, dict) and row.get("seed") in result_seeds
    ]
    return matching == results


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    main()
