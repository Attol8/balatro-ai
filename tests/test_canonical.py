from __future__ import annotations

from copy import deepcopy

import pytest

from balatro_ai_v2.canonical import BalatroBotCanonicalizer, CanonicalizationError
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from state_factory import hidden_joker_slot, item_card, state


def test_raw_ids_and_presentation_text_do_not_affect_semantic_state() -> None:
    left = state("SHOP")
    right = deepcopy(left)
    for area_name in ("cards", "hand", "jokers", "consumables", "shop", "packs", "vouchers"):
        for card in (right.get(area_name) or {}).get("cards", []):
            card["id"] += 10000
            card["label"] = "Translated label"
            card["value"]["effect"] = "Translated effect"
    right["blinds"]["small"]["effect"] = "Translated blind text"
    right["hands"]["High Card"]["example"] = [["D_2", False]]

    left_state = BalatroBotCanonicalizer().canonicalize(left)
    right_state = BalatroBotCanonicalizer().canonicalize(right)

    assert left_state.raw_digest != right_state.raw_digest
    assert left_state.canonical_digest == right_state.canonical_digest


def test_order_and_mutable_ability_are_semantic() -> None:
    raw = state("SHOP")
    reordered = deepcopy(raw)
    reordered["cards"]["cards"].reverse()
    mutated = deepcopy(raw)
    mutated["shop"]["cards"][0]["value"]["ability"]["mult"] = 7

    baseline = BalatroBotCanonicalizer().canonicalize(raw).canonical_digest

    assert BalatroBotCanonicalizer().canonicalize(reordered).canonical_digest != baseline
    assert BalatroBotCanonicalizer().canonicalize(mutated).canonical_digest != baseline


def test_permanent_card_bonus_is_canonical_semantic_state() -> None:
    raw = state("SELECTING_HAND")
    changed = deepcopy(raw)
    changed["hand"]["cards"][0]["value"]["perma_bonus"] = 5

    baseline = BalatroBotCanonicalizer().canonicalize(raw).canonical_digest
    canonical = BalatroBotCanonicalizer().canonicalize(changed)

    assert canonical.canonical["hand"]["cards"][0]["value"]["perma_bonus"] == 5
    assert canonical.canonical_digest != baseline


def test_numbered_booster_artwork_is_not_policy_or_semantic_state() -> None:
    first = state("SHOP")
    second = deepcopy(first)
    second["packs"]["cards"][0]["key"] = "p_buffoon_normal_2"
    second["packs"]["cards"][0]["id"] += 100

    first_canonical = BalatroBotCanonicalizer().canonicalize(first).canonical
    second_canonical = BalatroBotCanonicalizer().canonicalize(second).canonical

    assert first_canonical == second_canonical
    assert to_public_observation(first) == to_public_observation(second)
    assert to_public_observation(first).packs[0].key == "p_buffoon_normal"

    custom = deepcopy(first)
    custom["packs"]["cards"][0]["key"] = "p_custom_rule_2"
    assert to_public_observation(custom).packs[0].key == "p_custom_rule_2"
    unknown_vanilla_like = deepcopy(first)
    unknown_vanilla_like["packs"]["cards"][0]["key"] = "p_buffoon_jumbo_2"
    assert to_public_observation(unknown_vanilla_like).packs[0].key == "p_buffoon_jumbo_2"


def test_entity_identity_survives_area_movement() -> None:
    before_left = state("BLIND_SELECT")
    before_right = deepcopy(before_left)
    for card in before_right["cards"]["cards"]:
        card["id"] += 100

    left = BalatroBotCanonicalizer()
    right = BalatroBotCanonicalizer()
    left.canonicalize(before_left)
    right.canonicalize(before_right)

    after_left = state("SELECTING_HAND")
    after_right = deepcopy(after_left)
    # Align the same logical entities across two runtimes with different raw IDs.
    for card in after_right["cards"]["cards"]:
        card["id"] += 100
    for card in after_right["hand"]["cards"]:
        card["id"] += 100

    assert left.canonicalize(after_left).canonical_digest == right.canonicalize(after_right).canonical_digest


def test_unknown_authority_schema_fails_closed() -> None:
    raw = state()
    raw["new_private_field"] = 1

    with pytest.raises(CanonicalizationError, match="unknown top-level"):
        BalatroBotCanonicalizer().canonicalize(raw)


@pytest.mark.parametrize("bad_count", [True, 0, 1.5])
def test_deck_composition_counts_fail_closed(bad_count: object) -> None:
    raw = state()
    raw["deck_composition"][0]["count"] = bad_count

    with pytest.raises(CanonicalizationError, match="count must be a positive integer"):
        BalatroBotCanonicalizer().canonicalize(raw)


def test_deck_composition_duplicate_and_total_fail_closed() -> None:
    duplicate = state()
    duplicate["deck_composition"].append(deepcopy(duplicate["deck_composition"][0]))
    with pytest.raises(CanonicalizationError, match="duplicate entry"):
        BalatroBotCanonicalizer().canonicalize(duplicate)

    wrong_total = state()
    wrong_total["deck_composition"][0]["count"] -= 1
    with pytest.raises(CanonicalizationError, match="total must equal"):
        BalatroBotCanonicalizer().canonicalize(wrong_total)


def test_anonymous_hidden_joker_slots_are_canonical_without_entity_ids() -> None:
    left = state("SELECTING_HAND")
    left["jokers"] = {
        "cards": [hidden_joker_slot(), hidden_joker_slot()],
        "count": 2,
        "highlighted_limit": 1,
        "limit": 5,
    }
    right = deepcopy(left)
    right["jokers"]["cards"].reverse()

    left_state = BalatroBotCanonicalizer().canonicalize(left)
    right_state = BalatroBotCanonicalizer().canonicalize(right)

    assert left_state.canonical_digest == right_state.canonical_digest
    assert left_state.canonical["jokers"]["cards"] == [
        {"set": "JOKER", "state": {"hidden": True}},
        {"set": "JOKER", "state": {"hidden": True}},
    ]

    leaked = deepcopy(left)
    full = item_card("j_blueprint", card_id=99, kind="JOKER")
    full["state"] = {"hidden": True}
    leaked["jokers"]["cards"][0] = full
    with pytest.raises(CanonicalizationError, match="exposed private fields"):
        BalatroBotCanonicalizer().canonicalize(leaked)


@pytest.mark.parametrize("value", [None, 0, 1, "false"])
def test_blind_disabled_state_must_be_present_and_boolean(value: object) -> None:
    raw = state()
    if value is None:
        raw["blinds"]["small"].pop("disabled")
    else:
        raw["blinds"]["small"]["disabled"] = value

    with pytest.raises(CanonicalizationError, match="disabled must be boolean"):
        BalatroBotCanonicalizer().canonicalize(raw)


def test_empty_lua_table_normalization_is_path_specific() -> None:
    left = state("SHOP")
    right = deepcopy(left)
    right["shop"]["cards"][0]["state"] = []

    assert (
        BalatroBotCanonicalizer().canonicalize(left).canonical_digest
        == BalatroBotCanonicalizer().canonicalize(right).canonical_digest
    )


def test_lua_json_float_precision_is_canonicalized() -> None:
    authority = state("SHOP")
    candidate = deepcopy(authority)
    authority["shop"]["cards"][0]["value"]["ability"]["x_mult"] = 1.87
    candidate["shop"]["cards"][0]["value"]["ability"]["x_mult"] = 1.8699999999999999

    assert (
        BalatroBotCanonicalizer().canonicalize(authority).canonical_digest
        == BalatroBotCanonicalizer().canonicalize(candidate).canonical_digest
    )


def test_closed_pack_choice_counter_is_not_canonical_semantic_state() -> None:
    cleared = state("SHOP")
    stale = deepcopy(cleared)
    stale["pack_choices_remaining"] = 1

    cleared_state = BalatroBotCanonicalizer().canonicalize(cleared)
    stale_state = BalatroBotCanonicalizer().canonicalize(stale)

    assert stale_state.raw_digest != cleared_state.raw_digest
    assert stale_state.canonical_digest == cleared_state.canonical_digest
    assert stale_state.canonical["pack_choices_remaining"] == 0

    stale["pack_choices_remaining"] = "1"
    with pytest.raises(CanonicalizationError, match="pack_choices_remaining must be an integer"):
        BalatroBotCanonicalizer().canonicalize(stale)
