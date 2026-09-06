from __future__ import annotations

import inspect
from dataclasses import replace

import pytest

from balatro_ai_v2.actions import SkipBlind, iter_legal_actions
from balatro_ai_v2.backend import RunSpec
from balatro_ai_v2.baselines import PublicStrategicPolicy
from balatro_ai_v2.determinize import (
    DeterminizationUnavailable,
    canonical_private_state,
    freeze_backend,
)
from balatro_ai_v2.determinized_search import DeterminizedSearchPolicy, RolloutBudget
from balatro_ai_v2.jackdaw import JackdawBackend
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.public_root import construct_public_root, public_root_seed
from balatro_ai_v2.public_state import Phase, PublicItem


def _blind_select_states(seed: str, limit: int = 5):
    backend = JackdawBackend()
    backend.reset(RunSpec("RED", "WHITE", seed))
    policy = PublicStrategicPolicy()
    observation = backend.current_public
    history: list[PublicHistoryStep] = []
    produced = 0
    try:
        assert observation is not None
        while not observation.terminal and len(history) < 200 and produced < limit:
            if observation.phase == Phase.BLIND_SELECT:
                produced += 1
                yield observation, tuple(history)
            action = policy.choose_action(
                observation,
                lambda: iter_legal_actions(observation),
                tuple(history),
            )
            result = backend.step(action)
            assert result.status == "accepted", result.error
            after = backend.current_public
            assert after is not None
            history.append(PublicHistoryStep(observation, action, after))
            observation = after
    finally:
        backend.close()


def test_public_root_api_accepts_only_public_inputs() -> None:
    assert tuple(inspect.signature(construct_public_root).parameters) == (
        "observation",
        "history",
        "nonce",
        "index",
    )


def test_fresh_blind_select_roots_round_trip_at_initial_and_later_antes() -> None:
    checked = 0
    reached_later_ante = False
    for observation, history in _blind_select_states("11", limit=10):
        root = construct_public_root(observation, history, "roundtrip", 0)
        try:
            assert root.current_public == observation
            checked += 1
            reached_later_ante |= observation.ante >= 2
        finally:
            root.close()
    assert checked == 10
    assert reached_later_ante


def test_same_public_particle_is_deterministic_and_other_particles_are_hidden_twins() -> None:
    observation, history = next(iter(_blind_select_states("7", limit=1)))
    roots = [
        construct_public_root(observation, history, "twins", index)
        for index in (0, 0, 1)
    ]
    try:
        states = [canonical_private_state(root._backend._gs) for root in roots]
        assert states[0] == states[1]
        assert states[0] != states[2]
        assert all(root.current_public == observation for root in roots)
        assert public_root_seed(observation, history, "twins", 0) == public_root_seed(
            observation, history, "twins", 0
        )
        assert public_root_seed(observation, history, "twins", 0) != public_root_seed(
            observation, history, "twins", 1
        )
    finally:
        for root in roots:
            root.close()


def test_frozen_branch_restores_card_counter_before_shop_creation() -> None:
    observation, history = next(iter(_blind_select_states("7", limit=1)))
    root = construct_public_root(observation, history, "card-counter", 0)
    frozen = freeze_backend(root)
    root.close()

    def play_to_shop():
        clone = frozen.clone()
        policy = PublicStrategicPolicy()
        current = clone.current_public
        trajectory: list[PublicHistoryStep] = []
        try:
            assert current is not None
            for _ in range(60):
                if current.phase == Phase.SHOP:
                    return canonical_private_state(clone._backend._gs)
                action = policy.choose_action(
                    current,
                    lambda: iter_legal_actions(current),
                    tuple(trajectory),
                )
                result = clone.step(action)
                assert result.status == "accepted", result.error
                after = clone.current_public
                assert after is not None
                trajectory.append(PublicHistoryStep(current, action, after))
                current = after
            raise AssertionError("constructed branch did not reach a shop")
        finally:
            clone.close()

    first = play_to_shop()
    from jackdaw.engine.card_factory import create_joker

    for _ in range(20):
        create_joker("j_joker")
    second = play_to_shop()
    assert first == second


def test_existing_search_consumes_fresh_public_roots_and_falls_back_elsewhere() -> None:
    observation, history = next(iter(_blind_select_states("7", limit=1)))
    continuation = PublicStrategicPolicy()
    policy = DeterminizedSearchPolicy(
        backend=None,
        continuation=continuation,
        root_factory=construct_public_root,
        nonce="public-search",
        budget=RolloutBudget(samples=1, horizon_antes=1, max_steps=80, override_z=1),
    )
    selected = policy.choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        history,
    )
    assert selected in tuple(iter_legal_actions(observation))
    assert policy.last_decision is not None
    assert policy.last_decision.unavailable_reason is None
    assert policy.counters.searched == 1

    # The constructor's unsupported-phase error is contained by search and the
    # public continuation remains authoritative for the fallback action.
    source = iter(_blind_select_states("11", limit=2))
    next(source)
    _, later_history = next(source)
    shop_step = next(step for step in later_history if step.before.phase == Phase.SHOP)
    baseline = continuation.choose_action(
        shop_step.before,
        lambda: iter_legal_actions(shop_step.before),
        (),
    )
    fallback = policy.choose_action(
        shop_step.before,
        lambda: iter_legal_actions(shop_step.before),
        (),
    )
    assert fallback == baseline
    assert policy.last_decision is not None
    assert "no fresh public constructor" in (policy.last_decision.unavailable_reason or "")


def test_noninitial_root_requires_contiguous_complete_public_history() -> None:
    states = list(_blind_select_states("11", limit=4))
    observation, history = states[-1]
    assert history
    with pytest.raises(DeterminizationUnavailable, match="complete history"):
        construct_public_root(observation, (), "bad", 0)
    with pytest.raises(DeterminizationUnavailable, match="not contiguous"):
        construct_public_root(observation, history[1:], "bad", 0)
    with pytest.raises(DeterminizationUnavailable, match="does not end"):
        construct_public_root(observation, history[:-1], "bad", 0)


def test_unsupported_phase_and_deck_boundary_fail_closed() -> None:
    states = iter(_blind_select_states("11", limit=2))
    initial, _ = next(states)
    later, history = next(states)
    selecting = next(step.before for step in history if step.before.phase == Phase.SELECTING_HAND)
    with pytest.raises(DeterminizationUnavailable, match="no fresh public constructor"):
        construct_public_root(selecting, (), "bad", 0)

    malformed = replace(initial, draw_count=initial.draw_count - 1)
    with pytest.raises(DeterminizationUnavailable, match="draw count"):
        construct_public_root(malformed, (), "bad", 0)

    # The current certified slice deliberately rejects retained skip-tag state.
    selectable = next(
        action for action in iter_legal_actions(initial) if isinstance(action, SkipBlind)
    )
    synthetic_history = (PublicHistoryStep(initial, selectable, later),)
    with pytest.raises(DeterminizationUnavailable, match="skip-tag"):
        construct_public_root(later, synthetic_history, "bad", 0)

    missing_runtime = replace(
        initial,
        jokers=(PublicItem("j_caino", "Canio", "JOKER"),),
    )
    with pytest.raises(DeterminizationUnavailable, match="lacks complete public runtime"):
        construct_public_root(missing_runtime, (), "bad", 0)

    boss = next(blind for blind in initial.blinds if blind.kind == "BOSS")
    unsupported_boss = replace(
        initial,
        blinds=tuple(
            replace(blind, name="The Pillar") if blind is boss else blind
            for blind in initial.blinds
        ),
    )
    with pytest.raises(DeterminizationUnavailable, match="absent from the public contract"):
        construct_public_root(unsupported_boss, (), "bad", 0)
