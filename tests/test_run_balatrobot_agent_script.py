from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_balatrobot_agent.py"
    spec = importlib.util.spec_from_file_location("run_balatrobot_agent_script", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_launch_command_adds_fast_balatrobot_settings() -> None:
    script = _load_script()

    command = script.build_launch_command("uvx balatrobot serve", host="127.0.0.1", port=12346, fast_server=True)

    assert command == [
        "uvx",
        "balatrobot",
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        "12346",
        "--headless",
        "--fast",
        "--no-shaders",
        "--gamespeed",
        "10",
        "--animation-fps",
        "60",
    ]


def test_build_launch_command_can_leave_server_settings_alone() -> None:
    script = _load_script()

    command = script.build_launch_command("balatrobot serve", host="localhost", port=23456, fast_server=False)

    assert command == ["balatrobot", "serve", "--host", "localhost", "--port", "23456"]


def test_build_launch_command_can_launch_fast_visible_server() -> None:
    script = _load_script()

    command = script.build_launch_command(
        "uvx balatrobot serve",
        host="127.0.0.1",
        port=12346,
        fast_server=True,
        headless_server=False,
    )

    assert "--fast" in command
    assert "--headless" not in command


def test_script_exposes_full_action_model_flag() -> None:
    script = _load_script()

    args = script.build_parser().parse_args(["--full-action-model", "model.json"])

    assert args.full_action_model == Path("model.json")
