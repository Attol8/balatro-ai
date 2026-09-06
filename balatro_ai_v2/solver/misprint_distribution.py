"""Public Misprint outcome enumeration for a narrow final-hand model.

Misprint adds an integer Mult uniformly from 0 through 23. With exactly one
uncopied instance and no other random scoring, each physical play is affine in
that value. Two scoring passes therefore recover all 24 outcomes without an
oracle choosing different cards after seeing the roll. Other scorer limitations
still apply: these are modeled probabilities, not authority guarantees.
"""
from dataclasses import dataclass, replace
from fractions import Fraction

from .actions import PlayCards, is_legal
from .public_scoring import _prepare_score_context, _score_play_prepared
from .public_state import Phase, PublicItem, VisiblePlayingCard


@dataclass(frozen=True)
class MisprintPlay:
    action: PlayCards
    expected_score: float
    family: str
    clear_probability: float
    capped_score: float
    maximum_score: float


def _contexts(observation):
    if observation.phase != Phase.SELECTING_HAND or observation.round.hands_left != 1:
        return None
    if (any(not isinstance(j, PublicItem) for j in observation.jokers)
            or any(not isinstance(c, VisiblePlayingCard) for c in observation.hand)):
        return None
    active = [j for j in observation.jokers if not j.debuffed]
    if sum(j.key == 'j_misprint' for j in active) != 1:
        return None
    if any(j.key in {'j_blueprint', 'j_brainstorm', 'j_bloodstone', 'j_space'} for j in active):
        return None
    if any(c.enhancement == 'LUCKY' and not c.debuffed
           for c in (*observation.hand, *(entry.card for entry in observation.remaining_deck))):
        return None
    context = _prepare_score_context(observation)
    return replace(context, misprint_value=0), replace(context, misprint_value=23)


def _outcomes(observation, selected, contexts):
    low, family = _score_play_prepared(observation, selected, None, contexts[0])
    high, _ = _score_play_prepared(observation, selected, None, contexts[1])
    increment = Fraction(high - low) / 23
    return tuple(Fraction(low) + increment * roll for roll in range(24)), family


def misprint_outcomes(observation, selected):
    """Return scores for one physical play, or None outside the admitted slice."""
    contexts = _contexts(observation)
    if contexts is None or not is_legal(observation, PlayCards(selected)):
        return None
    return _outcomes(observation, selected, contexts)[0]


def best_misprint_play(observation, target, preferred=None):
    from .tactical_search import _selections, _is_scoring_family_eligible
    contexts = _contexts(observation)
    if contexts is None:
        return None
    result = None
    best_key = None
    for selected in _selections(len(observation.hand), observation.selection_limit):
        action = PlayCards(selected)
        if not is_legal(observation, action) or not _is_scoring_family_eligible(observation, action):
            continue
        outcomes, family = _outcomes(observation, selected, contexts)
        probability = sum(value >= target for value in outcomes) / 24
        capped = float(sum(min(target, value) for value in outcomes) / 24)
        expected = float(sum(outcomes) / 24)
        key = (probability, capped, action == preferred, -len(selected), expected,
               tuple(-slot.value for slot in selected))
        if best_key is None or key > best_key:
            best_key = key
            result = MisprintPlay(action, expected, family, probability, capped, float(max(outcomes)))
    return result
