"""BalatroBot server lifecycle helpers."""

from __future__ import annotations

import os
import shlex
import subprocess
import time

from balatro_ai_v2.balatrobot.client import BalatroBotClient, BalatroBotError


FAST_SERVER_ARGS = (
    "--fast",
    "--no-shaders",
    "--gamespeed",
    "10",
    "--animation-fps",
    "60",
)
PROFILE_MODES = frozenset({"all_unlocked", "career"})


def build_launch_command(
    base_command: str,
    *,
    host: str,
    port: int,
    fast_server: bool,
    headless_server: bool = True,
) -> list[str]:
    command = shlex.split(base_command)
    if not command:
        raise ValueError("launch command cannot be empty")
    command.extend(("--host", host, "--port", str(port)))
    if fast_server:
        if headless_server:
            command.append("--headless")
        command.extend(FAST_SERVER_ARGS)
    return command


def build_launch_environment(*, profile_mode: str) -> dict[str, str]:
    if profile_mode not in PROFILE_MODES:
        raise ValueError(f"unsupported profile mode {profile_mode!r}")
    environment = os.environ.copy()
    environment["BALATROBOT_ALL_UNLOCKED"] = "1" if profile_mode == "all_unlocked" else "0"
    return environment


def require_profile_mode(health: object, *, expected: str) -> None:
    if expected not in PROFILE_MODES:
        raise ValueError(f"unsupported profile mode {expected!r}")
    actual = health.get("profile_mode") if isinstance(health, dict) else None
    if actual != expected:
        raise RuntimeError(f"BalatroBot profile mode is {actual!r}; expected {expected!r}")


def wait_for_balatrobot(
    client: BalatroBotClient,
    *,
    timeout: float,
    poll_delay: float,
    process: subprocess.Popen[bytes] | None = None,
) -> None:
    deadline = time.monotonic() + timeout
    last_error: BalatroBotError | None = None
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"BalatroBot exited before becoming reachable at {client.url}")
        try:
            client.health()
            return
        except BalatroBotError as exc:
            last_error = exc
            if poll_delay > 0:
                time.sleep(poll_delay)
    raise RuntimeError(f"BalatroBot is not reachable at {client.url}: {last_error}")


def stop_balatrobot_server(process: subprocess.Popen[bytes], *, timeout: float = 5.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
