from __future__ import annotations

import json
from copy import deepcopy
from fractions import Fraction

import pytest

from balatro_ai_v2.actions import DiscardCards, PlayCards, SelectBlind, iter_legal_actions
from balatro_ai_v2.backend import AuthorityObservation, RunSpec
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.baselines import PublicStrategicPolicy
from balatro_ai_v2.blind_search import _RolloutState, _supports_rollout, _transition
from balatro_ai_v2.jackdaw import JackdawBackend
from balatro_ai_v2.policy import PublicHistoryStep
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
    backend.close()


@pytest.mark.parametrize(
    ("seed", "blind_name", "joker_keys"),
    [
        ("1", "Big Blind", ("j_bull",)),
        ("5", "Big Blind", ("j_crafty",)),
        ("9", "Big Blind", ("j_gluttenous_joker",)),
        ("11", "Big Blind", ("j_mystic_summit",)),
        ("17", "Big Blind", ("j_wily",)),
        ("22", "Small Blind", ("j_joker", "j_greedy_joker", "j_crafty")),
        (
            "27",
            "Small Blind",
            ("j_droll", "j_riff_raff", "j_lusty_joker", "j_crafty", "j_scary_face"),
        ),
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
    assert _assert_all_tactical_transitions(backend, before) == 436
    backend.close()


def _assert_all_tactical_transitions(
    backend: JackdawBackend,
    before: AuthorityObservation,
) -> int:
    observation = to_public_observation(json.loads(before.observed.raw_json))
    game_state = backend._backend._gs
    assert game_state is not None
    tape = tuple(_public_base_card(card) for card in reversed(game_state["deck"]))
    initial = _RolloutState(
        hand=tuple(observation.hand),
        deck_index=0,
        chips=Fraction(observation.round.chips),
        hands_left=observation.round.hands_left,
        discards_left=observation.round.discards_left,
        hands_played=observation.round.hands_played,
        discards_used=observation.round.discards_used,
        hand_stats=observation.hand_stats,
    )

    checked = 0
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
        assert predicted.hands_left == actual.round.hands_left
        assert predicted.discards_left == actual.round.discards_left
        assert predicted.hands_played == actual.round.hands_played
        assert predicted.discards_used == actual.round.discards_used
        assert predicted.hand_stats == actual.hand_stats
        if actual.phase == Phase.SELECTING_HAND:
            assert predicted.hand == actual.hand
            assert len(tape) - predicted.deck_index == actual.draw_count
        checked += 1

    return checked


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
