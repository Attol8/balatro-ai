from balatro_ai_v2.balatrobot.adapter import card_to_fast_id, hand_to_fast_ids
from balatro_ai_v2.fast.cards import NUM_RANKS


def test_card_to_fast_id_uses_value_fields() -> None:
    card = {"value": {"rank": "A", "suit": "H"}}

    assert card_to_fast_id(card) == 1 * NUM_RANKS + 12


def test_card_to_fast_id_falls_back_to_key() -> None:
    card = {"key": "S_T", "value": {}}

    assert card_to_fast_id(card) == 8


def test_hand_to_fast_ids_converts_balatrobot_state() -> None:
    state = {
        "hand": {
            "cards": [
                {"value": {"rank": "A", "suit": "H"}},
                {"value": {"rank": "2", "suit": "S"}},
            ]
        }
    }

    assert hand_to_fast_ids(state) == (1 * NUM_RANKS + 12, 0)
