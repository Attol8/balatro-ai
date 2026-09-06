"""Bounded request/response transport for local JSON-lines workers."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path


class JsonlProcessError(RuntimeError):
    pass


_MAX_WORKER_ERROR_BYTES = 4_096


class JsonlChildProcess:
    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: float,
        max_request_bytes: int,
        max_response_bytes: int,
    ) -> None:
        if not command or timeout_seconds <= 0:
            raise ValueError("worker command and timeout must be non-empty and positive")
        self.timeout_seconds = timeout_seconds
        self.max_request_bytes = max_request_bytes
        self.max_response_bytes = max_response_bytes
        self._closed = False
        self._process = subprocess.Popen(
            tuple(command),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            cwd=cwd,
            env=dict(environment),
            start_new_session=True,
        )
        if self._process.stdin is None or self._process.stdout is None:
            self.close()
            raise JsonlProcessError("worker pipes are unavailable")

    @property
    def closed(self) -> bool:
        return self._closed

    def exchange(self, frame: bytes) -> bytes:
        if self._closed:
            raise JsonlProcessError("worker is closed")
        try:
            self._write_frame(frame)
            return self._read_frame()
        except (BrokenPipeError, OSError, JsonlProcessError):
            self.close()
            raise

    def read_startup_frame(self) -> bytes:
        if self._closed:
            raise JsonlProcessError("worker is closed")
        try:
            return self._read_frame()
        except (OSError, JsonlProcessError):
            self.close()
            raise

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._process
        if process.poll() is None:
            _signal_process_group(process, signal.SIGTERM)
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                _signal_process_group(process, signal.SIGKILL)
                process.wait(timeout=1.0)
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None:
                pipe.close()

    def _write_frame(self, frame: bytes) -> None:
        if not frame or len(frame) > self.max_request_bytes or self._process.stdin is None:
            raise JsonlProcessError("request frame is invalid")
        descriptor = self._process.stdin.fileno()
        os.set_blocking(descriptor, False)
        view = memoryview(frame)
        deadline = time.monotonic() + self.timeout_seconds
        with selectors.DefaultSelector() as selector:
            selector.register(descriptor, selectors.EVENT_WRITE)
            while view:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise JsonlProcessError("worker timed out while receiving a request")
                written = os.write(descriptor, view)
                view = view[written:]

    def _read_frame(self) -> bytes:
        if self._process.stdout is None:
            raise JsonlProcessError("response pipe is unavailable")
        descriptor = self._process.stdout.fileno()
        os.set_blocking(descriptor, False)
        buffer = bytearray()
        deadline = time.monotonic() + self.timeout_seconds
        with selectors.DefaultSelector() as selector:
            selector.register(descriptor, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise JsonlProcessError("worker timed out")
                chunk = os.read(descriptor, min(4096, self.max_response_bytes + 1 - len(buffer)))
                if not chunk:
                    detail = self._worker_error_detail()
                    suffix = f": {detail}" if detail else ""
                    raise JsonlProcessError(f"worker exited before responding{suffix}")
                buffer.extend(chunk)
                newline = buffer.find(b"\n")
                if newline >= 0:
                    if newline != len(buffer) - 1:
                        raise JsonlProcessError("worker wrote extra stdout")
                    return bytes(buffer)
                if len(buffer) > self.max_response_bytes:
                    raise JsonlProcessError("worker response exceeded the frame limit")

    def _worker_error_detail(self) -> str:
        stderr = self._process.stderr
        if stderr is None:
            return ""
        try:
            os.set_blocking(stderr.fileno(), False)
            payload = os.read(stderr.fileno(), _MAX_WORKER_ERROR_BYTES)
        except (BlockingIOError, OSError):
            return ""
        text = payload.decode("utf-8", errors="replace").strip()
        return " ".join(text.split())


def minimal_child_environment(python_paths: Sequence[Path]) -> dict[str, str]:
    environment = {
        "PYTHONPATH": os.pathsep.join(str(path.resolve()) for path in python_paths),
        "PYTHONUNBUFFERED": "1",
    }
    for name in ("PATH", "LANG", "LC_ALL"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _signal_process_group(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, sig)
            return
        except ProcessLookupError:
            return
        except PermissionError:
            pass
        if process.poll() is not None:
            return
    if sig == signal.SIGTERM:
        process.terminate()
    else:
        process.kill()
