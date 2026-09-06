"""Run a public-information smoke policy through the real Balatro authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.backend import RunSpec
from balatro_ai_v2.candidate_trace_replay import (
    CandidateTraceReplayError,
    CandidateTraceReplayPolicy,
)
from balatro_ai_v2.baselines import PUBLIC_BASELINE_NAMES, build_public_baseline
from balatro_ai_v2.balatrobot.backend import BalatroBotBackend
from balatro_ai_v2.balatrobot.client import BalatroBotClient, BalatroBotError
from balatro_ai_v2.balatrobot.process import (
    build_launch_command,
    build_launch_environment,
    require_active_mods,
    require_profile_mode,
    stop_balatrobot_server,
    wait_for_balatrobot,
)
from balatro_ai_v2.balatrobot.runner import AuthorityRunner, NoBuySmokePolicy
from balatro_ai_v2.balatrobot.tracing import AuthorityTraceWriter, build_manifest
from balatro_ai_v2.policy_process import PolicyProcess
from balatro_ai_v2.policy_wire import POLICY_ACTION_CONTRACT


def main() -> None:
    args = build_parser().parse_args()
    root = Path(__file__).resolve().parents[1]
    replay_policy: CandidateTraceReplayPolicy | None = None
    if args.replay_trace is not None:
        if args.policy != "smoke":
            raise SystemExit("--replay-trace cannot be combined with a baseline policy")
        if args.trace_jsonl is None:
            raise SystemExit("--replay-trace requires --trace-jsonl")
        if args.seed is None:
            raise SystemExit("--replay-trace requires the launcher-only --seed")
        if not args.launch_server or args.fast_server:
            raise SystemExit(
                "candidate replay requires a fresh --launch-server with --no-fast-server"
            )
        try:
            replay_policy = CandidateTraceReplayPolicy.from_path(args.replay_trace)
        except CandidateTraceReplayError as exc:
            raise SystemExit(f"invalid candidate replay trace: {exc}") from exc
        if args.deck != replay_policy.deck or args.stake != replay_policy.stake:
            raise SystemExit("candidate replay deck/stake disagree with the source trace")
    client = BalatroBotClient(host=args.host, port=args.port, timeout=args.timeout)
    process: subprocess.Popen[bytes] | None = None
    policy_process: PolicyProcess | None = None
    staged_trace: Path | None = None
    try:
        if args.launch_server:
            command = build_launch_command(
                args.launch_command,
                host=args.host,
                port=args.port,
                fast_server=args.fast_server,
                headless_server=args.headless_server,
            )
            process = subprocess.Popen(command, env=build_launch_environment(profile_mode=args.profile_mode))
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

        health = client.health()
        require_profile_mode(health, expected=args.profile_mode)
        if args.trace_jsonl is not None:
            require_active_mods(health, identities=tuple(args.mod))
        backend_version = _version(
            args.balatrobot_version,
            health.get("version"),
            name="BalatroBot",
            required=args.trace_jsonl is not None,
        )
        game_version = _version(
            args.game_version,
            health.get("game_version"),
            name="Balatro game",
            required=args.trace_jsonl is not None,
        )
        runtime_version = _version(
            args.runtime_version,
            health.get("runtime_version"),
            name="LÖVE/LuaJIT runtime",
            required=args.trace_jsonl is not None,
        )
        backend = BalatroBotBackend(
            client,
            max_settle_polls=args.max_settle_polls,
            settle_poll_delay=args.settle_poll_delay,
            backend_version=backend_version or "unknown",
            game_version=game_version,
            runtime_version=runtime_version,
        )
        if replay_policy is not None:
            policy = replay_policy
            source_policy_digest = hashlib.sha256(
                replay_policy.source_policy_name.encode("utf-8")
            ).hexdigest()
            policy_name = (
                "CandidateTraceReplayPolicy["
                f"candidate_sha256={replay_policy.source_digest};"
                f"source_policy_sha256={source_policy_digest}]"
            )
            inference_budget = (
                f"policy_action_contract={POLICY_ACTION_CONTRACT};"
                f"candidate_trace_sha256={replay_policy.source_digest};"
                f"actions={len(replay_policy.steps)};exact_public_replay"
            )
        elif args.policy == "smoke":
            policy = NoBuySmokePolicy()
            policy_name = "NoBuySmokePolicy"
            inference_budget = "none"
        elif args.policy == "public-search":
            command = (
                sys.executable,
                "-m",
                "balatro_ai_v2.public_search_child",
                "--continuation",
                "strategic",
                "--policy-nonce",
                args.policy_seed,
                "--samples",
                str(args.search_samples),
                "--horizon-antes",
                str(args.search_horizon_antes),
                "--max-steps",
                str(args.search_max_steps),
                "--override-z",
                str(args.search_override_z),
                *(
                    ("--strategy-options",)
                    if args.search_strategy_options
                    else ()
                ),
                *(("--decision-log", str(args.search_decision_log)) if args.search_decision_log else ()),
            )
            policy_process = PolicyProcess(
                "public-search",
                command=command,
                timeout_seconds=args.policy_timeout,
            )
            policy = policy_process
            policy_name = "PublicRootDeterminizedSearchPolicy:process-v1"
            inference_budget = (
                f"policy_action_contract={POLICY_ACTION_CONTRACT};"
                "root_source=public_observation_history_v1;"
                f"samples={args.search_samples};"
                f"horizon_antes={args.search_horizon_antes};"
                f"max_steps={args.search_max_steps};"
                f"override_z={args.search_override_z};"
                f"strategy_options={args.search_strategy_options};"
                f"policy_timeout_seconds={args.policy_timeout}"
            )
        else:
            _, implementation_name = build_public_baseline(args.policy, args.policy_seed)
            policy_process = PolicyProcess(
                args.policy,
                policy_seed=args.policy_seed,
                timeout_seconds=args.policy_timeout,
            )
            policy = policy_process
            policy_name = f"{implementation_name}:process-v1"
            inference_budget = (
                f"policy_action_contract={POLICY_ACTION_CONTRACT};"
                f"policy_timeout_seconds={args.policy_timeout}"
            )
        spec = (
            RunSpec(replay_policy.deck, replay_policy.stake, args.seed)
            if replay_policy is not None
            else RunSpec(deck=args.deck, stake=args.stake, seed=args.seed)
        )
        max_decisions = (
            replay_policy.max_decisions
            if replay_policy is not None
            else args.max_decisions
        )
        max_antes_cleared = (
            replay_policy.max_antes_cleared
            if replay_policy is not None
            else 20
        )
        trace = None
        if args.trace_jsonl is not None:
            manifest = build_manifest(
                repository_root=root,
                command=tuple(sys.argv),
                policy_name=policy_name,
                backend=backend.metadata,
                run=spec,
                max_decisions=max_decisions,
                max_settle_polls=args.max_settle_polls,
                launch_fast=args.fast_server,
                launch_headless=args.headless_server,
                profile_mode=args.profile_mode,
                inference_budget=inference_budget,
                mods=tuple(args.mod),
            )
            trace_path = args.trace_jsonl
            if replay_policy is not None:
                staged_trace = trace_path.with_name(
                    f".{trace_path.name}.{secrets.token_hex(8)}.staged"
                )
                trace_path = staged_trace
            trace = AuthorityTraceWriter(trace_path, manifest)
        result = AuthorityRunner(
            backend=backend,
            policy=policy,
            max_decisions=max_decisions,
            max_antes_cleared=max_antes_cleared,
            trace=trace,
        ).run(spec)
        if replay_policy is not None:
            try:
                replay_policy.assert_complete(result.final_observation)
            except CandidateTraceReplayError as exc:
                raise CandidateTraceReplayError(
                    f"{exc}; terminal_reason={result.terminal_reason}; "
                    f"terminal_error={result.terminal_error}"
                ) from exc
            assert staged_trace is not None and args.trace_jsonl is not None
            if args.trace_jsonl.exists():
                raise CandidateTraceReplayError(
                    f"refusing to overwrite existing output: {args.trace_jsonl}"
                )
            os.link(staged_trace, args.trace_jsonl)
            staged_trace.unlink()
            staged_trace = None
        print(
            json.dumps(
                {
                    "complete": result.complete,
                    "won": result.won,
                    "ante": result.ante,
                    "round": result.round_no,
                    "decisions": result.decisions,
                    "terminal_reason": result.terminal_reason,
                    "terminal_error": result.terminal_error,
                    "policy_diagnostics": (
                        asdict(policy_process.run_diagnostic_counters)
                        if policy_process is not None
                        else None
                    ),
                },
                sort_keys=True,
            )
        )
        if not result.complete:
            raise SystemExit(2)
    except (BalatroBotError, CandidateTraceReplayError) as exc:
        raise SystemExit(f"BalatroBot authority failed: {exc}") from exc
    finally:
        if policy_process is not None:
            policy_process.close()
        if process is not None:
            stop_balatrobot_server(process)
        if staged_trace is not None:
            staged_trace.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a non-solving public-information smoke policy through BalatroBot"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=12346)
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="WHITE")
    parser.add_argument("--seed")
    parser.add_argument(
        "--policy",
        choices=("smoke", "public-search", *PUBLIC_BASELINE_NAMES),
        default="smoke",
    )
    parser.add_argument("--policy-seed", default="authority-v1")
    parser.add_argument("--policy-timeout", type=float, default=5.0)
    parser.add_argument("--search-samples", type=int, default=6)
    parser.add_argument("--search-horizon-antes", type=int, default=1)
    parser.add_argument("--search-max-steps", type=int, default=200)
    parser.add_argument("--search-override-z", type=float, default=1.0)
    parser.add_argument(
        "--search-strategy-options",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--search-decision-log", type=Path)
    parser.add_argument("--max-decisions", type=int, default=800)
    parser.add_argument("--max-settle-polls", type=int, default=40)
    parser.add_argument("--settle-poll-delay", type=float, default=0.02)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--trace-jsonl", type=Path)
    parser.add_argument(
        "--replay-trace",
        type=Path,
        help=(
            "Replay one complete non-authoritative search trace against a fresh "
            "non-fast Balatro authority, failing on any canonical public divergence."
        ),
    )
    parser.add_argument("--balatrobot-version", default=os.environ.get("BALATROBOT_VERSION"))
    parser.add_argument("--game-version", default=os.environ.get("BALATRO_GAME_VERSION"))
    parser.add_argument("--runtime-version", default=os.environ.get("BALATRO_RUNTIME_VERSION"))
    parser.add_argument(
        "--mod",
        action="append",
        default=[],
        help="Loaded mod identity as name@version-or-digest; repeat for every mod.",
    )
    parser.add_argument("--launch-server", action="store_true")
    parser.add_argument(
        "--launch-command",
        default=os.environ.get("BALATROBOT_LAUNCH_COMMAND", "uvx balatrobot serve"),
    )
    parser.add_argument("--fast-server", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--headless-server", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--profile-mode", choices=("all_unlocked", "career"), default="all_unlocked")
    parser.add_argument("--launch-timeout", type=float, default=45.0)
    parser.add_argument("--launch-poll-delay", type=float, default=0.2)
    parser.add_argument("--post-launch-delay", type=float, default=1.0)
    return parser


def _version(explicit: object, discovered: object, *, name: str, required: bool) -> str | None:
    value = explicit if isinstance(explicit, str) and explicit else discovered
    if isinstance(value, str) and value:
        return value
    if required:
        raise SystemExit(f"exact {name} version is required for evidence traces")
    return None


if __name__ == "__main__":
    main()
