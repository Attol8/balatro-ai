"""Run deterministic public-action traces through real Balatro and Jackdaw."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.backend import RunSpec
from balatro_ai_v2.baselines import DeterministicCoveragePolicy
from balatro_ai_v2.balatrobot.backend import BalatroBotBackend
from balatro_ai_v2.balatrobot.client import BalatroBotClient, BalatroBotError
from balatro_ai_v2.balatrobot.process import build_launch_command, stop_balatrobot_server, wait_for_balatrobot
from balatro_ai_v2.balatrobot.runner import AuthorityRunner
from balatro_ai_v2.balatrobot.tracing import AuthorityTraceWriter, build_manifest
from balatro_ai_v2.differential import replay_authority_trace
from balatro_ai_v2.jackdaw import JACKDAW_REVISION, JackdawBackend, JackdawUnavailable


def main() -> None:
    args = build_parser().parse_args()
    if args.seeds < 1 or args.max_shop_actions < 0:
        raise SystemExit("--seeds must be positive and --max-shop-actions must be non-negative")
    root = Path(__file__).resolve().parents[1]
    client = BalatroBotClient(host=args.host, port=args.port, timeout=args.timeout)
    process: subprocess.Popen[bytes] | None = None
    candidate: JackdawBackend | None = None
    try:
        candidate = JackdawBackend()
        args.output_dir.mkdir(parents=True, exist_ok=False)
        if args.launch_server:
            command = build_launch_command(
                args.launch_command,
                host=args.host,
                port=args.port,
                fast_server=args.fast_server,
                headless_server=args.headless_server,
            )
            process = subprocess.Popen(command)
            wait_for_balatrobot(
                client,
                timeout=args.launch_timeout,
                poll_delay=args.launch_poll_delay,
                process=process,
            )
            if args.post_launch_delay:
                time.sleep(args.post_launch_delay)
        else:
            client.health()

        authority = BalatroBotBackend(
            client,
            max_settle_polls=args.max_settle_polls,
            settle_poll_delay=args.settle_poll_delay,
            backend_version=args.balatrobot_version,
            game_version=args.game_version,
            runtime_version=args.runtime_version,
        )
        policy = DeterministicCoveragePolicy(
            policy_seed=args.policy_seed,
            max_shop_actions=args.max_shop_actions,
            pack_strategy=args.pack_strategy,
        )
        for seed_number in range(args.seed_start, args.seed_start + args.seeds):
            seed = str(seed_number)
            spec = RunSpec(args.deck, args.stake, seed)
            trace_path = args.output_dir / f"{args.deck.lower()}-{args.stake.lower()}-seed{seed}.jsonl"
            manifest = build_manifest(
                repository_root=root,
                command=tuple(sys.argv),
                policy_name=f"DeterministicCoveragePolicy:{args.policy_seed}",
                backend=authority.metadata,
                run=spec,
                max_decisions=args.max_decisions,
                max_settle_polls=args.max_settle_polls,
                launch_fast=args.fast_server,
                launch_headless=args.headless_server,
                inference_budget=(
                    f"tactical_candidates<=2048;public_actions<=256;shop_actions<={args.max_shop_actions}"
                ),
                mods=tuple(args.mod),
            )
            result = AuthorityRunner(
                backend=authority,
                policy=policy,
                max_decisions=args.max_decisions,
                trace=AuthorityTraceWriter(trace_path, manifest),
            ).run(spec)
            if not result.complete:
                print(
                    json.dumps(
                        {
                            "authority_complete": False,
                            "seed": seed,
                            "terminal_reason": result.terminal_reason,
                            "trace": str(trace_path),
                        },
                        sort_keys=True,
                    )
                )
                raise SystemExit(2)

            report = replay_authority_trace(trace_path, candidate)
            payload = {
                "ante": result.ante,
                "authority_complete": True,
                "candidate_revision": JACKDAW_REVISION,
                "decisions": result.decisions,
                "differential": asdict(report),
                "seed": seed,
                "trace": str(trace_path),
                "won": result.won,
            }
            print(json.dumps(payload, sort_keys=True))
            if not report.observed_lockstep:
                raise SystemExit(1)
    except JackdawUnavailable as exc:
        raise SystemExit(f"Jackdaw candidate unavailable: {exc}") from exc
    except BalatroBotError as exc:
        raise SystemExit(f"BalatroBot authority failed: {exc}") from exc
    finally:
        if candidate is not None:
            candidate.close()
        if process is not None:
            stop_balatrobot_server(process)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stop-on-first-mismatch campaign against real Balatro and pinned Jackdaw"
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=4)
    parser.add_argument("--policy-seed", default="coverage-v1")
    parser.add_argument("--max-shop-actions", type=int, default=3)
    parser.add_argument("--pack-strategy", choices=("mixed", "skip", "pick"), default="mixed")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=12346)
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="WHITE")
    parser.add_argument("--max-decisions", type=int, default=800)
    parser.add_argument("--max-settle-polls", type=int, default=40)
    parser.add_argument("--settle-poll-delay", type=float, default=0.02)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--balatrobot-version", required=True)
    parser.add_argument("--game-version", required=True)
    parser.add_argument("--runtime-version", required=True)
    parser.add_argument("--mod", action="append", default=[])
    parser.add_argument("--launch-server", action="store_true")
    parser.add_argument(
        "--launch-command",
        default=os.environ.get("BALATROBOT_LAUNCH_COMMAND", "uvx balatrobot serve"),
    )
    parser.add_argument("--fast-server", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--headless-server", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--launch-timeout", type=float, default=90.0)
    parser.add_argument("--launch-poll-delay", type=float, default=0.2)
    parser.add_argument("--post-launch-delay", type=float, default=1.0)
    return parser


if __name__ == "__main__":
    main()
