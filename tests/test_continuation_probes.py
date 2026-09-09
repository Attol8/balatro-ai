"""Exact independent public-deck oracles for deliberately small constructed cases.

No continuation implementation, hidden draw order, model or live game is used.
Every unordered draw is equally likely here because all public entries count one.
"""

import json
from collections import Counter
from dataclasses import replace
from fractions import Fraction
from itertools import combinations
from pathlib import Path

import pytest

from balatro_ai.game.actions import (
    DiscardCards,
    HandSlot,
    PlayCards,
    action_to_data,
    canonical_action_from_data,
    is_legal,
    iter_legal_actions,
)
from balatro_ai.game.codec import public_observation_from_data
from balatro_ai.game.scoring import score_play

CASES = json.loads((Path(__file__).parent / "fixtures" / "continuation_probes.json").read_text())


def subsets(size):
    for count in range(1, min(5, size) + 1):
        yield from combinations(range(size), count)


def arithmetic_score(cards):
    """These <=3-card hands can only make High Card or a pair of Twos."""
    ranks = Counter(card.rank for card in cards)
    assert len(cards) <= 3
    if ranks.get("2") == 2:
        return (10 + 2 + 2) * 2
    assert max(ranks.values()) == 1
    return 5 + max(11 if card.rank == "A" else int(card.rank) for card in cards)


def win_probability(obs, action):
    selected = {slot.value for slot in action.cards}
    held = tuple(card for slot, card in enumerate(obs.hand) if slot not in selected)
    immediate = (
        arithmetic_score(tuple(obs.hand[i] for i in selected))
        if isinstance(action, PlayCards)
        else 0
    )
    public_pool = tuple(entry.card for entry in obs.remaining_deck for _ in range(entry.count))
    draw_size = min(obs.hand_limit - len(held), len(public_pool))
    outcomes = tuple(combinations(public_pool, draw_size))
    target = next(blind.score for blind in obs.blinds if blind.status == "CURRENT")
    wins = 0
    for draw in outcomes:
        next_hand = held + draw
        # Independent arithmetic is also checked against the existing scorer.
        next_obs = replace(obs, hand=next_hand)
        scores = []
        for indices in subsets(len(next_hand)):
            expected = arithmetic_score(tuple(next_hand[i] for i in indices))
            assert score_play(next_obs, tuple(HandSlot(i) for i in indices))[0] == expected
            scores.append(expected)
        wins += obs.round.chips + immediate + max(scores) >= target
    return Fraction(wins, len(outcomes))


@pytest.mark.parametrize("row", CASES, ids=lambda row: row["id"])
def test_constructed_cases_have_coherent_public_counts_and_legal_oracles(row):
    obs = public_observation_from_data(row["observation"])
    assert row["provenance"] == "constructed"
    assert "not a natural Black Deck opening" in row["rationale"]
    assert obs.hand_limit == len(obs.hand) == 3
    assert obs.draw_count == 2
    assert obs.deck_size == 5
    assert not obs.jokers
    assert Counter({entry.card: entry.count for entry in obs.full_deck}) == (
        Counter(obs.hand) + Counter({entry.card: entry.count for entry in obs.remaining_deck})
    )
    for data in row["accepted_actions"]:
        assert is_legal(obs, canonical_action_from_data(data))


@pytest.mark.parametrize("row", CASES, ids=lambda row: row["id"])
def test_exact_public_draw_enumeration_has_only_one_certain_winning_action(row):
    obs = public_observation_from_data(row["observation"])
    kind = PlayCards if obs.round.hands_left == 2 else DiscardCards
    probabilities = {
        action: win_probability(obs, action)
        for action in iter_legal_actions(obs)
        if isinstance(action, kind)
    }
    assert max(probabilities.values()) == 1
    assert [action_to_data(a) for a, chance in probabilities.items() if chance == 1] == row[
        "accepted_actions"
    ]
    assert probabilities[kind((HandSlot(0),))] == Fraction(1, 2)
    assert probabilities[kind((HandSlot(0), HandSlot(1)))] == 0
    assert probabilities[kind((HandSlot(0), HandSlot(1), HandSlot(2)))] == 0
    target = next(blind.score for blind in obs.blinds if blind.status == "CURRENT")
    assert (
        max(score_play(obs, tuple(HandSlot(i) for i in indices))[0] for indices in subsets(3))
        == 16
        < target
    )


def test_equal_immediate_scores_hide_different_continuation_probabilities():
    obs = public_observation_from_data(CASES[0]["observation"])
    for indices, probability in [
        ((0,), Fraction(1, 2)),
        ((0, 2), Fraction(1)),
        ((0, 1), Fraction(0)),
    ]:
        action = PlayCards(tuple(HandSlot(i) for i in indices))
        assert score_play(obs, action.cards)[0] == 16
        assert win_probability(obs, action) == probability
