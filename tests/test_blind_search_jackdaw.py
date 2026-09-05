from __future__ import annotations

import json
from copy import deepcopy
from fractions import Fraction

import pytest

from balatro_ai_v2.actions import (
    BuyShopCard,
    CashOut,
    DiscardCards,
    HandSlot,
    LeaveShop,
    PlayCards,
    SelectBlind,
    ShopSlot,
    iter_legal_actions,
)
from balatro_ai_v2.backend import AuthorityObservation, RunSpec
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.blind_search import (
    PublicBlindBeliefSearch,
    _RolloutState,
    _exact_successors,
    _initial_exact_state,
    _new_exact_context,
    _supports_rollout,
    _transition,
)
from balatro_ai_v2.jackdaw import JackdawBackend
from balatro_ai_v2.public_state import Phase, VisiblePlayingCard


_RANK = {"10": "T", "Jack": "J", "Queen": "Q", "King": "K", "Ace": "A"}
_SUIT = {"Spades": "S", "Hearts": "H", "Clubs": "C", "Diamonds": "D"}


def test_base_card_transition_matches_every_candidate_action() -> None:
    """Evaluator-only private clones certify the policy's narrow public model."""

    pytest.importorskip("jackdaw")
    backend = JackdawBackend()
    backend.reset(RunSpec("RED", "GOLD", "1"))
    selected = backend.step(SelectBlind())
    assert selected.after is not None
    assert _assert_all_tactical_transitions(backend, selected.after) == 436
    after_first = _assert_exact_successor_matches_actual(
        backend,
        selected.after,
        DiscardCards((next(iter_legal_hand_slots(selected.after)),)),
    )
    _assert_exact_successor_matches_actual(
        backend,
        after_first,
        DiscardCards((next(iter_legal_hand_slots(after_first)),)),
    )
    backend.close()


@pytest.mark.parametrize(
    "joker_keys",
    [
        ("j_bull",),
        ("j_gluttenous_joker", "j_credit_card"),
        ("j_mystic_summit",),
        ("j_drunkard",),
        ("j_faceless",),
        ("j_joker",),
        ("j_sly",),
        ("j_droll",),
        ("j_scary_face",),
        ("j_banner",),
        ("j_wily",),
        ("j_lusty_joker",),
        ("j_riff_raff", "j_crafty", "j_greedy_joker"),
    ],
)
def test_constructed_supported_joker_matches_every_candidate_action(
    joker_keys: tuple[str, ...],
) -> None:
    """Keep engine-parity fixtures independent from the changing control policy."""

    pytest.importorskip("jackdaw")
    from jackdaw.engine.card_factory import create_joker

    backend = JackdawBackend()
    backend.reset(RunSpec("RED", "GOLD", "4" if "j_faceless" in joker_keys else "1"))
    selected = backend.step(SelectBlind())
    assert selected.after is not None
    backend._backend._gs["jokers"] = [create_joker(key) for key in joker_keys]
    before = backend.observe()
    observation = to_public_observation(json.loads(before.observed.raw_json))

    assert tuple(joker.key for joker in observation.jokers) == joker_keys
    assert _supports_rollout(observation)
    assert _assert_all_tactical_transitions(
        backend,
        before,
        require_money_change="j_faceless" in joker_keys,
    ) == 436
    backend.close()


def test_constructed_drunkard_purchase_adds_the_next_blind_discard() -> None:
    pytest.importorskip("jackdaw")
    from jackdaw.engine.card_factory import create_joker

    backend = JackdawBackend()
    backend.reset(RunSpec("RED", "GOLD", "5"))
    prefix = (
        SelectBlind(),
        DiscardCards(tuple(HandSlot(index) for index in (3, 4, 5, 7))),
        PlayCards(tuple(HandSlot(index) for index in (1, 3, 4, 5, 7))),
        DiscardCards(tuple(HandSlot(index) for index in (1, 3, 5, 6))),
        PlayCards(tuple(HandSlot(index) for index in (0, 1, 5, 6, 7))),
        CashOut(),
    )
    for action in prefix:
        reached_shop = backend.step(action)
        assert reached_shop.after is not None

    drunkard = create_joker("j_drunkard")
    drunkard.set_cost()
    backend._backend._gs["shop_cards"] = [drunkard]
    backend.observe()
    bought = backend.step(BuyShopCard(ShopSlot(0)))
    assert bought.after is not None
    left = backend.step(LeaveShop())
    assert left.after is not None
    result = backend.step(SelectBlind())
    assert result.after is not None
    observation = to_public_observation(json.loads(result.after.observed.raw_json))

    assert tuple(joker.key for joker in observation.jokers) == ("j_drunkard",)
    assert observation.round.discards_left == 4
    assert observation.round.hands_left == 4
    backend.close()


def _assert_all_tactical_transitions(
    backend: JackdawBackend,
    before: AuthorityObservation,
    *,
    require_money_change: bool = False,
) -> int:
    observation = to_public_observation(json.loads(before.observed.raw_json))
    game_state = backend._backend._gs
    assert game_state is not None
    tape = tuple(_public_base_card(card) for card in reversed(game_state["deck"]))
    initial = _RolloutState(
        hand=tuple(observation.hand),
        deck_index=0,
        chips=Fraction(observation.round.chips),
        money=observation.money,
        hands_left=observation.round.hands_left,
        discards_left=observation.round.discards_left,
        hands_played=observation.round.hands_played,
        discards_used=observation.round.discards_used,
        hand_stats=observation.hand_stats,
    )

    checked = 0
    money_changes = 0
    for action in iter_legal_actions(observation):
        if not isinstance(action, (PlayCards, DiscardCards)):
            continue
        predicted = _transition(observation, initial, action, tape)

        # This clone remains in the evaluator. It is never reachable by policy code.
        oracle = JackdawBackend()
        oracle._backend._gs = deepcopy(game_state)
        oracle._current = before
        oracle._poker_hand_iteration_order = backend._poker_hand_iteration_order
        result = oracle.step(action)
        assert result.status == "accepted"
        assert result.after is not None
        actual = to_public_observation(json.loads(result.after.observed.raw_json))

        assert predicted.chips == actual.round.chips
        assert predicted.money == actual.money
        money_changes += int(predicted.money != observation.money)
        assert predicted.hands_left == actual.round.hands_left
        assert predicted.discards_left == actual.round.discards_left
        assert predicted.hands_played == actual.round.hands_played
        assert predicted.discards_used == actual.round.discards_used
        assert predicted.hand_stats == actual.hand_stats
        if actual.phase == Phase.SELECTING_HAND:
            assert predicted.hand == actual.hand
            assert len(tape) - predicted.deck_index == actual.draw_count
        checked += 1

    if require_money_change:
        assert money_changes > 0
    return checked


def iter_legal_hand_slots(before: AuthorityObservation):
    observation = to_public_observation(json.loads(before.observed.raw_json))
    for action in iter_legal_actions(observation):
        if isinstance(action, DiscardCards) and len(action.cards) == 1:
            yield action.cards[0]


def _assert_exact_successor_matches_actual(
    backend: JackdawBackend,
    before: AuthorityObservation,
    action: DiscardCards,
) -> AuthorityObservation:
    observation = to_public_observation(json.loads(before.observed.raw_json))
    target = next(blind.score for blind in observation.blinds if blind.status == "CURRENT")
    search = PublicBlindBeliefSearch()
    context = _new_exact_context(observation, target, search)
    successors = _exact_successors(
        context,
        _initial_exact_state(observation),
        action,
    )

    result = backend.step(action)
    assert result.status == "accepted"
    assert result.after is not None
    actual = to_public_observation(json.loads(result.after.observed.raw_json))
    actual_state = _initial_exact_state(actual)
    matches = [successor for successor in successors if successor.state == actual_state]
    assert len(matches) == 1
    assert matches[0].probability == Fraction(1, observation.draw_count)
    assert sum((successor.probability for successor in successors), Fraction(0)) == 1
    return result.after


def _public_base_card(card: object) -> VisiblePlayingCard:
    base = card.base
    return VisiblePlayingCard(
        rank=_RANK.get(base.rank.value, base.rank.value),
        suit=_SUIT[base.suit.value],
        enhancement=None,
        edition=None,
        seal=None,
        debuffed=False,
        permanent_bonus=0,
        effect_text="Base",
    )
