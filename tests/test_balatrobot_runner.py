import json
from typing import Sequence

from balatro_ai_v2.actions import ActionKind
from balatro_ai_v2.balatrobot.imitation_policy import (
    balatrobot_state_to_fast_observation,
    balatrobot_state_to_full_fast_observation,
    fast_legal_full_actions,
    fast_legal_tactical_actions,
    game_action_to_full_fast_action,
)
from balatro_ai_v2.balatrobot.client import BalatroBotClient
from balatro_ai_v2.balatrobot.policy import BalatroBotPolicy
from balatro_ai_v2.balatrobot.policy_config import PolicyConfig, ShopPolicyConfig, TacticalPolicyConfig
from balatro_ai_v2.balatrobot.runner import BalatroBotRunner
from balatro_ai_v2.balatrobot.shop_planner import plan_consumable_action, plan_pack_action, plan_shop_action
from balatro_ai_v2.balatrobot.tactical_planner import _jokers_after_play, plan_tactical_action, score_play_action
from balatro_ai_v2.balatrobot.tracing import JsonlTraceWriter
from balatro_ai_v2.fast.env import DISCARD_ACTION_OFFSET
from balatro_ai_v2.fast.full_game import (
    BUY_CARD_ACTION_BASE,
    BUY_PACK_ACTION_BASE,
    BUY_VOUCHER_ACTION,
    CASH_OUT_ACTION,
    NEXT_ROUND_ACTION,
    SELECT_BLIND_ACTION,
    _ITEM_OBS_IDS,
)
from balatro_ai_v2.fast.hand import FOUR_OF_A_KIND, STRAIGHT, TWO_PAIR, FastScore
from balatro_ai_v2.fast.jokers import Joker
from balatro_ai_v2.learning.balatrobot_traces import iter_balatrobot_trace_oracle_steps


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


def test_runner_selects_useful_booster_card() -> None:
    calls = []

    def transport(payload: dict) -> dict:
        calls.append((payload["method"], payload.get("params") or {}))
        method = payload["method"]
        if method == "menu":
            result = {"state": "MENU"}
        elif method == "start":
            result = {"state": "SMODS_BOOSTER_OPENED", "seed": "1", "ante_num": 1, "round_num": 1}
        elif method == "pack":
            result = {"state": "GAME_OVER", "seed": "1", "ante_num": 9, "round_num": 24, "won": True}
        else:
            result = {"state": "GAME_OVER", "seed": "1", "ante_num": 0, "round_num": 0, "won": False}
        if result["state"] == "SMODS_BOOSTER_OPENED":
            result["pack"] = {
                "count": 2,
                "limit": 2,
                "cards": [
                    {"key": "j_unimplemented", "set": "JOKER", "cost": {"buy": 0, "sell": 0}},
                    {"key": "j_cavendish", "set": "JOKER", "cost": {"buy": 0, "sell": 0}},
                ],
            }
            result["jokers"] = {"count": 0, "limit": 5, "cards": []}
            result["hands"] = {name: {"level": 1} for name in _HAND_NAMES}
            result["round"] = {"hands_left": 4, "discards_left": 3, "chips": 0}
        return {"jsonrpc": "2.0", "result": result, "id": 1}

    runner = BalatroBotRunner(BalatroBotClient(transport=transport))
    result = runner.play_run(seed="1")

    assert result.won
    assert calls[2] == ("pack", {"card": 1})


def test_runner_polls_opened_pack_until_cards_are_available() -> None:
    calls = []

    def pack_state(cards: list[dict]) -> dict:
        return {
            "state": "PLANET_PACK",
            "seed": "1",
            "ante_num": 1,
            "round_num": 1,
            "pack": {"count": 2, "limit": 2, "cards": cards},
            "packs": {
                "cards": [
                    {"key": "p_celestial_normal_4", "set": "BOOSTER", "cost": {"buy": 4, "sell": 0}},
                ],
            },
            "jokers": {"count": 0, "limit": 5, "cards": []},
            "hands": {name: {"level": 1, "played": 0} for name in _HAND_NAMES},
            "round": {"hands_left": 4, "discards_left": 3, "chips": 0},
        }

    def transport(payload: dict) -> dict:
        calls.append((payload["method"], payload.get("params") or {}))
        method = payload["method"]
        if method == "menu":
            result = {"state": "MENU"}
        elif method == "start":
            result = pack_state([])
        elif method == "gamestate":
            result = pack_state(
                [
                    {"key": "c_pluto", "set": "PLANET", "cost": {"buy": 0, "sell": 0}},
                    {"key": "c_jupiter", "set": "PLANET", "cost": {"buy": 0, "sell": 0}},
                ]
            )
        elif method == "pack":
            result = {"state": "GAME_OVER", "seed": "1", "ante_num": 9, "round_num": 24, "won": True}
        else:
            result = {"state": "GAME_OVER", "seed": "1", "ante_num": 0, "round_num": 0, "won": False}
        return {"jsonrpc": "2.0", "result": result, "id": 1}

    runner = BalatroBotRunner(BalatroBotClient(transport=transport), poll_delay=0)
    result = runner.play_run(seed="1")

    assert result.won
    assert calls[2] == ("gamestate", {})
    assert calls[3] == ("pack", {"card": 1})


def test_runner_retries_pack_when_balatrobot_selection_is_still_in_progress() -> None:
    calls = []
    rejected_pack_once = False

    def pack_state() -> dict:
        return {
            "state": "PLANET_PACK",
            "seed": "1",
            "ante_num": 1,
            "round_num": 1,
            "pack": {
                "count": 2,
                "limit": 2,
                "cards": [
                    {"key": "c_pluto", "set": "PLANET", "cost": {"buy": 0, "sell": 0}},
                    {"key": "c_jupiter", "set": "PLANET", "cost": {"buy": 0, "sell": 0}},
                ],
            },
            "jokers": {"count": 0, "limit": 5, "cards": []},
            "hands": {name: {"level": 1, "played": 0} for name in _HAND_NAMES},
            "round": {"hands_left": 4, "discards_left": 3, "chips": 0},
        }

    def transport(payload: dict) -> dict:
        nonlocal rejected_pack_once
        calls.append((payload["method"], payload.get("params") or {}))
        method = payload["method"]
        if method == "menu":
            result = {"state": "MENU"}
        elif method == "start":
            result = pack_state()
        elif method == "pack" and not rejected_pack_once:
            rejected_pack_once = True
            return {"jsonrpc": "2.0", "error": {"message": "Pack selection already in progress"}, "id": 1}
        elif method == "gamestate":
            result = pack_state()
        elif method == "pack":
            result = {"state": "GAME_OVER", "seed": "1", "ante_num": 9, "round_num": 24, "won": True}
        else:
            result = {"state": "GAME_OVER", "seed": "1", "ante_num": 0, "round_num": 0, "won": False}
        return {"jsonrpc": "2.0", "result": result, "id": 1}

    runner = BalatroBotRunner(BalatroBotClient(transport=transport), poll_delay=0)
    result = runner.play_run(seed="1")

    assert result.won
    assert calls[2] == ("pack", {"card": 1})
    assert calls[3] == ("gamestate", {})
    assert calls[4] == ("pack", {"card": 1})


def test_runner_skips_pack_when_balatrobot_selection_guard_stays_stuck() -> None:
    calls = []

    def pack_state() -> dict:
        return {
            "state": "PLANET_PACK",
            "seed": "1",
            "ante_num": 1,
            "round_num": 1,
            "pack": {
                "count": 2,
                "limit": 2,
                "cards": [
                    {"key": "c_pluto", "set": "PLANET", "cost": {"buy": 0, "sell": 0}},
                    {"key": "c_jupiter", "set": "PLANET", "cost": {"buy": 0, "sell": 0}},
                ],
            },
            "jokers": {"count": 0, "limit": 5, "cards": []},
            "hands": {name: {"level": 1, "played": 0} for name in _HAND_NAMES},
            "round": {"hands_left": 4, "discards_left": 3, "chips": 0},
        }

    def transport(payload: dict) -> dict:
        calls.append((payload["method"], payload.get("params") or {}))
        method = payload["method"]
        if method == "menu":
            result = {"state": "MENU"}
        elif method == "start":
            result = pack_state()
        elif method == "pack" and payload.get("params", {}).get("skip"):
            result = {"state": "SHOP", "seed": "1", "ante_num": 1, "round_num": 1, "won": False}
        elif method == "pack":
            return {"jsonrpc": "2.0", "error": {"message": "Pack selection already in progress"}, "id": 1}
        elif method == "gamestate":
            result = pack_state()
        elif method == "next_round":
            result = {"state": "GAME_OVER", "seed": "1", "ante_num": 9, "round_num": 24, "won": True}
        else:
            result = {"state": "GAME_OVER", "seed": "1", "ante_num": 0, "round_num": 0, "won": False}
        return {"jsonrpc": "2.0", "result": result, "id": 1}

    runner = BalatroBotRunner(
        BalatroBotClient(transport=transport),
        poll_delay=0,
        pack_in_progress_retries=2,
    )
    result = runner.play_run(seed="1")

    assert result.won
    assert calls[2] == ("pack", {"card": 1})
    assert calls[3] == ("gamestate", {})
    assert calls[4] == ("pack", {"card": 1})
    assert calls[5] == ("pack", {"skip": True})
    assert calls[6] == ("next_round", {})


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


def test_shop_planner_buys_no_target_tarot() -> None:
    state = _shop_state(
        money=12,
        shop_cards=[
            {"key": "c_hermit", "set": "TAROT", "cost": {"buy": 3, "sell": 1}},
        ],
    )

    decision = plan_shop_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.BUY_CARD
    assert decision.action.index == 0


def test_shop_planner_buys_valuable_booster_pack() -> None:
    state = _shop_state(
        money=8,
        shop_cards=[],
        packs=[
            {"key": "p_buffoon_normal_1", "set": "BOOSTER", "cost": {"buy": 4, "sell": 0}},
        ],
    )

    decision = plan_shop_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.BUY_PACK
    assert decision.action.index == 0


def test_shop_planner_buys_arcana_pack_for_tarot_access() -> None:
    state = _shop_state(
        money=8,
        shop_cards=[],
        packs=[
            {"key": "p_arcana_normal_1", "set": "BOOSTER", "cost": {"buy": 4, "sell": 0}},
        ],
    )

    decision = plan_shop_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.BUY_PACK
    assert decision.action.index == 0


def test_shop_planner_compares_pack_against_weaker_shop_card() -> None:
    state = _shop_state(
        money=8,
        shop_cards=[
            {"key": "c_pluto", "set": "PLANET", "cost": {"buy": 3, "sell": 1}},
        ],
        packs=[
            {"key": "p_buffoon_normal_1", "set": "BOOSTER", "cost": {"buy": 4, "sell": 0}},
        ],
    )

    decision = plan_shop_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.BUY_PACK
    assert decision.action.index == 0


def test_shop_planner_buys_high_value_visible_voucher() -> None:
    state = _shop_state(
        money=14,
        shop_cards=[
            {"key": "c_pluto", "set": "PLANET", "cost": {"buy": 3, "sell": 1}},
        ],
        packs=[
            {"key": "p_celestial_normal_1", "set": "BOOSTER", "cost": {"buy": 4, "sell": 0}},
        ],
    )
    state["vouchers"] = {
        "count": 1,
        "limit": 1,
        "cards": [{"key": "v_grabber", "set": "VOUCHER", "cost": {"buy": 10, "sell": 0}}],
    }

    decision = plan_shop_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.BUY_VOUCHER
    assert decision.action.index == 0


def test_shop_planner_does_not_go_broke_on_arcana_pack() -> None:
    state = _shop_state(
        money=6,
        shop_cards=[],
        packs=[
            {"key": "p_arcana_jumbo_2", "set": "BOOSTER", "cost": {"buy": 6, "sell": 0}},
        ],
        jokers=[
            {"key": "j_bull", "set": "JOKER", "cost": {"sell": 3}, "value": {"ability": {"extra": 2}}},
        ],
    )

    decision = plan_shop_action(state)

    assert decision.action is None or decision.action.kind != ActionKind.USE_CONSUMABLE


def test_pack_planner_selects_best_opened_planet() -> None:
    state = _shop_state(money=8, shop_cards=[])
    state["state"] = "SMODS_BOOSTER_OPENED"
    state["hands"]["Flush"]["played"] = 3
    state["pack"] = {
        "count": 2,
        "limit": 2,
        "cards": [
            {"key": "c_pluto", "set": "PLANET", "cost": {"buy": 0, "sell": 0}},
            {"key": "c_jupiter", "set": "PLANET", "cost": {"buy": 0, "sell": 0}},
        ],
    }

    decision = plan_pack_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.PACK_SELECT
    assert decision.action.index == 1


def test_pack_planner_selects_no_target_tarot_from_opened_pack() -> None:
    state = _shop_state(money=12, shop_cards=[])
    state["state"] = "TAROT_PACK"
    state["pack"] = {
        "count": 2,
        "limit": 2,
        "cards": [
            {"key": "c_strength", "set": "TAROT", "cost": {"buy": 0, "sell": 0}},
            {"key": "c_hermit", "set": "TAROT", "cost": {"buy": 0, "sell": 0}},
        ],
    }

    decision = plan_pack_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.PACK_SELECT
    assert decision.action.index == 1


def test_pack_planner_can_select_no_target_tarot_when_consumable_slots_are_full() -> None:
    state = _shop_state(
        money=12,
        shop_cards=[],
        consumables=[
            {"key": "c_pluto", "set": "PLANET", "cost": {"buy": 0, "sell": 0}},
            {"key": "c_mercury", "set": "PLANET", "cost": {"buy": 0, "sell": 0}},
        ],
    )
    state["state"] = "TAROT_PACK"
    state["pack"] = {
        "count": 2,
        "limit": 2,
        "cards": [
            {"key": "c_hermit", "set": "TAROT", "cost": {"buy": 0, "sell": 0}},
            {"key": "c_strength", "set": "TAROT", "cost": {"buy": 0, "sell": 0}},
        ],
    }

    decision = plan_pack_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.PACK_SELECT
    assert decision.action.index == 0


def test_pack_planner_selects_targeted_tarot_with_card_targets() -> None:
    state = _shop_state(money=8, shop_cards=[])
    state["state"] = "TAROT_PACK"
    state["hand"] = {
        "count": 5,
        "limit": 8,
        "highlighted_limit": 5,
        "cards": [_card("S", "A"), _card("H", "K"), _card("C", "7"), _card("D", "3"), _card("S", "2")],
    }
    state["pack"] = {
        "count": 2,
        "limit": 2,
        "cards": [
            {"key": "c_strength", "set": "TAROT", "cost": {"buy": 0, "sell": 0}},
            {"key": "c_hanged_man", "set": "TAROT", "cost": {"buy": 0, "sell": 0}},
        ],
    }

    decision = plan_pack_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.PACK_SELECT
    assert decision.action.index == 1
    assert decision.action.indices == (4, 3)


def test_policy_does_not_auto_use_held_targeted_tarot_before_playing_hand() -> None:
    state = _selecting_hand_state(
        [_card("S", "A"), _card("H", "K"), _card("C", "7"), _card("D", "3"), _card("S", "2")],
        required_score=300,
    )
    state["consumables"] = {
        "count": 1,
        "limit": 2,
        "cards": [{"key": "c_hanged_man", "set": "TAROT", "cost": {"buy": 3, "sell": 1}}],
    }

    action = BalatroBotPolicy().tactical_action(state)

    assert action.kind != ActionKind.USE_CONSUMABLE


def test_consumable_planner_does_not_use_targeted_tarot_without_visible_hand() -> None:
    state = _shop_state(
        money=8,
        shop_cards=[],
        consumables=[{"key": "c_hanged_man", "set": "TAROT", "cost": {"buy": 3, "sell": 1}}],
    )

    decision = plan_consumable_action(state)

    assert decision is None


def test_pack_planner_does_not_use_unopened_pack_offers_as_opened_cards() -> None:
    state = _shop_state(
        money=8,
        shop_cards=[],
        packs=[
            {"key": "p_celestial_normal_4", "set": "BOOSTER", "cost": {"buy": 4, "sell": 0}},
        ],
    )
    state["state"] = "PLANET_PACK"
    state["pack"] = {"count": 2, "limit": 2, "cards": []}

    decision = plan_pack_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.PACK_SKIP


def test_shop_planner_respects_configured_high_priestess_money_floor() -> None:
    state = _shop_state(
        money=16,
        shop_cards=[
            {"key": "c_high_priestess", "set": "TAROT", "cost": {"buy": 3, "sell": 1}},
        ],
    )

    decision = plan_shop_action(
        state,
        config=ShopPolicyConfig(high_priestess_min_money=999, reroll_max_cost=0),
    )

    assert decision.action is None or decision.action.kind != ActionKind.USE_CONSUMABLE


def test_shop_planner_sells_weakest_joker_for_major_upgrade() -> None:
    state = _shop_state(
        money=4,
        shop_cards=[
            {"key": "j_cavendish", "set": "JOKER", "cost": {"buy": 6, "sell": 3}},
        ],
        jokers=[
            {"key": "j_joker", "set": "JOKER", "cost": {"buy": 2, "sell": 1}},
            {"key": "j_half", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
            {"key": "j_scholar", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
            {"key": "j_bull", "set": "JOKER", "cost": {"buy": 6, "sell": 3}},
            {"key": "j_mystic_summit", "set": "JOKER", "cost": {"buy": 5, "sell": 2}},
        ],
    )

    decision = plan_shop_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.SELL_JOKER
    assert decision.action.index == 1


def test_shop_planner_does_not_sell_for_marginal_upgrade() -> None:
    state = _shop_state(
        money=8,
        shop_cards=[
            {"key": "j_raised_fist", "set": "JOKER", "cost": {"buy": 5, "sell": 2}},
        ],
        jokers=[
            {"key": "j_joker", "set": "JOKER", "cost": {"buy": 2, "sell": 1}},
            {"key": "j_half", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
            {"key": "j_scholar", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
            {"key": "j_bull", "set": "JOKER", "cost": {"buy": 6, "sell": 3}},
            {"key": "j_mystic_summit", "set": "JOKER", "cost": {"buy": 5, "sell": 2}},
        ],
    )

    decision = plan_shop_action(state)

    assert decision.action is None


def test_shop_planner_rerolls_dead_shop_with_open_joker_slot() -> None:
    state = _shop_state(
        money=10,
        shop_cards=[
            {"key": "j_unimplemented", "set": "JOKER", "cost": {"buy": 1, "sell": 1}},
        ],
        jokers=[
            {"key": "j_joker", "set": "JOKER", "cost": {"buy": 2, "sell": 1}},
        ],
    )
    state["round"]["reroll_cost"] = 5

    decision = plan_shop_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.REROLL


def test_shop_planner_waits_when_unaffordable_major_upgrade_is_visible() -> None:
    state = _shop_state(
        money=6,
        shop_cards=[
            {"key": "j_cavendish", "set": "JOKER", "cost": {"buy": 8, "sell": 4}},
        ],
        jokers=[
            {"key": "j_joker", "set": "JOKER", "cost": {"buy": 2, "sell": 1}},
        ],
    )
    state["round"]["reroll_cost"] = 5

    decision = plan_shop_action(state)

    assert decision.action is None


def test_shop_planner_prioritizes_late_open_joker_slot_over_planet() -> None:
    state = _shop_state(
        money=8,
        shop_cards=[
            {"key": "j_ride_the_bus", "set": "JOKER", "cost": {"buy": 6, "sell": 3}},
            {"key": "c_jupiter", "set": "PLANET", "cost": {"buy": 3, "sell": 1}},
        ],
        jokers=[
            {"key": "j_bull", "set": "JOKER", "cost": {"buy": 6, "sell": 3}},
            {"key": "j_scholar", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
            {"key": "j_square", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
            {"key": "j_mystic_summit", "set": "JOKER", "cost": {"buy": 5, "sell": 2}},
        ],
    )
    state["ante_num"] = 4
    state["hands"]["Flush"]["played"] = 8

    decision = plan_shop_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.BUY_CARD
    assert decision.action.index == 0


def test_shop_planner_buys_economy_joker_over_marginal_late_pack() -> None:
    state = _shop_state(
        money=7,
        shop_cards=[
            {"key": "j_drunkard", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
            {"key": "j_rocket", "set": "JOKER", "cost": {"buy": 6, "sell": 3}},
        ],
        packs=[
            {"key": "p_celestial_normal_1", "set": "BOOSTER", "cost": {"buy": 4, "sell": 2}},
        ],
        jokers=[
            {"key": "j_bull", "set": "JOKER", "cost": {"buy": 6, "sell": 3}},
            {"key": "j_scholar", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
            {"key": "j_square", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
            {"key": "j_mystic_summit", "set": "JOKER", "cost": {"buy": 5, "sell": 2}},
        ],
    )
    state["ante_num"] = 3

    decision = plan_shop_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.BUY_CARD
    assert decision.action.index == 1


def test_shop_planner_rerolls_late_without_carry_instead_of_buying_planet_pack() -> None:
    state = _shop_state(
        money=8,
        shop_cards=[
            {"key": "c_star", "set": "TAROT", "cost": {"buy": 3, "sell": 1}},
            {"key": "j_drunkard", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
        ],
        packs=[
            {"key": "p_standard_normal_1", "set": "BOOSTER", "cost": {"buy": 4, "sell": 2}},
            {"key": "p_celestial_normal_3", "set": "BOOSTER", "cost": {"buy": 4, "sell": 2}},
        ],
        jokers=[
            {"key": "j_bull", "set": "JOKER", "cost": {"buy": 6, "sell": 3}},
            {"key": "j_scholar", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
            {"key": "j_square", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
            {"key": "j_mystic_summit", "set": "JOKER", "cost": {"buy": 5, "sell": 2}},
            {"key": "j_ride_the_bus", "set": "JOKER", "cost": {"buy": 6, "sell": 3}},
        ],
    )
    state["ante_num"] = 4
    state["round"]["reroll_cost"] = 5

    decision = plan_shop_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.REROLL


def test_shop_planner_can_sell_to_afford_visible_upgrade_before_slots_are_full() -> None:
    state = _shop_state(
        money=4,
        shop_cards=[
            {"key": "j_raised_fist", "set": "JOKER", "cost": {"buy": 5, "sell": 2}},
        ],
        jokers=[
            {"key": "j_bull", "set": "JOKER", "cost": {"buy": 6, "sell": 3}},
            {"key": "j_scholar", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
            {"key": "j_square", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
            {"key": "j_mystic_summit", "set": "JOKER", "cost": {"buy": 5, "sell": 2}},
        ],
    )
    state["ante_num"] = 3

    decision = plan_shop_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.SELL_JOKER


def test_shop_planner_accepts_small_late_replacement_when_build_has_no_carry() -> None:
    state = _shop_state(
        money=10,
        shop_cards=[
            {"key": "j_sly", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
        ],
        jokers=[
            {"key": "j_bull", "set": "JOKER", "cost": {"buy": 6, "sell": 3}},
            {"key": "j_scholar", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
            {"key": "j_mystic_summit", "set": "JOKER", "cost": {"buy": 5, "sell": 2}},
            {"key": "j_raised_fist", "set": "JOKER", "cost": {"buy": 5, "sell": 2}},
            {"key": "j_rocket", "set": "JOKER", "cost": {"buy": 6, "sell": 3}},
        ],
    )
    state["ante_num"] = 4
    state["hands"]["Pair"]["played"] = 8

    decision = plan_shop_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.SELL_JOKER


def test_shop_planner_values_type_joker_for_established_hand_family() -> None:
    state = _shop_state(
        money=6,
        shop_cards=[
            {"key": "j_sly", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
        ],
        jokers=[
            {"key": "j_bull", "set": "JOKER", "cost": {"buy": 6, "sell": 3}},
            {"key": "j_scholar", "set": "JOKER", "cost": {"buy": 4, "sell": 2}},
            {"key": "j_raised_fist", "set": "JOKER", "cost": {"buy": 5, "sell": 2}},
            {"key": "j_rocket", "set": "JOKER", "cost": {"buy": 6, "sell": 3}},
            {"key": "j_ride_the_bus", "set": "JOKER", "cost": {"buy": 6, "sell": 3}},
        ],
    )
    state["ante_num"] = 4
    state["hands"]["Pair"]["played"] = 12

    decision = plan_shop_action(state)

    assert decision.action is not None
    assert decision.action.kind == ActionKind.SELL_JOKER


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


def test_policy_skips_high_value_non_boss_tag() -> None:
    state = _selecting_hand_state([], required_score=300)
    state["state"] = "BLIND_SELECT"
    state["blinds"]["small"]["status"] = "SELECT"
    state["blinds"]["small"]["tag_name"] = "Negative Tag"
    state["blinds"]["small"]["tag_effect"] = "Next base edition shop Joker is free and becomes Negative"

    action = BalatroBotPolicy().blind_action(state)

    assert action.kind == ActionKind.SKIP_BLIND


def test_policy_does_not_skip_late_negative_tag_with_weak_build() -> None:
    state = _selecting_hand_state([], required_score=5_000)
    state["state"] = "BLIND_SELECT"
    state["ante_num"] = 4
    state["money"] = 2
    state["blinds"]["small"]["status"] = "SELECT"
    state["blinds"]["small"]["tag_name"] = "Negative Tag"
    state["blinds"]["small"]["tag_effect"] = "Next base edition shop Joker is free and becomes Negative"
    state["jokers"] = {
        "count": 5,
        "limit": 5,
        "cards": [
            {"key": "j_bull", "set": "JOKER"},
            {"key": "j_scholar", "set": "JOKER"},
            {"key": "j_square", "set": "JOKER"},
            {"key": "j_mystic_summit", "set": "JOKER"},
            {"key": "j_ride_the_bus", "set": "JOKER"},
        ],
    }

    action = BalatroBotPolicy().blind_action(state)

    assert action.kind == ActionKind.SELECT_BLIND


def test_policy_can_skip_late_negative_tag_with_carry_joker() -> None:
    state = _selecting_hand_state([], required_score=5_000)
    state["state"] = "BLIND_SELECT"
    state["ante_num"] = 4
    state["blinds"]["small"]["status"] = "SELECT"
    state["blinds"]["small"]["tag_name"] = "Negative Tag"
    state["jokers"] = {
        "count": 1,
        "limit": 5,
        "cards": [{"key": "j_cavendish", "set": "JOKER"}],
    }

    action = BalatroBotPolicy().blind_action(state)

    assert action.kind == ActionKind.SKIP_BLIND


def test_policy_does_not_skip_ante_five_holographic_tag_for_medium_carry() -> None:
    state = _selecting_hand_state([], required_score=16_500)
    state["state"] = "BLIND_SELECT"
    state["ante_num"] = 5
    state["money"] = 12
    state["blinds"]["big"]["status"] = "SELECT"
    state["blinds"]["big"]["tag_name"] = "Holographic Tag"
    state["blinds"]["big"]["tag_effect"] = "Next base edition shop Joker is free and becomes Holographic"
    state["jokers"] = {
        "count": 5,
        "limit": 5,
        "cards": [
            {"key": "j_bull", "set": "JOKER"},
            {"key": "j_scholar", "set": "JOKER"},
            {"key": "j_raised_fist", "set": "JOKER"},
            {"key": "j_rocket", "set": "JOKER"},
            {"key": "j_trio", "set": "JOKER"},
        ],
    }

    action = BalatroBotPolicy().blind_action(state)

    assert action.kind == ActionKind.SELECT_BLIND


def test_policy_does_not_skip_unscoped_orbital_tag() -> None:
    state = _selecting_hand_state([], required_score=3_000)
    state["state"] = "BLIND_SELECT"
    state["ante_num"] = 3
    state["blinds"]["big"]["status"] = "SELECT"
    state["blinds"]["big"]["tag_name"] = "Orbital Tag"
    state["blinds"]["big"]["tag_effect"] = "Upgrade Poker Hand by 3 levels"

    action = BalatroBotPolicy().blind_action(state)

    assert action.kind == ActionKind.SELECT_BLIND


def test_policy_does_not_skip_boss() -> None:
    state = _selecting_hand_state([], required_score=300)
    state["state"] = "BLIND_SELECT"
    state["blinds"]["boss"]["status"] = "SELECT"
    state["blinds"]["boss"]["tag_name"] = "Negative Tag"

    action = BalatroBotPolicy().blind_action(state)

    assert action.kind == ActionKind.SELECT_BLIND


def test_policy_can_use_trained_tactical_model() -> None:
    class DiscardModel:
        def predict(self, observation: Sequence[int], legal_actions: Sequence[int]) -> int:
            assert observation[0] == 1
            action = DISCARD_ACTION_OFFSET + 0b11
            assert action in legal_actions
            return action

    action = BalatroBotPolicy(tactical_model=DiscardModel()).tactical_action(
        _selecting_hand_state(
            [
                _card("S", "A"),
                _card("H", "A"),
                _card("S", "Q"),
            ],
            required_score=1_000,
        )
    )

    assert action.kind == ActionKind.DISCARD
    assert action.indices == (0, 1)


def test_policy_can_use_full_action_model_for_shop_actions() -> None:
    class BuyVoucherModel:
        def predict(self, observation: Sequence[int], legal_actions: Sequence[int]) -> int:
            assert observation[0] == 3
            assert BUY_VOUCHER_ACTION in legal_actions
            assert BUY_CARD_ACTION_BASE in legal_actions
            assert BUY_PACK_ACTION_BASE in legal_actions
            return BUY_VOUCHER_ACTION

    state = _shop_state(
        money=20,
        shop_cards=[{"key": "j_joker", "set": "JOKER", "cost": {"buy": 2, "sell": 1}}],
        packs=[{"key": "p_buffoon_normal_1", "set": "BOOSTER", "cost": {"buy": 4, "sell": 0}}],
    )
    state["vouchers"] = {
        "count": 1,
        "limit": 1,
        "cards": [{"key": "v_grabber", "set": "VOUCHER", "cost": {"buy": 10, "sell": 0}}],
    }

    action = BalatroBotPolicy(full_action_model=BuyVoucherModel()).shop_action(state)

    assert action is not None
    assert action.kind == ActionKind.BUY_VOUCHER
    assert action.index == 0


def test_policy_can_use_full_action_model_to_leave_shop() -> None:
    class NextRoundModel:
        def predict(self, observation: Sequence[int], legal_actions: Sequence[int]) -> int:
            assert NEXT_ROUND_ACTION in legal_actions
            return NEXT_ROUND_ACTION

    action = BalatroBotPolicy(full_action_model=NextRoundModel()).shop_action(
        _shop_state(money=0, shop_cards=[])
    )

    assert action is not None
    assert action.kind == ActionKind.NEXT_ROUND


def test_game_action_to_full_fast_action_encodes_all_full_action_families() -> None:
    assert game_action_to_full_fast_action(None) == NEXT_ROUND_ACTION
    assert game_action_to_full_fast_action(BalatroBotPolicy().round_eval_action({})) == CASH_OUT_ACTION
    assert game_action_to_full_fast_action(
        BalatroBotPolicy().blind_action({"state": "BLIND_SELECT"})
    ) == SELECT_BLIND_ACTION
    assert game_action_to_full_fast_action(
        _action(ActionKind.BUY_CARD, index=2)
    ) == BUY_CARD_ACTION_BASE + 2
    assert game_action_to_full_fast_action(
        _action(ActionKind.BUY_PACK, index=1)
    ) == BUY_PACK_ACTION_BASE + 1


def test_balatrobot_trace_oracle_data_labels_live_hand_with_legal_planner_action() -> None:
    state = _selecting_hand_state(
        [
            _card("S", "A"),
            _card("S", "9"),
            _card("D", "8"),
            _card("H", "7"),
            _card("S", "5"),
            _card("D", "3"),
            _card("H", "2"),
            _card("C", "2"),
        ],
        required_score=300,
    )
    rows = [
        {
            "event": "transition",
            "before": state,
            "action": {"method": "discard", "params": {"cards": [0, 4, 5, 6, 7]}},
            "after": {"state": "SELECTING_HAND", "round_num": 1, "seed": "1"},
        }
    ]

    steps = list(iter_balatrobot_trace_oracle_steps(rows))

    assert len(steps) == 1
    assert steps[0].action in steps[0].legal_actions
    assert steps[0].action == _action(ActionKind.PLAY, indices=(6, 7)).to_fast_action_id()
    assert steps[0].info["executed_method"] == "discard"


def test_live_imitation_observation_includes_hand_levels_and_play_counts() -> None:
    state = _selecting_hand_state([_card("S", "A")], required_score=300)
    state["hands"]["Pair"] = {"level": 3, "played": 2}

    observation = balatrobot_state_to_fast_observation(state)

    assert observation[11] == 3
    assert observation[23] == 2
    assert fast_legal_tactical_actions(state)


def test_full_action_observation_includes_shop_voucher_pack_and_hand_tail() -> None:
    state = _shop_state(
        money=20,
        shop_cards=[{"key": "j_joker", "set": "JOKER", "cost": {"buy": 2, "sell": 1}}],
        packs=[{"key": "p_buffoon_normal_1", "set": "BOOSTER", "cost": {"buy": 4, "sell": 0}}],
    )
    state["vouchers"] = {
        "count": 1,
        "limit": 1,
        "cards": [{"key": "v_grabber", "set": "VOUCHER", "cost": {"buy": 10, "sell": 0}}],
    }

    observation = balatrobot_state_to_full_fast_observation(state)

    assert observation[0] == 3
    assert observation[-8:] == (-1, -1, -1, -1, -1, -1, -1, -1)
    assert _ITEM_OBS_IDS["j_joker"] in observation
    assert _ITEM_OBS_IDS["p_buffoon_normal_1"] in observation
    assert _ITEM_OBS_IDS["v_grabber"] in observation
    legal_actions = fast_legal_full_actions(state)
    assert BUY_CARD_ACTION_BASE in legal_actions
    assert BUY_PACK_ACTION_BASE in legal_actions
    assert BUY_VOUCHER_ACTION in legal_actions


def test_tactical_beam_carries_scaling_joker_state_forward() -> None:
    selected = (_fast_card("S", "2"), _fast_card("H", "2"), _fast_card("C", "2"), _fast_card("D", "2"))
    jokers = (
        Joker("j_square", scaling=0),
        Joker("j_runner", scaling=0),
        Joker("j_trousers", scaling=0),
        Joker("j_green_joker", scaling=0),
        Joker("j_ride_the_bus", scaling=0),
    )

    after_four = _jokers_after_play(
        jokers,
        FastScore(kind=FOUR_OF_A_KIND, chips=68, mult=7, total=476, scoring_mask=0b1111),
        selected,
    )
    after_straight = _jokers_after_play(
        jokers,
        FastScore(kind=STRAIGHT, chips=60, mult=4, total=240, scoring_mask=0b11111),
        tuple(_fast_card("S", rank) for rank in ("2", "3", "4", "5", "6")),
    )
    after_two_pair = _jokers_after_play(
        jokers,
        FastScore(kind=TWO_PAIR, chips=40, mult=2, total=80, scoring_mask=0b1111),
        selected,
    )

    assert after_four[0].scaling == 4
    assert after_four[3].scaling == 1
    assert after_four[4].scaling == 1
    assert after_straight[1].scaling == 15
    assert after_two_pair[2].scaling == 2


def test_score_play_abstract_counts_unimplemented_jokers() -> None:
    state = _selecting_hand_state([_card("S", "A")], required_score=300)
    state["jokers"] = {
        "count": 2,
        "limit": 5,
        "cards": [
            {"key": "j_abstract", "set": "JOKER", "value": {"ability": {"extra": 3}}},
            {"key": "j_rocket", "set": "JOKER", "value": {"ability": {"dollars": 3}}},
        ],
    }

    score = score_play_action(state, _action(ActionKind.PLAY, indices=(0,)))

    assert score.total == 112


def test_score_play_blocks_non_first_hand_type_for_the_mouth() -> None:
    state = _selecting_hand_state(
        [_card("S", "A"), _card("H", "A"), _card("D", "Q"), _card("C", "7")],
        required_score=70_000,
    )
    state["blinds"]["small"]["status"] = "DEFEATED"
    state["blinds"]["boss"]["status"] = "CURRENT"
    state["blinds"]["boss"]["name"] = "The Mouth"
    state["blinds"]["boss"]["effect"] = "Play only 1 hand type this round"
    state["hands"]["High Card"]["played_this_round"] = 1

    score = score_play_action(state, _action(ActionKind.PLAY, indices=(0, 1)))

    assert score.total == 0


def test_tactical_planner_does_not_treat_debuffed_cards_as_clear() -> None:
    state = _selecting_hand_state(
        [
            _card("H", "9"),
            _card("C", "8"),
            _card("C", "7", debuffed=True),
            _card("S", "6"),
            _card("S", "5", debuffed=True),
            _card("C", "5", debuffed=True),
            _card("S", "4", debuffed=True),
            _card("H", "2", debuffed=True),
        ],
        required_score=10_000,
    )
    state["round"]["chips"] = 7654
    state["round"]["hands_left"] = 1
    state["round"]["discards_left"] = 1
    state["money"] = 8
    state["blinds"]["small"]["status"] = "DEFEATED"
    state["blinds"]["big"]["status"] = "DEFEATED"
    state["blinds"]["boss"]["status"] = "CURRENT"
    state["blinds"]["boss"]["name"] = "The Pillar"
    state["blinds"]["boss"]["effect"] = "Cards played previously this Ante are debuffed"
    state["blinds"]["boss"]["score"] = 10_000
    state["jokers"] = {
        "count": 5,
        "limit": 5,
        "cards": [
            {"key": "j_bull", "set": "JOKER", "cost": {"sell": 3}, "value": {"ability": {"extra": 2}}},
            {"key": "j_rocket", "set": "JOKER", "cost": {"sell": 3}, "value": {"ability": {"dollars": 5}}},
            {"key": "j_ride_the_bus", "set": "JOKER", "cost": {"sell": 3}, "value": {"ability": {"mult": 1}}},
            {"key": "j_sly", "set": "JOKER", "cost": {"sell": 1}, "value": {"ability": {"t_chips": 50}}},
            {"key": "j_abstract", "set": "JOKER", "cost": {"sell": 2}, "value": {"ability": {"extra": 3}}},
        ],
    }
    state["cards"] = {
        "count": 5,
        "limit": 52,
        "cards": [
            _card("H", "A"),
            _card("D", "A"),
            _card("S", "K"),
            _card("C", "K"),
            _card("S", "Q"),
        ],
    }

    plan = plan_tactical_action(state)

    assert plan.action.kind == ActionKind.DISCARD


def test_tactical_planner_widens_search_when_default_beam_misses_clear() -> None:
    state = _selecting_hand_state(
        [
            _card("H", "A"),
            _card("C", "A"),
            _card("C", "K"),
            _card("H", "Q"),
            _card("C", "Q"),
            _card("H", "T"),
            _card("H", "7"),
            _card("D", "4"),
            _card("D", "3"),
        ],
        required_score=11_000,
    )
    state["hand"]["limit"] = 9
    state["round"]["hands_left"] = 4
    state["round"]["discards_left"] = 4
    state["round"]["most_played_poker_hand"] = "Pair"
    state["money"] = 7
    state["hands"]["Pair"]["level"] = 2
    state["hands"]["Pair"]["played"] = 11
    state["hands"]["Flush"]["level"] = 2
    state["hands"]["Flush"]["played"] = 5
    state["hands"]["Straight"]["level"] = 2
    state["hands"]["Straight"]["played"] = 5
    state["jokers"] = {
        "count": 5,
        "limit": 5,
        "cards": [
            {"key": "j_bull", "set": "JOKER", "cost": {"sell": 3}, "value": {"ability": {"extra": 2}}},
            {"key": "j_rocket", "set": "JOKER", "cost": {"sell": 3}, "value": {"ability": {"dollars": 5}}},
            {"key": "j_ride_the_bus", "set": "JOKER", "cost": {"sell": 3}, "value": {"ability": {"mult": 1}}},
            {"key": "j_sly", "set": "JOKER", "cost": {"sell": 1}, "value": {"ability": {"t_chips": 50}}},
            {"key": "j_abstract", "set": "JOKER", "cost": {"sell": 2}, "value": {"ability": {"extra": 3}}},
        ],
    }
    state["cards"] = {
        "count": 43,
        "limit": 52,
        "cards": [_card_from_key(key) for key in _ANTE_FIVE_SEARCH_DECK],
    }

    plan = plan_tactical_action(state)

    assert plan.clears
    assert plan.projected_score >= 11_000


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


def test_shop_planner_does_not_auto_use_wheel_of_fortune() -> None:
    state = _shop_state(
        money=10,
        shop_cards=[],
        consumables=[
            {"key": "c_wheel_of_fortune", "set": "TAROT", "cost": {"buy": 3, "sell": 1}},
        ],
        jokers=[
            {"key": "j_bull", "set": "JOKER", "cost": {"buy": 6, "sell": 3}},
        ],
    )

    decision = plan_shop_action(state)

    assert decision.action is None or decision.action.kind != ActionKind.USE_CONSUMABLE


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
    packs: list[dict] | None = None,
    jokers: list[dict] | None = None,
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
    state["packs"] = {
        "count": len(packs or []),
        "limit": 2,
        "cards": packs or [],
    }
    state["jokers"] = {
        "count": len(jokers or []),
        "limit": 5,
        "cards": jokers or [],
    }
    return state


def _action(kind: ActionKind, *, indices: tuple[int, ...] = (), index: int | None = None):
    from balatro_ai_v2.actions import GameAction

    return GameAction(kind=kind, indices=indices, index=index)


def _card(suit: str, rank: str, *, debuffed: bool = False) -> dict:
    return {
        "key": f"{suit}_{rank}",
        "value": {"suit": suit, "rank": rank},
        "state": {"debuff": True} if debuffed else {},
        "cost": {"buy": 0, "sell": 0},
    }


def _card_from_key(key: str) -> dict:
    suit, rank = key.split("_", 1)
    return _card(suit, rank)


def _fast_card(suit: str, rank_value: str) -> int:
    suit_index = {"S": 0, "H": 1, "C": 2, "D": 3}[suit]
    rank_index = {"2": 0, "3": 1, "4": 2, "5": 3, "6": 4}[rank_value]
    return suit_index * 13 + rank_index


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

_ANTE_FIVE_SEARCH_DECK = (
    "D_J",
    "S_A",
    "S_7",
    "C_7",
    "S_6",
    "S_T",
    "D_6",
    "H_9",
    "S_2",
    "S_J",
    "H_2",
    "D_7",
    "D_T",
    "D_5",
    "S_Q",
    "S_K",
    "D_9",
    "C_T",
    "S_9",
    "S_4",
    "H_J",
    "H_3",
    "C_4",
    "C_5",
    "D_K",
    "H_5",
    "D_2",
    "H_K",
    "S_8",
    "D_8",
    "C_J",
    "C_8",
    "D_Q",
    "C_9",
    "S_5",
    "C_6",
    "S_3",
    "H_6",
    "C_2",
    "H_4",
    "D_A",
    "H_8",
    "C_3",
)
