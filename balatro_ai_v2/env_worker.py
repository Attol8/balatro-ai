"""Pinned-candidate worker exposing only the strict public environment protocol."""

from __future__ import annotations

import json
import hashlib
import platform
import subprocess
import sys
from pathlib import Path

from balatro_ai_v2.actions import is_legal
from balatro_ai_v2.backend import AuthorityObservation, RunSpec
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.env_wire import (
    ENV_CANONICAL_SCHEMA_VERSION,
    ENV_REWARD_SCHEMA,
    MAX_ENV_REQUEST_BYTES,
    EnvCloseRequest,
    EnvClosed,
    EnvResetRequest,
    EnvResetResult,
    EnvStepRequest,
    EnvStepResult,
    WorkerHello,
    decode_env_request,
    encode_env_response,
    encode_hello,
)
from balatro_ai_v2.jackdaw import JackdawBackend, verify_jackdaw_runtime
from balatro_ai_v2.public_state import Phase, PublicObservation


def main() -> None:
    backend: JackdawBackend | None = None
    try:
        runtime = verify_jackdaw_runtime()
        backend = JackdawBackend()
        metadata = backend.metadata
        repository_revision, repository_dirty = _repository_state()
        config_digest = _config_digest(
            runtime,
            metadata.backend_name,
            metadata.backend_version,
            metadata.adapter_version,
        )
        hello = WorkerHello(
            candidate_revision=str(runtime["revision"]),
            candidate_dirty=bool(runtime["dirty"]),
            backend_name=metadata.backend_name,
            backend_version=metadata.backend_version,
            adapter_version=metadata.adapter_version,
            game_version=metadata.game_version,
            runtime_version=metadata.runtime_version,
            python_version=platform.python_version(),
            repository_revision=repository_revision,
            repository_dirty=repository_dirty,
            profile_mode="all_unlocked",
            config_digest=config_digest,
            canonical_schema_version=ENV_CANONICAL_SCHEMA_VERSION,
            reward_schema=ENV_REWARD_SCHEMA,
        )
        _write(encode_hello(hello))

        expected_request_id = 0
        step_index = 0
        max_steps = 0
        done = False
        current: PublicObservation | None = None
        while True:
            frame = sys.stdin.buffer.readline(MAX_ENV_REQUEST_BYTES + 1)
            if not frame:
                return
            request = decode_env_request(frame)
            if request.request_id != expected_request_id:
                raise RuntimeError("environment request ID is not contiguous")
            expected_request_id += 1

            if isinstance(request, EnvResetRequest):
                current = _public(backend.reset(RunSpec(request.deck, request.stake, request.seed)))
                step_index = 0
                max_steps = request.max_steps
                done = False
                _write(encode_env_response(EnvResetResult(request.request_id, step_index, current)))
                continue
            if isinstance(request, EnvCloseRequest):
                _write(encode_env_response(EnvClosed(request.request_id)))
                return
            if not isinstance(request, EnvStepRequest) or current is None or done:
                raise RuntimeError("environment must be reset before stepping")
            if request.step_index != step_index:
                raise RuntimeError("environment step index is stale")
            if current.terminal or not is_legal(current, request.action):
                raise RuntimeError("environment received an illegal or post-terminal action")
            result = backend.step(request.action)
            if result.status != "accepted" or result.after is None:
                raise RuntimeError(f"candidate rejected public action: {result.status}")
            current = _public(result.after)
            step_index += 1
            terminated = current.terminal
            truncated = not terminated and step_index >= max_steps
            done = terminated or truncated
            reward = (1 if current.won else -1) if terminated else 0
            response = EnvStepResult(
                request_id=request.request_id,
                step_index=step_index,
                observation=current,
                reward=reward,
                terminated=terminated,
                truncated=truncated,
                terminal_reason=(
                    "game_over"
                    if terminated and current.phase == Phase.GAME_OVER
                    else "won"
                    if terminated
                    else "step_limit"
                    if truncated
                    else None
                ),
                won=current.won if terminated else None,
            )
            _write(encode_env_response(response))
    except Exception as exc:
        print(f"environment worker failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2) from exc
    finally:
        if backend is not None:
            backend.close()


def _public(authority: AuthorityObservation) -> PublicObservation:
    raw: object = json.loads(authority.observed.raw_json)
    if not isinstance(raw, dict):
        raise RuntimeError("candidate observation root is not an object")
    return to_public_observation(raw)


def _write(frame: bytes) -> None:
    sys.stdout.buffer.write(frame)
    sys.stdout.buffer.flush()


def _repository_state() -> tuple[str, bool]:
    root = Path(__file__).resolve().parents[1]
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True
    return revision, dirty


def _config_digest(
    runtime: dict[str, object],
    backend_name: str,
    backend_version: str,
    adapter_version: str,
) -> str:
    payload = {
        "adapter_version": adapter_version,
        "backend_name": backend_name,
        "backend_version": backend_version,
        "candidate_revision": runtime["revision"],
        "canonical_schema_version": ENV_CANONICAL_SCHEMA_VERSION,
        "profile_mode": "all_unlocked",
        "python_version": platform.python_version(),
        "reward_schema": ENV_REWARD_SCHEMA,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    main()
