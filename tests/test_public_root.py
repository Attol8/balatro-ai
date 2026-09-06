from __future__ import annotations

import inspect
from dataclasses import replace

import pytest

from balatro_ai_v2.actions import (
    BuyPack,
    ChoosePackCard,
    LeaveShop,
    ReorderConsumables,
    ReorderHand,
    ReorderJokers,
    RerollShop,
    SelectBlind,
    SkipBlind,
    iter_legal_actions,
)
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
    yield from _organic_states(seed, Phase.BLIND_SELECT, limit)


def _organic_states(seed: str, phase: Phase, limit: int = 5):
    backend = JackdawBackend()
    backend.reset(RunSpec("RED", "WHITE", seed))
    policy = PublicStrategicPolicy()
    observation = backend.current_public
    history: list[PublicHistoryStep] = []
    produced = 0
    try:
        assert observation is not None
        while not observation.terminal and len(history) < 200 and produced < limit:
            if observation.phase == phase:
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


def test_shop_roots_round_trip_and_accept_every_decision_root() -> None:
    checked = 0
    for observation, history in _organic_states("11", Phase.SHOP, limit=10):
        root = construct_public_root(observation, history, "shop-roundtrip", 0)
        frozen = freeze_backend(root)
        root.close()
        assert frozen.current_public == observation
        for action in iter_legal_actions(observation):
            if isinstance(action, (ReorderConsumables, ReorderHand, ReorderJokers)):
                continue
            clone = frozen.clone()
            try:
                result = clone.step(action)
                assert result.status == "accepted", (action, result.error)
            finally:
                clone.close()
        next_kind = next(
            blind.kind for blind in observation.blinds if blind.status == "UPCOMING"
        )
        progression = frozen.clone()
        try:
            left = progression.step(LeaveShop())
            assert left.status == "accepted", left.error
            after = progression.current_public
            assert after is not None and after.phase == Phase.BLIND_SELECT
            assert next(
                blind.kind for blind in after.blinds if blind.status == "SELECT"
            ) == next_kind
        finally:
            progression.close()
        checked += 1
    assert checked == 10


def test_shop_root_standard_pack_pick_updates_permanent_deck() -> None:
    observation, history = next(
        (observation, history)
        for observation, history in _organic_states("1", Phase.SHOP, limit=10)
        if any(pack.key == "p_standard_normal" for pack in observation.packs)
    )
    pack_index = next(
        index
        for index, pack in enumerate(observation.packs)
        if pack.key == "p_standard_normal"
    )
    root = construct_public_root(observation, history, "standard-pack", 0)
    try:
        buy = next(
            action
            for action in iter_legal_actions(observation)
            if isinstance(action, BuyPack) and action.pack.value == pack_index
        )
        opened = root.step(buy)
        assert opened.status == "accepted", opened.error
        pack = root.current_public
        assert pack is not None and pack.phase == Phase.PACK
        choice = next(
            action
            for action in iter_legal_actions(pack)
            if isinstance(action, ChoosePackCard)
        )
        picked = root.step(choice)
        assert picked.status == "accepted", picked.error
        after = root.current_public
        assert after is not None
        assert after.deck_size == observation.deck_size + 1
    finally:
        root.close()


def test_shop_root_reconstructs_paid_and_chaos_rerolls() -> None:
    paid, paid_history = next(
        (observation, history)
        for observation, history in _organic_states("1", Phase.SHOP, limit=15)
        if observation.round.reroll_cost == 6
        and observation.money >= observation.round.reroll_cost
    )
    paid_root = construct_public_root(paid, paid_history, "paid-reroll", 0)
    try:
        game_state = paid_root._backend._gs
        assert game_state["round_resets"]["reroll_cost"] == 5
        assert game_state["current_round"]["reroll_cost_increase"] == 1
        rerolled = paid_root.step(RerollShop())
        assert rerolled.status == "accepted", rerolled.error
        assert paid_root.current_public is not None
        assert paid_root.current_public.round.reroll_cost == 7
        assert paid_root.step(LeaveShop()).status == "accepted"
        blind = paid_root.current_public
        assert blind is not None and blind.phase == Phase.BLIND_SELECT
        select = next(
            action
            for action in iter_legal_actions(blind)
            if isinstance(action, SelectBlind)
        )
        assert paid_root.step(select).status == "accepted"
        assert game_state["current_round"]["reroll_cost_increase"] == 0
        assert game_state["current_round"]["reroll_cost"] == 5
    finally:
        paid_root.close()

    chaos, chaos_history = next(
        (observation, history)
        for observation, history in _organic_states("28", Phase.SHOP, limit=20)
        if observation.round.reroll_cost == 0
    )
    chaos_root = construct_public_root(chaos, chaos_history, "chaos-reroll", 0)
    try:
        game_state = chaos_root._backend._gs
        assert game_state["round_resets"]["reroll_cost"] == 5
        assert game_state["current_round"]["free_rerolls"] == 1
        assert chaos_root.step(RerollShop()).status == "accepted"
        assert chaos_root.current_public is not None
        assert chaos_root.current_public.round.reroll_cost == 5
    finally:
        chaos_root.close()


def test_public_roots_reconstruct_publicly_derivable_pool_lifecycle() -> None:
    source = JackdawBackend()
    source.reset(RunSpec("RED", "WHITE", "11"))
    policy = PublicStrategicPolicy()
    observation = source.current_public
    history: list[PublicHistoryStep] = []
    checked = 0
    try:
        assert observation is not None
        while not observation.terminal and checked < 16:
            if observation.phase in {Phase.BLIND_SELECT, Phase.SHOP}:
                source_state = source._backend._gs
                expected = {
                    "bosses_used": dict(source_state["bosses_used"]),
                    "first_shop_buffoon": source_state.get(
                        "first_shop_buffoon", False
                    ),
                    "pool_flags": dict(source_state.get("pool_flags", {})),
                    "used_jokers": dict(source_state["used_jokers"]),
                }
                root = construct_public_root(
                    observation,
                    tuple(history),
                    "lifecycle",
                    0,
                )
                try:
                    root_state = root._backend._gs
                    assert {
                        "bosses_used": root_state["bosses_used"],
                        "first_shop_buffoon": root_state.get(
                            "first_shop_buffoon", False
                        ),
                        "pool_flags": root_state.get("pool_flags", {}),
                        "used_jokers": root_state["used_jokers"],
                    } == expected
                finally:
                    root.close()
                checked += 1
            action = policy.choose_action(
                observation,
                lambda: iter_legal_actions(observation),
                tuple(history),
            )
            result = source.step(action)
            assert result.status == "accepted", result.error
            after = source.current_public
            assert after is not None
            history.append(PublicHistoryStep(observation, action, after))
            observation = after
    finally:
        source.close()
    assert checked == 16


@pytest.mark.parametrize(
    ("seed", "key"),
    (
        ("4", "j_green_joker"),
        ("38", "j_castle"),
        ("27", "j_flash"),
        ("46", "j_stencil"),
    ),
)
def test_publicly_derivable_runtime_jokers_round_trip(
    seed: str,
    key: str,
) -> None:
    observation, history = next(
        (observation, history)
        for observation, history in _organic_states(seed, Phase.SHOP, limit=15)
        if any(
            isinstance(joker, PublicItem) and joker.key == key
            for joker in (*observation.jokers, *observation.shop)
        )
    )
    root = construct_public_root(observation, history, f"runtime-{key}", 0)
    try:
        assert root.current_public == observation
    finally:
        root.close()


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

    # SHOP is also searched from a freshly constructed public root.
    shop, shop_history = next(iter(_organic_states("11", Phase.SHOP, limit=1)))
    shop_action = policy.choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        shop_history,
    )
    assert shop_action in tuple(iter_legal_actions(shop))
    assert policy.last_decision is not None
    assert policy.last_decision.unavailable_reason is None

    # The constructor's unsupported PACK error is contained by search and the
    # public continuation remains authoritative for the fallback action.
    pack, pack_history = next(iter(_organic_states("11", Phase.PACK, limit=1)))
    baseline = continuation.choose_action(
        pack,
        lambda: iter_legal_actions(pack),
        pack_history,
    )
    fallback = policy.choose_action(
        pack,
        lambda: iter_legal_actions(pack),
        pack_history,
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
