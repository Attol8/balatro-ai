"""Independent tiny-deck oracle and conservative rollout boundary checks."""

from dataclasses import replace
from itertools import combinations

import pytest

from balatro_ai.continuation import continuation_advice
from balatro_ai.game.actions import action_from_data, is_legal
from balatro_ai.game.adapter import to_public_observation
from balatro_ai.game.state import (
    DeckCardCount,
    HiddenHandCard,
    HiddenJokerSlot,
    Phase,
    PublicItem,
    PublicJokerRuntime,
    VisiblePlayingCard,
)
from tests.game.state_factory import state


def observation(target=12):
    base = to_public_observation(state("SELECTING_HAND"))
    return replace(
        base,
        deck="BLACK",
        stake="GOLD",
        hand=(VisiblePlayingCard("2", "C"),),
        hand_limit=1,
        round=replace(base.round, hands_left=2, discards_left=1),
        blinds=(replace(base.blinds[0], score=target),),
        remaining_deck=(
            DeckCardCount(VisiblePlayingCard("3", "H"), 1),
            DeckCardCount(VisiblePlayingCard("A", "S"), 1),
        ),
        draw_count=2,
        jokers=(),
    )


def candidates():
    return [
        {
            "action": {"type": "play_cards", "cards": [0]},
            "estimated_score": 7,
            "family": "High Card",
        }
    ]


def test_small_deck_independent_score_oracle_and_uncertainty():
    # A one-card hand scores 5 + rank chips. This oracle never calls the scorer.
    next_scores = [5 + draw[0] for draw in combinations((3, 11), 1)]
    assert next_scores == [8, 16]
    result = continuation_advice(observation(), candidates(), samples=128)
    rows = {row["horizon"]: row for row in result["candidates"]}
    play = rows["play_then_best_play"]
    discard = rows["discard_then_best_play"]
    assert play["immediate_score"] == 7
    assert discard["immediate_score"] == 0
    assert play["finish_probability"] == 1.0  # 7 + either possible next score >= 12.
    assert play["mean_best_next_score"] == discard["mean_best_next_score"]
    # Only the Ace finishes after a discard. Both candidates use common draws.
    assert discard["finish_probability"] == pytest.approx((discard["mean_best_next_score"] - 8) / 8)
    assert discard["wilson_95_interval"][0] < 0.5 < discard["wilson_95_interval"][1]
    assert abs(discard["finish_probability"] - 0.5) < 0.15


def test_horizon_uses_existing_chips_and_preserves_inputs():
    obs = observation(target=25)
    obs = replace(obs, round=replace(obs.round, chips=5))
    before = repr(obs)
    proposed = candidates()
    original = repr(proposed)
    result = continuation_advice(obs, proposed, samples=128)
    rows = {row["horizon"]: row for row in result["candidates"]}
    assert rows["discard_then_best_play"]["finish_probability"] == 0
    assert 0 < rows["play_then_best_play"]["finish_probability"] < 1
    assert repr(obs) == before
    assert repr(proposed) == original
    for row in result["candidates"]:
        assert is_legal(obs, action_from_data(row["action"]))


def test_public_multiset_order_does_not_change_samples():
    obs = observation()
    reordered = replace(obs, remaining_deck=tuple(reversed(obs.remaining_deck)))
    assert continuation_advice(obs, candidates()) == continuation_advice(reordered, candidates())
    assert continuation_advice(obs, candidates()) == continuation_advice(obs, candidates())


@pytest.mark.parametrize("samples", [0, -1, 129, True, 1.5])
def test_invalid_sample_budget_is_omitted(samples):
    assert continuation_advice(observation(), candidates(), samples=samples) == {}


@pytest.mark.parametrize("samples", [1, 128])
def test_budget_and_output_caps(samples):
    result = continuation_advice(observation(), candidates() * 20, samples=samples)
    assert result["samples"] == samples
    rows = result["candidates"]
    assert len(rows) <= result["candidate_cap"] == 8
    assert sum(row["horizon"] == "play_then_best_play" for row in rows) <= 4
    assert sum(row["horizon"] == "discard_then_best_play" for row in rows) <= 4
    assert len({repr(row["action"]) for row in rows}) == len(rows)
    assert all(row["samples"] == samples for row in rows)


@pytest.mark.parametrize(
    "changes",
    [
        {"phase": Phase.SHOP},
        {"deck": "PLASMA"},
        {"draw_count": 3},
        {"hand_limit": 2},
        {"hand": (HiddenHandCard(),)},
        {"jokers": (PublicItem("j_ice_cream", "Ice Cream", "JOKER"),)},
        {"jokers": (PublicItem("j_green_joker", "Green Joker", "JOKER"),)},
        {"jokers": (PublicItem("j_bloodstone", "Bloodstone", "JOKER"),)},
        {
            "jokers": (
                PublicItem("j_joker", "Joker", "JOKER", runtime=PublicJokerRuntime(current_mult=4)),
            )
        },
    ],
)
def test_unsupported_context_is_omitted(changes):
    assert continuation_advice(replace(observation(), **changes), candidates()) == {}


@pytest.mark.parametrize(
    "changes",
    [
        {"enhancement": "STEEL"},
        {"edition": "FOIL"},
        {"seal": "RED"},
        {"debuffed": True},
        {"permanent_bonus": 1},
    ],
)
@pytest.mark.parametrize("zone", ["hand", "remaining_deck"])
def test_modified_cards_are_omitted(changes, zone):
    obs = observation()
    if zone == "hand":
        obs = replace(obs, hand=(replace(obs.hand[0], **changes),))
    else:
        entry = obs.remaining_deck[0]
        obs = replace(
            obs,
            remaining_deck=(
                replace(entry, card=replace(entry.card, **changes)),
                *obs.remaining_deck[1:],
            ),
        )
    assert continuation_advice(obs, candidates()) == {}


@pytest.mark.parametrize("boss", ["The Head", "Amber Acorn", "Cerulean Bell"])
def test_boss_hidden_jokers_and_required_cards_are_omitted(boss):
    obs = observation()
    obs = replace(
        obs,
        blinds=(replace(obs.blinds[0], kind="BOSS", name=boss),),
        jokers=(HiddenJokerSlot(),) if boss == "Amber Acorn" else (),
        required_hand_slots=(0,) if boss == "Cerulean Bell" else (),
    )
    assert continuation_advice(obs, candidates()) == {}


def test_already_winning_play_needs_no_continuation():
    assert continuation_advice(observation(target=7), candidates()) == {}


def test_no_remaining_resources_yields_no_illegal_proposal():
    obs = observation()
    obs = replace(obs, round=replace(obs.round, hands_left=1, discards_left=0))
    assert not continuation_advice(obs, candidates()).get("candidates")


@pytest.mark.parametrize(
    "key",
    [
        "j_joker",
        "j_odd_todd",
        "j_hack",
        "j_drunkard",
        "j_gros_michel",
        "j_walkie_talkie",
        "j_shoot_the_moon",
        "j_jolly",
        "j_droll",
    ],
)
@pytest.mark.parametrize("edition", [None, "FOIL", "HOLO", "POLYCHROME", "NEGATIVE"])
def test_fixed_jokers_and_round_end_stickers_are_admitted(key, edition):
    obs = replace(
        observation(target=100000),
        jokers=(
            PublicItem(
                key,
                key,
                "JOKER",
                edition=edition,
                rental=True,
                perishable_rounds=1,
            ),
        ),
    )
    result = continuation_advice(obs, candidates(), samples=1)
    assert result["candidates"]
    assert all(is_legal(obs, action_from_data(row["action"])) for row in result["candidates"])


def test_proposals_are_rescored_and_invalid_actions_cannot_escape():
    supplied = candidates()
    supplied[0]["estimated_score"] = 100000
    supplied += [
        {"action": {"type": "play_cards", "cards": [99]}},
        {"action": {"type": "discard_cards", "cards": [0]}},
    ]
    result = continuation_advice(observation(), supplied, samples=1)
    play = next(row for row in result["candidates"] if row["horizon"] == "play_then_best_play")
    assert play["immediate_score"] == 7


def test_terminal_guard_does_not_trust_underreported_supplied_score():
    supplied = candidates()
    supplied[0]["estimated_score"] = 0
    assert continuation_advice(observation(target=7), supplied) == {}


def test_empty_unseen_deck_and_debuffed_joker_are_omitted():
    obs = observation()
    assert continuation_advice(replace(obs, remaining_deck=(), draw_count=0), candidates()) == {}
    joker = PublicItem("j_joker", "Joker", "JOKER", debuffed=True, perishable_rounds=0)
    assert continuation_advice(replace(obs, jokers=(joker,)), candidates()) == {}
