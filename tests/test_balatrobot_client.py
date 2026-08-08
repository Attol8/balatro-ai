import pytest

from balatro_ai_v2.balatrobot.client import (
    BalatroBotClient,
    BalatroBotError,
    BalatroBotProtocolError,
    BalatroBotTransportError,
)


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


def test_start_uses_deck_stake_and_optional_seed() -> None:
    calls = []

    def transport(payload: dict) -> dict:
        calls.append(payload)
        return {"jsonrpc": "2.0", "result": {"state": "BLIND_SELECT"}, "id": 1}

    client = BalatroBotClient(transport=transport)

    assert client.start(deck="RED", stake="WHITE", seed="1") == {"state": "BLIND_SELECT"}
    assert calls[0]["method"] == "start"
    assert calls[0]["params"] == {"deck": "RED", "stake": "WHITE", "seed": "1"}


def test_save_and_load_use_private_file_endpoint_paths() -> None:
    calls = []

    def transport(payload: dict) -> dict:
        calls.append(payload)
        return {"jsonrpc": "2.0", "result": {"success": True}, "id": payload["id"]}

    client = BalatroBotClient(transport=transport)

    client.save(path="/private/tmp/parent.jkr")
    client.load(path="/private/tmp/parent.jkr")

    assert [(call["method"], call["params"]) for call in calls] == [
        ("save", {"path": "/private/tmp/parent.jkr"}),
        ("load", {"path": "/private/tmp/parent.jkr"}),
    ]


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


def test_request_ids_increment_and_response_id_must_match() -> None:
    ids = []

    def transport(payload: dict) -> dict:
        ids.append(payload["id"])
        return {"jsonrpc": "2.0", "result": {}, "id": payload["id"]}

    client = BalatroBotClient(transport=transport)
    client.health()
    client.health()

    assert ids == [1, 2]

    bad = BalatroBotClient(
        transport=lambda payload: {"jsonrpc": "2.0", "result": {}, "id": payload["id"] + 1}
    )
    with pytest.raises(BalatroBotProtocolError):
        bad.health()


def test_transport_failure_has_a_distinct_error_type() -> None:
    def transport(payload: dict) -> dict:
        raise OSError("offline")

    with pytest.raises(BalatroBotTransportError):
        BalatroBotClient(transport=transport).health()
