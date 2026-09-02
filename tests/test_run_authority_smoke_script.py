from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_authority_smoke.py"
    spec = importlib.util.spec_from_file_location("run_authority_smoke_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_launch_command_adds_real_game_fast_settings() -> None:
    script = _load_script()

    command = script.build_launch_command(
        "uvx balatrobot serve",
        host="127.0.0.1",
        port=12346,
        fast_server=True,
    )

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


def test_smoke_cli_has_no_model_or_legacy_policy_flags() -> None:
    script = _load_script()
    parser = script.build_parser()

    args = parser.parse_args(["--seed", "17", "--trace-jsonl", "evidence/seed17.jsonl"])

    assert args.seed == "17"
    assert args.policy == "smoke"
    assert not hasattr(args, "imitation_model")
    assert not hasattr(args, "planner")


def test_smoke_cli_accepts_isolated_public_baseline() -> None:
    script = _load_script()
    parser = script.build_parser()

    args = parser.parse_args(
        ["--seed", "44", "--policy", "strategic", "--policy-timeout", "8"]
    )

    assert args.policy == "strategic"
    assert args.policy_timeout == 8
