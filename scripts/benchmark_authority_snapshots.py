"""Benchmark exact branch replay through Balatro's game-native save/load path."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.actions import PublicAction, action_to_data, iter_legal_actions
from balatro_ai_v2.backend import AuthorityObservation, RunSpec
from balatro_ai_v2.balatrobot.adapter import to_public_observation
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
from balatro_ai_v2.balatrobot.runner import PublicHistoryStep
from balatro_ai_v2.balatrobot.tracing import build_manifest
from balatro_ai_v2.baselines import DeterministicCoveragePolicy
from balatro_ai_v2.canonical import BalatroBotCanonicalizer
from balatro_ai_v2.public_state import Phase, PublicObservation


def main() -> None:
    args = build_parser().parse_args()
    if args.depth < 1 or args.repeats < 1:
        raise SystemExit("--depth and --repeats must be positive")
    root = Path(__file__).resolve().parents[1]
    client = BalatroBotClient(host=args.host, port=args.port, timeout=args.timeout)
    process: subprocess.Popen[bytes] | None = None
    try:
        if args.launch_server:
            process = subprocess.Popen(
                build_launch_command(
                    args.launch_command,
                    host=args.host,
                    port=args.port,
                    fast_server=args.fast_server,
                    headless_server=args.headless_server,
                ),
                env=build_launch_environment(profile_mode=args.profile_mode),
            )
            wait_for_balatrobot(
                client,
                timeout=args.launch_timeout,
                poll_delay=args.launch_poll_delay,
                process=process,
            )
            if args.post_launch_delay:
                time.sleep(args.post_launch_delay)

        health = client.health()
        require_profile_mode(health, expected=args.profile_mode)
        require_active_mods(health, identities=tuple(args.mod))
        backend = BalatroBotBackend(
            client,
            max_settle_polls=args.max_settle_polls,
            settle_poll_delay=args.settle_poll_delay,
            backend_version=args.balatrobot_version,
            game_version=args.game_version,
            runtime_version=args.runtime_version,
        )
        spec = RunSpec(args.deck, args.stake, args.seed)
        manifest = build_manifest(
            repository_root=root,
            command=tuple(sys.argv),
            policy_name=f"DeterministicCoveragePolicy:{args.policy_seed}:snapshot-benchmark",
            backend=backend.metadata,
            run=spec,
            max_decisions=args.depth,
            max_settle_polls=args.max_settle_polls,
            launch_fast=args.fast_server,
            launch_headless=args.headless_server,
            profile_mode=args.profile_mode,
            inference_budget=f"branch_depth={args.depth};repeats={args.repeats}",
            mods=tuple(args.mod),
        )
        if args.protocol == "memory":
            report = benchmark_memory_snapshots(
                backend,
                spec,
                depth=args.depth,
                repeats=args.repeats,
                policy_seed=args.policy_seed,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="balatro-snapshot-") as temp_dir:
                report = benchmark_file_snapshots(
                    backend,
                    spec,
                    Path(temp_dir) / "parent.jkr",
                    depth=args.depth,
                    repeats=args.repeats,
                    policy_seed=args.policy_seed,
                )
        payload = {"manifest": asdict(manifest), **report}
        encoded = json.dumps(payload, sort_keys=True)
        print(encoded)
        if args.report_json is not None:
            args.report_json.parent.mkdir(parents=True, exist_ok=True)
            with args.report_json.open("x", encoding="utf-8") as handle:
                handle.write(encoded + "\n")
        if not report["exact_observed_replay"]:
            raise SystemExit(1)
    except BalatroBotError as exc:
        raise SystemExit(f"BalatroBot authority failed: {exc}") from exc
    finally:
        if process is not None:
            stop_balatrobot_server(process)


def benchmark_file_snapshots(
    backend: BalatroBotBackend,
    spec: RunSpec,
    path: Path,
    *,
    depth: int,
    repeats: int,
    policy_seed: str,
) -> dict[str, object]:
    before_save = backend.reset(spec)
    started = time.perf_counter()
    backend.save_file_snapshot(path)
    capture_ms = _milliseconds_since(started)
    after_save = backend.observe()
    snapshot = path.read_bytes()
    return _benchmark_restores(
        backend,
        before_save,
        after_save,
        lambda: backend.load_file_snapshot(path),
        protocol="game_native_file_save_load",
        snapshot={
            "bytes": len(snapshot),
            "sha256": hashlib.sha256(snapshot).hexdigest(),
            "capture_ms": capture_ms,
        },
        depth=depth,
        repeats=repeats,
        policy_seed=policy_seed,
    )


def benchmark_memory_snapshots(
    backend: BalatroBotBackend,
    spec: RunSpec,
    *,
    depth: int,
    repeats: int,
    policy_seed: str,
) -> dict[str, object]:
    before_save = backend.reset(spec)
    started = time.perf_counter()
    snapshot_id, size = backend.create_memory_checkpoint()
    capture_ms = _milliseconds_since(started)
    after_save = backend.observe()
    try:
        return _benchmark_restores(
            backend,
            before_save,
            after_save,
            lambda: backend.load_memory_checkpoint(snapshot_id),
            protocol="game_native_memory_checkpoint",
            snapshot={"bytes": size, "capture_ms": capture_ms},
            depth=depth,
            repeats=repeats,
            policy_seed=policy_seed,
        )
    finally:
        backend.delete_memory_checkpoint(snapshot_id)


def _benchmark_restores(
    backend: BalatroBotBackend,
    before_save: AuthorityObservation,
    after_save: AuthorityObservation,
    restore: Callable[[], AuthorityObservation],
    *,
    protocol: str,
    snapshot: dict[str, object],
    depth: int,
    repeats: int,
    policy_seed: str,
) -> dict[str, object]:
    before_digest = _root_digest(before_save)
    after_digest = _root_digest(after_save)
    policy = DeterministicCoveragePolicy(policy_seed=policy_seed)
    actions, expected_digests = _record_branch(backend, after_save, policy, depth)
    mismatch: dict[str, object] | None = None
    restore_ms: list[float] = []
    replayed = 0

    if before_digest != after_digest:
        mismatch = {"kind": "save_mutated_parent", "before": before_digest, "after": after_digest}

    for repeat in range(repeats):
        started = time.perf_counter()
        restored = restore()
        restore_ms.append(_milliseconds_since(started))
        canonicalizer = BalatroBotCanonicalizer()
        restored_digest = _canonicalize(restored, canonicalizer)
        if mismatch is None and restored_digest != after_digest:
            mismatch = {
                "kind": "parent_restore",
                "repeat": repeat,
                "expected": after_digest,
                "actual": restored_digest,
            }
        if mismatch is not None:
            break
        for index, action in enumerate(actions):
            result = backend.step(action)
            if result.status != "accepted" or result.after is None:
                mismatch = {
                    "kind": "action_status",
                    "repeat": repeat,
                    "step": index,
                    "status": result.status,
                    "error": result.error,
                }
                break
            actual = _canonicalize(result.after, canonicalizer)
            replayed += 1
            if actual != expected_digests[index]:
                mismatch = {
                    "kind": "successor",
                    "repeat": repeat,
                    "step": index,
                    "action": action_to_data(action),
                    "expected": expected_digests[index],
                    "actual": actual,
                }
                break
        if mismatch is not None:
            break

    snapshot.update(
        {
            "restore_ms": restore_ms,
            "restore_p50_ms": statistics.median(restore_ms),
            "restore_max_ms": max(restore_ms),
        }
    )
    return {
        "protocol": protocol,
        "exact_observed_replay": mismatch is None,
        "mismatch": mismatch,
        "snapshot": snapshot,
        "parent_canonical_digest": after_digest,
        "branch_actions": [action_to_data(action) for action in actions],
        "branch_canonical_digests": expected_digests,
        "branch_depth": len(actions),
        "repeats": repeats,
        "replayed_transitions": replayed,
    }


def _record_branch(
    backend: BalatroBotBackend,
    parent: AuthorityObservation,
    policy: DeterministicCoveragePolicy,
    depth: int,
) -> tuple[list[PublicAction], list[str]]:
    canonicalizer = BalatroBotCanonicalizer()
    _canonicalize(parent, canonicalizer)
    public = _public(parent)
    history: list[PublicHistoryStep] = []
    actions: list[PublicAction] = []
    digests: list[str] = []
    for _ in range(depth):
        if public.phase == Phase.GAME_OVER:
            break
        action = policy.choose_action(public, lambda: iter_legal_actions(public), tuple(history))
        result = backend.step(action)
        if result.status != "accepted" or result.after is None:
            raise RuntimeError(f"branch action failed: {result.status}: {result.error}")
        after_public = _public(result.after)
        actions.append(action)
        digests.append(_canonicalize(result.after, canonicalizer))
        history.append(PublicHistoryStep(public, action, after_public))
        public = after_public
    return actions, digests


def _root_digest(observation: AuthorityObservation) -> str:
    return _canonicalize(observation, BalatroBotCanonicalizer())


def _canonicalize(
    observation: AuthorityObservation,
    canonicalizer: BalatroBotCanonicalizer,
) -> str:
    raw = json.loads(observation.observed.raw_json)
    if not isinstance(raw, dict):
        raise RuntimeError("authority state root is not an object")
    return canonicalizer.canonicalize(raw).canonical_digest


def _public(observation: AuthorityObservation) -> PublicObservation:
    raw = json.loads(observation.observed.raw_json)
    if not isinstance(raw, dict):
        raise RuntimeError("authority state root is not an object")
    return to_public_observation(raw)


def _milliseconds_since(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark exact Balatro save/restore branch replay")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=12346)
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="WHITE")
    parser.add_argument("--seed", default="1")
    parser.add_argument("--depth", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--protocol", choices=("file", "memory"), default="file")
    parser.add_argument("--policy-seed", default="snapshot-benchmark-v1")
    parser.add_argument("--max-settle-polls", type=int, default=40)
    parser.add_argument("--settle-poll-delay", type=float, default=0.02)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--report-json", type=Path)
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
    parser.add_argument("--profile-mode", choices=("all_unlocked", "career"), default="all_unlocked")
    parser.add_argument("--launch-timeout", type=float, default=90.0)
    parser.add_argument("--launch-poll-delay", type=float, default=0.2)
    parser.add_argument("--post-launch-delay", type=float, default=1.0)
    return parser


if __name__ == "__main__":
    main()
