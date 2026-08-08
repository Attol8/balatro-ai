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
from balatro_ai_v2.jackdaw import JackdawBackend, JackdawUnavailable, verify_jackdaw_runtime


def main() -> None:
    args = build_parser().parse_args()
    if args.seeds < 1 or args.max_decisions < 1:
        raise SystemExit("--seeds and --max-decisions must be positive")
    root = Path(__file__).resolve().parents[1]
    policy, policy_name = build_public_baseline(args.policy, args.policy_seed)
    backend: JackdawBackend | None = None
    started = time.perf_counter()
    try:
        candidate_runtime = verify_jackdaw_runtime()
        backend = JackdawBackend()
        results = []
        for seed_number in range(args.seed_start, args.seed_start + args.seeds):
            result = AuthorityRunner(backend, policy, max_decisions=args.max_decisions).run(
                RunSpec(args.deck, args.stake, str(seed_number))
            )
            results.append(
                {
                    "seed": seed_number,
                    "complete": result.complete,
                    "won": result.won,
                    "ante": result.ante,
                    "round": result.round_no,
                    "decisions": result.decisions,
                    "terminal_reason": result.terminal_reason,
                }
            )
        elapsed = time.perf_counter() - started
        terminal_reasons = Counter(str(result["terminal_reason"]) for result in results)
        complete_runs = sum(bool(result["complete"]) for result in results)
        manifest = build_manifest(
            repository_root=root,
            command=tuple(sys.argv),
            policy_name=policy_name,
            backend=backend.metadata,
            run=RunSpec(args.deck, args.stake, f"{args.seed_start}:{args.seeds}"),
            max_decisions=args.max_decisions,
            max_settle_polls=0,
            launch_fast=False,
            launch_headless=False,
            profile_mode="all_unlocked",
            inference_budget="public_actions<=256;tactical_candidates<=2048;draw_branches<=512",
        )
        payload = {
            "candidate_only": True,
            "candidate_runtime": candidate_runtime,
            "manifest": asdict(manifest),
            "results": results,
            "summary": {
                "runs": len(results),
                "complete": complete_runs,
                "wins": sum(result["won"] for result in results),
                "average_ante": sum(result["ante"] for result in results) / len(results),
                "average_round": sum(result["round"] for result in results) / len(results),
                "elapsed_seconds": elapsed,
                "decisions_per_second": sum(result["decisions"] for result in results) / elapsed,
                "terminal_reasons": dict(sorted(terminal_reasons.items())),
            },
        }
        encoded = json.dumps(payload, sort_keys=True)
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
        if backend is not None:
            backend.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate public-only baselines in pinned Jackdaw")
    parser.add_argument("--policy", choices=PUBLIC_BASELINE_NAMES, required=True)
    parser.add_argument("--policy-seed", default="baseline-v1")
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="WHITE")
    parser.add_argument("--max-decisions", type=int, default=800)
    parser.add_argument("--report-json", type=Path)
    return parser


if __name__ == "__main__":
    main()
