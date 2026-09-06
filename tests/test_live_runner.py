import json
from pathlib import Path

import pytest

from balatro_ai_v2.actions import ActionKind, GameAction
from balatro_ai_v2.live.policy import Decision
from balatro_ai_v2.live.runner import RunConfig, replay, run_batch, run_episode, summarize


def snapshot(phase="SELECTING_HAND", *, chips=0, won=False, ante=1, **extra):
    return {"state": phase, "seed": "TEST", "deck": "RED", "stake": "WHITE",
            "won": won, "ante_num": ante, "round_num": 1,
            "round": {"chips": chips, "hands_left": 4}, "jokers": {"cards": []},
            "blinds": {"small": {"status": "CURRENT", "name": "Small Blind", "score": 300}},
            **extra}


class ScriptedClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def rpc(self, method, params=None):
        self.calls.append((method, params or {}))
        expected, response = next(self.replies)
        assert method == expected
        if isinstance(response, BaseException):
            raise response
        return response


class PlayPolicy:
    def choose(self, state):
        assert "seed" not in state and "cards" not in state
        return Decision(GameAction(ActionKind.PLAY, indices=(0,)), "test", predicted_score=20)


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_episode_records_true_loss_and_observed_score_without_private_information(tmp_path):
    trace = tmp_path / "run.jsonl"
    client = ScriptedClient([
        ("start", snapshot(cards={"cards": [{"key": "SECRET"}]})),
        ("play", snapshot("GAME_OVER", chips="1.2e2")),
    ])
    result = run_episode(client, PlayPolicy(), "TEST", trace, RunConfig())
    assert result["status"] == "lost"
    assert result["peak_hand_score"] == 120
    assert result["final_context"]["required_score"] == 300
    events = records(trace)
    decision = next(e for e in events if e["event"] == "decision")
    transition = next(e for e in events if e["event"] == "transition")
    assert "seed" not in decision["observation"]
    assert "SECRET" not in trace.read_text()
    assert transition["prediction_error"] == 100
    assert replay(trace, PlayPolicy()) == {
        "decisions": 1, "matching": 1, "complete_trace": True, "differences": [],
    }


def test_victory_stops_before_endless_even_when_phase_is_not_game_over(tmp_path):
    client = ScriptedClient([
        ("start", snapshot(ante=8)), ("play", snapshot("ROUND_EVAL", chips=120000, won=True, ante=9)),
    ])
    result = run_episode(client, PlayPolicy(), "TEST", tmp_path / "run.jsonl", RunConfig())
    assert result["status"] == "won"
    assert result["reason"] == "ante_8_cleared"
    assert len(client.calls) == 2


def test_final_boss_loss_with_premature_native_win_flag_is_a_loss(tmp_path):
    path = tmp_path / "run.jsonl"
    client = ScriptedClient([
        ("start", snapshot(ante=8)),
        ("play", snapshot("GAME_OVER", chips=79040, won=True, ante=8)),
    ])
    result = run_episode(client, PlayPolicy(), "TEST", path, RunConfig())
    assert result["status"] == "lost" and result["won"] is False
    after = next(e["observation"] for e in records(path) if e["event"] == "transition")
    assert after["reported_won"] is True and after["won"] is False


def test_endless_death_keeps_ante_eight_victory(tmp_path):
    client = ScriptedClient([
        ("start", snapshot(ante=9, won=True)),
        ("play", snapshot("GAME_OVER", chips=200, won=True, ante=9)),
    ])
    result = run_episode(client, PlayPolicy(), "TEST", tmp_path / "run.jsonl", RunConfig(endless=True))
    assert result["status"] == "won" and result["won"]
    assert result["ante_reached"] == 9


@pytest.mark.parametrize("error", [TimeoutError("unknown action outcome"), RuntimeError("card not allowed")])
def test_failed_mutation_is_logged_before_rpc_and_never_retried(tmp_path, error):
    path = tmp_path / "run.jsonl"
    client = ScriptedClient([("start", snapshot()), ("play", error)])
    result = run_episode(client, PlayPolicy(), "TEST", path, RunConfig())
    assert result["status"] == "error"
    assert len(client.calls) == 2
    events = records(path)
    assert [e["event"] for e in events][-3:] == ["decision", "error", "result"]
    assert events[-3]["action"] == {"method": "play", "params": {"cards": [0]}}


def test_decision_limit_is_not_counted_as_a_loss(tmp_path):
    client = ScriptedClient([("start", snapshot()), ("play", snapshot(chips=10))])
    result = run_episode(client, PlayPolicy(), "TEST", tmp_path / "run.jsonl", RunConfig(max_decisions=1))
    assert result["status"] == "truncated"
    summary = summarize([result], 1)
    assert summary["win_rate_attempted"] == 0
    assert summary["win_rate_completed"] is None
    assert summary["completed_peak_hand_score"]["count"] == 0


def test_transitional_states_are_polled_with_a_bound(tmp_path):
    client = ScriptedClient([
        ("start", snapshot("DRAW_TO_HAND")), ("gamestate", snapshot()),
        ("play", snapshot("HAND_PLAYED")), ("gamestate", snapshot("GAME_OVER", chips=30)),
    ])
    result = run_episode(client, PlayPolicy(), "TEST", tmp_path / "run.jsonl", RunConfig(poll_interval=0))
    assert result["status"] == "lost"
    assert result["peak_hand_score"] == 30


def test_stalled_transition_becomes_error(tmp_path):
    client = ScriptedClient([
        ("start", snapshot("DRAW_TO_HAND")), ("gamestate", snapshot("DRAW_TO_HAND")),
    ])
    result = run_episode(client, PlayPolicy(), "TEST", tmp_path / "run.jsonl",
                         RunConfig(poll_interval=0, settle_polls=1))
    assert result["status"] == "error"
    assert "did not settle" in result["reason"]


def test_last_allowed_poll_can_reach_a_valid_state(tmp_path):
    client = ScriptedClient([
        ("start", snapshot("DRAW_TO_HAND")), ("gamestate", snapshot()),
        ("play", snapshot("GAME_OVER")),
    ])
    result = run_episode(client, PlayPolicy(), "TEST", tmp_path / "run.jsonl",
                         RunConfig(poll_interval=0, settle_polls=1))
    assert result["status"] == "lost"


def test_interrupt_is_recorded_as_truncation(tmp_path):
    path = tmp_path / "run.jsonl"
    client = ScriptedClient([("start", snapshot()), ("play", KeyboardInterrupt())])
    result = run_episode(client, PlayPolicy(), "TEST", path, RunConfig())
    assert result["status"] == "truncated" and result["reason"] == "interrupted"
    assert records(path)[-1]["event"] == "result"


def test_seed_mismatch_prevents_play(tmp_path):
    client = ScriptedClient([("start", snapshot(seed="WRONG"))])
    result = run_episode(client, PlayPolicy(), "TEST", tmp_path / "run.jsonl", RunConfig())
    assert result["status"] == "error"
    assert "requested seed" in result["reason"]
    assert len(client.calls) == 1


def test_batch_does_not_replace_active_game_by_default(tmp_path):
    client = ScriptedClient([("health", {"status": "ok"}), ("gamestate", snapshot())])
    with pytest.raises(RuntimeError, match="active"):
        run_batch(client, ["TEST"], tmp_path / "batch", RunConfig())
    assert len(client.calls) == 2
    assert not (tmp_path / "batch").exists()


def test_batch_rejects_a_different_unlock_profile_before_starting(tmp_path):
    client = ScriptedClient([("health", {"status": "ok", "profile_mode": "career"})])
    with pytest.raises(RuntimeError, match="profile"):
        run_batch(client, ["TEST"], tmp_path / "batch", RunConfig(expected_profile="all_unlocked"))
    assert len(client.calls) == 1


def test_batch_error_preserves_game_and_reports_unattempted_seeds(tmp_path):
    client = ScriptedClient([
        ("health", {"status": "ok"}), ("gamestate", {"state": "MENU"}),
        ("start", RuntimeError("cannot start")),
    ])
    summary = run_batch(client, ["TEST", "OTHER"], tmp_path / "batch", RunConfig(), progress=lambda _: None)
    assert summary["status_counts"] == {"error": 1}
    assert summary["attempted"] == summary["not_attempted"] == 1
    persisted = json.loads((tmp_path / "batch" / "summary.json").read_text())
    assert persisted == summary
    assert json.loads((tmp_path / "batch" / "manifest.json").read_text())["seeds"] == ["TEST", "OTHER"]


def test_existing_output_is_not_overwritten(tmp_path):
    client = ScriptedClient([("health", {"status": "ok"}), ("gamestate", {"state": "MENU"})])
    with pytest.raises(FileExistsError):
        run_batch(client, ["TEST"], tmp_path, RunConfig())


def test_replay_reports_differences_without_running_game(tmp_path):
    path = tmp_path / "run.jsonl"
    client = ScriptedClient([("start", snapshot()), ("play", snapshot("GAME_OVER"))])
    run_episode(client, PlayPolicy(), "TEST", path, RunConfig())

    class ChangedPolicy:
        def choose(self, state):
            return Decision(GameAction(ActionKind.DISCARD, indices=(0,)), "different")

    result = replay(path, ChangedPolicy())
    assert result["matching"] == 0
    assert result["differences"][0]["current"]["method"] == "discard"


def test_no_progress_loop_is_bounded(tmp_path):
    client = ScriptedClient([("start", snapshot())] + [("play", snapshot())] * 3)
    result = run_episode(client, PlayPolicy(), "TEST", tmp_path / "run.jsonl", RunConfig())
    assert result["status"] == "error" and result["decisions"] == 3
    assert "unchanged" in result["reason"]


def test_replay_recovers_complete_decisions_before_partial_tail(tmp_path):
    path = tmp_path / "partial.jsonl"
    event = {"event": "decision", "index": 0, "observation": snapshot(),
             "action": {"method": "play", "params": {"cards": [0]}}}
    path.write_text(json.dumps(event) + '\n{"event": "trans', encoding="utf-8")
    result = replay(path, PlayPolicy())
    assert result["matching"] == 1
    assert result["complete_trace"] is False
    assert "incomplete" in result["warning"]
    path.write_text('{broken}\n', encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        replay(path, PlayPolicy())
