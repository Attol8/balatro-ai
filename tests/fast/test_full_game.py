from random import Random

from balatro_ai_v2.fast.full_game import (
    BUY_CARD_ACTION_BASE,
    BUY_PACK_ACTION_BASE,
    BUY_VOUCHER_ACTION,
    CASH_OUT_ACTION,
    NEXT_ROUND_ACTION,
    PACK_SELECT_ACTION_BASE,
    REROLL_ACTION,
    SELL_JOKER_ACTION_BASE,
    SELECT_BLIND_ACTION,
    USE_CONSUMABLE_ACTION_BASE,
    FastFullGameEnv,
    RolloutSearchRunAgent,
    SearchRunAgent,
    evaluate_agent,
)
from balatro_ai_v2.fast.jokers import Joker
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


def test_rollout_search_agent_scores_shop_candidates_without_replacing_default() -> None:
    class TinyRolloutAgent(RolloutSearchRunAgent):
        shop_rollout_candidates = 2
        shop_rollout_steps = 2

    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=3)
    env.run.phase = RunPhase.SHOP
    env.run.money = 8
    env.available_voucher = None
    env.run.shop.item_keys = ["j_joker", "c_pluto"]

    action = TinyRolloutAgent().act(env)

    assert SearchRunAgent.shop_rollout_candidates == 0
    assert RolloutSearchRunAgent.shop_rollout_candidates > 0
    assert RolloutSearchRunAgent.beam_width == 2
    assert RolloutSearchRunAgent.action_beam == 1
    assert action in env.legal_action_ids()


def test_search_agent_does_not_sell_joker_without_visible_upgrade() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=5)
    env.run.phase = RunPhase.SHOP
    env.run.money = 0
    env.jokers = [Joker("j_joker", sell_value=1) for _ in range(env.run.joker_slots)]
    env.run.shop.item_keys = ["c_pluto", "c_mercury"]

    action = SearchRunAgent().act(env)

    assert not SELL_JOKER_ACTION_BASE <= action < SELL_JOKER_ACTION_BASE + 8


def test_search_agent_sells_weak_joker_for_visible_upgrade() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=5)
    env.run.phase = RunPhase.SHOP
    env.run.money = 5
    env.jokers = [
        Joker("j_joker", sell_value=1),
        Joker("j_square", sell_value=1),
        Joker("j_mystic_summit", sell_value=1),
        Joker("j_bull", sell_value=1),
        Joker("j_abstract", sell_value=1),
    ]
    env.run.shop.item_keys = ["j_cavendish"]

    action = SearchRunAgent().act(env)

    assert SELL_JOKER_ACTION_BASE <= action < SELL_JOKER_ACTION_BASE + 8


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


def test_mega_pack_applies_two_consumables_immediately() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=4)
    env.run.phase = RunPhase.PACK
    env.run.money = 10
    env.pack_cards = ["c_hermit", "c_mercury", "c_jupiter"]
    env.pack_choices = 2

    env.step(PACK_SELECT_ACTION_BASE)

    assert env.run.phase == RunPhase.PACK
    assert env.run.money == 20
    assert env.consumables == []

    env.step(PACK_SELECT_ACTION_BASE)

    assert env.run.phase == RunPhase.SHOP
    assert env.hand_levels[1] == 2


def test_fast_pack_generation_includes_arcana_tarots() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=4)

    cards = env._generate_pack_cards("p_arcana_mega_1")

    assert cards
    assert all(key.startswith("c_") for key in cards)
    assert any(key in {"c_hermit", "c_high_priestess", "c_judgement"} for key in cards)


def test_first_shop_pack_has_source_buffoon_guarantee() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=4)
    env.run.phase = RunPhase.SHOP
    env.run.ante = 1
    env.run.round_num = 0

    assert env._pack_keys()[0].startswith("p_buffoon_normal_")


def test_search_agent_buys_arcana_pack() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=3)
    env.run.phase = RunPhase.SHOP
    env.run.money = 12
    env.run.shop.item_keys = []

    action = SearchRunAgent().act(env)

    assert action == BUY_PACK_ACTION_BASE


def test_search_agent_does_not_go_broke_on_arcana_pack() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=3)
    env.run.phase = RunPhase.SHOP
    env.run.ante = 2
    env.run.round_num = 1
    env.run.money = 6
    env.run.shop.item_keys = []

    action = SearchRunAgent().act(env)

    assert action != BUY_PACK_ACTION_BASE


def test_buffoon_pack_does_not_offer_owned_jokers() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=4)
    env.jokers = [Joker("j_joker"), Joker("j_abstract")]

    cards = env._generate_pack_cards("p_buffoon_mega_1")

    assert "j_joker" not in cards
    assert "j_abstract" not in cards


def test_shop_generation_does_not_offer_owned_jokers() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=4)
    env.jokers = [Joker(key) for key in ("j_joker", "j_abstract", "j_bull", "j_square", "j_mystic_summit")]

    pool = env._available_shop_card_pool()

    assert "j_joker" not in pool
    assert "j_abstract" not in pool


def test_shop_generation_uses_source_shaped_joker_pool() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=4)

    pool = env._available_shop_card_pool()

    assert len(pool) > 50
    assert "j_photograph" in pool
    # Unimplemented source jokers are excluded so rollouts never buy dead cards.
    assert "j_8_ball" not in pool
    from balatro_ai_v2.fast.jokers import IMPLEMENTED_JOKERS

    assert all(key in IMPLEMENTED_JOKERS for key in pool if key.startswith("j_"))


def test_packs_deplete_when_bought() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=1)
    env.run.phase = RunPhase.SHOP
    env.run.money = 50

    pack_actions = [a for a in env.legal_action_ids() if BUY_PACK_ACTION_BASE <= a < BUY_PACK_ACTION_BASE + 8]
    assert pack_actions
    env.step(pack_actions[0])
    while env.run.phase == RunPhase.PACK:
        env.step(env.legal_action_ids()[-1])

    remaining = [a for a in env.legal_action_ids() if BUY_PACK_ACTION_BASE <= a < BUY_PACK_ACTION_BASE + 8]
    assert pack_actions[0] not in remaining

    try:
        env.step(pack_actions[0])
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_voucher_generation_respects_upgrade_requirements() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=4)

    seen = {env._generate_voucher(Random(seed)) for seed in range(100)}

    assert "v_overstock_plus" not in seen
    env.purchased_vouchers.append("v_overstock_norm")
    seen_after_purchase = {env._generate_voucher(Random(seed)) for seed in range(100)}
    assert "v_overstock_plus" in seen_after_purchase


def test_full_game_targeted_tarots_mutate_persistent_deck_cards() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=4)
    env.run.phase = RunPhase.SHOP
    env.run.hand = [0, 12, 25, 38]
    env.deck_cards = [0, 12, 25, 38, 5]
    env.consumables = ["c_hanged_man"]

    env.step(USE_CONSUMABLE_ACTION_BASE)

    assert len(env.deck_cards) == 3
    assert 0 not in env.deck_cards
    assert 12 not in env.deck_cards


def test_full_game_death_and_strength_modify_deck_composition() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=4)
    env.run.phase = RunPhase.SHOP
    env.run.hand = [0, 5, 12]
    env.deck_cards = [0, 5, 12]
    env.consumables = ["c_death", "c_strength"]

    env.step(USE_CONSUMABLE_ACTION_BASE)

    assert 12 in env.deck_cards
    assert 0 not in env.deck_cards

    env.step(USE_CONSUMABLE_ACTION_BASE)

    assert any(card % 13 == 6 for card in env.deck_cards)


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
