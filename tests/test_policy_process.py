from __future__ import annotations

import sys

import pytest

from balatro_ai_v2.actions import action_to_data, iter_legal_actions
from balatro_ai_v2.baselines import DeterministicRandomPolicy
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.policy_process import PolicyProcess, PolicyProcessError
from balatro_ai_v2.policy_wire import POLICY_PROTOCOL_VERSION
from balatro_ai_v2.strategy_tuning import StrategyTuning
from state_factory import item_card, playing_card, state


def test_actual_policy_child_returns_a_legal_public_action() -> None:
    observation = to_public_observation(state())

    with PolicyProcess("greedy", timeout_seconds=2) as policy:
        action = policy.choose_action(observation, lambda: iter_legal_actions(observation), ())

    assert action_to_data(action) == {"type": "select_blind"}
    assert policy.closed


def test_explicit_tuning_reaches_isolated_policy_and_changes_decision() -> None:
    raw = state("SHOP", money=8)
    raw["ante_num"] = 1
    raw["shop"]["cards"] = [item_card("j_green_joker", card_id=20, kind="JOKER", buy=4)]
    raw["shop"]["count"] = 1
    raw["jokers"]["cards"] = [
        item_card("j_joker", card_id=40, kind="JOKER"),
        item_card("j_sly", card_id=41, kind="JOKER"),
    ]
    raw["jokers"]["count"] = 2
    raw["vouchers"]["cards"] = []
    raw["vouchers"]["count"] = 0
    raw["packs"]["cards"] = []
    raw["packs"]["count"] = 0
    observation = to_public_observation(raw)

    with PolicyProcess("strategic", timeout_seconds=2) as default_policy:
        default_action = default_policy.choose_action(
            observation, lambda: iter_legal_actions(observation), ()
        )
    with PolicyProcess(
        "strategic",
        timeout_seconds=2,
        tuning=StrategyTuning(reserve_ante_1=100),
    ) as tuned_policy:
        tuned_action = tuned_policy.choose_action(
            observation, lambda: iter_legal_actions(observation), ()
        )

    assert action_to_data(default_action)["type"] == "buy_shop_card"
    assert action_to_data(tuned_action) == {"type": "leave_shop"}


def test_policy_transport_covers_normal_eight_card_tactical_actions() -> None:
    raw = state("SELECTING_HAND")
    raw["hand"]["cards"].extend(
        playing_card(key, card_id=index)
        for index, key in enumerate(("S_A", "H_K", "D_Q", "C_J", "S_9"), 40)
    )
    raw["hand"]["count"] = 8
    observation = to_public_observation(raw)

    with PolicyProcess("greedy", timeout_seconds=2) as policy:
        action = policy.choose_action(observation, lambda: iter_legal_actions(observation), ())

    assert action_to_data(action)["type"] == "play_cards"


def test_policy_transport_factorizes_large_tactical_action_sets() -> None:
    raw = state("SELECTING_HAND")
    raw["hand"]["cards"].extend(
        playing_card(key, card_id=index)
        for index, key in enumerate(("S_A", "H_K", "D_Q", "C_J", "S_9", "H_8"), 40)
    )
    raw["hand"]["count"] = 9
    observation = to_public_observation(raw)
    assert len(tuple(iter_legal_actions(observation))) > 512

    with PolicyProcess("greedy", timeout_seconds=2) as policy:
        action = policy.choose_action(
            observation,
            lambda: iter_legal_actions(observation),
            (),
        )

    assert action_to_data(action)["type"] == "play_cards"


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


def test_policy_process_retains_and_resets_typed_diagnostic_counters() -> None:
    observation = to_public_observation(state())
    program = """
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    root = request["history_length"] == 0
    response = {
        "protocol": %d,
        "type": "action",
        "request_id": request["request_id"],
        "observation_digest": request["observation_digest"],
        "action": {"type": "select_blind"},
        "diagnostics": {
            "exact_blind": {
                "attempted": root,
                "completed": root,
                "changed": root,
                "incomplete_reason": None,
            },
            "preboss": {
                "attempted": not root,
                "completed": not root,
                "changed": False,
                "incomplete_reason": None,
            },
        },
    }
    print(json.dumps(response), flush=True)
""" % POLICY_PROTOCOL_VERSION
    step = PublicHistoryStep(observation, next(iter_legal_actions(observation)), observation)

    with PolicyProcess("greedy", timeout_seconds=2, command=(sys.executable, "-c", program)) as policy:
        policy.choose_action(observation, lambda: iter_legal_actions(observation), ())
        assert policy.last_response_diagnostics.exact_blind.changed
        assert policy.run_diagnostic_counters.exact_blind.changed == 1
        policy.choose_action(observation, lambda: iter_legal_actions(observation), (step,))
        assert policy.run_diagnostic_counters.preboss.attempted == 1
        policy.choose_action(observation, lambda: iter_legal_actions(observation), ())
        assert policy.run_diagnostic_counters.exact_blind == policy.run_diagnostic_counters.preboss.__class__(
            attempted=1,
            completed=1,
            changed=1,
        )
        assert policy.run_diagnostic_counters.preboss == policy.run_diagnostic_counters.preboss.__class__()


def test_policy_process_counts_incomplete_reasons() -> None:
    observation = to_public_observation(state())
    program = """
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    response = {
        "protocol": %d,
        "type": "action",
        "request_id": request["request_id"],
        "observation_digest": request["observation_digest"],
        "action": {"type": "select_blind"},
        "diagnostics": {
            "exact_blind": {
                "attempted": True,
                "completed": False,
                "changed": False,
                "incomplete_reason": "decision_horizon",
            },
            "preboss": {
                "attempted": False,
                "completed": False,
                "changed": False,
                "incomplete_reason": None,
            },
        },
    }
    print(json.dumps(response), flush=True)
""" % POLICY_PROTOCOL_VERSION

    with PolicyProcess("greedy", timeout_seconds=2, command=(sys.executable, "-c", program)) as policy:
        policy.choose_action(observation, lambda: iter_legal_actions(observation), ())

        assert policy.run_diagnostic_counters.exact_blind.incomplete == 1
        assert policy.run_diagnostic_counters.exact_blind.incomplete_reasons == (
            ("decision_horizon", 1),
        )


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


def test_custom_policy_command_rejects_nondefault_tuning() -> None:
    with pytest.raises(ValueError, match="custom policy commands"):
        PolicyProcess(
            "strategic",
            command=(sys.executable, "-c", "pass"),
            tuning=StrategyTuning(reserve_ante_1=100),
        )


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
    "protocol": %d,
    "type": "action",
    "request_id": request["request_id"],
    "observation_digest": request["observation_digest"],
    "action": {"type": "select_blind"},
}
if mutation == "request_id": response["request_id"] += 1
if mutation == "digest": response["observation_digest"] = "stale"
if mutation == "action": response["action"] = {"type": "skip_pack"}
if mutation == "extra_stdout":
    sys.stdout.write(json.dumps(response) + "\\nextra\\n")
    sys.stdout.flush()
else:
    print(json.dumps(response), flush=True)
""" % POLICY_PROTOCOL_VERSION
    policy = PolicyProcess(
        "greedy",
        timeout_seconds=1,
        command=(sys.executable, "-c", program, mutation),
    )

    with pytest.raises(PolicyProcessError):
        policy.choose_action(observation, lambda: iter_legal_actions(observation), ())

    assert policy.closed
