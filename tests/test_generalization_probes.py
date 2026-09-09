"""Independent arithmetic for diverse synthetic Black/Gold decision contracts."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import replace
from fractions import Fraction
from pathlib import Path

import pytest

from balatro_ai.game.actions import (
    HandSlot,
    PlayCards,
    action_to_data,
    canonical_action_from_data,
    is_legal,
    iter_legal_actions,
)
from balatro_ai.game.codec import public_observation_from_data
from balatro_ai.game.scoring import score_play

CASES = json.loads((Path(__file__).parent / "fixtures" / "generalization_probes.json").read_text())


def observation(case_id):
    return public_observation_from_data(
        next(row["observation"] for row in CASES if row["id"] == case_id)
    )


def winning_plays(obs):
    target = next(blind.score for blind in obs.blinds if blind.status == "CURRENT")
    return [
        action_to_data(action)
        for action in iter_legal_actions(obs)
        if isinstance(action, PlayCards)
        and score_play(obs, action.cards)[0] + obs.round.chips >= target
    ]


@pytest.mark.parametrize("row", CASES, ids=lambda row: row["id"])
def test_generalization_cases_are_public_coherent_and_legal(row):
    obs = public_observation_from_data(row["observation"])
    assert row["provenance"] == "constructed"
    assert row["evaluation_split"] in {"development", "held_out"}
    assert "not derived from a seed" in row["rationale"]
    assert obs.deck == "BLACK" and obs.stake == "GOLD"
    assert obs.round.hands_left == 1
    assert obs.round.discards_left == obs.draw_count == 0
    assert Counter({entry.card: entry.count for entry in obs.full_deck}) == Counter(
        replace(card, debuffed=False) for card in obs.hand
    )
    for action in row["accepted_actions"]:
        assert is_legal(obs, canonical_action_from_data(action))


def test_development_and_held_out_splits_are_fixed_before_inference():
    assert {row["id"] for row in CASES if row["evaluation_split"] == "development"} == {
        "gold_active_perishable_rental_pair",
        "gold_supported_planet_constellation",
    }
    assert {row["id"] for row in CASES if row["evaluation_split"] == "held_out"} == {
        "gold_expired_perishable_pair_planet",
        "gold_plant_retrigger_pair_escape",
    }


@pytest.mark.parametrize("index", [0, 3])
def test_terminal_play_oracles_accept_every_winning_selection(index):
    row = CASES[index]
    assert {
        json.dumps(action, sort_keys=True)
        for action in winning_plays(public_observation_from_data(row["observation"]))
    } == {json.dumps(action, sort_keys=True) for action in row["accepted_actions"]}


def test_active_rental_perishable_is_required_for_this_round():
    obs = observation("gold_active_perishable_rental_pair")
    assert obs.jokers[0].perishable_rounds == 1 and obs.jokers[0].rental
    expected = (10 + 8 + 8) * (2 + 8)
    assert score_play(obs, (HandSlot(0), HandSlot(1)))[0] == expected == 260
    without = replace(obs, jokers=())
    assert score_play(without, (HandSlot(0), HandSlot(1)))[0] == (10 + 8 + 8) * 2 == 52
    assert not winning_plays(without)


def test_expired_joker_requires_supported_planet_before_final_hand():
    obs = observation("gold_expired_perishable_pair_planet")
    assert obs.jokers[0].perishable_rounds == 0 and obs.jokers[0].debuffed
    selected = (HandSlot(0), HandSlot(1))
    assert score_play(obs, selected)[0] == (10 + 18 + 2 * 31) * 2 == 180
    assert not winning_plays(obs)
    # Independent vanilla Mercury update: +15 base chips, +1 base Mult.
    upgraded = replace(
        obs,
        hand_stats=tuple(
            replace(stat, chips=25, mult=3, level=2) if stat.name == "Pair" else stat
            for stat in obs.hand_stats
        ),
        consumables=(),
    )
    assert score_play(upgraded, selected)[0] == (25 + 18 + 2 * 31) * 3 == 315
    assert winning_plays(upgraded)
    # Selling the expired card first is also valid; forbid a false unique-first-action oracle.
    sold_expired = replace(upgraded, jokers=upgraded.jokers[1:], money=1)
    assert score_play(sold_expired, selected)[0] == 315
    assert not winning_plays(replace(upgraded, jokers=(upgraded.jokers[0],)))


def test_planet_and_constellation_growth_are_both_necessary():
    obs = observation("gold_supported_planet_constellation")
    selected = (HandSlot(0),)
    assert score_play(obs, selected)[0] == (5 + 11) * (1 + 4) * 2 == 160
    assert not winning_plays(obs)
    leveled = replace(
        obs,
        hand_stats=tuple(
            replace(stat, chips=15, mult=2, level=2) if stat.name == "High Card" else stat
            for stat in obs.hand_stats
        ),
    )
    grown_jokers = (
        obs.jokers[0],
        replace(obs.jokers[1], runtime=replace(obs.jokers[1].runtime, current_x_mult=2.1)),
    )
    assert score_play(leveled, selected)[0] == 26 * 6 * 2 == 312 < 320
    assert (
        score_play(replace(obs, jokers=grown_jokers), selected)[0]
        == 16 * 5 * Fraction(21, 10)
        == 168
    )
    after = replace(leveled, jokers=grown_jokers, consumables=())
    assert score_play(after, selected)[0] == (26 * 6 * Fraction(21, 10)) // 1 == 327 > 320
    assert winning_plays(after)
    assert not winning_plays(replace(after, jokers=(after.jokers[0],)))
    assert not winning_plays(replace(after, jokers=(after.jokers[1],)))


def test_plant_requires_switching_from_debuffed_face_to_pair_retrigger():
    obs = observation("gold_plant_retrigger_pair_escape")
    assert obs.hand[0].debuffed
    assert score_play(obs, (HandSlot(1), HandSlot(2)))[0] == (10 + 4 * 8) * 2 == 84
    assert score_play(obs, (HandSlot(0),))[0] < 80
    ordinary = replace(
        obs,
        hand=tuple(replace(card, debuffed=False) for card in obs.hand),
        blinds=tuple(
            replace(blind, name="Small Blind", kind="SMALL", effect="")
            if blind.status == "CURRENT"
            else blind
            for blind in obs.blinds
        ),
    )
    assert score_play(ordinary, (HandSlot(0),))[0] == (5 + 3 * 10) * 2**3 == 280
