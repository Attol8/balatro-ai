"""Evaluate frozen public-only controls in the pinned candidate kernel."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.backend import RunSpec
from balatro_ai_v2.balatrobot.runner import AuthorityRunner
from balatro_ai_v2.balatrobot.tracing import build_manifest
from balatro_ai_v2.baselines import PUBLIC_BASELINE_NAMES, build_public_baseline
from balatro_ai_v2.blind_search import exact_blind_inference_budget
from balatro_ai_v2.jackdaw import JackdawBackend, JackdawUnavailable, verify_jackdaw_runtime
from balatro_ai_v2.policy_process import PolicyProcess
from balatro_ai_v2.public_state import PublicBlind, PublicObservation
from balatro_ai_v2.strategy_tuning import StrategyTuning


TERMINAL_PROJECTION_SCHEMA_VERSION = 2


def main() -> None:
    args = build_parser().parse_args()
    if (
        args.seeds < 1
        or args.max_decisions < 1
        or args.ante_cap < 1
        or args.policy_timeout <= 0
    ):
        raise SystemExit(
            "--seeds, --max-decisions, --ante-cap, and --policy-timeout must be positive"
        )
    root = Path(__file__).resolve().parents[1]
    try:
        tuning = StrategyTuning.from_json(args.tuning_json)
    except ValueError as exc:
        raise SystemExit(f"invalid --tuning-json: {exc}") from exc
    _, implementation_name = build_public_baseline(args.policy, args.policy_seed, tuning)
    policy_name = f"{implementation_name}:process-v1"
    exact_budget = (
        f"{exact_blind_inference_budget()};" if args.policy == "red_gold_search" else ""
    )
    backend: JackdawBackend | None = None
    policy: PolicyProcess | None = None
    started = time.perf_counter()
    try:
        candidate_runtime = verify_jackdaw_runtime()
        backend = JackdawBackend()
        policy = PolicyProcess(
            args.policy,
            policy_seed=args.policy_seed,
            timeout_seconds=args.policy_timeout,
            tuning=tuning,
        )
        results = []
        for seed_number in range(args.seed_start, args.seed_start + args.seeds):
            result = AuthorityRunner(
                backend,
                policy,
                max_decisions=args.max_decisions,
                max_antes_cleared=args.ante_cap,
            ).run(
                RunSpec(args.deck, args.stake, str(seed_number))
            )
            results.append(
                {
                    "seed": seed_number,
                    "complete": result.complete,
                    "won": result.won,
                    "antes_cleared": result.antes_cleared,
                    "survived_to_ante_6": result.complete and result.ante >= 6,
                    "ante": result.ante,
                    "round": result.round_no,
                    "decisions": result.decisions,
                    "rejected_decisions": result.rejected_decisions,
                    "terminal_reason": result.terminal_reason,
                    "terminal": terminal_projection(
                        result.final_observation,
                        terminal_blind=result.terminal_blind,
                    ),
                    "final_observation": (
                        json.loads(result.final_observation.canonical_json())
                        if result.final_observation is not None
                        else None
                    ),
                    "actions": {
                        "counts": dict(result.action_counts),
                        "semantic_counts": dict(result.semantic_action_counts),
                        "cards_played": result.cards_played,
                        "cards_discarded": result.cards_discarded,
                    },
                    "policy_diagnostics": asdict(policy.run_diagnostic_counters),
                }
            )
        elapsed = time.perf_counter() - started
        terminal_reasons = Counter(str(result["terminal_reason"]) for result in results)
        summary = summarize_results(results, elapsed=elapsed, terminal_reasons=terminal_reasons)
        complete_runs = sum(bool(result["complete"]) for result in results)
        manifest = build_manifest(
            repository_root=root,
            command=tuple(sys.argv),
            policy_name=policy_name,
            backend=backend.metadata,
            run=RunSpec(args.deck, args.stake, f"{args.seed_start}:{args.seeds}"),
            max_decisions=args.max_decisions,
            max_antes_cleared=args.ante_cap,
            max_settle_polls=0,
            launch_fast=False,
            launch_headless=False,
            profile_mode="all_unlocked",
            inference_budget=(
                "policy_action_contract=public_legality_v3;random_public_actions<=256;"
                "tactical_candidates<=2048;draw_branches<=512;"
                f"{exact_budget}"
                f"policy_timeout_seconds={args.policy_timeout}"
                f";ante_cap={args.ante_cap}"
            ),
        )
        payload = {
            "candidate_only": True,
            "candidate_runtime": candidate_runtime,
            "manifest": asdict(manifest),
            "strategy_tuning": json.loads(tuning.canonical_json()),
            "results": results,
            "summary": summary,
        }
        encoded = json.dumps(payload, sort_keys=True)
        if args.fitness_only:
            print(json.dumps({"fitness": summary["mean_antes_cleared"]}))
        else:
            print(encoded)
        if args.report_json is not None:
            args.report_json.parent.mkdir(parents=True, exist_ok=True)
            with args.report_json.open("x", encoding="utf-8") as handle:
                handle.write(encoded + "\n")
        if complete_runs != len(results):
            raise SystemExit(2)
    except JackdawUnavailable as exc:
        raise SystemExit(f"Jackdaw candidate unavailable: {exc}") from exc
    finally:
        if policy is not None:
            policy.close()
        if backend is not None:
            backend.close()


def terminal_projection(
    observation: PublicObservation | None,
    *,
    terminal_blind: PublicBlind | None = None,
) -> dict[str, object] | None:
    """Return stable public diagnostics for a run's final observation."""

    if observation is None:
        return None
    current = next((blind for blind in observation.blinds if blind.status == "CURRENT"), None)
    terminal_blind = terminal_blind or current
    boss = next((blind for blind in observation.blinds if blind.kind == "BOSS"), None)
    target = terminal_blind.score if terminal_blind is not None else None
    return {
        "schema_version": TERMINAL_PROJECTION_SCHEMA_VERSION,
        "phase": observation.phase.value,
        "won": observation.won,
        "antes_cleared": observation.antes_cleared,
        "ante": observation.ante,
        "round": observation.round_no,
        "money": observation.money,
        "chips": observation.round.chips,
        "target": target,
        "chip_margin": observation.round.chips - target if target is not None else None,
        "hands_left": observation.round.hands_left,
        "discards_left": observation.round.discards_left,
        "hands_played": observation.round.hands_played,
        "discards_used": observation.round.discards_used,
        "terminal_blind": _blind_projection(terminal_blind),
        "visible_boss": _blind_projection(boss),
    }


def summarize_results(
    results: list[dict[str, object]],
    *,
    elapsed: float,
    terminal_reasons: Counter[str],
) -> dict[str, object]:
    """Summarize outcomes with completed antes as the headline metric."""

    survived = sum(bool(result["survived_to_ante_6"]) for result in results)
    antes_cleared = [int(result["antes_cleared"]) for result in results]
    return {
        "runs": len(results),
        "complete": sum(bool(result["complete"]) for result in results),
        "mean_antes_cleared": sum(antes_cleared) / len(results),
        "antes_cleared_deciles": _deciles(antes_cleared),
        "wins": sum(bool(result["won"]) for result in results),
        "win_rate": sum(bool(result["won"]) for result in results) / len(results),
        "survived_to_ante_6": survived,
        "survival_to_ante_6_rate": survived / len(results),
        "average_ante": sum(int(result["ante"]) for result in results) / len(results),
        "average_round": sum(int(result["round"]) for result in results) / len(results),
        "elapsed_seconds": elapsed,
        "decisions_per_second": sum(int(result["decisions"]) for result in results) / elapsed,
        "terminal_reasons": dict(sorted(terminal_reasons.items())),
    }


def _deciles(values: list[int]) -> dict[str, int]:
    """Return deterministic lower empirical deciles, including both endpoints."""

    ordered = sorted(values)
    return {
        f"p{percentile}": ordered[((len(ordered) - 1) * percentile) // 100]
        for percentile in range(0, 101, 10)
    }


def _blind_projection(blind: PublicBlind | None) -> dict[str, object] | None:
    if blind is None:
        return None
    return {
        "kind": blind.kind,
        "status": blind.status,
        "name": blind.name,
        "effect": blind.effect,
        "score": blind.score,
        "tag_name": blind.tag_name,
        "tag_effect": blind.tag_effect,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate public-only baselines in pinned Jackdaw")
    parser.add_argument("--policy", choices=PUBLIC_BASELINE_NAMES, required=True)
    parser.add_argument("--policy-seed", default="baseline-v1")
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="WHITE")
    parser.add_argument("--max-decisions", type=int, default=800)
    parser.add_argument("--ante-cap", type=int, default=20)
    parser.add_argument("--policy-timeout", type=float, default=5.0)
    parser.add_argument("--tuning-json", default=StrategyTuning().canonical_json())
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--fitness-only", action="store_true")
    return parser


if __name__ == "__main__":
    main()
