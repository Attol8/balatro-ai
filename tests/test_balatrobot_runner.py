import json

from balatro_ai_v2.actions import ActionKind
from balatro_ai_v2.balatrobot.client import BalatroBotClient
from balatro_ai_v2.balatrobot.policy import BalatroBotPolicy
from balatro_ai_v2.balatrobot.policy_config import PolicyConfig, ShopPolicyConfig, TacticalPolicyConfig
from balatro_ai_v2.balatrobot.runner import BalatroBotRunner
from balatro_ai_v2.balatrobot.shop_planner import plan_shop_action
from balatro_ai_v2.balatrobot.tracing import JsonlTraceWriter


def test_policy_plays_when_discard_cannot_improve_unwinnable_round() -> None:
    action = BalatroBotPolicy().tactical_action(
        _selecting_hand_state(
            [
                _card("S", "A"),
                _card("S", "K"),
                _card("S", "Q"),
                _card("H", "2"),
                _card("D", "3"),
                _card("C", "4"),
                _card("S", "J"),
                _card("S", "T"),
            ],
            required_score=100_000,
        )
    )

    assert action.kind == ActionKind.PLAY
    assert action.indices


def test_policy_plays_when_best_play_clears_current_blind() -> None:
    action = BalatroBotPolicy().tactical_action(
        _selecting_hand_state(
            [
                _card("S", "A"),
                _card("S", "K"),
                _card("S", "Q"),
                _card("S", "J"),
                _card("S", "T"),
            ],
            required_score=100,
        )
    )

    assert action.kind == ActionKind.PLAY
    assert action.indices == (0, 1, 2, 3, 4)


def test_runner_executes_balatrobot_state_machine() -> None:
    calls = []

    def transport(payload: dict) -> dict:
        calls.append((payload["method"], payload.get("params") or {}))
        method = payload["method"]
        if method == "menu":
            result = {"state": "MENU"}
        elif method == "start":
            result = {"state": "BLIND_SELECT", "seed": "1", "ante_num": 1, "round_num": 0}
        elif method == "select":
            result = _selecting_hand_state(
                [_card("S", "A"), _card("S", "K"), _card("S", "Q"), _card("S", "J"), _card("S", "T")],
                required_score=100,
            )
        elif method == "play":
            result = {"state": "ROUND_EVAL", "seed": "1", "ante_num": 1, "round_num": 1, "won": False}
        elif method == "cash_out":
            result = {"state": "SHOP", "seed": "1", "ante_num": 1, "round_num": 1, "won": False}
        elif method == "next_round":
            result = {"state": "GAME_OVER", "seed": "1", "ante_num": 9, "round_num": 24, "won": True}
        else:
            result = {"state": "GAME_OVER", "seed": "1", "ante_num": 0, "round_num": 0, "won": False}
        return {"jsonrpc": "2.0", "result": result, "id": 1}

    runner = BalatroBotRunner(BalatroBotClient(transport=transport))
    result = runner.play_run(seed="1")

    assert result.won
    assert result.ante == 9
    assert [method for method, _ in calls] == ["menu", "start", "select", "play", "cash_out", "next_round"]
    assert calls[3] == ("play", {"cards": [0, 1, 2, 3, 4]})


def test_runner_writes_compact_jsonl_trace(tmp_path) -> None:
    def transport(payload: dict) -> dict:
        method = payload["method"]
        if method == "menu":
            result = {"state": "MENU"}
        elif method == "start":
            result = {"state": "BLIND_SELECT", "seed": "1", "ante_num": 1, "round_num": 0}
        elif method == "select":
            result = {"state": "GAME_OVER", "seed": "1", "ante_num": 1, "round_num": 0, "won": False}
        else:
            result = {"state": "GAME_OVER", "seed": "1", "ante_num": 0, "round_num": 0, "won": False}
        return {"jsonrpc": "2.0", "result": result, "id": 1}

    trace_path = tmp_path / "trace.jsonl"
    runner = BalatroBotRunner(
        BalatroBotClient(transport=transport),
        trace_writer=JsonlTraceWriter(trace_path, include_states=False),
    )

    runner.play_run(seed="1")

    rows = [json.loads(line) for line in trace_path.read_text().splitlines()]
    assert [row["event"] for row in rows] == ["run_start", "transition", "run_end"]
    assert rows[1]["action"]["method"] == "select"
    assert rows[1]["before"]["state"] == "BLIND_SELECT"
    assert rows[1]["after"]["state"] == "GAME_OVER"


def test_shop_planner_buys_visible_affordable_modeled_joker() -> None:
    state = _shop_state(
        money=8,
        shop_cards=[
            {"key": "j_joker", "set": "JOKER", "cost": {"buy": 2, "sell": 1}},
            {"key": "j_unimplemented", "set": "JOKER", "cost": {"buy": 1, "sell": 1}},
        ],
    )

    decision = plan_shop_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.BUY_CARD
    assert decision.action.index == 0


def test_shop_planner_uses_held_planet_card() -> None:
    state = _shop_state(
        money=8,
        shop_cards=[],
        consumables=[
            {"key": "c_jupiter", "set": "PLANET", "cost": {"buy": 3, "sell": 1}},
        ],
    )

    decision = plan_shop_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.USE_CONSUMABLE
    assert decision.action.index == 0


def test_shop_planner_buys_high_priestess_for_planet_generation() -> None:
    state = _shop_state(
        money=16,
        shop_cards=[
            {"key": "c_high_priestess", "set": "TAROT", "cost": {"buy": 3, "sell": 1}},
        ],
    )

    decision = plan_shop_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.BUY_CARD
    assert decision.action.index == 0


def test_shop_planner_respects_configured_high_priestess_money_floor() -> None:
    state = _shop_state(
        money=16,
        shop_cards=[
            {"key": "c_high_priestess", "set": "TAROT", "cost": {"buy": 3, "sell": 1}},
        ],
    )

    decision = plan_shop_action(
        state,
        config=ShopPolicyConfig(high_priestess_min_money=999),
    )

    assert decision.action is None


def test_policy_passes_tactical_config() -> None:
    policy = BalatroBotPolicy(
        config=PolicyConfig(tactical=TacticalPolicyConfig(beam_width=1, action_beam=1))
    )

    action = policy.tactical_action(
        _selecting_hand_state(
            [
                _card("S", "A"),
                _card("S", "K"),
                _card("S", "Q"),
                _card("S", "J"),
                _card("S", "T"),
            ],
            required_score=100,
        )
    )

    assert action.kind == ActionKind.PLAY


def test_shop_planner_uses_held_high_priestess() -> None:
    state = _shop_state(
        money=10,
        shop_cards=[],
        consumables=[
            {"key": "c_high_priestess", "set": "TAROT", "cost": {"buy": 3, "sell": 1}},
        ],
    )

    decision = plan_shop_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.USE_CONSUMABLE
    assert decision.action.index == 0


def _selecting_hand_state(cards: list[dict], *, required_score: int) -> dict:
    return {
        "state": "SELECTING_HAND",
        "round_num": 1,
        "ante_num": 1,
        "money": 4,
        "seed": "1",
        "round": {"hands_left": 4, "discards_left": 3, "chips": 0},
        "hands": {name: {"level": 1} for name in _HAND_NAMES},
        "blinds": {
            "small": {"type": "SMALL", "status": "CURRENT", "score": required_score},
            "big": {"type": "BIG", "status": "UPCOMING", "score": 150},
            "boss": {"type": "BOSS", "status": "UPCOMING", "score": 200},
        },
        "jokers": {"count": 0, "limit": 5, "cards": []},
        "cards": {"count": 44, "limit": 52, "cards": []},
        "hand": {"count": len(cards), "limit": 8, "highlighted_limit": 5, "cards": cards},
    }


def _shop_state(
    *,
    money: int,
    shop_cards: list[dict],
    consumables: list[dict] | None = None,
) -> dict:
    state = _selecting_hand_state([], required_score=300)
    state["state"] = "SHOP"
    state["money"] = money
    state["shop"] = {"count": len(shop_cards), "limit": 2, "cards": shop_cards}
    state["consumables"] = {
        "count": len(consumables or []),
        "limit": 2,
        "cards": consumables or [],
    }
    return state


def _card(suit: str, rank: str) -> dict:
    return {"key": f"{suit}_{rank}", "value": {"suit": suit, "rank": rank}, "cost": {"buy": 0, "sell": 0}}


_HAND_NAMES = (
    "High Card",
    "Pair",
    "Two Pair",
    "Three of a Kind",
    "Straight",
    "Flush",
    "Full House",
    "Four of a Kind",
    "Straight Flush",
    "Five of a Kind",
    "Flush House",
    "Flush Five",
)
