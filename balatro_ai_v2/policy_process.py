"""Parent-side client for a process-isolated public policy."""

from __future__ import annotations

import os
import selectors
import subprocess
import sys
import time
from collections.abc import Sequence
from itertools import islice
from pathlib import Path

from balatro_ai_v2.actions import PublicAction, action_to_data, is_legal
from balatro_ai_v2.policy import ActionSource, PublicHistoryStep
from balatro_ai_v2.policy_wire import (
    MAX_LEGAL_ACTIONS,
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    PolicyRequest,
    PolicyWireError,
    decode_response,
    encode_request,
)
from balatro_ai_v2.public_state import PublicObservation


class PolicyProcessError(RuntimeError):
    pass


class PolicyProcess:
    def __init__(
        self,
        policy_name: str,
        *,
        policy_seed: str = "isolated-v1",
        timeout_seconds: float = 5.0,
        command: Sequence[str] | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self._request_id = 0
        self._closed = False
        child_command = tuple(command) if command is not None else (
            sys.executable,
            "-m",
            "balatro_ai_v2.policy_child",
            "--policy",
            policy_name,
            "--policy-seed",
            policy_seed,
        )
        if not child_command:
            raise ValueError("policy child command cannot be empty")
        self._process = subprocess.Popen(
            child_command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            cwd=Path(__file__).resolve().parents[1],
            env=_child_environment(),
            start_new_session=True,
        )
        if self._process.stdin is None or self._process.stdout is None:
            self.close()
            raise PolicyProcessError("policy child pipes are unavailable")

    @property
    def closed(self) -> bool:
        return self._closed

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        if self._closed:
            raise PolicyProcessError("policy child is closed")
        legal = tuple(islice(legal_actions(), MAX_LEGAL_ACTIONS))
        try:
            request = PolicyRequest(self._request_id, len(history), observation, legal)
            frame = encode_request(request)
            self._write_frame(frame)
            response = decode_response(self._read_frame())
            if response.request_id != self._request_id:
                raise PolicyProcessError("policy response request ID mismatch")
            if response.observation_digest != observation.digest():
                raise PolicyProcessError("policy response observation digest mismatch")
            action_data = action_to_data(response.action)
            if action_data not in [action_to_data(action) for action in legal]:
                raise PolicyProcessError("policy response was not in the supplied legal action set")
            if not is_legal(observation, response.action):
                raise PolicyProcessError("policy response is not legal in the current observation")
        except (BrokenPipeError, OSError, PolicyWireError, PolicyProcessError) as exc:
            self.close()
            if isinstance(exc, PolicyProcessError):
                raise
            raise PolicyProcessError(f"policy child protocol failed: {exc}") from exc
        self._request_id += 1
        return response.action

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._process
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        for pipe in (process.stdin, process.stdout):
            if pipe is not None:
                pipe.close()

    def __enter__(self) -> PolicyProcess:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _write_frame(self, frame: bytes) -> None:
        if len(frame) > MAX_REQUEST_BYTES or self._process.stdin is None:
            raise PolicyProcessError("policy request frame is invalid")
        descriptor = self._process.stdin.fileno()
        os.set_blocking(descriptor, False)
        view = memoryview(frame)
        deadline = time.monotonic() + self.timeout_seconds
        with selectors.DefaultSelector() as selector:
            selector.register(descriptor, selectors.EVENT_WRITE)
            while view:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise PolicyProcessError("policy child timed out while receiving a request")
                written = os.write(descriptor, view)
                view = view[written:]

    def _read_frame(self) -> bytes:
        if self._process.stdout is None:
            raise PolicyProcessError("policy response pipe is unavailable")
        descriptor = self._process.stdout.fileno()
        os.set_blocking(descriptor, False)
        buffer = bytearray()
        deadline = time.monotonic() + self.timeout_seconds
        with selectors.DefaultSelector() as selector:
            selector.register(descriptor, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    raise PolicyProcessError("policy child timed out")
                chunk = os.read(descriptor, min(4096, MAX_RESPONSE_BYTES + 1 - len(buffer)))
                if not chunk:
                    raise PolicyProcessError("policy child exited before responding")
                buffer.extend(chunk)
                newline = buffer.find(b"\n")
                if newline >= 0:
                    if newline != len(buffer) - 1:
                        raise PolicyProcessError("policy child wrote extra stdout")
                    return bytes(buffer)
                if len(buffer) > MAX_RESPONSE_BYTES:
                    raise PolicyProcessError("policy child response exceeded the frame limit")


def _child_environment() -> dict[str, str]:
    root = str(Path(__file__).resolve().parents[1])
    environment = {"PYTHONPATH": root, "PYTHONUNBUFFERED": "1"}
    for name in ("PATH", "LANG", "LC_ALL"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment
