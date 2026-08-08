from __future__ import annotations

import sys

import pytest

from balatro_ai_v2.actions import action_to_data, iter_legal_actions
from balatro_ai_v2.baselines import DeterministicRandomPolicy
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.policy_process import PolicyProcess, PolicyProcessError
from state_factory import state


def test_actual_policy_child_returns_a_legal_public_action() -> None:
    observation = to_public_observation(state())

    with PolicyProcess("greedy", timeout_seconds=2) as policy:
        action = policy.choose_action(observation, lambda: iter_legal_actions(observation), ())

    assert action_to_data(action) == {"type": "select_blind"}
    assert policy.closed


def test_isolated_random_policy_preserves_full_public_history_length() -> None:
    blind = to_public_observation(state())
    hand = to_public_observation(state("SELECTING_HAND"))
    local = DeterministicRandomPolicy("same-seed")
    expected_first = local.choose_action(blind, lambda: iter_legal_actions(blind), ())
    history = (PublicHistoryStep(blind, expected_first, hand),)
    expected_second = local.choose_action(hand, lambda: iter_legal_actions(hand), history)

    with PolicyProcess("random", policy_seed="same-seed", timeout_seconds=2) as isolated:
        actual_first = isolated.choose_action(blind, lambda: iter_legal_actions(blind), ())
        actual_second = isolated.choose_action(hand, lambda: iter_legal_actions(hand), history)

    assert action_to_data(actual_first) == action_to_data(expected_first)
    assert action_to_data(actual_second) == action_to_data(expected_second)


def test_policy_child_timeout_fails_closed_and_stops_process() -> None:
    observation = to_public_observation(state())
    policy = PolicyProcess(
        "greedy",
        timeout_seconds=0.05,
        command=(sys.executable, "-c", "import time; time.sleep(60)"),
    )

    with pytest.raises(PolicyProcessError, match="timed out"):
        policy.choose_action(observation, lambda: iter_legal_actions(observation), ())

    assert policy.closed


@pytest.mark.parametrize(
    "program",
    [
        "import sys; sys.stdin.buffer.readline(); print('{}', flush=True)",
        "import sys; sys.stdin.buffer.readline(); sys.stdout.write('x' * 32001); sys.stdout.flush()",
        "import sys; sys.stdin.buffer.readline()",
    ],
)
def test_malformed_crashed_or_oversized_child_fails_closed(program: str) -> None:
    observation = to_public_observation(state())
    policy = PolicyProcess(
        "greedy",
        timeout_seconds=1,
        command=(sys.executable, "-c", program),
    )

    with pytest.raises(PolicyProcessError):
        policy.choose_action(observation, lambda: iter_legal_actions(observation), ())

    assert policy.closed


def test_policy_child_rejects_noncontiguous_parent_history() -> None:
    observation = to_public_observation(state())
    fake_history = (
        PublicHistoryStep(observation, next(iter_legal_actions(observation)), observation),
    )

    with PolicyProcess("greedy", timeout_seconds=2) as policy:
        with pytest.raises(PolicyProcessError, match="exited before responding"):
            policy.choose_action(
                observation,
                lambda: iter_legal_actions(observation),
                fake_history,
            )


@pytest.mark.parametrize("mutation", ["request_id", "digest", "action", "extra_stdout"])
def test_policy_process_rejects_stale_illegal_or_extra_response(mutation: str) -> None:
    observation = to_public_observation(state())
    program = """
import json, sys
request = json.loads(sys.stdin.buffer.readline())
mutation = sys.argv[1]
response = {
    "protocol": 1,
    "type": "action",
    "request_id": request["request_id"],
    "observation_digest": request["observation_digest"],
    "action": request["legal_actions"][0],
}
if mutation == "request_id": response["request_id"] += 1
if mutation == "digest": response["observation_digest"] = "stale"
if mutation == "action": response["action"] = {"type": "skip_pack"}
if mutation == "extra_stdout":
    sys.stdout.write(json.dumps(response) + "\\nextra\\n")
    sys.stdout.flush()
else:
    print(json.dumps(response), flush=True)
"""
    policy = PolicyProcess(
        "greedy",
        timeout_seconds=1,
        command=(sys.executable, "-c", program, mutation),
    )

    with pytest.raises(PolicyProcessError):
        policy.choose_action(observation, lambda: iter_legal_actions(observation), ())

    assert policy.closed
