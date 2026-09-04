from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from fractions import Fraction

import pytest

from balatro_ai_v2.actions import (
    BuyPack,
    BuyShopCard,
    BuyVoucher,
    CashOut,
    ChoosePackCard,
    ConsumableSlot,
    DiscardCards,
    HandSlot,
    JokerSlot,
    LeaveShop,
    PackOfferSlot,
    PlayCards,
    ReorderJokers,
    RerollShop,
    SelectBlind,
    SellConsumable,
    SellJoker,
    ShopSlot,
    SkipBlind,
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
    _best_play_with_score,
    _build_pace_play,
    _classify,
    _coverage_discard,
    _joker_is_scorer,
    _joker_value,
    _loyalty_remaining_from_history,
    _play_score,
    _persisted_shop_score_context,
    _shop_score_context,
    _with_history_derived_joker_runtime,
    build_public_baseline,
)
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.balatrobot.runner import PublicHistoryStep
from balatro_ai_v2.boss_rules import boss_rule
from balatro_ai_v2.build_strategy import BuildPlan
from balatro_ai_v2.public_state import (
    DeckCardCount,
    HandStat,
    HiddenHandCard,
    Phase,
    PublicItem,
    PublicJokerRuntime,
    PublicObservation,
    VisiblePlayingCard,
)
from balatro_ai_v2.policy import NoPublicProgressAction
from balatro_ai_v2.strategy_options import StrategyIntent
from balatro_ai_v2.public_scoring import score_play
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

    left_action = policy.choose_action(
        left_public, lambda: iter_legal_actions(left_public), ()
    )
    right_action = policy.choose_action(
        right_public, lambda: iter_legal_actions(right_public), ()
    )

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
        left_action = policy.choose_action(
            left_public, lambda: iter_legal_actions(left_public), ()
        )
        right_action = policy.choose_action(
            right_public, lambda: iter_legal_actions(right_public), ()
        )
        assert action_to_data(left_action) == action_to_data(right_action)
        assert is_legal(left_public, left_action)


@pytest.mark.parametrize(
    ("money", "kind", "tag_name", "expected_type"),
    [
        (20, "SMALL", "Economy Tag", SkipBlind),
        (19, "SMALL", "Economy Tag", SelectBlind),
        (40, "BIG", "Economy Tag", SelectBlind),
        (99, "SMALL", "Coupon Tag", SelectBlind),
    ],
)
def test_strategic_baseline_skips_only_guaranteed_small_economy_tag(
    money: int,
    kind: str,
    tag_name: str,
    expected_type: type[object],
) -> None:
    raw = state("BLIND_SELECT", money=money)
    if kind == "BIG":
        raw["blinds"]["small"]["status"] = "DEFEATED"
        raw["blinds"]["big"]["status"] = "SELECT"
        selected = raw["blinds"]["big"]
    else:
        selected = raw["blinds"]["small"]
    selected["tag_name"] = tag_name
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, expected_type)
    assert is_legal(observation, action)


def test_strategic_baseline_revalidates_an_intent_and_forks_distinctly() -> None:
    raw = state("BLIND_SELECT", money=10)
    raw["blinds"]["small"]["tag_name"] = "Coupon Tag"
    observation = to_public_observation(raw)
    policy = PublicStrategicPolicy()

    action = policy.choose_action_for_intent(
        observation,
        lambda: iter_legal_actions(observation),
        (),
        StrategyIntent.ECONOMY,
    )
    fork = policy.fork_for_rollout(StrategyIntent.ECONOMY)

    assert isinstance(action, SkipBlind)
    assert is_legal(observation, action)
    assert fork == policy
    assert fork is not policy


def test_strategic_baseline_names_an_empty_hand_as_no_public_progress() -> None:
    raw = state("SELECTING_HAND")
    raw["hand"]["cards"] = []
    raw["hand"]["count"] = 0
    raw["round"].update(hands_left=1, discards_left=0)
    observation = to_public_observation(raw)

    with pytest.raises(NoPublicProgressAction):
        PublicStrategicPolicy().choose_action(
            observation,
            lambda: iter_legal_actions(observation),
            (),
        )


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

    left_action = policy.choose_action(
        left_public, lambda: iter_legal_actions(left_public), ()
    )
    right_action = policy.choose_action(
        right_public, lambda: iter_legal_actions(right_public), ()
    )

    assert action_to_data(left_action) == action_to_data(right_action)
    assert is_legal(left_public, left_action)


def test_public_belief_tactical_policy_discards_low_card_for_better_public_draw() -> (
    None
):
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

    assert action != BuyShopCard(ShopSlot(0))


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


def test_strategic_policy_uses_a_legal_discard_when_no_play_is_proposed() -> None:
    observation = to_public_observation(state("SELECTING_HAND"))
    discards = tuple(
        action
        for action in iter_legal_actions(observation)
        if isinstance(action, DiscardCards)
    )
    assert discards

    action = PublicStrategicPolicy().choose_action(
        observation, lambda: iter(discards), ()
    )

    assert action == discards[0]
    assert is_legal(observation, action)


def test_strategic_policy_plays_a_weak_hand_that_already_clears() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["score"] = 1
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, PlayCards)


def test_strategic_policy_moves_additive_mult_before_main_xmult() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["score"] = 10_000
    raw["hand"]["cards"] = [
        playing_card("S_A", card_id=100),
        playing_card("H_A", card_id=101),
        playing_card("D_K", card_id=102),
    ]
    raw["hand"]["count"] = 3
    raw["hands"]["Pair"] = {
        "chips": 10,
        "example": [],
        "level": 1,
        "mult": 2,
        "order": 11,
        "played": 0,
        "played_this_round": 0,
    }
    raw["jokers"]["cards"] = [
        item_card("j_duo", card_id=200, kind="JOKER"),
        item_card("j_joker", card_id=201, kind="JOKER"),
    ]
    raw["jokers"]["count"] = 2
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert action == ReorderJokers((JokerSlot(1), JokerSlot(0)))


def test_strategic_policy_reorders_blueprint_before_public_target() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["score"] = 10_000
    raw["jokers"]["cards"] = [
        item_card("j_joker", card_id=200, kind="JOKER"),
        item_card("j_blueprint", card_id=201, kind="JOKER"),
    ]
    raw["jokers"]["count"] = 2
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert action == ReorderJokers((JokerSlot(1), JokerSlot(0)))


def test_strategic_policy_uses_late_discard_after_old_two_discard_cap() -> None:
    raw = state("SELECTING_HAND")
    raw["round"].update(hands_left=1, discards_left=2, discards_used=2)
    raw["blinds"]["small"]["score"] = 10_000
    raw["hand"]["cards"] = [
        playing_card(key, card_id=100 + index)
        for index, key in enumerate(
            ("S_A", "H_2", "D_3", "C_4", "S_5", "H_K", "D_Q", "C_9")
        )
    ]
    raw["hand"]["count"] = 8
    raw["hands"]["Straight"] = {
        "chips": 30,
        "example": [],
        "level": 1,
        "mult": 4,
        "order": 5,
        "played": 0,
        "played_this_round": 0,
    }
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, DiscardCards)
    assert {slot.value for slot in action.cards}.isdisjoint({0, 1, 2, 3, 4})


def test_strategic_policy_preserves_made_committed_pair_over_larger_fragment() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["score"] = 10_000
    raw["hand"]["cards"] = [
        playing_card(key, card_id=100 + index)
        for index, key in enumerate(
            ("S_A", "S_9", "D_8", "H_7", "S_5", "D_3", "H_2", "C_2")
        )
    ]
    raw["hand"]["count"] = 8
    raw["hands"]["Pair"] = {
        "chips": 10,
        "example": [],
        "level": 1,
        "mult": 2,
        "order": 11,
        "played": 0,
        "played_this_round": 0,
    }
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, DiscardCards)
    assert len(action.cards) == 5
    assert {slot.value for slot in action.cards}.isdisjoint({6, 7})


def test_strategic_policy_retains_fragment_fallback_when_committed_pair_is_unmade() -> (
    None
):
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["score"] = 10_000
    raw["hand"]["cards"] = [
        playing_card(key, card_id=100 + index)
        for index, key in enumerate(
            ("S_A", "S_9", "D_8", "H_7", "S_5", "D_3", "H_2", "C_K")
        )
    ]
    raw["hand"]["count"] = 8
    raw["hands"]["Pair"] = {
        "chips": 10,
        "example": [],
        "level": 1,
        "mult": 2,
        "order": 11,
        "played": 0,
        "played_this_round": 0,
    }
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, DiscardCards)
    assert tuple(slot.value for slot in action.cards) == (0, 5, 6, 7)


def test_strategic_policy_prioritizes_survival_over_discard_sensitive_joker_on_last_hand() -> (
    None
):
    raw = state("SELECTING_HAND")
    raw["round"].update(hands_left=1, discards_left=2, discards_used=2)
    raw["blinds"]["small"]["score"] = 10_000
    raw["jokers"]["cards"] = [item_card("j_green_joker", card_id=300, kind="JOKER")]
    raw["jokers"]["count"] = 1
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, DiscardCards)


def test_strategic_policy_discards_anonymous_fish_slots_before_last_play() -> None:
    raw = state("SELECTING_HAND")
    _current_boss(raw, "The Fish")
    raw["round"].update(hands_left=1, discards_left=2, discards_used=2)
    raw["blinds"]["boss"]["score"] = 10_000
    for card in raw["hand"]["cards"][1:]:
        card["state"] = {"hidden": True}
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, DiscardCards)
    assert action in iter_legal_actions(observation)
    assert any(
        isinstance(observation.hand[slot.value], HiddenHandCard)
        for slot in action.cards
    )


def test_strategic_policy_discards_hidden_house_opening_before_playing() -> None:
    raw = state("SELECTING_HAND")
    _current_boss(raw, "The House")
    raw["blinds"]["boss"]["score"] = 10_000
    for card in raw["hand"]["cards"]:
        card["state"] = {"hidden": True}
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, DiscardCards)
    assert len(action.cards) == min(
        5, observation.selection_limit, len(observation.hand)
    )
    assert all(
        isinstance(observation.hand[slot.value], HiddenHandCard)
        for slot in action.cards
    )


@pytest.mark.parametrize("boss_name", ["The Fish", "The Mark", "The Wheel"])
def test_strategic_policy_cycles_hidden_cards_for_other_face_down_bosses(
    boss_name: str,
) -> None:
    raw = state("SELECTING_HAND")
    _current_boss(raw, boss_name)
    raw["blinds"]["boss"]["score"] = 10_000
    raw["hand"]["cards"][0]["state"] = {"hidden": True}
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert action == DiscardCards((HandSlot(0),))


def test_strategic_policy_cannot_cycle_hidden_boss_card_without_a_discard() -> None:
    raw = state("SELECTING_HAND")
    _current_boss(raw, "The Wheel")
    raw["blinds"]["boss"]["score"] = 10_000
    raw["round"]["discards_left"] = 0
    raw["hand"]["cards"][0]["state"] = {"hidden": True}
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, PlayCards)


def test_strategic_policy_does_not_cycle_hidden_slots_outside_face_down_boss() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["score"] = 10_000
    for card in raw["hand"]["cards"]:
        card["state"] = {"hidden": True}
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, PlayCards)


def test_strategic_policy_plays_committed_hand_when_it_meets_clear_pace() -> None:
    raw = state("SELECTING_HAND")
    raw["hand"]["cards"] = [
        playing_card("S_2", card_id=10),
        playing_card("H_2", card_id=11),
        playing_card("D_3", card_id=12),
        playing_card("C_4", card_id=13),
        playing_card("S_5", card_id=14),
        playing_card("H_6", card_id=15),
    ]
    raw["hand"]["count"] = 6
    raw["hands"] = {
        "High Card": {
            "chips": 5,
            "level": 1,
            "mult": 1,
            "played": 0,
            "played_this_round": 0,
        },
        "Pair": {
            "chips": 40,
            "level": 1,
            "mult": 2,
            "played": 0,
            "played_this_round": 0,
        },
        "Straight": {
            "chips": 30,
            "level": 1,
            "mult": 4,
            "played": 0,
            "played_this_round": 0,
        },
    }
    raw["blinds"]["small"]["score"] = 300
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, PlayCards)
    assert (
        _classify(tuple(observation.hand[slot.value] for slot in action.cards))
        == "Pair"
    )


@pytest.mark.parametrize(
    ("primary_hand", "card_keys", "target_score", "expected_hand"),
    [
        ("Pair", ("S_A", "H_A", "D_K", "C_K", "S_4", "H_3"), 100, "Two Pair"),
        (
            "Two Pair",
            ("S_A", "H_A", "D_A", "C_K", "S_K", "H_3"),
            200,
            "Full House",
        ),
    ],
)
def test_build_pace_accepts_stronger_hands_containing_primary_family(
    primary_hand: str,
    card_keys: tuple[str, ...],
    target_score: int,
    expected_hand: str,
) -> None:
    raw = state("SELECTING_HAND")
    raw["hand"]["cards"] = [
        playing_card(key, card_id=100 + index) for index, key in enumerate(card_keys)
    ]
    raw["hand"]["count"] = len(card_keys)
    raw["blinds"]["small"]["score"] = 300
    observation = to_public_observation(raw)
    build = BuildPlan(primary_hand, None, 1, 1, frozenset())

    action = _build_pace_play(
        observation,
        list(iter_legal_actions(observation)),
        None,
        build,
        target_score,
    )

    assert isinstance(action, PlayCards)
    assert (
        _classify(tuple(observation.hand[slot.value] for slot in action.cards))
        == expected_hand
    )


def test_build_pace_preserves_adequate_exact_primary_before_containing_hand() -> None:
    raw = state("SELECTING_HAND")
    raw["hand"]["cards"] = [
        playing_card(key, card_id=100 + index)
        for index, key in enumerate(("S_A", "H_A", "D_A", "C_K", "S_K", "H_3"))
    ]
    raw["hand"]["count"] = 6
    observation = to_public_observation(raw)

    action = _build_pace_play(
        observation,
        list(iter_legal_actions(observation)),
        None,
        BuildPlan("Two Pair", None, 1, 1, frozenset()),
        100,
    )

    assert isinstance(action, PlayCards)
    assert (
        _classify(tuple(observation.hand[slot.value] for slot in action.cards))
        == "Two Pair"
    )


def test_build_pace_rejects_incompatible_stronger_hand() -> None:
    raw = state("SELECTING_HAND")
    raw["hand"]["cards"] = [
        playing_card(key, card_id=100 + index)
        for index, key in enumerate(("S_A", "H_A", "D_K", "C_K", "S_4", "H_3"))
    ]
    raw["hand"]["count"] = 6
    raw["blinds"]["small"]["score"] = 100
    observation = to_public_observation(raw)

    action = _build_pace_play(
        observation,
        list(iter_legal_actions(observation)),
        None,
        BuildPlan("Flush", None, 1, 1, frozenset()),
        100,
    )

    assert action is None


def test_build_pace_preserves_boss_play_eligibility() -> None:
    raw = state("SELECTING_HAND")
    raw["hand"]["cards"] = [
        playing_card(key, card_id=100 + index)
        for index, key in enumerate(("S_A", "H_A", "D_K", "C_K"))
    ]
    raw["hand"]["count"] = 4
    raw["blinds"]["small"]["score"] = 100
    observation = to_public_observation(raw)
    psychic = boss_rule("The Psychic")
    assert psychic is not None

    action = _build_pace_play(
        observation,
        list(iter_legal_actions(observation)),
        psychic,
        BuildPlan("Pair", None, 1, 1, frozenset()),
        100,
    )

    assert action is None


def _current_boss(raw: dict[str, object], name: str) -> None:
    blinds = raw["blinds"]
    assert isinstance(blinds, dict)
    blinds["small"]["status"] = "DEFEATED"
    blinds["big"]["status"] = "DEFEATED"
    blinds["boss"].update(name=name, effect=name, status="CURRENT")


def test_strategic_policy_selects_five_cards_for_the_psychic() -> None:
    raw = state("SELECTING_HAND")
    _current_boss(raw, "The Psychic")
    raw["hand"]["cards"].extend(
        [playing_card("D_9", card_id=90), playing_card("C_8", card_id=91)]
    )
    raw["hand"]["count"] = 5
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, PlayCards)
    assert len(action.cards) == 5


def test_strategic_policy_avoids_repeating_a_hand_for_the_eye() -> None:
    raw = state("SELECTING_HAND")
    _current_boss(raw, "The Eye")
    raw["round"]["discards_left"] = 0
    raw["hand"]["cards"] = [
        playing_card("S_A", card_id=90),
        playing_card("H_A", card_id=91),
        playing_card("D_K", card_id=92),
    ]
    raw["hand"]["count"] = 3
    raw["hands"]["Pair"] = {
        "chips": 10,
        "example": [],
        "level": 1,
        "mult": 2,
        "order": 11,
        "played": 1,
        "played_this_round": 1,
    }
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, PlayCards)
    selected = tuple(observation.hand[slot.value] for slot in action.cards)
    assert _classify(selected) != "Pair"


def test_strategic_policy_plays_off_build_hand_at_pace_for_the_eye() -> None:
    raw = state("SELECTING_HAND")
    _current_boss(raw, "The Eye")
    raw["blinds"]["boss"]["score"] = 60
    raw["hand"]["cards"] = [
        playing_card("S_Q", card_id=90),
        playing_card("H_J", card_id=91),
        playing_card("D_9", card_id=92),
    ]
    raw["hand"]["count"] = 3
    raw["hands"]["Pair"] = {
        "chips": 10,
        "example": [],
        "level": 1,
        "mult": 2,
        "order": 11,
        "played": 10,
        "played_this_round": 0,
    }
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, PlayCards)
    selected = tuple(observation.hand[slot.value] for slot in action.cards)
    assert _classify(selected) == "High Card"


def test_strategic_policy_stays_with_first_hand_family_for_the_mouth() -> None:
    raw = state("SELECTING_HAND")
    _current_boss(raw, "The Mouth")
    raw["round"]["discards_left"] = 0
    raw["hand"]["cards"] = [
        playing_card("S_A", card_id=90),
        playing_card("H_A", card_id=91),
        playing_card("D_K", card_id=92),
    ]
    raw["hand"]["count"] = 3
    raw["hands"]["High Card"]["played_this_round"] = 1
    raw["hands"]["Pair"] = {
        "chips": 10,
        "example": [],
        "level": 1,
        "mult": 2,
        "order": 11,
        "played": 0,
        "played_this_round": 0,
    }
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, PlayCards)
    selected = tuple(observation.hand[slot.value] for slot in action.cards)
    assert _classify(selected) == "High Card"


@pytest.mark.parametrize(
    ("boss_name", "discards_used", "expected_count"),
    [
        ("The Serpent", 1, 3),
        ("The Serpent", 0, 3),
        ("The Club", 1, 4),
    ],
)
def test_strategic_policy_caps_only_post_action_serpent_discards(
    boss_name: str,
    discards_used: int,
    expected_count: int,
) -> None:
    raw = state("SELECTING_HAND")
    _current_boss(raw, boss_name)
    raw["blinds"]["boss"]["score"] = 100_000
    raw["round"]["discards_used"] = discards_used
    raw["round"]["discards_left"] = 3 - discards_used
    raw["hand"]["cards"] = [
        playing_card(key, card_id=90 + index)
        for index, key in enumerate(
            ("S_A", "H_K", "D_J", "C_9", "S_7", "H_5", "D_3", "C_2")
        )
    ]
    raw["hand"]["count"] = 8
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, DiscardCards)
    assert len(action.cards) == expected_count


def test_ordinary_coverage_discard_preserves_five_card_limit() -> None:
    raw = state("SELECTING_HAND")
    raw["hand"]["cards"] = [
        playing_card(key, card_id=90 + index)
        for index, key in enumerate(
            ("S_A", "H_K", "D_J", "C_9", "S_7", "H_5", "D_3", "C_2")
        )
    ]
    raw["hand"]["count"] = 8
    observation = to_public_observation(raw)

    action = _coverage_discard(
        observation,
        PlayCards((HandSlot(0),)),
        "High Card",
    )

    assert action is not None
    assert len(action.cards) == 5


def test_post_action_serpent_discard_uses_fewer_than_three_when_only_two_are_free() -> (
    None
):
    raw = state("SELECTING_HAND")
    _current_boss(raw, "The Serpent")
    raw["blinds"]["boss"]["score"] = 100_000
    raw["round"]["discards_used"] = 1
    raw["round"]["discards_left"] = 2
    raw["hand"]["cards"] = [
        playing_card("S_A", card_id=90),
        playing_card("H_K", card_id=91),
        playing_card("D_2", card_id=92),
    ]
    raw["hand"]["count"] = 3
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, DiscardCards)
    assert len(action.cards) == 2


def test_post_action_serpent_cap_preserves_green_joker_discard_suppression() -> None:
    raw = state("SELECTING_HAND")
    _current_boss(raw, "The Serpent")
    raw["blinds"]["boss"]["score"] = 100_000
    raw["round"]["discards_used"] = 1
    raw["round"]["discards_left"] = 2
    raw["jokers"]["cards"] = [item_card("j_green_joker", card_id=300, kind="JOKER")]
    raw["jokers"]["count"] = 1
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, PlayCards)


def test_public_score_halves_only_the_hand_base_for_the_flint() -> None:
    raw = state("SELECTING_HAND")
    raw["hands"]["High Card"].update(chips=35, mult=4)
    ordinary = to_public_observation(raw)
    _current_boss(raw, "The Flint")
    flint = to_public_observation(raw)
    selected = (HandSlot(0),)
    ordinary_stats = {stat.name: stat for stat in ordinary.hand_stats}
    flint_stats = {stat.name: stat for stat in flint.hand_stats}

    assert _play_score(ordinary, selected, ordinary_stats)[0] == 180
    assert _play_score(flint, selected, flint_stats)[0] == 56


def test_play_score_cache_preserves_custom_hand_stat_mapping_keys() -> None:
    observation = to_public_observation(state("SELECTING_HAND"))
    selected = (HandSlot(0),)
    low = HandStat("High Card", 1, 1, 1, 0, 0)
    high = HandStat("Pair", 1, 1_000, 10, 0, 0)
    first = {"High Card": low, "Pair": high}
    swapped = {"High Card": high, "Pair": low}

    assert _play_score(observation, selected, first) == score_play(
        observation, selected, first
    )
    assert _play_score(observation, selected, swapped) == score_play(
        observation, selected, swapped
    )


def test_public_score_projects_the_arms_pre_score_level_reduction() -> None:
    raw = state("SELECTING_HAND")
    raw["hands"]["High Card"].update(chips=25, level=3, mult=3)
    _current_boss(raw, "The Arm")
    observation = to_public_observation(raw)
    stats = {stat.name: stat for stat in observation.hand_stats}

    score = _play_score(observation, (HandSlot(0),), stats)[0]

    # The Arm lowers level 3 to level 2 before the selected 10 scores.
    assert score == (15 + 10) * 2


def test_strategic_policy_fails_closed_on_unknown_current_boss() -> None:
    raw = state("SELECTING_HAND")
    _current_boss(raw, "Future Boss")
    observation = to_public_observation(raw)

    with pytest.raises(RuntimeError, match="unknown current boss blind"):
        PublicStrategicPolicy().choose_action(
            observation,
            lambda: iter_legal_actions(observation),
            (),
        )


def test_strategic_policy_sells_joker_that_maximizes_post_verdant_score() -> None:
    raw = state("SELECTING_HAND")
    _current_boss(raw, "Verdant Leaf")
    for card in raw["hand"]["cards"]:
        card["state"] = {"debuff": True}
    raw["jokers"]["cards"] = [
        item_card("j_joker", card_id=300, kind="JOKER", sell=1),
        item_card("j_cavendish", card_id=301, kind="JOKER", sell=4),
    ]
    raw["jokers"]["count"] = 2
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert action == SellJoker(JokerSlot(1))


def test_verdant_sale_preserves_last_hand_capacity_over_immediate_score() -> None:
    raw = state("SELECTING_HAND")
    _current_boss(raw, "Verdant Leaf")
    raw["round"].update(hands_left=4, discards_left=0)
    for card in raw["hand"]["cards"]:
        card["state"] = {"debuff": True}
    observation = replace(
        to_public_observation(raw),
        jokers=(
            PublicItem(
                "j_square",
                "Square Joker",
                "JOKER",
                sell_cost=2,
                runtime=PublicJokerRuntime(current_chips=5),
            ),
            PublicItem("j_acrobat", "Acrobat", "JOKER", sell_cost=2),
        ),
        joker_limit=2,
    )

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    # The next hand scores more after selling Acrobat, but keeping its final-
    # hand x3 produces more modeled capacity across all four hands.
    assert action == SellJoker(JokerSlot(0))


def test_strategic_policy_spends_luchador_on_current_boss() -> None:
    raw = state("SELECTING_HAND")
    _current_boss(raw, "The Head")
    raw["jokers"]["cards"] = [item_card("j_luchador", card_id=300, kind="JOKER")]
    raw["jokers"]["count"] = 1
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert action == SellJoker(JokerSlot(0))


def _late_pair_observation(hand_size: int):
    if hand_size < 9:
        raise ValueError("late-pair fixture requires at least nine cards")
    raw = state("SELECTING_HAND")
    ranks = ("2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q")[: hand_size - 2]
    raw["hand"]["cards"] = [
        playing_card(f"S_{rank}", card_id=index + 100)
        for index, rank in enumerate(ranks)
    ] + [
        playing_card("H_A", card_id=200),
        playing_card("D_A", card_id=201),
    ]
    raw["hand"]["count"] = hand_size
    raw["hand"]["limit"] = hand_size
    raw["jokers"]["cards"] = [
        item_card("j_duo", card_id=300, kind="JOKER"),
        item_card("j_half", card_id=301, kind="JOKER"),
        item_card("j_green_joker", card_id=302, kind="JOKER"),
    ]
    raw["jokers"]["count"] = 3
    return to_public_observation(raw)


@pytest.mark.parametrize("hand_size", (9, 10))
def test_strategic_policy_reaches_late_small_pair_beyond_old_action_prefix(
    hand_size: int,
) -> None:
    observation = _late_pair_observation(hand_size)
    legal = tuple(iter_legal_actions(observation))
    old_prefix = legal[:512]

    action = PublicStrategicPolicy().choose_action(observation, lambda: iter(legal), ())

    assert isinstance(action, PlayCards)
    assert action not in old_prefix
    assert (
        _classify(tuple(observation.hand[slot.value] for slot in action.cards))
        == "Pair"
    )
    assert len(action.cards) <= 3
    assert action in legal


def test_large_hand_best_play_does_not_omit_late_small_pair() -> None:
    observation = _late_pair_observation(13)

    action, hand_name, score = _best_play_with_score(observation, 0)

    assert hand_name == "Pair"
    assert len(action.cards) <= 3
    assert score > 44


def test_late_pair_reachability_preserves_hidden_twin_action_and_legality() -> None:
    left = _late_pair_observation(10)
    raw = state("SELECTING_HAND", seed="OTHER-PRIVATE-SEED")
    ranks = ("2", "3", "4", "5", "6", "7", "8", "9")
    raw["hand"]["cards"] = [
        playing_card(f"S_{rank}", card_id=index + 9_000)
        for index, rank in enumerate(ranks)
    ] + [
        playing_card("H_A", card_id=9_100),
        playing_card("D_A", card_id=9_101),
    ]
    raw["hand"]["count"] = 10
    raw["hand"]["limit"] = 10
    raw["jokers"]["cards"] = [
        item_card("j_duo", card_id=9_300, kind="JOKER"),
        item_card("j_half", card_id=9_301, kind="JOKER"),
        item_card("j_green_joker", card_id=9_302, kind="JOKER"),
    ]
    raw["jokers"]["count"] = 3
    raw["cards"]["cards"].reverse()
    right = to_public_observation(raw)
    policy = PublicStrategicPolicy()

    left_action = policy.choose_action(left, lambda: iter_legal_actions(left), ())
    right_action = policy.choose_action(right, lambda: iter_legal_actions(right), ())

    assert action_to_data(left_action) == action_to_data(right_action)
    assert is_legal(left, left_action)
    assert is_legal(right, right_action)


def test_strategic_baseline_preserves_visible_interest_floor() -> None:
    raw = state("SHOP", money=8)
    raw["ante_num"] = 4
    raw["shop"]["cards"][0]["cost"]["buy"] = 4
    raw["jokers"]["cards"] = [
        item_card(key, card_id=300 + index, kind="JOKER")
        for index, key in enumerate(("j_joker", "j_cavendish", "j_abstract", "j_sly"))
    ]
    raw["jokers"]["count"] = 4
    shop = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert isinstance(action, LeaveShop)


def test_strategic_baseline_prefers_modeled_blueprint_pack_pick() -> None:
    raw = state("BUFFOON_PACK")
    raw["pack"]["cards"] = [
        item_card("j_blueprint", card_id=30, kind="JOKER"),
        item_card("j_joker", card_id=31, kind="JOKER"),
    ]
    raw["pack"]["count"] = 2
    pack = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        pack,
        lambda: iter_legal_actions(pack),
        (),
    )

    assert isinstance(action, ChoosePackCard)
    assert action.card.value == 0


def test_strategic_baseline_uses_only_primary_build_planet() -> None:
    raw = state("SELECTING_HAND")
    raw["consumables"]["cards"] = [
        item_card("c_uranus", card_id=30, kind="PLANET"),
        item_card("c_mercury", card_id=31, kind="PLANET"),
    ]
    raw["consumables"]["count"] = 2
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert action == UseConsumable(ConsumableSlot(1))


def test_strategic_baseline_holds_off_build_planet() -> None:
    raw = state("SELECTING_HAND")
    raw["consumables"]["cards"] = [
        item_card("c_jupiter", card_id=30, kind="PLANET"),
    ]
    raw["consumables"]["count"] = 1
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert not isinstance(action, UseConsumable)


def test_strategic_baseline_buys_only_primary_build_planet() -> None:
    raw = state("SHOP", money=40)
    raw["ante_num"] = 4
    raw["shop"]["cards"] = [
        item_card("c_uranus", card_id=20, kind="PLANET", buy=3),
        item_card("c_mercury", card_id=21, kind="PLANET", buy=3),
    ]
    raw["shop"]["count"] = 2
    raw["vouchers"]["cards"] = []
    raw["vouchers"]["count"] = 0
    raw["packs"]["cards"] = []
    raw["packs"]["count"] = 0
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert action == BuyShopCard(ShopSlot(1))


@pytest.mark.parametrize(
    ("planet_key", "should_buy"),
    [
        ("c_mercury", True),
        ("c_uranus", False),
    ],
)
def test_only_primary_planet_may_break_interest_floor(
    planet_key: str,
    should_buy: bool,
) -> None:
    raw = state("SHOP", money=25)
    raw["ante_num"] = 4
    raw["shop"]["cards"] = [
        item_card(planet_key, card_id=20, kind="PLANET", buy=3),
    ]
    raw["shop"]["count"] = 1
    raw["vouchers"]["cards"] = []
    raw["vouchers"]["count"] = 0
    raw["packs"]["cards"] = []
    raw["packs"]["count"] = 0
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, BuyShopCard) is should_buy


def test_strategic_baseline_skips_off_build_planet_pack() -> None:
    raw = state("PLANET_PACK")
    raw["pack"]["cards"] = [
        item_card("c_jupiter", card_id=30, kind="PLANET"),
    ]
    raw["pack"]["count"] = 1
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, SkipPack)


def test_strategic_baseline_skips_non_scoring_buffoon_offer() -> None:
    raw = state("BUFFOON_PACK")
    raw["pack"]["cards"] = [
        item_card("j_credit_card", card_id=30, kind="JOKER"),
    ]
    raw["pack"]["count"] = 1
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, SkipPack)


def test_strategic_baseline_does_not_buy_contextless_standard_pack() -> None:
    raw = state("SHOP", money=20)
    raw["shop"]["cards"] = []
    raw["shop"]["count"] = 0
    raw["vouchers"]["cards"] = []
    raw["vouchers"]["count"] = 0
    raw["packs"]["cards"] = [
        item_card("p_standard_normal_1", card_id=60, kind="BOOSTER", buy=4),
    ]
    raw["packs"]["count"] = 1
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert not isinstance(action, BuyPack)


@pytest.mark.parametrize(
    ("voucher_key", "expected_type"),
    [("v_tarot_merchant", LeaveShop), ("v_planet_merchant", BuyVoucher)],
)
def test_voucher_value_requires_a_supported_downstream_affordance(
    voucher_key: str,
    expected_type: type[object],
) -> None:
    raw = state("SHOP", money=50)
    raw["ante_num"] = 4
    raw["round"]["reroll_cost"] = 100
    raw["shop"]["cards"] = []
    raw["shop"]["count"] = 0
    raw["vouchers"]["cards"] = [
        item_card(voucher_key, card_id=50, kind="VOUCHER", buy=10),
    ]
    raw["vouchers"]["count"] = 1
    raw["packs"]["cards"] = []
    raw["packs"]["count"] = 0
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, expected_type)


def test_strategic_baseline_prefers_committed_planet_to_unopened_pack() -> None:
    raw = state("SHOP", money=40)
    raw["ante_num"] = 4
    raw["shop"]["cards"] = [
        item_card("c_mercury", card_id=20, kind="PLANET", buy=3),
    ]
    raw["shop"]["count"] = 1
    raw["vouchers"]["cards"] = []
    raw["vouchers"]["count"] = 0
    raw["packs"]["cards"] = [
        item_card("p_celestial_normal_1", card_id=60, kind="BOOSTER", buy=4),
    ]
    raw["packs"]["count"] = 1
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert action == BuyShopCard(ShopSlot(0))


@pytest.mark.parametrize(
    ("money", "expected_type"),
    [(16, BuyPack), (15, LeaveShop)],
)
def test_celestial_pack_preserves_twelve_dollar_reserve(
    money: int,
    expected_type: type[object],
) -> None:
    raw = state("SHOP", money=money)
    raw["ante_num"] = 4
    raw["shop"]["cards"] = []
    raw["shop"]["count"] = 0
    raw["vouchers"]["cards"] = []
    raw["vouchers"]["count"] = 0
    raw["packs"]["cards"] = [
        item_card("p_celestial_normal_1", card_id=60, kind="BOOSTER", buy=4),
    ]
    raw["packs"]["count"] = 1
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, expected_type)


def test_joker_value_uses_typed_roles_and_fails_closed_for_unknown_keys() -> None:
    assert _joker_value(PublicItem("j_cavendish", "Cavendish", "JOKER")) > _joker_value(
        PublicItem("j_credit_card", "Credit Card", "JOKER")
    )
    assert _joker_value(PublicItem("j_blueprint", "Blueprint", "JOKER")) > 0
    assert _joker_value(PublicItem("j_drunkard", "Drunkard", "JOKER")) == 55
    assert _joker_value(PublicItem("j_credit_card", "Credit Card", "JOKER")) == 0
    assert _joker_value(PublicItem("j_future", "Future", "JOKER")) == 0
    assert _joker_value(PublicItem("j_riff_raff", "Riff-Raff", "JOKER")) == 0


@pytest.mark.parametrize("key", ["j_fortune_teller", "j_idol"])
def test_unimplemented_semantic_scorer_has_zero_phase1_value(key: str) -> None:
    assert _joker_value(PublicItem(key, key, "JOKER")) == 0


@pytest.mark.parametrize("key", ["j_blueprint", "j_brainstorm", "j_hiker"])
def test_already_modeled_semantic_scorer_has_phase1_value(key: str) -> None:
    assert _joker_value(PublicItem(key, key, "JOKER")) > 0


def test_fresh_flash_card_is_supported_without_fabricating_mult() -> None:
    flash = PublicItem("j_flash", "Flash Card", "JOKER")

    assert _joker_value(flash) > 0
    assert _single_card_score_with_jokers((flash,)) == _single_card_score_with_jokers(
        ()
    )


def test_runtime_backed_joker_requires_visible_runtime_value() -> None:
    unsupported = PublicItem("j_hologram", "Hologram", "JOKER")
    supported = replace(
        unsupported,
        runtime=PublicJokerRuntime(current_x_mult=1.0),
    )

    assert _joker_value(unsupported) == 0
    assert _joker_value(supported) > 0


def test_todo_list_target_is_preferred_only_when_it_also_clears() -> None:
    raw = state("SELECTING_HAND")
    raw["hand"]["cards"] = [
        playing_card("S_2", card_id=10),
        playing_card("H_2", card_id=11),
        playing_card("D_3", card_id=12),
        playing_card("C_4", card_id=13),
        playing_card("S_5", card_id=14),
        playing_card("H_6", card_id=15),
    ]
    raw["hand"]["count"] = 6
    raw["hands"] = {
        "High Card": {
            "chips": 5,
            "level": 1,
            "mult": 1,
            "played": 0,
            "played_this_round": 0,
        },
        "Pair": {
            "chips": 10,
            "level": 1,
            "mult": 2,
            "played": 0,
            "played_this_round": 0,
        },
        "Straight": {
            "chips": 30,
            "level": 1,
            "mult": 4,
            "played": 0,
            "played_this_round": 0,
        },
    }
    raw["blinds"]["small"]["score"] = 20
    raw["jokers"]["cards"] = [
        item_card(
            "j_todo_list",
            card_id=30,
            kind="JOKER",
            ability={"poker_hand": "Pair"},
        ),
    ]
    raw["jokers"]["count"] = 1
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, PlayCards)
    assert (
        _classify(tuple(observation.hand[slot.value] for slot in action.cards))
        == "Pair"
    )


@pytest.mark.parametrize("key", ["j_green_joker", "j_ride_the_bus", "j_red_card"])
def test_known_initial_scaler_offer_is_supported_without_runtime(key: str) -> None:
    assert _joker_value(PublicItem(key, key, "JOKER")) > 0


@pytest.mark.parametrize("key", ["j_golden", "j_chaos", "j_rough_gem"])
def test_deterministic_economy_offer_is_valued_but_not_a_scorer(key: str) -> None:
    item = PublicItem(key, key, "JOKER")

    assert _joker_value(item) >= 45
    assert not _joker_is_scorer(item)


@pytest.mark.parametrize(
    "key",
    [
        "j_green_joker",
        "j_ride_the_bus",
        "j_red_card",
        "j_golden",
        "j_chaos",
        "j_rough_gem",
    ],
)
def test_strategic_policy_buys_public_complete_joker_offer(key: str) -> None:
    raw = state("SHOP", money=10)
    raw["shop"]["cards"] = [item_card(key, card_id=20, kind="JOKER", buy=4)]
    raw["shop"]["count"] = 1
    raw["vouchers"]["cards"] = []
    raw["vouchers"]["count"] = 0
    raw["packs"]["cards"] = []
    raw["packs"]["count"] = 0
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert action == BuyShopCard(ShopSlot(0))


def test_shop_prefers_offer_that_closes_visible_boss_survival_gap() -> None:
    raw = state("SHOP", money=20)
    raw["round_num"] = 2
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["big"]["status"] = "DEFEATED"
    raw["blinds"]["boss"]["name"] = "The Wall"
    raw["blinds"]["boss"]["score"] = 700
    raw["shop"]["cards"] = [
        item_card("j_sly", card_id=20, kind="JOKER", buy=4),
        item_card("j_joker", card_id=21, kind="JOKER", buy=4),
    ]
    raw["shop"]["count"] = 2
    raw["vouchers"]["cards"] = []
    raw["vouchers"]["count"] = 0
    raw["packs"]["cards"] = []
    raw["packs"]["count"] = 0
    shop = to_public_observation(raw)
    played_raw = state("SELECTING_HAND")
    played_raw["round_num"] = 2
    played_raw["blinds"]["small"]["status"] = "DEFEATED"
    played_raw["blinds"]["big"]["status"] = "CURRENT"
    played_raw["blinds"]["boss"]["name"] = "The Wall"
    played = replace(
        to_public_observation(played_raw),
        hand=(
            VisiblePlayingCard("A", "S"),
            VisiblePlayingCard("A", "H"),
            VisiblePlayingCard("7", "C"),
        ),
        hand_stats=(
            HandStat("High Card", 1, 5, 1, 0, 0),
            HandStat("Pair", 1, 10, 2, 0, 0),
        ),
    )
    shop = replace(shop, hand_stats=played.hand_stats)
    evaluated = replace(
        played,
        phase=Phase.ROUND_EVAL,
        round=replace(played.round, chips=64),
    )
    history = (
        PublicHistoryStep(
            played,
            PlayCards((HandSlot(0), HandSlot(1))),
            evaluated,
        ),
        PublicHistoryStep(evaluated, CashOut(), shop),
    )

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        history,
    )

    assert action == BuyShopCard(ShopSlot(1))


def test_shop_survival_projection_falls_back_without_public_play_history() -> None:
    raw = state("SHOP", money=20)
    raw["blinds"]["boss"]["score"] = 700
    raw["shop"]["cards"] = [
        item_card("j_sly", card_id=20, kind="JOKER", buy=4),
        item_card("j_joker", card_id=21, kind="JOKER", buy=4),
    ]
    raw["shop"]["count"] = 2
    raw["vouchers"]["cards"] = []
    raw["vouchers"]["count"] = 0
    raw["packs"]["cards"] = []
    raw["packs"]["count"] = 0
    shop = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert action == BuyShopCard(ShopSlot(0))


def test_shop_ranks_modeled_jokers_by_exact_public_score_delta() -> None:
    raw = state("SHOP", money=20)
    raw["round_num"] = 2
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["big"]["status"] = "DEFEATED"
    raw["blinds"]["boss"]["name"] = "The Hook"
    raw["shop"]["cards"] = [
        item_card("j_sly", card_id=20, kind="JOKER", buy=4),
        item_card("j_jolly", card_id=21, kind="JOKER", buy=4),
    ]
    raw["shop"]["count"] = 2
    raw["vouchers"]["cards"] = []
    raw["vouchers"]["count"] = 0
    raw["packs"]["cards"] = []
    raw["packs"]["count"] = 0
    shop = to_public_observation(raw)
    played_raw = state("SELECTING_HAND")
    played_raw["round_num"] = 2
    played_raw["blinds"]["small"]["status"] = "DEFEATED"
    played_raw["blinds"]["big"]["status"] = "CURRENT"
    played_raw["blinds"]["boss"]["name"] = "The Hook"
    played = replace(
        to_public_observation(played_raw),
        hand=(
            VisiblePlayingCard("A", "S"),
            VisiblePlayingCard("A", "H"),
            VisiblePlayingCard("7", "C"),
        ),
        hand_stats=(
            HandStat("High Card", 1, 5, 1, 0, 0),
            HandStat("Pair", 1, 10, 2, 0, 0),
        ),
    )
    shop = replace(shop, hand_stats=played.hand_stats)
    evaluated = replace(
        played,
        phase=Phase.ROUND_EVAL,
        round=replace(played.round, chips=64),
    )
    history = (
        PublicHistoryStep(
            played,
            PlayCards((HandSlot(0), HandSlot(1))),
            evaluated,
        ),
        PublicHistoryStep(evaluated, CashOut(), shop),
    )

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        history,
    )

    assert action == BuyShopCard(ShopSlot(1))


def test_shop_score_rank_falls_back_when_public_score_does_not_reproduce() -> None:
    raw = state("SHOP", money=20)
    raw["shop"]["cards"] = [
        item_card("j_sly", card_id=20, kind="JOKER", buy=4),
        item_card("j_jolly", card_id=21, kind="JOKER", buy=4),
    ]
    raw["shop"]["count"] = 2
    raw["vouchers"]["cards"] = []
    raw["vouchers"]["count"] = 0
    raw["packs"]["cards"] = []
    raw["packs"]["count"] = 0
    shop = to_public_observation(raw)
    played = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(VisiblePlayingCard("A", "S"), VisiblePlayingCard("A", "H")),
        hand_stats=(HandStat("Pair", 1, 10, 2, 0, 0),),
    )
    evaluated = replace(
        played,
        phase=Phase.ROUND_EVAL,
        round=replace(played.round, chips=65),
    )
    history = (
        PublicHistoryStep(
            played,
            PlayCards((HandSlot(0), HandSlot(1))),
            evaluated,
        ),
        PublicHistoryStep(evaluated, CashOut(), shop),
    )

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        history,
    )

    assert action == BuyShopCard(ShopSlot(0))


def test_joker_value_respects_visible_runtime_xmult() -> None:
    inactive = PublicItem(
        "j_stencil",
        "Joker Stencil",
        "JOKER",
        runtime=PublicJokerRuntime(current_x_mult=1.0),
    )
    active = replace(
        inactive,
        runtime=PublicJokerRuntime(current_x_mult=2.0),
    )

    assert _joker_value(inactive) < _joker_value(
        PublicItem("j_blue_joker", "Blue Joker", "JOKER")
    )
    assert _joker_value(active) > _joker_value(inactive)


def test_joker_value_does_not_price_unscaled_throwback_as_realized_xmult() -> None:
    throwback = PublicItem(
        "j_throwback",
        "Throwback",
        "JOKER",
        runtime=PublicJokerRuntime(current_x_mult=1.0),
    )

    assert _joker_value(throwback) < _joker_value(
        PublicItem("j_blue_joker", "Blue Joker", "JOKER")
    )


def test_hand_xmult_value_requires_a_committed_hand_that_contains_its_trigger() -> None:
    pair_build = BuildPlan(
        "Two Pair",
        "Pair",
        4,
        10,
        frozenset(
            {
                "pair",
                "two_pair",
                "three_of_a_kind",
                "four_of_a_kind",
                "full_house",
            }
        ),
    )

    assert _joker_value(PublicItem("j_duo", "The Duo", "JOKER"), pair_build) > 0
    assert _joker_value(PublicItem("j_trio", "The Trio", "JOKER"), pair_build) == 0
    assert _joker_value(PublicItem("j_family", "The Family", "JOKER"), pair_build) == 0

    rank_build = replace(
        pair_build,
        primary_hand="Four of a Kind",
        secondary_hand="Three of a Kind",
    )
    assert _joker_value(PublicItem("j_trio", "The Trio", "JOKER"), rank_build) > 0
    assert _joker_value(PublicItem("j_family", "The Family", "JOKER"), rank_build) > 0


def test_straight_and_flush_xmult_do_not_share_build_families() -> None:
    straight_build = BuildPlan(
        "Straight",
        "Straight Flush",
        4,
        10,
        frozenset({"straight", "straight_flush"}),
    )

    assert _joker_value(PublicItem("j_order", "The Order", "JOKER"), straight_build) > 0
    assert (
        _joker_value(PublicItem("j_tribe", "The Tribe", "JOKER"), straight_build) == 0
    )


def test_strategic_baseline_skips_a_legal_but_unvalued_tarot() -> None:
    raw = state("TAROT_PACK")
    raw["pack"]["cards"] = [item_card("c_temperance", card_id=30, kind="TAROT")]
    raw["pack"]["count"] = 1
    pack = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        pack,
        lambda: iter_legal_actions(pack),
        (),
    )

    assert isinstance(action, SkipPack)


def test_strategic_policy_uses_public_money_tarot() -> None:
    raw = state("SELECTING_HAND", money=5)
    raw["consumables"]["cards"] = [item_card("c_hermit", card_id=30, kind="TAROT")]
    raw["consumables"]["count"] = 1
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert action == UseConsumable(ConsumableSlot(0))


def test_strategic_policy_uses_targeted_hanged_man_on_low_cards() -> None:
    raw = state("SELECTING_HAND")
    raw["consumables"]["cards"] = [item_card("c_hanged_man", card_id=30, kind="TAROT")]
    raw["consumables"]["count"] = 1
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, UseConsumable)
    assert action.consumable == ConsumableSlot(0)
    assert len(action.targets) == 2


def test_strategic_policy_sells_dead_consumable_to_open_target_planet_slot() -> None:
    raw = state("SHOP", money=10)
    raw["shop"]["cards"] = [item_card("c_mercury", card_id=20, kind="PLANET", buy=3)]
    raw["shop"]["count"] = 1
    raw["consumables"]["cards"] = [
        item_card("c_future", card_id=30, kind="TAROT"),
        item_card("c_future_two", card_id=31, kind="TAROT"),
    ]
    raw["consumables"]["count"] = 2
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, SellConsumable)


def _joker_shop(
    *,
    ante: int = 6,
    money: int = 20,
    offer_buy: int = 4,
    offer_key: str = "j_order",
    joker_cards: list[dict[str, object]] | None = None,
) -> PublicObservation:
    raw = state("SHOP", money=money)
    raw["ante_num"] = ante
    raw["shop"]["cards"] = [
        item_card(offer_key, card_id=20, kind="JOKER", buy=offer_buy)
    ]
    raw["shop"]["count"] = 1
    cards = (
        joker_cards
        if joker_cards is not None
        else [
            item_card(f"j_weak_{index}", card_id=40 + index, kind="JOKER")
            for index in range(5)
        ]
    )
    raw["jokers"]["cards"] = cards
    raw["jokers"]["count"] = len(cards)
    return to_public_observation(raw)


def test_strategic_baseline_never_buys_unknown_joker_to_fill_slot() -> None:
    raw = state("SHOP", money=10)
    raw["shop"]["cards"] = [
        item_card("j_future", card_id=20, kind="JOKER", buy=5),
    ]
    raw["shop"]["count"] = 1
    raw["vouchers"]["cards"] = []
    raw["vouchers"]["count"] = 0
    raw["packs"]["cards"] = []
    raw["packs"]["count"] = 0
    shop = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert not isinstance(action, BuyShopCard)


def test_strategic_baseline_rejects_off_build_conditional_joker() -> None:
    raw = state("SHOP", money=10)
    raw["shop"]["cards"] = [
        item_card("j_crafty", card_id=20, kind="JOKER", buy=5),
    ]
    raw["shop"]["count"] = 1
    raw["vouchers"]["cards"] = []
    raw["vouchers"]["count"] = 0
    raw["packs"]["cards"] = []
    raw["packs"]["count"] = 0
    shop = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert not isinstance(action, BuyShopCard)


def test_strategic_baseline_sells_late_economy_joker_for_material_upgrade() -> None:
    shop = _joker_shop(
        money=12,
        offer_key="j_cavendish",
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


def test_strategic_baseline_can_replace_from_ante_four() -> None:
    shop = _joker_shop(
        ante=4,
        money=12,
        offer_key="j_cavendish",
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


def test_strategic_baseline_buys_replacement_after_slot_is_open() -> None:
    shop = _joker_shop(
        money=14,
        offer_key="j_cavendish",
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


def test_replacement_preserves_only_additive_mult_floor() -> None:
    shop = _joker_shop(
        money=60,
        offer_key="j_cavendish",
        joker_cards=[
            item_card("j_joker", card_id=40, kind="JOKER", sell=2),
            item_card("j_blackboard", card_id=41, kind="JOKER", sell=2),
            item_card("j_baron", card_id=42, kind="JOKER", sell=2),
            item_card("j_card_sharp", card_id=43, kind="JOKER", sell=2),
            item_card("j_acrobat", card_id=44, kind="JOKER", sell=2),
        ],
    )
    shop = replace(shop, vouchers=(), packs=())

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert action != SellJoker(JokerSlot(0))


def test_replacement_may_sell_redundant_additive_mult_floor() -> None:
    shop = _joker_shop(
        money=60,
        offer_key="j_cavendish",
        joker_cards=[
            item_card("j_joker", card_id=40, kind="JOKER", sell=3),
            item_card("j_misprint", card_id=41, kind="JOKER", sell=2),
            item_card("j_baron", card_id=42, kind="JOKER", sell=2),
            item_card("j_card_sharp", card_id=43, kind="JOKER", sell=2),
            item_card("j_acrobat", card_id=44, kind="JOKER", sell=2),
        ],
    )
    shop = replace(shop, vouchers=(), packs=())

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert action == SellJoker(JokerSlot(0))


def test_replacement_allows_additive_for_additive_swap() -> None:
    offer = item_card("j_bootstraps", card_id=20, kind="JOKER", buy=4)
    offer["modifier"] = {"edition": "POLYCHROME"}
    raw = state("SHOP", money=60)
    raw["ante_num"] = 6
    raw["shop"]["cards"] = [offer]
    raw["shop"]["count"] = 1
    raw["jokers"]["cards"] = [
        item_card("j_joker", card_id=40, kind="JOKER", sell=2),
        item_card("j_blackboard", card_id=41, kind="JOKER", sell=2),
        item_card("j_baron", card_id=42, kind="JOKER", sell=2),
        item_card("j_card_sharp", card_id=43, kind="JOKER", sell=2),
        item_card("j_acrobat", card_id=44, kind="JOKER", sell=2),
    ]
    raw["jokers"]["count"] = 5
    shop = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert action == SellJoker(JokerSlot(0))


def test_modeled_conditional_xmult_satisfies_upgrade_check() -> None:
    shop = _joker_shop(
        money=60,
        offer_key="j_credit_card",
        joker_cards=[
            item_card("j_jolly", card_id=40, kind="JOKER", sell=2),
            item_card("j_blackboard", card_id=41, kind="JOKER", sell=2),
            item_card("j_baron", card_id=42, kind="JOKER", sell=2),
            item_card("j_card_sharp", card_id=43, kind="JOKER", sell=2),
            item_card("j_acrobat", card_id=44, kind="JOKER", sell=2),
        ],
    )
    shop = replace(shop, vouchers=(), packs=())

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert not isinstance(action, RerollShop)


def test_unsupported_conditional_xmult_does_not_satisfy_upgrade_check() -> None:
    shop = _joker_shop(
        money=60,
        offer_key="j_credit_card",
        joker_cards=[
            item_card("j_jolly", card_id=40, kind="JOKER", sell=2),
            item_card("j_idol", card_id=41, kind="JOKER", sell=2),
            item_card("j_sly", card_id=42, kind="JOKER", sell=2),
            item_card("j_mad", card_id=43, kind="JOKER", sell=2),
            item_card("j_clever", card_id=44, kind="JOKER", sell=2),
        ],
    )
    shop = replace(shop, vouchers=(), packs=())

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert isinstance(action, RerollShop)


def test_inactive_runtime_xmult_does_not_satisfy_upgrade_check() -> None:
    shop = _joker_shop(
        money=60,
        offer_key="j_credit_card",
        joker_cards=[
            item_card("j_jolly", card_id=40, kind="JOKER", sell=2),
            item_card(
                "j_ramen",
                card_id=41,
                kind="JOKER",
                sell=2,
                ability={"x_mult": 1.0},
            ),
            item_card("j_sly", card_id=42, kind="JOKER", sell=2),
            item_card("j_mad", card_id=43, kind="JOKER", sell=2),
            item_card("j_clever", card_id=44, kind="JOKER", sell=2),
        ],
    )
    shop = replace(shop, vouchers=(), packs=())

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert isinstance(action, RerollShop)


def test_build_compatible_xmult_satisfies_upgrade_check() -> None:
    shop = _joker_shop(
        money=60,
        offer_key="j_credit_card",
        joker_cards=[
            item_card("j_jolly", card_id=40, kind="JOKER", sell=2),
            item_card("j_duo", card_id=41, kind="JOKER", sell=2),
            item_card("j_baron", card_id=42, kind="JOKER", sell=2),
            item_card("j_card_sharp", card_id=43, kind="JOKER", sell=2),
            item_card("j_acrobat", card_id=44, kind="JOKER", sell=2),
        ],
    )
    shop = replace(shop, vouchers=(), packs=())

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        (),
    )

    assert not isinstance(action, RerollShop)


def test_strategic_baseline_never_sells_an_eternal_joker() -> None:
    jokers = [
        item_card(f"j_eternal_{index}", card_id=40 + index, kind="JOKER")
        for index in range(5)
    ]
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
    shop = _joker_shop(
        ante=8,
        money=12,
        offer_key="j_cavendish",
        joker_cards=[
            item_card("j_trousers", card_id=40, kind="JOKER", sell=4),
            item_card("j_business", card_id=41, kind="JOKER", sell=2),
            item_card("j_blue_joker", card_id=42, kind="JOKER", sell=3),
            item_card("j_banner", card_id=43, kind="JOKER", sell=2),
            item_card("j_runner", card_id=44, kind="JOKER", sell=3),
        ],
    )
    history = (PublicHistoryStep(shop, SellJoker(JokerSlot(0)), shop),)

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        history,
    )

    assert not isinstance(action, SellJoker)


def _repeat_replacement_shop(
    offer_key: str,
) -> tuple[PublicObservation, tuple[PublicHistoryStep, ...]]:
    shop = _joker_shop(
        ante=8,
        money=30,
        offer_buy=5,
        offer_key=offer_key,
        joker_cards=[
            item_card("j_joker", card_id=40, kind="JOKER", sell=4),
            item_card("j_business", card_id=41, kind="JOKER", sell=2),
            item_card("j_blue_joker", card_id=42, kind="JOKER", sell=3),
            item_card("j_banner", card_id=43, kind="JOKER", sell=2),
            item_card("j_runner", card_id=44, kind="JOKER", sell=3),
        ],
    )
    played = replace(
        shop,
        phase=Phase.SELECTING_HAND,
        hand=(
            VisiblePlayingCard("A", "S"),
            VisiblePlayingCard("A", "H"),
            VisiblePlayingCard("7", "C"),
        ),
        hand_stats=(
            HandStat("High Card", 1, 5, 1, 0, 0),
            HandStat("Pair", 1, 10, 2, 4, 0),
        ),
    )
    selected = (HandSlot(0), HandSlot(1))
    score, _ = _play_score(
        played,
        selected,
        {stat.name: stat for stat in played.hand_stats},
    )
    assert score.denominator == 1
    evaluated = replace(
        played,
        phase=Phase.ROUND_EVAL,
        round=replace(played.round, chips=int(score)),
    )
    shop = replace(shop, hand_stats=played.hand_stats)
    previous_shop = replace(shop, round_no=shop.round_no - 1)
    history = (
        PublicHistoryStep(
            previous_shop,
            SellJoker(JokerSlot(0)),
            previous_shop,
        ),
        PublicHistoryStep(played, PlayCards(selected), evaluated),
        PublicHistoryStep(evaluated, CashOut(), shop),
    )
    return shop, history


@pytest.mark.parametrize("offer_key", ["j_brainstorm", "j_cavendish"])
def test_prior_shop_sale_allows_exact_positive_replacement(offer_key: str) -> None:
    shop, history = _repeat_replacement_shop(offer_key)

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        history,
    )

    assert isinstance(action, SellJoker)


def test_prior_shop_sale_blocks_exact_non_improving_replacement() -> None:
    shop, history = _repeat_replacement_shop("j_photograph")

    action = PublicStrategicPolicy().choose_action(
        shop,
        lambda: iter_legal_actions(shop),
        history,
    )

    assert not isinstance(action, SellJoker)


def test_strategic_baseline_never_sells_a_negative_joker() -> None:
    negative = item_card("j_weak", card_id=40, kind="JOKER")
    negative["modifier"] = {"edition": "NEGATIVE"}
    eternals = [
        item_card(f"j_eternal_{index}", card_id=41 + index, kind="JOKER")
        for index in range(4)
    ]
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
        offer_key="j_joker",
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


def test_strategic_baseline_rerolls_full_weak_build_with_excess_cash() -> None:
    raw = state("SHOP", money=60)
    raw["ante_num"] = 6
    raw["shop"]["cards"] = [item_card("j_credit_card", card_id=20, kind="JOKER")]
    raw["shop"]["count"] = 1
    raw["jokers"]["cards"] = [
        item_card("j_joker", card_id=40 + index, kind="JOKER") for index in range(5)
    ]
    raw["jokers"]["count"] = 5
    raw["vouchers"]["cards"] = []
    raw["vouchers"]["count"] = 0
    raw["packs"]["cards"] = []
    raw["packs"]["count"] = 0
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, RerollShop)


def test_reserve_blocked_joker_offer_does_not_suppress_building_reroll() -> None:
    raw = state("SHOP", money=30)
    raw["ante_num"] = 4
    raw["shop"]["cards"] = [
        item_card("j_cavendish", card_id=20, kind="JOKER", buy=28),
    ]
    raw["shop"]["count"] = 1
    raw["vouchers"]["cards"] = []
    raw["vouchers"]["count"] = 0
    raw["packs"]["cards"] = []
    raw["packs"]["count"] = 0
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, RerollShop)


def test_strategic_baseline_rerolls_full_weak_build_before_buying_pack() -> None:
    raw = state("SHOP", money=60)
    raw["ante_num"] = 6
    raw["shop"]["cards"] = [item_card("j_credit_card", card_id=20, kind="JOKER")]
    raw["shop"]["count"] = 1
    raw["jokers"]["cards"] = [
        item_card("j_joker", card_id=40 + index, kind="JOKER") for index in range(5)
    ]
    raw["jokers"]["count"] = 5
    raw["vouchers"]["cards"] = []
    raw["vouchers"]["count"] = 0
    raw["packs"]["cards"] = [
        item_card("p_standard_normal_1", card_id=60, kind="BOOSTER", buy=4),
    ]
    raw["packs"]["count"] = 1
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, RerollShop)


def test_strategic_baseline_keeps_pack_replacement_fail_closed() -> None:
    raw = state("BUFFOON_PACK")
    raw["pack"]["cards"] = [item_card("j_order", card_id=30, kind="JOKER")]
    raw["jokers"]["cards"] = [
        item_card(f"j_weak_{index}", card_id=40 + index, kind="JOKER")
        for index in range(5)
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

    action = policy.choose_action(
        observation, lambda: iter_legal_actions(observation), history
    )

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

    action = policy.choose_action(
        observation, lambda: iter_legal_actions(observation), ()
    )

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
    wheel = tuple(
        VisiblePlayingCard(rank, suit)
        for rank, suit in zip(("A", "2", "3", "4", "5"), "SHCDS")
    )
    full_house = tuple(
        VisiblePlayingCard(rank, suit)
        for rank, suit in zip(("K", "K", "K", "2", "2"), "SHCDS")
    )

    assert _classify(wheel) == "Straight"
    assert _classify(full_house) == "Full House"


def test_public_poker_classifier_applies_visible_utility_jokers() -> None:
    four_card_flush = tuple(
        VisiblePlayingCard(rank, "H") for rank in ("A", "9", "6", "2")
    )
    shortcut = tuple(
        VisiblePlayingCard(rank, suit)
        for rank, suit in zip(("A", "Q", "T", "8", "6"), "SHDCS")
    )
    smeared = tuple(
        VisiblePlayingCard(rank, suit)
        for rank, suit in zip(("A", "K", "9", "6", "2"), "HDHDH")
    )

    assert _classify(four_card_flush) == "High Card"
    assert _classify(four_card_flush, frozenset({"j_four_fingers"})) == "Flush"
    assert _classify(shortcut, frozenset({"j_shortcut"})) == "Straight"
    assert _classify(smeared, frozenset({"j_smeared"})) == "Flush"


def test_hanging_chad_retriggers_first_scoring_card() -> None:
    observation = to_public_observation(state("SELECTING_HAND"))
    selected = (HandSlot(0),)
    stats = {stat.name: stat for stat in observation.hand_stats}
    base = _play_score(observation, selected, stats)[0]
    with_chad = _play_score(
        replace(
            observation,
            jokers=(PublicItem("j_hanging_chad", "Hanging Chad", "JOKER"),),
        ),
        selected,
        stats,
    )[0]

    assert with_chad == base + 2 * 10


def test_card_time_xmult_does_not_multiply_later_joker_mult() -> None:
    observation = replace(
        to_public_observation(state("SELECTING_HAND", money=20)),
        hand=(VisiblePlayingCard("K", "S"),),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=(
            PublicItem("j_photograph", "Photograph", "JOKER"),
            PublicItem("j_joker", "Joker", "JOKER"),
        ),
    )
    stats = {stat.name: stat for stat in observation.hand_stats}

    score = _play_score(observation, (HandSlot(0),), stats)[0]

    # (1 base Mult x 2 Photograph) + 4 Joker Mult; 5 + 10 chips.
    assert score == 90


def test_polychrome_joker_does_not_multiply_later_joker_mult() -> None:
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(VisiblePlayingCard("A", "S"),),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=(
            PublicItem(
                "j_photograph",
                "Photograph",
                "JOKER",
                edition="POLYCHROME",
            ),
            PublicItem("j_joker", "Joker", "JOKER"),
        ),
    )
    stats = {stat.name: stat for stat in observation.hand_stats}

    score = _play_score(observation, (HandSlot(0),), stats)[0]

    # (1 base Mult x 1.5 edition) + 4 Joker Mult; 5 + 11 chips.
    assert score == 88


def test_held_steel_xmult_does_not_multiply_later_joker_mult() -> None:
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(
            VisiblePlayingCard("A", "S"),
            VisiblePlayingCard("K", "D", enhancement="STEEL"),
        ),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=(PublicItem("j_joker", "Joker", "JOKER"),),
    )
    stats = {stat.name: stat for stat in observation.hand_stats}

    score = _play_score(observation, (HandSlot(0),), stats)[0]

    # (1 base Mult x 1.5 Steel) + 4 Joker Mult; 5 + 11 chips.
    assert score == 88


def test_mime_retriggers_held_card_joker_effects() -> None:
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(VisiblePlayingCard("A", "S"), VisiblePlayingCard("Q", "D")),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=(
            PublicItem("j_mime", "Mime", "JOKER"),
            PublicItem("j_shoot_the_moon", "Shoot the Moon", "JOKER"),
        ),
    )
    stats = {stat.name: stat for stat in observation.hand_stats}

    score = _play_score(observation, (HandSlot(0),), stats)[0]

    assert score == 16 * (1 + 13 + 13)


def test_card_retrigger_repeats_individual_joker_effects_in_order() -> None:
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(VisiblePlayingCard("A", "S"),),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=(
            PublicItem("j_hanging_chad", "Hanging Chad", "JOKER"),
            PublicItem("j_scholar", "Scholar", "JOKER"),
        ),
    )
    stats = {stat.name: stat for stat in observation.hand_stats}

    score = _play_score(observation, (HandSlot(0),), stats)[0]

    assert score == (5 + 3 * (11 + 20)) * (1 + 3 * 4)


def _single_card_score_with_jokers(
    jokers: tuple[PublicItem, ...],
    *,
    rank: str = "A",
    suit: str = "S",
) -> int | Fraction:
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(VisiblePlayingCard(rank, suit),),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=jokers,
    )
    stats = {stat.name: stat for stat in observation.hand_stats}
    return _play_score(observation, (HandSlot(0),), stats)[0]


def test_triboulet_scores_each_king_or_queen_and_public_retrigger() -> None:
    triboulet = PublicItem("j_triboulet", "Triboulet", "JOKER")
    chad = PublicItem("j_hanging_chad", "Hanging Chad", "JOKER")

    assert _single_card_score_with_jokers((triboulet,), rank="K") == 30
    assert _single_card_score_with_jokers((triboulet,), rank="A") == 16
    assert _single_card_score_with_jokers((chad, triboulet), rank="Q") == 280


def test_blueprint_copies_triboulet_individual_effect() -> None:
    blueprint = PublicItem("j_blueprint", "Blueprint", "JOKER")
    triboulet = PublicItem("j_triboulet", "Triboulet", "JOKER")

    assert _single_card_score_with_jokers((blueprint, triboulet), rank="K") == 60


def test_baseball_scores_once_for_each_live_uncommon_joker() -> None:
    baseball = PublicItem("j_baseball", "Baseball Card", "JOKER")
    uncommon = PublicItem("j_luchador", "Luchador", "JOKER")
    debuffed = replace(uncommon, debuffed=True)

    assert _single_card_score_with_jokers((uncommon, baseball)) == 24
    assert _single_card_score_with_jokers((debuffed, baseball)) == 16
    assert _single_card_score_with_jokers((uncommon, uncommon, baseball)) == 36


def test_source_complete_deterministic_jokers_are_supported() -> None:
    for key in ("j_baseball", "j_ramen", "j_triboulet"):
        item = PublicItem(key, key, "JOKER")
        assert _joker_is_scorer(item)
        assert _joker_value(item) > 0


def test_fresh_ramen_uses_initial_xmult_until_runtime_is_visible() -> None:
    fresh = PublicItem("j_ramen", "Ramen", "JOKER")
    decayed = replace(
        fresh,
        runtime=PublicJokerRuntime(current_x_mult=1.75),
    )

    assert _single_card_score_with_jokers((fresh,)) == 32
    assert _single_card_score_with_jokers((decayed,)) == 28


def test_blueprint_copies_immediate_right_main_effect() -> None:
    score = _single_card_score_with_jokers(
        (
            PublicItem("j_blueprint", "Blueprint", "JOKER"),
            PublicItem("j_joker", "Joker", "JOKER"),
        )
    )

    assert score == 16 * (1 + 4 + 4)


def test_blueprint_rightmost_and_debuffed_targets_do_not_copy() -> None:
    joker = PublicItem("j_joker", "Joker", "JOKER")
    rightmost = _single_card_score_with_jokers(
        (joker, PublicItem("j_blueprint", "Blueprint", "JOKER"))
    )
    debuffed = _single_card_score_with_jokers(
        (
            PublicItem("j_blueprint", "Blueprint", "JOKER"),
            replace(joker, debuffed=True),
        )
    )

    assert rightmost == _single_card_score_with_jokers((joker,))
    assert debuffed == _single_card_score_with_jokers(())


def test_brainstorm_copies_literal_leftmost_and_leftmost_self_noops() -> None:
    joker = PublicItem("j_joker", "Joker", "JOKER")
    brainstorm = PublicItem("j_brainstorm", "Brainstorm", "JOKER")

    assert _single_card_score_with_jokers((joker, brainstorm)) == 16 * (1 + 4 + 4)
    assert _single_card_score_with_jokers((brainstorm, joker)) == 16 * (1 + 4)


def test_copy_chains_preserve_occurrences_and_cycles_fail_closed() -> None:
    blueprint = PublicItem("j_blueprint", "Blueprint", "JOKER")
    brainstorm = PublicItem("j_brainstorm", "Brainstorm", "JOKER")
    joker = PublicItem("j_joker", "Joker", "JOKER")

    assert _single_card_score_with_jokers((joker, blueprint, brainstorm)) == 16 * (
        1 + 3 * 4
    )
    assert _single_card_score_with_jokers((blueprint, blueprint, joker)) == 16 * (
        1 + 3 * 4
    )
    assert _single_card_score_with_jokers((blueprint, brainstorm)) == 16


def test_blueprint_copies_played_card_effects_and_duplicate_retriggers() -> None:
    greedy = PublicItem("j_greedy_joker", "Greedy Joker", "JOKER")
    blueprint = PublicItem("j_blueprint", "Blueprint", "JOKER")
    hanging_chad = PublicItem("j_hanging_chad", "Hanging Chad", "JOKER")

    assert _single_card_score_with_jokers((blueprint, greedy), suit="D") == 16 * (
        1 + 3 + 3
    )
    assert _single_card_score_with_jokers((blueprint, hanging_chad)) == 5 + 5 * 11
    assert (
        _single_card_score_with_jokers(
            (PublicItem("j_hack", "Hack", "JOKER"),) * 2,
            rank="2",
        )
        == 5 + 3 * 2
    )


def test_blueprint_copies_mime_and_brainstorm_copies_baron() -> None:
    base = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(
            VisiblePlayingCard("A", "S"),
            VisiblePlayingCard("K", "D", enhancement="STEEL"),
        ),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
    )
    selected = (HandSlot(0),)
    stats = {stat.name: stat for stat in base.hand_stats}
    mime = replace(
        base,
        jokers=(
            PublicItem("j_blueprint", "Blueprint", "JOKER"),
            PublicItem("j_mime", "Mime", "JOKER"),
        ),
    )
    baron = replace(
        base,
        hand=(VisiblePlayingCard("A", "S"), VisiblePlayingCard("K", "D")),
        jokers=(
            PublicItem("j_baron", "Baron", "JOKER"),
            PublicItem("j_brainstorm", "Brainstorm", "JOKER"),
        ),
    )

    assert _play_score(mime, selected, stats)[0] == 16 * Fraction(3, 2) ** 3
    assert _play_score(baron, selected, stats)[0] == 16 * Fraction(3, 2) ** 2


def test_copy_uses_target_runtime_and_only_copier_edition() -> None:
    green = PublicItem(
        "j_green_joker",
        "Green Joker",
        "JOKER",
        runtime=PublicJokerRuntime(current_mult=5),
    )
    blueprint = PublicItem("j_blueprint", "Blueprint", "JOKER")
    copied_runtime = _single_card_score_with_jokers((blueprint, green))
    target_polychrome = _single_card_score_with_jokers(
        (
            blueprint,
            replace(PublicItem("j_joker", "Joker", "JOKER"), edition="POLYCHROME"),
        )
    )

    assert copied_runtime == 16 * (1 + 6 + 6)
    # Blueprint adds +4 without copying the target edition. Joker then adds its
    # own +4 and applies Polychrome once: (1 + 4 + 4) * 1.5.
    assert target_polychrome == 16 * 9 * Fraction(3, 2)


def test_blueprint_fails_closed_when_target_runtime_is_missing() -> None:
    blueprint = PublicItem("j_blueprint", "Blueprint", "JOKER")
    green_without_runtime = PublicItem("j_green_joker", "Green Joker", "JOKER")

    assert _single_card_score_with_jokers(
        (blueprint, green_without_runtime)
    ) == _single_card_score_with_jokers((green_without_runtime,))


@pytest.mark.parametrize("target", ["j_hiker", "j_splash", "j_future"])
def test_blueprint_fails_closed_for_mutation_global_and_unknown_targets(
    target: str,
) -> None:
    target_item = PublicItem(target, target, "JOKER")
    blueprint = PublicItem("j_blueprint", "Blueprint", "JOKER")

    assert _single_card_score_with_jokers(
        (blueprint, target_item)
    ) == _single_card_score_with_jokers((target_item,))


def test_hiker_permanent_bonus_is_visible_to_later_retriggers_only() -> None:
    base = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(VisiblePlayingCard("A", "S"),),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
    )
    selected = (HandSlot(0),)
    stats = {stat.name: stat for stat in base.hand_stats}
    hiker = replace(base, jokers=(PublicItem("j_hiker", "Hiker", "JOKER"),))
    retriggered = replace(
        base,
        jokers=(
            PublicItem("j_hanging_chad", "Hanging Chad", "JOKER"),
            PublicItem("j_hiker", "Hiker", "JOKER"),
        ),
    )

    assert (
        _play_score(hiker, selected, stats)[0] == _play_score(base, selected, stats)[0]
    )
    assert _play_score(retriggered, selected, stats)[0] == 5 + 11 + 16 + 21


def test_shoot_the_moon_scores_only_known_held_queens() -> None:
    observation = to_public_observation(state("SELECTING_HAND"))
    selected = (HandSlot(1),)
    stats = {stat.name: stat for stat in observation.hand_stats}
    joker = PublicItem("j_shoot_the_moon", "Shoot the Moon", "JOKER")
    known = replace(observation, jokers=(joker,))
    hidden = replace(known, hand=(HiddenHandCard(), *known.hand[1:]))

    assert (
        _play_score(known, selected, stats)[0]
        > _play_score(replace(known, jokers=()), selected, stats)[0]
    )
    assert (
        _play_score(hidden, selected, stats)[0]
        == _play_score(replace(hidden, jokers=()), selected, stats)[0]
    )


@pytest.mark.parametrize(
    ("key", "label", "held_rank"),
    [
        ("j_raised_fist", "Raised Fist", "2"),
        ("j_shoot_the_moon", "Shoot the Moon", "Q"),
        ("j_baron", "Baron", "K"),
    ],
)
def test_held_card_jokers_ignore_debuffed_held_cards(
    key: str,
    label: str,
    held_rank: str,
) -> None:
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(
            VisiblePlayingCard("A", "S"),
            VisiblePlayingCard(held_rank, "D", debuffed=True),
        ),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
    )
    selected = (HandSlot(0),)
    stats = {stat.name: stat for stat in observation.hand_stats}

    assert (
        _play_score(
            replace(observation, jokers=(PublicItem(key, label, "JOKER"),)),
            selected,
            stats,
        )[0]
        == _play_score(observation, selected, stats)[0]
    )


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


def test_public_score_consumes_typed_runtime_mult_chips_and_xmult() -> None:
    observation = to_public_observation(state("SELECTING_HAND"))
    selected = (HandSlot(0),)
    stats = {stat.name: stat for stat in observation.hand_stats}
    base = _play_score(observation, selected, stats)[0]

    green = replace(
        observation,
        jokers=(
            PublicItem(
                "j_green_joker",
                "Green Joker",
                "JOKER",
                runtime=PublicJokerRuntime(current_mult=4),
            ),
        ),
    )
    ice_cream = replace(
        observation,
        jokers=(
            PublicItem(
                "j_ice_cream",
                "Ice Cream",
                "JOKER",
                runtime=PublicJokerRuntime(current_chips=75),
            ),
        ),
    )
    constellation = replace(
        observation,
        jokers=(
            PublicItem(
                "j_constellation",
                "Constellation",
                "JOKER",
                runtime=PublicJokerRuntime(current_x_mult=2.0),
            ),
        ),
    )

    assert _play_score(green, selected, stats)[0] == base + 5 * 15
    assert _play_score(ice_cream, selected, stats)[0] == base + 75
    assert _play_score(constellation, selected, stats)[0] == base * 2


@pytest.mark.parametrize("key", ["j_green_joker", "j_ride_the_bus"])
def test_public_score_initializes_known_fresh_mult_scaler_from_zero(key: str) -> None:
    joker = PublicItem(key, key, "JOKER")

    assert _single_card_score_with_jokers((joker,)) == 16 * 2


def test_fresh_ride_the_bus_stays_at_zero_on_a_scoring_face_card() -> None:
    bus = PublicItem("j_ride_the_bus", "Ride the Bus", "JOKER")

    assert _single_card_score_with_jokers((bus,), rank="K") == 15


def test_unrelated_missing_runtime_still_has_no_invented_value() -> None:
    hologram = PublicItem("j_hologram", "Hologram", "JOKER")

    assert _single_card_score_with_jokers((hologram,)) == 16


def _loyalty_history(
    plays_since_acquisition: int,
) -> tuple[PublicObservation, tuple[PublicHistoryStep, ...]]:
    loyalty = PublicItem(
        "j_loyalty_card",
        "Loyalty Card",
        "JOKER",
        runtime=PublicJokerRuntime(loyalty_remaining=5),
    )
    owned = replace(
        to_public_observation(state("SELECTING_HAND")),
        jokers=(loyalty,),
    )
    empty = replace(owned, jokers=())
    steps = [PublicHistoryStep(empty, BuyShopCard(ShopSlot(0)), owned)]
    steps.extend(
        PublicHistoryStep(
            owned,
            PlayCards((HandSlot(0),)),
            owned,
        )
        for _ in range(plays_since_acquisition)
    )
    return owned, tuple(steps)


@pytest.mark.parametrize("plays_since_acquisition", range(6))
def test_loyalty_countdown_is_derived_from_public_play_history(
    plays_since_acquisition: int,
) -> None:
    observation, history = _loyalty_history(plays_since_acquisition)

    assert (
        _loyalty_remaining_from_history(observation, history)
        == (5 - plays_since_acquisition) % 6
    )


def test_loyalty_countdown_ignores_non_play_actions() -> None:
    observation, history = _loyalty_history(0)
    history = (
        *history,
        PublicHistoryStep(observation, RerollShop(), observation),
    )

    assert _loyalty_remaining_from_history(observation, history) == 5


def test_loyalty_runtime_fails_closed_without_contiguous_provenance() -> None:
    observation, _ = _loyalty_history(0)
    observation = replace(
        observation,
        jokers=(
            replace(
                observation.jokers[0],
                runtime=PublicJokerRuntime(loyalty_remaining=0),
            ),
        ),
    )

    enriched = _with_history_derived_joker_runtime(observation, ())

    assert enriched.jokers[0].runtime is not None
    assert enriched.jokers[0].runtime.loyalty_remaining is None


def test_loyalty_countdown_rejects_duplicate_ownership_ambiguity() -> None:
    observation, history = _loyalty_history(0)
    duplicated = replace(observation, jokers=observation.jokers * 2)
    history = (
        *history,
        PublicHistoryStep(observation, BuyShopCard(ShopSlot(0)), duplicated),
        PublicHistoryStep(duplicated, SellJoker(JokerSlot(1)), observation),
    )

    assert _loyalty_remaining_from_history(observation, history) is None


def test_loyalty_countdown_resets_after_clean_reacquisition() -> None:
    observation, history = _loyalty_history(3)
    empty = replace(observation, jokers=())
    history = (
        *history,
        PublicHistoryStep(observation, SellJoker(JokerSlot(0)), empty),
        PublicHistoryStep(empty, BuyShopCard(ShopSlot(0)), observation),
    )

    assert _loyalty_remaining_from_history(observation, history) == 5


def test_loyalty_countdown_rejects_creation_during_scoring_transition() -> None:
    observation, _ = _loyalty_history(0)
    empty = replace(observation, jokers=())
    history = (PublicHistoryStep(empty, PlayCards((HandSlot(0),)), observation),)

    assert _loyalty_remaining_from_history(observation, history) is None


def test_loyalty_history_enrichment_scores_the_sixth_play() -> None:
    observation, history = _loyalty_history(5)
    enriched = _with_history_derived_joker_runtime(observation, history)
    stats = {stat.name: stat for stat in observation.hand_stats}
    selected = (HandSlot(0),)

    assert (
        _play_score(enriched, selected, stats)[0]
        == 4
        * _play_score(
            replace(observation, jokers=()),
            selected,
            stats,
        )[0]
    )


def test_shop_score_context_reproduces_a_history_derived_loyalty_trigger() -> None:
    observation, history = _loyalty_history(5)
    enriched = _with_history_derived_joker_runtime(observation, history)
    selected = (HandSlot(0),)
    stats = {stat.name: stat for stat in observation.hand_stats}
    score = _play_score(enriched, selected, stats)[0]
    assert score.denominator == 1
    evaluated = replace(
        observation,
        phase=Phase.ROUND_EVAL,
        round=replace(observation.round, chips=int(score)),
    )
    shop = replace(evaluated, phase=Phase.SHOP)
    history = (
        *history,
        PublicHistoryStep(observation, PlayCards(selected), evaluated),
        PublicHistoryStep(evaluated, CashOut(), shop),
    )
    enriched_shop = _with_history_derived_joker_runtime(shop, history)

    assert _shop_score_context(enriched_shop, history) is not None


def test_shop_score_context_survives_current_shop_reroll_only() -> None:
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(VisiblePlayingCard("A", "S"),),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
    )
    selected = (HandSlot(0),)
    evaluated = replace(
        observation,
        phase=Phase.ROUND_EVAL,
        round=replace(observation.round, chips=16),
    )
    shop = replace(evaluated, phase=Phase.SHOP)
    rerolled = replace(
        shop,
        money=shop.money - shop.round.reroll_cost,
        round=replace(shop.round, reroll_cost=shop.round.reroll_cost + 1),
    )
    history = (
        PublicHistoryStep(observation, PlayCards(selected), evaluated),
        PublicHistoryStep(evaluated, CashOut(), shop),
        PublicHistoryStep(shop, RerollShop(), rerolled),
    )

    assert _shop_score_context(rerolled, history) is None
    assert _persisted_shop_score_context(rerolled, history) is not None
    assert (
        _persisted_shop_score_context(
            replace(rerolled, round_no=rerolled.round_no + 1),
            history,
        )
        is None
    )


def test_public_score_recovers_displayed_runtime_xmult_from_float_noise() -> None:
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(VisiblePlayingCard("A", "S"),),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=(
            PublicItem(
                "j_ramen",
                "Ramen",
                "JOKER",
                runtime=PublicJokerRuntime(current_x_mult=1.7999999999999998),
            ),
        ),
    )
    stats = {stat.name: stat for stat in observation.hand_stats}

    assert _play_score(observation, (HandSlot(0),), stats)[0] == 16 * Fraction(9, 5)


@pytest.mark.parametrize(
    ("consumables", "factor"),
    [
        ((PublicItem("c_pluto", "Pluto", "PLANET"),), Fraction(3, 2)),
        (
            (
                PublicItem("c_pluto", "Pluto", "PLANET"),
                PublicItem("c_pluto", "Pluto", "PLANET"),
            ),
            Fraction(9, 4),
        ),
        ((PublicItem("c_mercury", "Mercury", "PLANET"),), Fraction(1)),
        (
            (PublicItem("c_pluto", "Pluto", "PLANET", debuffed=True),),
            Fraction(1),
        ),
    ],
)
def test_public_score_applies_matching_held_planets_with_observatory(
    consumables: tuple[PublicItem, ...],
    factor: Fraction,
) -> None:
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        used_vouchers=("v_observatory",),
        consumables=consumables,
    )
    selected = (HandSlot(0),)
    stats = {stat.name: stat for stat in observation.hand_stats}
    without_observatory = _play_score(
        replace(observation, used_vouchers=()),
        selected,
        stats,
    )[0]

    assert _play_score(observation, selected, stats)[0] == without_observatory * factor


def test_ride_the_bus_does_not_reset_on_debuffed_face_card() -> None:
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(VisiblePlayingCard("K", "S", debuffed=True),),
        hand_stats=(HandStat("High Card", 1, 5, 1, 0, 0),),
        jokers=(
            PublicItem(
                "j_ride_the_bus",
                "Ride the Bus",
                "JOKER",
                runtime=PublicJokerRuntime(current_mult=4),
            ),
        ),
    )
    stats = {stat.name: stat for stat in observation.hand_stats}

    # The debuffed King contributes no chips and is not a face for Bus, whose
    # visible +4 counter therefore becomes +5 before scoring.
    assert _play_score(observation, (HandSlot(0),), stats)[0] == 5 * (1 + 5)


def test_blackboard_fails_closed_when_a_held_card_is_hidden() -> None:
    observation = to_public_observation(state("SELECTING_HAND"))
    selected = (HandSlot(0),)
    stats = {stat.name: stat for stat in observation.hand_stats}
    blackboard = PublicItem("j_blackboard", "Blackboard", "JOKER")
    visible_dark = replace(
        observation,
        hand=(
            VisiblePlayingCard("Q", "H"),
            VisiblePlayingCard("J", "S"),
            VisiblePlayingCard("T", "C"),
        ),
        jokers=(blackboard,),
    )
    hidden = replace(
        visible_dark,
        hand=(visible_dark.hand[0], HiddenHandCard(), visible_dark.hand[2]),
    )
    without = replace(visible_dark, jokers=())

    assert (
        _play_score(visible_dark, selected, stats)[0]
        == _play_score(without, selected, stats)[0] * 3
    )
    assert (
        _play_score(hidden, selected, stats)[0]
        == _play_score(replace(hidden, jokers=()), selected, stats)[0]
    )


def test_flower_pot_counts_debuffed_non_wild_scoring_suit() -> None:
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(
            VisiblePlayingCard("A", "S"),
            VisiblePlayingCard("K", "H"),
            VisiblePlayingCard("Q", "D"),
            VisiblePlayingCard("J", "C", debuffed=True),
            VisiblePlayingCard("T", "H"),
        ),
        hand_stats=(HandStat("Straight", 1, 30, 4, 0, 0),),
    )
    selected = tuple(HandSlot(index) for index in range(5))
    stats = {stat.name: stat for stat in observation.hand_stats}
    base = _play_score(observation, selected, stats)[0]
    flower_pot = replace(
        observation,
        jokers=(PublicItem("j_flower_pot", "Flower Pot", "JOKER"),),
    )

    assert _play_score(flower_pot, selected, stats)[0] == base * 3


def test_flower_pot_uses_each_live_wild_for_one_missing_suit() -> None:
    observation = replace(
        to_public_observation(state("SELECTING_HAND")),
        hand=(
            VisiblePlayingCard("A", "S"),
            VisiblePlayingCard("K", "H"),
            VisiblePlayingCard("Q", "D"),
            VisiblePlayingCard("J", "H", enhancement="WILD"),
            VisiblePlayingCard("T", "H"),
        ),
        hand_stats=(HandStat("Straight", 1, 30, 4, 0, 0),),
        jokers=(PublicItem("j_flower_pot", "Flower Pot", "JOKER"),),
    )
    selected = tuple(HandSlot(index) for index in range(5))
    stats = {stat.name: stat for stat in observation.hand_stats}
    without = replace(observation, jokers=())
    debuffed_wild = replace(
        observation,
        hand=(
            *observation.hand[:3],
            replace(observation.hand[3], debuffed=True),
            observation.hand[4],
        ),
    )

    assert (
        _play_score(observation, selected, stats)[0]
        == _play_score(without, selected, stats)[0] * 3
    )
    assert (
        _play_score(debuffed_wild, selected, stats)[0]
        == _play_score(replace(debuffed_wild, jokers=()), selected, stats)[0]
    )


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


def test_strategic_policy_preserves_ramen_without_a_survival_last_hand() -> None:
    raw = state("SELECTING_HAND")
    raw["jokers"]["cards"] = [
        item_card("j_ramen", card_id=30, kind="JOKER", ability={"x_mult": 2}),
    ]
    raw["jokers"]["count"] = 1
    observation = to_public_observation(raw)

    action = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )

    assert isinstance(action, PlayCards)
