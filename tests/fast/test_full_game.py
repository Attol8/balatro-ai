from balatro_ai_v2.fast.full_game import (
    BUY_CARD_ACTION_BASE,
    BUY_VOUCHER_ACTION,
    CASH_OUT_ACTION,
    NEXT_ROUND_ACTION,
    PACK_SELECT_ACTION_BASE,
    REROLL_ACTION,
    SELECT_BLIND_ACTION,
    FastFullGameEnv,
    SearchRunAgent,
    evaluate_agent,
)
from balatro_ai_v2.fast.run import RunPhase


def test_full_game_reset_is_deterministic() -> None:
    env = FastFullGameEnv(deck_key="b_red")

    first = env.reset(seed=42)
    second = env.reset(seed=42)

    assert first == second
    assert env.run.phase == RunPhase.BLIND_SELECT
    assert SELECT_BLIND_ACTION in env.legal_action_ids()


def test_full_game_exposes_blind_round_eval_and_shop_actions() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=1)

    result = env.step(SELECT_BLIND_ACTION)

    assert result.info["phase_action"] == "select_blind"
    assert env.run.phase == RunPhase.SELECTING_HAND
    while env.run.phase == RunPhase.SELECTING_HAND:
        result = env.step(env.greedy_play_action())

    assert env.run.phase == RunPhase.ROUND_EVAL
    assert CASH_OUT_ACTION in env.legal_action_ids()

    result = env.step(CASH_OUT_ACTION)

    assert result.info["phase_action"] == "cash_out"
    assert env.run.phase == RunPhase.SHOP
    assert env.run.shop.item_keys
    assert NEXT_ROUND_ACTION in env.legal_action_ids()


def test_full_game_shop_buy_is_explicit() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=1)
    env.run.phase = RunPhase.SHOP
    env.run.money = 10
    env.run.shop.item_keys = ["j_joker", "c_jupiter"]

    result = env.step(BUY_CARD_ACTION_BASE)

    assert result.info["phase_action"] == "buy:j_joker"
    assert [joker.key for joker in env.jokers] == ["j_joker"]
    assert env.run.money == 8
    assert env.run.shop.item_keys == ["c_jupiter"]


def test_full_game_shop_voucher_buy_applies_run_modifier() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=1)
    env.run.phase = RunPhase.SHOP
    env.run.money = 20
    env.available_voucher = "v_grabber"

    result = env.step(BUY_VOUCHER_ACTION)

    assert result.info["phase_action"] == "buy_voucher:v_grabber"
    assert env.run.money == 10
    assert env.run.hands == 5
    assert env.available_voucher is None
    assert env.purchased_vouchers == ["v_grabber"]


def test_full_game_shop_slots_and_observation_stay_stable_after_voucher() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=2)
    env.run.phase = RunPhase.SHOP
    env.run.money = 20
    before_len = len(env.observation())
    env.available_voucher = "v_overstock_norm"

    env.step(BUY_VOUCHER_ACTION)
    env.step(REROLL_ACTION)

    assert env.run.shop_slots == 3
    assert len(env.run.shop.item_keys) == 3
    assert len(env.observation()) == before_len


def test_search_agent_can_choose_high_value_voucher_before_cards() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=3)
    env.run.phase = RunPhase.SHOP
    env.run.money = 20
    env.available_voucher = "v_antimatter"
    env.run.shop.item_keys = ["c_pluto", "c_mercury"]

    assert SearchRunAgent().act(env) == BUY_VOUCHER_ACTION


def test_mega_pack_allows_multiple_selections_before_returning_to_shop() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=4)
    env.run.phase = RunPhase.PACK
    env.pack_cards = ["c_pluto", "c_mercury", "c_jupiter"]
    env.pack_choices = 2

    env.step(PACK_SELECT_ACTION_BASE)

    assert env.run.phase == RunPhase.PACK
    assert env.pack_cards == ["c_mercury", "c_jupiter"]

    env.step(PACK_SELECT_ACTION_BASE)

    assert env.run.phase == RunPhase.SHOP
    assert env.pack_cards == []


def test_search_agent_runs_first_red_deck_seed_without_fixed_flush_target() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    agent = SearchRunAgent()
    env.reset(seed=1)

    for _ in range(12):
        result = env.step(agent.act(env))
        if result.terminated:
            break

    assert env.rounds_cleared > 0
    assert len(env.hand_play_counts) == len(env.hand_levels)
    assert env.hand_play_counts[5] < sum(env.hand_play_counts)


def test_search_agent_evaluates_multiple_seeds_without_claiming_solve() -> None:
    metrics = evaluate_agent(range(1, 3), deck_key="b_red", max_steps=12)

    assert metrics["seeds"] == 2
    assert 0 <= metrics["wins"] <= 2
    assert 0.0 <= metrics["win_rate"] <= 1.0
    assert metrics["avg_rounds_cleared"] > 0
