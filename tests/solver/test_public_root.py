from __future__ import annotations

import inspect
import importlib.util
from dataclasses import replace

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("jackdaw") is None,
    reason="optional Python 3.12 candidate dependency",
)

from balatro_ai_v2.solver.candidate_errors import DeterminizationUnavailable

from balatro_ai_v2.solver.actions import (
    BuyPack,
    ChoosePackCard,
    HandSlot,
    LeaveShop,
    PlayCards,
    ReorderConsumables,
    ReorderHand,
    ReorderJokers,
    RerollShop,
    SelectBlind,
    SkipBlind,
    SkipPack,
    iter_legal_actions,
)
from balatro_ai_v2.solver.backend import RunSpec
from balatro_ai_v2.solver.baselines import PublicStrategicPolicy
from balatro_ai_v2.solver.jackdaw import JackdawBackend
from balatro_ai_v2.solver.policy import PublicHistoryStep
from balatro_ai_v2.solver.public_root import (
    _permanent_card_identity,
    _pillar_played_identities,
    _sample_poker_hand_order,
    construct_public_root,
    public_root_seed,
)
from balatro_ai_v2.solver.public_state import (
    HiddenHandCard,
    Phase,
    PublicItem,
    PublicJokerRuntime,
    VisiblePlayingCard,
)


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


def _organic_boss_select_state(
    seed: str,
    boss_name: str,
):
    backend = JackdawBackend(lightweight=True)
    backend.reset(RunSpec("RED", "WHITE", seed))
    policy = PublicStrategicPolicy()
    observation = backend.current_public
    history: list[PublicHistoryStep] = []
    try:
        assert observation is not None
        while not observation.terminal and len(history) < 100:
            selectable = next(
                (blind for blind in observation.blinds if blind.status == "SELECT"),
                None,
            )
            if selectable is not None and selectable.kind == "BOSS":
                assert selectable.name == boss_name
                return observation, tuple(history)
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
    raise AssertionError(f"seed {seed} did not reach {boss_name}")


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


def test_pillar_root_reconstructs_current_ante_markers_and_future_debuffs() -> None:
    observation, history = _organic_boss_select_state("2507", "The Pillar")
    played = {
        _permanent_card_identity(step.before.hand[slot.value])
        for step in history
        if step.before.ante == observation.ante
        and isinstance(step.action, PlayCards)
        for slot in step.action.cards
        if isinstance(step.before.hand[slot.value], VisiblePlayingCard)
    }
    assert played

    root = construct_public_root(observation, history, "pillar-organic", 0)
    try:
        private = root._backend._gs
        marked = sum(
            bool(card.ability.get("played_this_ante"))
            for area in ("deck", "hand", "discard_pile")
            for card in private[area]
        )
        assert marked == len(played)

        selected = root.step(SelectBlind())
        assert selected.status == "accepted", selected.error
        assert root.current_public is not None
        assert root.current_public.phase == Phase.SELECTING_HAND
        visible_hand = tuple(
            card
            for card in root.current_public.hand
            if isinstance(card, VisiblePlayingCard)
        )
        assert any(card.debuffed for card in visible_hand)
        assert all(
            card.debuffed == (_permanent_card_identity(card) in played)
            for card in visible_hand
        )
    finally:
        root.close()


def test_live_pillar_rejects_hidden_play_identity() -> None:
    observation, history = _organic_boss_select_state("2507", "The Pillar")
    index = next(
        index
        for index, step in enumerate(history)
        if step.before.ante == observation.ante and isinstance(step.action, PlayCards)
    )
    step = history[index]
    slot = step.action.cards[0]
    hidden_hand = list(step.before.hand)
    hidden_hand[slot.value] = HiddenHandCard()
    malformed = list(history)
    malformed[index] = replace(
        step,
        before=replace(step.before, hand=tuple(hidden_hand)),
    )

    with pytest.raises(DeterminizationUnavailable, match="identity was hidden"):
        _pillar_played_identities(observation, tuple(malformed))


def test_future_boss_reroll_keeps_unsafe_pillar_history_fail_closed() -> None:
    observation, history = _organic_boss_select_state("2507", "The Pillar")
    index = next(
        index
        for index, step in enumerate(history)
        if step.before.ante == observation.ante and isinstance(step.action, PlayCards)
    )
    step = history[index]
    changed_deck = list(step.before.full_deck)
    changed_deck[0] = replace(changed_deck[0], count=2)
    changed_deck.pop()
    malformed = list(history)
    malformed[index] = replace(
        step,
        before=replace(step.before, full_deck=tuple(changed_deck)),
    )
    without_pillar = replace(
        observation,
        used_vouchers=(*observation.used_vouchers, "v_directors_cut"),
        blinds=tuple(
            replace(blind, name="The Wall", effect="The Wall")
            if blind.kind == "BOSS"
            else blind
            for blind in observation.blinds
        ),
    )

    with pytest.raises(DeterminizationUnavailable, match="permanent deck changed"):
        _pillar_played_identities(without_pillar, tuple(malformed))


@pytest.mark.parametrize(
    ("target", "expected_money"),
    (("High Card", 0), ("Pair", 20)),
)
def test_ox_uses_frozen_public_target_not_dynamic_hand_maximum(
    target: str,
    expected_money: int,
) -> None:
    initial, _ = next(_blind_select_states("11", limit=1))
    blinds = tuple(
        replace(blind, status="DEFEATED")
        if blind.kind != "BOSS"
        else replace(blind, status="SELECT", name="The Ox", effect="The Ox")
        for blind in initial.blinds
    )
    hand_stats = tuple(
        replace(stat, played=5) if stat.name == "Pair" else stat
        for stat in initial.hand_stats
    )
    observation = replace(
        initial,
        money=20,
        blinds=blinds,
        hand_stats=hand_stats,
        round=replace(initial.round, most_played_hand=target),
    )

    root = construct_public_root(observation, (), f"ox-{target}", 0)
    try:
        assert root.current_public == observation
        selected = root.step(SelectBlind())
        assert selected.status == "accepted", selected.error
        played = root.step(PlayCards((HandSlot(0),)))
        assert played.status == "accepted", played.error
        assert root.current_public is not None
        assert root.current_public.money == expected_money
    finally:
        root.close()


def test_hidden_hand_order_is_conditioned_at_boss_defeats_only() -> None:
    initial, _ = next(_blind_select_states("11", limit=1))
    tied = tuple(
        replace(stat, played=3)
        if stat.name in {"Pair", "Two Pair"}
        else stat
        for stat in initial.hand_stats
    )
    after = replace(
        initial,
        ante=2,
        round_no=1,
        hand_stats=tied,
        round=replace(initial.round, most_played_hand="Pair"),
    )
    history = (PublicHistoryStep(initial, SelectBlind(), after),)

    order = _sample_poker_hand_order(after, history, "conditioned")
    assert order.index("Two Pair") < order.index("Pair")

    current_counts_disagree = replace(
        after,
        hand_stats=tuple(
            replace(stat, played=9) if stat.name == "Two Pair" else stat
            for stat in after.hand_stats
        ),
    )
    assert _sample_poker_hand_order(
        current_counts_disagree,
        history,
        "conditioned",
    ) == order


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
    missing_ox_target = replace(
        initial,
        round=replace(initial.round, most_played_hand=None),
        blinds=tuple(
            replace(blind, name="The Ox") if blind is boss else blind
            for blind in initial.blinds
        ),
    )
    with pytest.raises(DeterminizationUnavailable, match="requires its visible"):
        construct_public_root(missing_ox_target, (), "bad", 0)
