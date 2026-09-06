from collections import Counter
from dataclasses import replace

import pytest

from balatro_ai_v2.solver.actions import DiscardCards, HandSlot, PlayCards, ReorderHand, is_legal
from balatro_ai_v2.solver.adapter import to_public_observation
from balatro_ai_v2.solver.public_scoring import score_play
from balatro_ai_v2.solver.public_state import DeckCardCount, HandStat, HiddenHandCard, HiddenJokerSlot, PublicBlind, PublicItem, VisiblePlayingCard
from balatro_ai_v2.solver.tactical_search import choose_tactical
from solver_state_factory import state


_HAND_BASES = {
    "High Card": (5, 1), "Pair": (10, 2), "Two Pair": (20, 2),
    "Three of a Kind": (30, 3), "Straight": (30, 4), "Flush": (35, 4),
    "Full House": (40, 4), "Four of a Kind": (60, 7), "Straight Flush": (100, 8),
}


def observation(keys, draws, *, target=300, boss=None, discards=3, seed="ONE"):
    base = to_public_observation(state("SELECTING_HAND", seed=seed))
    hand = tuple(VisiblePlayingCard(key[2:], key[0]) for key in keys)
    deck = tuple(VisiblePlayingCard(key[2:], key[0]) for key in draws)
    full = Counter(hand + deck)
    return replace(base, hand=hand, hand_limit=len(hand),
                   required_hand_slots=(0,) if boss == "Cerulean Bell" else (),
                   remaining_deck=tuple(DeckCardCount(card, count) for card, count in Counter(deck).items()),
                   draw_count=len(deck), full_deck=tuple(DeckCardCount(card, count) for card, count in full.items()),
                   deck_size=len(hand) + len(deck),
                   hand_stats=tuple(HandStat(name, 1, chips, mult, 0, 0) for name, (chips, mult) in _HAND_BASES.items()),
                   round=replace(base.round, discards_left=discards),
                   blinds=(PublicBlind("BOSS" if boss else "SMALL", "CURRENT", boss or "Small Blind", "", target, False),))


def play(*indices):
    return PlayCards(tuple(HandSlot(index) for index in indices))


def discard(*indices):
    return DiscardCards(tuple(HandSlot(index) for index in indices))


def test_clears_now_without_spending_a_discard():
    obs = observation(["S_A", "H_A", "C_3", "D_7", "S_9"], ["H_K"] * 5, target=50)
    choice = choose_tactical(obs, discard(2, 3, 4))
    assert isinstance(choice.action, PlayCards)
    assert score_play(obs, choice.action.cards)[0] >= 50
    assert choice.samples == 0
    assert choice.reason == "clear blind now"


def test_four_flush_draw_discards_off_suit_cards():
    obs = observation(["H_A", "H_K", "H_9", "H_6", "C_2", "D_3", "S_4", "C_7"],
                      ["H_2", "H_3", "H_4", "H_5", "H_7", "H_8", "H_T", "H_J", "H_Q"])
    choice = choose_tactical(obs, play(0), samples=4)
    assert isinstance(choice.action, DiscardCards)
    assert all(obs.hand[slot.value].suit != "H" for slot in choice.action.cards)
    assert choice.expected_score > choice.baseline_score
    assert is_legal(obs, choice.action)


def test_deterministic_public_sampling_and_no_input_mutation():
    args = (["H_A", "H_K", "H_9", "H_6", "C_2", "D_3", "S_4", "C_7"],
            ["H_2", "H_3", "D_4", "C_5", "S_7", "H_8", "H_T", "H_J"])
    first, second = observation(*args, seed="SECRET1"), observation(*args, seed="SECRET2")
    original = first.canonical_json()
    assert first == second
    assert choose_tactical(first, play(0), samples=4) == choose_tactical(second, play(0), samples=4)
    assert first.canonical_json() == original


def test_hidden_cards_preserve_baseline_without_scoring():
    obs = observation(["H_A", "H_K", "C_2"], ["H_2", "H_3"])
    obs = replace(obs, hand=(HiddenHandCard(), *obs.hand[1:]))
    baseline = discard(0)
    choice = choose_tactical(obs, baseline)
    assert choice.action == baseline and choice.samples == 0
    assert choice.expected_score is None


def test_preserves_a_lower_scoring_strategic_play_that_already_clears():
    obs = observation(["H_A", "C_A", "S_3"], ["H_4"], target=10)
    baseline = play(0)
    choice = choose_tactical(obs, baseline)
    assert choice.action == baseline
    assert choice.reason == "preserve strategic clearing play"


def test_hidden_jokers_and_discard_effects_preserve_baseline():
    obs = observation(["H_A", "C_3", "S_7"], ["H_4"], boss="Amber Acorn")
    obs = replace(obs, jokers=(HiddenJokerSlot(),))
    assert choose_tactical(obs, discard(1)).action == discard(1)
    ordinary = observation(["H_A", "C_3", "S_7"], ["H_4"], target=5000)
    ordinary = replace(ordinary, jokers=(PublicItem("j_green_joker", "Green Joker", "JOKER"),))
    choice = choose_tactical(ordinary, discard(1))
    assert choice.action == discard(1)
    assert choice.reason == "discard changes joker state: preserve baseline"


@pytest.mark.parametrize("boss", ["The Psychic", "The Eye", "The Mouth"])
def test_boss_scoring_restrictions_are_preserved(boss):
    obs = observation(["H_A", "C_A", "S_K", "D_K", "C_9", "D_8", "S_3", "H_2"],
                      ["H_4", "D_5"], target=5000, boss=boss, discards=0)
    if boss in {"The Eye", "The Mouth"}:
        obs = replace(obs, hand_stats=tuple(replace(stat, played_this_round=int(stat.name == "Pair")) for stat in obs.hand_stats))
    choice = choose_tactical(obs, play(0, 1, 4, 5, 6), samples=2)
    assert isinstance(choice.action, PlayCards) and is_legal(obs, choice.action)
    assert 1 <= len(choice.action.cards) <= 5
    family = score_play(obs, choice.action.cards)[1]
    if boss == "The Psychic":
        assert len(choice.action.cards) == 5
    elif boss == "The Eye":
        assert family != "Pair"
    else:
        assert family == "Pair"


def test_forced_card_and_non_tactical_ordering_are_preserved():
    obs = observation(["H_A", "C_A", "S_3"], ["H_4"], boss="Cerulean Bell")
    obs = replace(obs, required_hand_slots=(0,))
    baseline = play(0, 1)
    assert choose_tactical(obs, baseline).action == baseline
    order = ReorderHand((HandSlot(2), HandSlot(1), HandSlot(0)))
    assert choose_tactical(obs, order).action == order


def test_no_discard_when_refill_is_worse():
    obs = observation(["H_A", "C_A", "S_K", "D_K", "C_9"], ["S_2"], target=5000)
    choice = choose_tactical(obs, discard(4), samples=2)
    assert isinstance(choice.action, PlayCards)
    assert choice.reason == "sampled refill does not justify discard"


@pytest.mark.parametrize("samples", [0, -1, True, 65, 1.5])
def test_invalid_sample_budget_is_rejected(samples):
    obs = observation(["H_A", "C_3"], ["S_2"])
    with pytest.raises(ValueError, match="samples"):
        choose_tactical(obs, play(0), samples=samples)
