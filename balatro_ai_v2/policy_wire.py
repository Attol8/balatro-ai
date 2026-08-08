"""Strict JSON-lines protocol for the public policy process boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final

from balatro_ai_v2.actions import PublicAction, action_from_data, action_to_data
from balatro_ai_v2.public_codec import public_observation_from_data, public_observation_to_data
from balatro_ai_v2.public_state import PublicObservation


POLICY_PROTOCOL_VERSION: Final = 1
MAX_LEGAL_ACTIONS: Final = 512
MAX_PUBLIC_HISTORY: Final = 2048
MAX_REQUEST_BYTES: Final = 1_000_000
MAX_RESPONSE_BYTES: Final = 32_000


class PolicyWireError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    request_id: int
    history_length: int
    observation: PublicObservation
    legal_actions: tuple[PublicAction, ...]


@dataclass(frozen=True, slots=True)
class PolicyResponse:
    request_id: int
    observation_digest: str
    action: PublicAction


def encode_request(request: PolicyRequest) -> bytes:
    if not 0 <= request.request_id:
        raise PolicyWireError("request_id must be non-negative")
    if not 0 <= request.history_length <= MAX_PUBLIC_HISTORY:
        raise PolicyWireError("history_length exceeds the public bound")
    if not 1 <= len(request.legal_actions) <= MAX_LEGAL_ACTIONS:
        raise PolicyWireError("legal action count is outside the public bound")
    payload = {
        "protocol": POLICY_PROTOCOL_VERSION,
        "type": "choose_action",
        "request_id": request.request_id,
        "history_length": request.history_length,
        "observation_digest": request.observation.digest(),
        "observation": public_observation_to_data(request.observation),
        "legal_actions": [action_to_data(action) for action in request.legal_actions],
    }
    return _encode_frame(payload, MAX_REQUEST_BYTES)


def decode_request(frame: bytes) -> PolicyRequest:
    payload = _decode_frame(frame, MAX_REQUEST_BYTES)
    expected = {
        "protocol",
        "type",
        "request_id",
        "history_length",
        "observation_digest",
        "observation",
        "legal_actions",
    }
    _require_fields(payload, expected, "policy request")
    if payload["protocol"] != POLICY_PROTOCOL_VERSION or payload["type"] != "choose_action":
        raise PolicyWireError("unsupported policy request protocol or type")
    request_id = _nonnegative_integer(payload["request_id"], "request_id")
    history_length = _nonnegative_integer(payload["history_length"], "history_length")
    if history_length > MAX_PUBLIC_HISTORY:
        raise PolicyWireError("history_length exceeds the public bound")
    observation = public_observation_from_data(payload["observation"])
    digest = payload["observation_digest"]
    if not isinstance(digest, str) or digest != observation.digest():
        raise PolicyWireError("policy request observation digest mismatch")
    legal_raw = payload["legal_actions"]
    if not isinstance(legal_raw, list) or not 1 <= len(legal_raw) <= MAX_LEGAL_ACTIONS:
        raise PolicyWireError("legal action count is outside the public bound")
    legal_actions = tuple(_canonical_action(value) for value in legal_raw)
    serialized = [_canonical_json(action_to_data(action)) for action in legal_actions]
    if len(serialized) != len(set(serialized)):
        raise PolicyWireError("legal action list contains duplicates")
    return PolicyRequest(request_id, history_length, observation, legal_actions)


def encode_response(response: PolicyResponse) -> bytes:
    if not 0 <= response.request_id or not response.observation_digest:
        raise PolicyWireError("policy response identity is invalid")
    return _encode_frame(
        {
            "protocol": POLICY_PROTOCOL_VERSION,
            "type": "action",
            "request_id": response.request_id,
            "observation_digest": response.observation_digest,
            "action": action_to_data(response.action),
        },
        MAX_RESPONSE_BYTES,
    )


def decode_response(frame: bytes) -> PolicyResponse:
    payload = _decode_frame(frame, MAX_RESPONSE_BYTES)
    expected = {"protocol", "type", "request_id", "observation_digest", "action"}
    _require_fields(payload, expected, "policy response")
    if payload["protocol"] != POLICY_PROTOCOL_VERSION or payload["type"] != "action":
        raise PolicyWireError("unsupported policy response protocol or type")
    request_id = _nonnegative_integer(payload["request_id"], "request_id")
    digest = payload["observation_digest"]
    if not isinstance(digest, str) or not digest:
        raise PolicyWireError("policy response observation_digest must be a string")
    return PolicyResponse(request_id, digest, _canonical_action(payload["action"]))


def _canonical_action(value: object) -> PublicAction:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise PolicyWireError("public action must be an object")
    try:
        action = action_from_data(value)
    except (TypeError, ValueError) as exc:
        raise PolicyWireError(f"invalid public action: {exc}") from exc
    if action_to_data(action) != value:
        raise PolicyWireError("public action is not in canonical form")
    return action


def _encode_frame(payload: dict[str, object], maximum: int) -> bytes:
    try:
        encoded = (_canonical_json(payload) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PolicyWireError(f"policy frame is not JSON serializable: {exc}") from exc
    if len(encoded) > maximum:
        raise PolicyWireError(f"policy frame exceeds {maximum} bytes")
    return encoded


def _decode_frame(frame: bytes, maximum: int) -> dict[str, object]:
    if not frame or len(frame) > maximum or not frame.endswith(b"\n"):
        raise PolicyWireError("policy frame is empty, oversized, or unterminated")
    try:
        text = frame.decode("utf-8")
        value: object = json.loads(text, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PolicyWireError(f"invalid policy JSON: {exc}") from exc
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise PolicyWireError("policy frame root must be an object")
    return dict(value)


def _reject_constant(value: str) -> object:
    raise PolicyWireError(f"invalid JSON constant {value!r}")


def _require_fields(raw: dict[str, object], expected: set[str], name: str) -> None:
    actual = set(raw)
    if actual != expected:
        raise PolicyWireError(
            f"{name} fields differ: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def _nonnegative_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PolicyWireError(f"{name} must be a non-negative integer")
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
