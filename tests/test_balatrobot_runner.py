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
from balatro_ai_v2.balatrobot.shop_planner import plan_pack_action, plan_shop_action
from balatro_ai_v2.balatrobot.tactical_planner import _jokers_after_play
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

    assert decision.action is None


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


def _card(suit: str, rank: str) -> dict:
    return {"key": f"{suit}_{rank}", "value": {"suit": suit, "rank": rank}, "cost": {"buy": 0, "sell": 0}}


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
