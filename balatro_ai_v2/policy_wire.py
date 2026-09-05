"""Strict JSON-lines protocol for the public policy process boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
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


POLICY_PROTOCOL_VERSION: Final = 8
POLICY_ACTION_CONTRACT: Final = "public_legality_boss_reroll_v7"
MAX_PUBLIC_HISTORY: Final = 2048
MAX_REQUEST_BYTES: Final = 1_000_000
MAX_RESPONSE_BYTES: Final = 32_000
MAX_INCOMPLETE_REASON_CHARS: Final = 160
INCOMPLETE_REASON_CODES: Final = frozenset(
    {
        "baseline_illegal",
        "baseline_omitted",
        "baseline_semantic_absent",
        "chance_outcome_budget",
        "decision_horizon",
        "draw_distribution_budget",
        "future_baseline_outside_action_space",
        "proposal_preflight",
        "raw_action_budget",
        "score_budget",
        "scoring_contract",
        "semantic_action_budget",
        "state_budget",
        "successor_probability",
        "transition_budget",
        "unknown",
    }
)


PolicyWireError = JsonlProtocolError


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    request_id: int
    history_length: int
    observation: PublicObservation


@dataclass(frozen=True, slots=True)
class SearchDecisionDiagnostics:
    """Small, non-stateful accounting for one search family.

    This is deliberately not a generic diagnostics payload: it cannot carry
    observations, action values, random material, or engine state.
    """

    attempted: bool = False
    completed: bool = False
    changed: bool = False
    incomplete_reason: str | None = None

    def __post_init__(self) -> None:
        if not all(isinstance(value, bool) for value in (self.attempted, self.completed, self.changed)):
            raise ValueError("search diagnostic flags must be boolean")
        if (self.completed or self.changed) and not self.attempted:
            raise ValueError("completed or changed search must have been attempted")
        if self.incomplete_reason is not None:
            if self.completed or not self.attempted:
                raise ValueError("incomplete reason requires an attempted incomplete search")
            if (
                not isinstance(self.incomplete_reason, str)
                or not self.incomplete_reason
                or len(self.incomplete_reason) > MAX_INCOMPLETE_REASON_CHARS
                or not self.incomplete_reason.isprintable()
                or self.incomplete_reason not in INCOMPLETE_REASON_CODES
            ):
                raise ValueError("incomplete reason is invalid or exceeds its bound")


@dataclass(frozen=True, slots=True)
class PolicyDiagnostics:
    """Fixed public-policy accounting emitted alongside every action."""

    exact_blind: SearchDecisionDiagnostics = field(default_factory=SearchDecisionDiagnostics)
    preboss: SearchDecisionDiagnostics = field(default_factory=SearchDecisionDiagnostics)


@dataclass(frozen=True, slots=True)
class PolicyResponse:
    request_id: int
    observation_digest: str
    action: PublicAction
    diagnostics: PolicyDiagnostics = field(default_factory=PolicyDiagnostics)


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
            "diagnostics": _diagnostics_to_data(response.diagnostics),
        },
        MAX_RESPONSE_BYTES,
    )


def decode_response(frame: bytes) -> PolicyResponse:
    payload = decode_frame(frame, MAX_RESPONSE_BYTES)
    expected = {"protocol", "type", "request_id", "observation_digest", "action", "diagnostics"}
    require_fields(payload, expected, "policy response")
    if payload["protocol"] != POLICY_PROTOCOL_VERSION or payload["type"] != "action":
        raise PolicyWireError("unsupported policy response protocol or type")
    request_id = nonnegative_integer(payload["request_id"], "request_id")
    digest = payload["observation_digest"]
    if not isinstance(digest, str) or not digest:
        raise PolicyWireError("policy response observation_digest must be a string")
    return PolicyResponse(
        request_id,
        digest,
        _canonical_action(payload["action"]),
        _diagnostics_from_data(payload["diagnostics"]),
    )


def _diagnostics_to_data(value: PolicyDiagnostics) -> dict[str, object]:
    return {
        "exact_blind": _search_diagnostics_to_data(value.exact_blind),
        "preboss": _search_diagnostics_to_data(value.preboss),
    }


def _search_diagnostics_to_data(value: SearchDecisionDiagnostics) -> dict[str, object]:
    return {
        "attempted": value.attempted,
        "completed": value.completed,
        "changed": value.changed,
        "incomplete_reason": value.incomplete_reason,
    }


def _diagnostics_from_data(value: object) -> PolicyDiagnostics:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise PolicyWireError("policy diagnostics must be an object with string keys")
    expected = {"exact_blind", "preboss"}
    require_fields(value, expected, "policy diagnostics")
    return PolicyDiagnostics(
        exact_blind=_search_diagnostics_from_data(value["exact_blind"], "exact_blind"),
        preboss=_search_diagnostics_from_data(value["preboss"], "preboss"),
    )


def _search_diagnostics_from_data(value: object, name: str) -> SearchDecisionDiagnostics:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise PolicyWireError(f"{name} diagnostics must be an object with string keys")
    expected = {"attempted", "completed", "changed", "incomplete_reason"}
    require_fields(value, expected, f"{name} diagnostics")
    attempted = value["attempted"]
    completed = value["completed"]
    changed = value["changed"]
    reason = value["incomplete_reason"]
    if not all(isinstance(flag, bool) for flag in (attempted, completed, changed)):
        raise PolicyWireError(f"{name} diagnostics flags must be boolean")
    if reason is not None and not isinstance(reason, str):
        raise PolicyWireError(f"{name} diagnostics incomplete_reason must be a string or null")
    try:
        return SearchDecisionDiagnostics(attempted, completed, changed, reason)
    except ValueError as exc:
        raise PolicyWireError(f"invalid {name} diagnostics: {exc}") from exc


def _canonical_action(value: object) -> PublicAction:
    try:
        return canonical_action_from_data(value)
    except (TypeError, ValueError) as exc:
        raise PolicyWireError(f"invalid public action: {exc}") from exc
