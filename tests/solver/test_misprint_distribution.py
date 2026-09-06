from dataclasses import replace
import pytest

from balatro_ai_v2.solver.actions import HandSlot
from balatro_ai_v2.solver.adapter import to_public_observation
from balatro_ai_v2.solver.misprint_distribution import misprint_outcomes, best_misprint_play
from balatro_ai_v2.solver.public_scoring import _prepare_score_context, _score_play_prepared, score_play
from balatro_ai_v2.solver.public_state import PublicItem, DeckCardCount, VisiblePlayingCard
from solver_state_factory import state


def obs():
    o = to_public_observation(state('SELECTING_HAND'))
    return replace(o, round=replace(o.round, hands_left=1),
                   jokers=(PublicItem('j_misprint', 'Misprint', 'JOKER'),))


@pytest.mark.parametrize('extra', [(), (PublicItem('j_cavendish', 'Cavendish', 'JOKER'),),
                                  (PublicItem('j_baseball', 'Baseball', 'JOKER'),)])
def test_affine_distribution_equals_all_24_direct_scores(extra):
    o = obs()
    o = replace(o, jokers=o.jokers + extra)
    selected = (HandSlot(0),)
    original = o.canonical_json()
    outcomes = misprint_outcomes(o, selected)
    context = _prepare_score_context(o)
    direct = tuple(_score_play_prepared(o, selected, None, replace(context, misprint_value=k))[0]
                   for k in range(24))
    assert outcomes == direct
    assert sum(outcomes) / 24 == score_play(o, selected)[0]
    assert o.canonical_json() == original


def test_single_physical_best_play_is_evaluated_across_all_outcomes():
    o = obs()
    result = best_misprint_play(o, 100)
    outcomes = misprint_outcomes(o, result.action.cards)
    assert result.clear_probability == sum(v >= 100 for v in outcomes) / 24
    assert result.expected_score == float(sum(outcomes) / 24)
    assert result.maximum_score == max(outcomes)


@pytest.mark.parametrize('key', ['j_blueprint', 'j_brainstorm', 'j_space', 'j_bloodstone', 'j_misprint'])
def test_other_randomness_and_copying_fail_closed(key):
    o = obs()
    o = replace(o, jokers=o.jokers + (PublicItem(key, key, 'JOKER'),))
    assert best_misprint_play(o, 100) is None


def test_lucky_refills_are_not_treated_as_deterministic():
    o = obs()
    o = replace(o, remaining_deck=(DeckCardCount(VisiblePlayingCard('A', 'S', enhancement='LUCKY'), 1),), draw_count=1)
    assert best_misprint_play(o, 100) is None


def test_only_final_hand_is_admitted():
    o = obs()
    assert best_misprint_play(replace(o, round=replace(o.round, hands_left=2)), 100) is None
