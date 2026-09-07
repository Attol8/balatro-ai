"""Small, single-attempt JSON-RPC client for BalatroBot."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib import request
from urllib.error import URLError

JsonObject = dict[str, Any]
Transport = Callable[[JsonObject], object]
MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class BalatroBotError(RuntimeError):
    """BalatroBot was unreachable or returned an invalid/error response."""


@dataclass(frozen=True, slots=True)
class BalatroBotClient:
    host: str = "127.0.0.1"
    port: int = 12346
    # The mod replies once an action has settled; visible-mode animations can take
    # several seconds, and a timed-out mutation ends the run, so allow a wide margin.
    timeout: float = 60.0
    transport: Transport | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def rpc(self, method: str, params: JsonObject | None = None) -> JsonObject:
        payload: JsonObject = {
            "jsonrpc": "2.0",
            "method": method,
            "params": {} if params is None else params,
            "id": 1,
        }
        # Every call gets exactly one transport attempt. In particular, mutation
        # requests are never replayed after an ambiguous failure.
        response = (
            self.transport(payload) if self.transport is not None else self._http_post(payload)
        )
        if not isinstance(response, dict):
            raise BalatroBotError(f"BalatroBot returned invalid JSON-RPC response: {response!r}")
        if "error" in response:
            error = response["error"]
            message = (
                error.get("message", "BalatroBot error") if isinstance(error, dict) else str(error)
            )
            raise BalatroBotError(message)
        if "result" not in response:
            raise BalatroBotError(f"BalatroBot response for {method} has no result")
        result = response["result"]
        if not isinstance(result, dict):
            raise BalatroBotError(f"BalatroBot returned non-object result for {method}: {result!r}")
        return result

    def health(self) -> JsonObject:
        return self.rpc("health")

    def gamestate(self) -> JsonObject:
        return self.rpc("gamestate")

    def _http_post(self, payload: JsonObject) -> JsonObject:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(http_request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except (OSError, URLError) as exc:
            raise BalatroBotError(f"failed to connect to BalatroBot at {self.url}: {exc}") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise BalatroBotError(f"BalatroBot response exceeds {MAX_RESPONSE_BYTES} bytes")
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BalatroBotError("BalatroBot returned malformed JSON") from exc
        if not isinstance(decoded, dict):
            raise BalatroBotError(f"BalatroBot returned invalid JSON-RPC response: {decoded!r}")
        return decoded
