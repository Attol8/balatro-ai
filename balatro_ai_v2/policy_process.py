"""Parent-side client for a process-isolated public policy."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from balatro_ai_v2.actions import PublicAction, is_legal
from balatro_ai_v2.jsonl_process import (
    JsonlChildProcess,
    JsonlProcessError,
    minimal_child_environment,
)
from balatro_ai_v2.policy import ActionSource, PublicHistoryStep
from balatro_ai_v2.policy_wire import (
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
        self._request_id = 0
        root = Path(__file__).resolve().parents[1]
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
        self._transport = JsonlChildProcess(
            child_command,
            cwd=root,
            environment=minimal_child_environment((root,)),
            timeout_seconds=timeout_seconds,
            max_request_bytes=MAX_REQUEST_BYTES,
            max_response_bytes=MAX_RESPONSE_BYTES,
        )

    @property
    def closed(self) -> bool:
        return self._transport.closed

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        if self.closed:
            raise PolicyProcessError("policy child is closed")
        del legal_actions
        try:
            request = PolicyRequest(self._request_id, len(history), observation)
            frame = encode_request(request)
            response = decode_response(self._transport.exchange(frame))
            if response.request_id != self._request_id:
                raise PolicyProcessError("policy response request ID mismatch")
            if response.observation_digest != observation.digest():
                raise PolicyProcessError("policy response observation digest mismatch")
            if not is_legal(observation, response.action):
                raise PolicyProcessError("policy response is not legal in the current observation")
        except (JsonlProcessError, PolicyWireError, PolicyProcessError) as exc:
            self.close()
            if isinstance(exc, PolicyProcessError):
                raise
            raise PolicyProcessError(f"policy child protocol failed: {exc}") from exc
        self._request_id += 1
        return response.action

    def close(self) -> None:
        self._transport.close()

    def __enter__(self) -> PolicyProcess:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
