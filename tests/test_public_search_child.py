from __future__ import annotations

import sys

from balatro_ai_v2.actions import iter_legal_actions
from balatro_ai_v2.backend import RunSpec
from balatro_ai_v2.jackdaw import JackdawBackend
from balatro_ai_v2.policy_process import PolicyProcess


def _command() -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "balatro_ai_v2.public_search_child",
        "--continuation",
        "strategic",
        "--policy-nonce",
        "isolated-public-test",
        "--samples",
        "1",
        "--max-steps",
        "80",
    )


def test_public_search_child_computes_repeatable_legal_online_action() -> None:
    backend = JackdawBackend()
    backend.reset(RunSpec("RED", "WHITE", "authority-hidden-from-child"))
    observation = backend.current_public
    assert observation is not None
    try:
        with PolicyProcess(
            "custom-public-search",
            command=_command(),
            timeout_seconds=30,
        ) as process:
            first = process.choose_action(
                observation,
                lambda: iter_legal_actions(observation),
                (),
            )
            second = process.choose_action(
                observation,
                lambda: iter_legal_actions(observation),
                (),
            )
        assert first == second
        assert first in tuple(iter_legal_actions(observation))
        assert "authority-hidden-from-child" not in _command()
    finally:
        backend.close()
