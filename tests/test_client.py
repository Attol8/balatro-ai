import pytest

from balatro_ai.client import BalatroBotClient, BalatroBotError


def test_rpc_sends_one_json_rpc_request_and_returns_object_result() -> None:
    calls = []

    def transport(payload: dict) -> object:
        calls.append(payload)
        return {"jsonrpc": "2.0", "result": {"state": "MENU"}, "id": 1}

    client = BalatroBotClient(transport=transport)
    assert client.gamestate() == {"state": "MENU"}
    assert calls == [{
        "jsonrpc": "2.0", "method": "gamestate", "params": {}, "id": 1,
    }]


def test_rpc_surfaces_remote_error_without_retrying_mutation() -> None:
    calls = []

    def transport(payload: dict) -> object:
        calls.append(payload)
        return {"jsonrpc": "2.0", "error": {"code": -32001, "message": "bad state"}, "id": 1}

    with pytest.raises(BalatroBotError, match="bad state"):
        BalatroBotClient(transport=transport).rpc("play", {"cards": [0]})
    assert len(calls) == 1


@pytest.mark.parametrize("response", [None, [], "bad", {"jsonrpc": "2.0"}, {"result": 4}])
def test_rpc_rejects_malformed_response_without_retry(response: object) -> None:
    calls = 0

    def transport(payload: dict) -> object:
        nonlocal calls
        calls += 1
        return response

    with pytest.raises(BalatroBotError):
        BalatroBotClient(transport=transport).rpc("sell", {"joker": 0})
    assert calls == 1


def test_health_uses_standard_method() -> None:
    def transport(payload: dict) -> object:
        assert payload["method"] == "health"
        return {"jsonrpc": "2.0", "result": {"status": "ok"}, "id": 1}

    assert BalatroBotClient(transport=transport).health() == {"status": "ok"}
