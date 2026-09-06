from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest

from balatro_ai_v2.solver.adapter import to_public_observation
from balatro_ai_v2.solver.build_strategy import BuildPlan, infer_build_plan, planet_fit, planet_hand
from balatro_ai_v2.solver.public_state import HandStat, PublicItem
from solver_state_factory import state


_PLANETS = {
    "c_pluto": "High Card",
    "c_mercury": "Pair",
    "c_uranus": "Two Pair",
    "c_venus": "Three of a Kind",
    "c_saturn": "Straight",
    "c_jupiter": "Flush",
    "c_earth": "Full House",
    "c_mars": "Four of a Kind",
    "c_neptune": "Straight Flush",
    "c_planet_x": "Five of a Kind",
    "c_ceres": "Flush House",
    "c_eris": "Flush Five",
}


def _observation(**changes):
    observation = to_public_observation(state("SHOP"))
    return replace(observation, **changes)


def _joker(key: str) -> PublicItem:
    return PublicItem(key=key, label=key, kind="JOKER")


def _stat(name: str, *, level: int = 1, played: int = 0) -> HandStat:
    return HandStat(name=name, level=level, chips=0, mult=1, played=played, played_this_round=0)


def test_default_tie_prefers_pair_then_two_pair() -> None:
    plan = infer_build_plan(_observation(hand_stats=()))

    assert plan == BuildPlan(
        primary_hand="Pair",
        secondary_hand="Two Pair",
        confidence_numerator=2,
        confidence_denominator=7,
        favored_tags=frozenset(
            {
                "pair",
                "two_pair",
                "three_of_a_kind",
                "full_house",
                "four_of_a_kind",
            }
        ),
    )


def test_catalog_joker_archetype_votes_for_its_hand() -> None:
    plan = infer_build_plan(_observation(hand_stats=(), jokers=(_joker("j_tribe"),)))

    assert plan.primary_hand == "Flush"
    assert plan.confidence_numerator == 4
    assert plan.confidence_denominator == 9


@pytest.mark.parametrize(
    ("deck", "expected_primary", "expected_numerator"),
    [("CHECKERED", "Flush", 5), ("ABANDONED", "Flush", 4)],
)
def test_deck_votes_are_public_and_deterministic(
    deck: str,
    expected_primary: str,
    expected_numerator: int,
) -> None:
    plan = infer_build_plan(_observation(deck=deck, hand_stats=()))

    assert plan.primary_hand == expected_primary
    assert plan.confidence_numerator == expected_numerator


def test_top_played_hand_and_capped_levels_add_votes() -> None:
    observation = _observation(
        hand_stats=(
            _stat("Pair", level=7, played=2),
            _stat("Straight", level=4, played=5),
            _stat("Flush", level=2, played=1),
        )
    )

    plan = infer_build_plan(observation)

    assert plan.primary_hand == "Straight"
    assert plan.secondary_hand == "Pair"
    assert plan.confidence_numerator == 7  # prior 1 + history 3 + capped levels 3
    assert plan.confidence_denominator == 17


@pytest.mark.parametrize(("key", "hand"), sorted(_PLANETS.items()))
def test_all_vanilla_planets_have_exact_hand_mapping(key: str, hand: str) -> None:
    assert planet_hand(key) == hand


def test_planet_fit_rewards_primary_related_family_and_rejects_unknown() -> None:
    pair_plan = BuildPlan("Pair", "Flush", 2, 7, frozenset({"pair"}))

    assert planet_fit("c_mercury", pair_plan) == 100
    assert planet_fit("c_uranus", pair_plan) == 60
    assert planet_fit("c_jupiter", pair_plan) == 10
    assert planet_hand("c_modded_future") is None
    assert planet_fit("c_modded_future", pair_plan) == 0

    straight_flush_plan = BuildPlan("Straight Flush", None, 1, 1, frozenset())
    assert planet_fit("c_saturn", straight_flush_plan) == 60
    assert planet_fit("c_jupiter", straight_flush_plan) == 60


def test_build_plan_is_frozen() -> None:
    plan = infer_build_plan(_observation(hand_stats=()))

    with pytest.raises(FrozenInstanceError):
        plan.primary_hand = "Flush"  # type: ignore[misc]


def test_hidden_twins_produce_identical_build_plan() -> None:
    left = state("SHOP", seed="PRIVATE-A")
    right = deepcopy(left)
    right["seed"] = "PRIVATE-B"
    right["cards"]["cards"].reverse()
    for card in right["cards"]["cards"]:
        card["id"] += 10_000

    assert infer_build_plan(to_public_observation(left)) == infer_build_plan(
        to_public_observation(right)
    )
