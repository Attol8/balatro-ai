"""Public-observation firewall tests for raw BalatroBot state."""

from __future__ import annotations

from copy import deepcopy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "game"))
from state_factory import hidden_joker_slot, item_card, state  # noqa: E402

from balatro_ai.game.adapter import ObservationError, to_public_observation  # noqa: E402
from balatro_ai.game.state import HiddenHandCard, HiddenJokerSlot  # noqa: E402


def test_private_seed_and_entity_ids_do_not_enter_public_observation() -> None:
    left = state("SELECTING_HAND")
    right = deepcopy(left)
    right["seed"] = "DIFFERENT-PRIVATE-SEED"
    for area_name in ("cards", "hand", "jokers", "consumables", "shop", "packs", "vouchers"):
        for card in (right.get(area_name) or {}).get("cards", []):
            card["id"] += 10_000

    assert to_public_observation(left) == to_public_observation(right)


def test_hidden_hand_identity_is_replaced_by_typed_sentinel() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(name="The House", status="CURRENT")
    raw["hand"]["cards"][0]["state"] = {"hidden": True}

    observation = to_public_observation(raw)
    assert isinstance(observation.hand[0], HiddenHandCard)


def test_hidden_joker_identity_is_replaced_by_typed_sentinel() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(name="Amber Acorn", status="CURRENT")
    raw["jokers"] = {
        "cards": [hidden_joker_slot()], "count": 1, "highlighted_limit": 1, "limit": 5,
    }

    observation = to_public_observation(raw)
    assert isinstance(observation.jokers[0], HiddenJokerSlot)


def test_hidden_joker_payload_fails_closed_if_identity_leaks() -> None:
    raw = state("SELECTING_HAND")
    leaked = item_card("j_blueprint", card_id=99, kind="JOKER")
    leaked["state"] = {"hidden": True}
    raw["jokers"] = {
        "cards": [leaked], "count": 1, "highlighted_limit": 1, "limit": 5,
    }

    with pytest.raises(ObservationError, match="exposed private fields"):
        to_public_observation(raw)


def test_unknown_ability_payload_is_not_copied_into_public_state() -> None:
    raw = state("SHOP")
    raw["shop"]["cards"][0]["value"]["ability"]["private_future_roll"] = "SECRET"

    observation = to_public_observation(raw)
    assert "SECRET" not in observation.canonical_json()


def test_only_known_booster_artwork_variants_are_collapsed() -> None:
    raw = state("SHOP")
    raw["packs"]["cards"][0]["key"] = "p_buffoon_normal_2"
    assert to_public_observation(raw).packs[0].key == "p_buffoon_normal"

    raw["packs"]["cards"][0]["key"] = "p_custom_rule_2"
    assert to_public_observation(raw).packs[0].key == "p_custom_rule_2"


@pytest.mark.parametrize(
    ("card_state", "message"),
    [
        ({}, "requires one visibly forced"),
        ({"highlight": False, "forced_selection": True}, "not visibly highlighted"),
        ({"highlight": True, "forced_selection": "yes"}, "marker must be boolean"),
    ],
)
def test_cerulean_forced_slot_fails_closed(card_state: dict[str, object], message: str) -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(name="Cerulean Bell", status="CURRENT")
    raw["hand"]["cards"][1]["state"] = card_state

    with pytest.raises(ObservationError, match=message):
        to_public_observation(raw)


@pytest.mark.parametrize("bad_count", [True, 0, 1.5])
def test_deck_composition_counts_fail_closed(bad_count: object) -> None:
    raw = state()
    raw["deck_composition"][0]["count"] = bad_count
    with pytest.raises(ObservationError, match="positive integer"):
        to_public_observation(raw)


@pytest.mark.parametrize(("delta", "expected_size"), [(1, 53), (-1, 51)])
def test_deck_size_comes_from_public_composition_when_area_limit_is_stale(
    delta: int, expected_size: int
) -> None:
    raw = state("SELECTING_HAND")
    assert raw["cards"]["limit"] == 52
    raw["deck_composition"][0]["count"] += delta

    observation = to_public_observation(raw)

    assert observation.deck_size == expected_size
    assert sum(entry.count for entry in observation.full_deck) == expected_size
    assert raw["cards"]["limit"] == 52
