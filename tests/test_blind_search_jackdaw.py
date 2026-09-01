from __future__ import annotations

import json
from copy import deepcopy
from fractions import Fraction

import pytest

from balatro_ai_v2.actions import (
    BuyShopCard,
    DiscardCards,
    PlayCards,
    SelectBlind,
    iter_legal_actions,
)
from balatro_ai_v2.backend import AuthorityObservation, RunSpec
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.baselines import PublicStrategicPolicy
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
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.preboss_search import _next_blind_discards, _next_blind_hands
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
    ("seed", "blind_name", "joker_keys"),
    [
        ("1", "Big Blind", ("j_bull",)),
        ("5", "Big Blind", ("j_crafty",)),
        ("9", "Big Blind", ("j_gluttenous_joker",)),
        ("9", "Small Blind", ("j_gluttenous_joker", "j_credit_card")),
        ("11", "Big Blind", ("j_mystic_summit",)),
        ("17", "Big Blind", ("j_wily",)),
        ("19", "Big Blind", ("j_drunkard",)),
        ("20", "Big Blind", ("j_faceless",)),
        ("22", "Small Blind", ("j_joker", "j_greedy_joker", "j_crafty")),
        (
            "27",
            "Small Blind",
            ("j_droll", "j_riff_raff", "j_lusty_joker", "j_crafty", "j_scary_face"),
        ),
        ("29", "Big Blind", ("j_sly",)),
        ("86", "Big Blind", ("j_banner",)),
    ],
)
def test_organic_supported_joker_matches_every_candidate_action(
    seed: str,
    blind_name: str,
    joker_keys: tuple[str, ...],
) -> None:
    pytest.importorskip("jackdaw")
    backend = JackdawBackend()
    before = backend.reset(RunSpec("RED", "GOLD", seed))
    observation = to_public_observation(json.loads(before.observed.raw_json))
    history: list[PublicHistoryStep] = []
    policy = PublicStrategicPolicy()

    for _ in range(100):
        current = next(
            (blind for blind in observation.blinds if blind.status == "CURRENT"),
            None,
        )
        if (
            observation.phase == Phase.SELECTING_HAND
            and current is not None
            and current.name == blind_name
            and tuple(joker.key for joker in observation.jokers) == joker_keys
            and (
                "j_faceless" not in joker_keys
                or sum(
                    isinstance(card, VisiblePlayingCard)
                    and card.rank in {"J", "Q", "K"}
                    for card in observation.hand
                )
                >= 3
            )
        ):
            break
        action = policy.choose_action(
            observation,
            lambda: iter_legal_actions(observation),
            tuple(history),
        )
        result = backend.step(action)
        assert result.after is not None
        after = to_public_observation(json.loads(result.after.observed.raw_json))
        history.append(PublicHistoryStep(observation, action, after))
        before = result.after
        observation = after
    else:
        raise AssertionError(f"seed {seed} did not organically reach {joker_keys}")

    assert _supports_rollout(observation)
    assert _assert_all_tactical_transitions(
        backend,
        before,
        require_money_change="j_faceless" in joker_keys,
    ) == 436
    backend.close()


def test_organic_drunkard_purchase_adds_the_next_blind_discard() -> None:
    pytest.importorskip("jackdaw")
    backend = JackdawBackend()
    before = backend.reset(RunSpec("RED", "GOLD", "2"))
    observation = to_public_observation(json.loads(before.observed.raw_json))
    history: list[PublicHistoryStep] = []
    policy = PublicStrategicPolicy()
    expected_discards: int | None = None
    expected_hands: int | None = None

    for _ in range(100):
        action = policy.choose_action(
            observation,
            lambda: iter_legal_actions(observation),
            tuple(history),
        )
        if isinstance(action, BuyShopCard):
            offer = observation.shop[action.card.value]
            if offer.key == "j_drunkard":
                next_blind = next(
                    blind
                    for blind in observation.blinds
                    if blind.kind == "BIG" and blind.status == "UPCOMING"
                )
                expected_discards = _next_blind_discards(
                    observation,
                    next_blind,
                    offer,
                )
                expected_hands = _next_blind_hands(observation, next_blind)
        result = backend.step(action)
        assert result.after is not None
        after = to_public_observation(json.loads(result.after.observed.raw_json))
        history.append(PublicHistoryStep(observation, action, after))
        observation = after
        if (
            expected_discards is not None
            and observation.phase == Phase.SELECTING_HAND
            and any(
                blind.name == "Big Blind" and blind.status == "CURRENT"
                for blind in observation.blinds
            )
        ):
            break
    else:
        raise AssertionError("seed 2 did not organically buy Drunkard before Big Blind")

    assert observation.round.discards_left == expected_discards
    assert observation.round.hands_left == expected_hands
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
