from __future__ import annotations

from copy import deepcopy

from balatro_ai_v2.actions import (
    BuyPack,
    ChoosePackCard,
    ConsumableSlot,
    LeaveShop,
    PackOfferSlot,
    RerollShop,
    SkipPack,
    UseConsumable,
    action_to_data,
    is_legal,
    iter_legal_actions,
)
from balatro_ai_v2.baselines import DeterministicCoveragePolicy, _classify
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.balatrobot.runner import PublicHistoryStep
from balatro_ai_v2.public_state import VisiblePlayingCard
from state_factory import item_card, state


def test_coverage_policy_is_identical_for_hidden_state_twins() -> None:
    left = state("SELECTING_HAND", seed="PRIVATE-A")
    right = deepcopy(left)
    right["seed"] = "PRIVATE-B"
    right["cards"]["cards"].reverse()
    for card in right["cards"]["cards"]:
        card["id"] += 1000
    left_public = to_public_observation(left)
    right_public = to_public_observation(right)
    policy = DeterministicCoveragePolicy("policy-seed")

    left_action = policy.choose_action(left_public, lambda: iter_legal_actions(left_public), ())
    right_action = policy.choose_action(right_public, lambda: iter_legal_actions(right_public), ())

    assert action_to_data(left_action) == action_to_data(right_action)
    assert is_legal(left_public, left_action)


def test_coverage_policy_leaves_shop_at_its_public_budget() -> None:
    observation = to_public_observation(state("SHOP"))
    policy = DeterministicCoveragePolicy(max_shop_actions=2)
    history = (
        PublicHistoryStep(observation, RerollShop(), observation),
        PublicHistoryStep(observation, RerollShop(), observation),
    )

    action = policy.choose_action(observation, lambda: iter_legal_actions(observation), history)

    assert isinstance(action, LeaveShop)


def test_shop_budget_survives_a_pack_excursion() -> None:
    shop = to_public_observation(state("SHOP"))
    pack = to_public_observation(state("BUFFOON_PACK"))
    policy = DeterministicCoveragePolicy(max_shop_actions=1)
    history = (
        PublicHistoryStep(shop, BuyPack(PackOfferSlot(0)), pack),
        PublicHistoryStep(pack, SkipPack(), shop),
    )

    action = policy.choose_action(shop, lambda: iter_legal_actions(shop), history)

    assert isinstance(action, LeaveShop)


def test_extended_coverage_rerolls_before_buying() -> None:
    shop = to_public_observation(state("SHOP", money=10))
    policy = DeterministicCoveragePolicy(coverage_mode="extended")

    action = policy.choose_action(shop, lambda: iter_legal_actions(shop), ())

    assert isinstance(action, RerollShop)


def test_extended_coverage_uses_held_planet() -> None:
    raw = state("SELECTING_HAND")
    raw["consumables"]["cards"] = [item_card("c_mercury", card_id=30, kind="PLANET")]
    raw["consumables"]["count"] = 1
    observation = to_public_observation(raw)
    policy = DeterministicCoveragePolicy(coverage_mode="extended")

    action = policy.choose_action(observation, lambda: iter_legal_actions(observation), ())

    assert action == UseConsumable(ConsumableSlot(0))


def test_explicit_pack_lanes_skip_or_pick_safe_visible_offer() -> None:
    pack = to_public_observation(state("BUFFOON_PACK"))

    skipped = DeterministicCoveragePolicy(pack_strategy="skip").choose_action(
        pack, lambda: iter_legal_actions(pack), ()
    )
    picked = DeterministicCoveragePolicy(pack_strategy="pick").choose_action(
        pack, lambda: iter_legal_actions(pack), ()
    )

    assert isinstance(skipped, SkipPack)
    assert isinstance(picked, ChoosePackCard)


def test_public_poker_classifier_covers_wheel_straight_and_full_house() -> None:
    wheel = tuple(VisiblePlayingCard(rank, suit) for rank, suit in zip(("A", "2", "3", "4", "5"), "SHCDS"))
    full_house = tuple(
        VisiblePlayingCard(rank, suit)
        for rank, suit in zip(("K", "K", "K", "2", "2"), "SHCDS")
    )

    assert _classify(wheel) == "Straight"
    assert _classify(full_house) == "Full House"
