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
