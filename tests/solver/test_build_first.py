from dataclasses import replace
import pytest

from balatro_ai_v2.live.build_first import BuildFirstPolicy
from balatro_ai_v2.live.runner import RunConfig, make_policy
from balatro_ai_v2.solver.actions import (
    BuyShopCard,
    ChoosePackCard,
    HandSlot,
    LeaveShop,
    OpenedPackSlot,
    PlayCards,
    SellJoker,
    SkipPack,
    is_legal,
    iter_legal_actions,
)
from balatro_ai_v2.solver.adapter import to_public_observation
from balatro_ai_v2.solver.build_intent import BuildIntent
from solver_state_factory import item_card, playing_card, state


def test_build_first_is_registered_with_runner():
    policy = make_policy("build-first")
    assert isinstance(policy, BuildFirstPolicy)
    assert RunConfig(policy="build-first").policy == "build-first"


def test_planet_pack_follows_committed_intent(monkeypatch):
    raw = state("PLANET_PACK")
    raw["pack"]["cards"] = [
        item_card("c_saturn", card_id=30, kind="PLANET"),
        item_card("c_mercury", card_id=31, kind="PLANET"),
    ]
    raw["pack"]["count"] = 2
    observation = to_public_observation(raw)
    intent = BuildIntent("Pair", "hand", (), 0, 1)
    monkeypatch.setattr("balatro_ai_v2.live.build_first.derive_intent", lambda _: intent)

    action, _, _ = BuildFirstPolicy().select(observation)

    assert action == ChoosePackCard(card=OpenedPackSlot(1))
    assert is_legal(observation, action)


def test_worthless_standard_playing_card_pack_is_skipped():
    raw = state("STANDARD_PACK")
    raw["pack"]["cards"] = [playing_card("S_A", card_id=30)]
    observation = to_public_observation(raw)

    action, _, _ = BuildFirstPolicy().select(observation)

    assert isinstance(action, SkipPack)
    assert is_legal(observation, action)


def test_pending_replacement_requires_same_round_fingerprint_and_offer():
    raw = state("SHOP", money=20)
    raw["shop"]["cards"] = [item_card("j_future", card_id=30, kind="JOKER", buy=2)]
    raw["jokers"]["cards"] = [item_card("j_joker", card_id=40, kind="JOKER")]
    raw["jokers"]["count"] = 1
    observation = to_public_observation(raw)
    policy = BuildFirstPolicy()
    offer = observation.shop[0]
    policy.pending_purchase = (observation.round_no, (("j_other", None, False, None, False),), offer)

    action = policy._shop(observation, BuildIntent("Pair", "hand", (), 0, 1), tuple(iter_legal_actions(observation)), LeaveShop())

    assert not isinstance(action, BuyShopCard)
    assert not policy.pending_purchase


def test_eternal_joker_is_never_selected_for_replacement_sale(monkeypatch):
    raw = state("SHOP", money=20)
    eternal = item_card("j_joker", card_id=40, kind="JOKER")
    eternal["modifier"] = {"eternal": True}
    raw["jokers"]["cards"] = [eternal]
    raw["jokers"]["count"] = 1
    raw["jokers"]["limit"] = 1
    raw["shop"]["cards"] = [item_card("j_green_joker", card_id=30, kind="JOKER", buy=2)]
    observation = to_public_observation(raw)
    policy = BuildFirstPolicy()
    monkeypatch.setattr(policy.probe, "_hands", lambda _: ())
    monkeypatch.setattr(policy.probe, "_next_blind_projection", lambda _: (None, None))
    monkeypatch.setattr(policy.probe, "_capacity_components", lambda *_: (100, 100, 100))

    action = policy._shop(observation, BuildIntent("Pair", "hand", (), 0, 1), tuple(iter_legal_actions(observation)), LeaveShop())

    assert not isinstance(action, SellJoker)
    assert is_legal(observation, action)


@pytest.mark.parametrize(
    "changes",
    [
        {"round": {"hands_left": 1}},
        {"round": {"chips": 1000}},
    ],
)
def test_growth_play_keeps_fallback_when_no_safe_growth_window(monkeypatch, changes):
    raw = state("SELECTING_HAND")
    raw["round"].update(changes["round"])
    observation = to_public_observation(raw)
    fallback = PlayCards((HandSlot(0),))
    intent = BuildIntent("Pair", "small_hand", ("j_green_joker",), 0, 1)
    actions = tuple(iter_legal_actions(observation))
    monkeypatch.setattr("balatro_ai_v2.live.build_first._play_score", lambda *_: (1, "Pair"))

    assert BuildFirstPolicy()._growth_play(observation, intent, actions, fallback) == fallback


@pytest.mark.parametrize("boss_name", ["The Needle", "The Psychic"])
def test_growth_play_does_not_override_boss_or_hidden_constraints(monkeypatch, boss_name):
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "UPCOMING"
    raw["blinds"]["boss"].update(status="CURRENT", name=boss_name, type="BOSS")
    observation = to_public_observation(raw)
    fallback = PlayCards((HandSlot(0),))
    intent = BuildIntent("Pair", "small_hand", ("j_green_joker",), 0, 1)
    monkeypatch.setattr("balatro_ai_v2.live.build_first._play_score", lambda *_: (1, "Pair"))

    assert BuildFirstPolicy()._growth_play(observation, intent, tuple(iter_legal_actions(observation)), fallback) == fallback


def test_growth_play_keeps_fallback_when_hand_identity_is_hidden(monkeypatch):
    raw = state("SELECTING_HAND")
    raw["hand"]["cards"][0]["state"] = {"hidden": True}
    observation = to_public_observation(raw)
    fallback = PlayCards((HandSlot(0),))
    intent = BuildIntent("Pair", "small_hand", ("j_green_joker",), 0, 1)
    monkeypatch.setattr("balatro_ai_v2.live.build_first._play_score", lambda *_: (1, "Pair"))

    assert BuildFirstPolicy()._growth_play(observation, intent, tuple(iter_legal_actions(observation)), fallback) == fallback


@pytest.mark.parametrize("phase", ["BLIND_SELECT", "SELECTING_HAND", "ROUND_EVAL", "SHOP"])
def test_selected_actions_are_legal(phase):
    observation = to_public_observation(state(phase))
    action, _, _ = BuildFirstPolicy().select(observation)
    assert is_legal(observation, action)


def test_safe_square_growth_prefers_four_cards(monkeypatch):
    raw = state('SELECTING_HAND')
    raw['hand']['cards'].append(playing_card('D_9', card_id=7))
    raw['hand']['count'] = 4
    observation = to_public_observation(raw)
    observation = replace(observation, round=replace(observation.round, hands_left=4, chips=0),
                          blinds=tuple(replace(b, score=300) for b in observation.blinds))
    intent = BuildIntent('Pair', 'small_hand', ('j_square',), 0, 1)
    monkeypatch.setattr('balatro_ai_v2.live.build_first._play_score', lambda *_: (100, 'High Card'))
    action = BuildFirstPolicy()._growth_play(observation, intent,
                                           tuple(iter_legal_actions(observation)),
                                           PlayCards((HandSlot(0),)))
    assert len(action.cards) == 4
    assert is_legal(observation, action)


def test_valid_pending_purchase_completes_before_other_spending():
    from balatro_ai_v2.solver.shop_search import _owned_fingerprints
    observation = to_public_observation(state('SHOP', money=50))
    action = next(a for a in iter_legal_actions(observation) if isinstance(a, BuyShopCard))
    policy = BuildFirstPolicy()
    policy.pending_purchase = (observation.round_no, _owned_fingerprints(observation.jokers),
                               observation.shop[action.card.value])
    selected = policy._shop(observation, BuildIntent('Pair', 'hand', (), 0, 0),
                            tuple(iter_legal_actions(observation)), LeaveShop())
    assert selected == action
    assert policy.pending_purchase is None
