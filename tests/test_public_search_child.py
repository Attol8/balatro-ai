from __future__ import annotations

import json
import sys
from pathlib import Path

from balatro_ai_v2.actions import iter_legal_actions
from balatro_ai_v2.backend import RunSpec
from balatro_ai_v2.jackdaw import JackdawBackend
from balatro_ai_v2.policy_process import PolicyProcess


def _command(*extra: str) -> tuple[str, ...]:
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
        *extra,
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
        assert process.run_diagnostic_counters.public_root.completed == 1
    finally:
        backend.close()


def test_public_search_decision_log_contains_only_bounded_public_diagnostics(
    tmp_path: Path,
) -> None:
    backend = JackdawBackend()
    backend.reset(RunSpec("RED", "WHITE", "authority-secret-not-logged"))
    observation = backend.current_public
    assert observation is not None
    path = tmp_path / "public-decisions.jsonl"
    try:
        with PolicyProcess(
            "custom-public-search",
            command=_command("--decision-log", str(path)),
            timeout_seconds=30,
        ) as process:
            process.choose_action(
                observation,
                lambda: iter_legal_actions(observation),
                (),
            )
    finally:
        backend.close()

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert set(rows[0]) == {
        "ante",
        "baseline",
        "changed",
        "phase",
        "rejected_rollouts",
        "rejection_reasons",
        "roots",
        "samples",
        "selected",
        "steps",
        "unavailable_reason",
    }
    serialized = json.dumps(rows[0], sort_keys=True)
    for forbidden in ("authority-secret-not-logged", "seed", "raw", "private"):
        assert forbidden not in serialized
