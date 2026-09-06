from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import balatro_ai_v2.jackdaw as jackdaw
from balatro_ai_v2.actions import (
    BuyMode,
    BuyPack,
    BuyShopCard,
    CashOut,
    DiscardCards,
    HandSlot,
    LeaveShop,
    OpenedPackSlot,
    PackOfferSlot,
    PlayCards,
    RerollBoss,
    SelectBlind,
    SellConsumable,
    SellJoker,
    ShopSlot,
    SkipPack,
    ConsumableSlot,
    JokerSlot,
    ChoosePackCard,
    action_from_data,
    iter_legal_actions,
)
from balatro_ai_v2.backend import RunSpec
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.balatrobot.tracing import read_verified_trace
from balatro_ai_v2.public_state import HiddenJokerSlot, PublicShopPlayingCard
from state_factory import item_card, state


def _candidate_playing_card(raw_card: dict[str, object], **ability: object) -> object:
    from jackdaw.engine.card_factory import create_playing_card
    from jackdaw.engine.data.enums import Rank, Suit

    value = raw_card["value"]
    assert isinstance(value, dict)
    suit = next(candidate for candidate in Suit if candidate.value.startswith(str(value["suit"])))
    rank = next(
        candidate
        for candidate in Rank
        if candidate.value == {"T": "10", "J": "Jack", "Q": "Queen", "K": "King", "A": "Ace"}.get(
            str(value["rank"]), str(value["rank"])
        )
    )
    card = create_playing_card(suit, rank)
    card.ability.update(ability)
    return card


def test_candidate_module_is_lazy_and_revision_is_pinned() -> None:
    assert jackdaw.JACKDAW_REVISION == "dbedc66255fe594cce7b7cccc188c8a11649d9ec"


def test_schema_six_authority_trace_is_retired_after_public_blind_change() -> None:
    trace = (
        Path(__file__).resolve().parents[1]
        / "runs/evidence/phase1-voucher-affordance-v1-red-white-seed44-authority-20260902-attempt3.jsonl"
    )
    with pytest.raises(ValueError, match="unsupported canonical schema version"):
        read_verified_trace(trace)


def test_candidate_data_bootstrap_copies_missing_pinned_files(tmp_path) -> None:
    package = tmp_path / "jackdaw"
    package.mkdir()
    module = SimpleNamespace(__file__=str(package / "__init__.py"))

    copied = jackdaw._ensure_jackdaw_data(module)

    installed = package / "engine" / "data"
    assert {path.name for path in installed.glob("*.json")} == set(
        jackdaw._JACKDAW_DATA_HASHES
    )
    assert set(copied) == set(jackdaw._JACKDAW_DATA_HASHES)
    assert jackdaw._ensure_jackdaw_data(module) == ()


def test_candidate_data_bootstrap_rejects_existing_mismatch(tmp_path) -> None:
    package = tmp_path / "jackdaw"
    data = package / "engine" / "data"
    data.mkdir(parents=True)
    (data / "centers.json").write_text("{}", encoding="utf-8")
    module = SimpleNamespace(__file__=str(package / "__init__.py"))

    with pytest.raises(
        jackdaw.JackdawUnavailable, match="installed Jackdaw data hash mismatch"
    ):
        jackdaw._ensure_jackdaw_data(module)


def test_candidate_boss_reroll_consumes_money_rng_and_public_allowance() -> None:
    pytest.importorskip("jackdaw")
    backend = jackdaw.JackdawBackend()
    backend.reset(RunSpec("RED", "WHITE", "17"))
    game_state = backend._backend._gs
    game_state["used_vouchers"]["v_retcon"] = True
    game_state["dollars"] = 30
    backend._current = backend._observation(backend._backend.handle("gamestate", {}))
    before = backend.current_public
    assert before is not None
    old_boss = next(blind.name for blind in before.blinds if blind.kind == "BOSS")

    result = backend.step(RerollBoss())

    after = backend.current_public
    assert result.status == "accepted"
    assert after is not None
    assert after.money == 20
    assert after.round.boss_rerolled is True
    assert next(blind.name for blind in after.blinds if blind.kind == "BOSS") != old_boss
    assert RerollBoss() in tuple(iter_legal_actions(after))

    repeated = backend.step(RerollBoss())
    assert repeated.status == "accepted"
    assert backend.current_public is not None
    assert backend.current_public.money == 10


def test_candidate_exposes_visible_idol_tooltip_target() -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine.card_factory import create_joker

    backend = jackdaw.JackdawBackend()
    backend.reset(RunSpec("RED", "WHITE", "2"))
    backend._backend._gs["jokers"].append(create_joker("j_idol"))

    backend.observe()

    assert backend.current_public is not None
    idol = backend.current_public.jokers[0]
    assert idol.runtime is not None
    assert idol.runtime.target_rank in {"2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A"}
    assert idol.runtime.target_suit in {"S", "H", "D", "C"}


def test_candidate_exposes_visible_castle_tooltip_target() -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine.card_factory import create_joker

    backend = jackdaw.JackdawBackend()
    backend.reset(RunSpec("RED", "WHITE", "2"))
    backend._backend._gs["jokers"].append(create_joker("j_castle"))

    backend.observe()

    assert backend.current_public is not None
    castle = backend.current_public.jokers[0]
    assert castle.runtime is not None
    assert castle.runtime.current_chips == 0
    assert castle.runtime.castle_suit in {"S", "H", "D", "C"}


def test_candidate_deck_composition_repairs_stale_private_count() -> None:
    pytest.importorskip("jackdaw")
    backend = jackdaw.JackdawBackend()
    backend.reset(RunSpec("RED", "WHITE", "2"))
    game_state = backend._backend._gs
    game_state["playing_cards_count"] = 52
    game_state["deck"].pop()
    game_state["deck"].pop()

    backend.observe()

    assert backend.current_public is not None
    assert backend.current_public.deck_size == 50
    assert sum(entry.count for entry in backend.current_public.full_deck) == 50


def test_candidate_deck_composition_matches_sparse_authority_wire_shape() -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine.card_factory import create_playing_card
    from jackdaw.engine.data.enums import Rank, Suit

    base = create_playing_card(Suit.CLUBS, Rank.TWO)
    modified = create_playing_card(
        Suit.SPADES,
        Rank.ACE,
        enhancement="m_steel",
        edition={"foil": True},
        seal="Red",
    )

    composition = jackdaw._jackdaw_deck_composition(
        {"deck": [base, modified], "hand": [], "discard_pile": [], "play": []}
    )

    assert composition == [
        {"rank": "2", "suit": "C", "permanent_bonus": 0, "count": 1},
        {
            "rank": "A",
            "suit": "S",
            "enhancement": "STEEL",
            "edition": "FOIL",
            "seal": "RED",
            "permanent_bonus": 0,
            "count": 1,
        },
    ]


def test_candidate_deck_composition_uses_authority_pipe_key_order() -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine.card_factory import create_playing_card
    from jackdaw.engine.data.enums import Rank, Suit

    plain = create_playing_card(Suit.DIAMONDS, Rank.FOUR)
    wild = create_playing_card(
        Suit.DIAMONDS,
        Rank.FOUR,
        enhancement="m_wild",
        seal="Purple",
    )

    composition = jackdaw._jackdaw_deck_composition(
        {"deck": [plain, wild], "hand": [], "discard_pile": [], "play": []}
    )

    assert composition == [
        {
            "rank": "4",
            "suit": "D",
            "enhancement": "WILD",
            "seal": "PURPLE",
            "permanent_bonus": 0,
            "count": 1,
        },
        {"rank": "4", "suit": "D", "permanent_bonus": 0, "count": 1},
    ]


def test_candidate_pack_capacity_survives_selections_and_resets() -> None:
    backend = object.__new__(jackdaw.JackdawBackend)
    backend._active_pack_cards = None
    backend._pack_card_limit = None
    first_pack = [object() for _ in range(5)]

    assert backend._track_pack_card_limit({"pack_cards": first_pack}) == 5
    first_pack.pop()
    assert backend._track_pack_card_limit({"pack_cards": first_pack}) == 5

    queued_pack = [object() for _ in range(3)]
    assert backend._track_pack_card_limit({"pack_cards": queued_pack}) == 3
    assert backend._track_pack_card_limit({"pack_cards": []}) is None
    assert backend._track_pack_card_limit({}) is None


@pytest.mark.parametrize(
    ("blind_name", "marker_remains"),
    [("Cerulean Bell", False), ("The Head", True)],
)
def test_cash_out_clears_only_completed_cerulean_forced_markers(
    blind_name: str,
    marker_remains: bool,
) -> None:
    shared = SimpleNamespace(ability={"x_mult": 1, "forced_selection": True})
    other = SimpleNamespace(ability={"x_mult": 1, "forced_selection": True})
    game_state = {
        "blind": SimpleNamespace(name=blind_name),
        "current_round": {"jokers_purchased": 2, "discards_left": 0, "hands_left": 0},
        "round_resets": {"discards": 4, "hands": 4},
        "round_bonus": {"discards": 0, "next_hands": 0},
        "deck": [shared],
        "hand": [shared, other],
        "discard_pile": [],
        "play": [],
        "chips": 600,
    }
    backend = object.__new__(jackdaw.JackdawBackend)
    backend._backend = SimpleNamespace(_gs=game_state)

    backend._finish_cash_out_compatibility()

    assert ("forced_selection" in shared.ability) is marker_remains
    assert ("forced_selection" in other.ability) is marker_remains


def test_crimson_heart_round_end_clears_only_transient_joker_debuffs() -> None:
    class Joker:
        def __init__(
            self,
            *,
            debuff: bool,
            perishable: bool = False,
            perish_tally: int = 5,
            ability: dict[str, object] | None = None,
        ) -> None:
            self.debuff = debuff
            self.perishable = perishable
            self.perish_tally = perish_tally
            self.ability = {} if ability is None else ability

        def set_debuff(self, value: bool) -> None:
            self.debuff = value

    transient = Joker(debuff=True)
    active_perishable = Joker(debuff=True, perishable=True, perish_tally=2)
    expired_perishable = Joker(debuff=True, perishable=True, perish_tally=0)
    nested_expired = Joker(
        debuff=True,
        ability={"perishable": True, "perish_tally": 0},
    )
    backend = object.__new__(jackdaw.JackdawBackend)
    backend._backend = SimpleNamespace(
        _gs={
            "blind": SimpleNamespace(name="Crimson Heart"),
            "jokers": [
                transient,
                active_perishable,
                expired_perishable,
                nested_expired,
            ],
        }
    )

    backend._clear_crimson_heart_debuffs_at_round_end()

    assert transient.debuff is False
    assert active_perishable.debuff is False
    assert expired_perishable.debuff is True
    assert nested_expired.debuff is True


def test_non_crimson_round_end_does_not_clear_joker_debuffs() -> None:
    joker = SimpleNamespace(debuff=True)
    backend = object.__new__(jackdaw.JackdawBackend)
    backend._backend = SimpleNamespace(
        _gs={"blind": SimpleNamespace(name="The Wall"), "jokers": [joker]}
    )

    backend._clear_crimson_heart_debuffs_at_round_end()

    assert joker.debuff is True


def test_crimson_heart_selects_reordered_joker_by_creation_order() -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine.blind import Blind

    class Joker:
        def __init__(self, sort_id: int) -> None:
            self.sort_id = sort_id
            self.debuff = False

        def set_debuff(self, value: bool) -> None:
            self.debuff = value

    class Rng:
        def seed(self, key: str) -> float:
            assert key == "crimson_heart"
            return 0.5

        def element(self, cards: list[Joker], seed: float) -> tuple[Joker, int]:
            assert seed == 0.5
            assert isinstance(cards, list)
            chosen = min(cards, key=lambda card: card.sort_id)
            return chosen, cards.index(chosen) + 1

    newest = Joker(30)
    oldest = Joker(10)
    middle = Joker(20)
    jokers = [newest, oldest, middle]
    backend = object.__new__(jackdaw.JackdawBackend)
    blind = Blind("test", "Crimson Heart", 100, 2, 5, True)

    with backend._crimson_heart_order_compatibility("select"):
        result = blind.drawn_to_hand([], jokers, Rng())

    assert result["debuffed_joker_index"] == 1
    assert [joker.debuff for joker in jokers] == [False, True, False]

    with backend._crimson_heart_order_compatibility("discard"):
        assert blind.drawn_to_hand([], jokers, Rng()) == {}
    assert [joker.debuff for joker in jokers] == [False, True, False]


def test_economy_tag_money_is_deferred_until_the_next_action() -> None:
    backend = object.__new__(jackdaw.JackdawBackend)
    backend._pending_skip_dollars = 0
    backend._backend = SimpleNamespace(_gs={"dollars": 126})
    before = {
        "money": 86,
        "blinds": {
            "small": {"status": "SELECT", "tag_name": "Economy Tag"},
            "big": {"status": "UPCOMING", "tag_name": "Double Tag"},
        },
    }

    assert backend._defer_economy_tag_dollars(before)
    assert backend._backend._gs["dollars"] == 86
    assert backend._pending_skip_dollars == 40

    backend._apply_pending_skip_dollars()

    assert backend._backend._gs["dollars"] == 126
    assert backend._pending_skip_dollars == 0


def test_zero_dollar_economy_tag_is_a_valid_zero_payout() -> None:
    backend = object.__new__(jackdaw.JackdawBackend)
    backend._pending_skip_dollars = 0
    backend._backend = SimpleNamespace(_gs={"dollars": 0})
    before = {
        "money": 0,
        "blinds": {
            "small": {"status": "DEFEATED", "tag_name": "Skip Tag"},
            "big": {"status": "SELECT", "tag_name": "Economy Tag"},
        },
    }

    assert backend._defer_economy_tag_dollars(before)
    assert backend._backend._gs["dollars"] == 0
    assert backend._pending_skip_dollars == 0


def test_candidate_captures_boss_disabling_sale_before_handler_removes_joker() -> None:
    backend = object.__new__(jackdaw.JackdawBackend)
    blind = SimpleNamespace(name="The Wall", boss=True, disabled=False)
    backend._backend = SimpleNamespace(
        _gs={
            "blind": blind,
            "jokers": [
                SimpleNamespace(center_key="j_joker"),
                SimpleNamespace(center_key="j_luchador"),
            ],
        }
    )

    assert backend._selected_boss_disabling_sale("sell", {"joker": 1})
    assert not backend._selected_boss_disabling_sale("sell", {"joker": 0})

    blind.name = "Verdant Leaf"
    assert backend._selected_boss_disabling_sale("sell", {"joker": 0})
    blind.disabled = True
    assert not backend._selected_boss_disabling_sale("sell", {"joker": 0})
    assert not backend._selected_boss_disabling_sale("buy", {"card": 1})


@pytest.mark.parametrize(
    ("name", "blind_chips", "discards_sub", "hands_sub", "expected"),
    [
        (
            "The Water",
            100,
            3,
            None,
            {"discards_left": 3, "hands_left": 1, "chips": 100},
        ),
        (
            "The Needle",
            100,
            None,
            3,
            {"discards_left": 0, "hands_left": 4, "chips": 100},
        ),
        (
            "The Manacle",
            100,
            None,
            None,
            {"discards_left": 0, "hands_left": 1, "chips": 100},
        ),
        (
            "The Wall",
            100,
            None,
            None,
            {"discards_left": 0, "hands_left": 1, "chips": 50},
        ),
        (
            "Violet Vessel",
            300,
            None,
            None,
            {"discards_left": 0, "hands_left": 1, "chips": 100},
        ),
        (
            "Cerulean Bell",
            100,
            None,
            None,
            {"discards_left": 0, "hands_left": 1, "chips": 100},
        ),
    ],
)
def test_boss_disable_sale_compatibility_applies_special_boss_state(
    name: str,
    blind_chips: int,
    discards_sub: int | None,
    hands_sub: int | None,
    expected: dict[str, int],
) -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine.blind import Blind

    class Card:
        def __init__(self) -> None:
            self.ability = {"forced_selection": True}
            self.debuff = True
            self.facing = "front"

        def set_debuff(self, value: bool) -> None:
            self.debuff = value

    blind = Blind(
        key="test",
        name=name,
        chips=blind_chips,
        mult=2,
        dollars=5,
        boss=True,
        discards_sub=discards_sub,
        hands_sub=hands_sub,
    )
    playing_card = Card()
    joker = Card()
    game_state = {
        "blind": blind,
        "current_round": {"discards_left": 0, "hands_left": 1},
        "deck": [playing_card],
        "hand": [playing_card],
        "discard_pile": [],
        "play": [],
        "jokers": [joker],
        "hand_size": 7,
    }
    backend = object.__new__(jackdaw.JackdawBackend)
    backend._backend = SimpleNamespace(_gs=game_state)

    assert backend._apply_boss_disable_sale_compatibility()

    assert blind.disabled
    assert blind.chips == expected["chips"]
    assert game_state["current_round"] == {
        "discards_left": expected["discards_left"],
        "hands_left": expected["hands_left"],
    }
    assert game_state["hand_size"] == (8 if name == "The Manacle" else 7)
    assert playing_card.debuff is False
    assert joker.debuff is False
    if name == "Cerulean Bell":
        assert "forced_selection" not in playing_card.ability


def test_boss_disable_sale_compatibility_reveals_face_down_state_and_crimson_marker() -> (
    None
):
    pytest.importorskip("jackdaw")
    from jackdaw.engine.blind import Blind

    class Card:
        def __init__(self, ability: dict[str, object]) -> None:
            self.ability = ability
            self.debuff = True
            self.facing = "back"

        def set_debuff(self, value: bool) -> None:
            self.debuff = value

    hand_card = Card({"wheel_flipped": True})
    joker = Card({"crimson_heart_chosen": True})
    backend = object.__new__(jackdaw.JackdawBackend)
    game_state = {
        "blind": Blind("test", "The Wheel", 100, 2, 5, True),
        "current_round": {"discards_left": 1, "hands_left": 4},
        "deck": [hand_card],
        "hand": [hand_card],
        "discard_pile": [],
        "play": [],
        "jokers": [joker],
        "hand_size": 8,
    }
    backend._backend = SimpleNamespace(_gs=game_state)

    assert backend._apply_boss_disable_sale_compatibility()
    assert hand_card.facing == "front"
    assert "wheel_flipped" not in hand_card.ability
    assert joker.facing == "front"

    game_state["blind"] = Blind("test", "Crimson Heart", 100, 2, 5, True)
    game_state["blind"].disabled = False
    joker.ability["crimson_heart_chosen"] = True
    assert backend._apply_boss_disable_sale_compatibility()
    assert "crimson_heart_chosen" not in joker.ability


def test_boss_disable_sale_compatibility_is_inert_outside_an_active_boss() -> None:
    blind = SimpleNamespace(boss=False, disabled=False)
    backend = object.__new__(jackdaw.JackdawBackend)
    backend._backend = SimpleNamespace(_gs={"blind": blind})

    assert not backend._apply_boss_disable_sale_compatibility()
    assert blind.disabled is False


def test_bridge_normalization_preserves_candidate_round_timing() -> None:
    raw = state()
    raw["state"] = "SHOP"
    raw["cards"]["highlighted_limit"] = 0
    raw["cards"]["cards"][0]["set"] = "ENHANCED"
    raw["cards"]["cards"][0]["cost"] = {"buy": 0, "sell": 0}
    raw["cards"]["cards"][0]["state"] = {
        "hidden": False,
        "debuff": False,
        "highlight": False,
    }
    raw["cards"]["cards"][0]["modifier"] = {"edition": None, "eternal": False}
    raw["cards"]["cards"][0]["value"].pop("ability")
    raw["shop"] = {"cards": [], "count": 0, "highlighted_limit": 0, "limit": 0}
    raw["vouchers"] = {"cards": [], "count": 2, "highlighted_limit": 0, "limit": 2}
    raw["round"].pop("ancient_suit")
    raw["round"].pop("most_played_poker_hand")
    raw["round"]["hands_left"] = 0
    raw["round"]["discards_left"] = 0
    raw["used_vouchers"] = {"v_grabber": True}
    private = {
        "deck": [
            _candidate_playing_card(card, x_mult=1)
            for card in raw["cards"]["cards"]
        ],
        "discard_pile": [],
        "hand": [],
        "jokers": [],
        "consumables": [],
        "shop_cards": [],
        "shop": {"joker_max": 0},
        "shop_vouchers": [],
        "shop_voucher_limit": 2,
        "shop_boosters": [],
        "pack_cards": [],
        "current_round": {
            "ancient_card": {"suit": "Hearts"},
            "most_played_poker_hand": "High Card",
        },
        "round": 1,
        "round_resets": {"hands": 4, "discards": 4, "boss_rerolled": False},
    }

    original_raw = json.loads(json.dumps(raw))
    normalized = jackdaw._normalize_jackdaw_bridge(raw, private)
    owned_raw = json.loads(json.dumps(raw))
    owned_normalized = jackdaw._normalize_jackdaw_bridge(
        owned_raw,
        private,
        copy_raw=False,
    )

    assert raw == original_raw
    assert owned_normalized is owned_raw
    assert owned_normalized == normalized
    assert normalized["shop"]["cards"] == []
    assert normalized["vouchers"]["limit"] == 2
    assert normalized["cards"]["highlighted_limit"] == 5
    assert normalized["cards"]["cards"][0]["cost"] == {"buy": 1, "sell": 1}
    assert normalized["cards"]["cards"][0]["state"] == {"hidden": True}
    assert normalized["cards"]["cards"][0]["modifier"] == []
    assert normalized["cards"]["cards"][0]["value"]["ability"] == {"x_mult": 1}
    assert normalized["round"]["ancient_suit"] == "H"
    assert normalized["round"]["hands_left"] == 0
    assert normalized["used_vouchers"] == {"v_grabber": ""}
    assert "Flush Five" in normalized["hands"]


def test_bridge_normalization_redacts_amber_jokers_before_public_projection() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(name="Amber Acorn", status="CURRENT")
    raw["jokers"]["cards"] = [
        item_card("j_blueprint", card_id=70, kind="JOKER"),
        item_card("j_brainstorm", card_id=71, kind="JOKER"),
    ]
    raw["jokers"]["count"] = 2
    for card in raw["jokers"]["cards"]:
        card["state"] = {"hidden": True}
    private = {
        "blind": SimpleNamespace(name="Amber Acorn", disabled=False),
        "deck": [
            _candidate_playing_card(card, x_mult=1)
            for card in raw["cards"]["cards"]
        ],
        "discard_pile": [],
        "hand": [
            _candidate_playing_card(card, x_mult=1)
            for card in raw["hand"]["cards"]
        ],
        "jokers": [
            SimpleNamespace(ability={"x_mult": 1}),
            SimpleNamespace(ability={"x_mult": 1}),
        ],
        "consumables": [],
        "current_round": {},
        "round": 1,
        "round_resets": {"boss_rerolled": False},
    }

    normalized = jackdaw._normalize_jackdaw_bridge(raw, private)
    observation = to_public_observation(normalized)

    assert normalized["jokers"]["cards"] == [
        {"set": "JOKER", "state": {"hidden": True}},
        {"set": "JOKER", "state": {"hidden": True}},
    ]
    assert observation.jokers == (HiddenJokerSlot(), HiddenJokerSlot())


def test_candidate_amber_loss_keeps_terminal_jokers_anonymous() -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine.card_factory import create_joker

    backend = jackdaw.JackdawBackend()
    try:
        backend.reset(RunSpec("RED", "WHITE", "91001"))
        game_state = backend._backend._gs
        game_state["jokers"].append(create_joker("j_joker"))
        game_state["blind_on_deck"] = "Boss"
        game_state["round_resets"]["blind_choices"]["Boss"] = "bl_final_acorn"
        game_state["round_resets"]["blind_states"].update(
            Small="Defeated", Big="Defeated", Boss="Select"
        )
        backend._current = backend._observation(
            backend._backend.handle("gamestate", {})
        )

        selected = backend.step(SelectBlind())
        assert selected.status == "accepted"
        assert backend.current_public is not None
        assert backend.current_public.jokers == (HiddenJokerSlot(),)

        game_state["current_round"]["hands_left"] = 1
        lost = backend.step(PlayCards((HandSlot(0),)))

        assert lost.status == "accepted"
        assert backend.current_public is not None
        assert backend.current_public.phase.value == "GAME_OVER"
        assert backend.current_public.jokers == (HiddenJokerSlot(),)
        assert "j_joker" not in backend.current_public.canonical_json()
    finally:
        backend.close()


def test_bridge_normalization_exposes_cerulean_forced_slot_from_empty_card_state() -> (
    None
):
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(name="Cerulean Bell", status="CURRENT")
    private_hand = [
        _candidate_playing_card(card, x_mult=1, forced_selection=index == 1)
        for index, card in enumerate(raw["hand"]["cards"])
    ]
    private = {
        "blind": SimpleNamespace(name="Cerulean Bell", disabled=False),
        "deck": [
            _candidate_playing_card(card, x_mult=1)
            for card in raw["cards"]["cards"]
        ],
        "discard_pile": [],
        "hand": private_hand,
        "jokers": [],
        "consumables": [],
        "current_round": {
            "ancient_card": {"suit": "Hearts"},
            "most_played_poker_hand": "High Card",
        },
        "round": 1,
        "round_resets": {"boss_rerolled": False},
    }

    normalized = jackdaw._normalize_jackdaw_bridge(raw, private)
    observation = to_public_observation(normalized)

    assert normalized["hand"]["cards"][1]["state"] == {
        "highlight": True,
        "forced_selection": True,
    }
    assert observation.required_hand_slots == (1,)


def test_bridge_normalization_exposes_disabled_cerulean_without_forced_slot() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(name="Cerulean Bell", status="CURRENT")
    cards = [
        _candidate_playing_card(card, x_mult=1)
        for card in raw["hand"]["cards"]
    ]
    private = {
        "blind": SimpleNamespace(name="Cerulean Bell", disabled=True),
        "deck": [
            _candidate_playing_card(card, x_mult=1)
            for card in raw["cards"]["cards"]
        ],
        "discard_pile": [],
        "hand": cards,
        "jokers": [],
        "consumables": [],
        "current_round": {},
        "round": 1,
        "round_resets": {"boss_rerolled": False},
    }

    normalized = jackdaw._normalize_jackdaw_bridge(raw, private)
    observation = to_public_observation(normalized)

    assert normalized["blinds"]["boss"]["disabled"] is True
    assert observation.required_hand_slots == ()


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
            "to_do_poker_hand": "Two Pair",
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
            "poker_hand": "Two Pair",
        },
        "effect": "",
        "perma_bonus": 7,
    }


def test_card_value_normalization_drops_null_optional_fields() -> None:
    value = {"effect": "", "rank": None, "suit": None, "rarity": None}
    card = SimpleNamespace(ability={"x_mult": 1})

    jackdaw._apply_balatrobot_card_values(value, card)

    assert value == {"effect": "", "ability": {"x_mult": 1}}


def test_swashbuckler_display_mult_tracks_other_owned_sell_values() -> None:
    owned = SimpleNamespace(center_key="j_joker", sell_cost=3, ability={})
    owned_swash = SimpleNamespace(
        center_key="j_swashbuckler", sell_cost=2, ability={"mult": 1}
    )
    pack_swash = SimpleNamespace(
        center_key="j_swashbuckler", sell_cost=2, ability={"mult": 1}
    )
    state = {
        "jokers": [owned, owned_swash],
        "shop_cards": [],
        "pack_cards": [pack_swash],
    }

    jackdaw._refresh_swashbuckler_mult(state)

    assert owned_swash.ability["mult"] == 3
    assert pack_swash.ability["mult"] == 5


def test_stencil_display_xmult_tracks_visible_joker_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        jackdaw, "_jackdaw_center", lambda card: {"effect": "Hand Size Mult"}
    )
    owned = [SimpleNamespace(center_key="j_joker", ability={}) for _ in range(5)]
    shop_stencil = SimpleNamespace(
        center_key="j_stencil", ability={"effect": "Hand Size Mult"}, edition=None
    )
    pack_stencil = SimpleNamespace(
        center_key="j_stencil", ability={"effect": "Hand Size Mult"}, edition=None
    )
    game_state = {
        "joker_slots": 5,
        "jokers": owned,
        "shop_cards": [shop_stencil],
        "pack_cards": [pack_stencil],
    }

    jackdaw._refresh_stencil_x_mult(game_state)
    modifier: dict[str, object] = {}
    jackdaw._apply_balatrobot_card_modifiers(modifier, shop_stencil)

    assert shop_stencil.ability["x_mult"] == 0
    assert pack_stencil.ability["x_mult"] == 0
    assert modifier == {"enhancement": "HAND SIZE MULT", "enhancement_x_mult": 0}

    owned_stencil = SimpleNamespace(center_key="j_stencil", ability={})
    game_state["jokers"] = [owned_stencil, *owned[1:]]
    jackdaw._refresh_stencil_x_mult(game_state)

    assert owned_stencil.ability["x_mult"] == 1
    assert shop_stencil.ability["x_mult"] == 1
    assert pack_stencil.ability["x_mult"] == 1


def test_drivers_license_display_tally_tracks_permanent_enhancements() -> None:
    base = object()
    plain = SimpleNamespace(base=base, center_key="c_base")
    enhanced = SimpleNamespace(base=base, center_key="m_bonus")
    driver = SimpleNamespace(center_key="j_drivers_license", ability={})
    shop_driver = SimpleNamespace(center_key="j_drivers_license", ability={})
    pack_driver = SimpleNamespace(center_key="j_drivers_license", ability={})
    game_state = {
        "deck": [plain, enhanced],
        "hand": [],
        "discard_pile": [],
        "play": [enhanced],
        "jokers": [driver],
        "shop_cards": [shop_driver],
        "pack_cards": [pack_driver],
    }

    jackdaw._refresh_drivers_license_tally(game_state)

    assert driver.ability["driver_tally"] == 1
    assert shop_driver.ability["driver_tally"] == 1
    assert pack_driver.ability["driver_tally"] == 1

    game_state["deck"] = [plain]
    game_state["play"] = []
    jackdaw._refresh_drivers_license_tally(game_state)

    assert driver.ability["driver_tally"] == 0


def test_candidate_refreshes_enhancement_gated_joker_pool_state() -> None:
    base = object()
    plain = SimpleNamespace(base=base, center_key="c_base")
    lucky = SimpleNamespace(base=base, center_key="m_lucky")
    gold = SimpleNamespace(base=base, center_key="m_gold")
    game_state = {
        "deck": [plain, lucky],
        "hand": [gold],
        "discard_pile": [],
        "play": [lucky],
        "deck_enhancements": {"m_stale"},
    }

    jackdaw._refresh_deck_enhancements(game_state)

    assert game_state["deck_enhancements"] == {"m_gold", "m_lucky"}

    game_state["deck"] = [plain]
    game_state["hand"] = []
    game_state["play"] = []
    jackdaw._refresh_deck_enhancements(game_state)

    assert game_state["deck_enhancements"] == set()


def test_candidate_places_pack_cryptid_copies_at_deck_front_newest_first() -> None:
    original = SimpleNamespace(center_key="c_base")
    other = SimpleNamespace(center_key="c_base")
    first_copy = SimpleNamespace(center_key="c_base")
    second_copy = SimpleNamespace(center_key="c_base")
    backend = object.__new__(jackdaw.JackdawBackend)
    backend._backend = SimpleNamespace(
        _gs={
            "deck": [original, other, first_copy, second_copy],
            "hand": [],
            "discard_pile": [],
            "play": [],
            "playing_cards_count": 2,
        }
    )

    changed = backend._place_pack_cryptid_copies(
        (frozenset({id(original), id(other)}), 2)
    )

    assert changed is True
    assert backend._backend._gs["deck"] == [
        second_copy,
        first_copy,
        original,
        other,
    ]
    assert backend._backend._gs["playing_cards_count"] == 4


def test_card_modifier_normalization_preserves_explicit_empty_effect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        jackdaw,
        "_jackdaw_center",
        lambda card: {"effect": ""} if card.center_key == "j_throwback" else {},
    )
    explicit: dict[str, object] = {}
    absent: dict[str, object] = {}

    jackdaw._apply_balatrobot_card_modifiers(
        explicit,
        SimpleNamespace(
            center_key="j_throwback", ability={"effect": "", "x_mult": 1}, edition=None
        ),
    )
    jackdaw._apply_balatrobot_card_modifiers(
        absent,
        SimpleNamespace(
            center_key="j_bull", ability={"effect": "", "x_mult": 1}, edition=None
        ),
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

    round_end = backend.step(
        PlayCards(tuple(HandSlot(index) for index in (0, 2, 3, 4, 6)))
    )
    assert round_end.after is not None
    rolled_suit = round_end.after.observed.canonical["round"]["ancient_suit"]
    shop = backend.step(CashOut())
    assert shop.after is not None

    assert rolled_suit == "S"
    assert shop.after.observed.canonical["round"]["ancient_suit"] == rolled_suit
    assert (
        shop.after.observed.canonical["packs"]["cards"][0]["key"] == "p_buffoon_normal"
    )

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


def test_candidate_organic_magic_trick_shop_card_purchase_grows_deck() -> None:
    pytest.importorskip("jackdaw")
    actions = (
        {"type": "select_blind"},
        {"type": "discard_cards", "cards": [1, 2, 5, 6, 7]},
        {"type": "play_cards", "cards": [0, 1, 2, 3, 4]},
        {"type": "play_cards", "cards": [0, 1, 2, 3, 4]},
        {"type": "cash_out"},
        {"type": "buy_shop_card", "card": 0, "mode": "store"},
        {"type": "leave_shop"},
        {"type": "select_blind"},
        {"type": "play_cards", "cards": [0, 1, 2, 3, 4]},
        {"type": "discard_cards", "cards": [0, 1, 3, 4]},
        {"type": "discard_cards", "cards": [0, 2, 5, 6, 7]},
        {"type": "play_cards", "cards": [0, 1, 2, 3, 4]},
        {"type": "play_cards", "cards": [0, 3, 4, 5, 6]},
        {"type": "cash_out"},
        {"type": "buy_voucher", "voucher": 0},
        {"type": "leave_shop"},
        {"type": "select_blind"},
        {"type": "discard_cards", "cards": [0, 5, 6, 7]},
        {"type": "play_cards", "cards": [0, 1, 2, 3, 4]},
        {"type": "discard_cards", "cards": [1, 2, 5, 6, 7]},
        {"type": "play_cards", "cards": [1, 2, 3, 5, 6]},
        {"type": "cash_out"},
    )
    backend = jackdaw.JackdawBackend()
    try:
        observation = backend.reset(RunSpec("RED", "WHITE", "4002"))
        for data in actions:
            result = backend.step(action_from_data(data))
            assert result.status == "accepted"
            assert result.after is not None
            observation = result.after

        before = to_public_observation(json.loads(observation.observed.raw_json))
        assert "v_magic_trick" in before.used_vouchers
        assert isinstance(before.shop[1], PublicShopPlayingCard)
        price = before.shop[1].buy_cost
        result = backend.step(BuyShopCard(ShopSlot(1)))
        assert result.status == "accepted"
        assert result.after is not None
        after = to_public_observation(json.loads(result.after.observed.raw_json))

        assert result.rpc_method == "buy"
        assert result.rpc_params == {"card": 1}
        assert after.money == before.money - price
        assert after.deck_size == before.deck_size + 1
        assert sum(entry.count for entry in after.remaining_deck) == after.deck_size
        assert len(after.shop) == len(before.shop) - 1
    finally:
        backend.close()


def test_candidate_planet_buy_and_use_is_atomic_at_full_capacity() -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine.actions import GamePhase
    from jackdaw.engine.card_factory import create_consumable, create_joker
    from jackdaw.engine.data.hands import HandType

    backend = jackdaw.JackdawBackend()
    try:
        backend.reset(RunSpec("RED", "WHITE", "9001"))
        game_state = backend._backend._gs
        planet = create_consumable("c_mercury")
        planet.cost = 3
        planet.edition = {"negative": True}
        game_state["phase"] = GamePhase.SHOP
        game_state["dollars"] = 10
        game_state["shop_cards"] = [planet]
        game_state["shop_vouchers"] = []
        game_state["shop_boosters"] = []
        game_state["shop_voucher_limit"] = 1
        game_state["shop_booster_limit"] = 2
        game_state["consumables"] = [
            create_consumable("c_uranus"),
            create_consumable("c_pluto"),
        ]
        game_state["consumable_slots"] = 2
        constellation = create_joker("j_constellation")
        game_state["jokers"] = [constellation]
        backend.observe()
        before_level = game_state["hand_levels"].get_state(HandType.PAIR).level
        before_x_mult = constellation.ability["x_mult"]

        result = backend.step(BuyShopCard(ShopSlot(0), BuyMode.USE))

        assert result.status == "accepted"
        assert result.after is not None
        after = to_public_observation(json.loads(result.after.observed.raw_json))
        assert result.rpc_params == {"card": 0, "mode": "use"}
        assert after.money == 7
        assert len(after.shop) == 0
        assert len(after.consumables) == 2
        assert after.consumable_limit == 2
        pair = next(hand for hand in after.hand_stats if hand.name == "Pair")
        assert pair.level == before_level + 1
        assert after.last_tarot_planet == "c_mercury"
        assert game_state["cards_purchased"] == 1
        assert game_state["consumable_usage"]["c_mercury"]["count"] == 1
        assert constellation.ability["x_mult"] == pytest.approx(before_x_mult + 0.1)
    finally:
        backend.close()


def test_candidate_pack_inventory_sales_preserve_pack_and_fire_campfire() -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine.actions import GamePhase
    from jackdaw.engine.card_factory import create_consumable, create_joker

    backend = jackdaw.JackdawBackend()
    try:
        backend.reset(RunSpec("RED", "WHITE", "9005"))
        game_state = backend._backend._gs
        campfire = create_joker("j_campfire")
        owned = create_joker("j_joker")
        owned.sell_cost = 2
        consumable = create_consumable("c_mercury")
        consumable.sell_cost = 1
        offered = create_joker("j_greedy_joker")
        game_state["phase"] = GamePhase.PACK_OPENING
        game_state["pack_type"] = "Buffoon"
        game_state["pack_cards"] = [offered]
        game_state["pack_choices_remaining"] = 1
        game_state["jokers"] = [campfire, owned]
        game_state["joker_slots"] = 2
        game_state["consumables"] = [consumable]
        game_state["consumable_slots"] = 2
        game_state["dollars"] = 10
        backend.observe()

        before = backend.current_public
        assert before is not None
        assert before.pack_kind == "BUFFOON"
        assert ChoosePackCard(OpenedPackSlot(0)) not in tuple(
            iter_legal_actions(before)
        )
        assert SellJoker(JokerSlot(1)) in tuple(iter_legal_actions(before))

        sold_joker = backend.step(SellJoker(JokerSlot(1)))

        after_joker = backend.current_public
        assert sold_joker.status == "accepted"
        assert after_joker is not None
        assert after_joker.phase.value == "PACK"
        assert after_joker.pack_kind == "BUFFOON"
        assert after_joker.pack_choices_remaining == 1
        assert len(after_joker.opened_pack) == 1
        assert after_joker.money == 12
        assert campfire.ability["x_mult"] == pytest.approx(1.25)
        assert ChoosePackCard(OpenedPackSlot(0)) in tuple(
            iter_legal_actions(after_joker)
        )

        sold_consumable = backend.step(SellConsumable(ConsumableSlot(0)))

        after_consumable = backend.current_public
        assert sold_consumable.status == "accepted"
        assert after_consumable is not None
        assert after_consumable.phase.value == "PACK"
        assert after_consumable.pack_kind == "BUFFOON"
        assert after_consumable.pack_choices_remaining == 1
        assert len(after_consumable.opened_pack) == 1
        assert after_consumable.money == 13
        assert campfire.ability["x_mult"] == pytest.approx(1.5)
    finally:
        backend.close()


def test_candidate_preserves_original_suit_tiebreaker_across_sun_and_ouija() -> (
    None
):
    pytest.importorskip("jackdaw")
    from jackdaw.engine.card_factory import create_playing_card
    from jackdaw.engine.data.enums import Rank, Suit
    from jackdaw.engine.game import _sort_hand_desc

    changed_diamond = create_playing_card(Suit.DIAMONDS, Rank.FOUR)
    original_heart = create_playing_card(Suit.HEARTS, Rank.JACK)
    assert changed_diamond.base is not None
    assert original_heart.base is not None
    diamond_original = changed_diamond.base.suit_nominal_original
    heart_original = original_heart.base.suit_nominal_original
    backend = jackdaw.JackdawBackend()

    with backend._original_suit_nominal_compatibility():
        changed_diamond.change_suit("Hearts")
        changed_diamond.change_rank("5")
        original_heart.change_rank("5")

    hand = [changed_diamond, original_heart]
    _sort_hand_desc(hand)

    assert changed_diamond.base is not None
    assert original_heart.base is not None
    assert changed_diamond.base.suit_nominal_original == diamond_original
    assert original_heart.base.suit_nominal_original == heart_original
    assert hand == [original_heart, changed_diamond]


def test_candidate_reveals_secret_hand_on_first_play() -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.bridge.serializer import serialize_hands
    from jackdaw.engine.data.hands import HandType
    from jackdaw.engine.hand_levels import HandLevels

    hand_levels = HandLevels()
    backend = jackdaw.JackdawBackend()

    with backend._secret_hand_visibility_compatibility():
        hand_levels.record_play(HandType.FIVE_OF_A_KIND)

    state = hand_levels.get_state(HandType.FIVE_OF_A_KIND)
    assert state.visible is True
    assert state.played == 1
    assert serialize_hands(hand_levels)["Five of a Kind"]["played"] == 1


def test_candidate_defers_nonexpiring_turtle_bean_decay_at_terminal_snapshot() -> (
    None
):
    turtle = SimpleNamespace(
        center_key="j_turtle_bean",
        ability={"extra": {"h_size": 5, "h_mod": 1}},
    )
    backend = object.__new__(jackdaw.JackdawBackend)
    backend._backend = SimpleNamespace(
        _gs={"hand_size": 13, "jokers": [turtle]}
    )

    snapshot = backend._terminal_turtle_bean_snapshot("play")
    backend._backend._gs["hand_size"] = 12
    turtle.ability["extra"]["h_size"] = 4
    backend._restore_terminal_turtle_bean(snapshot)

    assert backend._backend._gs["hand_size"] == 13
    assert turtle.ability["extra"] == {"h_size": 4, "h_mod": 1}
    assert backend._terminal_turtle_bean_snapshot("gamestate") is None


def test_candidate_buy_and_use_rejection_does_not_mutate_state() -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine.actions import GamePhase
    from jackdaw.engine.card_factory import create_consumable

    backend = jackdaw.JackdawBackend()
    try:
        backend.reset(RunSpec("RED", "WHITE", "9002"))
        game_state = backend._backend._gs
        tarot = create_consumable("c_magician")
        tarot.cost = 3
        game_state["phase"] = GamePhase.SHOP
        game_state["dollars"] = 10
        game_state["shop_cards"] = [tarot]
        game_state["shop_vouchers"] = []
        game_state["shop_boosters"] = []
        game_state["shop_voucher_limit"] = 1
        game_state["shop_booster_limit"] = 2
        backend.observe()
        before = backend._handle("gamestate", {})

        with pytest.raises(backend._rpc_error):
            backend._buy_and_use_planet_compatibility({"card": 0, "mode": "use"})
        assert backend._handle("gamestate", {}) == before
        assert game_state["shop_cards"] == [tarot]
        assert game_state["dollars"] == 10
    finally:
        backend.close()


def test_candidate_buy_and_use_rejects_unknown_planet_key() -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine.actions import GamePhase
    from jackdaw.engine.card_factory import create_consumable

    backend = jackdaw.JackdawBackend()
    try:
        backend.reset(RunSpec("RED", "WHITE", "9004"))
        game_state = backend._backend._gs
        planet = create_consumable("c_mercury")
        planet.center_key = "c_modded_planet"
        game_state["phase"] = GamePhase.SHOP
        game_state["dollars"] = 10
        game_state["shop_cards"] = [planet]

        with pytest.raises(backend._rpc_error, match="known Planets only"):
            backend._buy_and_use_planet_compatibility({"card": 0, "mode": "use"})

        assert game_state["shop_cards"] == [planet]
        assert game_state["dollars"] == 10
    finally:
        backend.close()


def test_candidate_buy_and_use_rolls_back_post_mutation_failure_with_credit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine import game
    from jackdaw.engine.actions import GamePhase
    from jackdaw.engine.card_factory import create_consumable

    backend = jackdaw.JackdawBackend()
    try:
        backend.reset(RunSpec("RED", "WHITE", "9003"))
        game_state = backend._backend._gs
        planet = create_consumable("c_mercury")
        planet.cost = 3
        game_state["phase"] = GamePhase.SHOP
        game_state["dollars"] = 0
        game_state["bankrupt_at"] = -20
        game_state["shop_cards"] = [planet]
        game_state["shop_vouchers"] = []
        game_state["shop_boosters"] = []
        game_state["shop_voucher_limit"] = 1
        game_state["shop_booster_limit"] = 2
        before = backend._handle("gamestate", {})

        def fail_after_purchase(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("forced Planet failure")

        monkeypatch.setattr(game, "_use_consumable_card", fail_after_purchase)
        with pytest.raises(RuntimeError, match="forced Planet failure"):
            backend._buy_and_use_planet_compatibility({"card": 0, "mode": "use"})

        assert backend._backend._gs is game_state
        assert backend._handle("gamestate", {}) == before
        assert game_state["dollars"] == 0
        assert game_state["bankrupt_at"] == -20
    finally:
        backend.close()


def test_candidate_seed_five_gold_shop_stickers_use_stake_modifiers() -> None:
    pytest.importorskip("jackdaw")
    actions = (
        SelectBlind(),
        DiscardCards(tuple(HandSlot(index) for index in (3, 4, 5, 7))),
        PlayCards(tuple(HandSlot(index) for index in (1, 3, 4, 5, 7))),
        DiscardCards(tuple(HandSlot(index) for index in (1, 3, 5, 6))),
        PlayCards(tuple(HandSlot(index) for index in (0, 1, 5, 6, 7))),
        CashOut(),
    )
    backend = jackdaw.JackdawBackend()
    try:
        poker_hand_order = [
            "Five of a Kind",
            "Straight Flush",
            "Four of a Kind",
            "Full House",
            "Flush",
            "Straight",
            "Three of a Kind",
            "Two Pair",
            "Pair",
            "High Card",
            "Flush Five",
            "Flush House",
        ]
        backend.configure_replay(
            {
                "poker_hand_iteration_order": poker_hand_order,
                "hands": dict.fromkeys(poker_hand_order),
            }
        )
        backend.reset(RunSpec("RED", "GOLD", "5"))
        result = None
        for action in actions:
            result = backend.step(action)
            assert result.status == "accepted"
            assert result.after is not None
        assert result is not None and result.after is not None
        offers = result.after.observed.canonical["shop"]["cards"]
        assert [offer["key"] for offer in offers] == ["j_crafty", "j_todo_list"]
        assert offers[0]["modifier"] == {"rental": True}
        assert offers[0]["cost"] == {"buy": 1, "sell": 1}
        assert offers[1]["modifier"] == {}
        assert offers[1]["cost"] == {"buy": 4, "sell": 2}

        continuation = (
            BuyShopCard(ShopSlot(1)),
            BuyShopCard(ShopSlot(0)),
            LeaveShop(),
            SelectBlind(),
            DiscardCards(tuple(HandSlot(index) for index in (0, 7))),
            DiscardCards(tuple(HandSlot(index) for index in (5, 6, 7))),
            PlayCards(tuple(HandSlot(index) for index in (0, 1, 2, 4, 5))),
            PlayCards(tuple(HandSlot(index) for index in (0, 1, 2, 3, 4))),
            PlayCards(tuple(HandSlot(index) for index in (0, 1, 2, 4, 5))),
            PlayCards(tuple(HandSlot(index) for index in (0, 1, 5, 6, 7))),
        )
        for action in continuation:
            result = backend.step(action)
            assert result.status == "accepted"
            assert result.after is not None
        assert result.after.observed.canonical["state"] == "GAME_OVER"
        assert result.after.observed.canonical["money"] == 1
    finally:
        backend.close()


def test_candidate_hiker_permanent_bonus_survives_discard_serialization() -> None:
    pytest.importorskip("jackdaw")
    actions = (
        {"type": "select_blind"},
        {"type": "play_cards", "cards": [0, 2, 4, 5, 7]},
        {"type": "play_cards", "cards": [0, 1, 2, 4, 5]},
        {"type": "cash_out"},
        {"type": "buy_shop_card", "card": 1, "mode": "store"},
        {"type": "leave_shop"},
        {"type": "select_blind"},
        {"type": "play_cards", "cards": [0, 3, 4, 5, 7]},
    )
    backend = jackdaw.JackdawBackend()
    try:
        backend.reset(RunSpec("RED", "WHITE", "40096"))
        result = None
        for action in actions:
            result = backend.step(action_from_data(action))
            assert result.after is not None
        assert result is not None and result.after is not None
        discard_values = [
            card["value"]
            for card in result.after.observed.canonical["discard"]["cards"]
        ]
        assert any(value.get("perma_bonus") == 5 for value in discard_values)
    finally:
        backend.close()


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
    assert {
        key: boss_eval["blinds"][key]["status"] for key in ("small", "big", "boss")
    } == {
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


def test_duplicate_shop_boosters_mirror_vanilla_physical_order() -> None:
    first = SimpleNamespace(center_key="p_celestial_normal", cost=4)
    second = SimpleNamespace(center_key="p_celestial_normal", cost=4)
    different = SimpleNamespace(center_key="p_arcana_normal", cost=4)

    duplicate_state = {"shop_boosters": [first, second]}
    jackdaw._mirror_duplicate_booster_emplacement(duplicate_state)
    assert duplicate_state["shop_boosters"] == [second, first]

    distinct_state = {"shop_boosters": [first, different]}
    jackdaw._mirror_duplicate_booster_emplacement(distinct_state)
    assert distinct_state["shop_boosters"] == [first, different]


def test_troubadour_hand_reset_waits_for_blind_selection() -> None:
    pytest.importorskip("jackdaw")
    backend = jackdaw.JackdawBackend()
    observation = backend.reset(RunSpec("RED", "WHITE", "3"))
    actions = [
        {"type": "select_blind"},
        {"cards": [0, 1, 2, 3, 4], "type": "play_cards"},
        {"type": "cash_out"},
        {"card": 1, "mode": "store", "type": "buy_shop_card"},
        {"pack": 0, "type": "buy_pack"},
        {"card": 0, "targets": [], "type": "choose_pack_card"},
        {"type": "leave_shop"},
    ]
    for action in actions:
        result = backend.step(action_from_data(action))
        assert result.after is not None
        observation = result.after

    assert observation.observed.canonical["state"] == "BLIND_SELECT"
    assert observation.observed.canonical["round"]["hands_left"] == 4

    selected = backend.step(action_from_data({"type": "select_blind"}))
    assert selected.after is not None
    assert selected.after.observed.canonical["round"]["hands_left"] == 3


def test_blind_skip_tag_pack_has_no_stale_shop_areas() -> None:
    pytest.importorskip("jackdaw")
    backend = jackdaw.JackdawBackend()
    backend.reset(RunSpec("RED", "WHITE", "5"))

    opened = backend.step(action_from_data({"type": "skip_blind"}))
    assert opened.after is not None
    assert opened.after.observed.canonical["state"] == "TAROT_PACK"
    assert all(
        area not in opened.after.observed.canonical
        for area in ("shop", "packs", "vouchers")
    )
    assert opened.after.observed.canonical["round"]["hands_left"] == 4
    assert opened.after.observed.canonical["round"]["discards_left"] == 4

    skipped = backend.step(action_from_data({"type": "skip_pack"}))
    assert skipped.after is not None
    assert skipped.after.observed.canonical["state"] == "BLIND_SELECT"


def test_replay_uses_authority_vm_order_for_to_do_list() -> None:
    pytest.importorskip("jackdaw")
    order = (
        "Straight Flush",
        "Four of a Kind",
        "Full House",
        "Flush",
        "Straight",
        "Three of a Kind",
        "Two Pair",
        "Pair",
        "High Card",
    )
    backend = jackdaw.JackdawBackend()
    backend.configure_replay(
        {
            "hands": {name: {} for name in order},
            "poker_hand_iteration_order": list(order),
        }
    )
    observation = backend.reset(RunSpec("RED", "WHITE", "5"))
    assert observation.observed.canonical["poker_hand_iteration_order"] == list(order)
    for action in (
        {"type": "skip_blind"},
        {"type": "skip_pack"},
        {"type": "select_blind"},
        {"cards": [7, 5, 4, 3], "type": "discard_cards"},
        {"cards": [1, 3, 4, 5, 7], "type": "play_cards"},
        {"cards": [5, 6, 3, 1], "type": "discard_cards"},
        {"cards": [0, 1, 5, 6, 7], "type": "play_cards"},
        {"type": "cash_out"},
    ):
        result = backend.step(action_from_data(action))
        assert result.after is not None
        observation = result.after

    assert (
        observation.observed.canonical["shop"]["cards"][1]["value"]["ability"][
            "poker_hand"
        ]
        == "Full House"
    )


def test_boss_most_played_tie_uses_last_runtime_table_entry() -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine.hand_levels import HandLevels

    levels = HandLevels()
    for name in ("Straight Flush", "Full House", "Straight", "Two Pair"):
        levels.record_play(name)
    order = (
        "Straight Flush",
        "Four of a Kind",
        "Full House",
        "Flush",
        "Straight",
        "Three of a Kind",
        "Two Pair",
        "Pair",
        "High Card",
        "Flush Five",
        "Flush House",
        "Five of a Kind",
    )

    assert jackdaw._vanilla_most_played_hand(levels, order).value == "Two Pair"


def test_orbital_tag_uses_visible_authority_table_order() -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine.hand_levels import HandLevels
    from jackdaw.engine.tags import Tag

    class Seventh:
        @staticmethod
        def seed(_key: str) -> float:
            return 0.5

        @staticmethod
        def random(_seed: float, _minimum: int, _maximum: int) -> int:
            return 7

    order = (
        "Flush",
        "Straight",
        "Three of a Kind",
        "Two Pair",
        "Pair",
        "High Card",
        "Flush Five",
        "Flush House",
        "Five of a Kind",
        "Straight Flush",
        "Four of a Kind",
        "Full House",
    )
    backend = jackdaw.JackdawBackend()
    backend._poker_hand_iteration_order = order
    game_state = {
        "blind_on_deck": "Small",
        "hand_levels": HandLevels(),
        "rng": Seventh(),
        "round_resets": {"ante": 3},
    }
    backend._backend._gs = game_state
    backend._initialize_orbital_choices()

    with backend._poker_hand_order_compatibility():
        result = Tag("tag_orbital").apply(
            "immediate",
            game_state,
            game_state["rng"],
        )

    assert result is not None
    assert result.level_up is not None
    assert result.level_up[0].value == "Straight Flush"
    assert set(game_state["orbital_choices"][3]) == {"Small", "Big", "Boss"}


def test_hook_discards_follow_hand_position_not_random_selection_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine import game

    left = object()
    middle = object()
    right = object()
    backend = jackdaw.JackdawBackend()
    backend._backend._gs = {"hand": [left, middle, right]}
    calls: list[tuple[list[object], bool]] = []

    monkeypatch.setattr(
        game,
        "_fire_discard_effects",
        lambda _state, discarded, *, hook: calls.append((list(discarded), hook)),
    )
    with backend._play_compatibility():
        game._fire_discard_effects({}, [right, left], hook=True)
        game._fire_discard_effects({}, [right, left], hook=False)

    assert calls == [([left, right], True), ([right, left], False)]


@pytest.mark.parametrize(
    ("planet_keys", "debuff_first", "red_mult", "plasma_value"),
    [
        (("c_mercury",), False, 15.0, 57),
        (("c_mercury", "c_mercury"), False, 22.5, 61),
        (("c_uranus",), False, 10.0, 55),
        (("c_mercury",), True, 10.0, 55),
    ],
)
def test_observatory_compatibility_scores_before_deck_back(
    monkeypatch: pytest.MonkeyPatch,
    planet_keys: tuple[str, ...],
    debuff_first: bool,
    red_mult: float,
    plasma_value: int,
) -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine import scoring
    from jackdaw.engine.back import Back
    from jackdaw.engine.card_factory import create_consumable, create_playing_card
    from jackdaw.engine.data.enums import Rank, Suit

    played = [
        create_playing_card(Suit.SPADES, Rank.ACE),
        create_playing_card(Suit.HEARTS, Rank.ACE),
    ]
    consumables = [create_consumable(key) for key in planet_keys]
    if debuff_first:
        consumables[0].set_debuff(True)
    game_state = {
        "used_vouchers": {"v_observatory": True},
        "consumables": consumables,
    }
    backend = object.__new__(jackdaw.JackdawBackend)
    backend._backend = SimpleNamespace(_gs=game_state)

    def score_through_back(**kwargs: object) -> dict[str, float]:
        effect = Back(str(kwargs["back_key"])).trigger_effect(
            "final_scoring_step",
            chips=100.0,
            mult=10.0,
        )
        return effect or {"chips": 100.0, "mult": 10.0}

    monkeypatch.setattr(scoring, "score_hand", score_through_back)
    with backend._observatory_scoring_compatibility():
        red = scoring.score_hand(
            played_cards=played,
            held_cards=[],
            jokers=[],
            game_state=game_state,
            back_key="b_red",
        )
        plasma = scoring.score_hand(
            played_cards=played,
            held_cards=[],
            jokers=[],
            game_state=game_state,
            back_key="b_plasma",
        )

    assert red == {"chips": 100.0, "mult": red_mult}
    assert plasma == {"chips": plasma_value, "mult": plasma_value}


def test_standard_pack_edition_reprices_playing_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine import packs
    from jackdaw.engine.card_factory import create_playing_card
    from jackdaw.engine.data.enums import Rank, Suit

    card = create_playing_card(Suit.HEARTS, Rank.TEN, edition={"foil": True})
    monkeypatch.setattr(packs, "_gen_standard", lambda *_args: card)
    backend = jackdaw.JackdawBackend()

    with backend._standard_pack_cost_compatibility():
        generated = packs._gen_standard(None, 3, {})

    assert generated is card
    assert generated.cost == 3
    assert generated.sell_cost == 1


def test_credit_card_floor_applies_to_all_candidate_purchases() -> None:
    pytest.importorskip("jackdaw")
    backend = jackdaw.JackdawBackend()
    game_state = {
        "bankrupt_at": -20,
        "current_round": {"free_rerolls": 0, "reroll_cost": 5},
        "dollars": 3,
        "shop_boosters": [SimpleNamespace(cost=6)],
        "shop_cards": [SimpleNamespace(cost=4)],
        "shop_vouchers": [SimpleNamespace(cost=10)],
    }
    backend._backend._gs = game_state

    for method, params, cost in (
        ("buy", {"card": 0}, 4),
        ("buy", {"voucher": 0}, 10),
        ("buy", {"pack": 0}, 6),
        ("reroll", {}, 5),
    ):
        game_state["dollars"] = 3
        with backend._credit_compatibility(method, params) as used_credit:
            assert used_credit
            game_state["dollars"] -= cost
        assert game_state["dollars"] == 3 - cost
