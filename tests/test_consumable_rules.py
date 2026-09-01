from __future__ import annotations

from balatro_ai_v2.actions import ConsumableSlot, HandSlot, UseConsumable, is_legal
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from state_factory import item_card, playing_card, state


def _with_consumable(key: str):
    raw = state("SELECTING_HAND")
    raw["consumables"]["cards"] = [item_card(key, card_id=90, kind="SPECTRAL")]
    raw["consumables"]["count"] = 1
    return raw


def test_ankh_fails_closed_when_joker_area_is_full() -> None:
    raw = _with_consumable("c_ankh")
    raw["jokers"]["cards"] = [item_card("j_joker", card_id=91, kind="JOKER")]
    raw["jokers"]["count"] = 1
    raw["jokers"]["limit"] = 1

    observation = to_public_observation(raw)

    assert not is_legal(observation, UseConsumable(ConsumableSlot(0)))


def test_editionless_debuffed_joker_remains_eligible_for_wheel() -> None:
    raw = _with_consumable("c_wheel_of_fortune")
    joker = item_card("j_joker", card_id=91, kind="JOKER")
    joker["state"] = {"debuff": True}
    raw["jokers"]["cards"] = [joker]
    raw["jokers"]["count"] = 1

    observation = to_public_observation(raw)

    assert observation.jokers[0].debuffed
    assert is_legal(observation, UseConsumable(ConsumableSlot(0)))


def test_aura_fails_closed_for_face_down_target_regardless_of_hidden_edition() -> None:
    plain = _with_consumable("c_aura")
    plain["hand"]["cards"][0] = playing_card("S_A", card_id=100, hidden=True)
    edited = _with_consumable("c_aura")
    edited["hand"]["cards"][0] = playing_card(
        "D_2", card_id=101, hidden=True, modifier=["FOIL"]
    )

    plain_observation = to_public_observation(plain)
    edited_observation = to_public_observation(edited)
    action = UseConsumable(ConsumableSlot(0), (HandSlot(0),))

    assert not is_legal(plain_observation, action)
    assert not is_legal(edited_observation, action)


def test_fool_requires_a_remembered_non_fool_tarot_or_planet() -> None:
    raw = _with_consumable("c_fool")
    absent = to_public_observation(raw)
    raw["last_tarot_planet"] = "c_mercury"
    present = to_public_observation(raw)

    action = UseConsumable(ConsumableSlot(0))
    assert not is_legal(absent, action)
    assert is_legal(present, action)
