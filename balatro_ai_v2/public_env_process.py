"""Trainer-side public client for the isolated pinned candidate worker."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from balatro_ai_v2.actions import PublicAction, is_legal
from balatro_ai_v2.env_wire import (
    ENV_CANONICAL_SCHEMA_VERSION,
    ENV_REWARD_SCHEMA,
    MAX_ENV_REQUEST_BYTES,
    MAX_ENV_RESPONSE_BYTES,
    EnvCloseRequest,
    EnvClosed,
    EnvResetRequest,
    EnvResetResult,
    EnvStepRequest,
    EnvStepResult,
    EnvWireError,
    WorkerHello,
    decode_env_response,
    decode_hello,
    encode_env_request,
)
from balatro_ai_v2.jsonl_process import (
    JsonlChildProcess,
    JsonlProcessError,
    minimal_child_environment,
)
from balatro_ai_v2.public_state import Phase, PublicObservation


class PublicEnvironmentError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PublicEpisodeSpec:
    deck: str
    stake: str
    seed: str
    max_steps: int = 800


@dataclass(frozen=True, slots=True)
class PublicTransition:
    observation: PublicObservation
    reward: int
    terminated: bool
    truncated: bool
    terminal_reason: str | None
    won: bool | None
    step_index: int


class PublicEnvironmentProcess:
    def __init__(
        self,
        *,
        worker_python: Path,
        candidate_root: Path,
        timeout_seconds: float = 5.0,
    ) -> None:
        root = Path(__file__).resolve().parents[1]
        expected_revision = _pinned_revision(root)
        self._transport = JsonlChildProcess(
            (str(worker_python), "-m", "balatro_ai_v2.env_worker"),
            cwd=root,
            environment=minimal_child_environment((root, candidate_root)),
            timeout_seconds=timeout_seconds,
            max_request_bytes=MAX_ENV_REQUEST_BYTES,
            max_response_bytes=MAX_ENV_RESPONSE_BYTES,
        )
        try:
            self.hello = decode_hello(self._transport.read_startup_frame())
            _validate_hello(self.hello, expected_revision)
        except (EnvWireError, JsonlProcessError, PublicEnvironmentError):
            self._transport.close()
            raise
        self._request_id = 0
        self._step_index = 0
        self._current: PublicObservation | None = None
        self._done = False

    @property
    def closed(self) -> bool:
        return self._transport.closed

    def reset(self, spec: PublicEpisodeSpec) -> PublicObservation:
        if spec.max_steps <= 0:
            raise PublicEnvironmentError("episode max_steps must be positive")
        response = self._exchange(
            EnvResetRequest(
                self._request_id,
                spec.deck,
                spec.stake,
                spec.seed,
                spec.max_steps,
            )
        )
        if not isinstance(response, EnvResetResult) or response.request_id != self._request_id:
            self.close()
            raise PublicEnvironmentError("environment reset response is stale or has the wrong type")
        if response.step_index != 0 or response.observation.phase == Phase.GAME_OVER:
            self.close()
            raise PublicEnvironmentError("environment reset returned an invalid public state")
        self._request_id += 1
        self._step_index = 0
        self._current = response.observation
        self._done = False
        return response.observation

    def step(self, action: PublicAction) -> PublicTransition:
        if self._current is None:
            raise PublicEnvironmentError("environment must be reset before stepping")
        if self._done or self._current.phase == Phase.GAME_OVER or not is_legal(self._current, action):
            raise PublicEnvironmentError("action is illegal in the current public observation")
        response = self._exchange(EnvStepRequest(self._request_id, self._step_index, action))
        if not isinstance(response, EnvStepResult) or response.request_id != self._request_id:
            self.close()
            raise PublicEnvironmentError("environment step response is stale or has the wrong type")
        if response.step_index != self._step_index + 1:
            self.close()
            raise PublicEnvironmentError("environment step index is not contiguous")
        self._request_id += 1
        self._step_index = response.step_index
        self._current = response.observation
        self._done = response.terminated or response.truncated
        return PublicTransition(
            observation=response.observation,
            reward=response.reward,
            terminated=response.terminated,
            truncated=response.truncated,
            terminal_reason=response.terminal_reason,
            won=response.won,
            step_index=response.step_index,
        )

    def close(self) -> None:
        if self.closed:
            return
        try:
            frame = encode_env_request(EnvCloseRequest(self._request_id))
            response = decode_env_response(self._transport.exchange(frame))
            if not isinstance(response, EnvClosed) or response.request_id != self._request_id:
                raise PublicEnvironmentError("environment close response is invalid")
        except (EnvWireError, JsonlProcessError, PublicEnvironmentError):
            pass
        finally:
            self._transport.close()

    def __enter__(self) -> PublicEnvironmentProcess:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _exchange(self, request: EnvResetRequest | EnvStepRequest) -> EnvResetResult | EnvStepResult:
        try:
            frame = encode_env_request(request)
            response = decode_env_response(self._transport.exchange(frame))
        except (EnvWireError, JsonlProcessError) as exc:
            self._transport.close()
            raise PublicEnvironmentError(f"environment worker protocol failed: {exc}") from exc
        if not isinstance(response, (EnvResetResult, EnvStepResult)):
            self._transport.close()
            raise PublicEnvironmentError("environment worker returned an unexpected response")
        return response


def _pinned_revision(root: Path) -> str:
    path = root / "kernels" / "jackdaw.lock.json"
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicEnvironmentError("cannot read the pinned candidate lock") from exc
    if not isinstance(value, dict) or not isinstance(value.get("revision"), str):
        raise PublicEnvironmentError("candidate lock has no revision")
    return value["revision"]


def _validate_hello(hello: WorkerHello, expected_revision: str) -> None:
    if hello.candidate_revision != expected_revision or hello.candidate_dirty:
        raise PublicEnvironmentError("environment worker is not the clean pinned candidate")
    if (
        hello.reward_schema != ENV_REWARD_SCHEMA
        or hello.canonical_schema_version != ENV_CANONICAL_SCHEMA_VERSION
        or not hello.python_version.startswith("3.12.")
        or hello.profile_mode != "all_unlocked"
    ):
        raise PublicEnvironmentError("environment worker schema is incompatible")
