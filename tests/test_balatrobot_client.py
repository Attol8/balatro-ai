import pytest

from balatro_ai_v2.balatrobot.client import BalatroBotClient, BalatroBotError


def test_rpc_sends_json_rpc_payload() -> None:
    calls = []

    def transport(payload: dict) -> dict:
        calls.append(payload)
        return {
            "jsonrpc": "2.0",
            "result": {"state": "MENU"},
            "id": 1,
        }

    client = BalatroBotClient(transport=transport)

    state = client.gamestate()

    assert state == {"state": "MENU"}
    assert calls == [
        {
            "jsonrpc": "2.0",
            "method": "gamestate",
            "params": {},
            "id": 1,
        }
    ]


def test_health_uses_standard_endpoint() -> None:
    def transport(payload: dict) -> dict:
        assert payload["method"] == "health"
        return {"jsonrpc": "2.0", "result": {"status": "ok"}, "id": 1}

    client = BalatroBotClient(transport=transport)

    assert client.health() == {"status": "ok"}


def test_rpc_error_raises_balatrobot_error() -> None:
    def transport(payload: dict) -> dict:
        return {
            "jsonrpc": "2.0",
            "error": {"code": -32001, "message": "bad state"},
            "id": 1,
        }

    client = BalatroBotClient(transport=transport)

    with pytest.raises(BalatroBotError, match="bad state"):
        client.gamestate()
