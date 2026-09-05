from __future__ import annotations

from copy import deepcopy
from dataclasses import fields

import pytest

from balatro_ai_v2.actions import (
    PlayCards,
    ReorderJokers,
    SellJoker,
    action_to_data,
    iter_legal_actions,
)
from balatro_ai_v2.balatrobot.adapter import ObservationError, to_public_observation
from balatro_ai_v2.baselines import PUBLIC_BASELINE_NAMES, build_public_baseline
from balatro_ai_v2.public_state import (
    HiddenHandCard,
    HiddenJokerSlot,
    OBSCURED_CARD_ATTRIBUTE,
    Phase,
    PublicObservation,
    PublicShopPlayingCard,
)
from state_factory import hidden_joker_slot, item_card, playing_card, state


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
    left_hidden = playing_card(
        "S_A", card_id=800, hidden=True, modifier=["POLYCHROME"], debuffed=True
    )
    right_hidden = playing_card(
        "D_2",
        card_id=999,
        hidden=True,
        modifier=["POLYCHROME"],
        permanent_bonus=25,
    )
    left["hand"]["cards"][0] = left_hidden
    right["hand"]["cards"][0] = right_hidden
    # Preserve the public Remaining multiset while varying which private card
    # occupies the anonymous hand slot.
    left["cards"]["cards"][0] = deepcopy(right_hidden)
    right["cards"]["cards"][0] = deepcopy(left_hidden)

    left_public = to_public_observation(left)
    right_public = to_public_observation(right)

    assert isinstance(left_public.hand[0], HiddenHandCard)
    assert left_public == right_public


def test_full_deck_is_unordered_public_composition_without_private_ids() -> None:
    raw = state("SELECTING_HAND")
    raw["deck_composition"] = [
        {
            "rank": "K",
            "suit": "H",
            "enhancement": "STEEL",
            "edition": "POLYCHROME",
            "seal": "RED",
            "permanent_bonus": 7,
            "count": 52,
        }
    ]

    observation = to_public_observation(raw)

    assert len(observation.full_deck) == 1
    assert observation.full_deck[0].count == observation.deck_size == 52
    assert observation.full_deck[0].card.rank == "K"
    assert '"id":' not in observation.canonical_json()

    raw["deck_composition"][0]["private_id"] = 99
    with pytest.raises(ObservationError, match="fields differ"):
        to_public_observation(raw)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("rank", "PRIVATE_RANK", "rank or suit"),
        ("suit", "PRIVATE_SUIT", "rank or suit"),
        ("enhancement", "PRIVATE_ENHANCEMENT", "enhancement"),
        ("edition", "PRIVATE_EDITION", "edition"),
        ("seal", "PRIVATE_SEAL", "seal"),
    ],
)
def test_full_deck_rejects_unknown_card_semantics(
    field: str, value: str, message: str
) -> None:
    raw = state()
    raw["deck_composition"][0][field] = value

    with pytest.raises(ObservationError, match=message):
        to_public_observation(raw)


def test_full_deck_rejects_unobscured_stone_identity() -> None:
    raw = state()
    raw["deck_composition"][0]["enhancement"] = "STONE"

    with pytest.raises(ObservationError, match="Stone identity must be obscured"):
        to_public_observation(raw)


def test_full_deck_does_not_encode_hidden_hand_location() -> None:
    left = state("SELECTING_HAND")
    right = deepcopy(left)
    left_hidden = playing_card("S_A", card_id=800, hidden=True)
    right_hidden = playing_card("D_2", card_id=999, hidden=True)
    left["hand"]["cards"][0] = left_hidden
    right["hand"]["cards"][0] = right_hidden
    left["cards"]["cards"][0] = deepcopy(right_hidden)
    right["cards"]["cards"][0] = deepcopy(left_hidden)

    left_public = to_public_observation(left)
    right_public = to_public_observation(right)

    assert left_public.full_deck == right_public.full_deck
    assert left_public == right_public


def test_face_down_edition_does_not_change_aura_observation() -> None:
    plain = state("SELECTING_HAND")
    edited = deepcopy(plain)
    plain_hidden = playing_card("S_A", card_id=800, hidden=True)
    edited_hidden = playing_card(
        "D_2", card_id=999, hidden=True, modifier=["FOIL"]
    )
    plain["hand"]["cards"][0] = plain_hidden
    edited["hand"]["cards"][0] = edited_hidden
    plain["cards"]["cards"][0] = deepcopy(edited_hidden)
    edited["cards"]["cards"][0] = deepcopy(plain_hidden)

    plain_card = to_public_observation(plain).hand[0]
    edited_card = to_public_observation(edited).hand[0]

    assert isinstance(plain_card, HiddenHandCard)
    assert isinstance(edited_card, HiddenHandCard)
    assert plain_card == HiddenHandCard()
    assert edited_card == HiddenHandCard()
    assert to_public_observation(plain) == to_public_observation(edited)


def _amber_state() -> dict[str, object]:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(
        {"name": "Amber Acorn", "status": "CURRENT", "effect": "Flips and shuffles Jokers"}
    )
    raw["jokers"] = {
        "cards": [hidden_joker_slot(), hidden_joker_slot()],
        "count": 2,
        "highlighted_limit": 1,
        "limit": 5,
    }
    return raw


def test_amber_acorn_jokers_are_anonymous_and_not_selectable_by_identity() -> None:
    observation = to_public_observation(_amber_state())
    actions = tuple(iter_legal_actions(observation))

    assert observation.jokers == (HiddenJokerSlot(), HiddenJokerSlot())
    assert any(isinstance(action, PlayCards) for action in actions)
    assert not any(isinstance(action, SellJoker | ReorderJokers) for action in actions)
    assert "j_" not in observation.canonical_json()


def test_amber_acorn_loss_keeps_terminal_jokers_anonymous() -> None:
    raw = _amber_state()
    raw["state"] = "GAME_OVER"

    observation = to_public_observation(raw)

    assert observation.phase == Phase.GAME_OVER
    assert observation.jokers == (HiddenJokerSlot(), HiddenJokerSlot())
    assert "j_" not in observation.canonical_json()


@pytest.mark.parametrize(
    ("phase", "boss_update"),
    (
        ("SHOP", {}),
        ("GAME_OVER", {"disabled": True}),
        ("GAME_OVER", {"name": "The Head"}),
        ("GAME_OVER", {"status": "DEFEATED"}),
    ),
)
def test_anonymous_jokers_outside_live_amber_hand_or_loss_fail_closed(
    phase: str,
    boss_update: dict[str, object],
) -> None:
    raw = _amber_state()
    raw["state"] = phase
    raw["blinds"]["boss"].update(boss_update)

    with pytest.raises(ValueError, match="anonymous Joker slots"):
        to_public_observation(raw)


@pytest.mark.parametrize("baseline_name", PUBLIC_BASELINE_NAMES)
def test_every_public_baseline_plays_amber_without_joker_identity(
    baseline_name: str,
) -> None:
    observation = to_public_observation(_amber_state())
    legal = tuple(iter_legal_actions(observation))
    policy, _ = build_public_baseline(baseline_name, "amber-firewall")

    action = policy.choose_action(observation, lambda: iter(legal), ())

    assert action in legal
    assert not isinstance(action, SellJoker | ReorderJokers)


def test_hidden_joker_full_payload_or_malformed_marker_fails_closed() -> None:
    full = _amber_state()
    leaked = item_card("j_blueprint", card_id=999, kind="JOKER")
    leaked["state"] = {"hidden": True}
    full["jokers"]["cards"][0] = leaked
    malformed = _amber_state()
    malformed["jokers"]["cards"][0]["state"]["hidden"] = 1

    with pytest.raises(ObservationError, match="exposed private fields"):
        to_public_observation(full)
    with pytest.raises(ObservationError, match="must be boolean"):
        to_public_observation(malformed)


def test_hidden_marker_outside_joker_area_fails_closed() -> None:
    raw = state("SHOP")
    raw["shop"]["cards"][0]["state"] = {"hidden": True}

    with pytest.raises(ObservationError, match="hidden item"):
        to_public_observation(raw)


def test_draw_pile_is_public_composition_but_not_private_order() -> None:
    left = state()
    reordered = deepcopy(left)
    reordered["cards"]["cards"].reverse()
    changed = deepcopy(left)
    changed["cards"]["cards"][0] = playing_card("C_7", card_id=1, hidden=True)
    changed_bonus = deepcopy(left)
    changed_bonus["cards"]["cards"][0]["value"]["perma_bonus"] = 5

    assert to_public_observation(left) == to_public_observation(reordered)
    assert to_public_observation(left) != to_public_observation(changed)
    assert to_public_observation(left) != to_public_observation(changed_bonus)


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


def test_admitted_joker_runtime_is_fixed_and_tooltip_visible() -> None:
    raw = state("SELECTING_HAND")
    raw["jokers"]["cards"] = [
        item_card("j_green_joker", card_id=100, kind="JOKER", ability={"mult": 17}),
        item_card("j_runner", card_id=101, kind="JOKER", ability={"chips": 75}),
        item_card("j_constellation", card_id=102, kind="JOKER", ability={"x_mult": 1.7}),
        item_card("j_rocket", card_id=103, kind="JOKER", ability={"dollars": 6}),
        item_card("j_selzer", card_id=104, kind="JOKER", ability={"extra": 5}),
        item_card("j_loyalty_card", card_id=105, kind="JOKER", ability={"loyalty_remaining": 0}),
        item_card("j_drivers_license", card_id=106, kind="JOKER", ability={"driver_tally": 16}),
        item_card("j_todo_list", card_id=107, kind="JOKER", ability={"poker_hand": "Flush"}),
        item_card(
            "j_idol",
            card_id=108,
            kind="JOKER",
            ability={"idol_rank": "K", "idol_suit": "H"},
        ),
    ]
    raw["jokers"]["count"] = len(raw["jokers"]["cards"])

    runtimes = [joker.runtime for joker in to_public_observation(raw).jokers]

    assert runtimes[0] is not None and runtimes[0].current_mult == 17
    assert runtimes[1] is not None and runtimes[1].current_chips == 75
    assert runtimes[2] is not None and runtimes[2].current_x_mult == 1.7
    assert runtimes[3] is not None and runtimes[3].current_dollars == 6
    assert runtimes[4] is not None and runtimes[4].remaining_hands == 5
    assert runtimes[5] is not None and runtimes[5].loyalty_remaining == 0
    assert runtimes[6] is not None and runtimes[6].driver_tally == 16
    assert runtimes[7] is not None and runtimes[7].target_hand == "Flush"
    assert runtimes[8] is not None
    assert (runtimes[8].target_rank, runtimes[8].target_suit) == ("K", "H")


def test_visible_idol_target_is_strict_but_hidden_idol_remains_anonymous() -> None:
    raw = state("SELECTING_HAND")
    raw["jokers"]["cards"] = [
        item_card("j_idol", card_id=108, kind="JOKER", ability={"idol_rank": "K"})
    ]
    raw["jokers"]["count"] = 1

    with pytest.raises(ObservationError, match="both rank and suit"):
        to_public_observation(raw)

    raw["jokers"]["cards"] = [{"set": "JOKER", "state": {"hidden": True}}]
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(name="Amber Acorn", status="CURRENT")
    observation = to_public_observation(raw)
    assert observation.jokers == (HiddenJokerSlot(),)


def test_unlisted_or_malformed_joker_ability_never_crosses_the_firewall() -> None:
    raw = state("SELECTING_HAND")
    raw["jokers"]["cards"] = [
        item_card("j_joker", card_id=100, kind="JOKER", ability={"future_rng": "NOPE"})
    ]
    raw["jokers"]["count"] = 1

    assert to_public_observation(raw).jokers[0].runtime is None

    raw["jokers"]["cards"][0] = item_card(
        "j_green_joker", card_id=100, kind="JOKER", ability={"mult": "not-a-number"}
    )
    with pytest.raises(ObservationError, match="joker ability mult must be an integer"):
        to_public_observation(raw)


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
    assert observation.round.ancient_suit == "H"


def test_magic_trick_shop_card_preserves_only_visible_card_semantics() -> None:
    raw = state("SHOP", seed="SECRET-A")
    card = playing_card("H_K", card_id=991)
    card["cost"]["buy"] = 2
    card["modifier"] = {"enhancement": "", "edition": "FOIL", "seal": "RED"}
    raw["shop"] = {"cards": [card], "count": 1, "highlighted_limit": 1, "limit": 2}
    raw["used_vouchers"] = ["v_magic_trick"]

    twin = deepcopy(raw)
    twin["seed"] = "SECRET-B"
    twin["shop"]["cards"][0]["id"] = 123_456

    observation = to_public_observation(raw)
    twin_observation = to_public_observation(twin)

    assert observation == twin_observation
    assert isinstance(observation.shop[0], PublicShopPlayingCard)
    assert observation.shop[0].buy_cost == 2
    assert observation.shop[0].card.rank == "K"
    assert observation.shop[0].card.suit == "H"
    assert observation.shop[0].card.edition == "FOIL"
    assert observation.shop[0].card.seal == "RED"


def test_illusion_stone_shop_card_hides_private_base_identity() -> None:
    left = state("SHOP", seed="SECRET-A")
    stone = playing_card("H_K", card_id=996, modifier=["STONE", "FOIL", "RED"])
    stone["set"] = "ENHANCED"
    stone["cost"]["buy"] = 5
    left["shop"] = {
        "cards": [stone],
        "count": 1,
        "highlighted_limit": 1,
        "limit": 2,
    }
    left["used_vouchers"] = ["v_magic_trick", "v_illusion"]
    right = deepcopy(left)
    right["seed"] = "SECRET-B"
    right_stone = right["shop"]["cards"][0]
    right_stone["id"] = 123_457
    right_stone["key"] = "C_2"
    right_stone["value"]["rank"] = "2"
    right_stone["value"]["suit"] = "C"

    left_public = to_public_observation(left)
    right_public = to_public_observation(right)

    assert left_public == right_public
    offer = left_public.shop[0]
    assert isinstance(offer, PublicShopPlayingCard)
    assert offer.card.rank == OBSCURED_CARD_ATTRIBUTE
    assert offer.card.suit == OBSCURED_CARD_ATTRIBUTE
    assert offer.card.enhancement == "STONE"
    assert offer.card.edition == "FOIL"
    assert offer.card.seal == "RED"


def test_shop_playing_card_hidden_or_set_modifier_mismatch_fails_closed() -> None:
    hidden = state("SHOP")
    hidden_card = playing_card("C_2", card_id=992, hidden=True)
    hidden["shop"] = {
        "cards": [hidden_card],
        "count": 1,
        "highlighted_limit": 1,
        "limit": 2,
    }
    with pytest.raises(ObservationError, match="hidden card identity"):
        to_public_observation(hidden)

    mismatched = state("SHOP")
    enhanced = playing_card("D_6", card_id=993, modifier=["BONUS"])
    mismatched["shop"] = {
        "cards": [enhanced],
        "count": 1,
        "highlighted_limit": 1,
        "limit": 2,
    }
    with pytest.raises(ObservationError, match="set disagrees"):
        to_public_observation(mismatched)


@pytest.mark.parametrize("bad_cost", [True, "1", None])
def test_shop_playing_card_invalid_buy_cost_fails_closed(bad_cost: object) -> None:
    raw = state("SHOP")
    card = playing_card("C_2", card_id=994)
    card["cost"]["buy"] = bad_cost
    raw["shop"] = {"cards": [card], "count": 1, "highlighted_limit": 1, "limit": 2}

    with pytest.raises(ObservationError, match="buy must be an integer"):
        to_public_observation(raw)


def test_shop_playing_card_negative_buy_cost_fails_closed() -> None:
    raw = state("SHOP")
    card = playing_card("C_2", card_id=995)
    card["cost"]["buy"] = -1
    raw["shop"] = {"cards": [card], "count": 1, "highlighted_limit": 1, "limit": 2}

    with pytest.raises(ObservationError, match="buy cost must be non-negative"):
        to_public_observation(raw)


def test_transient_animation_state_is_not_a_policy_decision() -> None:
    raw = state("SELECTING_HAND")
    raw["state"] = "DRAW_TO_HAND"

    with pytest.raises(ObservationError, match="unsupported Balatro state"):
        to_public_observation(raw)


def test_closed_pack_stale_choice_counter_is_not_public_pack_metadata() -> None:
    raw = state("SHOP")
    raw["pack_choices_remaining"] = 1

    observation = to_public_observation(raw)

    assert observation.pack_kind is None
    assert observation.pack_choices_remaining == 0

    raw["pack_choices_remaining"] = "1"
    with pytest.raises(ObservationError, match="pack_choices_remaining must be an integer"):
        to_public_observation(raw)
