from __future__ import annotations

import json
import pickle
import random
import subprocess
import sys
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

import balatro_ai_v2.determinize as determinize_module
from balatro_ai_v2.actions import RerollShop, action_to_data, iter_legal_actions
from balatro_ai_v2.backend import RunSpec
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.baselines import PublicStrategicPolicy
from balatro_ai_v2.determinize import (
    DeterminizationUnavailable,
    FrozenJackdawBackend,
    canonical_private_state,
    clone_backend,
    freeze_backend,
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
from state_factory import hidden_joker_slot, state


def _organic_states(seed: str, *, phases: set[Phase], limit: int = 6):
    """Yield ``(backend, observation, history)`` at organic decisions of the given phases."""

    policy = PublicStrategicPolicy()
    backend = JackdawBackend()
    authority = backend.reset(RunSpec("RED", "WHITE", seed))
    observation = to_public_observation(json.loads(authority.observed.raw_json))
    history: list[PublicHistoryStep] = []
    produced = 0
    try:
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
    finally:
        backend.close()


def _legacy_clone_backend(backend: JackdawBackend) -> JackdawBackend:
    """Previous clone implementation, retained here as an equivalence oracle."""

    clone = JackdawBackend(lightweight=True)
    clone._backend._gs, clone._active_pack_cards, clone._stale_shop_areas = (
        pickle.loads(
            pickle.dumps(
                (
                    backend._backend._gs,
                    backend._active_pack_cards,
                    backend._stale_shop_areas,
                ),
                protocol=pickle.HIGHEST_PROTOCOL,
            )
        )
    )
    for name in (
        "_round_targets_rolled",
        "_pending_ante_setup",
        "_poker_hand_iteration_order",
        "_pack_card_limit",
        "_won",
        "_pending_skip_dollars",
    ):
        setattr(clone, name, getattr(backend, name))
    clone._current = backend._current
    clone.current_public = backend.current_public
    return clone


def _action_key(action) -> str:
    return json.dumps(action_to_data(action), sort_keys=True, separators=(",", ":"))


def _bounded_legal_roots(observation, *, limit: int = 5):
    """Retain a small, deterministic cross-section of one organic root set."""

    legal = tuple(iter_legal_actions(observation))
    assert legal
    if len(legal) <= limit:
        return legal
    return legal[: limit - 1] + legal[-1:]


def _step_projection(result, backend: JackdawBackend):
    """Behavior visible at the bridge plus the resulting engine state."""

    assert result.status == "accepted", result.error
    assert result.after is not None
    assert backend.current_public is not None
    return (
        result.status,
        result.action,
        result.rpc_method,
        result.rpc_params,
        len(result.rpc_observations),
        result.after.settled,
        len(result.after.polls),
        result.error,
        backend.current_public,
        canonical_private_state(backend._backend._gs),
    )


def _run_bounded_branch(
    clone_factory,
    observation,
    history: tuple[PublicHistoryStep, ...],
    root,
    *,
    max_steps: int,
):
    """Run one root and a deterministic public-policy continuation."""

    backend = clone_factory()
    policy = PublicStrategicPolicy()
    current = observation
    branch_history = list(history)
    action = root
    trajectory = []
    try:
        for _ in range(max_steps):
            result = backend.step(action)
            trajectory.append(_step_projection(result, backend))
            after = backend.current_public
            assert after is not None
            branch_history.append(PublicHistoryStep(current, action, after))
            current = after
            if current.terminal:
                break
            action = policy.choose_action(
                current,
                lambda: iter_legal_actions(current),
                tuple(branch_history),
            )
        return tuple(trajectory)
    finally:
        backend.close()


def _evaluate_roots(
    clone_factory,
    observation,
    history: tuple[PublicHistoryStep, ...],
    roots,
):
    return {
        _action_key(root): _run_bounded_branch(
            clone_factory, observation, history, root, max_steps=1
        )
        for root in roots
    }


def test_sample_seed_depends_only_on_public_digest_nonce_and_index() -> None:
    for backend, observation, _ in _organic_states("3", phases={Phase.SHOP}, limit=1):
        twin = deepcopy(observation)
        assert sample_seed(observation, "n", 0) == sample_seed(twin, "n", 0)
        assert sample_seed(observation, "n", 0) != sample_seed(observation, "n", 1)
        assert sample_seed(observation, "n", 0) != sample_seed(observation, "m", 0)
        with pytest.raises(ValueError):
            sample_seed(observation, "n", -1)


def test_frozen_backend_matches_legacy_clone_and_preserves_bridge_fields() -> None:
    for backend, observation, _ in _organic_states("3", phases={Phase.SHOP}, limit=1):
        game_state = backend._backend._gs
        pack_cards = game_state.setdefault("pack_cards", [])
        backend._active_pack_cards = pack_cards
        backend._stale_shop_areas = {"test": {"cards": pack_cards}}
        backend._round_targets_rolled = True
        backend._pending_ante_setup = 7
        backend._poker_hand_iteration_order = ("Pair", "High Card")
        backend._pack_card_limit = len(pack_cards)
        backend._won = True
        backend._pending_skip_dollars = 4
        frozen = freeze_backend(backend)
        legacy = _legacy_clone_backend(backend)
        loaded = frozen.clone()
        try:
            assert isinstance(frozen, FrozenJackdawBackend)
            assert canonical_private_state(
                loaded._backend._gs
            ) == canonical_private_state(legacy._backend._gs)
            assert loaded.current_public == legacy.current_public == observation
            assert loaded._current == legacy._current
            assert loaded._current is backend._current
            assert loaded.current_public is backend.current_public
            for name in (
                "_round_targets_rolled",
                "_pending_ante_setup",
                "_poker_hand_iteration_order",
                "_pack_card_limit",
                "_won",
                "_pending_skip_dollars",
            ):
                assert getattr(loaded, name) == getattr(legacy, name)
            assert loaded._active_pack_cards is loaded._backend._gs["pack_cards"]
            assert (
                loaded._stale_shop_areas["test"]["cards"] is loaded._active_pack_cards
            )
        finally:
            loaded.close()
            legacy.close()
        return
    pytest.skip("no shop reached in the fixture run")


def test_frozen_backend_loads_repeated_independent_clones() -> None:
    for backend, _, _ in _organic_states("3", phases={Phase.SHOP}, limit=1):
        backend._active_pack_cards = backend._backend._gs.setdefault("pack_cards", [])
        backend._stale_shop_areas = {"test": {"cards": backend._active_pack_cards}}
        frozen = freeze_backend(backend)
        expected = frozen.clone()
        expected_state = canonical_private_state(expected._backend._gs)
        expected.close()

        backend._backend._gs["dollars"] += 1_000
        left = frozen.clone()
        right = frozen.clone()
        try:
            assert left._backend._gs is not right._backend._gs
            assert left._active_pack_cards is not right._active_pack_cards
            assert left._stale_shop_areas is not right._stale_shop_areas
            left._backend._gs["dollars"] += 99
            left._stale_shop_areas["test"]["mutated"] = True
            left._round_targets_rolled = not left._round_targets_rolled

            assert canonical_private_state(right._backend._gs) == expected_state
            assert "mutated" not in right._stale_shop_areas["test"]
            assert right._round_targets_rolled == backend._round_targets_rolled
            with pytest.raises(FrozenInstanceError):
                frozen._payload = b"changed"  # type: ignore[misc]
        finally:
            left.close()
            right.close()
        return
    pytest.skip("no shop reached in the fixture run")


def test_refrozen_sampled_clones_own_independent_normalized_frames() -> None:
    for backend, observation, history in _organic_states(
        "3", phases={Phase.SHOP}, limit=1
    ):
        sample = sample_candidate(
            backend, observation, history, sample_seed(observation, "frame", 0)
        )
        try:
            frozen = freeze_backend(sample)
        finally:
            sample.close()

        left = frozen.clone()
        right = frozen.clone()
        try:
            assert left._lightweight_normalized is not None
            assert right._lightweight_normalized is not None
            assert left._lightweight_normalized == right._lightweight_normalized
            assert left._lightweight_normalized is not right._lightweight_normalized

            left._lightweight_normalized["test_mutation"] = True

            assert "test_mutation" not in right._lightweight_normalized
        finally:
            left.close()
            right.close()
        return
    pytest.skip("no shop reached in the fixture run")


def test_refrozen_sampled_clone_steps_without_json_round_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for backend, observation, history in _organic_states(
        "3", phases={Phase.SHOP}, limit=1
    ):
        action = PublicStrategicPolicy().choose_action(
            observation, lambda: iter_legal_actions(observation), history
        )
        sample = sample_candidate(
            backend, observation, history, sample_seed(observation, "frame", 0)
        )
        try:
            frozen = freeze_backend(sample)
        finally:
            sample.close()
        clone = frozen.clone()

        def unexpected_json(*_args, **_kwargs):
            raise AssertionError("lightweight rollout performed a JSON round trip")

        try:
            with monkeypatch.context() as patch:
                patch.setattr(json, "loads", unexpected_json)
                patch.setattr(json, "dumps", unexpected_json)
                result = clone.step(action)
            assert result.status == "accepted", result.error
            assert result.rpc_observations == ()
            assert result.after is not None
            assert result.after.observed.raw_json == ""
            assert clone.current_public is not None
        finally:
            clone.close()
        return
    pytest.skip("no shop reached in the fixture run")


def test_normal_frozen_clone_bootstraps_json_once_then_owns_the_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for backend, observation, history in _organic_states(
        "3", phases={Phase.SHOP}, limit=1
    ):
        action = PublicStrategicPolicy().choose_action(
            observation, lambda: iter_legal_actions(observation), history
        )
        clone = freeze_backend(backend).clone()
        original_loads = json.loads
        original_dumps = json.dumps
        calls = {"loads": 0, "dumps": 0}

        def counting_loads(*args, **kwargs):
            calls["loads"] += 1
            return original_loads(*args, **kwargs)

        def counting_dumps(*args, **kwargs):
            calls["dumps"] += 1
            return original_dumps(*args, **kwargs)

        try:
            with monkeypatch.context() as patch:
                patch.setattr(json, "loads", counting_loads)
                patch.setattr(json, "dumps", counting_dumps)
                first = clone.step(action)
                assert first.status == "accepted", first.error
                assert clone.current_public is not None
                second_action = next(iter_legal_actions(clone.current_public))
                second = clone.step(second_action)
                assert second.status == "accepted", second.error
            assert calls == {"loads": 1, "dumps": 0}
        finally:
            clone.close()
        return
    pytest.skip("no shop reached in the fixture run")


def test_frozen_backend_repr_never_contains_private_payload() -> None:
    for backend, _, _ in _organic_states("11", phases={Phase.SHOP}, limit=1):
        frozen = freeze_backend(backend)

        rendered = repr(frozen)

        assert "_payload" not in rendered
        assert "_current" not in rendered
        assert repr(frozen._payload) not in rendered
        return
    pytest.skip("no organic shop reached")


def test_sample_candidate_closes_clone_when_validation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Clone:
        def __init__(self) -> None:
            self._backend = type("Backend", (), {"_gs": {}})()
            self.closed = False

        def close(self) -> None:
            self.closed = True

    def reject(_game_state) -> None:
        raise DeterminizationUnavailable("injected validation failure")

    clone = Clone()
    monkeypatch.setattr(determinize_module, "clone_backend", lambda backend: clone)
    monkeypatch.setattr(determinize_module, "_require_visible_private_state", reject)
    observation = to_public_observation(state("SHOP"))

    with pytest.raises(DeterminizationUnavailable, match="injected"):
        sample_candidate(None, observation, (), "PUBLICSEED")  # type: ignore[arg-type]

    assert clone.closed


def test_clone_backend_remains_a_one_shot_frozen_clone() -> None:
    for backend, observation, _ in _organic_states("3", phases={Phase.SHOP}, limit=1):
        clone = clone_backend(backend)
        try:
            assert clone.current_public == observation
            assert canonical_private_state(
                clone._backend._gs
            ) == canonical_private_state(backend._backend._gs)
        finally:
            clone.close()
        return
    pytest.skip("no shop reached in the fixture run")


def test_frozen_clone_behavior_matches_legacy_on_organic_strategic_states() -> None:
    wanted = {Phase.BLIND_SELECT, Phase.SHOP, Phase.PACK}
    checked: set[Phase] = set()
    states = _organic_states("11", phases=wanted, limit=40)
    try:
        for backend, observation, history in states:
            if observation.phase in checked:
                continue

            roots = _bounded_legal_roots(observation)
            assert len(roots) >= 2
            frozen = freeze_backend(backend)

            def legacy_factory():
                return _legacy_clone_backend(backend)

            legacy_results = _evaluate_roots(
                legacy_factory, observation, history, roots
            )
            frozen_forward = _evaluate_roots(frozen.clone, observation, history, roots)
            frozen_reverse = _evaluate_roots(
                frozen.clone, observation, history, tuple(reversed(roots))
            )

            # Every selected legal sibling has exactly the legacy transition,
            # regardless of which other frozen sibling is evaluated first.
            assert frozen_forward == legacy_results
            assert frozen_reverse == legacy_results

            continuation_root = PublicStrategicPolicy().choose_action(
                observation,
                lambda: iter_legal_actions(observation),
                history,
            )
            legacy_trajectory = _run_bounded_branch(
                legacy_factory,
                observation,
                history,
                continuation_root,
                max_steps=6,
            )
            frozen_trajectory = _run_bounded_branch(
                frozen.clone,
                observation,
                history,
                continuation_root,
                max_steps=6,
            )
            assert frozen_trajectory == legacy_trajectory

            checked.add(observation.phase)
            if checked == wanted:
                break
    finally:
        states.close()

    assert checked == wanted


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


def test_face_down_joker_order_fails_before_private_backend_access() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(name="Amber Acorn", status="CURRENT")
    raw["jokers"] = {
        "cards": [hidden_joker_slot(), hidden_joker_slot()],
        "count": 2,
        "highlighted_limit": 1,
        "limit": 5,
    }
    observation = to_public_observation(raw)

    with pytest.raises(
        DeterminizationUnavailable,
        match="face-down Joker order cannot be resampled soundly",
    ):
        sample_candidate(object(), observation, (), "unused")  # type: ignore[arg-type]


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
        assert any(
            "continuation_exception:RuntimeError" in reason
            for reason, _ in policy.last_decision.rejection_reasons
        )
