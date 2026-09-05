from __future__ import annotations

from dataclasses import replace

import pytest
from state_factory import hidden_joker_slot, state

from balatro_ai_v2 import public_scoring
from balatro_ai_v2.actions import HandSlot
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.public_scoring import score_play
from balatro_ai_v2.public_state import (
    HandStat,
    PublicItem,
    PublicJokerRuntime,
    VisiblePlayingCard,
)


def test_exact_score_is_unavailable_for_amber_joker_order() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(name="Amber Acorn", status="CURRENT")
    raw["jokers"] = {
        "cards": [hidden_joker_slot(), hidden_joker_slot()],
        "count": 2,
        "highlighted_limit": 1,
        "limit": 5,
    }
    observation = to_public_observation(raw)

    with pytest.raises(ValueError, match="exact scoring is unavailable"):
        score_play(observation, (HandSlot(0),))


@pytest.mark.parametrize(
    ("key", "hand", "selected", "stat", "expected"),
    [
        ("j_raised_fist", (("A", "S"), ("2", "D")), (0,), ("High Card", 5, 1, 0), 80),
        ("j_odd_todd", (("A", "S"),), (0,), ("High Card", 5, 1, 0), 47),
        ("j_wrathful_joker", (("A", "S"),), (0,), ("High Card", 5, 1, 0), 64),
        ("j_even_steven", (("2", "S"),), (0,), ("High Card", 5, 1, 0), 35),
        ("j_walkie_talkie", (("T", "S"),), (0,), ("High Card", 5, 1, 0), 125),
        ("j_scholar", (("A", "S"),), (0,), ("High Card", 5, 1, 0), 180),
        ("j_photograph", (("K", "S"),), (0,), ("High Card", 5, 1, 0), 30),
        ("j_hanging_chad", (("A", "S"),), (0,), ("High Card", 5, 1, 0), 38),
        ("j_shoot_the_moon", (("A", "S"), ("Q", "D")), (0,), ("High Card", 5, 1, 0), 224),
        ("j_blue_joker", (("A", "S"),), (0,), ("High Card", 5, 1, 0), 20),
        ("j_half", (("A", "S"),), (0,), ("High Card", 5, 1, 0), 336),
        ("j_supernova", (("A", "S"),), (0,), ("High Card", 5, 1, 3), 80),
        ("j_juggler", (("A", "S"),), (0,), ("High Card", 5, 1, 0), 16),
        ("j_stuntman", (("A", "S"),), (0,), ("High Card", 5, 1, 0), 266),
        ("j_jolly", (("A", "C"), ("A", "S")), (0, 1), ("Pair", 10, 2, 0), 320),
        ("j_seeing_double", (("A", "C"), ("A", "S")), (0, 1), ("Pair", 10, 2, 0), 128),
        ("j_mad", (("A", "C"), ("A", "S"), ("K", "H"), ("K", "D")), (0, 1, 2, 3), ("Two Pair", 20, 2, 0), 744),
        ("j_clever", (("A", "C"), ("A", "S"), ("K", "H"), ("K", "D")), (0, 1, 2, 3), ("Two Pair", 20, 2, 0), 284),
    ],
)
def test_one_play_capacity_jokers_have_constructed_exact_scores(
    key: str,
    hand: tuple[tuple[str, str], ...],
    selected: tuple[int, ...],
    stat: tuple[str, int, int, int],
    expected: int,
) -> None:
    observation = to_public_observation(state("SELECTING_HAND"))
    name, chips, mult, played = stat
    observation = replace(
        observation,
        hand=tuple(VisiblePlayingCard(rank, suit) for rank, suit in hand),
        hand_stats=(HandStat(name, 1, chips, mult, played, played),),
        jokers=(PublicItem(key, key, "JOKER"),),
    )

    score, _ = score_play(
        observation,
        tuple(HandSlot(slot) for slot in selected),
    )

    assert score == expected


@pytest.mark.parametrize(
    ("key", "runtime", "hand", "selected", "stat", "expected"),
    [
        ("j_green_joker", PublicJokerRuntime(current_mult=4), (("A", "S"),), (0,), ("High Card", 5, 1), 96),
        ("j_ice_cream", PublicJokerRuntime(current_chips=75), (("A", "S"),), (0,), ("High Card", 5, 1), 91),
        ("j_swashbuckler", PublicJokerRuntime(current_mult=7), (("A", "S"),), (0,), ("High Card", 5, 1), 128),
        ("j_flash", PublicJokerRuntime(current_mult=8), (("A", "S"),), (0,), ("High Card", 5, 1), 144),
        ("j_red_card", PublicJokerRuntime(current_mult=9), (("A", "S"),), (0,), ("High Card", 5, 1), 160),
        ("j_ride_the_bus", PublicJokerRuntime(current_mult=5), (("A", "S"),), (0,), ("High Card", 5, 1), 112),
        ("j_square", PublicJokerRuntime(current_chips=20), (("A", "S"), ("K", "H"), ("Q", "D"), ("J", "C")), (0, 1, 2, 3), ("High Card", 5, 1), 40),
        ("j_trousers", PublicJokerRuntime(current_mult=6), (("A", "S"), ("A", "H"), ("K", "D"), ("K", "C")), (0, 1, 2, 3), ("Two Pair", 20, 2), 620),
    ],
)
def test_one_play_runtime_jokers_use_the_public_current_counter(
    key: str,
    runtime: PublicJokerRuntime,
    hand: tuple[tuple[str, str], ...],
    selected: tuple[int, ...],
    stat: tuple[str, int, int],
    expected: int,
) -> None:
    observation = to_public_observation(state("SELECTING_HAND"))
    name, chips, mult = stat
    observation = replace(
        observation,
        hand=tuple(VisiblePlayingCard(rank, suit) for rank, suit in hand),
        hand_stats=(HandStat(name, 1, chips, mult, 0, 0),),
        jokers=(PublicItem(key, key, "JOKER", runtime=runtime),),
    )

    score, _ = score_play(
        observation,
        tuple(HandSlot(slot) for slot in selected),
    )

    assert score == expected


def test_prepared_passes_filter_irrelevant_jokers_without_copying_bloodstone() -> None:
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        jokers=(
            PublicItem("j_photograph", "Photograph", "JOKER"),
            PublicItem("j_brainstorm", "Brainstorm", "JOKER"),
            PublicItem("j_joker", "Joker", "JOKER"),
            PublicItem("j_bloodstone", "Bloodstone", "JOKER"),
            PublicItem("j_blueprint", "Blueprint", "JOKER"),
            PublicItem("j_bloodstone", "Bloodstone", "JOKER"),
        ),
    )

    context = public_scoring._prepare_score_context(observation)

    assert tuple(joker.key for joker in context.played_individual_jokers) == (
        "j_photograph",
        "j_photograph",
        "j_bloodstone",
        "j_bloodstone",
    )
    assert context.played_retrigger_jokers == ()
    assert context.held_individual_jokers == ()
    assert context.held_retrigger_jokers == ()


def test_played_addition_and_xmult_keep_source_joker_order() -> None:
    base = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(VisiblePlayingCard("A", "H"),),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
    )
    lusty = PublicItem("j_lusty_joker", "Lusty Joker", "JOKER")
    bloodstone = PublicItem("j_bloodstone", "Bloodstone", "JOKER")

    add_then_multiply, _ = score_play(
        replace(base, jokers=(lusty, bloodstone)),
        (HandSlot(0),),
    )
    multiply_then_add, _ = score_play(
        replace(base, jokers=(bloodstone, lusty)),
        (HandSlot(0),),
    )

    assert add_then_multiply == 80
    assert multiply_then_add == 68
