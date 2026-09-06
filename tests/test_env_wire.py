from __future__ import annotations

import json

import pytest

from balatro_ai_v2.actions import SelectBlind
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.env_wire import (
    ENV_CANONICAL_SCHEMA_VERSION,
    ENV_PROTOCOL_VERSION,
    ENV_REWARD_SCHEMA,
    EnvCloseRequest,
    EnvClosed,
    EnvRequest,
    EnvResetRequest,
    EnvResetResult,
    EnvStepRequest,
    EnvStepResult,
    EnvWireError,
    WorkerHello,
    decode_env_request,
    decode_env_response,
    decode_hello,
    encode_env_request,
    encode_env_response,
    encode_hello,
)
from state_factory import state


def test_environment_hello_round_trip() -> None:
    hello = WorkerHello(
        candidate_revision="abc",
        candidate_dirty=False,
        backend_name="Jackdaw",
        backend_version="1",
        adapter_version="1",
        game_version="game",
        runtime_version="python",
        python_version="3.12.11",
        repository_revision="abc123",
        repository_dirty=False,
        profile_mode="all_unlocked",
        config_digest="config-digest",
        canonical_schema_version=ENV_CANONICAL_SCHEMA_VERSION,
        reward_schema=ENV_REWARD_SCHEMA,
    )

    assert decode_hello(encode_hello(hello)) == hello


@pytest.mark.parametrize(
    "env_request",
    [
        EnvResetRequest(1, "RED", "WHITE", "PRIVATE-SEED", 800),
        EnvStepRequest(2, 0, SelectBlind()),
        EnvCloseRequest(3),
    ],
)
def test_environment_request_round_trip(env_request: EnvRequest) -> None:
    assert decode_env_request(encode_env_request(env_request)) == env_request


def test_environment_reset_response_contains_no_seed() -> None:
    observation = to_public_observation(state(seed="PRIVATE-SEED"))
    response = EnvResetResult(1, 0, observation)

    frame = encode_env_response(response)

    assert decode_env_response(frame) == response
    assert b"PRIVATE-SEED" not in frame
    assert b'"seed"' not in frame


def test_environment_step_response_enforces_sparse_public_reward() -> None:
    playing = to_public_observation(state("SELECTING_HAND"))
    terminal = to_public_observation(state("GAME_OVER", won=True))
    win_boundary = to_public_observation(state("ROUND_EVAL", won=True))
    ongoing = EnvStepResult(2, 1, playing, 0, False, False, None, None)
    won = EnvStepResult(3, 2, terminal, 1, True, False, "game_over", True)
    continuing_endless = EnvStepResult(4, 2, win_boundary, 0, False, False, None, None)
    truncated = EnvStepResult(5, 3, playing, 0, False, True, "step_limit", None)

    assert decode_env_response(encode_env_response(ongoing)) == ongoing
    assert decode_env_response(encode_env_response(won)) == won
    assert decode_env_response(encode_env_response(continuing_endless)) == continuing_endless
    assert decode_env_response(encode_env_response(truncated)) == truncated
    assert decode_env_response(encode_env_response(EnvClosed(6))) == EnvClosed(6)


def test_environment_wire_rejects_inconsistent_terminal_data() -> None:
    terminal = to_public_observation(state("GAME_OVER", won=False))

    with pytest.raises(EnvWireError, match="terminal reward"):
        encode_env_response(
            EnvStepResult(1, 1, terminal, 1, True, False, "game_over", False)
        )


def test_environment_wire_rejects_noncanonical_action() -> None:
    payload = {
        "protocol": ENV_PROTOCOL_VERSION,
        "type": "step",
        "request_id": 1,
        "step_index": 0,
        "action": {"type": "select_blind", "private": True},
    }

    with pytest.raises(EnvWireError, match="canonical form"):
        decode_env_request((json.dumps(payload) + "\n").encode())


def test_environment_wire_rejects_unknown_fields() -> None:
    payload = json.loads(encode_env_request(EnvCloseRequest(1)))
    payload["snapshot"] = "private"

    with pytest.raises(EnvWireError, match="extra=.*snapshot"):
        decode_env_request((json.dumps(payload) + "\n").encode())
