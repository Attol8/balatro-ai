from balatro_ai_v2.fast.full_game import SELECT_BLIND_ACTION, FastFullGameEnv
from balatro_ai_v2.fast.jokers import Joker
from balatro_ai_v2.fast.run import RunPhase
from balatro_ai_v2.planner.evaluation import (
    projected_best_hand_score,
    requirement_curve,
    run_value,
    survival_margin,
)


def _env(seed: int = 1) -> FastFullGameEnv:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=seed)
    return env


def test_run_value_increases_with_money() -> None:
    env = _env()
    base = run_value(env)
    env.run.money += 20
    assert run_value(env) > base


def test_run_value_increases_with_hand_levels() -> None:
    env = _env()
    base = run_value(env)
    env.hand_levels[1] += 2
    assert run_value(env) > base


def test_run_value_increases_with_xmult_joker() -> None:
    env = _env()
    base = run_value(env)
    env.jokers = [Joker(key="j_cavendish", x_mult=3.0, sell_value=2)]
    assert run_value(env) > base


def test_run_value_rewards_win_and_punishes_loss() -> None:
    env = _env()
    env.run.won = True
    env.run.phase = RunPhase.GAME_OVER
    won_value = run_value(env)

    lost = _env()
    lost.run.phase = RunPhase.GAME_OVER
    lost_value = run_value(lost)

    assert won_value > 500_000
    assert lost_value < 0
    assert won_value > lost_value


def test_projection_grows_with_jokers_and_levels() -> None:
    env = _env()
    base = projected_best_hand_score(env)

    env.jokers = [Joker(key="j_cavendish", x_mult=3.0, sell_value=2)]
    boosted = projected_best_hand_score(env)
    assert boosted > base

    env.hand_levels = [level + 3 for level in env.hand_levels]
    leveled = projected_best_hand_score(env)
    assert leveled > boosted


def test_requirement_curve_uses_known_boss_then_worst_case() -> None:
    env = _env()
    env.boss_key = "bl_wall"
    curve = requirement_curve(env, horizon=2)

    assert curve[0] == 300 * 4
    assert curve[1] >= 800 * 2
    assert len(curve) == 3


def test_requirement_curve_stops_at_ante_8() -> None:
    env = _env()
    env.run.ante = 8
    env.boss_key = "bl_final_vessel"
    curve = requirement_curve(env, horizon=2)
    assert curve == (50_000 * 6,)


def test_survival_margin_falls_as_antes_rise() -> None:
    early = _env()
    margin_early = survival_margin(early)

    late = _env()
    late.run.ante = 6
    late._select_boss_for_ante()
    margin_late = survival_margin(late)

    assert margin_early > margin_late


def test_projection_is_boss_neutral() -> None:
    env = _env()
    plain = projected_best_hand_score(env)

    bossy = _env()
    bossy.run.blind_kind = type(bossy.run.blind_kind).BOSS
    bossy.boss_key = "bl_psychic"
    bossy.step(SELECT_BLIND_ACTION)
    bossy.hand_levels = list(env.hand_levels)
    assert projected_best_hand_score(bossy) > 0
    assert abs(projected_best_hand_score(bossy) - plain) < plain
