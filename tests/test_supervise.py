import json

from balatro_ai.client import BalatroBotError
from balatro_ai.supervise import classify, default_save_file, supervise


class FakeClient:
    """Scripted BalatroBot: states are popped per call, the last one sticks."""

    def __init__(self, states=("SHOP",), healthy=True):
        self.states = list(states)
        self.healthy = healthy
        self.calls = []
        self.loaded = None

    def rpc(self, method, params=None):
        self.calls.append((method, params))
        if not self.healthy:
            raise BalatroBotError("failed to connect to BalatroBot")
        if method == "load":
            self.loaded = params["path"]
            self.states = ["SHOP"]
            return {}
        if method == "health":
            return {"profile_mode": "all_unlocked"}
        state = self.states[0] if len(self.states) == 1 else self.states.pop(0)
        return {"state": state}


class FakeRunner:
    """Returns one scripted result per segment and leaves a trajectory behind."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, directory, resume):
        self.calls.append((directory.name, resume.name if resume else None))
        directory.mkdir(parents=True, exist_ok=False)
        (directory / "trajectory.jsonl").write_text(json.dumps({"event": "transition"}) + "\n")
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        if result is not None:
            (directory / "result.json").write_text(json.dumps(result))
        return result


WON = dict(status="won", reason="ante_8_cleared", won=True, decisions=90)
ERROR = dict(status="error", reason="BalatroBotError: request timed out")


def run(tmp_path, results, states=("SHOP",), save_file=None, **kwargs):
    """Drive the supervisor with fakes only; no real game, server or Codex."""

    client = FakeClient(states)
    runner = FakeRunner(results)
    logs = []
    summary = supervise(
        tmp_path / "game",
        runner=runner,
        client_factory=lambda: client,
        sleep=lambda _: None,
        log=logs.append,
        # Never fall back to this machine's real Balatro autosave.
        save_file=save_file or tmp_path / "no-such-save.jkr",
        **kwargs,
    )
    return summary, runner, client, logs


def test_a_clean_win_stops_after_one_segment(tmp_path):
    summary, runner, _, logs = run(tmp_path, [WON], states=["MENU", "SHOP"])
    assert runner.calls == [("segment-00", None)]
    assert summary["status"] == "won" and summary["restarts"] == 0
    assert len(summary["segments"]) == 1
    assert any("the game finished" in line for line in logs)


def test_an_error_is_resumed_and_recorded(tmp_path):
    summary, runner, _, _ = run(tmp_path, [ERROR, WON], states=["MENU", "SHOP"])
    assert runner.calls == [("segment-00", None), ("segment-01", "segment-00")]
    assert summary["status"] == "won" and summary["restarts"] == 1
    state = json.loads((tmp_path / "game/supervisor.json").read_text())
    assert [s["disposition"] for s in state["segments"]] == ["recoverable", "finished"]
    assert state["segments"][1]["resumed_from"] == "segment-00"
    assert state["segments"][0]["reason"] == ERROR["reason"]
    assert state["restarts"] == 1 and state["stopped"] is True
    assert state["segments"][0]["started_at"] and state["updated_at"]
    # The root mirrors the latest segment so `balatro inspect DIR` reads the game.
    assert json.loads((tmp_path / "game/result.json").read_text())["status"] == "won"
    assert json.loads((tmp_path / "game/summary.json").read_text())["restarts"] == 1


def test_a_dead_process_is_restored_from_the_save_file(tmp_path):
    save = tmp_path / "save.jkr"
    save.write_text("autosave")
    summary, runner, client, logs = run(
        tmp_path,
        [None, dict(status="lost", reason="game_over")],
        states=["MENU", "MENU", "SHOP"],
        save_file=save,
    )
    assert client.loaded == str(save)
    assert runner.calls == [("segment-00", None), ("segment-01", "segment-00")]
    assert summary["status"] == "lost" and summary["restarts"] == 1
    assert summary["segments"][0]["reason"] == "the runner wrote no result"
    assert any("restoring the autosaved run" in line for line in logs)


def test_menu_without_a_save_file_stops(tmp_path):
    summary, runner, client, _ = run(tmp_path, [ERROR], states=["MENU", "MENU"])
    assert len(runner.calls) == 1 and client.loaded is None
    assert "at MENU and no save file" in summary["stop_reason"]


def test_a_crash_that_raises_is_recoverable(tmp_path):
    summary, runner, _, logs = run(tmp_path, [RuntimeError("killed"), WON], states=["MENU", "SHOP"])
    assert len(runner.calls) == 2 and summary["status"] == "won"
    assert any("the runner raised RuntimeError: killed" in line for line in logs)


def test_an_unreachable_server_is_relaunched(tmp_path):
    client = FakeClient(["MENU", "SHOP"])
    runner = FakeRunner([ERROR, WON])
    launched = []

    def launcher(command, log_path):
        launched.append((command, log_path.name))
        client.healthy = True
        return object()

    def sleep(_):
        client.healthy = False  # the server dies while the supervisor backs off

    summary = supervise(
        tmp_path / "game",
        runner=runner,
        client_factory=lambda: client,
        sleep=sleep,
        log=lambda _: None,
        launcher=launcher,
        server_command="start-balatro",
        save_file=tmp_path / "no-such-save.jkr",
    )
    assert launched == [("start-balatro", "server.log")]
    assert "health" in [method for method, _ in client.calls]
    assert summary["status"] == "won" and len(runner.calls) == 2


def test_a_codex_login_failure_stops_without_restarting(tmp_path):
    login = dict(status="error", reason="RuntimeError: Codex CLI must be logged in using ChatGPT")
    summary, runner, _, _ = run(tmp_path, [login, WON], states=["MENU", "SHOP"])
    assert len(runner.calls) == 1 and summary["restarts"] == 0
    assert "log in again" in summary["stop_reason"]
    assert classify(login)[0] == "login"


def test_the_restart_cap_is_respected(tmp_path):
    summary, runner, _, _ = run(tmp_path, [ERROR] * 4, states=["MENU", "SHOP"], max_restarts=2)
    assert len(runner.calls) == 3 and summary["restarts"] == 2
    assert "restart limit of 2" in summary["stop_reason"]


def test_budget_exhaustion_stops(tmp_path):
    for reason in ("action_limit", "coach_call_limit", "game time limit reached"):
        summary, runner, _, _ = run(
            tmp_path / reason.replace(" ", "-"),
            [dict(status="stopped", reason=reason), WON],
            states=["MENU", "SHOP"],
        )
        assert len(runner.calls) == 1
        assert summary["stop_reason"] == f"the run budget is spent: {reason}"


def test_an_interrupted_runner_stops(tmp_path):
    summary, runner, _, _ = run(
        tmp_path, [dict(status="stopped", reason="interrupted"), WON], states=["MENU", "SHOP"]
    )
    assert len(runner.calls) == 1 and summary["stop_reason"] == "the runner was interrupted"


def test_a_fresh_game_needs_an_idle_table(tmp_path):
    summary, runner, _, _ = run(tmp_path, [WON], states=["SHOP"])
    assert runner.calls == [] and "idle at MENU, found SHOP" in summary["stop_reason"]


def test_a_game_that_ended_while_away_stops(tmp_path):
    summary, runner, _, _ = run(tmp_path, [ERROR, WON], states=["MENU", "GAME_OVER"])
    assert len(runner.calls) == 1
    assert summary["stop_reason"] == "the game ended while the supervisor was away"


def test_a_restarted_supervisor_continues_the_existing_segments(tmp_path):
    run(tmp_path, [ERROR], states=["MENU", "MENU"])
    summary, runner, _, _ = run(tmp_path, [WON], states=["SHOP"])
    assert runner.calls == [("segment-01", "segment-00")]
    assert summary["status"] == "won"


def test_ctrl_c_in_the_supervisor_leaves_the_game_alone(tmp_path):
    summary, runner, client, _ = run(tmp_path, [KeyboardInterrupt()], states=["MENU", "SHOP"])
    assert "interrupted" in summary["stop_reason"]
    assert [method for method, _ in client.calls] == ["gamestate"]


def test_the_default_save_file_is_the_platform_autosave():
    save = default_save_file(home="/home/player")
    assert save.name == "save.jkr" and save.parent.name == "1"
    assert "Balatro" in str(save)
