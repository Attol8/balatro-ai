"""Strict JSON-lines protocol for the public policy process boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

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


POLICY_PROTOCOL_VERSION: Final = 2
POLICY_ACTION_CONTRACT: Final = "public_legality_v3"
MAX_PUBLIC_HISTORY: Final = 2048
MAX_REQUEST_BYTES: Final = 1_000_000
MAX_RESPONSE_BYTES: Final = 32_000


PolicyWireError = JsonlProtocolError


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    request_id: int
    history_length: int
    observation: PublicObservation


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
    payload = {
        "protocol": POLICY_PROTOCOL_VERSION,
        "type": "choose_action",
        "action_contract": POLICY_ACTION_CONTRACT,
        "request_id": request.request_id,
        "history_length": request.history_length,
        "observation_digest": request.observation.digest(),
        "observation": public_observation_to_data(request.observation),
    }
    return encode_frame(payload, MAX_REQUEST_BYTES)


def decode_request(frame: bytes) -> PolicyRequest:
    payload = decode_frame(frame, MAX_REQUEST_BYTES)
    expected = {
        "protocol",
        "type",
        "action_contract",
        "request_id",
        "history_length",
        "observation_digest",
        "observation",
    }
    require_fields(payload, expected, "policy request")
    if (
        payload["protocol"] != POLICY_PROTOCOL_VERSION
        or payload["type"] != "choose_action"
        or payload["action_contract"] != POLICY_ACTION_CONTRACT
    ):
        raise PolicyWireError("unsupported policy request protocol or type")
    request_id = nonnegative_integer(payload["request_id"], "request_id")
    history_length = nonnegative_integer(payload["history_length"], "history_length")
    if history_length > MAX_PUBLIC_HISTORY:
        raise PolicyWireError("history_length exceeds the public bound")
    observation = public_observation_from_data(payload["observation"])
    digest = payload["observation_digest"]
    if not isinstance(digest, str) or digest != observation.digest():
        raise PolicyWireError("policy request observation digest mismatch")
    return PolicyRequest(request_id, history_length, observation)


def encode_response(response: PolicyResponse) -> bytes:
    if not 0 <= response.request_id or not response.observation_digest:
        raise PolicyWireError("policy response identity is invalid")
    return encode_frame(
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
    payload = decode_frame(frame, MAX_RESPONSE_BYTES)
    expected = {"protocol", "type", "request_id", "observation_digest", "action"}
    require_fields(payload, expected, "policy response")
    if payload["protocol"] != POLICY_PROTOCOL_VERSION or payload["type"] != "action":
        raise PolicyWireError("unsupported policy response protocol or type")
    request_id = nonnegative_integer(payload["request_id"], "request_id")
    digest = payload["observation_digest"]
    if not isinstance(digest, str) or not digest:
        raise PolicyWireError("policy response observation_digest must be a string")
    return PolicyResponse(request_id, digest, _canonical_action(payload["action"]))


def _canonical_action(value: object) -> PublicAction:
    try:
        return canonical_action_from_data(value)
    except (TypeError, ValueError) as exc:
        raise PolicyWireError(f"invalid public action: {exc}") from exc
