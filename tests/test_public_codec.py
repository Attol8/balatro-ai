from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.public_codec import (
    PublicCodecError,
    public_observation_from_data,
    public_observation_to_data,
)
from state_factory import state


@pytest.mark.parametrize(
    "phase",
    ["BLIND_SELECT", "SELECTING_HAND", "ROUND_EVAL", "SHOP", "BUFFOON_PACK", "GAME_OVER"],
)
def test_public_observation_codec_round_trips_every_public_phase(phase: str) -> None:
    raw = state(phase, won=phase == "GAME_OVER")
    observation = to_public_observation(raw)

    assert public_observation_from_data(public_observation_to_data(observation)) == observation


def test_public_observation_codec_rejects_unknown_and_missing_fields() -> None:
    data = public_observation_to_data(to_public_observation(state()))
    extra = deepcopy(data)
    extra["seed"] = "PRIVATE"
    missing = deepcopy(data)
    missing.pop("money")

    with pytest.raises(PublicCodecError, match="extra=.*seed"):
        public_observation_from_data(extra)
    with pytest.raises(PublicCodecError, match="missing=.*money"):
        public_observation_from_data(missing)


def test_public_observation_codec_rejects_boolean_integer() -> None:
    data = public_observation_to_data(to_public_observation(state()))
    data["ante"] = True

    with pytest.raises(PublicCodecError, match="ante must be an integer"):
        public_observation_from_data(data)


def test_public_observation_codec_round_trips_and_validates_forced_hand_slot() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(name="Cerulean Bell", status="CURRENT")
    raw["hand"]["cards"][1]["state"] = {
        "highlight": True,
        "forced_selection": True,
    }
    observation = to_public_observation(raw)
    data = public_observation_to_data(observation)

    assert public_observation_from_data(data) == observation
    assert data["required_hand_slots"] == [1]

    data["required_hand_slots"] = [True]
    with pytest.raises(PublicCodecError, match="required_hand_slots item must be an integer"):
        public_observation_from_data(data)


def test_public_observation_codec_round_trips_fixed_joker_runtime_only() -> None:
    raw = state("SHOP")
    raw["shop"]["cards"][0]["key"] = "j_green_joker"
    raw["shop"]["cards"][0]["value"]["ability"] = {"mult": 12, "x_mult": 999}
    data = public_observation_to_data(to_public_observation(raw))
    shop = data["shop"]
    assert isinstance(shop, list) and isinstance(shop[0], dict)

    decoded = public_observation_from_data(data)

    assert decoded.shop[0].runtime is not None
    assert decoded.shop[0].runtime.current_mult == 12
    assert decoded.shop[0].runtime.current_x_mult is None

    shop[0]["runtime"]["future_rng"] = "NOPE"  # type: ignore[index]
    with pytest.raises(PublicCodecError, match="joker runtime fields differ"):
        public_observation_from_data(data)


def test_public_observation_codec_rejects_malformed_card_union() -> None:
    data = public_observation_to_data(to_public_observation(state("SELECTING_HAND")))
    hand = data["hand"]
    assert isinstance(hand, list) and isinstance(hand[0], dict)
    hand[0]["private_id"] = 99

    with pytest.raises(PublicCodecError, match="visible card fields differ"):
        public_observation_from_data(data)


def test_public_codec_has_no_authority_or_candidate_dependency() -> None:
    source = (Path(__file__).resolve().parents[1] / "balatro_ai_v2" / "public_codec.py").read_text()

    assert "balatrobot" not in source.lower()
    assert "jackdaw" not in source.lower()
