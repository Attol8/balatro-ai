from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

from balatro_ai_v2.actions import (
    BuyPack,
    BuyShopCard,
    ChoosePackCard,
    ConsumableSlot,
    DiscardCards,
    HandSlot,
    JokerSlot,
    LeaveShop,
    PackOfferSlot,
    PlayCards,
    RerollShop,
    SellJoker,
    SkipPack,
    UseConsumable,
    action_to_data,
    is_legal,
    iter_legal_actions,
)
from balatro_ai_v2.baselines import (
    DeterministicCoveragePolicy,
    DeterministicRandomPolicy,
    GreedyImmediatePolicy,
    PublicBeliefTacticalPolicy,
    PublicStrategicPolicy,
    _classify,
    _play_score,
    build_public_baseline,
)
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.balatrobot.runner import PublicHistoryStep
from balatro_ai_v2.public_state import (
    DeckCardCount,
    HandStat,
    PublicItem,
    PublicObservation,
    VisiblePlayingCard,
)
from state_factory import item_card, playing_card, state


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


def test_random_and_greedy_baselines_are_identical_for_hidden_twins() -> None:
    left = state("SELECTING_HAND", seed="PRIVATE-A")
    right = deepcopy(left)
    right["seed"] = "PRIVATE-B"
    right["cards"]["cards"].reverse()
    left_public = to_public_observation(left)
    right_public = to_public_observation(right)

    for policy in (
        DeterministicRandomPolicy("control-v1"),
        GreedyImmediatePolicy(),
        PublicStrategicPolicy(),
    ):
        left_action = policy.choose_action(left_public, lambda: iter_legal_actions(left_public), ())
        right_action = policy.choose_action(right_public, lambda: iter_legal_actions(right_public), ())
        assert action_to_data(left_action) == action_to_data(right_action)
        assert is_legal(left_public, left_action)


def test_public_belief_tactical_policy_is_identical_for_hidden_twins() -> None:
    left = state("SELECTING_HAND", seed="PRIVATE-A")
    right = deepcopy(left)
    right["seed"] = "PRIVATE-B"
    right["cards"]["cards"].reverse()
    for card in right["cards"]["cards"]:
        card["id"] += 5000
    left_public = to_public_observation(left)
    right_public = to_public_observation(right)
    policy = PublicBeliefTacticalPolicy()

    left_action = policy.choose_action(left_public, lambda: iter_legal_actions(left_public), ())
    right_action = policy.choose_action(right_public, lambda: iter_legal_actions(right_public), ())

    assert action_to_data(left_action) == action_to_data(right_action)
    assert is_legal(left_public, left_action)


def test_public_belief_tactical_policy_discards_low_card_for_better_public_draw() -> None:
    raw = state("SELECTING_HAND")
    raw["hand"]["cards"][2] = playing_card("D_2", card_id=6)
    observation = to_public_observation(raw)

    action = PublicBeliefTacticalPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, DiscardCards)
    assert len(action.cards) == 1


def test_public_belief_tactical_policy_plays_when_discards_are_unavailable() -> None:
    raw = state("SELECTING_HAND")
    raw["round"]["discards_left"] = 0
    observation = to_public_observation(raw)

    action = PublicBeliefTacticalPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert action_to_data(action)["type"] == "play_cards"


def test_public_belief_tactical_policy_falls_back_for_face_down_hand() -> None:
    raw = state("SELECTING_HAND")
    raw["hand"]["cards"][0] = playing_card("S_A", card_id=100, hidden=True)
    observation = to_public_observation(raw)

    action = PublicBeliefTacticalPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert action_to_data(action)["type"] == "play_cards"


def test_public_belief_tactical_policy_falls_back_for_invalid_counts() -> None:
    observation = to_public_observation(state("SELECTING_HAND"))
    malformed = replace(observation, draw_count=observation.draw_count + 1)

    action = PublicBeliefTacticalPolicy().choose_action(
        malformed,
        lambda: iter_legal_actions(malformed),
        (),
    )

    assert action_to_data(action)["type"] == "play_cards"


def test_public_belief_tactical_policy_falls_back_above_branch_budget() -> None:
    observation = to_public_observation(state("SELECTING_HAND"))
    large_hand = (observation.hand * 3)[:8]
    large_deck = tuple(
        DeckCardCount(VisiblePlayingCard(str(index), "S", effect_text=str(index)), 1)
        for index in range(65)
    )
    oversized = replace(
        observation,
        hand=large_hand,
        remaining_deck=large_deck,
        draw_count=len(large_deck),
    )

    action = PublicBeliefTacticalPolicy().choose_action(
        oversized,
        lambda: iter_legal_actions(oversized),
        (),
    )

    assert action_to_data(action)["type"] == "play_cards"


def test_public_baseline_factory_rejects_unknown_policy() -> None:
    with pytest.raises(ValueError, match="unknown public baseline"):
        build_public_baseline("private-clone", "seed")


def test_greedy_baseline_leaves_shop_without_private_economy_model() -> None:
    shop = to_public_observation(state("SHOP", money=10))

    action = GreedyImmediatePolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert isinstance(action, LeaveShop)


def test_strategic_baseline_buys_an_early_public_joker() -> None:
    shop = to_public_observation(state("SHOP", money=10))

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert isinstance(action, BuyShopCard)
    assert action.card.value == 0


def test_strategic_tactical_action_is_in_the_canonical_legal_set() -> None:
    raw = state("SELECTING_HAND")
    raw["hand"]["cards"].extend(
        playing_card(key, card_id=index)
        for index, key in enumerate(("S_A", "H_K", "D_Q", "C_J", "S_9"), 40)
    )
    raw["hand"]["count"] = 8
    observation = to_public_observation(raw)
    legal = tuple(iter_legal_actions(observation))

    action = PublicStrategicPolicy().choose_action(observation, lambda: iter(legal), ())

    assert action_to_data(action) in [action_to_data(candidate) for candidate in legal]
    assert action_to_data(action)["cards"] == sorted(action_to_data(action)["cards"])


def test_strategic_baseline_preserves_visible_interest_floor() -> None:
    raw = state("SHOP", money=8)
    raw["ante_num"] = 4
    raw["shop"]["cards"][0]["cost"]["buy"] = 4
    shop = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert isinstance(action, LeaveShop)


def test_strategic_baseline_prefers_a_great_joker_pack_pick() -> None:
    raw = state("BUFFOON_PACK")
    raw["pack"]["cards"] = [
        item_card("c_mercury", card_id=30, kind="PLANET"),
        item_card("j_blueprint", card_id=31, kind="JOKER"),
    ]
    raw["pack"]["count"] = 2
    pack = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        pack,
        lambda: iter_legal_actions(pack),
        (),
    )

    assert isinstance(action, ChoosePackCard)
    assert action.card.value == 1


def _joker_shop(
    *,
    ante: int = 6,
    money: int = 20,
    offer_buy: int = 4,
    joker_cards: list[dict[str, object]] | None = None,
) -> PublicObservation:
    raw = state("SHOP", money=money)
    raw["ante_num"] = ante
    raw["shop"]["cards"] = [item_card("j_order", card_id=20, kind="JOKER", buy=offer_buy)]
    raw["shop"]["count"] = 1
    cards = (
        joker_cards
        if joker_cards is not None
        else [item_card(f"j_weak_{index}", card_id=40 + index, kind="JOKER") for index in range(5)]
    )
    raw["jokers"]["cards"] = cards
    raw["jokers"]["count"] = len(cards)
    return to_public_observation(raw)


def test_strategic_baseline_sells_late_economy_joker_for_material_upgrade() -> None:
    shop = _joker_shop(
        money=12,
        joker_cards=[
            item_card("j_trousers", card_id=40, kind="JOKER", sell=4),
            item_card("j_business", card_id=41, kind="JOKER", sell=2),
            item_card("j_blue_joker", card_id=42, kind="JOKER", sell=3),
            item_card("j_banner", card_id=43, kind="JOKER", sell=2),
            item_card("j_runner", card_id=44, kind="JOKER", sell=3),
        ],
    )

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert action == SellJoker(JokerSlot(1))
    assert is_legal(shop, action)


def test_strategic_baseline_buys_replacement_after_slot_is_open() -> None:
    shop = _joker_shop(
        money=14,
        joker_cards=[
            item_card("j_trousers", card_id=40, kind="JOKER"),
            item_card("j_blue_joker", card_id=42, kind="JOKER"),
            item_card("j_banner", card_id=43, kind="JOKER"),
            item_card("j_runner", card_id=44, kind="JOKER"),
        ],
    )

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert isinstance(action, BuyShopCard)
    assert action.card.value == 0


def test_strategic_baseline_never_sells_an_eternal_joker() -> None:
    jokers = [item_card(f"j_eternal_{index}", card_id=40 + index, kind="JOKER") for index in range(5)]
    for item in jokers:
        item["modifier"] = {"eternal": True}
    shop = _joker_shop(joker_cards=jokers)

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert not isinstance(action, SellJoker)


def test_strategic_baseline_does_not_churn_early_jokers() -> None:
    shop = _joker_shop(ante=5)

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert not isinstance(action, SellJoker)


def test_strategic_baseline_makes_at_most_one_replacement() -> None:
    shop = _joker_shop(ante=8)
    history = (PublicHistoryStep(shop, SellJoker(JokerSlot(0)), shop),)

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        history,
    )

    assert not isinstance(action, SellJoker)


def test_strategic_baseline_never_sells_a_negative_joker() -> None:
    negative = item_card("j_weak", card_id=40, kind="JOKER")
    negative["modifier"] = {"edition": "NEGATIVE"}
    eternals = [item_card(f"j_eternal_{index}", card_id=41 + index, kind="JOKER") for index in range(4)]
    for item in eternals:
        item["modifier"] = {"eternal": True}
    shop = _joker_shop(joker_cards=[negative, *eternals])

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert not isinstance(action, SellJoker)


def test_strategic_baseline_does_not_orphan_replacement_at_shop_budget() -> None:
    shop = _joker_shop(money=12)
    history = tuple(PublicHistoryStep(shop, RerollShop(), shop) for _ in range(5))

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        history,
    )

    assert not isinstance(action, SellJoker)


def test_strategic_baseline_preserves_interest_floor_before_replacement() -> None:
    shop = _joker_shop(
        money=10,
        offer_buy=5,
        joker_cards=[
            item_card(f"j_weak_{index}", card_id=40 + index, kind="JOKER", sell=2)
            for index in range(5)
        ],
    )

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert not isinstance(action, SellJoker)


def test_strategic_baseline_keeps_pack_replacement_fail_closed() -> None:
    raw = state("BUFFOON_PACK")
    raw["pack"]["cards"] = [item_card("j_order", card_id=30, kind="JOKER")]
    raw["jokers"]["cards"] = [
        item_card(f"j_weak_{index}", card_id=40 + index, kind="JOKER") for index in range(5)
    ]
    raw["jokers"]["count"] = 5
    pack = to_public_observation(raw)

    legal = tuple(iter_legal_actions(pack))
    action = PublicStrategicPolicy().choose_action(pack, lambda: iter(legal), ())

    assert isinstance(action, SkipPack)
    assert not any(isinstance(candidate, SellJoker) for candidate in legal)


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


def test_public_score_excludes_unscored_pair_kickers() -> None:
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=tuple(
            VisiblePlayingCard(rank, suit)
            for rank, suit in zip(("A", "A", "K", "Q", "J"), "SHDCS")
        ),
        hand_stats=(HandStat("Pair", 1, 10, 2, 0, 0),),
    )
    stats = {hand.name: hand for hand in observation.hand_stats}

    pair_score = _play_score(observation, (HandSlot(0), HandSlot(1)), stats)[0]
    pair_with_kickers = _play_score(
        observation,
        tuple(HandSlot(index) for index in range(5)),
        stats,
    )[0]

    assert pair_with_kickers == pair_score


def test_public_score_applies_visible_hand_family_joker() -> None:
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(VisiblePlayingCard("A", "S"), VisiblePlayingCard("A", "H")),
        hand_stats=(HandStat("Pair", 1, 10, 2, 0, 0),),
    )
    stats = {hand.name: hand for hand in observation.hand_stats}
    selected = (HandSlot(0), HandSlot(1))
    without_joker = _play_score(observation, selected, stats)[0]
    with_duo = _play_score(
        replace(observation, jokers=(PublicItem("j_duo", "The Duo", "JOKER"),)),
        selected,
        stats,
    )[0]

    assert with_duo == without_joker * 2


def test_public_score_uses_action_dependent_runner_increment() -> None:
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=tuple(VisiblePlayingCard(rank, "S") for rank in ("2", "3", "4", "5", "6")),
        hand_stats=(HandStat("Straight Flush", 1, 100, 8, 0, 0),),
    )
    stats = {hand.name: hand for hand in observation.hand_stats}
    selected = tuple(HandSlot(index) for index in range(5))
    without_joker = _play_score(observation, selected, stats)[0]
    with_runner = _play_score(
        replace(observation, jokers=(PublicItem("j_runner", "Runner", "JOKER"),)),
        selected,
        stats,
    )[0]

    assert with_runner > without_joker


def test_strategic_policy_does_not_discard_green_joker_scaling() -> None:
    raw = state("SELECTING_HAND")
    raw["jokers"]["cards"] = [item_card("j_green_joker", card_id=30, kind="JOKER")]
    raw["jokers"]["count"] = 1
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, PlayCards)
