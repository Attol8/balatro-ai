"""Strict public-only protocol for the isolated candidate environment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TypeAlias

from balatro_ai_v2.actions import PublicAction, action_to_data, canonical_action_from_data
from balatro_ai_v2.jsonl import (
    JsonlProtocolError,
    decode_frame,
    encode_frame,
    nonnegative_integer,
    require_fields,
)
from balatro_ai_v2.public_codec import public_observation_from_data, public_observation_to_data
from balatro_ai_v2.public_state import PublicObservation


ENV_PROTOCOL_VERSION: Final = 2
ENV_REWARD_SCHEMA: Final = "sparse_terminal_v1"
ENV_CANONICAL_SCHEMA_VERSION: Final = 10
MAX_ENV_REQUEST_BYTES: Final = 64_000
MAX_ENV_RESPONSE_BYTES: Final = 1_000_000
EnvWireError = JsonlProtocolError


@dataclass(frozen=True, slots=True)
class WorkerHello:
    candidate_revision: str
    candidate_dirty: bool
    backend_name: str
    backend_version: str
    adapter_version: str
    game_version: str | None
    runtime_version: str | None
    python_version: str
    repository_revision: str
    repository_dirty: bool
    profile_mode: str
    config_digest: str
    canonical_schema_version: int
    reward_schema: str


@dataclass(frozen=True, slots=True)
class EnvResetRequest:
    request_id: int
    deck: str
    stake: str
    seed: str
    max_steps: int


@dataclass(frozen=True, slots=True)
class EnvStepRequest:
    request_id: int
    step_index: int
    action: PublicAction


@dataclass(frozen=True, slots=True)
class EnvCloseRequest:
    request_id: int


EnvRequest: TypeAlias = EnvResetRequest | EnvStepRequest | EnvCloseRequest


@dataclass(frozen=True, slots=True)
class EnvResetResult:
    request_id: int
    step_index: int
    observation: PublicObservation


@dataclass(frozen=True, slots=True)
class EnvStepResult:
    request_id: int
    step_index: int
    observation: PublicObservation
    reward: int
    terminated: bool
    truncated: bool
    terminal_reason: str | None
    won: bool | None


@dataclass(frozen=True, slots=True)
class EnvClosed:
    request_id: int


EnvResponse: TypeAlias = EnvResetResult | EnvStepResult | EnvClosed


def encode_hello(hello: WorkerHello) -> bytes:
    return encode_frame(
        {
            "protocol": ENV_PROTOCOL_VERSION,
            "type": "hello",
            "candidate_revision": hello.candidate_revision,
            "candidate_dirty": hello.candidate_dirty,
            "backend_name": hello.backend_name,
            "backend_version": hello.backend_version,
            "adapter_version": hello.adapter_version,
            "game_version": hello.game_version,
            "runtime_version": hello.runtime_version,
            "python_version": hello.python_version,
            "repository_revision": hello.repository_revision,
            "repository_dirty": hello.repository_dirty,
            "profile_mode": hello.profile_mode,
            "config_digest": hello.config_digest,
            "canonical_schema_version": hello.canonical_schema_version,
            "reward_schema": hello.reward_schema,
        },
        MAX_ENV_RESPONSE_BYTES,
    )


def decode_hello(frame: bytes) -> WorkerHello:
    raw = decode_frame(frame, MAX_ENV_RESPONSE_BYTES)
    expected = {
        "protocol",
        "type",
        "candidate_revision",
        "candidate_dirty",
        "backend_name",
        "backend_version",
        "adapter_version",
        "game_version",
        "runtime_version",
        "python_version",
        "repository_revision",
        "repository_dirty",
        "profile_mode",
        "config_digest",
        "canonical_schema_version",
        "reward_schema",
    }
    require_fields(raw, expected, "environment hello")
    if raw["protocol"] != ENV_PROTOCOL_VERSION or raw["type"] != "hello":
        raise EnvWireError("unsupported environment hello")
    return WorkerHello(
        candidate_revision=_string(raw["candidate_revision"], "candidate_revision"),
        candidate_dirty=_boolean(raw["candidate_dirty"], "candidate_dirty"),
        backend_name=_string(raw["backend_name"], "backend_name"),
        backend_version=_string(raw["backend_version"], "backend_version"),
        adapter_version=_string(raw["adapter_version"], "adapter_version"),
        game_version=_optional_string(raw["game_version"], "game_version"),
        runtime_version=_optional_string(raw["runtime_version"], "runtime_version"),
        python_version=_nonempty_string(raw["python_version"], "python_version"),
        repository_revision=_nonempty_string(
            raw["repository_revision"], "repository_revision"
        ),
        repository_dirty=_boolean(raw["repository_dirty"], "repository_dirty"),
        profile_mode=_nonempty_string(raw["profile_mode"], "profile_mode"),
        config_digest=_nonempty_string(raw["config_digest"], "config_digest"),
        canonical_schema_version=nonnegative_integer(
            raw["canonical_schema_version"], "canonical_schema_version"
        ),
        reward_schema=_string(raw["reward_schema"], "reward_schema"),
    )


def encode_env_request(request: EnvRequest) -> bytes:
    if isinstance(request, EnvResetRequest):
        payload: dict[str, object] = {
            "protocol": ENV_PROTOCOL_VERSION,
            "type": "reset",
            "request_id": request.request_id,
            "deck": request.deck,
            "stake": request.stake,
            "seed": request.seed,
            "max_steps": request.max_steps,
        }
    elif isinstance(request, EnvStepRequest):
        payload = {
            "protocol": ENV_PROTOCOL_VERSION,
            "type": "step",
            "request_id": request.request_id,
            "step_index": request.step_index,
            "action": action_to_data(request.action),
        }
    else:
        payload = {
            "protocol": ENV_PROTOCOL_VERSION,
            "type": "close",
            "request_id": request.request_id,
        }
    return encode_frame(payload, MAX_ENV_REQUEST_BYTES)


def decode_env_request(frame: bytes) -> EnvRequest:
    raw = decode_frame(frame, MAX_ENV_REQUEST_BYTES)
    if raw.get("protocol") != ENV_PROTOCOL_VERSION:
        raise EnvWireError("unsupported environment request protocol")
    request_type = raw.get("type")
    if request_type == "reset":
        require_fields(
            raw,
            {"protocol", "type", "request_id", "deck", "stake", "seed", "max_steps"},
            "reset",
        )
        return EnvResetRequest(
            nonnegative_integer(raw["request_id"], "request_id"),
            _nonempty_string(raw["deck"], "deck"),
            _nonempty_string(raw["stake"], "stake"),
            _nonempty_string(raw["seed"], "seed"),
            _positive_integer(raw["max_steps"], "max_steps"),
        )
    if request_type == "step":
        require_fields(
            raw,
            {"protocol", "type", "request_id", "step_index", "action"},
            "step",
        )
        try:
            action = canonical_action_from_data(raw["action"])
        except ValueError as exc:
            raise EnvWireError(f"invalid public action: {exc}") from exc
        return EnvStepRequest(
            nonnegative_integer(raw["request_id"], "request_id"),
            nonnegative_integer(raw["step_index"], "step_index"),
            action,
        )
    if request_type == "close":
        require_fields(raw, {"protocol", "type", "request_id"}, "close")
        return EnvCloseRequest(nonnegative_integer(raw["request_id"], "request_id"))
    raise EnvWireError(f"unknown environment request type {request_type!r}")


def encode_env_response(response: EnvResponse) -> bytes:
    if isinstance(response, EnvResetResult):
        payload: dict[str, object] = {
            "protocol": ENV_PROTOCOL_VERSION,
            "type": "reset_result",
            "request_id": response.request_id,
            "step_index": response.step_index,
            "observation_digest": response.observation.digest(),
            "observation": public_observation_to_data(response.observation),
        }
    elif isinstance(response, EnvStepResult):
        _validate_step_result(response)
        payload = {
            "protocol": ENV_PROTOCOL_VERSION,
            "type": "step_result",
            "request_id": response.request_id,
            "step_index": response.step_index,
            "observation_digest": response.observation.digest(),
            "observation": public_observation_to_data(response.observation),
            "reward": response.reward,
            "terminated": response.terminated,
            "truncated": response.truncated,
            "terminal_reason": response.terminal_reason,
            "won": response.won,
        }
    else:
        payload = {
            "protocol": ENV_PROTOCOL_VERSION,
            "type": "closed",
            "request_id": response.request_id,
        }
    return encode_frame(payload, MAX_ENV_RESPONSE_BYTES)


def decode_env_response(frame: bytes) -> EnvResponse:
    raw = decode_frame(frame, MAX_ENV_RESPONSE_BYTES)
    if raw.get("protocol") != ENV_PROTOCOL_VERSION:
        raise EnvWireError("unsupported environment response protocol")
    response_type = raw.get("type")
    if response_type == "reset_result":
        expected = {
            "protocol",
            "type",
            "request_id",
            "step_index",
            "observation_digest",
            "observation",
        }
        require_fields(raw, expected, "reset result")
        observation = _observation(raw)
        return EnvResetResult(
            nonnegative_integer(raw["request_id"], "request_id"),
            nonnegative_integer(raw["step_index"], "step_index"),
            observation,
        )
    if response_type == "step_result":
        expected = {
            "protocol",
            "type",
            "request_id",
            "step_index",
            "observation_digest",
            "observation",
            "reward",
            "terminated",
            "truncated",
            "terminal_reason",
            "won",
        }
        require_fields(raw, expected, "step result")
        result = EnvStepResult(
            request_id=nonnegative_integer(raw["request_id"], "request_id"),
            step_index=nonnegative_integer(raw["step_index"], "step_index"),
            observation=_observation(raw),
            reward=_integer(raw["reward"], "reward"),
            terminated=_boolean(raw["terminated"], "terminated"),
            truncated=_boolean(raw["truncated"], "truncated"),
            terminal_reason=_optional_string(raw["terminal_reason"], "terminal_reason"),
            won=_optional_boolean(raw["won"], "won"),
        )
        _validate_step_result(result)
        return result
    if response_type == "closed":
        require_fields(raw, {"protocol", "type", "request_id"}, "closed")
        return EnvClosed(nonnegative_integer(raw["request_id"], "request_id"))
    raise EnvWireError(f"unknown environment response type {response_type!r}")


def _observation(raw: dict[str, object]) -> PublicObservation:
    observation = public_observation_from_data(raw["observation"])
    digest = raw["observation_digest"]
    if not isinstance(digest, str) or digest != observation.digest():
        raise EnvWireError("environment observation digest mismatch")
    return observation


def _validate_step_result(result: EnvStepResult) -> None:
    terminal_public = result.observation.terminal
    if result.terminated != terminal_public:
        raise EnvWireError("terminated flag disagrees with the public phase")
    if result.terminated and result.truncated:
        raise EnvWireError("an environment result cannot terminate and truncate")
    if result.terminated:
        expected_reward = 1 if result.observation.won else -1
        expected_reason = "game_over"
        if (
            result.terminal_reason != expected_reason
            or result.won != result.observation.won
            or result.reward != expected_reward
        ):
            raise EnvWireError("terminal reward or outcome is inconsistent")
    elif result.truncated:
        if result.reward != 0 or result.terminal_reason != "step_limit" or result.won is not None:
            raise EnvWireError("truncated result is inconsistent")
    elif result.reward != 0 or result.terminal_reason is not None or result.won is not None:
        raise EnvWireError("non-terminal result contains terminal data")


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise EnvWireError(f"{name} must be a string")
    return value


def _nonempty_string(value: object, name: str) -> str:
    result = _string(value, name)
    if not result:
        raise EnvWireError(f"{name} cannot be empty")
    return result


def _optional_string(value: object, name: str) -> str | None:
    return None if value is None else _string(value, name)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EnvWireError(f"{name} must be an integer")
    return value


def _positive_integer(value: object, name: str) -> int:
    result = _integer(value, name)
    if result <= 0:
        raise EnvWireError(f"{name} must be positive")
    return result


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise EnvWireError(f"{name} must be a boolean")
    return value


def _optional_boolean(value: object, name: str) -> bool | None:
    return None if value is None else _boolean(value, name)
