from dataclasses import replace

import pytest

from balatro_ai_v2.solver.actions import HandSlot, PlayCards, ReorderHand, ReorderJokers, is_legal
from balatro_ai_v2.solver.adapter import to_public_observation
from balatro_ai_v2.solver.ordering_search import improve_play_order
from balatro_ai_v2.solver.public_state import (
    HandStat, HiddenHandCard, HiddenJokerSlot, PublicBlind, PublicItem,
    PublicJokerRuntime, VisiblePlayingCard,
)
from solver_state_factory import state


def fixture():
    obs = to_public_observation(state("SELECTING_HAND"))
    return replace(obs,
        hand=(VisiblePlayingCard("A", "S"), VisiblePlayingCard("2", "C")),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=(PublicItem("j_blackboard", "Blackboard", "JOKER"),
                PublicItem("j_popcorn", "Popcorn", "JOKER", runtime=PublicJokerRuntime(current_mult=20))),
        blinds=(PublicBlind("SMALL", "CURRENT", "Small Blind", "", 100000, False),))


def test_blackboard_popcorn_gain_is_legal_deterministic_and_immutable():
    obs = fixture()
    original = obs.canonical_json()
    play = PlayCards((HandSlot(0),))
    choice = improve_play_order(obs, play)
    assert isinstance(choice.action, ReorderJokers)
    assert is_legal(obs, choice.action)
    assert choice.diagnostics["baseline_score"] == 368
    assert choice.diagnostics["reordered_score"] == 1008
    assert choice == improve_play_order(obs, play)
    assert obs.canonical_json() == original


def test_onyx_before_photograph_maps_same_physical_cards():
    obs = replace(fixture(),
        hand=(VisiblePlayingCard("Q", "C"), VisiblePlayingCard("9", "C"),
              VisiblePlayingCard("8", "C"), VisiblePlayingCard("6", "C"), VisiblePlayingCard("5", "C")),
        hand_stats=(HandStat("Flush", 1, 35, 4, 0, 0),),
        jokers=(PublicItem("j_photograph", "Photograph", "JOKER"),
                PublicItem("j_wrathful_joker", "Wrathful Joker", "JOKER"),
                PublicItem("j_onyx_agate", "Onyx Agate", "JOKER")))
    play = PlayCards(tuple(HandSlot(i) for i in range(5)))
    choice = improve_play_order(obs, play)
    assert isinstance(choice.action, ReorderHand)
    assert choice.diagnostics["swap"] == [0, 1]
    assert choice.diagnostics["reordered_score"] > choice.diagnostics["baseline_score"]
    assert choice.diagnostics["selected_after"] == list(range(5))
    assert is_legal(obs, choice.action)


@pytest.mark.parametrize("condition", ["clearing", "hidden_hand", "hidden_joker", "forced", "random", "illegal"])
def test_safe_no_intervention(condition):
    obs = fixture()
    play = PlayCards((HandSlot(0),))
    if condition == "clearing":
        obs = replace(obs, blinds=(replace(obs.blinds[0], score=1),))
    elif condition == "hidden_hand":
        obs = replace(obs, hand=(HiddenHandCard(), *obs.hand[1:]))
    elif condition == "hidden_joker":
        obs = replace(obs, jokers=(HiddenJokerSlot(),),
                      blinds=(replace(obs.blinds[0], kind="BOSS", name="Amber Acorn"),))
    elif condition == "forced":
        obs = replace(obs, required_hand_slots=(0,),
                      blinds=(replace(obs.blinds[0], kind="BOSS", name="Cerulean Bell"),))
    elif condition == "random":
        obs = replace(obs, jokers=(*obs.jokers, PublicItem("j_misprint", "Misprint", "JOKER")))
    else:
        play = PlayCards((HandSlot(9),))
    assert improve_play_order(obs, play) is None
