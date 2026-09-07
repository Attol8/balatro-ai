from __future__ import annotations

from dataclasses import replace
from fractions import Fraction

import pytest
from state_factory import hidden_joker_slot, state

from balatro_ai.game import scoring as public_scoring
from balatro_ai.game.actions import HandSlot
from balatro_ai.game.adapter import to_public_observation
from balatro_ai.game.mechanics import known_joker_keys
from balatro_ai.game.scoring import score_play
from balatro_ai.game.state import (
    OBSCURED_CARD_ATTRIBUTE,
    DeckCardCount,
    HandStat,
    PublicItem,
    PublicJokerRuntime,
    PublicObservation,
    VisiblePlayingCard,
)


@pytest.mark.parametrize("copy_key", ["j_blueprint", "j_brainstorm"])
@pytest.mark.parametrize(
    "key,runtime,expected",
    [
        ("j_popcorn", PublicJokerRuntime(current_mult=20), 656),
        ("j_blackboard", None, 144),
        ("j_throwback", PublicJokerRuntime(current_x_mult=2), 64),
        ("j_constellation", PublicJokerRuntime(current_x_mult=2), 64),
        ("j_hologram", PublicJokerRuntime(current_x_mult=2), 64),
        ("j_ice_cream", PublicJokerRuntime(current_chips=50), 116),
    ],
)
def test_verified_main_copy_targets_use_current_public_runtime(copy_key, key, runtime, expected):
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(VisiblePlayingCard("A", "S"),),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
    )
    target = PublicItem(key, key, "JOKER", runtime=runtime)
    copy = PublicItem(copy_key, copy_key, "JOKER")
    observation = replace(
        observation, jokers=(copy, target) if copy_key == "j_blueprint" else (target, copy)
    )
    assert public_scoring.score_play(observation, (HandSlot(0),))[0] == expected
    assert target.runtime == runtime


@pytest.mark.parametrize("key,field", list(public_scoring._COPY_MAIN_RUNTIME_FIELDS.items()))
def test_new_runtime_copy_targets_require_known_field_and_reject_debuff(key, field):
    copy = PublicItem("j_blueprint", "Blueprint", "JOKER")
    target = PublicItem(key, key, "JOKER")
    resolve = public_scoring._effective_joker_for_pass
    allowed = public_scoring._COPY_MAIN_JOKERS
    assert resolve((copy, target), 0, allowed) is None
    runtime = PublicJokerRuntime(**{field: 0 if field != "current_x_mult" else 2})
    target = replace(target, runtime=runtime)
    assert resolve((copy, target), 0, allowed) == target
    assert resolve((copy, replace(target, debuffed=True)), 0, allowed) is None


def test_new_copy_target_does_not_duplicate_edition():
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(VisiblePlayingCard("A", "S"),),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=(
            PublicItem("j_blueprint", "Blueprint", "JOKER"),
            PublicItem(
                "j_popcorn",
                "Popcorn",
                "JOKER",
                edition="HOLOGRAPHIC",
                runtime=PublicJokerRuntime(current_mult=20),
            ),
        ),
    )
    # 1 base + twice20 Popcorn + only one target edition's10 Mult.
    assert public_scoring.score_play(observation, (HandSlot(0),))[0] == 816


def test_wee_does_not_grow_from_a_debuffed_two():
    observation = to_public_observation(state("SELECTING_HAND"))
    observation = replace(
        observation,
        hand=(VisiblePlayingCard("2", "S"), VisiblePlayingCard("2", "H", debuffed=True)),
        hand_stats=(HandStat("Pair", 1, 10, 2, 0, 0),),
        jokers=(
            PublicItem(
                key="j_wee",
                kind="JOKER",
                label="Wee Joker",
                runtime=PublicJokerRuntime(current_chips=32),
            ),
        ),
    )
    score, family = score_play(observation, (HandSlot(0), HandSlot(1)))
    assert family == "Pair"
    assert score == 104  # (10 base + 2 active card + 32 prior Wee + 8 growth) * 2


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


@pytest.mark.parametrize("disabled", [False, True])
def test_psychic_short_play_scores_zero_only_while_boss_is_active(disabled: bool) -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(name="The Psychic", status="CURRENT", disabled=disabled)
    observation = to_public_observation(raw)

    score, _ = score_play(observation, (HandSlot(0),))

    assert (score == 0) is (not disabled)


@pytest.mark.parametrize("disabled", [False, True])
def test_eye_repeated_family_scores_zero_only_while_boss_is_active(disabled: bool) -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(name="The Eye", status="CURRENT", disabled=disabled)
    observation = to_public_observation(raw)
    _, family = score_play(observation, (HandSlot(0),))
    observation = replace(
        observation,
        hand_stats=tuple(
            replace(hand, played_this_round=1) if hand.name == family else hand
            for hand in observation.hand_stats
        ),
    )

    score, _ = score_play(observation, (HandSlot(0),))

    assert (score == 0) is (not disabled)


@pytest.mark.parametrize("disabled", [False, True])
def test_mouth_other_family_scores_zero_only_while_boss_is_active(disabled: bool) -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(name="The Mouth", status="CURRENT", disabled=disabled)
    observation = to_public_observation(raw)
    _, family = score_play(observation, (HandSlot(0),))
    observation = replace(
        observation,
        hand_stats=(
            *observation.hand_stats,
            HandStat("Pair", 1, 10, 2, 1, 1),
        ),
    )

    score, _ = score_play(observation, (HandSlot(0),))

    assert (score == 0) is (not disabled)


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
        (
            "j_mad",
            (("A", "C"), ("A", "S"), ("K", "H"), ("K", "D")),
            (0, 1, 2, 3),
            ("Two Pair", 20, 2, 0),
            744,
        ),
        (
            "j_clever",
            (("A", "C"), ("A", "S"), ("K", "H"), ("K", "D")),
            (0, 1, 2, 3),
            ("Two Pair", 20, 2, 0),
            284,
        ),
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
        (
            "j_green_joker",
            PublicJokerRuntime(current_mult=4),
            (("A", "S"),),
            (0,),
            ("High Card", 5, 1),
            96,
        ),
        (
            "j_ice_cream",
            PublicJokerRuntime(current_chips=75),
            (("A", "S"),),
            (0,),
            ("High Card", 5, 1),
            91,
        ),
        (
            "j_swashbuckler",
            PublicJokerRuntime(current_mult=7),
            (("A", "S"),),
            (0,),
            ("High Card", 5, 1),
            128,
        ),
        (
            "j_flash",
            PublicJokerRuntime(current_mult=8),
            (("A", "S"),),
            (0,),
            ("High Card", 5, 1),
            144,
        ),
        (
            "j_red_card",
            PublicJokerRuntime(current_mult=9),
            (("A", "S"),),
            (0,),
            ("High Card", 5, 1),
            160,
        ),
        (
            "j_ride_the_bus",
            PublicJokerRuntime(current_mult=5),
            (("A", "S"),),
            (0,),
            ("High Card", 5, 1),
            112,
        ),
        (
            "j_square",
            PublicJokerRuntime(current_chips=20),
            (("A", "S"), ("K", "H"), ("Q", "D"), ("J", "C")),
            (0, 1, 2, 3),
            ("High Card", 5, 1),
            40,
        ),
        (
            "j_trousers",
            PublicJokerRuntime(current_mult=6),
            (("A", "S"), ("A", "H"), ("K", "D"), ("K", "C")),
            (0, 1, 2, 3),
            ("Two Pair", 20, 2),
            620,
        ),
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


def _high_card_ace() -> PublicObservation:
    """One visible Ace of Spades under a level-one High Card."""

    return replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(VisiblePlayingCard("A", "S"),),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
    )


def _with_deck_enhancements(
    observation: PublicObservation, *, steel: int = 0, stone: int = 0
) -> PublicObservation:
    """Rebuild the public full deck with an exact Steel and Stone tally."""

    entries = [DeckCardCount(VisiblePlayingCard("A", "S"), 52 - steel - stone)]
    if steel:
        entries.append(DeckCardCount(VisiblePlayingCard("9", "H", enhancement="STEEL"), steel))
    if stone:
        entries.append(
            DeckCardCount(
                VisiblePlayingCard(
                    OBSCURED_CARD_ATTRIBUTE,
                    OBSCURED_CARD_ATTRIBUTE,
                    enhancement="STONE",
                ),
                stone,
            )
        )
    return replace(observation, full_deck=tuple(entries), deck_size=52)


def test_every_known_joker_key_is_classified_exactly_once() -> None:
    rules = public_scoring.SCORING_RULE_JOKERS
    inert = public_scoring.NO_SCORING_EFFECT_JOKERS

    assert rules & inert == frozenset()
    assert rules | inert == known_joker_keys()
    assert (len(rules), len(inert)) == (102, 48)


def test_no_scoring_effect_joker_is_reported_as_classified_not_missing() -> None:
    observation = replace(
        _high_card_ace(),
        jokers=(PublicItem("j_golden", "Golden Joker", "JOKER"),),
    )

    assert score_play(observation, (HandSlot(0),))[0] == 16
    assert public_scoring.unmodelled_scoring_jokers(observation) == ()


def test_an_unknown_joker_key_surfaces_instead_of_scoring_silently() -> None:
    unknown = PublicItem("j_not_a_vanilla_key", "Modded Joker", "JOKER")
    observation = replace(_high_card_ace(), jokers=(unknown,))

    assert score_play(observation, (HandSlot(0),))[0] == 16
    assert public_scoring.unmodelled_scoring_jokers(observation) == (unknown,)


def test_a_debuffed_unknown_joker_is_not_reported_as_a_scoring_gap() -> None:
    unknown = PublicItem("j_not_a_vanilla_key", "Modded Joker", "JOKER", debuffed=True)
    observation = replace(_high_card_ace(), jokers=(unknown,))

    assert public_scoring.unmodelled_scoring_jokers(observation) == ()


@pytest.mark.parametrize(
    ("steel", "expected"),
    [(0, 16), (1, Fraction(96, 5)), (4, Fraction(144, 5))],
)
def test_steel_joker_scales_with_the_full_deck_steel_tally(steel, expected) -> None:
    observation = _with_deck_enhancements(
        replace(_high_card_ace(), jokers=(PublicItem("j_steel_joker", "Steel Joker", "JOKER"),)),
        steel=steel,
    )

    assert score_play(observation, (HandSlot(0),))[0] == expected


def test_stone_joker_adds_chips_for_each_full_deck_stone_card() -> None:
    observation = _with_deck_enhancements(
        replace(_high_card_ace(), jokers=(PublicItem("j_stone", "Stone Joker", "JOKER"),)),
        stone=3,
    )

    # 5 base + 11 Ace + 3 Stone cards worth 25 Chips each.
    assert score_play(observation, (HandSlot(0),))[0] == 91


@pytest.mark.parametrize(
    ("rank", "suit", "expected"),
    [("A", "S", 32), ("K", "H", 16), ("A", "H", 16), ("K", "S", 16)],
)
def test_idol_doubles_only_a_card_matching_both_target_rank_and_suit(
    rank: str, suit: str, expected: int
) -> None:
    idol = PublicItem(
        "j_idol",
        "The Idol",
        "JOKER",
        runtime=PublicJokerRuntime(target_rank=rank, target_suit=suit),
    )
    observation = replace(_high_card_ace(), jokers=(idol,))

    assert score_play(observation, (HandSlot(0),))[0] == expected


def test_idol_without_a_public_target_is_flagged_instead_of_guessed() -> None:
    idol = PublicItem(
        "j_idol",
        "The Idol",
        "JOKER",
        runtime=PublicJokerRuntime(target_rank="A", target_suit="S"),
    )
    # The observation boundary requires the tooltip target, so strip it after
    # construction to exercise the scorer's own fail-closed branch.
    object.__setattr__(idol, "runtime", None)
    observation = replace(_high_card_ace(), jokers=(idol,))

    assert score_play(observation, (HandSlot(0),))[0] == 16
    assert public_scoring.unmodelled_scoring_jokers(observation) == (idol,)


def test_blueprint_copies_steel_joker_from_the_widened_main_pass() -> None:
    observation = _with_deck_enhancements(
        replace(
            _high_card_ace(),
            jokers=(
                PublicItem("j_blueprint", "Blueprint", "JOKER"),
                PublicItem("j_steel_joker", "Steel Joker", "JOKER"),
            ),
        ),
        steel=4,
    )

    # 16 * X1.8 applied by the copy and again by the target itself.
    assert score_play(observation, (HandSlot(0),))[0] == Fraction(16 * 81, 25)


def test_brainstorm_copies_the_hanging_chad_retrigger() -> None:
    observation = replace(
        _high_card_ace(),
        jokers=(
            PublicItem("j_hanging_chad", "Hanging Chad", "JOKER"),
            PublicItem("j_brainstorm", "Brainstorm", "JOKER"),
        ),
    )

    # Two extra triggers from each of the target and its copy: 5 + 5 * 11.
    assert score_play(observation, (HandSlot(0),))[0] == 60


def test_blueprint_through_brainstorm_resolves_to_brainstorms_own_target() -> None:
    observation = _with_deck_enhancements(
        replace(
            _high_card_ace(),
            jokers=(
                PublicItem("j_steel_joker", "Steel Joker", "JOKER"),
                PublicItem("j_egg", "Egg", "JOKER"),
                PublicItem("j_blueprint", "Blueprint", "JOKER"),
                PublicItem("j_brainstorm", "Brainstorm", "JOKER"),
            ),
        ),
        steel=4,
    )

    # Brainstorm copies slot 0, and Blueprint copies Brainstorm's resolution.
    assert score_play(observation, (HandSlot(0),))[0] == Fraction(16 * 729, 125)


def test_a_debuffed_copy_target_makes_both_the_copy_and_the_target_inert() -> None:
    observation = _with_deck_enhancements(
        replace(
            _high_card_ace(),
            jokers=(
                PublicItem("j_blueprint", "Blueprint", "JOKER"),
                PublicItem("j_steel_joker", "Steel Joker", "JOKER", debuffed=True),
            ),
        ),
        steel=4,
    )

    assert score_play(observation, (HandSlot(0),))[0] == 16


def test_a_copy_cycle_between_two_copy_jokers_scores_nothing() -> None:
    observation = replace(
        _high_card_ace(),
        jokers=(
            PublicItem("j_blueprint", "Blueprint", "JOKER"),
            PublicItem("j_brainstorm", "Brainstorm", "JOKER"),
        ),
    )

    assert score_play(observation, (HandSlot(0),))[0] == 16
