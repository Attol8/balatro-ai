from dataclasses import replace

from balatro_ai_v2.solver.adapter import to_public_observation
from balatro_ai_v2.solver.build_intent import (
    BuildIntent,
    derive_intent,
    joker_value,
    planet_value,
)
from balatro_ai_v2.solver.public_state import PublicItem
from solver_state_factory import state


def _observation(**changes):
    return replace(to_public_observation(state("SHOP")), **changes)


def _joker(key, *, debuffed=False):
    return PublicItem(key, key, "JOKER", debuffed=debuffed)


def test_intent_is_frozen_and_ignores_hidden_and_debuffed_jokers():
    obs = _observation(jokers=(_joker("j_green_joker", debuffed=True), _joker("j_joker")))
    intent = derive_intent(obs)
    assert isinstance(intent, BuildIntent)
    assert intent.growth_keys == ()
    assert intent.scoring_slots == 1
    assert derive_intent(obs) == intent


def test_growth_and_economy_are_more_valuable_early():
    early = _observation(ante=1, jokers=(_joker("j_joker"),))
    late = replace(early, ante=7)
    early_intent = derive_intent(early)
    late_intent = derive_intent(late)
    assert joker_value(_joker("j_green_joker"), early, early_intent) > joker_value(
        _joker("j_green_joker"), late, late_intent
    )
    assert joker_value(_joker("j_rocket"), early, early_intent) > joker_value(
        _joker("j_rocket"), late, late_intent
    )


def test_planet_matches_committed_hand():
    intent = BuildIntent("Pair", "hand", (), 0, 0)
    assert planet_value("c_mercury", intent) == 100
    assert planet_value("c_saturn", intent) == 10
    assert planet_value("c_unknown", intent) == 0


def test_copy_is_only_good_with_a_payoff_and_unknown_is_conservative():
    bare = _observation(jokers=())
    built = _observation(jokers=(_joker("j_joker"), _joker("j_blueprint")))
    assert joker_value(_joker("j_blueprint"), bare, derive_intent(bare)) == 0
    assert joker_value(_joker("j_blueprint"), built, derive_intent(built)) > 0
    assert joker_value(_joker("j_future"), bare, derive_intent(bare)) == 0
