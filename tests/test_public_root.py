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
    SkipPack,
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
from balatro_ai_v2.public_state import Phase, PublicItem, PublicJokerRuntime


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


def _pack_kind_for_key(key: str) -> str | None:
    return next(
        (
            kind
            for prefix, kind in {
                "p_arcana_": "ARCANA",
                "p_celestial_": "CELESTIAL",
                "p_spectral_": "SPECTRAL",
                "p_standard_": "STANDARD",
                "p_buffoon_": "BUFFOON",
            }.items()
            if key.startswith(prefix)
        ),
        None,
    )


def _all_vanilla_pack_states():
    wanted = {"ARCANA", "CELESTIAL", "SPECTRAL", "STANDARD", "BUFFOON"}
    found = {}
    backend = JackdawBackend()
    backend.reset(RunSpec("RED", "WHITE", "1"))
    policy = PublicStrategicPolicy()
    observation = backend.current_public
    history: list[PublicHistoryStep] = []
    try:
        assert observation is not None
        while not observation.terminal and len(history) < 200 and set(found) != wanted:
            if observation.phase == Phase.PACK:
                found.setdefault(observation.pack_kind, (observation, tuple(history)))
            legal = tuple(iter_legal_actions(observation))
            forced = None
            if observation.phase == Phase.SHOP:
                forced = next(
                    (
                        action
                        for action in legal
                        if isinstance(action, BuyPack)
                        and _pack_kind_for_key(
                            observation.packs[action.pack.value].key
                        )
                        in wanted - set(found)
                    ),
                    None,
                )
            action = forced or policy.choose_action(
                observation,
                lambda: iter(legal),
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
    assert set(found) == wanted
    return found


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


def test_all_vanilla_pack_roots_round_trip_accept_actions_and_return_to_shop() -> None:
    for kind, (observation, history) in _all_vanilla_pack_states().items():
        root = construct_public_root(observation, history, f"pack-{kind}", 0)
        frozen = freeze_backend(root)
        root.close()
        assert frozen.current_public == observation

        for action in iter_legal_actions(observation):
            clone = frozen.clone()
            try:
                result = clone.step(action)
                assert result.status == "accepted", (kind, action, result.error)
            finally:
                clone.close()

        entrance = history[-1]
        assert isinstance(entrance.action, BuyPack)
        skipped = frozen.clone()
        try:
            result = skipped.step(SkipPack())
            assert result.status == "accepted", result.error
            after = skipped.current_public
            assert after is not None and after.phase == Phase.SHOP
            assert after.shop == entrance.before.shop
            assert after.vouchers == entrance.before.vouchers
            assert after.packs == tuple(
                pack
                for index, pack in enumerate(entrance.before.packs)
                if index != entrance.action.pack.value
            )
            assert not after.hand
            assert after.draw_count == after.deck_size
            assert {
                replace(entry.card, effect_text=""): entry.count
                for entry in after.remaining_deck
            } == {
                replace(entry.card, effect_text=""): entry.count
                for entry in after.full_deck
            }
        finally:
            skipped.close()

    spectral, spectral_history = _all_vanilla_pack_states()["SPECTRAL"]
    spectral_root = construct_public_root(
        spectral,
        spectral_history,
        "pack-usage",
        0,
    )
    try:
        state = spectral_root._backend._gs
        assert state["consumable_usage"] == {
            "c_mercury": {"count": 1, "set": "Planet"},
            "c_moon": {"count": 1, "set": "Tarot"},
        }
        assert state["consumable_usage_total"] == {
            "all": 2,
            "planet": 1,
            "spectral": 0,
            "tarot": 1,
            "tarot_planet": 2,
        }
    finally:
        spectral_root.close()


def test_mega_pack_mid_pick_root_preserves_capacity_and_return_shop() -> None:
    backend = JackdawBackend()
    backend.reset(RunSpec("RED", "WHITE", "1"))
    policy = PublicStrategicPolicy()
    observation = backend.current_public
    history: list[PublicHistoryStep] = []
    try:
        assert observation is not None
        for _ in range(100):
            legal = tuple(iter_legal_actions(observation))
            mega = None
            if observation.phase == Phase.SHOP:
                mega = next(
                    (
                        action
                        for action in legal
                        if isinstance(action, BuyPack)
                        and observation.packs[action.pack.value].key == "p_arcana_mega"
                    ),
                    None,
                )
            action = mega or policy.choose_action(
                observation,
                lambda: iter(legal),
                tuple(history),
            )
            result = backend.step(action)
            assert result.status == "accepted", result.error
            after = backend.current_public
            assert after is not None
            history.append(PublicHistoryStep(observation, action, after))
            observation = after
            if mega is not None:
                break
        assert observation.phase == Phase.PACK
        assert observation.pack_choices_remaining == 2
        entrance = history[-1]
        first_pick = next(
            action
            for action in iter_legal_actions(observation)
            if isinstance(action, ChoosePackCard)
        )
        result = backend.step(first_pick)
        assert result.status == "accepted", result.error
        after_pick = backend.current_public
        assert after_pick is not None and after_pick.phase == Phase.PACK
        history.append(PublicHistoryStep(observation, first_pick, after_pick))
    finally:
        backend.close()

    root = construct_public_root(after_pick, tuple(history), "mega-mid-pick", 0)
    try:
        assert root.current_public == after_pick
        assert root._pack_card_limit == 5
        skipped = root.step(SkipPack())
        assert skipped.status == "accepted", skipped.error
        shop = root.current_public
        assert shop is not None and shop.phase == Phase.SHOP
        assert shop.shop == entrance.before.shop
        assert shop.vouchers == entrance.before.vouchers
        assert shop.packs == tuple(
            pack
            for index, pack in enumerate(entrance.before.packs)
            if index != entrance.action.pack.value
        )
    finally:
        root.close()


def test_pack_roots_fail_closed_on_ambiguous_public_state() -> None:
    pack, history = _all_vanilla_pack_states()["ARCANA"]
    def ending_at(observation):
        return (*history[:-1], replace(history[-1], after=observation))

    smods = replace(pack, pack_kind="SMODS")
    with pytest.raises(DeterminizationUnavailable, match="unsupported opened pack"):
        construct_public_root(smods, ending_at(smods), "bad", 0)
    incompatible = replace(
        pack,
        opened_pack=(PublicItem("j_joker", "Joker", "JOKER"),),
    )
    with pytest.raises(DeterminizationUnavailable, match="incompatible public offer"):
        construct_public_root(
            incompatible,
            ending_at(incompatible),
            "bad",
            0,
        )
    empty_hand = replace(pack, hand=())
    with pytest.raises(DeterminizationUnavailable, match="fill the deck"):
        construct_public_root(empty_hand, ending_at(empty_hand), "bad", 0)
    with pytest.raises(DeterminizationUnavailable, match="does not end"):
        construct_public_root(pack, history[:-1], "bad", 0)


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


def test_remaining_stateful_jokers_round_trip_from_public_runtime() -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine.card_factory import create_joker

    source = JackdawBackend()
    source.reset(RunSpec("RED", "WHITE", "7"))
    state = source._backend._gs
    caino = create_joker("j_caino")
    caino.ability["caino_xmult"] = 4.5
    invisible = create_joker("j_invisible")
    invisible.ability["invis_rounds"] = 2
    mail = create_joker("j_mail")
    turtle = create_joker("j_turtle_bean")
    turtle.ability["extra"]["h_size"] = 3
    yorick = create_joker("j_yorick")
    yorick.ability["x_mult"] = 7
    yorick.ability["yorick_discards"] = 11
    state["jokers"] = [caino, invisible, mail, turtle, yorick]
    state["current_round"]["mail_card"] = {"rank": "Queen", "id": 12}
    for joker in state["jokers"]:
        joker.add_to_deck(state)
    source.observe()
    observation = source.current_public
    source.close()
    assert observation is not None

    root = construct_public_root(observation, (), "remaining-runtime", 0)
    try:
        assert root.current_public == observation
        rebuilt = root._backend._gs
        abilities = [joker.ability for joker in rebuilt["jokers"]]
        assert abilities[0]["caino_xmult"] == 4.5
        assert abilities[1]["invis_rounds"] == 2
        assert rebuilt["current_round"]["mail_card"] == {
            "rank": "Queen",
            "id": 12,
        }
        assert abilities[3]["extra"]["h_size"] == 3
        assert (abilities[4]["x_mult"], abilities[4]["yorick_discards"]) == (7, 11)
    finally:
        root.close()


def test_zero_and_progressed_scaling_mult_jokers_round_trip() -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine.card_factory import create_joker

    source = JackdawBackend()
    source.reset(RunSpec("RED", "WHITE", "7"))
    state = source._backend._gs
    ceremonial = create_joker("j_ceremonial")
    ceremonial.ability["mult"] = 0
    trousers = create_joker("j_trousers")
    trousers.ability["mult"] = 6
    state["jokers"] = [ceremonial, trousers]
    for joker in state["jokers"]:
        joker.add_to_deck(state)
    source.observe()
    observation = source.current_public
    source.close()
    assert observation is not None
    assert [joker.runtime.current_mult for joker in observation.jokers] == [0, 6]

    root = construct_public_root(observation, (), "scaling-zero-runtime", 0)
    try:
        assert root.current_public == observation
        assert [
            joker.ability["mult"] for joker in root._backend._gs["jokers"]
        ] == [0, 6]
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

    # PACK now uses the same fresh public-root search path.
    pack, pack_history = next(iter(_organic_states("11", Phase.PACK, limit=1)))
    pack_action = policy.choose_action(
        pack,
        lambda: iter_legal_actions(pack),
        pack_history,
    )
    assert pack_action in tuple(iter_legal_actions(pack))
    assert policy.last_decision is not None
    assert policy.last_decision.unavailable_reason is None
    assert policy.counters.searched == 3


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
    with pytest.raises(DeterminizationUnavailable, match="has no public runtime"):
        construct_public_root(missing_runtime, (), "bad", 0)

    incomplete_yorick = replace(
        initial,
        jokers=(
            PublicItem(
                "j_yorick",
                "Yorick",
                "JOKER",
                runtime=PublicJokerRuntime(current_x_mult=2),
            ),
        ),
    )
    with pytest.raises(DeterminizationUnavailable, match="discard countdown"):
        construct_public_root(incomplete_yorick, (), "bad", 0)

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
