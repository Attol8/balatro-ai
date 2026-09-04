#!/usr/bin/env python3
"""Evaluate determinized-rollout search in pinned Jackdaw.

Emits the same report schema as ``evaluate_candidate_baselines.py`` so that
``compare_candidate_reports.py`` works unchanged.  Seeds are sharded across
``--workers`` processes, one Jackdaw and one search policy per worker.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from balatro_ai_v2.backend import RunSpec
from balatro_ai_v2.balatrobot.runner import AuthorityRunner
from balatro_ai_v2.balatrobot.tracing import build_manifest
from balatro_ai_v2.baselines import build_public_baseline
from balatro_ai_v2.determinized_search import SEARCH_VERSION, DeterminizedSearchPolicy, RolloutBudget
from balatro_ai_v2.jackdaw import JackdawBackend, JackdawUnavailable, verify_jackdaw_runtime
from balatro_ai_v2.strategy_tuning import StrategyTuning
from evaluate_candidate_baselines import summarize_results, terminal_projection


_WORKER: dict[str, object] = {}


def _init_worker(args_dict: dict[str, object]) -> None:
    tuning = StrategyTuning.from_json(str(args_dict["tuning_json"]))
    continuation, _ = build_public_baseline(str(args_dict["continuation"]), str(args_dict["policy_seed"]), tuning)
    backend = JackdawBackend()
    policy = DeterminizedSearchPolicy(
        backend=backend,
        continuation=continuation,
        nonce=str(args_dict["nonce"]),
        budget=RolloutBudget(
            samples=int(args_dict["samples"]),
            horizon_antes=int(args_dict["horizon_antes"]),
            max_steps=int(args_dict["max_steps"]),
            override_z=float(args_dict["override_z"]),
        ),
    )
    _WORKER.update(args=args_dict, backend=backend, policy=policy)


def _run_seed(seed_number: int) -> dict[str, object]:
    args_dict = _WORKER["args"]
    backend = _WORKER["backend"]
    policy = _WORKER["policy"]
    assert isinstance(args_dict, dict) and isinstance(backend, JackdawBackend)
    assert isinstance(policy, DeterminizedSearchPolicy)
    policy.reset_run()
    started = time.perf_counter()
    result = AuthorityRunner(
        backend,
        policy,
        max_decisions=int(args_dict["max_decisions"]),
        max_antes_cleared=int(args_dict["ante_cap"]),
    ).run(RunSpec(str(args_dict["deck"]), str(args_dict["stake"]), str(seed_number)))
    print(
        f"seed {seed_number}: antes_cleared={result.antes_cleared} won={result.won} "
        f"decisions={result.decisions} searched={policy.counters.searched} "
        f"changed={policy.counters.changed} seconds={time.perf_counter() - started:.0f}",
        file=sys.stderr,
        flush=True,
    )
    return {
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
        "terminal": terminal_projection(result.final_observation, terminal_blind=result.terminal_blind),
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
        "policy_diagnostics": {},
        "search": {
            **policy.counters.as_dict(),
            "run_seconds": time.perf_counter() - started,
        },
        "search_decisions": [decision.as_dict() for decision in policy.decisions]
        if bool(args_dict["record_decisions"])
        else [],
        "capacity_decisions": [],
    }


def main() -> None:
    args = build_parser().parse_args()
    if args.seeds < 1 or args.max_decisions < 1 or args.ante_cap < 1 or args.workers < 1:
        raise SystemExit("--seeds, --max-decisions, --ante-cap, and --workers must be positive")
    root = Path(__file__).resolve().parents[1]
    try:
        tuning = StrategyTuning.from_json(args.tuning_json)
    except ValueError as exc:
        raise SystemExit(f"invalid --tuning-json: {exc}") from exc
    _, continuation_name = build_public_baseline(args.continuation, args.policy_seed, tuning)
    budget = RolloutBudget(
        samples=args.samples,
        horizon_antes=args.horizon_antes,
        max_steps=args.max_steps,
        override_z=args.override_z,
    )
    policy_name = f"DeterminizedSearchPolicy[{SEARCH_VERSION};{continuation_name};{budget.canonical()}]:parent-v1"
    worker_args = {
        "tuning_json": tuning.canonical_json(),
        "continuation": args.continuation,
        "policy_seed": args.policy_seed,
        "nonce": args.nonce,
        "samples": args.samples,
        "horizon_antes": args.horizon_antes,
        "max_steps": args.max_steps,
        "override_z": args.override_z,
        "max_decisions": args.max_decisions,
        "ante_cap": args.ante_cap,
        "deck": args.deck,
        "stake": args.stake,
        "record_decisions": args.record_decisions,
    }
    seeds = list(range(args.seed_start, args.seed_start + args.seeds))
    started = time.perf_counter()
    try:
        candidate_runtime = verify_jackdaw_runtime()
        metadata_backend = JackdawBackend()
        if args.workers == 1:
            _init_worker(worker_args)
            results = [_run_seed(seed) for seed in seeds]
        else:
            with ProcessPoolExecutor(
                max_workers=args.workers, initializer=_init_worker, initargs=(worker_args,)
            ) as executor:
                results = list(executor.map(_run_seed, seeds, chunksize=1))
        results.sort(key=lambda row: int(row["seed"]))
        elapsed = time.perf_counter() - started
        terminal_reasons = Counter(str(row["terminal_reason"]) for row in results)
        summary = summarize_results(results, elapsed=elapsed, terminal_reasons=terminal_reasons)
        summary["search"] = _search_summary(results)
        manifest = build_manifest(
            repository_root=root,
            command=tuple(sys.argv),
            policy_name=policy_name,
            backend=metadata_backend.metadata,
            run=RunSpec(args.deck, args.stake, f"{args.seed_start}:{args.seeds}"),
            max_decisions=args.max_decisions,
            max_antes_cleared=args.ante_cap,
            max_settle_polls=0,
            launch_fast=False,
            launch_headless=False,
            profile_mode="all_unlocked",
            inference_budget=(
                f"determinized_rollouts;{budget.canonical()};roots=all_legal_non_reorder;"
                f"workers={args.workers};ante_cap={args.ante_cap}"
            ),
        )
        payload = {
            "candidate_only": True,
            "candidate_runtime": candidate_runtime,
            "manifest": asdict(manifest),
            "search_protocol": {
                "version": SEARCH_VERSION,
                "continuation": continuation_name,
                "budget": json.loads(json.dumps(asdict(budget))),
                "nonce": args.nonce,
                "phases": ["BLIND_SELECT", "PACK", "SHOP"],
                "value": "rounds_cleared_plus_failed_blind_fraction;alive_at_horizon=+1",
                "selection": "paired_delta_vs_continuation;override_when_mean_minus_z_se_positive",
            },
            "strategy_tuning": json.loads(tuning.canonical_json()),
            "results": results,
            "summary": summary,
        }
        encoded = json.dumps(payload, sort_keys=True)
        print(json.dumps({"summary": summary}, sort_keys=True))
        if args.report_json is not None:
            args.report_json.parent.mkdir(parents=True, exist_ok=True)
            with args.report_json.open("x", encoding="utf-8") as handle:
                handle.write(encoded + "\n")
        if sum(bool(row["complete"]) for row in results) != len(results):
            raise SystemExit(2)
    except JackdawUnavailable as exc:
        raise SystemExit(f"Jackdaw candidate unavailable: {exc}") from exc


def _search_summary(results: list[dict[str, object]]) -> dict[str, float]:
    totals: Counter[str] = Counter()
    for row in results:
        search = row["search"]
        assert isinstance(search, dict)
        for key in ("strategic_decisions", "searched", "changed", "unavailable", "rollout_steps", "rejected_rollouts", "seconds", "run_seconds"):
            totals[key] += float(search[key])
    runs = max(1, len(results))
    return {
        **{key: totals[key] for key in totals},
        "mean_run_seconds": totals["run_seconds"] / runs,
        "steps_per_second": (totals["rollout_steps"] / totals["seconds"]) if totals["seconds"] > 0 else 0.0,
        "changed_fraction": (totals["changed"] / totals["searched"]) if totals["searched"] > 0 else 0.0,
        "unavailable_fraction": (
            totals["unavailable"] / totals["strategic_decisions"] if totals["strategic_decisions"] > 0 else 0.0
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--continuation", default="strategic")
    parser.add_argument("--policy-seed", default="baseline-v1")
    parser.add_argument("--nonce", default="search-v1")
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="WHITE")
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--horizon-antes", type=int, default=2)
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--override-z", type=float, default=1.0)
    parser.add_argument("--max-decisions", type=int, default=800)
    parser.add_argument("--ante-cap", type=int, default=20)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--tuning-json", default=StrategyTuning().canonical_json())
    parser.add_argument("--record-decisions", action="store_true")
    parser.add_argument("--report-json", type=Path)
    return parser


if __name__ == "__main__":
    main()
