from __future__ import annotations

import os
import signal
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import balatro_ai_v2.jsonl_process as jsonl_process
from balatro_ai_v2.jsonl_process import JsonlChildProcess, minimal_child_environment


@pytest.mark.skipif(os.name != "posix", reason="process-group cleanup is POSIX-specific")
def test_transport_close_terminates_the_entire_worker_process_group(tmp_path: Path) -> None:
    program = """
import subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
print(child.pid, flush=True)
time.sleep(60)
"""
    transport = JsonlChildProcess(
        (sys.executable, "-c", program),
        cwd=tmp_path,
        environment=minimal_child_environment((Path(__file__).resolve().parents[1],)),
        timeout_seconds=1,
        max_request_bytes=1_000,
        max_response_bytes=1_000,
    )
    child_pid = int(transport.read_startup_frame())

    transport.close()

    deadline = time.monotonic() + 1
    while _pid_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not _pid_exists(child_pid)


@pytest.mark.skipif(os.name != "posix", reason="process-group cleanup is POSIX-specific")
def test_process_group_signal_falls_back_when_killpg_is_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    process = SimpleNamespace(
        pid=123,
        poll=lambda: None,
        terminate=lambda: calls.append("terminate"),
        kill=lambda: calls.append("kill"),
    )

    def forbidden(_pid: int, _signal: signal.Signals) -> None:
        raise PermissionError

    monkeypatch.setattr(os, "killpg", forbidden)

    jsonl_process._signal_process_group(process, signal.SIGTERM)

    assert calls == ["terminate"]


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
