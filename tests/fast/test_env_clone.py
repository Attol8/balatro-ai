from copy import deepcopy
from dataclasses import fields

from balatro_ai_v2.fast.full_game import (
    CASH_OUT_ACTION,
    SELECT_BLIND_ACTION,
    FastFullGameEnv,
)
from balatro_ai_v2.fast.jokers import Joker
from balatro_ai_v2.fast.run import RunPhase


def _mid_run_env() -> FastFullGameEnv:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=7)
    env.jokers = [Joker(key="j_green_joker", scaling=3, sell_value=2)]
    env.consumables = ["c_pluto"]
    env.tags.append("tag_charm")
    env.step(SELECT_BLIND_ACTION)
    while env.run.phase == RunPhase.SELECTING_HAND:
        env.step(env.greedy_play_action())
    if env.run.phase == RunPhase.ROUND_EVAL:
        env.step(CASH_OUT_ACTION)
    return env


def test_clone_matches_deepcopy_observation_and_actions() -> None:
    env = _mid_run_env()
    clone = env.clone()
    copied = deepcopy(env)

    assert clone.observation() == copied.observation()
    assert clone.legal_action_ids() == copied.legal_action_ids()
    for spec in fields(env):
        assert getattr(clone, spec.name) == getattr(env, spec.name), spec.name


def test_clone_is_independent_under_mutation() -> None:
    env = _mid_run_env()
    clone = env.clone()

    action = clone.legal_action_ids()[0]
    clone.step(action)
    clone.run.money += 100
    clone.jokers.append(Joker(key="j_joker", sell_value=1))
    clone.hand_levels[0] += 5
    clone.tags.append("tag_skip")
    clone.deck_cards.append(0)

    fresh = _mid_run_env()
    assert env.observation() == fresh.observation()
    assert env.run.money == fresh.run.money
    assert len(env.jokers) == len(fresh.jokers)
    assert env.hand_levels == fresh.hand_levels
    assert env.tags == fresh.tags
    assert env.deck_cards == fresh.deck_cards


def test_clone_replays_identically_to_source_env() -> None:
    env = _mid_run_env()
    clone = env.clone()

    for _ in range(20):
        actions = env.legal_action_ids()
        if not actions:
            break
        action = actions[0]
        first = env.step(action)
        second = clone.step(action)
        assert first.observation == second.observation
        assert first.terminated == second.terminated
        if first.terminated:
            break
