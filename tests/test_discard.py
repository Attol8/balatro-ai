from dataclasses import replace
from fractions import Fraction
from itertools import combinations
from math import comb

import pytest

from balatro_ai.discard import flush_draws
from balatro_ai.game.actions import action_from_data, is_legal
from balatro_ai.game.adapter import to_public_observation
from balatro_ai.game.state import (
    DeckCardCount,
    HiddenHandCard,
    Phase,
    PublicItem,
    VisiblePlayingCard,
)
from tests.game.state_factory import state


def observation(suits="SSSSHHCD", matching=9, other=35):
    base = to_public_observation(state("SELECTING_HAND"))
    remaining = tuple(
        DeckCardCount(VisiblePlayingCard("A", suit), count)
        for suit, count in (("S", matching), ("H", other))
        if count
    )
    return replace(
        base,
        deck="BLACK",
        stake="GOLD",
        round=replace(base.round, discards_left=2),
        hand=tuple(VisiblePlayingCard("2", suit) for suit in suits),
        hand_limit=len(suits),
        jokers=(),
        remaining_deck=remaining,
        draw_count=matching + other,
    )


def test_four_held_nine_of_44_draw_four():
    obs = observation()
    row = flush_draws(obs)[0]
    probability = Fraction(comb(44, 4) - comb(35, 4), comb(44, 4))
    assert row["probability"] == float(probability)
    assert Fraction(row["probability_numerator"], row["probability_denominator"]) == probability
    assert row["action"] == {"type": "discard_cards", "cards": [4, 5, 6, 7]}
    assert (row["suit"], row["held_count"], row["needed"]) == ("S", 4, 1)
    assert (row["draw_count"], row["matching_unseen"], row["total_unseen"]) == (4, 9, 44)
    assert is_legal(obs, action_from_data(row["action"]))
    assert "not a winning chance" in row["note"]


def test_three_held_matches_exhaustive_small_deck():
    obs = observation("SSSHCD", matching=3, other=3)
    outcomes = list(combinations("SSSHHH", 3))
    expected = Fraction(sum(draw.count("S") >= 2 for draw in outcomes), len(outcomes))
    row = flush_draws(obs)[0]
    assert row["needed"] == 2
    assert row["probability"] == float(expected)


@pytest.mark.parametrize("matching,other,expected", [(0, 10, 0.0), (2, 0, 1.0), (0, 0, 0.0)])
def test_impossible_certain_and_exhausted_decks(matching, other, expected):
    row = flush_draws(observation(matching=matching, other=other))[0]
    assert row["draw_count"] == min(4, matching + other)
    assert row["probability"] == expected


@pytest.mark.parametrize(
    "changes",
    [
        {"phase": Phase.SHOP},
        {"hand_limit": 9},
        {"selection_limit": 3},
        {"draw_count": 43},
        {"jokers": (PublicItem("j_four_fingers", "Four Fingers", "JOKER"),)},
        {"jokers": (PublicItem("j_smeared", "Smeared Joker", "JOKER"),)},
    ],
)
def test_unsupported_context_is_omitted(changes):
    assert flush_draws(replace(observation(), **changes)) == []


@pytest.mark.parametrize("resource", ["discards_left", "hands_left"])
def test_no_legal_discard(resource):
    obs = observation()
    assert flush_draws(replace(obs, round=replace(obs.round, **{resource: 0}))) == []


@pytest.mark.parametrize("disabled", [False, True])
def test_all_current_boss_rounds_are_omitted(disabled):
    obs = observation()
    boss = replace(obs.blinds[-1], status="CURRENT", disabled=disabled)
    assert flush_draws(replace(obs, blinds=(boss,))) == []


@pytest.mark.parametrize(
    "changes",
    [{"enhancement": "WILD"}, {"debuffed": True}, {"seal": "PURPLE"}, {"edition": "FOIL"}],
)
@pytest.mark.parametrize("zone", ["hand", "remaining_deck"])
def test_modified_cards_are_omitted(changes, zone):
    obs = observation()
    if zone == "hand":
        obs = replace(obs, hand=(replace(obs.hand[0], **changes), *obs.hand[1:]))
    else:
        entry = obs.remaining_deck[0]
        obs = replace(
            obs,
            remaining_deck=(
                replace(entry, card=replace(entry.card, **changes)),
                *obs.remaining_deck[1:],
            ),
        )
    assert flush_draws(obs) == []


def test_hidden_hand_is_omitted():
    obs = observation()
    assert flush_draws(replace(obs, hand=(HiddenHandCard(), *obs.hand[1:]))) == []


def test_debuffed_rule_jokers_do_not_change_literal_suit_odds():
    obs = observation()
    joker = PublicItem("j_smeared", "Smeared Joker", "JOKER", debuffed=True)
    assert flush_draws(replace(obs, jokers=(joker,))) == flush_draws(obs)


@pytest.mark.parametrize("suits", ["SSHHCCDD", "SSSSSHCD", "SSSSHHCCDD"])
def test_only_three_or_four_held_and_one_to_five_discards(suits):
    assert flush_draws(observation(suits)) == []


def test_two_candidate_suits_and_public_deck_order_invariance():
    obs = observation("SSSHHHCD")
    rows = flush_draws(obs)
    assert [row["suit"] for row in rows] == ["S", "H"]
    assert flush_draws(replace(obs, remaining_deck=tuple(reversed(obs.remaining_deck)))) == rows
