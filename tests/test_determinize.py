from __future__ import annotations

import json
import random
import subprocess
import sys
from copy import deepcopy

import pytest

from balatro_ai_v2.actions import RerollShop, iter_legal_actions
from balatro_ai_v2.backend import RunSpec
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.baselines import PublicStrategicPolicy
from balatro_ai_v2.determinize import (
    DeterminizationUnavailable,
    canonical_private_state,
    clone_backend,
    sample_candidate,
    sample_seed,
    scrub_game_state,
)
from balatro_ai_v2.determinized_search import (
    DeterminizedSearchPolicy,
    RolloutBudget,
    SuccessTeacherBudget,
)
from balatro_ai_v2.jackdaw import JackdawBackend
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.public_state import Phase


def _organic_states(seed: str, *, phases: set[Phase], limit: int = 6):
    """Yield ``(backend, observation, history)`` at organic decisions of the given phases."""

    policy = PublicStrategicPolicy()
    backend = JackdawBackend()
    authority = backend.reset(RunSpec("RED", "WHITE", seed))
    observation = to_public_observation(json.loads(authority.observed.raw_json))
    history: list[PublicHistoryStep] = []
    produced = 0
    while not observation.terminal and len(history) < 400 and produced < limit:
        if observation.phase in phases:
            produced += 1
            yield backend, observation, tuple(history)
        action = policy.choose_action(
            observation, lambda: iter_legal_actions(observation), tuple(history)
        )
        result = backend.step(action)
        assert result.status == "accepted", result.error
        after = to_public_observation(json.loads(result.after.observed.raw_json))
        history.append(PublicHistoryStep(observation, action, after))
        observation = after
    backend.close()


def test_sample_seed_depends_only_on_public_digest_nonce_and_index() -> None:
    for backend, observation, _ in _organic_states("3", phases={Phase.SHOP}, limit=1):
        twin = deepcopy(observation)
        assert sample_seed(observation, "n", 0) == sample_seed(twin, "n", 0)
        assert sample_seed(observation, "n", 0) != sample_seed(observation, "n", 1)
        assert sample_seed(observation, "n", 0) != sample_seed(observation, "m", 0)
        with pytest.raises(ValueError):
            sample_seed(observation, "n", -1)


def test_scrubbed_states_round_trip_to_the_public_observation() -> None:
    checked = 0
    for backend, observation, history in _organic_states(
        "11", phases={Phase.SHOP, Phase.PACK, Phase.BLIND_SELECT}, limit=12
    ):
        for index in range(2):
            sample = sample_candidate(
                backend, observation, history, sample_seed(observation, "t", index)
            )
            assert sample.current_public == observation
            sample.close()
            checked += 1
    assert checked >= 12


def test_hidden_twins_scrub_to_identical_private_states() -> None:
    for backend, observation, history in _organic_states(
        "5", phases={Phase.BLIND_SELECT}, limit=9
    ):
        if observation.ante < 2:
            continue
        from jackdaw.engine.rng import PseudoRandom

        left = deepcopy(backend._backend._gs)
        right = deepcopy(left)
        right["seed"] = "OTHER-SEED"
        other = PseudoRandom("OTHER-SEED")
        other.seed("shuffle")
        other.random("misc")
        right["rng"] = other
        random.Random(7).shuffle(right["deck"])
        right["discard_pile"].reverse()
        right["current_round"]["voucher"] = "v_blank"
        from jackdaw.engine.card import Card

        for card in (
            right["deck"] + right["hand"] + right["jokers"] + right["discard_pile"]
        ):
            if isinstance(card, Card):
                card.sort_id += 5000

        seed = sample_seed(observation, "twin", 0)
        scrub_game_state(left, seed, voucher_public=False)
        scrub_game_state(right, seed, voucher_public=False)
        assert canonical_private_state(left) == canonical_private_state(right)
        return
    pytest.skip("no ante-2 blind select reached in the fixture run")


def test_samples_diverge_on_hidden_futures_but_agree_publicly() -> None:
    for backend, observation, history in _organic_states(
        "7", phases={Phase.SHOP}, limit=6
    ):
        reroll = next(
            (
                action
                for action in iter_legal_actions(observation)
                if isinstance(action, RerollShop)
            ),
            None,
        )
        if reroll is None:
            continue
        outcomes = []
        for index in range(4):
            sample = sample_candidate(
                backend, observation, history, sample_seed(observation, "d", index)
            )
            result = sample.step(reroll)
            assert result.status == "accepted"
            outcomes.append(tuple(item.key for item in sample.current_public.shop))
            sample.close()
        assert len(set(outcomes)) > 1
        return
    pytest.skip("no affordable reroll reached in the fixture run")


def test_face_down_hand_cards_fail_closed() -> None:
    for backend, observation, history in _organic_states(
        "2", phases={Phase.SELECTING_HAND}, limit=1
    ):
        clone = clone_backend(backend)
        clone._backend._gs["hand"][0].facing = "back"
        clone._current = clone.observe()
        hidden = clone.current_public
        with pytest.raises(DeterminizationUnavailable):
            sample_candidate(clone, hidden, history, sample_seed(hidden, "f", 0))


def test_search_policy_returns_legal_actions_and_records_paired_values() -> None:
    for backend, observation, history in _organic_states(
        "9", phases={Phase.SHOP}, limit=2
    ):
        policy = DeterminizedSearchPolicy(
            backend=backend,
            continuation=PublicStrategicPolicy(),
            budget=RolloutBudget(samples=1, horizon_antes=1, max_steps=40),
        )
        action = policy.choose_action(
            observation, lambda: iter_legal_actions(observation), history
        )
        assert action in list(iter_legal_actions(observation))
        decision = policy.last_decision
        assert decision is not None and decision.roots >= 2
        assert decision.unavailable_reason is None
        assert len(decision.values) == decision.roots
        assert decision.steps > 0
        assert decision.goal is None
        return


def test_strategy_option_search_is_legal_goal_conditioned_and_carries_intent() -> None:
    class IntentContinuation:
        def __init__(self) -> None:
            self.base = PublicStrategicPolicy()
            self.seen = []

        def fork_for_rollout(self, intent):
            parent = self

            class Branch:
                base = PublicStrategicPolicy()

                def choose_action(self, observation, legal_actions, history):
                    return self.base.choose_action(observation, legal_actions, history)

                def choose_action_for_intent(
                    self, observation, legal_actions, history, branch_intent
                ):
                    assert branch_intent == intent
                    parent.seen.append(branch_intent)
                    return self.base.choose_action(observation, legal_actions, history)

            return Branch()

        def choose_action(self, observation, legal_actions, history):
            return self.base.choose_action(observation, legal_actions, history)

        def choose_action_for_intent(self, observation, legal_actions, history, intent):
            self.seen.append(intent)
            return self.base.choose_action(observation, legal_actions, history)

    for backend, observation, history in _organic_states(
        "9", phases={Phase.SHOP}, limit=1
    ):
        continuation = IntentContinuation()
        policy = DeterminizedSearchPolicy(
            backend=backend,
            continuation=continuation,
            budget=RolloutBudget(samples=1, horizon_antes=1, max_steps=20),
            enable_strategy_options=True,
            include_reorders=True,
        )

        action = policy.choose_action(
            observation, lambda: iter_legal_actions(observation), history
        )

        assert action in tuple(iter_legal_actions(observation))
        assert policy.last_decision is not None
        assert policy.last_decision.goal == "victory"
        assert policy.last_decision.goal_values
        assert continuation.seen
        assert policy.teacher_drafts
        assert policy.teacher_drafts[-1].observation == observation
        assert all(
            candidate.samples for candidate in policy.teacher_drafts[-1].candidates
        )
        return


def test_production_strategy_continuation_executes_intent_rollouts() -> None:
    for backend, observation, history in _organic_states(
        "9", phases={Phase.SHOP}, limit=1
    ):
        policy = DeterminizedSearchPolicy(
            backend=backend,
            continuation=PublicStrategicPolicy(),
            budget=RolloutBudget(samples=1, horizon_antes=1, max_steps=200),
            enable_strategy_options=True,
        )

        action = policy.choose_action(
            observation, lambda: iter_legal_actions(observation), history
        )

        assert action in tuple(iter_legal_actions(observation))
        assert policy.last_decision is not None
        assert policy.last_decision.steps > 0
        assert policy.last_decision.rejected_rollouts == 0
        assert policy.teacher_drafts
        assert any(
            candidate.intent is not None
            for candidate in policy.teacher_drafts[-1].candidates
        )
        return


def test_strategy_rollouts_do_not_mutate_an_ordinary_stateful_continuation() -> None:
    class StatefulContinuation:
        def __init__(self) -> None:
            self.base = PublicStrategicPolicy()
            self.calls = 0

        def choose_action(self, observation, legal_actions, history):
            self.calls += 1
            return self.base.choose_action(observation, legal_actions, history)

    for backend, observation, history in _organic_states(
        "9", phases={Phase.SHOP}, limit=1
    ):
        continuation = StatefulContinuation()
        policy = DeterminizedSearchPolicy(
            backend=backend,
            continuation=continuation,
            budget=RolloutBudget(samples=1, horizon_antes=1, max_steps=20),
            enable_strategy_options=True,
        )

        action = policy.choose_action(
            observation, lambda: iter_legal_actions(observation), history
        )

        assert action in tuple(iter_legal_actions(observation))
        assert policy.last_decision is not None
        assert policy.last_decision.rejected_rollouts == 0
        assert continuation.calls == 1
        return


def test_success_teacher_is_action_inert_and_records_a_distinct_baseline() -> None:
    for backend, observation, history in _organic_states(
        "9", phases={Phase.SHOP}, limit=1
    ):
        behavior = DeterminizedSearchPolicy(
            backend=backend,
            continuation=PublicStrategicPolicy(),
            nonce="action-inert",
            budget=RolloutBudget(samples=1, horizon_antes=1, max_steps=200),
        )
        teacher = DeterminizedSearchPolicy(
            backend=backend,
            continuation=PublicStrategicPolicy(),
            nonce="action-inert",
            budget=RolloutBudget(samples=1, horizon_antes=1, max_steps=200),
            success_teacher=SuccessTeacherBudget(samples=1, max_steps=200),
        )

        expected = behavior.choose_action(
            observation, lambda: iter_legal_actions(observation), history
        )
        actual = teacher.choose_action(
            observation, lambda: iter_legal_actions(observation), history
        )

        assert actual == expected
        assert teacher.teacher_drafts
        draft = teacher.teacher_drafts[-1]
        assert draft.candidates[draft.baseline_index].action == actual
        assert teacher.last_decision is not None and behavior.last_decision is not None
        assert teacher.last_decision.selected == behavior.last_decision.selected
        return


def test_policy_child_cannot_import_determinization() -> None:
    code = (
        "import sys\n"
        "import balatro_ai_v2.determinize\n"
        "from balatro_ai_v2.policy_child import _require_public_imports_only\n"
        "_require_public_imports_only()\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert completed.returncode != 0
    assert "private engine modules" in completed.stderr


def test_continuation_failure_inside_a_rollout_fails_closed_for_that_rollout() -> None:
    class FlakyContinuation:
        calls = 0

        def choose_action(self, observation, legal_actions, history):
            self.calls += 1
            if self.calls > 2:
                raise RuntimeError("synthetic continuation failure")
            return PublicStrategicPolicy().choose_action(
                observation, legal_actions, history
            )

    for backend, observation, history in _organic_states(
        "9", phases={Phase.SHOP}, limit=1
    ):
        policy = DeterminizedSearchPolicy(
            backend=backend,
            continuation=FlakyContinuation(),
            budget=RolloutBudget(samples=1, horizon_antes=1, max_steps=40),
        )
        action = policy.choose_action(
            observation, lambda: iter_legal_actions(observation), history
        )
        assert action in list(iter_legal_actions(observation))
        assert policy.last_decision is not None
        assert policy.last_decision.rejected_rollouts >= 1
