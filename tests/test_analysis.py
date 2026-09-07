from __future__ import annotations

import gzip
import json
from dataclasses import replace
from pathlib import Path

from balatro_ai.analysis import analyze
from balatro_ai.game.adapter import to_public_observation
from balatro_ai.game.codec import public_observation_from_data
from balatro_ai.game.state import (
    HandStat,
    PublicBlind,
    PublicItem,
    PublicJokerRuntime,
    VisiblePlayingCard,
)
from tests.game.state_factory import hidden_joker_slot, item_card, state


def _selecting_hand():
    return to_public_observation(state("SELECTING_HAND"))


def test_keeps_lower_score_bus_safe_play_and_explains_card_roles() -> None:
    observation = replace(
        _selecting_hand(),
        hand=(
            VisiblePlayingCard("K", "H"),
            VisiblePlayingCard("2", "D"),
            VisiblePlayingCard("9", "S", enhancement="STEEL", seal="BLUE"),
        ),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=(
            PublicItem(
                "j_ride_the_bus",
                "Ride the Bus",
                "JOKER",
                runtime=PublicJokerRuntime(current_mult=5),
            ),
        ),
    )

    result = analyze(observation)
    candidates = result["play_candidates"]
    assert len(candidates) <= 16
    safe = next(row for row in candidates if row["action"] == {"type": "play_cards", "cards": [2]})
    assert safe["facts"]["ride_the_bus_reset_slots"] == []
    held = next(row for row in candidates if row["facts"]["held_steel_slots"] == [2])
    assert held["facts"]["held_blue_seal_slots"] == [2]
    assert any("Ride the Bus" in note for note in result["mechanism_reminders"])
    assert "model choice" in result["discard_note"]


def test_pareidolia_face_fact_does_not_invent_bus_reset() -> None:
    observation = replace(
        _selecting_hand(),
        hand=(VisiblePlayingCard("9", "S"),),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=(
            PublicItem("j_pareidolia", "Pareidolia", "JOKER"),
            PublicItem("j_ride_the_bus", "Ride the Bus", "JOKER"),
        ),
    )

    facts = analyze(observation)["play_candidates"][0]["facts"]
    assert facts["scoring_faces"] == [0]
    assert facts["ride_the_bus_reset_slots"] == []
    assert facts["pareidolia_active"] is True
    assert facts["ride_the_bus_interaction_uncertain"] is True
    assert (
        "treat reset safety as uncertain"
        in analyze(observation)["play_candidates"][0]["approximation"]
    )


def test_splash_facts_include_kickers_as_scoring_cards() -> None:
    observation = replace(
        _selecting_hand(),
        hand=(VisiblePlayingCard("K", "H"), VisiblePlayingCard("2", "D")),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=(PublicItem("j_splash", "Splash", "JOKER"),),
    )

    candidate = next(
        row for row in analyze(observation)["play_candidates"] if row["action"]["cards"] == [0, 1]
    )
    assert candidate["facts"]["scoring_slots"] == [0, 1]
    assert candidate["facts"]["harmless_kickers"] == []
    assert candidate["facts"]["splash_active"] is True


def test_every_score_is_labeled_and_lucky_omission_is_explicit() -> None:
    observation = replace(
        _selecting_hand(),
        hand=(VisiblePlayingCard("9", "S", enhancement="LUCKY"),),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
    )
    approximation = analyze(observation)["play_candidates"][0]["approximation"]
    assert "integer rounding" in approximation
    assert "Lucky Card" in approximation


def test_zero_score_boss_restriction_warns_that_legal_play_can_waste_hand() -> None:
    observation = replace(
        _selecting_hand(),
        blinds=(PublicBlind("BOSS", "CURRENT", "The Psychic", "Must play 5 cards", 300, False),),
    )
    candidates = analyze(observation)["play_candidates"]
    assert candidates
    assert all(row["estimated_score"] == 0 for row in candidates)
    assert all(
        "intentionally waste a hand" in row["facts"]["boss_scoring_restriction"]
        for row in candidates
    )


def test_hidden_jokers_suppress_scores_instead_of_faking_them() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"].update(type="BOSS", name="Amber Acorn")
    raw["jokers"] = {
        "cards": [hidden_joker_slot()],
        "count": 1,
        "highlighted_limit": 1,
        "limit": 5,
    }

    result = analyze(to_public_observation(raw))
    assert result["play_candidates"] == []
    assert result["reorder_suggestions"] == []


def test_shop_lists_only_affordable_legal_actions_and_reports_bound() -> None:
    raw = state("SHOP", money=4)
    raw["shop"]["cards"] = [
        item_card("j_joker", card_id=40 + index, kind="JOKER", buy=2) for index in range(30)
    ]
    raw["shop"]["count"] = 30
    raw["vouchers"]["cards"][0]["cost"]["buy"] = 10

    result = analyze(to_public_observation(raw))
    assert len(result["strategic_actions"]) == 24
    assert result["strategic_actions_omitted"] > 0
    assert result["shortlist_is_not_allowlist"] is True
    assert all(action["type"] != "buy_voucher" for action in result["strategic_actions"])


def test_adjacent_hand_reorder_remaps_the_same_physical_selection() -> None:
    observation = replace(
        _selecting_hand(),
        hand=(
            VisiblePlayingCard("Q", "C"),
            VisiblePlayingCard("9", "C"),
            VisiblePlayingCard("8", "C"),
            VisiblePlayingCard("6", "C"),
            VisiblePlayingCard("5", "C"),
        ),
        hand_stats=(HandStat("Flush", 1, 35, 4, 0, 0),),
        jokers=(
            PublicItem("j_photograph", "Photograph", "JOKER"),
            PublicItem("j_wrathful_joker", "Wrathful Joker", "JOKER"),
            PublicItem("j_onyx_agate", "Onyx Agate", "JOKER"),
        ),
        blinds=(PublicBlind("SMALL", "CURRENT", "Small Blind", "", 100_000, False),),
    )

    suggestions = analyze(observation)["reorder_suggestions"]
    hand_swap = next(row for row in suggestions if row["action"]["type"] == "reorder_hand")
    assert hand_swap["selected_before"] == [0, 1, 2, 3, 4]
    assert hand_swap["selected_after"] == [0, 1, 2, 3, 4]
    assert hand_swap["reordered_score"] > hand_swap["baseline_score"]


def _recorded_observation(segment: str, event_index: int):
    path = (
        (Path(__file__).resolve().parents[1] / "evidence/astra-low-2K9H9HN/segments")
        / segment
        / "trajectory.jsonl.gz"
    )
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        events = [json.loads(line) for line in stream]
    return public_observation_from_data(events[event_index]["observation"])


def test_recorded_full_slot_mime_offer_surfaces_public_steel_synergy() -> None:
    # Ante 7's actual shop had five occupied Joker slots, five Steel cards,
    # and Mime in shop slot 2. Capacity must not hide the strategic option.
    observation = _recorded_observation("05", 95)

    opportunities = analyze(observation)["engine_opportunities"]
    mime = next(row for row in opportunities if row["key"] == "j_mime")
    assert (mime["zone"], mime["slot"]) == ("shop", 2)
    assert mime["support"] == {"steel_cards_in_public_deck": 5}
    assert "fresh state" in mime["capacity"]
    assert "expected" not in json.dumps(mime).lower()


def test_unknown_public_deck_does_not_invent_offer_support() -> None:
    observation = _recorded_observation("05", 95)
    unknown = replace(observation, full_deck=(), deck_size=0)

    result = analyze(unknown)
    assert "engine_opportunities" not in result


def test_negative_mime_does_not_require_a_sale_with_full_slots() -> None:
    observation = _recorded_observation("05", 95)
    offers = list(observation.shop)
    offers[2] = replace(offers[2], edition="NEGATIVE")
    observation = replace(observation, shop=tuple(offers))
    mime = next(
        row for row in analyze(observation)["engine_opportunities"] if row["key"] == "j_mime"
    )
    assert "capacity" not in mime


def test_modelled_board_reports_no_unmodelled_jokers() -> None:
    observation = replace(
        _selecting_hand(),
        hand=(VisiblePlayingCard("A", "S"),),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=(
            PublicItem("j_steel_joker", "Steel Joker", "JOKER"),
            PublicItem("j_golden", "Golden Joker", "JOKER"),
        ),
    )

    result = analyze(observation)
    assert result["unmodelled_jokers"] == []
    assert "no scoring rule" not in result["play_candidates"][0]["approximation"]


def test_an_unclassified_joker_is_named_in_the_output_and_the_approximation() -> None:
    observation = replace(
        _selecting_hand(),
        hand=(VisiblePlayingCard("A", "S"),),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=(
            PublicItem(
                "j_not_a_vanilla_key",
                "Modded Joker",
                "JOKER",
                effect_text="Does something unmodelled",
            ),
        ),
    )

    result = analyze(observation)
    assert result["unmodelled_jokers"] == [
        {
            "key": "j_not_a_vanilla_key",
            "label": "Modded Joker",
            "effect_text": "Does something unmodelled",
        }
    ]
    assert (
        "Scores omit Modded Joker: no scoring rule."
        in (result["play_candidates"][0]["approximation"])
    )


def test_interest_preview_uses_the_base_cap_without_a_voucher() -> None:
    observation = replace(_selecting_hand(), money=17)

    assert analyze(observation)["economy"] == {
        "money": 17,
        "interest_at_cashout": 3,
        "interest_cap": 5,
        "next_interest_threshold": 20,
        "reroll_cost": 5,
    }


def test_interest_preview_reports_the_cap_is_reached() -> None:
    observation = replace(_selecting_hand(), money=40)

    economy = analyze(observation)["economy"]
    assert economy["interest_at_cashout"] == 5
    assert economy["next_interest_threshold"] is None


def test_seed_money_and_money_tree_raise_the_public_interest_cap() -> None:
    base = replace(_selecting_hand(), money=60)

    seeded = analyze(replace(base, used_vouchers=("v_seed_money",)))["economy"]
    assert (seeded["interest_cap"], seeded["interest_at_cashout"]) == (10, 10)
    assert seeded["next_interest_threshold"] is None

    tree = analyze(replace(base, used_vouchers=("v_seed_money", "v_money_tree")))["economy"]
    assert (tree["interest_cap"], tree["interest_at_cashout"]) == (20, 12)
    assert tree["next_interest_threshold"] == 65


def test_to_the_moon_doubles_the_previewed_interest() -> None:
    observation = replace(
        _selecting_hand(),
        money=17,
        jokers=(PublicItem("j_to_the_moon", "To the Moon", "JOKER"),),
    )

    economy = analyze(observation)["economy"]
    assert (economy["interest_at_cashout"], economy["interest_cap"]) == (6, 10)


def test_negative_money_previews_no_interest() -> None:
    observation = replace(_selecting_hand(), money=-3)

    economy = analyze(observation)["economy"]
    assert (economy["money"], economy["interest_at_cashout"]) == (-3, 0)
    assert economy["next_interest_threshold"] == 5


def test_analysis_names_the_phase_and_legal_action_types() -> None:
    path = Path("evidence/astra-low-2K9H9HN/segments/03/trajectory.jsonl.gz")
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if record.get("event") == "transition" and record["before"].get("phase") == "SHOP":
                observation = public_observation_from_data(record["before"])
                break
    analysis = analyze(observation)
    assert analysis["phase"] == "SHOP"
    assert "leave_shop" in analysis["legal_action_types"]
    assert "play_cards" not in analysis["legal_action_types"]
    assert "choose_pack_card" not in analysis["legal_action_types"]


def test_analysis_reports_inventory_slots() -> None:
    path = Path("evidence/astra-low-2K9H9HN/segments/03/trajectory.jsonl.gz")
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            if record.get("event") == "transition" and record["before"].get("phase") == "SHOP":
                observation = public_observation_from_data(record["before"])
                break
    slots = analyze(observation)["slots"]
    assert slots["jokers"] == f"{len(observation.jokers)}/{observation.joker_limit}"
    assert slots["jokers_full"] == (len(observation.jokers) >= observation.joker_limit)
    assert slots["consumables"].endswith(f"/{observation.consumable_limit}")
