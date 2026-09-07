import json
from pathlib import Path

import pytest

from balatro_ai.cli import main


def test_inspect_is_offline(capsys):
    assert main(["inspect", str(Path(__file__).parents[1] / "evidence/first-win")]) == 0
    assert json.loads(capsys.readouterr().out)["won"] is True


def test_bad_seed_cannot_start_game(tmp_path):
    with pytest.raises(SystemExit) as caught:
        main(["play", "--output", str(tmp_path / "run"), "--seed", "not valid"])
    assert caught.value.code == 1 and not (tmp_path / "run").exists()


def test_default_limits_cover_an_endless_game(tmp_path, monkeypatch):
    captured = {}

    def run_game(client, coach, output, *, limits, **kwargs):
        captured["limits"] = limits
        return dict(status="won")

    monkeypatch.setattr("balatro_ai.cli.run_game", run_game)
    monkeypatch.setattr("balatro_ai.cli.BalatroBotClient", lambda port: object())
    monkeypatch.setattr("balatro_ai.coach.CodexCoach", lambda: object())
    assert main(["play", "--output", str(tmp_path / "run")]) == 0
    limits = captured["limits"]
    assert (limits.max_calls, limits.max_actions) == (450, 750)
    assert (limits.seconds, limits.call_seconds) == (7200, 60)


def test_doctor_read_only(monkeypatch, capsys):
    from types import SimpleNamespace

    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="Logged in using ChatGPT", stderr="")

    monkeypatch.setattr("balatro_ai.cli.subprocess.run", run)
    calls = []

    def rpc(self, method, params=None):
        calls.append(method)
        return {"profile_mode": "all_unlocked"} if method == "health" else {"state": "MENU"}

    monkeypatch.setattr("balatro_ai.cli.BalatroBotClient.rpc", rpc)
    assert main(["doctor"]) == 0
    assert calls == ["health", "gamestate"]
    assert commands == [["codex", "--version"], ["codex", "login", "status"]]
    assert json.loads(capsys.readouterr().out)["game"]["ok"]


def _resume_dir(tmp_path, observation, seed, *, status="stopped"):
    run = tmp_path / "previous"
    run.mkdir(parents=True)
    transition = dict(
        event="transition",
        before=observation,
        action={"type": "select_blind"},
        after=observation,
        source="coach",
    )
    rows = [
        dict(event="coach_response", response={"plan": "Carried plan."}, plan_unchanged=False),
        transition,
        transition,
    ]
    (run / "trajectory.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    (run / "result.json").write_text(
        json.dumps(
            dict(
                status=status,
                reason="Codex CLI timed out",
                decisions=4,
                coach_requests=7,
                coach_timeouts=1,
                forced_actions=2,
                followup_actions=3,
                seconds=120,
                peak_hand_score=33,
            )
        )
    )
    (run / "manifest.json").write_text(json.dumps(dict(seed=seed)))
    return run


def _paused_game(monkeypatch):
    from balatro_ai.game.codec import public_observation_to_data
    from balatro_ai.runner import public_state
    from tests.test_runner import Coach, Game

    game = Game(active=True)
    monkeypatch.setattr("balatro_ai.runner.time.sleep", lambda _: None)
    monkeypatch.setattr("balatro_ai.runner.fcntl.flock", lambda *_: None)
    monkeypatch.setattr("balatro_ai.cli.BalatroBotClient", lambda port: game)
    monkeypatch.setattr("balatro_ai.coach.CodexCoach", Coach)
    return game, public_observation_to_data(public_state(game.raw))


def test_resume_carries_counters_and_plan_forward(tmp_path, monkeypatch):
    game, observation = _paused_game(monkeypatch)
    previous = _resume_dir(tmp_path, observation, game.raw["seed"])
    assert main(["play", "--output", str(tmp_path / "run"), "--resume", str(previous)]) == 0
    result = json.loads((tmp_path / "run/result.json").read_text())
    assert result["status"] == "won"
    assert result["decisions"] == 5 and result["coach_requests"] == 8
    assert result["forced_actions"] == 2 and result["followup_actions"] == 3
    assert result["coach_timeouts"] == 1 and result["seconds"] >= 120
    manifest = json.loads((tmp_path / "run/manifest.json").read_text())
    assert manifest["continuation_of"] == str(previous)
    assert manifest["resume_adjusted"] is False and manifest["resume_diff"] == []
    assert manifest["seed"] == game.raw["seed"]
    assert "start" not in game.calls


def test_resume_adopts_a_live_state_that_moved_on(tmp_path, monkeypatch):
    game, observation = _paused_game(monkeypatch)
    previous = _resume_dir(tmp_path, observation, game.raw["seed"])
    game.raw["money"] += 1
    assert main(["play", "--output", str(tmp_path / "run"), "--resume", str(previous)]) == 0
    manifest = json.loads((tmp_path / "run/manifest.json").read_text())
    assert manifest["resume_adjusted"] is True and manifest["resume_diff"] == ["money"]
    assert json.loads((tmp_path / "run/result.json").read_text())["status"] == "won"


def test_resume_refuses_a_menu_or_finished_game(tmp_path, monkeypatch):
    game, observation = _paused_game(monkeypatch)
    previous = _resume_dir(tmp_path, observation, game.raw["seed"], status="won")
    with pytest.raises(SystemExit) as caught:
        main(["play", "--output", str(tmp_path / "run"), "--resume", str(previous)])
    assert caught.value.code == 1 and not (tmp_path / "run").exists()
    game.active = False
    finished = _resume_dir(tmp_path / "menu", observation, game.raw["seed"])
    with pytest.raises(SystemExit) as caught:
        main(["play", "--output", str(tmp_path / "run"), "--resume", str(finished)])
    assert caught.value.code == 1 and not (tmp_path / "run").exists()


def test_resume_and_seed_are_mutually_exclusive(tmp_path, capsys):
    with pytest.raises(SystemExit) as caught:
        main(
            [
                "play",
                "--output",
                str(tmp_path / "run"),
                "--resume",
                str(tmp_path),
                "--seed",
                "ABCD",
            ]
        )
    assert caught.value.code == 1 and not (tmp_path / "run").exists()
    assert "drop --seed" in capsys.readouterr().err


def test_supervise_help_lists_the_operator_options(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["supervise", "--help"])
    assert caught.value.code == 0
    help_text = capsys.readouterr().out
    for option in (
        "--output",
        "--seed",
        "--endless",
        "--port",
        "--max-calls",
        "--max-actions",
        "--seconds",
        "--call-seconds",
        "--max-restarts",
        "--server-command",
        "--save-file",
    ):
        assert option in help_text


def test_supervise_validates_the_seed_before_touching_anything(tmp_path):
    with pytest.raises(SystemExit) as caught:
        main(["supervise", "--output", str(tmp_path / "game"), "--seed", "not valid"])
    assert caught.value.code == 1 and not (tmp_path / "game").exists()


def test_supervise_passes_the_operator_settings_through(tmp_path, monkeypatch):
    captured = {}

    def supervise(output, **kwargs):
        captured.update(kwargs, output=output)
        return dict(status="won", segments=[], restarts=2)

    monkeypatch.setattr("balatro_ai.supervise.supervise", supervise)
    assert (
        main(
            [
                "supervise",
                "--output",
                str(tmp_path / "game"),
                "--seed",
                "ABCD1234",
                "--endless",
                "--max-restarts",
                "3",
                "--server-command",
                "start-balatro",
                "--save-file",
                str(tmp_path / "save.jkr"),
            ]
        )
        == 0
    )
    assert captured["seed"] == "ABCD1234" and captured["endless"] is True
    assert captured["max_restarts"] == 3 and captured["server_command"] == "start-balatro"
    assert captured["save_file"] == tmp_path / "save.jkr"
    assert (captured["limits"].max_calls, captured["limits"].max_actions) == (450, 750)
