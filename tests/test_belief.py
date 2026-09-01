from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import pytest

from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.belief import (
    DrawOutcomeLimitExceeded,
    PublicDrawBelief,
    canonical_remaining_deck,
)
from balatro_ai_v2.public_state import DeckCardCount, VisiblePlayingCard
from state_factory import playing_card, state


def _entry(rank: str, suit: str, count: int) -> DeckCardCount:
    return DeckCardCount(VisiblePlayingCard(rank=rank, suit=suit), count)


def test_exact_without_replacement_probability_and_expectation() -> None:
    belief = PublicDrawBelief((_entry("A", "S", 2), _entry("2", "H", 2)), draw_count=4)

    assert belief.matching_count(lambda card: card.rank == "A") == 2
    assert belief.probability_at_least(lambda card: card.rank == "A", draws=2) == Fraction(5, 6)
    assert belief.expected_matches(lambda card: card.rank == "A", draws=2) == Fraction(1)


def test_exact_multivariate_draw_outcomes_preserve_duplicate_multiplicity() -> None:
    belief = PublicDrawBelief(
        (_entry("A", "S", 2), _entry("K", "H", 1)),
        draw_count=3,
    )

    outcomes = belief.exact_outcomes(2)

    assert sum((outcome.probability for outcome in outcomes), Fraction(0)) == 1
    probabilities = {
        tuple(card.rank for card in outcome.drawn_cards): outcome.probability
        for outcome in outcomes
    }
    assert probabilities == {("A", "A"): Fraction(1, 3), ("A", "K"): Fraction(2, 3)}


def test_exact_draws_merge_split_entries_and_ignore_entry_order() -> None:
    card = VisiblePlayingCard("A", "S")
    split = PublicDrawBelief(
        (
            DeckCardCount(VisiblePlayingCard("K", "H"), 1),
            DeckCardCount(card, 1),
            DeckCardCount(card, 1),
        ),
        draw_count=3,
    )
    merged = PublicDrawBelief(
        (DeckCardCount(card, 2), DeckCardCount(VisiblePlayingCard("K", "H"), 1)),
        draw_count=3,
    )

    assert split.exact_outcomes(2) == merged.exact_outcomes(2)
    assert canonical_remaining_deck(split.remaining_deck) == merged.remaining_deck


def test_exact_draw_outcome_limit_fails_instead_of_truncating() -> None:
    belief = PublicDrawBelief(
        (_entry("A", "S", 1), _entry("K", "H", 1), _entry("Q", "D", 1)),
        draw_count=3,
    )

    with pytest.raises(DrawOutcomeLimitExceeded, match="exceeds 2"):
        belief.exact_outcomes(1, max_outcomes=2)


def test_predicate_uses_only_visible_card_fields() -> None:
    belief = PublicDrawBelief(
        (
            DeckCardCount(VisiblePlayingCard("K", "H", enhancement="MULT"), 1),
            DeckCardCount(VisiblePlayingCard("K", "S"), 2),
            DeckCardCount(VisiblePlayingCard("3", "H"), 1),
        ),
        draw_count=4,
    )

    assert belief.matching_count(
        lambda card: card.rank == "K" and card.suit == "H" and card.enhancement == "MULT"
    ) == 1


def test_zero_draws_and_impossible_minimum_are_exact() -> None:
    belief = PublicDrawBelief((_entry("A", "S", 1),), draw_count=1)

    assert belief.probability_at_least(lambda card: True, draws=0) == Fraction(0)
    assert belief.expected_matches(lambda card: True, draws=0) == Fraction(0)
    assert belief.probability_at_least(lambda card: False, draws=1, minimum_matches=0) == Fraction(1)
    assert belief.probability_at_least(lambda card: True, draws=1, minimum_matches=2) == Fraction(0)


@pytest.mark.parametrize(
    ("entries", "draw_count", "message"),
    [
        ((_entry("A", "S", 1),), 2, "sum to draw_count"),
        ((_entry("A", "S", 0),), 0, "positive integers"),
        ((_entry("A", "S", -1),), -1, "non-negative"),
    ],
)
def test_invalid_public_populations_fail_closed(
    entries: tuple[DeckCardCount, ...], draw_count: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        PublicDrawBelief(entries, draw_count)


def test_invalid_draw_request_fails_closed() -> None:
    belief = PublicDrawBelief((_entry("A", "S", 1),), draw_count=1)

    with pytest.raises(ValueError, match="between zero"):
        belief.probability_at_least(lambda card: True, draws=2)
    with pytest.raises(ValueError, match="non-negative integer"):
        belief.probability_at_least(lambda card: True, draws=1, minimum_matches=-1)


def test_hidden_twins_produce_identical_beliefs() -> None:
    left = state("SELECTING_HAND", seed="PRIVATE-A")
    right = deepcopy(left)
    right["seed"] = "PRIVATE-B"
    right["cards"]["cards"].reverse()
    for card in right["cards"]["cards"]:
        card["id"] += 5000

    left_belief = PublicDrawBelief.from_observation(to_public_observation(left))
    right_belief = PublicDrawBelief.from_observation(to_public_observation(right))

    assert left_belief == right_belief

    changed = deepcopy(left)
    changed["cards"]["cards"][0] = playing_card("C_7", card_id=999, hidden=True)
    assert PublicDrawBelief.from_observation(to_public_observation(changed)) != left_belief


def test_belief_module_has_no_authority_or_candidate_dependency() -> None:
    source = (Path(__file__).resolve().parents[1] / "balatro_ai_v2" / "belief.py").read_text()

    assert "balatrobot" not in source.lower()
    assert "jackdaw" not in source.lower()
