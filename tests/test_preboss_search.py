from __future__ import annotations

from copy import deepcopy

from balatro_ai_v2.actions import BuyShopCard, LeaveShop, iter_legal_actions
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.preboss_search import PublicPreBossSearchPolicy
from state_factory import item_card, playing_card, state


def _preboss_shop(*, boss_score: int = 2500):
    raw = state("SHOP", money=10)
    raw["deck"] = "RED"
    raw["stake"] = "GOLD"
    raw["ante_num"] = 3
    raw["round_num"] = 2
    raw["round"]["hands_left"] = 0
    raw["round"]["hands_played"] = 1
    raw["round"]["reroll_cost"] = 20
    raw["blinds"]["big"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(
        name="The Wall",
        effect="Extra large blind",
        score=boss_score,
        status="UPCOMING",
    )
    raw["vouchers"] = {"cards": [], "count": 0, "highlighted_limit": 1, "limit": 1}
    raw["packs"] = {"cards": [], "count": 0, "highlighted_limit": 1, "limit": 2}
    raw["shop"]["cards"] = [item_card("j_joker", card_id=20, kind="JOKER", buy=2)]
    raw["shop"]["count"] = 1
    raw["jokers"]["cards"] = [
        item_card("j_mystic_summit", card_id=40 + index, kind="JOKER")
        for index in range(4)
    ]
    raw["jokers"]["count"] = 4
    raw["jokers"]["limit"] = 5
    raw["cards"]["cards"] = [
        playing_card(f"{('S', 'H', 'D', 'C')[index % 4]}_A", card_id=100 + index, hidden=True)
        for index in range(20)
    ]
    raw["cards"]["count"] = 20
    raw["hands"]["Five of a Kind"] = {
        "chips": 120,
        "example": [],
        "level": 1,
        "mult": 12,
        "order": 1,
        "played": 0,
        "played_this_round": 0,
    }
    raw["poker_hand_iteration_order"].append("Five of a Kind")
    return raw


def test_preboss_search_buys_only_for_a_shared_particle_survival_gain() -> None:
    observation = to_public_observation(_preboss_shop())
    policy = PublicPreBossSearchPolicy(particles=8, minimum_particle_gain=2)

    action = policy.choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, BuyShopCard)
    assert policy.last_decision is not None
    leave, buy = policy.last_decision.results
    assert leave.wins == 0
    assert buy.wins == 8
    assert policy.last_decision.selected == action


def test_preboss_search_returns_control_to_baseline_after_one_shop_intervention() -> None:
    observation = to_public_observation(_preboss_shop())
    policy = PublicPreBossSearchPolicy(particles=4, minimum_particle_gain=2)
    first = policy.choose_action(observation, lambda: iter_legal_actions(observation), ())
    assert isinstance(first, BuyShopCard)

    after_raw = _preboss_shop()
    after_raw["shop"]["cards"] = [
        item_card("j_blue_joker", card_id=21, kind="JOKER", buy=2)
    ]
    after_raw["shop"]["count"] = 1
    after = to_public_observation(after_raw)
    second = policy.choose_action(after, lambda: iter_legal_actions(after), ())

    assert isinstance(second, BuyShopCard)


def test_preboss_search_hidden_twins_share_tapes_statistics_and_action() -> None:
    left = _preboss_shop()
    right = deepcopy(left)
    right["seed"] = "DIFFERENT-PRIVATE-SEED"
    right["cards"]["cards"].reverse()
    for card in right["cards"]["cards"]:
        card["id"] += 10_000
    left_observation = to_public_observation(left)
    right_observation = to_public_observation(right)
    left_policy = PublicPreBossSearchPolicy(particles=8)
    right_policy = PublicPreBossSearchPolicy(particles=8)

    left_action = left_policy.choose_action(
        left_observation,
        lambda: iter_legal_actions(left_observation),
        (),
    )
    right_action = right_policy.choose_action(
        right_observation,
        lambda: iter_legal_actions(right_observation),
        (),
    )

    assert left_observation == right_observation
    assert left_action == right_action
    assert left_policy.last_decision == right_policy.last_decision


def test_preboss_search_leaves_when_no_particle_gain_clears_the_margin() -> None:
    observation = to_public_observation(_preboss_shop(boss_score=4000))
    policy = PublicPreBossSearchPolicy(particles=8, minimum_particle_gain=2)

    action = policy.choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, LeaveShop)
    assert policy.last_decision is not None
    assert all(result.wins == 0 for result in policy.last_decision.results)


def test_preboss_search_fails_closed_outside_the_scoring_envelope() -> None:
    policy = PublicPreBossSearchPolicy(particles=4)
    supported = to_public_observation(_preboss_shop())
    policy.choose_action(supported, lambda: iter_legal_actions(supported), ())
    assert policy.last_decision is not None

    raw = _preboss_shop()
    raw["jokers"]["cards"][0] = item_card(
        "j_blueprint",
        card_id=40,
        kind="JOKER",
    )
    observation = to_public_observation(raw)

    action = policy.choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, LeaveShop)
    assert policy.last_decision is None


def test_preboss_search_fails_closed_with_a_held_consumable() -> None:
    raw = _preboss_shop()
    raw["consumables"]["cards"] = [
        item_card("c_strength", card_id=80, kind="TAROT")
    ]
    raw["consumables"]["count"] = 1
    observation = to_public_observation(raw)
    policy = PublicPreBossSearchPolicy(particles=4)

    policy.choose_action(observation, lambda: iter_legal_actions(observation), ())

    assert policy.last_decision is None
