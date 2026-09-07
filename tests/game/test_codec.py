from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from balatro_ai.game.adapter import to_public_observation
from balatro_ai.game.codec import (
    PublicCodecError,
    public_observation_from_data,
    public_observation_to_data,
)
from balatro_ai.game.state import HiddenJokerSlot, PublicItem
from state_factory import hidden_joker_slot, playing_card, state


@pytest.mark.parametrize(
    "phase",
    ["BLIND_SELECT", "SELECTING_HAND", "ROUND_EVAL", "SHOP", "BUFFOON_PACK", "GAME_OVER"],
)
def test_public_observation_codec_round_trips_every_public_phase(phase: str) -> None:
    raw = state(phase, won=phase == "GAME_OVER")
    observation = to_public_observation(raw)

    assert public_observation_from_data(public_observation_to_data(observation)) == observation


def test_codec_round_trips_only_anonymous_joker_slots_in_amber_area() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update({"name": "Amber Acorn", "status": "CURRENT"})
    raw["jokers"] = {
        "cards": [hidden_joker_slot(), hidden_joker_slot()],
        "count": 2,
        "highlighted_limit": 1,
        "limit": 5,
    }
    observation = to_public_observation(raw)
    data = public_observation_to_data(observation)

    assert data["jokers"] == [{}, {}]
    assert public_observation_from_data(data) == observation
    assert observation.jokers == (HiddenJokerSlot(), HiddenJokerSlot())

    partial = deepcopy(data)
    partial["jokers"][0] = {"kind": "JOKER"}
    with pytest.raises(PublicCodecError, match="fields differ"):
        public_observation_from_data(partial)

    wrong_zone = deepcopy(data)
    wrong_zone["consumables"] = [{}]
    with pytest.raises(PublicCodecError, match="fields differ"):
        public_observation_from_data(wrong_zone)


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

    wrong_total = public_observation_to_data(to_public_observation(state()))
    wrong_total["full_deck"][0]["count"] = 49
    with pytest.raises(ValueError, match="equal the declared deck size"):
        public_observation_from_data(wrong_total)


def test_round_codec_preserves_frozen_ox_target_and_reads_legacy_rows() -> None:
    observation = to_public_observation(state())
    data = public_observation_to_data(observation)

    assert data["round"]["most_played_hand"] == "High Card"
    assert public_observation_from_data(data) == observation

    legacy = deepcopy(data)
    legacy["round"].pop("most_played_hand")
    decoded = public_observation_from_data(legacy)
    assert decoded == replace(
        observation,
        round=replace(observation.round, most_played_hand=None),
    )

    malformed = deepcopy(data)
    malformed["round"]["most_played_hand"] = "Royal Flush"
    with pytest.raises(ValueError, match="unsupported most-played"):
        public_observation_from_data(malformed)


def test_public_observation_codec_rejects_boolean_integer() -> None:
    data = public_observation_to_data(to_public_observation(state()))
    data["ante"] = True

    with pytest.raises(PublicCodecError, match="ante must be an integer"):
        public_observation_from_data(data)

    data = public_observation_to_data(to_public_observation(state()))
    data["round"]["boss_rerolled"] = 1
    with pytest.raises(PublicCodecError, match="round.boss_rerolled must be a boolean"):
        public_observation_from_data(data)


def test_finite_scientific_scores_canonicalize_to_unbounded_public_integers() -> None:
    raw = state("ROUND_EVAL")
    raw["round"]["chips"] = 1e200
    raw["blinds"]["small"]["score"] = 1e199
    raw["hands"]["High Card"]["chips"] = 1e180

    observation = to_public_observation(raw)

    assert isinstance(observation.round.chips, int)
    assert observation.round.chips > 10**199
    assert public_observation_from_data(public_observation_to_data(observation)) == observation


def test_non_integral_or_non_finite_scientific_scores_fail_closed() -> None:
    non_integral = state("ROUND_EVAL")
    non_integral["round"]["chips"] = 1.5
    non_finite = state("ROUND_EVAL")
    non_finite["blinds"]["small"]["score"] = float("inf")

    with pytest.raises(Exception, match="finite integer"):
        to_public_observation(non_integral)
    with pytest.raises(Exception, match="finite integer"):
        to_public_observation(non_finite)


@pytest.mark.parametrize(
    ("ante", "used_vouchers", "expected"),
    [
        (6, [], 5),
        (6, ["v_hieroglyph"], 6),
        (6, ["v_hieroglyph", "v_petroglyph"], 7),
    ],
)
def test_antes_cleared_accounts_for_public_ante_reduction_vouchers(
    ante: int, used_vouchers: list[str], expected: int
) -> None:
    raw = state("SHOP")
    raw["ante_num"] = ante
    raw["used_vouchers"] = used_vouchers

    observation = to_public_observation(raw)

    assert observation.antes_cleared == expected
    assert not observation.won


@pytest.mark.parametrize(
    ("ante", "used_vouchers", "expected"),
    [
        (9, [], 8),
        (9, ["v_hieroglyph"], 9),
        (9, ["v_hieroglyph", "v_petroglyph"], 10),
    ],
)
def test_victory_metric_supports_eight_to_ten_completed_bosses(
    ante: int, used_vouchers: list[str], expected: int
) -> None:
    raw = state("ROUND_EVAL", won=True)
    raw["ante_num"] = ante
    raw["used_vouchers"] = used_vouchers

    observation = to_public_observation(raw)

    assert observation.won
    assert observation.antes_cleared == expected


def test_public_observation_rejects_win_before_eight_cleared_antes() -> None:
    raw = state("ROUND_EVAL")
    raw["won"] = True

    with pytest.raises(ValueError, match="at least eight"):
        to_public_observation(raw)


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


def test_public_blind_disabled_contract_is_strict_and_round_trips() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(
        name="Cerulean Bell", status="CURRENT", disabled=True
    )

    observation = to_public_observation(raw)
    data = public_observation_to_data(observation)

    assert observation.required_hand_slots == ()
    assert public_observation_from_data(data) == observation

    missing = deepcopy(data)
    missing["blinds"][2].pop("disabled")
    with pytest.raises(PublicCodecError, match="missing=.*disabled"):
        public_observation_from_data(missing)

    malformed = deepcopy(data)
    malformed["blinds"][2]["disabled"] = 1
    with pytest.raises(PublicCodecError, match="blind.disabled must be a boolean"):
        public_observation_from_data(malformed)

    impossible = deepcopy(data)
    impossible["blinds"][0]["disabled"] = True
    with pytest.raises(ValueError, match="only the current boss"):
        public_observation_from_data(impossible)

    stale_slot = deepcopy(data)
    stale_slot["required_hand_slots"] = [0]
    with pytest.raises(ValueError, match="forced hand slots require"):
        public_observation_from_data(stale_slot)


def test_adapter_rejects_stale_forced_marker_after_cerulean_is_disabled() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(
        name="Cerulean Bell", status="CURRENT", disabled=True
    )
    raw["hand"]["cards"][0]["state"] = {
        "highlight": True,
        "forced_selection": True,
    }

    with pytest.raises(Exception, match="inconsistent with the active blind"):
        to_public_observation(raw)


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

    v12 = deepcopy(data)
    v12_shop = v12["shop"]
    assert isinstance(v12_shop, list) and isinstance(v12_shop[0], dict)
    v12_runtime = v12_shop[0]["runtime"]
    assert isinstance(v12_runtime, dict)
    for field in (
        "invisible_rounds",
        "mail_rank",
        "current_hand_size_bonus",
        "remaining_discards",
    ):
        v12_runtime.pop(field)
    assert public_observation_from_data(v12) == decoded

    v11 = deepcopy(v12)
    v11_shop = v11["shop"]
    assert isinstance(v11_shop, list) and isinstance(v11_shop[0], dict)
    v11_runtime = v11_shop[0]["runtime"]
    assert isinstance(v11_runtime, dict)
    v11_runtime.pop("castle_suit")
    assert public_observation_from_data(v11) == decoded

    wrong_owner = deepcopy(data)
    wrong_shop = wrong_owner["shop"]
    assert isinstance(wrong_shop, list) and isinstance(wrong_shop[0], dict)
    wrong_runtime = wrong_shop[0]["runtime"]
    assert isinstance(wrong_runtime, dict)
    wrong_runtime["mail_rank"] = "A"
    with pytest.raises(PublicCodecError, match="only j_mail"):
        public_observation_from_data(wrong_owner)

    shop[0]["runtime"]["future_rng"] = "NOPE"  # type: ignore[index]
    with pytest.raises(PublicCodecError, match="joker runtime fields differ"):
        public_observation_from_data(data)


def test_public_codec_rejects_partial_or_unknown_idol_target() -> None:
    raw = state("SHOP")
    raw["shop"]["cards"][0] = playing_card("H_K", card_id=20)
    raw["jokers"]["cards"] = [
        {
            "cost": {"buy": 6, "sell": 3},
            "id": 90,
            "key": "j_idol",
            "label": "The Idol",
            "modifier": [],
            "set": "JOKER",
            "state": {},
            "value": {
                "ability": {"idol_rank": "K", "idol_suit": "H"},
                "effect": "Retrigger",
            },
        }
    ]
    raw["jokers"]["count"] = 1
    data = public_observation_to_data(to_public_observation(raw))
    assert public_observation_from_data(data) == to_public_observation(raw)

    data["jokers"][0]["runtime"]["target_suit"] = None
    with pytest.raises(PublicCodecError, match="both rank and suit"):
        public_observation_from_data(data)

    data = public_observation_to_data(to_public_observation(raw))
    data["jokers"][0]["key"] = "j_joker"
    with pytest.raises(PublicCodecError, match="only a visible Idol"):
        public_observation_from_data(data)


def test_public_observation_codec_rejects_malformed_card_union() -> None:
    data = public_observation_to_data(to_public_observation(state("SELECTING_HAND")))
    hand = data["hand"]
    assert isinstance(hand, list) and isinstance(hand[0], dict)
    hand[0]["private_id"] = 99

    with pytest.raises(PublicCodecError, match="visible card fields differ"):
        public_observation_from_data(data)


def test_shop_playing_card_codec_round_trips_full_visible_card_and_cost() -> None:
    raw = state("SHOP")
    card = playing_card("S_A", card_id=901, modifier=["GLASS", "POLYCHROME", "BLUE"])
    card["set"] = "ENHANCED"
    card["cost"]["buy"] = 0
    raw["shop"] = {"cards": [card], "count": 1, "highlighted_limit": 1, "limit": 2}
    observation = to_public_observation(raw)

    data = public_observation_to_data(observation)
    decoded = public_observation_from_data(data)

    assert decoded == observation
    assert decoded.shop[0].buy_cost == 0
    assert decoded.shop[0].card.enhancement == "GLASS"
    assert decoded.shop[0].card.edition == "POLYCHROME"
    assert decoded.shop[0].card.seal == "BLUE"


def test_public_codec_enforces_opaque_stone_identity() -> None:
    raw = state("SHOP")
    card = playing_card("S_A", card_id=906, modifier=["STONE"])
    card["set"] = "ENHANCED"
    raw["shop"] = {"cards": [card], "count": 1, "highlighted_limit": 1, "limit": 2}
    encoded = public_observation_to_data(to_public_observation(raw))

    exposed = deepcopy(encoded)
    exposed["shop"][0]["card"]["rank"] = "A"  # type: ignore[index]
    exposed["shop"][0]["card"]["suit"] = "S"  # type: ignore[index]
    with pytest.raises(PublicCodecError, match="must obscure"):
        public_observation_from_data(exposed)

    non_stone = deepcopy(encoded)
    non_stone["shop"][0]["card"]["enhancement"] = "GLASS"  # type: ignore[index]
    with pytest.raises(PublicCodecError, match="only Stone"):
        public_observation_from_data(non_stone)


def test_shop_playing_card_codec_rejects_legacy_and_malformed_shapes() -> None:
    legacy = public_observation_to_data(to_public_observation(state("SHOP")))
    legacy["shop"][0]["kind"] = "DEFAULT"  # type: ignore[index]
    legacy["shop"][0]["key"] = "H_K"  # type: ignore[index]
    with pytest.raises(ValueError, match="generic public item"):
        public_observation_from_data(legacy)

    raw = state("SHOP")
    raw["shop"] = {
        "cards": [playing_card("C_2", card_id=902)],
        "count": 1,
        "highlighted_limit": 1,
        "limit": 2,
    }
    malformed = public_observation_to_data(to_public_observation(raw))
    malformed["shop"][0]["buy_cost"] = True  # type: ignore[index]
    with pytest.raises(PublicCodecError, match="buy_cost must be an integer"):
        public_observation_from_data(malformed)

    malformed["shop"][0]["buy_cost"] = -1  # type: ignore[index]
    with pytest.raises(PublicCodecError, match="buy_cost must be non-negative"):
        public_observation_from_data(malformed)

    malformed["shop"][0].pop("buy_cost")  # type: ignore[index]
    with pytest.raises(PublicCodecError, match="shop offer has unknown fields"):
        public_observation_from_data(malformed)


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("joker", "canonical uppercase"),
        ("DEFAULT", "generic public item"),
        ("ENHANCED", "generic public item"),
        ("FUTURE", "unsupported public item kind"),
    ],
)
def test_public_item_rejects_noncanonical_or_generic_kinds(
    kind: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        PublicItem("test", "Test", kind)


@pytest.mark.parametrize(
    ("zone", "kind"),
    [
        ("jokers", "TAROT"),
        ("consumables", "JOKER"),
        ("vouchers", "BOOSTER"),
        ("packs", "VOUCHER"),
        ("shop", "VOUCHER"),
        ("shop", "BOOSTER"),
        ("opened_pack", "VOUCHER"),
        ("opened_pack", "BOOSTER"),
    ],
)
def test_public_observation_rejects_item_kinds_in_the_wrong_zone(
    zone: str, kind: str
) -> None:
    phase = "TAROT_PACK" if zone == "opened_pack" else "SHOP"
    observation = to_public_observation(state(phase))
    malformed = PublicItem("test", "Test", kind)

    with pytest.raises(ValueError, match=f"{zone} contains unsupported"):
        replace(observation, **{zone: (malformed,)})


def test_spectral_item_is_valid_in_an_arcana_pack() -> None:
    observation = to_public_observation(state("TAROT_PACK"))
    soul = PublicItem("c_soul", "The Soul", "SPECTRAL")

    updated = replace(observation, opened_pack=(soul,))

    assert updated.pack_kind == "ARCANA"
    assert updated.opened_pack == (soul,)
    assert public_observation_from_data(public_observation_to_data(updated)) == updated


def test_public_codec_has_no_authority_or_candidate_dependency() -> None:
    source = (Path(__file__).resolve().parents[2] / "balatro_ai" / "game" / "codec.py").read_text()

    assert "balatrobot" not in source.lower()
    assert "jackdaw" not in source.lower()
