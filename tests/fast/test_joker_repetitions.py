from balatro_ai_v2.fast.cards import NUM_RANKS
from balatro_ai_v2.fast.joker_repetitions import (
    RETRIGGER_JOKERS,
    RepetitionContext,
    held_card_repetitions,
    played_card_repetitions,
    total_held_card_repetitions,
    total_played_card_repetitions,
)
from balatro_ai_v2.fast.jokers import Joker


def card(rank: int, suit: int) -> int:
    return suit * NUM_RANKS + rank


def test_retrigger_joker_set_tracks_source_repetition_rules() -> None:
    assert RETRIGGER_JOKERS == {
        "j_dusk",
        "j_hack",
        "j_hanging_chad",
        "j_mime",
        "j_selzer",
        "j_sock_and_buskin",
    }


def test_played_card_repetition_rules_match_source_conditions() -> None:
    context = RepetitionContext(scoring_indices=(1, 2, 3), hands_left=0)

    assert played_card_repetitions(Joker("j_hanging_chad"), card(12, 0), 1, context) == 2
    assert played_card_repetitions(Joker("j_hanging_chad"), card(12, 0), 2, context) == 0
    assert played_card_repetitions(Joker("j_dusk"), card(12, 0), 2, context) == 1
    assert played_card_repetitions(Joker("j_selzer"), card(12, 0), 2, context) == 1
    assert played_card_repetitions(Joker("j_hack"), card(3, 0), 2, context) == 1
    assert played_card_repetitions(Joker("j_hack"), card(4, 0), 2, context) == 0
    assert played_card_repetitions(Joker("j_sock_and_buskin"), card(9, 0), 2, context) == 1


def test_pareidolia_context_makes_sock_and_buskin_retrigger_non_faces() -> None:
    context = RepetitionContext(all_cards_are_face=True)

    assert played_card_repetitions(Joker("j_sock_and_buskin"), card(2, 0), 0, context) == 1


def test_repetition_totals_sum_multiple_jokers() -> None:
    context = RepetitionContext(scoring_indices=(0,), hands_left=0, held_card_has_effect=True)
    jokers = (Joker("j_hanging_chad"), Joker("j_dusk"), Joker("j_mime"))

    assert total_played_card_repetitions(jokers, card(12, 0), 0, context) == 3
    assert held_card_repetitions(Joker("j_mime"), context) == 1
    assert total_held_card_repetitions(jokers, context) == 1
