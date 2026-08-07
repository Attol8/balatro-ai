from __future__ import annotations

import json
from dataclasses import dataclass, field
from itertools import count
from typing import Any, Callable
from urllib import request
from urllib.error import URLError

JsonObject = dict[str, Any]
Transport = Callable[[JsonObject], JsonObject]


class BalatroBotError(RuntimeError):
    """Raised when BalatroBot returns an error response or cannot be reached."""


class BalatroBotTransportError(BalatroBotError):
    """BalatroBot could not be reached or returned invalid JSON."""


class BalatroBotRpcError(BalatroBotError):
    """BalatroBot rejected a syntactically valid JSON-RPC request."""


class BalatroBotProtocolError(BalatroBotError):
    """BalatroBot returned a malformed JSON-RPC response."""


@dataclass(frozen=True, slots=True)
class BalatroBotClient:
    host: str = "127.0.0.1"
    port: int = 12346
    timeout: float = 30.0
    transport: Transport | None = None
    _request_ids: Any = field(default_factory=lambda: count(1), init=False, repr=False, compare=False)

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def rpc(self, method: str, params: JsonObject | None = None) -> JsonObject:
        request_id = next(self._request_ids)
        payload: JsonObject = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": request_id,
        }
        if self.transport is None:
            response = self._http_post(payload)
        else:
            try:
                response = self.transport(payload)
            except BalatroBotError:
                raise
            except (OSError, TimeoutError) as exc:
                raise BalatroBotTransportError(f"BalatroBot transport failed: {exc}") from exc
        if not isinstance(response, dict):
            raise BalatroBotProtocolError(f"BalatroBot returned a non-object response: {response!r}")
        if response.get("jsonrpc") != "2.0" or response.get("id") != request_id:
            raise BalatroBotProtocolError(f"invalid JSON-RPC envelope for {method}: {response!r}")
        if "error" in response:
            error = response["error"]
            message = error.get("message", "BalatroBot error") if isinstance(error, dict) else str(error)
            raise BalatroBotRpcError(message)
        result = response.get("result")
        if not isinstance(result, dict):
            raise BalatroBotProtocolError(f"BalatroBot returned non-object result for {method}: {result!r}")
        return result

    def health(self) -> JsonObject:
        return self.rpc("health")

    def gamestate(self) -> JsonObject:
        return self.rpc("gamestate")

    def menu(self) -> JsonObject:
        return self.rpc("menu")

    def start(self, *, deck: str = "RED", stake: str = "WHITE", seed: str | None = None) -> JsonObject:
        params = {"deck": deck, "stake": stake}
        if seed is not None:
            params["seed"] = seed
        return self.rpc("start", params)

    def call_action(self, method: str, params: JsonObject | None = None) -> JsonObject:
        return self.rpc(method, params)

    def _http_post(self, payload: JsonObject) -> JsonObject:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self.url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                data = response.read().decode("utf-8")
        except (OSError, TimeoutError, URLError) as exc:
            raise BalatroBotTransportError(f"failed to connect to BalatroBot at {self.url}: {exc}") from exc

        try:
            decoded = json.loads(data)
        except json.JSONDecodeError as exc:
            raise BalatroBotTransportError(f"BalatroBot returned invalid JSON: {exc}") from exc
        if not isinstance(decoded, dict):
            raise BalatroBotProtocolError(f"BalatroBot returned invalid JSON-RPC response: {decoded!r}")
        return decoded
