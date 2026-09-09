from dataclasses import replace
from itertools import permutations

import pytest

from balatro_ai.game.actions import PlayCards, action_from_data, is_legal, iter_legal_actions
from balatro_ai.game.adapter import to_public_observation
from balatro_ai.game.scoring import _prepare_score_context, _score_play_prepared
from balatro_ai.game.state import HandStat, PublicItem, VisiblePlayingCard
from balatro_ai.reordering import joker_reorder_advice
from tests.game.state_factory import state


def _observation(keys=("j_ramen", "j_golden", "j_joker")):
    return replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(VisiblePlayingCard("2", "C"),),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=tuple(PublicItem(key, key, "JOKER") for key in keys),
    )


def _plays(observation):
    context = _prepare_score_context(observation)
    rows = [
        (action, *_score_play_prepared(observation, action.cards, None, context))
        for action in iter_legal_actions(observation)
        if isinstance(action, PlayCards)
    ]
    return sorted(rows, key=lambda row: row[1], reverse=True)[:3]


def test_neutral_bridge_distinguishes_immediate_and_target_arithmetic():
    observation = _observation()
    rows = joker_reorder_advice(observation, _plays(observation), "estimate")
    row = rows[0]
    # (5 + 2) chips * (1 * 2 + 4) vs (5 + 2) * ((1 + 4) * 2).
    assert row["baseline_score"] == row["reordered_score"] == 42
    assert row["target_score"] == 70
    assert row["action"] == {"type": "reorder_jokers", "order": [1, 0, 2]}
    assert row["adjacent_steps_to_target"] == 2
    assert is_legal(observation, action_from_data(row["action"]))
    assert "then observe and reassess" in row["note"]


def test_conservative_direction_can_miss_a_real_improvement():
    observation = _observation(("j_cavendish", "j_golden", "j_joker"))
    assert _plays(observation)[0][1] == 49
    target = replace(observation, jokers=observation.jokers[1:] + observation.jokers[:1])
    assert _plays(target)[0][1] == 105
    assert joker_reorder_advice(observation, _plays(observation), "estimate") == []


@pytest.mark.parametrize("keys", list(permutations(("j_ramen", "j_golden", "j_joker"))))
def test_reselection_of_multiple_plays_terminates_without_cycles(keys):
    observation = replace(
        _observation(keys),
        hand=(VisiblePlayingCard("2", "C"), VisiblePlayingCard("K", "H")),
    )
    visited = set()
    previous_best = 0
    for _ in range(12):
        order = tuple(repr(item) for item in observation.jokers)
        assert order not in visited
        visited.add(order)
        plays = _plays(observation)
        assert len(plays) == 3
        assert plays[0][1] >= previous_best
        previous_best = plays[0][1]
        rows = joker_reorder_advice(observation, plays, "estimate")
        if not rows:
            break
        row = rows[0]
        assert row["first_step_best_score"] >= previous_best
        observation = replace(
            observation,
            jokers=tuple(observation.jokers[index] for index in row["action"]["order"]),
        )
    else:
        raise AssertionError("reorder advice failed to terminate")
    assert previous_best == 150


def test_search_guards_large_joker_rows():
    observation = _observation(("j_ramen",) * 7)
    assert joker_reorder_advice(observation, _plays(observation), "estimate") == []
