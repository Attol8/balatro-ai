from __future__ import annotations

import json
from copy import deepcopy

import pytest

from balatro_ai_v2.actions import action_to_data, iter_legal_actions
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.policy_wire import (
    PolicyRequest,
    PolicyResponse,
    PolicyWireError,
    decode_request,
    decode_response,
    encode_request,
    encode_response,
)
from state_factory import state


def _request() -> PolicyRequest:
    observation = to_public_observation(state("SELECTING_HAND", seed="PRIVATE-SEED"))
    legal = tuple(iter_legal_actions(observation))
    return PolicyRequest(7, 3, observation, legal)


def test_policy_request_round_trip_contains_only_public_information() -> None:
    request = _request()

    frame = encode_request(request)
    decoded = decode_request(frame)

    assert decoded == request
    assert b"PRIVATE-SEED" not in frame
    assert b'"seed"' not in frame
    assert b'"rng"' not in frame
    assert b'"snapshot"' not in frame
    assert b'"raw"' not in frame


def test_policy_response_round_trip_is_canonical() -> None:
    request = _request()
    response = PolicyResponse(request.request_id, request.observation.digest(), request.legal_actions[0])

    assert decode_response(encode_response(response)) == response


def test_policy_wire_rejects_unknown_envelope_field() -> None:
    payload = json.loads(encode_request(_request()))
    payload["private"] = True
    frame = (json.dumps(payload) + "\n").encode()

    with pytest.raises(PolicyWireError, match="extra=.*private"):
        decode_request(frame)


def test_policy_wire_rejects_noncanonical_action_field() -> None:
    payload = json.loads(encode_request(_request()))
    payload["legal_actions"][0]["private"] = 1
    frame = (json.dumps(payload) + "\n").encode()

    with pytest.raises(PolicyWireError, match="canonical form"):
        decode_request(frame)


def test_policy_wire_rejects_digest_mismatch_and_invalid_constant() -> None:
    payload = json.loads(encode_request(_request()))
    payload["observation_digest"] = "stale"

    with pytest.raises(PolicyWireError, match="digest mismatch"):
        decode_request((json.dumps(payload) + "\n").encode())
    with pytest.raises(PolicyWireError, match="invalid JSON constant"):
        decode_response(b'{"value":NaN}\n')


def test_policy_wire_rejects_duplicate_legal_actions() -> None:
    payload = json.loads(encode_request(_request()))
    payload["legal_actions"].append(deepcopy(payload["legal_actions"][0]))

    with pytest.raises(PolicyWireError, match="duplicates"):
        decode_request((json.dumps(payload) + "\n").encode())


def test_policy_response_rejects_unknown_action_data() -> None:
    request = _request()
    payload = {
        "protocol": 1,
        "type": "action",
        "request_id": 7,
        "observation_digest": request.observation.digest(),
        "action": {**action_to_data(request.legal_actions[0]), "private": 1},
    }

    with pytest.raises(PolicyWireError, match="canonical form"):
        decode_response((json.dumps(payload) + "\n").encode())
