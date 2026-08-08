from __future__ import annotations

from copy import deepcopy
from dataclasses import fields

import pytest

from balatro_ai_v2.actions import action_to_data, iter_legal_actions
from balatro_ai_v2.balatrobot.adapter import ObservationError, to_public_observation
from balatro_ai_v2.public_state import HiddenHandCard, PublicObservation
from state_factory import playing_card, state


def test_hidden_state_twins_produce_identical_policy_input_and_actions() -> None:
    left = state("SELECTING_HAND", seed="SECRET-A")
    right = deepcopy(left)
    right["seed"] = "SECRET-B"
    for card in right["cards"]["cards"]:
        card["id"] += 5000
    right["cards"]["cards"].reverse()
    right["rng"] = {"future": 123}
    right["event_queue"] = ["secret"]
    right["save_payload"] = "private"

    left_public = to_public_observation(left)
    right_public = to_public_observation(right)
    left_actions = [action_to_data(action) for action in iter_legal_actions(left_public)]
    right_actions = [action_to_data(action) for action in iter_legal_actions(right_public)]

    assert left_public == right_public
    assert left_actions == right_actions


def test_face_down_card_identity_is_completely_anonymous() -> None:
    left = state("SELECTING_HAND")
    right = deepcopy(left)
    left["hand"]["cards"][0] = playing_card(
        "S_A", card_id=800, hidden=True, modifier=["POLYCHROME"], debuffed=True
    )
    right["hand"]["cards"][0] = playing_card("D_2", card_id=999, hidden=True, modifier=["GOLD"])

    left_public = to_public_observation(left)
    right_public = to_public_observation(right)

    assert isinstance(left_public.hand[0], HiddenHandCard)
    assert left_public == right_public


def test_draw_pile_is_public_composition_but_not_private_order() -> None:
    left = state()
    reordered = deepcopy(left)
    reordered["cards"]["cards"].reverse()
    changed = deepcopy(left)
    changed["cards"]["cards"][0] = playing_card("C_7", card_id=1, hidden=True)

    assert to_public_observation(left) == to_public_observation(reordered)
    assert to_public_observation(left) != to_public_observation(changed)


def test_vm_poker_hand_iteration_order_is_private() -> None:
    left = state()
    right = deepcopy(left)
    right["poker_hand_iteration_order"] = list(reversed(left["poker_hand_iteration_order"]))

    assert to_public_observation(left) == to_public_observation(right)


def test_visible_tooltip_and_money_remain_policy_information() -> None:
    raw = state("SHOP")
    changed = deepcopy(raw)
    changed["money"] += 1
    changed["shop"]["cards"][0]["value"]["effect"] = "Currently +99 Mult"

    assert to_public_observation(raw) != to_public_observation(changed)


def test_public_serialization_contains_no_private_seed_ids_or_ability_tree() -> None:
    raw = state("SELECTING_HAND", seed="NEVER-EXPOSE")
    raw["jokers"]["cards"] = [
        {
            "cost": {"buy": 5, "sell": 2},
            "id": 8675309,
            "key": "j_secret",
            "label": "Visible label",
            "modifier": [],
            "set": "JOKER",
            "state": {},
            "value": {"ability": {"future_rng": "DO-NOT-LEAK"}, "effect": "Visible effect", "rarity": 1},
        }
    ]
    raw["jokers"]["count"] = 1

    serialized = to_public_observation(raw).canonical_json()

    assert "NEVER-EXPOSE" not in serialized
    assert "8675309" not in serialized
    assert "DO-NOT-LEAK" not in serialized
    assert "Visible effect" in serialized


def test_unsettled_area_fails_closed() -> None:
    raw = state("SELECTING_HAND")
    raw["hand"]["count"] = 8

    with pytest.raises(ObservationError, match="unsettled hand"):
        to_public_observation(raw)


def test_policy_contract_has_no_dictionary_or_any_escape_hatch() -> None:
    annotation_text = " ".join(str(field.type) for field in fields(PublicObservation))

    assert "Any" not in annotation_text
    assert "dict" not in annotation_text


def test_public_observation_is_frozen() -> None:
    observation = to_public_observation(state())

    with pytest.raises(AttributeError):
        observation.money = 99  # type: ignore[misc]


def test_live_lua_table_shapes_are_normalized_at_the_firewall() -> None:
    raw = state("SHOP")
    raw["shop"]["cards"][0]["modifier"] = {
        "edition": "FOIL",
        "enhancement": "",
        "eternal": True,
        "perishable": 3,
        "rental": True,
    }
    raw["used_vouchers"] = {"v_seed_money": ""}

    observation = to_public_observation(raw)

    assert observation.shop[0].edition == "FOIL"
    assert observation.shop[0].eternal
    assert observation.shop[0].perishable_rounds == 3
    assert observation.shop[0].rental
    assert observation.used_vouchers == ("v_seed_money",)


def test_transient_animation_state_is_not_a_policy_decision() -> None:
    raw = state("SELECTING_HAND")
    raw["state"] = "DRAW_TO_HAND"

    with pytest.raises(ObservationError, match="unsupported Balatro state"):
        to_public_observation(raw)
