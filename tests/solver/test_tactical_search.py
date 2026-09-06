from collections import Counter
from dataclasses import replace

import pytest

from balatro_ai_v2.solver.actions import DiscardCards, HandSlot, PlayCards, ReorderHand, is_legal
from balatro_ai_v2.solver.adapter import to_public_observation
from balatro_ai_v2.solver.public_scoring import score_play
from balatro_ai_v2.solver.public_state import DeckCardCount, HandStat, HiddenHandCard, HiddenJokerSlot, PublicBlind, PublicItem, VisiblePlayingCard
from balatro_ai_v2.solver.tactical_search import _after_discard, _observed_sort, choose_tactical
from solver_state_factory import state
from balatro_ai_v2.solver.public_state import PublicJokerRuntime


@pytest.mark.parametrize("mult,expected", [(5, 4), (1, 0), (0, 0)])
def test_opt_in_green_discard_penalty_once_and_immutable(mult, expected):
    obs = observation(["H_A", "C_3", "S_7"], ["H_4", "C_5"], target=10000)
    green = PublicItem("j_green_joker", "Green Joker", "JOKER", runtime=PublicJokerRuntime(current_mult=mult))
    obs = replace(obs, jokers=(green,))
    original = obs.canonical_json()
    after = _after_discard(obs, discard(1, 2), (VisiblePlayingCard("4", "H"), VisiblePlayingCard("5", "C")),
                           model_green_joker=True)
    assert after.jokers[0].runtime.current_mult == expected
    assert obs.canonical_json() == original
    assert _after_discard(obs, discard(1), (VisiblePlayingCard("4", "H"),)).jokers == obs.jokers


def test_green_opt_in_enables_samples_but_default_still_falls_back():
    obs = observation(["H_A", "H_K", "H_9", "H_6", "C_2", "D_3", "S_4", "C_7"],
                      ["H_2", "H_3", "H_4", "H_5", "H_7", "H_8", "H_T", "H_J"], target=10000)
    green = PublicItem("j_green_joker", "Green Joker", "JOKER", runtime=PublicJokerRuntime(current_mult=5))
    obs = replace(obs, jokers=(green,))
    assert choose_tactical(obs, play(0)).reason == "discard changes joker state: preserve baseline"
    choice = choose_tactical(obs, play(0), samples=4, model_green_joker=True)
    assert choice.samples == 4 and is_legal(obs, choice.action)
    assert choice == choose_tactical(obs, play(0), samples=4, model_green_joker=True)
    unknown = replace(obs, jokers=(replace(green, runtime=None),))
    assert choose_tactical(unknown, play(0), model_green_joker=True).reason == "unknown Green Joker runtime: preserve baseline"
    other = replace(obs, jokers=(green, PublicItem("j_ramen", "Ramen", "JOKER")))
    assert choose_tactical(other, play(0), model_green_joker=True).reason == "discard changes joker state: preserve baseline"


def test_debuffed_green_is_not_decremented():
    obs = observation(["H_A", "C_3"], ["H_4"])
    green = PublicItem("j_green_joker", "Green Joker", "JOKER", debuffed=True,
                       runtime=PublicJokerRuntime(current_mult=5))
    obs = replace(obs, jokers=(green,))
    assert _after_discard(obs, discard(1), (VisiblePlayingCard("4", "H"),),
                          model_green_joker=True).jokers == obs.jokers


@pytest.mark.parametrize("copy_key", ["j_blueprint", "j_brainstorm"])
def test_copied_green_scores_updated_target_without_double_decrement(copy_key):
    obs = observation(["H_A", "C_3"], ["H_4"])
    green = PublicItem("j_green_joker", "Green Joker", "JOKER", runtime=PublicJokerRuntime(current_mult=5))
    copier = PublicItem(copy_key, "Copy", "JOKER")
    obs = replace(obs, jokers=(copier, green) if copy_key == "j_blueprint" else (green, copier))
    drawn = (VisiblePlayingCard("4", "H"),)
    after = _after_discard(obs, discard(1), drawn, model_green_joker=True)
    unpenalized = _after_discard(obs, discard(1), drawn)
    target = next(joker for joker in after.jokers if joker.key == "j_green_joker")
    assert target.runtime.current_mult == 4
    # High Card's 5 chips + Ace's 11, losing one Mult from each scoring copy.
    assert score_play(unpenalized, play(0).cards)[0] - score_play(after, play(0).cards)[0] == 32


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


def test_last_hand_discards_for_a_certain_one_chip_winning_improvement():
    obs = observation(["S_K", "H_9", "C_7", "D_5", "S_2"], ["H_A"], target=100)
    obs = replace(obs, round=replace(obs.round, hands_left=1),
                  hand_stats=tuple(replace(stat, chips=89) if stat.name == "High Card" else stat
                                   for stat in obs.hand_stats))
    assert score_play(obs, play(0).cards)[0] == 99
    choice = choose_tactical(obs, play(0), samples=4)
    assert isinstance(choice.action, DiscardCards)
    assert choice.expected_score == 100
    assert "modeled draw-clear fraction 1.000" in choice.reason


def test_refill_reproduces_unambiguous_observed_rank_order():
    obs = observation(["H_A", "C_K", "S_2"], ["D_Q"])
    mode = _observed_sort(obs.hand)
    assert mode == "rank descending"
    after = _after_discard(obs, discard(1), (VisiblePlayingCard("Q", "D"),), sort_mode=mode)
    assert [card.rank for card in after.hand] == ["A", "Q", "2"]


def test_refill_reproduces_unambiguous_observed_suit_order():
    obs = observation(["S_2", "H_A", "C_K"], ["D_Q"])
    mode = _observed_sort(obs.hand)
    assert mode == "suit descending"
    after = _after_discard(obs, discard(1), (VisiblePlayingCard("Q", "D"),), sort_mode=mode)
    assert [card.suit for card in after.hand] == ["S", "C", "D"]


def test_unknown_order_preserves_baseline_for_order_sensitive_jokers():
    obs = observation(["H_2", "S_A", "C_3", "D_K"], ["H_Q"], target=5000)
    obs = replace(obs, jokers=(PublicItem("j_hanging_chad", "Hanging Chad", "JOKER"),))
    assert _observed_sort(obs.hand) is None
    choice = choose_tactical(obs, discard(0))
    assert choice.action == discard(0)
    assert "unknown refill ordering" in choice.reason


@pytest.mark.parametrize("joker", ["j_misprint", "j_bloodstone"])
def test_random_scoring_clear_is_labeled_estimated(joker):
    obs = observation(["H_A", "C_3", "S_7"], ["H_4"], target=1)
    obs = replace(obs, jokers=(PublicItem(joker, joker, "JOKER"),))
    choice = choose_tactical(obs, play(0))
    assert "estimated clear" in choice.reason


def test_lucky_card_clear_is_labeled_estimated():
    obs = observation(["H_A", "C_3", "S_7"], ["H_4"], target=1)
    obs = replace(obs, hand=(replace(obs.hand[0], enhancement="LUCKY"), *obs.hand[1:]))
    assert "estimated clear" in choose_tactical(obs, play(0)).reason
