from balatro_ai_v2.fast.env import DISCARD_ACTION_OFFSET
from balatro_ai_v2.fast.full_game import (
    BUY_CARD_ACTION_BASE,
    CASH_OUT_ACTION,
    SELECT_BLIND_ACTION,
    SELL_JOKER_ACTION_BASE,
    USE_CONSUMABLE_ACTION_BASE,
    FastFullGameEnv,
)
from balatro_ai_v2.fast.jokers import Joker
from balatro_ai_v2.fast.run import BlindKind, RunPhase


def _blind_env(seed: int = 1) -> FastFullGameEnv:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=seed)
    env.step(SELECT_BLIND_ACTION)
    return env


def test_green_joker_scales_up_on_play_and_down_on_discard() -> None:
    env = _blind_env()
    env.jokers = [Joker(key="j_green_joker", scaling=2, sell_value=1)]

    env.step(DISCARD_ACTION_OFFSET + 0b1)
    assert env.jokers[0].scaling == 1

    env.step(env.greedy_play_action())
    assert env.jokers[0].scaling == 2


def test_ice_cream_decays_per_play_and_melts() -> None:
    env = _blind_env()
    env.jokers = [Joker(key="j_ice_cream", scaling=10, sell_value=2)]

    env.step(env.greedy_play_action())
    assert env.jokers[0].scaling == 5

    if env.run.phase == RunPhase.ROUND_EVAL:
        env.run.phase = RunPhase.SELECTING_HAND
        env.run.score = 0
    env.step(env.greedy_play_action())
    assert not env.jokers


def test_ramen_loses_x_mult_per_discarded_card() -> None:
    env = _blind_env()
    env.jokers = [Joker(key="j_ramen", x_mult=2.0, sell_value=2)]

    env.step(DISCARD_ACTION_OFFSET + 0b111)

    assert env.jokers[0].x_mult == 1.97


def test_popcorn_decays_each_round_and_burns_out() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=1)
    env.run.phase = RunPhase.ROUND_EVAL
    env.jokers = [Joker(key="j_popcorn", scaling=8, sell_value=2)]

    env.step(CASH_OUT_ACTION)
    assert env.jokers[0].scaling == 4

    env.run.phase = RunPhase.ROUND_EVAL
    env.step(CASH_OUT_ACTION)
    assert not env.jokers


def test_golden_joker_pays_at_cash_out() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=1)
    env.run.phase = RunPhase.ROUND_EVAL
    baseline = FastFullGameEnv(deck_key="b_red")
    baseline.reset(seed=1)
    baseline.run.phase = RunPhase.ROUND_EVAL
    env.jokers = [Joker(key="j_golden", sell_value=2)]

    env.step(CASH_OUT_ACTION)
    baseline.step(CASH_OUT_ACTION)

    assert env.run.money - baseline.run.money == 4


def test_rocket_bumps_on_boss_defeat_and_pays_bumped_amount() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=1)
    env.run.phase = RunPhase.ROUND_EVAL
    env.run.blind_kind = BlindKind.BOSS
    baseline = FastFullGameEnv(deck_key="b_red")
    baseline.reset(seed=1)
    baseline.run.phase = RunPhase.ROUND_EVAL
    baseline.run.blind_kind = BlindKind.BOSS
    env.jokers = [Joker(key="j_rocket", scaling=1, sell_value=2)]

    env.step(CASH_OUT_ACTION)
    baseline.step(CASH_OUT_ACTION)

    assert env.jokers[0].scaling == 3
    assert env.run.money - baseline.run.money == 3


def test_cloud_9_pays_per_nine_in_deck() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=1)
    env.run.phase = RunPhase.ROUND_EVAL
    baseline = FastFullGameEnv(deck_key="b_red")
    baseline.reset(seed=1)
    baseline.run.phase = RunPhase.ROUND_EVAL
    env.jokers = [Joker(key="j_cloud_9", sell_value=2)]

    env.step(CASH_OUT_ACTION)
    baseline.step(CASH_OUT_ACTION)

    assert env.run.money - baseline.run.money == 4


def test_drunkard_grants_discard_and_sell_reverts_it() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=1)
    base_discards = env.run.discards
    env.run.phase = RunPhase.SHOP
    env.run.money = 20
    env.run.shop.item_keys = ["j_drunkard"]

    env.step(BUY_CARD_ACTION_BASE)
    assert env.run.discards == base_discards + 1

    env.step(SELL_JOKER_ACTION_BASE)
    assert env.run.discards == base_discards


def test_constellation_grows_when_planet_used() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=1)
    env.run.phase = RunPhase.SHOP
    env.jokers = [Joker(key="j_constellation", x_mult=1.0, sell_value=2)]
    env.consumables = ["c_pluto"]

    env.step(USE_CONSUMABLE_ACTION_BASE)

    assert env.jokers[0].x_mult == 1.1
    assert "c_pluto" in env.planets_used
