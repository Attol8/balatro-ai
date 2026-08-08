from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

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


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True
