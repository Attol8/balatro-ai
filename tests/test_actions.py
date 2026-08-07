from __future__ import annotations

from dataclasses import replace

import pytest

from balatro_ai_v2.actions import (
    BuyShopCard,
    CashOut,
    DiscardCards,
    HandSlot,
    JokerSlot,
    LeaveShop,
    PlayCards,
    ReorderHand,
    SelectBlind,
    SellJoker,
    ShopSlot,
    ConsumableSlot,
    UseConsumable,
    action_from_data,
    action_to_data,
    is_legal,
    iter_legal_actions,
)
from balatro_ai_v2.balatrobot.adapter import IllegalPublicAction, action_to_rpc, to_public_observation
from state_factory import item_card, playing_card, state


@pytest.mark.parametrize(
    "action",
    [
        SelectBlind(),
        CashOut(),
        LeaveShop(),
        PlayCards((HandSlot(0), HandSlot(2))),
        DiscardCards((HandSlot(1),)),
        BuyShopCard(ShopSlot(0)),
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


def test_duplicate_or_negative_slots_fail() -> None:
    with pytest.raises(ValueError):
        PlayCards((HandSlot(0), HandSlot(0)))
    with pytest.raises(ValueError):
        HandSlot(-1)


def test_consumable_use_fails_closed_until_game_rules_are_encoded() -> None:
    observation = to_public_observation(state("SELECTING_HAND"))
    action = UseConsumable(ConsumableSlot(0))

    assert not is_legal(observation, action)
    with pytest.raises(IllegalPublicAction):
        action_to_rpc(action, observation)


def test_eternal_joker_cannot_be_sold() -> None:
    raw = state("SELECTING_HAND")
    joker = item_card("j_joker", card_id=20, kind="JOKER")
    joker["modifier"] = {"eternal": True}
    raw["jokers"]["cards"] = [joker]
    raw["jokers"]["count"] = 1
    observation = to_public_observation(raw)

    assert not is_legal(observation, SellJoker(JokerSlot(0)))
