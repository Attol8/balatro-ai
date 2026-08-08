from __future__ import annotations

import json
from pathlib import Path

import pytest

import balatro_ai_v2.public_env_process as public_env
from balatro_ai_v2.actions import SelectBlind, SkipPack
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.env_wire import (
    ENV_CANONICAL_SCHEMA_VERSION,
    ENV_REWARD_SCHEMA,
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
from balatro_ai_v2.public_env_process import (
    PublicEnvironmentError,
    PublicEnvironmentProcess,
    PublicEpisodeSpec,
)
from state_factory import state


PINNED_REVISION = "dbedc66255fe594cce7b7cccc188c8a11649d9ec"


class FakeEnvironmentTransport:
    hello = WorkerHello(
        candidate_revision=PINNED_REVISION,
        candidate_dirty=False,
        backend_name="Jackdaw",
        backend_version="test",
        adapter_version="test",
        game_version="test",
        runtime_version="test",
        python_version="3.12.11",
        repository_revision="repo",
        repository_dirty=False,
        profile_mode="all_unlocked",
        config_digest="config",
        canonical_schema_version=ENV_CANONICAL_SCHEMA_VERSION,
        reward_schema=ENV_REWARD_SCHEMA,
    )
    stale_step = False

    def __init__(self, *_: object, **__: object) -> None:
        self.closed = False
        self.exchanges = 0
        self.reset_request: EnvResetRequest | None = None

    def read_startup_frame(self) -> bytes:
        return encode_hello(self.hello)

    def exchange(self, frame: bytes) -> bytes:
        self.exchanges += 1
        request = decode_env_request(frame)
        if isinstance(request, EnvResetRequest):
            self.reset_request = request
            observation = to_public_observation(state())
            return encode_env_response(EnvResetResult(request.request_id, 0, observation))
        if isinstance(request, EnvStepRequest):
            terminal = to_public_observation(state("GAME_OVER", won=False))
            step_index = request.step_index if self.stale_step else request.step_index + 1
            return encode_env_response(
                EnvStepResult(
                    request.request_id,
                    step_index,
                    terminal,
                    -1,
                    True,
                    False,
                    "game_over",
                    False,
                )
            )
        assert isinstance(request, EnvCloseRequest)
        return encode_env_response(EnvClosed(request.request_id))

    def close(self) -> None:
        self.closed = True


def _environment(monkeypatch: pytest.MonkeyPatch) -> PublicEnvironmentProcess:
    monkeypatch.setattr(public_env, "JsonlChildProcess", FakeEnvironmentTransport)
    return PublicEnvironmentProcess(worker_python=Path("python3.12"), candidate_root=Path("candidate"))


def test_public_environment_process_reset_step_close_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment(monkeypatch)

    observation = environment.reset(PublicEpisodeSpec("RED", "WHITE", "PRIVATE-SEED", 9))
    transition = environment.step(SelectBlind())

    assert observation.phase.value == "BLIND_SELECT"
    assert transition.terminated and not transition.truncated
    assert transition.reward == -1
    assert transition.terminal_reason == "game_over"
    assert transition.won is False
    assert environment._transport.reset_request == EnvResetRequest(  # noqa: SLF001
        0, "RED", "WHITE", "PRIVATE-SEED", 9
    )
    with pytest.raises(PublicEnvironmentError, match="illegal"):
        environment.step(SelectBlind())

    environment.close()
    assert environment.closed


def test_public_environment_rejects_illegal_action_before_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = _environment(monkeypatch)
    environment.reset(PublicEpisodeSpec("RED", "WHITE", "PRIVATE-SEED"))
    exchanges = environment._transport.exchanges  # noqa: SLF001

    with pytest.raises(PublicEnvironmentError, match="illegal"):
        environment.step(SkipPack())

    assert environment._transport.exchanges == exchanges  # noqa: SLF001
    environment.close()


def test_public_environment_rejects_stale_step_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeEnvironmentTransport.stale_step = True
    try:
        environment = _environment(monkeypatch)
        environment.reset(PublicEpisodeSpec("RED", "WHITE", "PRIVATE-SEED"))

        with pytest.raises(PublicEnvironmentError, match="not contiguous"):
            environment.step(SelectBlind())

        assert environment.closed
    finally:
        FakeEnvironmentTransport.stale_step = False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate_revision", "wrong"),
        ("candidate_dirty", True),
        ("python_version", "3.11.9"),
        ("profile_mode", "career"),
        ("reward_schema", "private_reward"),
    ],
)
def test_public_environment_rejects_incompatible_worker_hello(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    original = FakeEnvironmentTransport.hello
    payload = json.loads(encode_hello(original))
    payload[field] = value
    mutated = public_env.decode_hello((json.dumps(payload) + "\n").encode())
    FakeEnvironmentTransport.hello = mutated
    monkeypatch.setattr(public_env, "JsonlChildProcess", FakeEnvironmentTransport)
    try:
        with pytest.raises(PublicEnvironmentError):
            PublicEnvironmentProcess(
                worker_python=Path("python3.12"), candidate_root=Path("candidate")
            )
    finally:
        FakeEnvironmentTransport.hello = original


def test_public_environment_client_does_not_import_private_engines() -> None:
    source = Path(public_env.__file__).read_text(encoding="utf-8")

    assert "import balatro_ai_v2.jackdaw" not in source
    assert "import balatro_ai_v2.balatrobot" not in source
