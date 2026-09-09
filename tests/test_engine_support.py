"""Cross-build support and reversal checks, independent of archived game seeds."""

from dataclasses import replace

import pytest

from balatro_ai.analysis import analyze
from balatro_ai.game.actions import HandSlot
from balatro_ai.game.adapter import to_public_observation
from balatro_ai.game.scoring import score_play
from balatro_ai.game.state import DeckCardCount, HandStat, PublicItem, VisiblePlayingCard
from tests.game.state_factory import state


def shop(cards, owned=(), offers=()):
    return replace(
        to_public_observation(state("SHOP")),
        hand=(),
        full_deck=tuple(DeckCardCount(card, 1) for card in cards),
        deck_size=len(cards),
        jokers=owned,
        shop=offers,
        opened_pack=(),
    )


@pytest.mark.parametrize("rank,suit", [("J", "S"), ("Q", "D"), ("K", "H")])
def test_plain_face_photograph_chad_support_has_independent_scoring_basis(rank, suit):
    card = VisiblePlayingCard(rank, suit)
    photo = PublicItem("j_photograph", "Photograph", "JOKER")
    chad = PublicItem("j_hanging_chad", "Hanging Chad", "JOKER")
    observation = shop((card,), (photo,), (chad,))
    row = analyze(observation)["engine_opportunities"][0]
    assert row["support"] == {
        "enhanced_scoring_cards_in_public_deck": 0,
        "active_photograph": True,
        "face_cards_in_public_deck": 1,
    }
    scoring = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(card,),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=(photo,),
    )
    assert score_play(scoring, (HandSlot(0),))[0] == (5 + 10) * 2
    assert (
        score_play(replace(scoring, jokers=(photo, chad)), (HandSlot(0),))[0] == (5 + 3 * 10) * 2**3
    )


@pytest.mark.parametrize("rank,active", [("2", True), ("Q", False)])
def test_plain_cards_without_active_face_engine_do_not_invent_chad_support(rank, active):
    observation = shop(
        (VisiblePlayingCard(rank, "C"),),
        (PublicItem("j_photograph", "Photograph", "JOKER", debuffed=not active),),
        (PublicItem("j_hanging_chad", "Hanging Chad", "JOKER"),),
    )
    assert "engine_opportunities" not in analyze(observation)


def test_moon_and_baron_offers_both_get_support_without_purchase_ranking():
    observation = shop(
        (VisiblePlayingCard("Q", "S"), VisiblePlayingCard("K", "H")),
        offers=(
            PublicItem("j_shoot_the_moon", "Shoot the Moon", "JOKER", buy_cost=5),
            PublicItem("j_baron", "Baron", "JOKER", buy_cost=8),
        ),
    )
    rows = analyze(observation)["engine_opportunities"]
    assert [(r["key"], r["support"]) for r in rows] == [
        ("j_shoot_the_moon", {"queens_in_public_deck": 1}),
        ("j_baron", {"kings_in_public_deck": 1}),
    ]
    assert "engine_opportunities" not in analyze(replace(observation, full_deck=(), deck_size=0))


def test_moon_support_disappears_without_queens():
    observation = shop(
        (VisiblePlayingCard("K", "D"),),
        offers=(PublicItem("j_shoot_the_moon", "Shoot the Moon", "JOKER"),),
    )
    assert "engine_opportunities" not in analyze(observation)
