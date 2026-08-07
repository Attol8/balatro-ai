from __future__ import annotations

from types import SimpleNamespace

import pytest

import balatro_ai_v2.jackdaw as jackdaw
from balatro_ai_v2.actions import (
    BuyPack,
    BuyShopCard,
    CashOut,
    DiscardCards,
    HandSlot,
    LeaveShop,
    PackOfferSlot,
    PlayCards,
    SelectBlind,
    ShopSlot,
    SkipPack,
    action_from_data,
)
from balatro_ai_v2.backend import RunSpec
from tests.state_factory import state


def test_candidate_module_is_lazy_and_revision_is_pinned() -> None:
    assert jackdaw.JACKDAW_REVISION == "dbedc66255fe594cce7b7cccc188c8a11649d9ec"


def test_bridge_normalization_uses_candidate_state_for_balatrobot_defaults() -> None:
    raw = state()
    raw["cards"]["highlighted_limit"] = 0
    raw["cards"]["cards"][0]["set"] = "ENHANCED"
    raw["cards"]["cards"][0]["cost"] = {"buy": 0, "sell": 0}
    raw["cards"]["cards"][0]["state"] = {"hidden": False, "debuff": False, "highlight": False}
    raw["cards"]["cards"][0]["modifier"] = {"edition": None, "eternal": False}
    raw["cards"]["cards"][0]["value"].pop("ability")
    raw["shop"] = {"cards": [], "count": 0, "highlighted_limit": 0, "limit": 0}
    raw["round"].pop("ancient_suit")
    raw["round"].pop("most_played_poker_hand")
    raw["round"]["hands_left"] = 0
    raw["round"]["discards_left"] = 0
    raw["used_vouchers"] = {"v_grabber": True}
    private = {
        "deck": [SimpleNamespace(ability={"x_mult": 1}) for _ in raw["cards"]["cards"]],
        "hand": [],
        "jokers": [],
        "consumables": [],
        "shop_cards": [],
        "shop_vouchers": [],
        "shop_boosters": [],
        "pack_cards": [],
        "current_round": {
            "ancient_card": {"suit": "Hearts"},
            "most_played_poker_hand": "High Card",
        },
        "round_resets": {"hands": 4, "discards": 4},
    }

    normalized = jackdaw._normalize_jackdaw_bridge(raw, private)

    assert "shop" not in normalized
    assert normalized["cards"]["highlighted_limit"] == 5
    assert normalized["cards"]["cards"][0]["cost"] == {"buy": 1, "sell": 1}
    assert normalized["cards"]["cards"][0]["state"] == {"hidden": True}
    assert normalized["cards"]["cards"][0]["modifier"] == []
    assert normalized["cards"]["cards"][0]["value"]["ability"] == {"x_mult": 1}
    assert normalized["round"]["ancient_suit"] == "H"
    assert normalized["round"]["hands_left"] == 4
    assert normalized["used_vouchers"] == {"v_grabber": ""}
    assert "Flush Five" in normalized["hands"]


def test_card_ability_normalization_matches_balatrobot_extractor() -> None:
    value = {"effect": ""}
    card = SimpleNamespace(
        ability={
            "extra": {"chips": 2, "nested": {"ignored": True}, "flag": False},
            "t_mult": 0,
            "t_chips": 50,
            "mult": 0,
            "x_mult": 1,
            "driver_tally": 0,
            "loyalty_remaining": 0,
            "perma_bonus": 7,
        }
    )

    jackdaw._apply_balatrobot_card_values(value, card)

    assert value == {
        "ability": {
            "chips": 2,
            "flag": False,
            "t_chips": 50,
            "x_mult": 1,
            "driver_tally": 0,
            "loyalty_remaining": 0,
        },
        "effect": "",
        "perma_bonus": 7,
    }


def test_card_value_normalization_drops_null_optional_fields() -> None:
    value = {"effect": "", "rank": None, "suit": None, "rarity": None}
    card = SimpleNamespace(ability={"x_mult": 1})

    jackdaw._apply_balatrobot_card_values(value, card)

    assert value == {"effect": "", "ability": {"x_mult": 1}}


def test_card_modifier_normalization_preserves_explicit_empty_effect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        jackdaw,
        "_jackdaw_center",
        lambda card: {"effect": ""} if card.center_key == "j_throwback" else {},
    )
    explicit: dict[str, object] = {}
    absent: dict[str, object] = {}

    jackdaw._apply_balatrobot_card_modifiers(
        explicit,
        SimpleNamespace(center_key="j_throwback", ability={"effect": "", "x_mult": 1}, edition=None),
    )
    jackdaw._apply_balatrobot_card_modifiers(
        absent,
        SimpleNamespace(center_key="j_bull", ability={"effect": "", "x_mult": 1}, edition=None),
    )

    assert explicit == {"enhancement": ""}
    assert absent == {}


def test_candidate_seed_one_shop_and_pack_compatibility() -> None:
    pytest.importorskip("jackdaw")
    backend = jackdaw.JackdawBackend()
    backend.reset(RunSpec("RED", "WHITE", "1"))
    backend.step(SelectBlind())
    backend.step(DiscardCards(tuple(HandSlot(index) for index in (6, 7, 5, 3, 2))))
    backend.step(DiscardCards(tuple(HandSlot(index) for index in (5, 4, 3, 2))))

    round_end = backend.step(PlayCards(tuple(HandSlot(index) for index in (0, 2, 3, 4, 6))))
    assert round_end.after is not None
    rolled_suit = round_end.after.observed.canonical["round"]["ancient_suit"]
    shop = backend.step(CashOut())
    assert shop.after is not None

    assert rolled_suit == "S"
    assert shop.after.observed.canonical["round"]["ancient_suit"] == rolled_suit
    assert shop.after.observed.canonical["packs"]["cards"][0]["key"] == "p_buffoon_normal_2"

    opened = backend.step(BuyPack(PackOfferSlot(1)))
    assert opened.after is not None
    assert opened.after.observed.canonical["state"] == "PLANET_PACK"
    assert opened.after.observed.canonical["pack"]["limit"] == 5

    skipped = backend.step(SkipPack())
    assert skipped.after is not None
    assert skipped.after.observed.canonical["packs"]["limit"] == 2
    backend.step(BuyShopCard(ShopSlot(0)))
    next_blind = backend.step(LeaveShop())
    assert next_blind.after is not None
    assert next_blind.after.observed.canonical["state"] == "BLIND_SELECT"
    assert next_blind.after.observed.canonical["shop"]["count"] == 1
    assert next_blind.after.observed.canonical["shop"]["cards"] == []


def test_candidate_seed_two_ante_pack_and_voucher_regression() -> None:
    pytest.importorskip("jackdaw")
    actions = [
        {"type": "select_blind"},
        {"cards": [3, 4, 0, 2], "type": "discard_cards"},
        {"cards": [1, 3, 5, 6, 7], "type": "play_cards"},
        {"cards": [6, 3, 4, 1], "type": "discard_cards"},
        {"cards": [0, 1, 2, 3, 4], "type": "play_cards"},
        {"type": "cash_out"},
        {"pack": 0, "type": "buy_pack"},
        {"card": 0, "targets": [], "type": "choose_pack_card"},
        {"type": "leave_shop"},
        {"type": "skip_blind"},
        {"type": "select_blind"},
        {"cards": [7, 5, 4, 1, 2], "type": "discard_cards"},
        {"cards": [6, 5, 0, 2], "type": "discard_cards"},
        {"cards": [0, 3, 4, 5, 6], "type": "play_cards"},
        {"cards": [0, 1, 2, 4, 5], "type": "play_cards"},
        {"cards": [0, 1, 2, 4, 5], "type": "play_cards"},
        {"cards": [1, 3, 4, 5, 6], "type": "play_cards"},
        {"type": "cash_out"},
        {"pack": 0, "type": "buy_pack"},
        {"card": 1, "targets": [], "type": "choose_pack_card"},
        {"card": 1, "mode": "store", "type": "buy_shop_card"},
        {"type": "leave_shop"},
        {"type": "skip_blind"},
        {"type": "skip_blind"},
        {"type": "select_blind"},
        {"cards": [6, 4, 2, 3, 0], "type": "discard_cards"},
        {"cards": [0, 2, 3, 6, 7], "type": "play_cards"},
        {"type": "cash_out"},
        {"pack": 0, "type": "buy_pack"},
        {"type": "skip_pack"},
        {"type": "buy_voucher", "voucher": 0},
    ]
    backend = jackdaw.JackdawBackend()
    backend.reset(RunSpec("RED", "WHITE", "2"))
    states = []
    for action in actions:
        result = backend.step(action_from_data(action))
        assert result.after is not None
        states.append(result.after.observed.canonical)

    boss_eval = states[16]
    assert boss_eval["ante_num"] == 2
    assert boss_eval["round"]["most_played_poker_hand"] == "Flush"
    assert {key: boss_eval["blinds"][key]["status"] for key in ("small", "big", "boss")} == {
        "small": "DEFEATED",
        "big": "SKIPPED",
        "boss": "DEFEATED",
    }

    next_ante_shop = states[17]
    assert next_ante_shop["money"] == 36
    assert next_ante_shop["blinds"]["big"]["tag_name"] == "Economy Tag"
    assert next_ante_shop["blinds"]["boss"]["name"] == "The Fish"
    assert next_ante_shop["vouchers"]["cards"][0]["key"] == "v_blank"

    standard_pick = states[19]
    assert standard_pick["cards"]["limit"] == 53
    assert standard_pick["cards"]["cards"][0]["id"] == "spawn:13:DEFAULT:C_7"

    spectral_pack = states[28]
    assert spectral_pack["state"] == "SPECTRAL_PACK"
    assert len(spectral_pack["hand"]["cards"]) == 8
    assert len(spectral_pack["cards"]["cards"]) == 45

    grabber = states[30]
    assert grabber["round"]["hands_left"] == 5
    assert grabber["used_vouchers"] == {"v_grabber": ""}
