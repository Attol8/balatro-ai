from __future__ import annotations

import os

import pytest

from balatro_ai_v2.balatrobot.process import build_launch_environment, require_profile_mode


def test_launch_environment_declares_all_unlocked_without_mutating_parent(monkeypatch) -> None:
    monkeypatch.delenv("BALATROBOT_ALL_UNLOCKED", raising=False)

    environment = build_launch_environment(profile_mode="all_unlocked")

    assert environment["BALATROBOT_ALL_UNLOCKED"] == "1"
    assert "BALATROBOT_ALL_UNLOCKED" not in os.environ


def test_profile_mode_verification_fails_closed() -> None:
    require_profile_mode({"profile_mode": "all_unlocked"}, expected="all_unlocked")

    with pytest.raises(RuntimeError, match="expected 'all_unlocked'"):
        require_profile_mode({"profile_mode": "career"}, expected="all_unlocked")
    with pytest.raises(RuntimeError, match="expected 'all_unlocked'"):
        require_profile_mode({"status": "ok"}, expected="all_unlocked")


def test_unknown_profile_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported profile mode"):
        build_launch_environment(profile_mode="mystery")
