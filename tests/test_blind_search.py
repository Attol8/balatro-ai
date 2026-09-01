from __future__ import annotations

from copy import deepcopy

from balatro_ai_v2.actions import action_to_data, is_legal, iter_legal_actions
from balatro_ai_v2.actions import ConsumableSlot, DiscardCards, HandSlot, UseConsumable
from balatro_ai_v2.baselines import PublicStrategicPolicy, build_public_baseline
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.blind_search import PublicBlindBeliefSearch
from state_factory import item_card, playing_card, state


def _supported_raw() -> dict[str, object]:
    raw = state("SELECTING_HAND")
    raw["stake"] = "GOLD"
    return raw


def _search(particles: int = 2) -> PublicBlindBeliefSearch:
    return PublicBlindBeliefSearch(
        particles=particles,
        minimum_particle_gain=1,
        root_play_width=2,
        root_discard_width=1,
        max_play_candidates_per_state=1000,
    )


def test_blind_search_returns_a_legal_action_with_bounded_rollouts() -> None:
    observation = to_public_observation(_supported_raw())
    baseline = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )
    search = _search()

    action = search.choose_action(observation, baseline, ())

    assert is_legal(observation, action)
    assert search.last_decision is not None
    assert search.last_decision.transitions_evaluated > 0
    assert search.last_decision.score_evaluations > 0
    assert len(search.last_decision.results) <= 4


def test_blind_search_hidden_twins_share_tapes_results_and_action() -> None:
    left = _supported_raw()
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
    raw = _supported_raw()
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
    supported = to_public_observation(_supported_raw())
    baseline = PublicStrategicPolicy().choose_action(
        supported,
        lambda: iter_legal_actions(supported),
        (),
    )
    search = _search()
    search.choose_action(supported, baseline, ())
    assert search.last_decision is not None

    raw = _supported_raw()
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


def test_discard_candidates_preserve_the_best_play_when_outsiders_exist() -> None:
    observation = to_public_observation(_supported_raw())
    search = PublicBlindBeliefSearch(
        particles=1,
        minimum_particle_gain=1,
        root_play_width=1,
        root_discard_width=1,
    )
    baseline = DiscardCards((HandSlot(0),))

    search.choose_action(observation, baseline, ())

    assert search.last_decision is not None
    play = next(
        result.action
        for result in search.last_decision.results
        if result.action.__class__.__name__ == "PlayCards"
    )
    discard = next(
        result.action
        for result in search.last_decision.results
        if isinstance(result.action, DiscardCards) and result.action != baseline
    )
    assert {slot.value for slot in discard.cards}.isdisjoint(
        slot.value for slot in play.cards
    )


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
