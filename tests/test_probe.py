import json
from pathlib import Path

import pytest

from balatro_ai.probe import run_probes

CASES = Path(__file__).parent / "fixtures" / "decision_probes.json"


class Coach:
    model = "fake"
    reasoning_effort = "low"

    def __init__(self, *, fail=False):
        self.packets = []
        self.fail = fail

    def choose(self, packet, timeout):
        self.packets.append(packet)
        if self.fail:
            raise TimeoutError("no retry")
        cases = json.loads(CASES.read_text())
        return dict(
            request_id=packet["request_id"],
            plan="",
            action_json=json.dumps(cases[len(self.packets) - 1]["accepted_actions"][0]),
        )


def test_offline_preparation_never_calls_coach(tmp_path):
    coach = Coach()
    result = run_probes(CASES, tmp_path / "out", coach=coach)
    assert result["calls"] == 0
    assert not coach.packets
    assert (tmp_path / "out" / "packets.json").exists()


def test_bounded_calls_and_oracle_firewall(tmp_path):
    coach = Coach()
    result = run_probes(CASES, tmp_path / "out", max_calls=2, coach=coach)
    assert result["calls"] == result["passed"] == len(coach.packets) == 2
    for packet in coach.packets:
        assert set(packet) == {
            "request_id",
            "instructions",
            "plan",
            "validation_feedback",
            "observation",
            "analysis",
            "recent_outcomes",
        }
        assert "accepted_actions" not in json.dumps(packet)
        assert "seed" not in packet["observation"]


def test_timeout_recorded_once_without_retry(tmp_path):
    coach = Coach(fail=True)
    result = run_probes(CASES, tmp_path / "out", max_calls=1, coach=coach)
    assert result["failed"] == len(coach.packets) == 1
    assert result["results"][0]["status"] == "error"
    assert json.loads((tmp_path / "out" / "result.json").read_text()) == result


@pytest.mark.parametrize("calls", [-1, 9])
def test_invalid_budget_rejected_before_output(tmp_path, calls):
    with pytest.raises(ValueError):
        run_probes(CASES, tmp_path / "out", max_calls=calls)
    assert not (tmp_path / "out").exists()


def test_refuses_to_overwrite_evidence(tmp_path):
    with pytest.raises(FileExistsError):
        run_probes(CASES, tmp_path)


@pytest.mark.parametrize(
    "action,status",
    [
        ({"type": "play_cards", "cards": [1]}, "failed"),
        ({"type": "leave_shop"}, "error"),
    ],
)
def test_legal_wrong_and_illegal_decisions_fail(tmp_path, action, status):
    class WrongCoach:
        def choose(self, packet, timeout):
            return dict(request_id=packet["request_id"], plan="", action_json=json.dumps(action))

    result = run_probes(CASES, tmp_path / "out", max_calls=1, coach=WrongCoach())
    assert result["passed"] == 0 and result["failed"] == 1
    assert result["results"][0]["status"] == status
