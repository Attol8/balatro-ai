from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

from balatro_ai_v2.solver.actions import (
    BuyMode,
    BuyShopCard,
    CashOut,
    ChoosePackCard,
    DiscardCards,
    HandSlot,
    JokerSlot,
    LeaveShop,
    PlayCards,
    OpenedPackSlot,
    ReorderConsumables,
    ReorderHand,
    ReorderJokers,
    RerollBoss,
    SelectBlind,
    SellConsumable,
    SellJoker,
    ShopSlot,
    SkipPack,
    ConsumableSlot,
    UseConsumable,
    action_from_data,
    action_to_data,
    is_legal,
    iter_legal_actions,
)
from balatro_ai_v2.solver.adapter import (
    IllegalPublicAction,
    ObservationError,
    action_to_rpc,
    to_public_observation,
)
from balatro_ai_v2.solver.consumable_rules import iter_public_targets
from balatro_ai_v2.solver.public_state import PublicObservation, VisiblePlayingCard
from solver_state_factory import item_card, playing_card, state


@pytest.mark.parametrize(
    "action",
    [
        SelectBlind(),
        CashOut(),
        LeaveShop(),
        RerollBoss(),
        PlayCards((HandSlot(0), HandSlot(2))),
        DiscardCards((HandSlot(1),)),
        BuyShopCard(ShopSlot(0)),
        BuyShopCard(ShopSlot(0), BuyMode.USE),
        ReorderHand((HandSlot(1), HandSlot(0))),
    ],
)
def test_action_codec_round_trips(action) -> None:
    assert action_from_data(action_to_data(action)) == action


def test_typed_play_maps_to_public_rpc() -> None:
    observation = to_public_observation(state("SELECTING_HAND"))
    action = PlayCards((HandSlot(0), HandSlot(2)))

    assert action_to_rpc(action, observation) == ("play", {"cards": [0, 2]})


def test_area_specific_slots_prevent_cross_area_mistakes() -> None:
    with pytest.raises(TypeError):
        PlayCards((ShopSlot(0),))  # type: ignore[arg-type]


def test_out_of_phase_action_is_rejected_before_rpc() -> None:
    observation = to_public_observation(state("BLIND_SELECT"))

    with pytest.raises(IllegalPublicAction):
        action_to_rpc(PlayCards((HandSlot(0),)), observation)


def test_blind_action_generator_never_yields_an_illegal_select() -> None:
    observation = to_public_observation(state("BLIND_SELECT"))
    observation = replace(
        observation,
        blinds=tuple(replace(blind, status="UPCOMING") for blind in observation.blinds),
    )

    actions = list(iter_legal_actions(observation))

    assert not any(isinstance(action, SelectBlind) for action in actions)
    assert all(is_legal(observation, action) for action in actions)


def test_boss_reroll_requires_public_voucher_money_and_selectable_boss() -> None:
    raw = state("BLIND_SELECT", money=10)
    raw["used_vouchers"] = ["v_directors_cut"]
    observation = to_public_observation(raw)
    action = RerollBoss()

    assert is_legal(observation, action)
    assert action in iter_legal_actions(observation)
    assert action_to_rpc(action, observation) == ("reroll_boss", {})

    assert not is_legal(replace(observation, money=9), action)
    assert not is_legal(replace(observation, used_vouchers=()), action)
    assert not is_legal(replace(observation, phase=observation.phase.SHOP), action)


def test_directors_cut_is_once_per_ante_but_retcon_is_not() -> None:
    raw = state("BLIND_SELECT", money=30)
    raw["used_vouchers"] = ["v_directors_cut"]
    raw["round"]["boss_rerolled"] = True

    assert not is_legal(to_public_observation(raw), RerollBoss())

    raw["used_vouchers"] = ["v_directors_cut", "v_retcon"]
    assert is_legal(to_public_observation(raw), RerollBoss())


def test_boss_reroll_honours_public_credit_card_floor() -> None:
    raw = state("BLIND_SELECT", money=-10)
    raw["used_vouchers"] = ["v_retcon"]
    raw["jokers"]["cards"] = [
        item_card("j_credit_card", card_id=30, kind="JOKER")
    ]
    raw["jokers"]["count"] = 1

    assert is_legal(to_public_observation(raw), RerollBoss())

    raw["jokers"]["cards"][0]["state"] = {"debuff": True}
    assert not is_legal(to_public_observation(raw), RerollBoss())


def test_hand_actions_are_not_limited_to_old_eight_card_mask() -> None:
    raw = state("SELECTING_HAND")
    raw["hand"]["cards"] = [playing_card(f"S_{index}", card_id=100 + index) for index in range(9)]
    raw["hand"]["count"] = 9
    raw["hand"]["limit"] = 9
    observation = to_public_observation(raw)
    action = PlayCards((HandSlot(8),))

    assert is_legal(observation, action)
    assert action_to_rpc(action, observation) == ("play", {"cards": [8]})


def test_action_generation_honours_live_selection_limit() -> None:
    observation = replace(to_public_observation(state("SELECTING_HAND")), selection_limit=2)
    actions = list(iter_legal_actions(observation))
    tactical = [action for action in actions if isinstance(action, (PlayCards, DiscardCards))]

    assert tactical
    assert max(len(action.cards) for action in tactical) == 2


def test_tactical_actions_offer_full_hands_before_smaller_subsets() -> None:
    observation = to_public_observation(state("SELECTING_HAND"))

    first = next(iter_legal_actions(observation))

    assert isinstance(first, PlayCards)
    assert len(first.cards) == min(5, observation.selection_limit, len(observation.hand))


def test_duplicate_or_negative_slots_fail() -> None:
    with pytest.raises(ValueError):
        PlayCards((HandSlot(0), HandSlot(0)))
    with pytest.raises(ValueError):
        HandSlot(-1)


def test_held_planet_is_a_legal_no_target_public_action() -> None:
    raw = state("SELECTING_HAND")
    raw["consumables"]["cards"] = [item_card("c_mercury", card_id=30, kind="PLANET")]
    raw["consumables"]["count"] = 1
    observation = to_public_observation(raw)
    action = UseConsumable(ConsumableSlot(0))

    assert is_legal(observation, action)
    assert action in iter_legal_actions(observation)
    assert action_to_rpc(action, observation) == ("use", {"consumable": 0})


def test_targeted_consumable_requires_and_compiles_exact_public_targets() -> None:
    raw = state("SELECTING_HAND")
    raw["consumables"]["cards"] = [item_card("c_death", card_id=31, kind="TAROT")]
    raw["consumables"]["count"] = 1
    observation = to_public_observation(raw)
    no_targets = UseConsumable(ConsumableSlot(0))
    action = UseConsumable(
        ConsumableSlot(0),
        (HandSlot(0), HandSlot(2)),
    )

    assert not is_legal(observation, no_targets)
    assert is_legal(observation, action)
    assert action in iter_legal_actions(observation)
    assert action_to_rpc(action, observation) == (
        "use",
        {"consumable": 0, "cards": [0, 2]},
    )
    with pytest.raises(IllegalPublicAction):
        action_to_rpc(no_targets, observation)


def test_cerulean_forced_slot_is_required_for_play_discard_and_consumable() -> None:
    raw = _cerulean_state()
    raw["hand"]["cards"][1]["state"] = {
        "highlight": True,
        "forced_selection": True,
    }
    raw["consumables"]["cards"] = [item_card("c_death", card_id=31, kind="TAROT")]
    raw["consumables"]["count"] = 1
    observation = to_public_observation(raw)

    assert observation.required_hand_slots == (1,)
    assert not is_legal(observation, PlayCards((HandSlot(0),)))
    assert not is_legal(observation, DiscardCards((HandSlot(0),)))
    assert not is_legal(
        observation,
        UseConsumable(ConsumableSlot(0), (HandSlot(0), HandSlot(2))),
    )
    assert is_legal(observation, PlayCards((HandSlot(0), HandSlot(1))))
    assert is_legal(
        observation,
        UseConsumable(ConsumableSlot(0), (HandSlot(0), HandSlot(1))),
    )
    assert all(
        not isinstance(action, (PlayCards, DiscardCards, UseConsumable))
        or 1 in tuple(slot.value for slot in getattr(action, "cards", getattr(action, "targets", ())))
        for action in iter_legal_actions(observation)
    )


@pytest.mark.parametrize(
    ("card_state", "message"),
    [
        ({}, "requires one visibly forced"),
        ({"highlight": False, "forced_selection": True}, "not visibly highlighted"),
        ({"highlight": True, "forced_selection": "yes"}, "marker must be boolean"),
    ],
)
def test_cerulean_forced_slot_fails_closed_on_missing_or_malformed_marker(
    card_state: dict[str, object],
    message: str,
) -> None:
    raw = _cerulean_state()
    raw["hand"]["cards"][1]["state"] = card_state

    with pytest.raises(ObservationError, match=message):
        to_public_observation(raw)


def test_forced_slot_fails_closed_without_active_cerulean_bell() -> None:
    raw = state("SELECTING_HAND")
    raw["hand"]["cards"][1]["state"] = {
        "highlight": True,
        "forced_selection": True,
    }

    with pytest.raises(ObservationError, match="inconsistent with the active blind"):
        to_public_observation(raw)


def test_cerulean_public_twins_have_identical_legality() -> None:
    left = _cerulean_state()
    left["hand"]["cards"][1]["state"] = {
        "highlight": True,
        "forced_selection": True,
    }
    right = deepcopy(left)
    right["seed"] = "OTHER-PRIVATE-SEED"
    right["cards"]["cards"].reverse()
    for index, card in enumerate(right["cards"]["cards"]):
        card["id"] = 900 + index

    left_observation = to_public_observation(left)
    right_observation = to_public_observation(right)

    assert left_observation == right_observation
    assert tuple(iter_legal_actions(left_observation)) == tuple(
        iter_legal_actions(right_observation)
    )


def _cerulean_state() -> dict[str, Any]:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(name="Cerulean Bell", status="CURRENT")
    return raw


def test_negative_joker_can_enter_a_full_area_from_shop_or_pack() -> None:
    shop_raw = state("SHOP", money=10)
    shop_raw["jokers"]["limit"] = 0
    shop_raw["shop"]["cards"][0]["modifier"] = ["NEGATIVE"]
    shop = to_public_observation(shop_raw)

    pack_raw = state("BUFFOON_PACK")
    pack_raw["jokers"]["limit"] = 0
    pack_raw["pack"]["cards"][0]["modifier"] = ["NEGATIVE"]
    pack = to_public_observation(pack_raw)

    assert is_legal(shop, BuyShopCard(ShopSlot(0)))
    assert is_legal(pack, ChoosePackCard(OpenedPackSlot(0)))


def _legacy_pack_actions(observation: PublicObservation) -> tuple[object, ...]:
    actions: list[object] = [SkipPack()]
    for index, item in enumerate(observation.opened_pack):
        if isinstance(item, VisiblePlayingCard) or item.kind.upper() == "JOKER":
            action = ChoosePackCard(OpenedPackSlot(index))
            if is_legal(observation, action):
                actions.append(action)
            continue
        for target_indexes in iter_public_targets(observation, item, from_pack=True):
            action = ChoosePackCard(
                OpenedPackSlot(index),
                tuple(HandSlot(target) for target in target_indexes),
            )
            if is_legal(observation, action):
                actions.append(action)
    return tuple(actions)


def test_pack_generation_preserves_legacy_order_and_legality() -> None:
    raw = state("TAROT_PACK")
    raw["hand"] = {
        "cards": [
            playing_card(f"{suit}_{rank}", card_id=100 + index)
            for index, (suit, rank) in enumerate(
                zip("SHDCSHDC", "AKQJT987", strict=True)
            )
        ],
        "count": 8,
        "highlighted_limit": 5,
        "limit": 8,
    }
    raw["pack"] = {
        "cards": [
            item_card("c_moon", card_id=200, kind="TAROT"),
            item_card("c_star", card_id=201, kind="TAROT"),
            item_card("c_fool", card_id=202, kind="TAROT"),
        ],
        "count": 3,
        "highlighted_limit": 1,
        "limit": 3,
    }
    raw["last_tarot_planet"] = "c_mercury"
    observation = to_public_observation(raw)

    actions = tuple(iter_legal_actions(observation))

    assert len(actions) == 186
    assert tuple(action_to_data(action) for action in actions) == tuple(
        action_to_data(action) for action in _legacy_pack_actions(observation)
    )
    assert all(is_legal(observation, action) for action in actions)


def test_pack_generation_preserves_capacity_and_hidden_target_filters() -> None:
    raw = state("SPECTRAL_PACK")
    raw["hand"] = {
        "cards": [
            playing_card("S_A", card_id=100),
            playing_card("H_K", card_id=101, hidden=True),
            playing_card("D_Q", card_id=102, modifier=["FOIL"]),
        ],
        "count": 3,
        "highlighted_limit": 5,
        "limit": 8,
    }
    raw["consumables"] = {
        "cards": [
            item_card("c_mercury", card_id=300, kind="PLANET"),
            item_card("c_venus", card_id=301, kind="PLANET"),
        ],
        "count": 2,
        "highlighted_limit": 1,
        "limit": 2,
    }
    raw["pack"] = {
        "cards": [
            item_card("c_aura", card_id=200, kind="SPECTRAL"),
            item_card("c_emperor", card_id=201, kind="TAROT"),
            playing_card("C_J", card_id=202),
        ],
        "count": 3,
        "highlighted_limit": 1,
        "limit": 3,
    }
    observation = to_public_observation(raw)

    actions = tuple(iter_legal_actions(observation))
    pack_actions = tuple(
        action
        for action in actions
        if isinstance(action, (ChoosePackCard, SkipPack))
    )

    assert tuple(action_to_data(action) for action in pack_actions) == tuple(
        action_to_data(action) for action in _legacy_pack_actions(observation)
    )
    assert all(is_legal(observation, action) for action in actions)


def _legacy_held_consumable_actions(
    observation: PublicObservation,
) -> tuple[UseConsumable, ...]:
    actions: list[UseConsumable] = []
    for index, item in enumerate(observation.consumables):
        for target_indexes in iter_public_targets(
            observation, item, from_pack=False
        ):
            action = UseConsumable(
                ConsumableSlot(index),
                tuple(HandSlot(target) for target in target_indexes),
            )
            if is_legal(observation, action):
                actions.append(action)
    return tuple(actions)


@pytest.mark.parametrize("phase", ["SHOP", "SELECTING_HAND"])
def test_held_consumable_generation_preserves_legacy_order_and_legality(
    phase: str,
) -> None:
    raw = state(phase)
    raw["hand"] = {
        "cards": [
            playing_card("S_A", card_id=100),
            playing_card("H_K", card_id=101, hidden=True),
            playing_card("D_Q", card_id=102, modifier=["FOIL"]),
            playing_card("C_J", card_id=103),
        ],
        "count": 4,
        "highlighted_limit": 5,
        "limit": 8,
    }
    raw["consumables"] = {
        "cards": [
            item_card("c_moon", card_id=200, kind="TAROT"),
            item_card("c_aura", card_id=201, kind="SPECTRAL"),
            item_card("c_mercury", card_id=202, kind="PLANET"),
            item_card("c_fool", card_id=203, kind="TAROT"),
        ],
        "count": 4,
        "highlighted_limit": 1,
        "limit": 4,
    }
    raw["last_tarot_planet"] = "c_mercury"
    observation = to_public_observation(raw)

    generated = tuple(
        action
        for action in iter_legal_actions(observation)
        if isinstance(action, UseConsumable)
    )

    assert tuple(action_to_data(action) for action in generated) == tuple(
        action_to_data(action)
        for action in _legacy_held_consumable_actions(observation)
    )
    assert all(is_legal(observation, action) for action in generated)
    if phase == "SHOP":
        assert {action.consumable.value for action in generated} == {2, 3}
        assert all(not action.targets for action in generated)
    else:
        assert {action.consumable.value for action in generated} == {0, 1, 2, 3}


def test_held_consumable_generation_preserves_forced_slot_filter() -> None:
    raw = _cerulean_state()
    raw["hand"]["cards"][1]["state"] = {
        "highlight": True,
        "forced_selection": True,
    }
    raw["consumables"]["cards"] = [
        item_card("c_death", card_id=200, kind="TAROT")
    ]
    raw["consumables"]["count"] = 1
    observation = to_public_observation(raw)

    generated = tuple(
        action
        for action in iter_legal_actions(observation)
        if isinstance(action, UseConsumable)
    )

    assert generated == _legacy_held_consumable_actions(observation)
    assert generated
    assert all(HandSlot(1) in action.targets for action in generated)
    assert all(is_legal(observation, action) for action in generated)


@pytest.mark.parametrize("phase", ["SHOP", "SELECTING_HAND"])
def test_unknown_held_consumable_still_fails_closed(phase: str) -> None:
    raw = state(phase)
    raw["consumables"]["cards"] = [
        item_card("c_modded_consumable", card_id=200, kind="TAROT")
    ]
    raw["consumables"]["count"] = 1
    observation = to_public_observation(raw)

    assert not any(
        isinstance(action, UseConsumable)
        for action in iter_legal_actions(observation)
    )
    assert _legacy_held_consumable_actions(observation) == ()


def test_debuffed_credit_card_does_not_extend_purchase_floor() -> None:
    active_raw = state("SHOP", money=0)
    active_raw["jokers"]["cards"] = [
        item_card("j_credit_card", card_id=30, kind="JOKER")
    ]
    active_raw["jokers"]["count"] = 1
    active_raw["shop"]["cards"][0]["cost"]["buy"] = 1
    debuffed_raw = deepcopy(active_raw)
    debuffed_raw["jokers"]["cards"][0]["state"] = {"debuff": True}

    action = BuyShopCard(ShopSlot(0))
    assert is_legal(to_public_observation(active_raw), action)
    assert not is_legal(to_public_observation(debuffed_raw), action)


def test_credit_card_purchase_floor_stacks_per_active_copy() -> None:
    raw = state("SHOP", money=-20)
    raw["jokers"]["cards"] = [
        item_card("j_credit_card", card_id=30, kind="JOKER"),
        item_card("j_credit_card", card_id=31, kind="JOKER"),
    ]
    raw["jokers"]["count"] = 2
    raw["shop"]["cards"][0]["cost"]["buy"] = 20

    action = BuyShopCard(ShopSlot(0))
    assert is_legal(to_public_observation(raw), action)

    raw["jokers"]["cards"][1]["state"] = {"debuff": True}
    assert not is_legal(to_public_observation(raw), action)


def test_magic_trick_shop_card_purchase_uses_money_not_item_capacity() -> None:
    raw = state("SHOP", money=1)
    raw["shop"] = {
        "cards": [playing_card("H_K", card_id=90)],
        "count": 1,
        "highlighted_limit": 1,
        "limit": 2,
    }
    raw["jokers"]["limit"] = raw["jokers"]["count"]
    raw["consumables"]["limit"] = raw["consumables"]["count"]
    observation = to_public_observation(raw)
    action = BuyShopCard(ShopSlot(0))

    assert is_legal(observation, action)
    assert action in set(iter_legal_actions(observation))
    assert action_to_rpc(action, observation) == ("buy", {"card": 0})
    assert not is_legal(replace(observation, money=0), action)

    credit_raw = deepcopy(raw)
    credit_raw["money"] = -20
    credit_raw["jokers"]["cards"] = [
        item_card("j_credit_card", card_id=91, kind="JOKER")
    ]
    credit_raw["jokers"]["count"] = 1
    credit_raw["jokers"]["limit"] = 1
    credit_raw["shop"]["cards"][0]["cost"]["buy"] = 0
    assert is_legal(to_public_observation(credit_raw), action)


def test_shop_planet_buy_and_use_bypasses_storage_but_not_public_use_gates() -> None:
    raw = state("SHOP", money=10)
    raw["shop"] = {
        "cards": [
            item_card("c_mercury", card_id=90, kind="PLANET", buy=3),
            item_card("c_magician", card_id=91, kind="TAROT", buy=3),
            item_card("c_modded_planet", card_id=94, kind="PLANET", buy=3),
        ],
        "count": 3,
        "highlighted_limit": 1,
        "limit": 2,
    }
    raw["consumables"] = {
        "cards": [
            item_card("c_uranus", card_id=92, kind="PLANET"),
            item_card("c_pluto", card_id=93, kind="PLANET"),
        ],
        "count": 2,
        "highlighted_limit": 1,
        "limit": 2,
    }
    observation = to_public_observation(raw)
    store = BuyShopCard(ShopSlot(0))
    use = BuyShopCard(ShopSlot(0), BuyMode.USE)
    targeted_use = BuyShopCard(ShopSlot(1), BuyMode.USE)
    unknown_use = BuyShopCard(ShopSlot(2), BuyMode.USE)

    assert not is_legal(observation, store)
    assert is_legal(observation, use)
    assert use in iter_legal_actions(observation)
    assert not is_legal(observation, targeted_use)
    assert targeted_use not in iter_legal_actions(observation)
    assert not is_legal(observation, unknown_use)
    assert unknown_use not in iter_legal_actions(observation)
    assert action_to_rpc(use, observation) == ("buy", {"card": 0, "mode": "use"})
    assert action_from_data(action_to_data(use)) == use
    assert not is_legal(replace(observation, money=2), use)


def test_negative_shop_consumable_can_be_stored_when_tray_is_nominally_full() -> None:
    raw = state("SHOP", money=10)
    raw["shop"] = {
        "cards": [
            item_card(
                "c_mercury",
                card_id=90,
                kind="PLANET",
                modifier=["NEGATIVE"],
                buy=3,
            )
        ],
        "count": 1,
        "highlighted_limit": 1,
        "limit": 2,
    }
    raw["consumables"] = {
        "cards": [
            item_card("c_uranus", card_id=92, kind="PLANET"),
            item_card("c_pluto", card_id=93, kind="PLANET"),
        ],
        "count": 2,
        "highlighted_limit": 1,
        "limit": 2,
    }
    observation = to_public_observation(raw)

    assert is_legal(observation, BuyShopCard(ShopSlot(0)))
    assert is_legal(observation, BuyShopCard(ShopSlot(0), BuyMode.USE))


def test_reorder_generator_exposes_only_adjacent_swaps() -> None:
    observation = to_public_observation(state("SELECTING_HAND"))
    reorders = [
        action
        for action in iter_legal_actions(observation)
        if isinstance(action, ReorderHand)
    ]

    assert len(reorders) == len(observation.hand) - 1
    assert all(is_legal(observation, action) for action in reorders)
    assert not is_legal(
        observation,
        ReorderHand((HandSlot(2), HandSlot(1), HandSlot(0))),
    )


def test_smods_pack_does_not_imply_unproved_inventory_reorder_permission() -> None:
    raw = state("SELECTING_HAND")
    raw["state"] = "SMODS_BOOSTER_OPENED"
    raw["pack_choices_remaining"] = 1
    raw["pack"] = {
        "cards": [item_card("c_mercury", card_id=30, kind="PLANET")],
        "count": 1,
        "highlighted_limit": 1,
        "limit": 2,
    }
    raw["jokers"] = {
        "cards": [
            item_card("j_joker", card_id=31, kind="JOKER"),
            item_card("j_greedy_joker", card_id=32, kind="JOKER"),
        ],
        "count": 2,
        "highlighted_limit": 1,
        "limit": 5,
    }
    raw["consumables"] = {
        "cards": [
            item_card("c_mercury", card_id=33, kind="PLANET"),
            item_card("c_uranus", card_id=34, kind="PLANET"),
        ],
        "count": 2,
        "highlighted_limit": 1,
        "limit": 2,
    }
    observation = to_public_observation(raw)
    reorders = (
        ReorderHand((HandSlot(1), HandSlot(0), HandSlot(2))),
        ReorderJokers((JokerSlot(1), JokerSlot(0))),
        ReorderConsumables((ConsumableSlot(1), ConsumableSlot(0))),
    )

    assert observation.pack_kind == "SMODS"
    assert not any(
        isinstance(action, (ReorderHand, ReorderJokers, ReorderConsumables))
        for action in iter_legal_actions(observation)
    )
    assert all(not is_legal(observation, action) for action in reorders)


def test_vanilla_pack_appends_owned_inventory_sales_after_pack_choices() -> None:
    raw = state("BUFFOON_PACK")
    eternal = item_card("j_eternal", card_id=41, kind="JOKER")
    eternal["modifier"] = {"eternal": True}
    raw["jokers"] = {
        "cards": [
            item_card("j_joker", card_id=40, kind="JOKER"),
            eternal,
        ],
        "count": 2,
        "highlighted_limit": 1,
        "limit": 5,
    }
    raw["consumables"] = {
        "cards": [item_card("c_mercury", card_id=50, kind="PLANET")],
        "count": 1,
        "highlighted_limit": 1,
        "limit": 2,
    }
    observation = to_public_observation(raw)

    actions = tuple(iter_legal_actions(observation))
    sales = tuple(
        action
        for action in actions
        if isinstance(action, (SellJoker, SellConsumable))
    )

    assert sales == (SellJoker(JokerSlot(0)), SellConsumable(ConsumableSlot(0)))
    assert actions[-2:] == sales
    assert all(is_legal(observation, action) for action in sales)
    assert not is_legal(observation, SellJoker(JokerSlot(1)))
    assert not any(isinstance(action, UseConsumable) for action in actions)
    assert action_to_rpc(sales[0], observation) == ("sell", {"joker": 0})
    assert action_to_rpc(sales[1], observation) == ("sell", {"consumable": 0})


def test_smods_pack_inventory_sales_fail_closed() -> None:
    raw = state("BUFFOON_PACK")
    raw["state"] = "SMODS_BOOSTER_OPENED"
    raw["jokers"]["cards"] = [item_card("j_joker", card_id=40, kind="JOKER")]
    raw["jokers"]["count"] = 1
    raw["consumables"]["cards"] = [
        item_card("c_mercury", card_id=50, kind="PLANET")
    ]
    raw["consumables"]["count"] = 1
    observation = to_public_observation(raw)
    sales = (SellJoker(JokerSlot(0)), SellConsumable(ConsumableSlot(0)))
    actions = tuple(iter_legal_actions(observation))

    assert all(not is_legal(observation, action) for action in sales)
    assert all(action not in actions for action in sales)


def test_eternal_joker_cannot_be_sold() -> None:
    raw = state("SELECTING_HAND")
    joker = item_card("j_joker", card_id=20, kind="JOKER")
    joker["modifier"] = {"eternal": True}
    raw["jokers"]["cards"] = [joker]
    raw["jokers"]["count"] = 1
    observation = to_public_observation(raw)

    assert not is_legal(observation, SellJoker(JokerSlot(0)))
