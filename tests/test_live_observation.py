import math

import pytest

from balatro_ai_v2.live.observation import active_blind, numeric, public_observation


def test_public_projection_removes_private_piles_but_keeps_public_deck() -> None:
    raw = {
        "seed": "SECRET", "cards": {"cards": [{"key": "S_A"}]},
        "discard": {"cards": [{"key": "H_K"}]},
        "poker_hand_iteration_order": ["Pair"],
        "deck_composition": [{"rank": "A", "suit": "S", "count": 4}],
        "round": {"chips": 100},
    }
    public = public_observation(raw)
    assert set(public) == {"deck_composition", "round"}
    public["deck_composition"][0]["count"] = 0
    assert raw["deck_composition"][0]["count"] == 4


@pytest.mark.parametrize("area", ["hand", "jokers", "consumables", "shop", "pack"])
def test_hidden_card_identity_is_fully_redacted_in_every_area(area: str) -> None:
    secret = {"id": 99, "key": "S_A", "set": "ENHANCED", "label": "SECRET",
              "value": {"effect": "SECRET", "rank": "A"}, "modifier": {"seal": "RED"},
              "cost": {"sell": 100}, "unknown_future_identity_field": "SECRET",
              "state": {"hidden": True, "forced_selection": True}}
    public = public_observation({area: {"cards": [secret]}})
    assert public[area]["cards"] == [{"state": {"hidden": True, "forced_selection": True}}]
    assert secret["key"] == "S_A"


def test_recursive_projection_and_empty_lua_maps() -> None:
    public = public_observation({
        "state": "SELECTING_HAND", "round": [], "blinds": {"small": []},
        "hands": {"Pair": []}, "shop": [],
        "hand": {"cards": [{"value": {"ability": []}, "modifier": [], "state": [], "cost": []}]},
        "nested": {"seed": "SECRET", "items": [{"state": {"hidden": True}, "key": "SECRET"}]},
    })
    assert public["state"] == "SELECTING_HAND"
    assert public["round"] == public["shop"] == {}
    assert public["hands"]["Pair"] == public["blinds"]["small"] == {}
    assert public["hand"]["cards"][0] == {"value": {"ability": {}}, "modifier": {}, "state": {}, "cost": {}}
    assert public["nested"] == {"items": [{"state": {"hidden": True}}]}


@pytest.mark.parametrize("value,expected", [(0, 0), (12, 12), (1.5, 1.5), ("1.2e6", 1200000), (" 42 ", 42), (None, 7)])
def test_numeric_accepts_finite_values(value: object, expected: float) -> None:
    assert numeric(value, default=7) == expected


@pytest.mark.parametrize("value", [True, False, "", "bad", "NaN", "inf", "1e999", math.inf, math.nan, [], {}])
def test_numeric_rejects_invalid_supplied_values(value: object) -> None:
    with pytest.raises(ValueError):
        numeric(value)


def test_active_blind_handles_missing_and_current_blinds() -> None:
    assert active_blind({"blinds": []}) == {}
    assert active_blind({}) == {}
    boss = {"status": "CURRENT", "score": 600}
    assert active_blind({"blinds": {"small": {"status": "DEFEATED"}, "boss": boss}}) == boss
