import pytest

from balatro_ai_v2.fast.cards import NUM_RANKS
from balatro_ai_v2.fast.card_state import FastCardState
from balatro_ai_v2.fast.hand import (
    FLUSH,
    PAIR,
    STRAIGHT,
    STRAIGHT_FLUSH,
    held_card_end_money,
    score_cards,
    score_card_states,
    score_cards_with_levels,
    score_cards_with_jokers,
    score_cards_with_modifiers,
)
from balatro_ai_v2.fast.modifiers import Edition, Enhancement, Seal


def card(rank: int, suit: int) -> int:
    return suit * NUM_RANKS + rank


def test_pair_scores_only_pair_cards() -> None:
    result = score_cards(
        (
            card(12, 0),
            card(12, 1),
            card(11, 2),
            card(5, 3),
            card(0, 0),
        )
    )

    assert result.kind == PAIR
    assert result.chips == 32
    assert result.mult == 2
    assert result.total == 64


def test_ace_low_straight() -> None:
    result = score_cards(
        (
            card(12, 0),
            card(0, 1),
            card(1, 2),
            card(2, 3),
            card(3, 0),
        )
    )

    assert result.kind == STRAIGHT


def test_straight_flush_beats_flush() -> None:
    result = score_cards(
        (
            card(7, 1),
            card(8, 1),
            card(9, 1),
            card(10, 1),
            card(11, 1),
        )
    )

    assert result.kind == STRAIGHT_FLUSH


def test_plain_flush() -> None:
    result = score_cards(
        (
            card(0, 2),
            card(3, 2),
            card(6, 2),
            card(8, 2),
            card(11, 2),
        )
    )

    assert result.kind == FLUSH


def test_hand_levels_apply_source_derived_chip_and_mult_increments() -> None:
    levels = [1] * 12
    levels[PAIR] = 3

    result = score_cards_with_levels(
        (
            card(12, 0),
            card(12, 1),
            card(11, 2),
            card(5, 3),
            card(0, 0),
        ),
        tuple(levels),
    )

    assert result.kind == PAIR
    assert result.chips == 32 + 2 * 15
    assert result.mult == 2 + 2 * 1
    assert result.total == 62 * 4


def test_deterministic_played_card_modifiers_score_in_scoring_order() -> None:
    levels = [1] * 12
    result = score_cards_with_modifiers(
        (
            card(12, 0),
            card(12, 1),
            card(11, 2),
            card(5, 3),
            card(0, 0),
        ),
        tuple(levels),
        (
            Enhancement.BONUS,
            Enhancement.MULT,
            Enhancement.BASE,
            Enhancement.BASE,
            Enhancement.BASE,
        ),
        (
            Edition.FOIL,
            Edition.HOLOGRAPHIC,
            Edition.BASE,
            Edition.BASE,
            Edition.BASE,
        ),
    )

    assert result.kind == PAIR
    assert result.chips == 32 + 30 + 50
    assert result.mult == 2 + 4 + 10
    assert result.total == 112 * 16


def test_probabilistic_lucky_modifier_is_not_silently_approximated() -> None:
    levels = [1] * 12

    with pytest.raises(NotImplementedError):
        score_cards_with_modifiers(
            (card(12, 0),),
            tuple(levels),
            (Enhancement.LUCKY,),
            (Edition.BASE,),
        )


def test_additive_joker_scores_flat_mult() -> None:
    levels = [1] * 12

    result = score_cards_with_jokers((card(12, 0),), tuple(levels), ("j_joker",))

    assert result.chips == 16
    assert result.mult == 5
    assert result.total == 80


def test_additive_joker_scores_type_chips_and_mult() -> None:
    levels = [1] * 12

    result = score_cards_with_jokers(
        (
            card(12, 0),
            card(12, 1),
            card(11, 2),
            card(5, 3),
            card(0, 0),
        ),
        tuple(levels),
        ("j_jolly", "j_sly"),
    )

    assert result.kind == PAIR
    assert result.chips == 32 + 50
    assert result.mult == 2 + 8
    assert result.total == 82 * 10


def test_contained_hand_type_jokers_trigger_on_full_house() -> None:
    levels = [1] * 12

    result = score_cards_with_jokers(
        (
            card(12, 0),
            card(12, 1),
            card(12, 2),
            card(5, 3),
            card(5, 0),
        ),
        tuple(levels),
        ("j_jolly", "j_sly"),
    )

    assert result.chips == 40 + 11 + 11 + 11 + 7 + 7 + 50
    assert result.mult == 4 + 8


def test_additive_joker_scores_per_scored_suit_card() -> None:
    levels = [1] * 12

    result = score_cards_with_jokers(
        (
            card(12, 3),
            card(12, 1),
            card(11, 2),
            card(5, 3),
            card(0, 0),
        ),
        tuple(levels),
        ("j_greedy_joker",),
    )

    assert result.kind == PAIR
    assert result.mult == 2 + 3
    assert result.total == result.chips * 5


def test_additive_joker_scores_rank_condition_cards() -> None:
    levels = [1] * 12

    result = score_cards_with_jokers(
        (
            card(12, 0),
            card(12, 1),
        ),
        tuple(levels),
        ("j_scholar",),
    )

    assert result.kind == PAIR
    assert result.chips == 10 + 11 + 11 + 40
    assert result.mult == 2 + 8


def test_global_xmult_joker_scores_hand_family() -> None:
    levels = [1] * 12

    result = score_cards_with_jokers(
        (card(12, 0), card(12, 1)),
        tuple(levels),
        ("j_duo",),
    )

    assert result.chips == 32
    assert result.mult == 2
    assert result.total == 32 * 2 * 2


def test_money_and_deck_count_jokers_use_context() -> None:
    from balatro_ai_v2.fast.jokers import Joker, ScoreContext, apply_additive_jokers

    levels = [1] * 12
    base = score_cards_with_levels((card(12, 0),), tuple(levels))
    result = apply_additive_jokers(
        base,
        (card(12, 0),),
        1,
        (Joker("j_bull"), Joker("j_blue_joker")),
        ScoreContext(money=20, deck_count=40),
    )

    assert result.chips == 16 + 40 + 80
    assert result.total == 136


def test_state_scorer_applies_stone_cards_as_always_scoring() -> None:
    levels = [1] * 12
    result = score_card_states(
        (
            FastCardState(card(12, 0)),
            FastCardState(card(4, 1), enhancement=Enhancement.STONE),
        ),
        tuple(levels),
    )

    assert result.score.chips == 5 + 11 + 50
    assert result.score.mult == 1
    assert result.scoring_indices == (0, 1)


def test_state_scorer_applies_held_steel_cards() -> None:
    levels = [1] * 12
    result = score_card_states(
        (FastCardState(card(12, 0)),),
        tuple(levels),
        (FastCardState(card(2, 1), enhancement=Enhancement.STEEL),),
    )

    assert result.score.chips == 16
    assert result.score.mult == 1.5
    assert result.score.total == 24


def test_state_scorer_red_seal_retriggers_scored_card() -> None:
    levels = [1] * 12
    result = score_card_states(
        (
            FastCardState(
                card(12, 0),
                enhancement=Enhancement.MULT,
                edition=Edition.FOIL,
                seal=Seal.RED,
            ),
        ),
        tuple(levels),
    )

    assert result.score.chips == 16 + 50 + 50
    assert result.score.mult == 1 + 4 + 4
    assert result.score.total == 116 * 9


def test_state_scorer_gold_seal_grants_money_when_scored() -> None:
    levels = [1] * 12
    result = score_card_states(
        (FastCardState(card(12, 0), seal=Seal.GOLD),),
        tuple(levels),
    )

    assert result.money_delta == 3


def test_held_gold_cards_grant_end_round_money() -> None:
    assert (
        held_card_end_money(
            (
                FastCardState(card(3, 0), enhancement=Enhancement.GOLD),
                FastCardState(card(4, 0), enhancement=Enhancement.BASE),
            )
        )
        == 3
    )
