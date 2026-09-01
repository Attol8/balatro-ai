from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from itertools import combinations, permutations

import pytest

from balatro_ai_v2.actions import action_to_data, is_legal, iter_legal_actions
from balatro_ai_v2.actions import (
    ConsumableSlot,
    DiscardCards,
    HandSlot,
    PlayCards,
    UseConsumable,
)
from balatro_ai_v2.baselines import PublicStrategicPolicy, build_public_baseline
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.blind_search import (
    PublicBlindBeliefSearch,
    _RolloutState,
    _exact_successors,
    _initial_exact_state,
    _new_exact_context,
    _solve_state,
    _transition,
)
from fractions import Fraction
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.public_state import DeckCardCount, VisiblePlayingCard
from state_factory import item_card, playing_card, state


def _supported_raw() -> dict[str, object]:
    raw = state("SELECTING_HAND")
    raw["stake"] = "GOLD"
    return raw


def _search(**overrides: int) -> PublicBlindBeliefSearch:
    config = {
        "max_decisions": 2,
        "max_states": 10_000,
        "max_transitions": 100_000,
        "max_chance_outcomes": 50_000,
        "max_chance_outcomes_per_transition": 2_048,
        "max_score_evaluations": 100_000,
        "max_actions_per_state": 1_000,
    }
    config.update(overrides)
    return PublicBlindBeliefSearch(
        **config,
    )


def _tiny_exact_raw(*, target: int = 16) -> dict[str, object]:
    raw = _supported_raw()
    raw["round"]["hands_left"] = 1
    raw["round"]["discards_left"] = 1
    raw["hand"]["limit"] = 3
    raw["blinds"]["small"]["score"] = target
    return raw


def test_blind_search_exactly_prefers_a_surviving_discard() -> None:
    observation = to_public_observation(_tiny_exact_raw())
    baseline = PlayCards(
        (HandSlot(0), HandSlot(1), HandSlot(2)),
    )
    search = _search()

    action = search.choose_action(observation, baseline, ())

    assert is_legal(observation, action)
    assert search.last_decision is not None
    assert search.last_decision.proposal_complete
    assert not search.last_decision.play_discard_action_complete
    assert search.last_decision.selected == action
    assert isinstance(action, DiscardCards)
    assert max(
        value.outcome.clear_probability for value in search.last_decision.values
    ) == Fraction(1, 2)
    assert search.last_decision.transitions_evaluated > 0
    assert search.last_decision.score_evaluations > 0
    assert search.last_decision.chance_outcomes_evaluated > 0
    assert search.last_decision.max_discard_cards == 1
    assert all(
        not isinstance(value.action, DiscardCards) or len(value.action.cards) == 1
        for value in search.last_decision.values
    )


def test_blind_search_hidden_twins_share_exact_results_and_action() -> None:
    left = _tiny_exact_raw()
    left["seed"] = "PRIVATE-A"
    right = deepcopy(left)
    right["seed"] = "PRIVATE-B"
    right["cards"]["cards"].reverse()
    for card in right["cards"]["cards"]:
        card["id"] += 1000
    left_observation = to_public_observation(left)
    right_observation = to_public_observation(right)
    baseline_policy = PublicStrategicPolicy()
    left_baseline = baseline_policy.choose_action(
        left_observation,
        lambda: iter_legal_actions(left_observation),
        (),
    )
    right_baseline = baseline_policy.choose_action(
        right_observation,
        lambda: iter_legal_actions(right_observation),
        (),
    )
    left_search = _search()
    right_search = _search()

    left_action = left_search.choose_action(left_observation, left_baseline, ())
    right_action = right_search.choose_action(right_observation, right_baseline, ())

    assert left_observation == right_observation
    assert action_to_data(left_action) == action_to_data(right_action)
    assert left_search.last_decision == right_search.last_decision


def test_blind_search_fails_closed_for_face_down_or_unsupported_boss() -> None:
    raw = _tiny_exact_raw()
    raw["hand"]["cards"][0] = playing_card("S_A", card_id=50, hidden=True)
    hidden = to_public_observation(raw)
    baseline = PublicStrategicPolicy().choose_action(
        hidden,
        lambda: iter_legal_actions(hidden),
        (),
    )
    search = _search()

    assert search.choose_action(hidden, baseline, ()) == baseline
    assert search.last_decision is None


def test_blind_search_fails_closed_for_unsupported_joker_and_clears_telemetry() -> None:
    supported = to_public_observation(_tiny_exact_raw())
    baseline = PublicStrategicPolicy().choose_action(
        supported,
        lambda: iter_legal_actions(supported),
        (),
    )
    search = _search()
    search.choose_action(supported, baseline, ())
    assert search.last_decision is not None

    raw = _tiny_exact_raw()
    raw["jokers"]["cards"] = [item_card("j_blueprint", card_id=99, kind="JOKER")]
    raw["jokers"]["count"] = 1
    unsupported = to_public_observation(raw)
    unsupported_baseline = PublicStrategicPolicy().choose_action(
        unsupported,
        lambda: iter_legal_actions(unsupported),
        (),
    )

    assert search.choose_action(unsupported, unsupported_baseline, ()) == unsupported_baseline
    assert search.last_decision is None


def test_blind_search_fails_closed_for_uncertified_credit_card_duplicates() -> None:
    raw = _supported_raw()
    raw["jokers"]["cards"] = [
        item_card("j_credit_card", card_id=98, kind="JOKER"),
        item_card("j_credit_card", card_id=99, kind="JOKER"),
    ]
    raw["jokers"]["count"] = 2
    observation = to_public_observation(raw)
    baseline = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )
    search = _search()

    assert search.choose_action(observation, baseline, ()) == baseline
    assert search.last_decision is None


def test_blind_search_budget_or_horizon_failure_is_atomic() -> None:
    raw = _tiny_exact_raw()
    raw["round"]["hands_left"] = 2
    observation = to_public_observation(raw)
    baseline = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )
    search = _search()

    assert search.choose_action(observation, baseline, ()) == baseline
    assert search.last_decision is not None
    assert not search.last_decision.proposal_complete
    assert search.last_decision.values == ()
    assert "horizon" in (search.last_decision.incomplete_reason or "")


def test_blind_search_transition_budget_boundary_is_exact_and_atomic() -> None:
    observation = to_public_observation(_tiny_exact_raw())
    baseline = PlayCards((HandSlot(0), HandSlot(1), HandSlot(2)))
    complete = _search()
    complete.choose_action(observation, baseline, ())
    assert complete.last_decision is not None
    assert complete.last_decision.proposal_complete
    required = complete.last_decision.transitions_evaluated

    exact = _search(max_transitions=required)
    truncated = _search(max_transitions=required - 1)

    exact.choose_action(observation, baseline, ())
    assert exact.last_decision is not None
    assert exact.last_decision.proposal_complete
    assert truncated.choose_action(observation, baseline, ()) == baseline
    assert truncated.last_decision is not None
    assert not truncated.last_decision.proposal_complete
    assert truncated.last_decision.values == ()


@pytest.mark.parametrize(
    "override",
    [
        {"max_states": 1},
        {"max_chance_outcomes": 1},
        {"max_chance_outcomes_per_transition": 1},
        {"max_score_evaluations": 1},
        {"max_actions_per_state": 1},
    ],
)
def test_blind_search_other_budget_failures_are_atomic(
    override: dict[str, int],
) -> None:
    observation = to_public_observation(_tiny_exact_raw())
    baseline = PlayCards((HandSlot(0), HandSlot(1), HandSlot(2)))
    search = _search(**override)

    assert search.choose_action(observation, baseline, ()) == baseline
    assert search.last_decision is not None
    assert not search.last_decision.proposal_complete
    assert search.last_decision.values == ()


def test_blind_search_exact_survival_tie_keeps_original_baseline() -> None:
    observation = to_public_observation(_tiny_exact_raw(target=15))
    baseline = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )
    search = _search()

    assert search.choose_action(observation, baseline, ()) == baseline
    assert search.last_decision is not None
    assert search.last_decision.proposal_complete


def test_blind_search_collapses_semantically_identical_duplicate_slots() -> None:
    raw = _tiny_exact_raw(target=16)
    raw["hand"]["cards"] = [
        playing_card("S_A", card_id=40),
        playing_card("S_A", card_id=41),
        playing_card("H_2", card_id=42),
    ]
    raw["hand"]["count"] = 3
    raw["round"]["discards_left"] = 0
    raw["hands"]["Pair"] = {
        "chips": 10,
        "example": [["S_A", True], ["S_A", True]],
        "level": 1,
        "mult": 2,
        "order": 11,
        "played": 0,
        "played_this_round": 0,
    }
    observation = to_public_observation(raw)
    baseline = PlayCards((HandSlot(1),))
    search = _search()

    assert search.choose_action(observation, baseline, ()) == baseline
    assert search.last_decision is not None
    assert search.last_decision.proposal_complete
    assert search.last_decision.semantic_actions < search.last_decision.raw_actions
    assert baseline in {value.action for value in search.last_decision.values}
    assert PlayCards((HandSlot(0),)) not in {
        value.action for value in search.last_decision.values
    }


def test_blind_search_matches_independent_tiny_public_oracle() -> None:
    observation = to_public_observation(_tiny_exact_raw())
    baseline = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )
    search = _search(max_discard_cards=5)

    selected = search.choose_action(observation, baseline, ())

    assert search.last_decision is not None
    assert search.last_decision.proposal_complete
    assert search.last_decision.play_discard_action_complete
    slots = tuple(HandSlot(index) for index in range(len(observation.hand)))
    expected_actions = {
        action
        for size in range(1, min(5, len(slots)) + 1)
        for selected_slots in combinations(slots, size)
        for action in (PlayCards(selected_slots), DiscardCards(selected_slots))
    }
    assert {value.action for value in search.last_decision.values} == expected_actions
    oracle_probabilities = {}
    for value in search.last_decision.values:
        expected_probability, expected_chips = _tiny_oracle_outcome(
            observation,
            value.action,
        )
        oracle_probabilities[value.action] = expected_probability
        assert value.outcome.clear_probability == expected_probability
        assert value.outcome.expected_capped_chips == expected_chips
    assert max(oracle_probabilities.values()) == oracle_probabilities[baseline]
    assert selected == baseline


def test_blind_search_preserves_exact_duplicate_draw_multiplicity() -> None:
    raw = _tiny_exact_raw()
    raw["cards"]["cards"] = [
        playing_card("S_A", card_id=1, hidden=True),
        playing_card("S_A", card_id=2, hidden=True),
        playing_card("H_K", card_id=3, hidden=True),
    ]
    raw["cards"]["count"] = 3
    observation = to_public_observation(raw)
    baseline = PlayCards((HandSlot(0), HandSlot(1), HandSlot(2)))
    search = _search()

    selected = search.choose_action(observation, baseline, ())

    assert search.last_decision is not None
    assert search.last_decision.proposal_complete
    selected_value = next(
        value for value in search.last_decision.values if value.action == selected
    )
    assert isinstance(selected, DiscardCards)
    assert selected_value.outcome.clear_probability == Fraction(2, 3)
    assert selected_value.outcome.expected_capped_chips == Fraction(47, 3)


def test_blind_search_is_independent_of_public_history() -> None:
    observation = to_public_observation(_tiny_exact_raw())
    baseline = PlayCards((HandSlot(0), HandSlot(1), HandSlot(2)))
    empty = _search()
    populated = _search()
    history = (PublicHistoryStep(observation, baseline, observation),)

    empty_action = empty.choose_action(observation, baseline, ())
    populated_action = populated.choose_action(observation, baseline, history)

    assert populated_action == empty_action
    assert populated.last_decision == empty.last_decision


def test_exact_state_cache_hits_and_does_not_alias_chip_state() -> None:
    observation = to_public_observation(_tiny_exact_raw())
    state = replace(_initial_exact_state(observation), discards_left=0)
    search = _search()
    warm = _new_exact_context(observation, 16, search)

    first = _solve_state(warm, state)
    scores_after_first = warm.score_evaluations
    repeated = _solve_state(warm, state)

    assert repeated == first
    assert warm.cache_hits > 0
    assert warm.score_evaluations == scores_after_first

    changed = replace(state, chips=1)
    warm_changed = _solve_state(warm, changed)
    fresh = _new_exact_context(observation, 16, search)
    fresh_changed = _solve_state(fresh, changed)

    assert warm_changed == fresh_changed
    assert warm_changed != first


def test_exact_draw_composition_cache_reuses_complete_distribution() -> None:
    observation = to_public_observation(_tiny_exact_raw())
    search = _search()
    context = _new_exact_context(observation, 16, search)
    state = _initial_exact_state(observation)
    action = DiscardCards((HandSlot(0),))

    first = _exact_successors(context, state, action)
    hits_before = context.cache_hits
    repeated = _exact_successors(context, state, action)

    assert repeated == first
    assert context.cache_hits == hits_before + 1
    assert len(context.draw_cache) == 1


def test_exact_score_cache_reuses_complete_score() -> None:
    observation = to_public_observation(_tiny_exact_raw())
    search = _search()
    context = _new_exact_context(observation, 16, search)
    state = _initial_exact_state(observation)
    action = PlayCards((HandSlot(0), HandSlot(1), HandSlot(2)))

    first = _exact_successors(context, state, action)
    hits_before = context.cache_hits
    score_calls = context.score_evaluations
    repeated = _exact_successors(context, state, action)

    assert repeated == first
    assert context.cache_hits == hits_before + 1
    assert context.score_evaluations == score_calls
    assert len(context.score_cache) == 1


def _tiny_oracle_outcome(
    observation,
    action: PlayCards | DiscardCards,
) -> tuple[Fraction, Fraction]:
    rank_chips = {"A": 11, "K": 10, "Q": 10, "J": 10, "T": 10, **{str(i): i for i in range(2, 10)}}
    target = next(blind.score for blind in observation.blinds if blind.status == "CURRENT")
    hand = tuple(card for card in observation.hand if isinstance(card, VisiblePlayingCard))
    selected = {slot.value for slot in action.cards}

    def high_card_score(cards: tuple[VisiblePlayingCard, ...]) -> int:
        return 5 + max(rank_chips[card.rank] for card in cards)

    if isinstance(action, PlayCards):
        played = tuple(card for index, card in enumerate(hand) if index in selected)
        score = high_card_score(played)
        return Fraction(int(score >= target)), Fraction(min(score, target))

    kept = tuple(card for index, card in enumerate(hand) if index not in selected)
    physical = tuple(
        entry.card
        for entry in observation.remaining_deck
        for _ in range(entry.count)
    )
    draws = min(observation.hand_limit - len(kept), len(physical))
    orders = tuple(permutations(physical))
    wins = 0
    capped_chips = 0
    for order in orders:
        next_hand = (*kept, *order[:draws])
        score = high_card_score(next_hand)
        wins += int(score >= target)
        capped_chips += min(score, target)
    return Fraction(wins, len(orders)), Fraction(capped_chips, len(orders))


def test_blind_search_is_invariant_to_deck_entry_split_and_order() -> None:
    observation = to_public_observation(_tiny_exact_raw())
    first = observation.remaining_deck[0]
    split = replace(
        observation,
        remaining_deck=(
            *reversed(observation.remaining_deck),
            DeckCardCount(first.card, 1),
        ),
        draw_count=observation.draw_count + 1,
    )
    merged = replace(
        observation,
        remaining_deck=(
            DeckCardCount(first.card, 2),
            *(entry for entry in observation.remaining_deck if entry != first),
        ),
        draw_count=observation.draw_count + 1,
    )
    policy = PublicStrategicPolicy()
    split_baseline = policy.choose_action(split, lambda: iter_legal_actions(split), ())
    merged_baseline = policy.choose_action(merged, lambda: iter_legal_actions(merged), ())
    split_search = _search()
    merged_search = _search()

    split_action = split_search.choose_action(split, split_baseline, ())
    merged_action = merged_search.choose_action(merged, merged_baseline, ())

    assert split_action == merged_action
    assert split_search.last_decision is not None
    assert merged_search.last_decision is not None
    assert split_search.last_decision.values == merged_search.last_decision.values


def test_faceless_discard_updates_public_rollout_money() -> None:
    raw = _supported_raw()
    raw["hand"]["cards"] = [
        playing_card("S_K", card_id=50),
        playing_card("H_Q", card_id=51),
        playing_card("D_J", card_id=52),
    ]
    raw["hand"]["count"] = 3
    raw["jokers"]["cards"] = [
        item_card("j_faceless", card_id=99, kind="JOKER")
    ]
    raw["jokers"]["count"] = 1
    observation = to_public_observation(raw)
    initial = _RolloutState(
        hand=tuple(observation.hand),
        deck_index=0,
        chips=Fraction(0),
        money=observation.money,
        hands_left=observation.round.hands_left,
        discards_left=observation.round.discards_left,
        hands_played=observation.round.hands_played,
        discards_used=observation.round.discards_used,
        hand_stats=observation.hand_stats,
    )

    after = _transition(
        observation,
        initial,
        DiscardCards((HandSlot(0), HandSlot(1), HandSlot(2))),
        (),
    )

    assert after.money == observation.money + 5


def test_faceless_reward_changes_later_bull_score() -> None:
    raw = _supported_raw()
    raw["hand"]["cards"] = [
        playing_card("S_K", card_id=50),
        playing_card("H_Q", card_id=51),
        playing_card("D_J", card_id=52),
        playing_card("C_T", card_id=53),
    ]
    raw["hand"]["count"] = 4
    raw["jokers"]["cards"] = [
        item_card("j_faceless", card_id=98, kind="JOKER"),
        item_card("j_bull", card_id=99, kind="JOKER"),
    ]
    raw["jokers"]["count"] = 2
    observation = to_public_observation(raw)
    initial = _RolloutState(
        hand=tuple(observation.hand),
        deck_index=0,
        chips=Fraction(0),
        money=observation.money,
        hands_left=observation.round.hands_left,
        discards_left=observation.round.discards_left,
        hands_played=observation.round.hands_played,
        discards_used=observation.round.discards_used,
        hand_stats=observation.hand_stats,
    )

    after_discard = _transition(
        observation,
        initial,
        DiscardCards((HandSlot(0), HandSlot(1), HandSlot(2))),
        (),
    )
    after_play = _transition(
        observation,
        after_discard,
        PlayCards((HandSlot(0),)),
        (),
    )

    assert after_discard.money == 9
    assert after_play.chips == 33


def test_exact_faceless_reward_changes_later_bull_score() -> None:
    raw = _supported_raw()
    raw["hand"]["cards"] = [
        playing_card("S_K", card_id=50),
        playing_card("H_Q", card_id=51),
        playing_card("D_J", card_id=52),
        playing_card("C_T", card_id=53),
    ]
    raw["hand"]["count"] = 4
    raw["jokers"]["cards"] = [
        item_card("j_faceless", card_id=98, kind="JOKER"),
        item_card("j_bull", card_id=99, kind="JOKER"),
    ]
    raw["jokers"]["count"] = 2
    observation = to_public_observation(raw)
    search = _search()
    context = _new_exact_context(observation, 300, search)
    initial = _initial_exact_state(observation)

    after_discard = _exact_successors(
        context,
        initial,
        DiscardCards((HandSlot(0), HandSlot(1), HandSlot(2))),
    )[0].state
    ten_slot = next(
        index for index, card in enumerate(after_discard.hand) if card.rank == "T"
    )
    after_play = _exact_successors(
        context,
        after_discard,
        PlayCards((HandSlot(ten_slot),)),
    )[0].state

    assert after_discard.money == 9
    assert after_play.chips == 33


def test_red_gold_search_preserves_a_held_planet_baseline() -> None:
    raw = _supported_raw()
    raw["consumables"]["cards"] = [
        item_card("c_mercury", card_id=90, kind="PLANET")
    ]
    raw["consumables"]["count"] = 1
    observation = to_public_observation(raw)
    policy, _ = build_public_baseline("red_gold_search", "search-test")

    action = policy.choose_action(observation, lambda: iter_legal_actions(observation), ())

    assert action == UseConsumable(ConsumableSlot(0))


def test_red_gold_search_policy_is_registered() -> None:
    policy, identity = build_public_baseline("red_gold_search", "search-test")

    assert policy.__class__.__name__ == "PublicRedGoldSearchPolicy"
    assert identity == "PublicRedGoldSearchPolicy:search-test"
