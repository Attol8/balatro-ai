from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib import request
from urllib.error import URLError

JsonObject = dict[str, Any]
Transport = Callable[[JsonObject], JsonObject]


class BalatroBotError(RuntimeError):
    """Raised when BalatroBot returns an error response or cannot be reached."""


@dataclass(frozen=True, slots=True)
class BalatroBotClient:
    host: str = "127.0.0.1"
    port: int = 12346
    timeout: float = 30.0
    transport: Transport | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def rpc(self, method: str, params: JsonObject | None = None) -> JsonObject:
        payload: JsonObject = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": 1,
        }
        response = self.transport(payload) if self.transport else self._http_post(payload)
        if "error" in response:
            error = response["error"]
            message = error.get("message", "BalatroBot error") if isinstance(error, dict) else str(error)
            raise BalatroBotError(message)
        result = response.get("result")
        if not isinstance(result, dict):
            raise BalatroBotError(f"BalatroBot returned non-object result for {method}: {result!r}")
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
            raise BalatroBotError(f"failed to connect to BalatroBot at {self.url}: {exc}") from exc

        decoded = json.loads(data)
        if not isinstance(decoded, dict):
            raise BalatroBotError(f"BalatroBot returned invalid JSON-RPC response: {decoded!r}")
        return decoded
