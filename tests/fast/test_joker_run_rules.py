from balatro_ai_v2.fast.joker_run_rules import RUN_EFFECT_JOKERS, apply_joker_run_effect
from balatro_ai_v2.fast.run import FastRunState
from balatro_ai_v2.fast.run_rules import RunModifiers


def test_source_run_effect_jokers_have_modifier_rules() -> None:
    assert RUN_EFFECT_JOKERS == {
        "j_credit_card",
        "j_chaos",
        "j_drunkard",
        "j_juggler",
        "j_oops",
        "j_to_the_moon",
        "j_astronomer",
        "j_troubadour",
        "j_merry_andy",
    }


def test_joker_run_effects_match_source_configs() -> None:
    modifiers = RunModifiers()
    modifiers = apply_joker_run_effect(modifiers, "j_credit_card")
    modifiers = apply_joker_run_effect(modifiers, "j_chaos")
    modifiers = apply_joker_run_effect(modifiers, "j_drunkard")
    modifiers = apply_joker_run_effect(modifiers, "j_juggler")
    modifiers = apply_joker_run_effect(modifiers, "j_oops")
    modifiers = apply_joker_run_effect(modifiers, "j_to_the_moon")
    modifiers = apply_joker_run_effect(modifiers, "j_astronomer")

    assert modifiers.bankrupt_at == -20
    assert modifiers.free_rerolls == 1
    assert modifiers.discards == 4
    assert modifiers.hand_size == 9
    assert modifiers.probability_multiplier == 2
    assert modifiers.interest_amount == 2
    assert modifiers.planets_are_free
    assert modifiers.celestial_packs_are_free


def test_complex_size_joker_run_effects_match_source_configs() -> None:
    troubadour = apply_joker_run_effect(RunModifiers(), "j_troubadour")
    merry_andy = apply_joker_run_effect(RunModifiers(), "j_merry_andy")

    assert troubadour.hand_size == 10
    assert troubadour.hands == 3
    assert merry_andy.discards == 6
    assert merry_andy.hand_size == 7


def test_fast_run_state_exposes_general_run_modifier_fields() -> None:
    run = FastRunState().reset(seed=1)
    run.bankrupt_at = -20
    run.probability_multiplier = 2
    run.planets_are_free = True
    run.celestial_packs_are_free = True

    assert run.bankrupt_at == -20
    assert run.probability_multiplier == 2
    assert run.planets_are_free
    assert run.celestial_packs_are_free
