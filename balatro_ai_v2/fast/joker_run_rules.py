from __future__ import annotations

from dataclasses import replace

from balatro_ai_v2.fast.run_rules import RunModifiers


RUN_EFFECT_JOKERS = frozenset(
    {
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
)


def apply_joker_run_effect(modifiers: RunModifiers, joker_key: str) -> RunModifiers:
    if joker_key == "j_credit_card":
        return replace(modifiers, bankrupt_at=modifiers.bankrupt_at - 20)
    if joker_key == "j_chaos":
        return replace(modifiers, free_rerolls=modifiers.free_rerolls + 1)
    if joker_key == "j_drunkard":
        return replace(modifiers, discards=modifiers.discards + 1)
    if joker_key == "j_juggler":
        return replace(modifiers, hand_size=modifiers.hand_size + 1)
    if joker_key == "j_oops":
        return replace(modifiers, probability_multiplier=modifiers.probability_multiplier * 2)
    if joker_key == "j_to_the_moon":
        return replace(modifiers, interest_amount=modifiers.interest_amount + 1)
    if joker_key == "j_astronomer":
        return replace(modifiers, planets_are_free=True, celestial_packs_are_free=True)
    if joker_key == "j_troubadour":
        return replace(modifiers, hand_size=modifiers.hand_size + 2, hands=modifiers.hands - 1)
    if joker_key == "j_merry_andy":
        return replace(modifiers, discards=modifiers.discards + 3, hand_size=modifiers.hand_size - 1)
    raise NotImplementedError(f"joker run effect is not implemented: {joker_key}")
