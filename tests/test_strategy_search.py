from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

import balatro_ai_v2.determinized_search as search_module
from balatro_ai_v2.actions import (
    BuyShopCard,
    LeaveShop,
    PlayCards,
    RerollShop,
    SelectBlind,
    ShopSlot,
    iter_legal_actions,
)
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.baselines import PublicStrategicPolicy
from balatro_ai_v2.determinized_search import (
    DeterminizedSearchPolicy,
    RolloutBudget,
    RolloutOutcome,
    SuccessTeacherBudget,
    SuccessTerminalActionBudget,
    _dense_teacher_indexes,
    _public_best_hand_score,
    _required_positive_discordances,
    _select_goal_root,
    _teacher_target,
    _terminal_action_relation,
)
from balatro_ai_v2.public_state import PublicItem
from balatro_ai_v2.policy import NoPublicProgressAction, PublicHistoryStep
from balatro_ai_v2.strategy_engine import GoalUtility, RouteStage, RunGoal, RunRoute
from balatro_ai_v2.strategy_options import (
    PersistentIntent,
    PersistentRoute,
    StrategicOption,
    StrategyCandidateRoot,
    StrategyIntent,
)
from balatro_ai_v2.strategy_teacher import StrategyTargetEndpoint
from state_factory import state


def _utility(
    *,
    win: float = 0.0,
    clear: float = 0.0,
    progress: float = 0.0,
    ante: float = 0.0,
    score: float = 0.0,
) -> GoalUtility:
    return GoalUtility(win, clear, progress, ante, score)


def test_victory_selector_never_trades_a_win_for_endless_score() -> None:
    values = (
        (_utility(win=1, clear=1, progress=8, score=2),),
        (_utility(win=0, clear=1, progress=99, ante=99, score=300),),
    )

    assert _select_goal_root(values, 0, RunGoal.VICTORY, 0) == 0


def test_endless_selector_uses_ante_then_log_score() -> None:
    values = (
        (_utility(win=1, ante=10, score=20),),
        (_utility(win=1, ante=10, score=21),),
        (_utility(win=1, ante=11, score=1),),
    )

    assert _select_goal_root(values, 0, RunGoal.ENDLESS, 0) == 2


def test_endless_selector_does_not_trade_liveness_for_score_at_same_ante() -> None:
    alive = _utility(win=1, ante=10, progress=10, score=1)
    dead = GoalUtility(
        1,
        1,
        10.99,
        endless_ante=10,
        log_score=300,
        alive_probability=0,
    )

    assert _select_goal_root(((alive,), (dead,)), 0, RunGoal.ENDLESS, 0) == 0


def test_uncertain_higher_priority_delta_cannot_be_rescued_by_score() -> None:
    baseline = (
        _utility(win=1, progress=8, score=1),
        _utility(win=0, progress=8, score=1),
    )
    noisy = (
        _utility(win=0, progress=100, score=100),
        _utility(win=1, progress=100, score=100),
    )

    assert _select_goal_root((baseline, noisy), 0, RunGoal.VICTORY, 1) == 0


def test_exact_higher_priority_tie_allows_survival_comparison() -> None:
    baseline = (_utility(clear=0.5, progress=1), _utility(clear=0.5, progress=1))
    better = (_utility(clear=0.5, progress=2), _utility(clear=0.5, progress=2))

    assert _select_goal_root((baseline, better), 0, RunGoal.VICTORY, 1) == 1


def test_truncated_or_rejected_root_is_ineligible_to_override() -> None:
    baseline = (_utility(progress=1),)
    apparently_better = (_utility(progress=100),)

    assert (
        _select_goal_root(
            (baseline, apparently_better),
            0,
            RunGoal.VICTORY,
            0,
            admissible=(True, False),
        )
        == 0
    )


def test_unknown_owned_mechanics_disable_only_specialist_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        jokers=(PublicItem("j_future_mod", "Future", "JOKER"),),
    )
    continuation = PublicStrategicPolicy()
    baseline = continuation.choose_action(
        observation, lambda: iter_legal_actions(observation), ()
    )
    _install_strategy_root_harness(
        monkeypatch,
        (StrategyCandidateRoot(baseline, None),),
        better_index=0,
    )
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=continuation,
        enable_strategy_options=True,
    )

    selected = policy.choose_action(
        observation, lambda: iter_legal_actions(observation), ()
    )

    assert selected == baseline
    assert policy.last_decision is not None
    assert policy.last_decision.unavailable_reason is None
    assert (
        policy.last_decision.specialist_unavailable_reason
        == "unsupported_public_state:unknown_owned_joker"
    )
    assert policy.counters.searched == 1


def test_unknown_active_voucher_disables_only_specialist_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        used_vouchers=("v_future_mod",),
    )
    continuation = PublicStrategicPolicy()
    baseline = continuation.choose_action(
        observation, lambda: iter_legal_actions(observation), ()
    )
    _install_strategy_root_harness(
        monkeypatch,
        (StrategyCandidateRoot(baseline, None),),
        better_index=0,
    )
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=continuation,
        enable_strategy_options=True,
    )

    assert (
        policy.choose_action(observation, lambda: iter_legal_actions(observation), ())
        == baseline
    )
    assert policy.last_decision is not None
    assert policy.last_decision.unavailable_reason is None
    assert (
        policy.last_decision.specialist_unavailable_reason
        == "unsupported_public_state:unknown_used_voucher"
    )
    assert policy.counters.searched == 1


def test_missing_route_continuation_disables_only_specialist_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnsafeIntentContinuation:
        control = PublicStrategicPolicy()

        def choose_action(self, observation, legal_actions, history):
            return self.control.choose_action(observation, legal_actions, history)

        def choose_action_for_intent(self, observation, legal_actions, history, intent):
            return self.control.choose_action(observation, legal_actions, history)

    observation = to_public_observation(state("SHOP", money=10))
    continuation = UnsafeIntentContinuation()
    baseline = continuation.choose_action(
        observation, lambda: iter_legal_actions(observation), ()
    )
    _install_strategy_root_harness(
        monkeypatch,
        (StrategyCandidateRoot(baseline, None),),
        better_index=0,
    )
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=continuation,
        enable_strategy_options=True,
    )

    assert (
        policy.choose_action(observation, lambda: iter_legal_actions(observation), ())
        == baseline
    )
    assert policy.last_decision is not None
    assert policy.last_decision.unavailable_reason is None
    assert (
        policy.last_decision.specialist_unavailable_reason
        == "route_continuation_unavailable"
    )
    assert policy.counters.searched == 1


def test_active_intent_controls_intervening_public_decisions() -> None:
    class IntentContinuation:
        calls: list[StrategyIntent] = []

        def choose_action(self, observation, legal_actions, history):
            return tuple(legal_actions())[0]

        def choose_action_for_intent(self, observation, legal_actions, history, intent):
            self.calls.append(intent)
            return tuple(legal_actions())[-1]

        def fork_for_rollout(self):
            return IntentContinuation()

    observation = to_public_observation(state("SELECTING_HAND"))
    legal = tuple(iter_legal_actions(observation))
    continuation = IntentContinuation()
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=continuation,  # type: ignore[arg-type]
        enable_strategy_options=True,
        active_intent=PersistentIntent(
            intent=StrategyIntent.RELIABLE_HAND,
            goal=RunGoal.VICTORY,
            started_ante=1,
            decisions=1,
            evidence=(),
        ),
    )

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == legal[-1]
    assert continuation.calls == [StrategyIntent.RELIABLE_HAND]


def test_active_route_controls_intervening_public_decisions() -> None:
    class RouteContinuation:
        calls: list[tuple[StrategyIntent | None, RunRoute]] = []

        def choose_action(self, observation, legal_actions, history):
            return tuple(legal_actions())[0]

        def choose_action_for_strategy(
            self, observation, legal_actions, history, intent, route
        ):
            self.calls.append((intent, route))
            return tuple(legal_actions())[-1]

        def fork_for_rollout(self, intent=None, route=None):
            return RouteContinuation()

    observation = to_public_observation(state("SELECTING_HAND"))
    legal = tuple(iter_legal_actions(observation))
    continuation = RouteContinuation()
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=continuation,  # type: ignore[arg-type]
        enable_strategy_options=True,
        active_route=PersistentRoute(
            route=RunRoute.HELD_RETRIGGER,
            stage=RouteStage.SEEDED,
            started_ante=1,
            decisions=1,
            pivots=0,
            evidence=(),
        ),
    )

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == legal[-1]
    assert continuation.calls == [(None, RunRoute.HELD_RETRIGGER)]


def test_victory_route_is_cleared_before_any_conditioned_decision() -> None:
    class TrackingContinuation:
        def __init__(self) -> None:
            self.ordinary_calls = 0
            self.strategy_calls = 0

        def choose_action(self, observation, legal_actions, history):
            del observation, history
            self.ordinary_calls += 1
            return tuple(legal_actions())[0]

        def choose_action_for_strategy(
            self, observation, legal_actions, history, intent, route
        ):
            del observation, history, intent, route
            self.strategy_calls += 1
            return tuple(legal_actions())[-1]

    observation = to_public_observation(state("SELECTING_HAND"))
    legal = tuple(iter_legal_actions(observation))
    engine = search_module.derive_engine_state(observation)
    continuation = TrackingContinuation()
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=continuation,  # type: ignore[arg-type]
        enable_strategy_options=True,
        active_route=PersistentRoute.start(RunRoute.VICTORY, engine, ()),
    )

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == legal[0]
    assert continuation.ordinary_calls == 1
    assert continuation.strategy_calls == 0
    assert policy.active_route is None
    assert policy.active_intent is None


def test_public_dead_end_is_a_losing_rollout_not_a_rejected_root() -> None:
    before = to_public_observation(state("BLIND_SELECT"))
    raw_dead_end = state("SELECTING_HAND")
    raw_dead_end["hand"]["cards"] = []
    raw_dead_end["hand"]["count"] = 0
    raw_dead_end["round"].update(hands_left=1, discards_left=0)
    dead_end = to_public_observation(raw_dead_end)

    class DeadEndClone:
        current_public = dead_end

        def step(self, action):
            del action
            return SimpleNamespace(status="accepted", after=SimpleNamespace())

    class DeadEndContinuation:
        def choose_action(self, observation, legal_actions, history):
            del observation, legal_actions, history
            raise NoPublicProgressAction("synthetic public dead end")

    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=DeadEndContinuation(),  # type: ignore[arg-type]
    )

    outcome = policy._rollout(  # noqa: SLF001 - exact rollout contract regression
        DeadEndClone(),  # type: ignore[arg-type]
        before,
        (),
        SelectBlind(),
    )

    assert not outcome.rejected
    assert outcome.rejection_reason is None
    assert not outcome.terminal_action_admissible
    assert outcome.goal_utility is not None
    assert outcome.goal_utility.alive_probability == 0


def test_rollout_fails_closed_when_clone_omits_public_projection() -> None:
    before = to_public_observation(state("BLIND_SELECT"))

    class MissingProjectionClone:
        current_public = None

        def step(self, action):
            del action
            return SimpleNamespace(status="accepted", after=SimpleNamespace())

    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=PublicStrategicPolicy(),
    )

    outcome = policy._rollout(  # noqa: SLF001 - exact rollout contract regression
        MissingProjectionClone(),  # type: ignore[arg-type]
        before,
        (),
        SelectBlind(),
    )

    assert outcome.rejected
    assert outcome.rejection_reason == "missing_public_projection"
    assert outcome.goal_utility is not None
    assert outcome.goal_utility.alive_probability == 0


def test_success_anchor_schedule_is_sparse_per_public_ante() -> None:
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=PublicStrategicPolicy(),
        success_teacher=SuccessTeacherBudget(),
    )
    shop = replace(to_public_observation(state("SHOP")), ante=4, antes_cleared=3)
    pack = replace(
        to_public_observation(state("BUFFOON_PACK")), ante=4, antes_cleared=3
    )

    assert policy._is_success_anchor(shop)  # noqa: SLF001
    assert not policy._is_success_anchor(shop)  # noqa: SLF001
    assert policy._is_success_anchor(pack)  # noqa: SLF001
    assert not policy._is_success_anchor(pack)  # noqa: SLF001


def test_teacher_score_target_includes_typed_public_prefix() -> None:
    before = to_public_observation(state("SELECTING_HAND"))
    after = replace(before, round=replace(before.round, chips=12_345))
    action = next(
        action for action in iter_legal_actions(before) if isinstance(action, PlayCards)
    )
    history = (PublicHistoryStep(before, action, after),)

    assert _public_best_hand_score(history) == 12_345


def test_dense_teacher_marks_observed_horizon_victory_as_exact() -> None:
    outcome = RolloutOutcome(
        value=3.0,
        steps=2,
        rejected=False,
        goal_utility=_utility(win=1, clear=1, progress=3, ante=8),
        endpoint=StrategyTargetEndpoint.HORIZON,
    )

    target = _teacher_target(outcome, 7, RunGoal.VICTORY)

    assert target.ante8_win == 1.0
    assert target.endpoint == StrategyTargetEndpoint.HORIZON


def test_dense_teacher_reuses_paired_ordinary_search_without_changing_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Sample:
        def close(self) -> None:
            pass

    class Frozen:
        def clone(self):
            return SimpleNamespace(close=lambda: None)

    monkeypatch.setattr(search_module, "sample_candidate", lambda *args: Sample())
    monkeypatch.setattr(search_module, "freeze_backend", lambda sample: Frozen())
    monkeypatch.setattr(
        search_module, "_teacher_config_digest", lambda policy: "1" * 64
    )

    def rollout(self, clone, observation, history, root, **kwargs):
        del self, clone, observation, history, kwargs
        value = 2.0 if isinstance(root, RerollShop) else 1.0
        return RolloutOutcome(
            value=value,
            steps=1,
            rejected=False,
            goal_utility=_utility(clear=1, progress=value, ante=1),
        )

    monkeypatch.setattr(DeterminizedSearchPolicy, "_rollout", rollout)
    observation = to_public_observation(state("SHOP", money=10))
    legal = tuple(iter_legal_actions(observation))

    class FirstContinuation:
        def choose_action(self, observation, legal_actions, history):
            del observation, history
            return next(
                action for action in legal_actions() if isinstance(action, LeaveShop)
            )

    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=FirstContinuation(),  # type: ignore[arg-type]
        budget=RolloutBudget(samples=2, horizon_antes=1, override_z=0),
        collect_dense_teacher=True,
    )

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert isinstance(selected, RerollShop)
    assert len(policy.teacher_drafts) == 1
    draft = policy.teacher_drafts[0]
    assert draft.candidates[draft.selected_index].action == selected
    assert draft.candidates[draft.baseline_index].action != selected
    assert draft.ordinary_index == draft.baseline_index
    assert draft.behavior_index == draft.selected_index
    assert all(len(candidate.samples) == 2 for candidate in draft.candidates)
    assert {
        sample.search_utility
        for candidate in draft.candidates
        for sample in candidate.samples
    } == {1.0, 2.0}


def test_route_terminal_teacher_separates_ordinary_behavior_and_selected_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Sample:
        def close(self) -> None:
            pass

    class Frozen:
        def clone(self):
            return SimpleNamespace(close=lambda: None)

    monkeypatch.setattr(search_module, "sample_candidate", lambda *args: Sample())
    monkeypatch.setattr(search_module, "freeze_backend", lambda sample: Frozen())
    monkeypatch.setattr(
        search_module, "_teacher_config_digest", lambda policy: "1" * 64
    )

    def rollout(self, clone, observation, history, root, **kwargs):
        del self, clone, observation, history, root
        route = kwargs.get("route")
        return _terminal_outcome(won=route == RunRoute.PLAYED_RETRIGGER)

    monkeypatch.setattr(DeterminizedSearchPolicy, "_rollout", rollout)
    selected_baselines: list[int] = []
    select_goal_root = search_module._select_goal_root

    def capture_baseline(utilities, baseline_index, goal, override_z, admissible=None):
        selected_baselines.append(baseline_index)
        return select_goal_root(
            utilities,
            baseline_index,
            goal,
            override_z,
            admissible,
        )

    monkeypatch.setattr(search_module, "_select_goal_root", capture_baseline)
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        ante=4,
        antes_cleared=3,
    )
    roots = (
        StrategyCandidateRoot(LeaveShop(), None),
        StrategyCandidateRoot(RerollShop(), None),
        StrategyCandidateRoot(
            RerollShop(),
            StrategyIntent.HELD_RETRIGGER_ENGINE,
            route=RunRoute.HELD_RETRIGGER,
        ),
        StrategyCandidateRoot(
            RerollShop(),
            StrategyIntent.PLAYED_RETRIGGER_ENGINE,
            route=RunRoute.PLAYED_RETRIGGER,
        ),
    )
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=PublicStrategicPolicy(),
        success_teacher=SuccessTeacherBudget(samples=2),
    )

    executed = policy._collect_success_teacher(  # noqa: SLF001
        observation,
        (),
        roots,
        behavior_index=2,
        ordinary_index=0,
        intent_aware=True,
        engine_goal=RunGoal.VICTORY,
    )

    assert executed == 2
    assert len(policy.teacher_drafts) == 1
    draft = policy.teacher_drafts[0]
    assert draft.baseline_index == draft.ordinary_index == 0
    assert draft.behavior_index == 2
    assert draft.selected_index == 3
    assert draft.candidate_space_size == len(roots)
    assert draft.candidates[draft.ordinary_index].route is None
    assert draft.candidates[draft.behavior_index].route == RunRoute.HELD_RETRIGGER
    assert draft.candidates[draft.selected_index].route == RunRoute.PLAYED_RETRIGGER
    assert policy.last_success_decision is not None
    assert selected_baselines == [0]
    assert not policy.last_success_decision.affects_actions
    assert policy.last_success_decision.ordinary_index == 0
    assert policy.last_success_decision.behavior_index == 2
    assert policy.last_success_decision.teacher_selected_index == 3
    assert policy.last_success_decision.executed_index == 2
    assert policy.last_success_decision.as_dict()["ordinary"] == {
        "action": {"type": "leave_shop"},
        "intent": None,
        "route": None,
    }


def test_dense_teacher_requires_the_complete_root_set_within_bound() -> None:
    roots = (LeaveShop(), SelectBlind(), *(RerollShop() for _ in range(138)))

    first = _dense_teacher_indexes(
        roots,
        baseline_index=0,
        selected_index=139,
        limit=512,
    )

    assert first == tuple(range(140))
    with pytest.raises(ValueError, match="complete-root cap"):
        _dense_teacher_indexes(
            roots,
            baseline_index=0,
            selected_index=139,
            limit=64,
        )


def _terminal_outcome(*, won: bool, admissible: bool = True) -> RolloutOutcome:
    return RolloutOutcome(
        value=float(won),
        steps=1,
        rejected=False,
        goal_utility=_utility(win=float(won), ante=8 if won else 4, score=5),
        endpoint=(
            StrategyTargetEndpoint.VICTORY if won else StrategyTargetEndpoint.DEATH
        ),
        terminal_action_admissible=admissible,
    )


def _install_terminal_rollout_stub(
    monkeypatch: pytest.MonkeyPatch,
    *,
    candidate_wins: bool = True,
    candidate_admissible: bool = True,
) -> None:
    class Sample:
        def __init__(self, index: int) -> None:
            self.index = index

        def close(self) -> None:
            pass

    class Frozen:
        def __init__(self, sample: Sample) -> None:
            self.sample = sample

        def clone(self):
            return SimpleNamespace(
                sample_index=self.sample.index,
                close=lambda: None,
            )

    monkeypatch.setattr(
        search_module,
        "sample_candidate",
        lambda backend, observation, history, seed: Sample(int(seed[-1], 16)),
    )
    monkeypatch.setattr(search_module, "freeze_backend", Frozen)

    def rollout(self, clone, observation, history, root, **kwargs):
        intent = kwargs.get("intent")
        del self, clone, observation, history, kwargs
        if isinstance(root, RerollShop) or intent == StrategyIntent.ECONOMY:
            return _terminal_outcome(
                won=candidate_wins,
                admissible=candidate_admissible,
            )
        return _terminal_outcome(won=False)

    monkeypatch.setattr(DeterminizedSearchPolicy, "_rollout", rollout)


class _IntentTrackingContinuation:
    def __init__(self) -> None:
        self.intent_calls: list[StrategyIntent] = []

    def choose_action(self, observation, legal_actions, history):
        del observation, history
        actions = tuple(legal_actions())
        return next(
            (action for action in actions if isinstance(action, LeaveShop)),
            actions[0],
        )

    def choose_action_for_intent(self, observation, legal_actions, history, intent):
        del observation, history
        self.intent_calls.append(intent)
        return tuple(legal_actions())[-1]

    def fork_for_rollout(self, intent=None):
        del intent
        return _IntentTrackingContinuation()


class _RouteOnlyContinuation:
    def choose_action(self, observation, legal_actions, history):
        del observation, history
        actions = tuple(legal_actions())
        return next(
            (action for action in actions if isinstance(action, LeaveShop)),
            actions[0],
        )

    def choose_action_for_strategy(
        self, observation, legal_actions, history, intent, route
    ):
        del observation, history, intent, route
        actions = tuple(legal_actions())
        return next(
            (action for action in actions if isinstance(action, LeaveShop)),
            actions[0],
        )

    def fork_for_rollout(self, intent=None, route=None):
        del intent, route
        return _RouteOnlyContinuation()


def _install_strategy_root_harness(
    monkeypatch: pytest.MonkeyPatch,
    roots: tuple[StrategyCandidateRoot, ...],
    *,
    better_index: int,
    rejected_index: int | None = None,
    rejected_samples: frozenset[int] | None = None,
) -> dict[str, object]:
    captured: dict[str, object] = {}

    class Sample:
        def __init__(self, index: int) -> None:
            self.index = index

        def close(self) -> None:
            pass

    class Frozen:
        def __init__(self, sample: Sample) -> None:
            self.index = sample.index

        def clone(self):
            return SimpleNamespace(sample_index=self.index, close=lambda: None)

    sample_seeds: list[str] = []

    def sample_candidate(*args):
        sample_seeds.append(args[3])
        return Sample(len(sample_seeds) - 1)

    captured["sample_seeds"] = sample_seeds
    captured["rollout_samples"] = {}
    monkeypatch.setattr(search_module, "sample_candidate", sample_candidate)
    monkeypatch.setattr(search_module, "freeze_backend", Frozen)
    monkeypatch.setattr(
        search_module, "_teacher_config_digest", lambda policy: "1" * 64
    )

    def candidates(*args, **kwargs):
        captured.update(kwargs)
        captured["control_action"] = args[2]
        return roots

    monkeypatch.setattr(search_module, "build_strategy_candidates", candidates)

    def rollout(self, clone, observation, history, action, **kwargs):
        del self, observation, history
        identity = (action, kwargs.get("intent"), kwargs.get("route"))
        rollout_samples = captured["rollout_samples"]
        assert isinstance(rollout_samples, dict)
        rollout_samples.setdefault(identity, []).append(clone.sample_index)
        value = 2.0 if identity == roots[better_index].identity else 1.0
        rejected = (
            rejected_index is not None
            and identity == roots[rejected_index].identity
            and (
                rejected_samples is None
                or clone.sample_index in rejected_samples
            )
        )
        return RolloutOutcome(
            value=value,
            steps=1,
            rejected=rejected,
            goal_utility=_utility(clear=1, progress=value, ante=1),
            rejection_reason="synthetic_rejection" if rejected else None,
        )

    monkeypatch.setattr(DeterminizedSearchPolicy, "_rollout", rollout)
    return captured


def test_v16_overlay_preserves_exact_ordinary_search_without_specialist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, object, StrategyIntent | None, RunRoute | None, bool]] = []
    sample_seeds: list[str] = []
    captured: dict[str, object] = {}

    class Sample:
        def __init__(self, index: int) -> None:
            self.index = index

        def close(self) -> None:
            pass

    class Frozen:
        def __init__(self, sample: Sample) -> None:
            self.index = sample.index

        def clone(self):
            return SimpleNamespace(sample_index=self.index, close=lambda: None)

    def sample_candidate(*args):
        sample_seeds.append(args[3])
        return Sample(len(sample_seeds) - 1)

    monkeypatch.setattr(search_module, "sample_candidate", sample_candidate)
    monkeypatch.setattr(search_module, "freeze_backend", Frozen)
    monkeypatch.setattr(
        search_module, "_teacher_config_digest", lambda policy: "1" * 64
    )

    def candidates(*args, **kwargs):
        del kwargs
        captured["control_action"] = args[2]
        return ()

    monkeypatch.setattr(search_module, "build_strategy_candidates", candidates)

    def rollout(self, clone, observation, history, action, **kwargs):
        del self, observation, history
        calls.append(
            (
                clone.sample_index,
                action,
                kwargs.get("intent"),
                kwargs.get("route"),
                kwargs.get("isolate_continuation", False),
            )
        )
        value = 3.0 if isinstance(action, RerollShop) else 1.0
        return RolloutOutcome(
            value=value,
            steps=1,
            rejected=False,
            goal_utility=_utility(clear=1, progress=value, ante=1),
        )

    monkeypatch.setattr(DeterminizedSearchPolicy, "_rollout", rollout)
    observation = to_public_observation(state("SHOP", money=10))
    legal = tuple(iter_legal_actions(observation))
    budget = RolloutBudget(samples=2, horizon_antes=1, override_z=0)

    control = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=_RouteOnlyContinuation(),  # type: ignore[arg-type]
        budget=budget,
    )
    control_selected = control.choose_action(observation, lambda: iter(legal), ())
    control_calls = tuple(calls)
    control_seeds = tuple(sample_seeds)
    calls.clear()
    sample_seeds.clear()

    overlay = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=_RouteOnlyContinuation(),  # type: ignore[arg-type]
        budget=budget,
        enable_strategy_options=True,
    )
    overlay_selected = overlay.choose_action(observation, lambda: iter(legal), ())

    assert control_selected == overlay_selected == RerollShop()
    assert tuple(calls) == control_calls
    assert tuple(sample_seeds) == control_seeds
    assert len(sample_seeds) == budget.samples
    assert all(
        intent is route is None and not isolated
        for _, _, intent, route, isolated in calls
    )
    by_action: dict[object, list[int]] = {}
    for sample_index, action, _, _, _ in calls:
        by_action.setdefault(action, []).append(sample_index)
    assert all(indexes == [0, 1] for indexes in by_action.values())
    assert captured["control_action"] == RerollShop()
    assert overlay.active_intent is None
    assert overlay.active_route is None
    assert overlay.counters.changed == control.counters.changed
    assert overlay.counters.rejected_rollouts == control.counters.rejected_rollouts
    assert overlay.last_decision is not None
    assert overlay.last_decision.ordinary_selected == '{"type":"reroll_shop"}'
    assert not overlay.last_decision.specialist_override
    assert control.last_decision is not None
    assert control.last_decision.ordinary_roots == control.last_decision.roots
    assert control.last_decision.specialist_roots == 0


def test_single_ordinary_root_without_specialist_does_not_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OrdinaryOnly:
        def choose_action(self, observation, legal_actions, history):
            del observation, history
            return tuple(legal_actions())[0]

    monkeypatch.setattr(
        search_module,
        "sample_candidate",
        lambda *args: pytest.fail("single-root ordinary search must not sample"),
    )
    observation = to_public_observation(state("SHOP", money=0))
    only_action = LeaveShop()
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=OrdinaryOnly(),  # type: ignore[arg-type]
        enable_strategy_options=True,
    )

    selected = policy.choose_action(observation, lambda: iter((only_action,)), ())

    assert selected == only_action
    assert policy.last_decision is None
    assert policy.counters.searched == 0


def test_specialist_builder_failure_falls_back_to_ordinary_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_strategy_root_harness(
        monkeypatch,
        (StrategyCandidateRoot(LeaveShop(), None),),
        better_index=0,
    )

    def fail_builder(*args, **kwargs):
        del args, kwargs
        raise ValueError("synthetic candidate mismatch")

    monkeypatch.setattr(search_module, "build_strategy_candidates", fail_builder)
    observation = to_public_observation(state("SHOP", money=10))
    legal = tuple(iter_legal_actions(observation))
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=_RouteOnlyContinuation(),  # type: ignore[arg-type]
        budget=RolloutBudget(samples=1, horizon_antes=1, override_z=0),
        enable_strategy_options=True,
    )

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == LeaveShop()
    assert policy.last_decision is not None
    assert policy.last_decision.specialist_roots == 0
    assert policy.last_decision.specialist_unavailable_reason is not None
    assert policy.last_decision.specialist_unavailable_reason.startswith(
        "specialist_builder_exception:ValueError"
    )
    assert policy.counters.strategy_specialist_unavailable == 1
    assert not policy.teacher_drafts


def test_whole_search_unavailability_abandons_active_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        search_module,
        "sample_candidate",
        lambda *args: (_ for _ in ()).throw(
            search_module.DeterminizationUnavailable("synthetic unavailable")
        ),
    )
    observation = to_public_observation(state("SHOP", money=10))
    engine = search_module.derive_engine_state(observation)
    legal = tuple(iter_legal_actions(observation))
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=_RouteOnlyContinuation(),  # type: ignore[arg-type]
        enable_strategy_options=True,
        active_route=PersistentRoute.start(
            RunRoute.HELD_RETRIGGER, engine, ("visible_baron",)
        ),
    )

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == LeaveShop()
    assert policy.active_route is None
    assert policy.active_intent is None
    assert policy.counters.unavailable == 1
    assert policy.counters.strategy_route_abandonments == 1
    assert policy.counters.strategy_victory_escapes == 0


def test_specialist_root_bound_preserves_ordinary_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specialists = tuple(
        StrategyCandidateRoot(
            BuyShopCard(ShopSlot(index)),
            StrategyIntent.ECONOMY,
            route=RunRoute.HELD_RETRIGGER,
        )
        for index in range(129)
    )
    captured = _install_strategy_root_harness(
        monkeypatch,
        specialists,
        better_index=0,
    )
    observation = to_public_observation(state("SHOP", money=10))
    legal = tuple(iter_legal_actions(observation))
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=_RouteOnlyContinuation(),  # type: ignore[arg-type]
        budget=RolloutBudget(samples=1, horizon_antes=1, override_z=0),
        enable_strategy_options=True,
    )

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == LeaveShop()
    assert policy.last_decision is not None
    assert policy.last_decision.specialist_roots_generated == 129
    assert policy.last_decision.specialist_roots == 0
    assert (
        policy.last_decision.specialist_unavailable_reason
        == "specialist_root_bound_exceeded:129>128"
    )
    rollout_samples = captured["rollout_samples"]
    assert isinstance(rollout_samples, dict)
    assert not any(identity in rollout_samples for identity in (root.identity for root in specialists))


def test_specialist_is_gated_against_ordinary_search_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    option = StrategicOption(
        StrategyIntent.RELIABLE_HAND,
        LeaveShop(),
        ("synthetic_held_route",),
        RunRoute.HELD_RETRIGGER,
    )
    specialist = StrategyCandidateRoot(
        option.first_action, option.intent, option, option.route
    )
    captured = _install_strategy_root_harness(
        monkeypatch,
        (specialist,),
        better_index=0,
    )

    def rollout(self, clone, observation, history, action, **kwargs):
        del self, observation, history
        identity = (action, kwargs.get("intent"), kwargs.get("route"))
        rollout_samples = captured["rollout_samples"]
        assert isinstance(rollout_samples, dict)
        rollout_samples.setdefault(identity, []).append(clone.sample_index)
        value = (
            3.0
            if isinstance(action, RerollShop) and identity[1:] == (None, None)
            else 2.0
            if identity == specialist.identity
            else 1.0
        )
        return RolloutOutcome(
            value=value,
            steps=1,
            rejected=False,
            goal_utility=_utility(clear=1, progress=value, ante=1),
        )

    monkeypatch.setattr(DeterminizedSearchPolicy, "_rollout", rollout)
    observation = to_public_observation(state("SHOP", money=10))
    legal = tuple(iter_legal_actions(observation))
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=_RouteOnlyContinuation(),  # type: ignore[arg-type]
        budget=RolloutBudget(samples=2, horizon_antes=1, override_z=0),
        enable_strategy_options=True,
    )

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == RerollShop()
    assert captured["control_action"] == RerollShop()
    assert policy.active_route is None
    assert policy.counters.strategy_specialist_challenges == 1
    assert policy.counters.strategy_specialist_overrides == 0
    rollout_samples = captured["rollout_samples"]
    assert isinstance(rollout_samples, dict)
    assert rollout_samples[(RerollShop(), None, None)] == [0, 1]
    assert rollout_samples[specialist.identity] == [0, 1]
    assert len(captured["sample_seeds"]) == 2
    assert policy.last_decision is not None
    assert policy.last_decision.specialist_paired_mean_delta == 0
    assert policy.last_decision.specialist_paired_lower_bound == 0


def test_active_specialist_retains_generic_action_only_with_paired_advantage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation = to_public_observation(state("SHOP", money=10))
    engine = search_module.derive_engine_state(observation)
    prior = PersistentRoute.start(
        RunRoute.HELD_RETRIGGER, engine, ("visible_baron",)
    )
    roots = (StrategyCandidateRoot(LeaveShop(), None, route=RunRoute.VICTORY),)
    _install_strategy_root_harness(monkeypatch, roots, better_index=0)

    def rollout(self, clone, observation, history, action, **kwargs):
        del self, clone, observation, history
        route = kwargs.get("route")
        value = (
            2.0
            if route == RunRoute.HELD_RETRIGGER and isinstance(action, LeaveShop)
            else 1.0
        )
        return RolloutOutcome(
            value=value,
            steps=1,
            rejected=False,
            goal_utility=_utility(clear=1, progress=value, ante=1),
        )

    monkeypatch.setattr(DeterminizedSearchPolicy, "_rollout", rollout)
    legal = tuple(iter_legal_actions(observation))
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=_RouteOnlyContinuation(),  # type: ignore[arg-type]
        budget=RolloutBudget(samples=2, horizon_antes=1, override_z=0),
        enable_strategy_options=True,
        active_route=prior,
    )

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == LeaveShop()
    assert policy.active_route is not None
    assert policy.active_route.route == RunRoute.HELD_RETRIGGER
    assert policy.active_route.started_ante == prior.started_ante
    assert policy.active_route.decisions == prior.decisions + 1
    assert policy.active_route.pivots == prior.pivots
    assert policy.counters.strategy_specialist_overrides == 1
    assert policy.counters.strategy_victory_escapes == 0
    assert policy.last_decision is not None
    assert policy.last_decision.specialist_paired_mean_delta == 1
    assert policy.last_decision.specialist_paired_lower_bound == 1


def test_route_only_continuation_preserves_candidate_intent_and_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    behavior = StrategyCandidateRoot(LeaveShop(), None, route=RunRoute.VICTORY)
    option = StrategicOption(
        StrategyIntent.ECONOMY,
        RerollShop(),
        ("retain_route_while_rerolling",),
        RunRoute.HELD_RETRIGGER,
    )
    candidate = StrategyCandidateRoot(
        option.first_action, option.intent, option, option.route
    )
    captured = _install_strategy_root_harness(
        monkeypatch, (behavior, candidate), better_index=1
    )
    observation = to_public_observation(state("SHOP", money=10))
    legal = tuple(iter_legal_actions(observation))
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=_RouteOnlyContinuation(),  # type: ignore[arg-type]
        budget=RolloutBudget(samples=1, horizon_antes=1, override_z=0),
        enable_strategy_options=True,
    )

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == RerollShop()
    assert captured["intent_aware"] is True
    assert captured["route_aware"] is True
    assert captured["control_action"] == LeaveShop()
    assert policy.active_intent is not None
    assert policy.active_intent.intent == StrategyIntent.ECONOMY
    assert policy.active_route is not None
    assert policy.active_route.route == RunRoute.HELD_RETRIGGER


def test_rejected_specialist_cannot_override_ordinary_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    option = StrategicOption(
        StrategyIntent.ECONOMY,
        RerollShop(),
        ("synthetic_rejected_specialist",),
        RunRoute.HELD_RETRIGGER,
    )
    candidate = StrategyCandidateRoot(
        option.first_action, option.intent, option, option.route
    )
    _install_strategy_root_harness(
        monkeypatch,
        (candidate,),
        better_index=0,
        rejected_index=0,
        rejected_samples=frozenset({1}),
    )
    observation = to_public_observation(state("SHOP", money=10))
    legal = tuple(iter_legal_actions(observation))
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=_RouteOnlyContinuation(),  # type: ignore[arg-type]
        budget=RolloutBudget(samples=2, horizon_antes=1, override_z=0),
        enable_strategy_options=True,
    )

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == LeaveShop()
    assert policy.active_route is None
    assert policy.counters.strategy_specialist_overrides == 0
    assert policy.counters.rejected_rollouts == 1
    assert policy.last_decision is not None
    assert not policy.last_decision.specialist_override
    assert policy.last_decision.specialist_roots == 1
    assert policy.last_decision.best_specialist_rejected
    assert any(
        reason.endswith("|synthetic_rejection")
        for reason, _ in policy.last_decision.rejection_reasons
    )
    assert not policy.teacher_drafts


@pytest.mark.parametrize("won", (False, True))
def test_specialized_route_can_escape_on_same_action_and_records_pivot(
    monkeypatch: pytest.MonkeyPatch,
    won: bool,
) -> None:
    action = LeaveShop()
    roots = (
        StrategyCandidateRoot(action, None, route=RunRoute.HELD_RETRIGGER),
        StrategyCandidateRoot(action, None, route=RunRoute.VICTORY),
    )
    _install_strategy_root_harness(monkeypatch, roots, better_index=1)
    observation = to_public_observation(state("SHOP", money=10))
    if won:
        observation = replace(observation, ante=9, antes_cleared=8, won=True)
    engine = search_module.derive_engine_state(observation)
    legal = tuple(iter_legal_actions(observation))
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=_RouteOnlyContinuation(),  # type: ignore[arg-type]
        budget=RolloutBudget(samples=1, horizon_antes=1, override_z=0),
        enable_strategy_options=True,
        active_route=PersistentRoute.start(
            RunRoute.HELD_RETRIGGER, engine, ("visible_baron",)
        ),
    )

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == action
    assert policy.last_decision is not None
    assert policy.last_decision.ordinary_selected == '{"type":"leave_shop"}'
    assert policy.active_intent is None
    assert policy.active_route is None
    assert policy.counters.changed == 0
    assert policy.counters.strategy_identity_changes == 0
    assert policy.counters.strategy_victory_escapes == 1
    assert policy.counters.strategy_route_transitions == {
        "held_retrigger->victory": 1
    }


def test_rollout_rejects_fork_that_loses_route_capability() -> None:
    class LostRouteFork(_RouteOnlyContinuation):
        def fork_for_rollout(self, intent=None, route=None):
            del intent, route
            return _IntentTrackingContinuation()

    observation = to_public_observation(state("SHOP"))
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=LostRouteFork(),  # type: ignore[arg-type]
    )

    outcome = policy._rollout(  # noqa: SLF001
        None,  # type: ignore[arg-type]
        observation,
        (),
        LeaveShop(),
        route=RunRoute.HELD_RETRIGGER,
        isolate_continuation=True,
    )

    assert outcome.rejected
    assert outcome.rejection_reason == "fork_lost_route_capability"


def _install_integrated_terminal_harness(
    monkeypatch: pytest.MonkeyPatch,
    roots: tuple[StrategyCandidateRoot, ...],
    *,
    candidate_result: str = "win",
) -> None:
    class Sample:
        def close(self) -> None:
            pass

    class Frozen:
        def __init__(self, sample: Sample) -> None:
            del sample

        def clone(self):
            return SimpleNamespace(close=lambda: None)

    monkeypatch.setattr(
        search_module,
        "sample_candidate",
        lambda backend, observation, history, seed: Sample(),
    )
    monkeypatch.setattr(search_module, "freeze_backend", Frozen)
    monkeypatch.setattr(
        search_module,
        "build_strategy_candidates",
        lambda *args, **kwargs: roots,
    )

    def rollout(self, clone, observation, history, root, **kwargs):
        del self, clone, observation, history
        intent = kwargs.get("intent")
        if kwargs.get("success_goal") is None:
            return _terminal_outcome(won=False)
        is_candidate = (
            root,
            intent,
            kwargs.get("route"),
        ) == roots[1].identity
        if not is_candidate:
            return _terminal_outcome(won=False)
        if candidate_result == "win":
            return _terminal_outcome(won=True)
        if candidate_result == "dead_end":
            return _terminal_outcome(won=True, admissible=False)
        if candidate_result == "rejected":
            return RolloutOutcome(
                value=1.0,
                steps=1,
                rejected=True,
                goal_utility=_utility(win=1, ante=8, score=5),
                rejection_reason="synthetic_rejection",
                endpoint=StrategyTargetEndpoint.VICTORY,
            )
        if candidate_result == "tie":
            return _terminal_outcome(won=False)
        raise AssertionError(f"unknown candidate result {candidate_result!r}")

    monkeypatch.setattr(DeterminizedSearchPolicy, "_rollout", rollout)


def _integrated_terminal_policy(
    continuation: _IntentTrackingContinuation,
) -> DeterminizedSearchPolicy:
    return DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=continuation,  # type: ignore[arg-type]
        nonce="integrated-terminal",
        budget=RolloutBudget(samples=1, horizon_antes=1, max_steps=20),
        success_teacher=SuccessTeacherBudget(samples=2, max_steps=20),
        success_terminal_actions=SuccessTerminalActionBudget(max_samples=5),
    )


def test_terminal_action_override_executes_legal_root_and_commits_its_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    behavior = StrategyCandidateRoot(LeaveShop(), None)
    option = StrategicOption(
        StrategyIntent.STABILIZE,
        RerollShop(),
        ("synthetic_terminal_override",),
    )
    candidate = StrategyCandidateRoot(option.first_action, option.intent, option)
    roots = (behavior, candidate)
    _install_integrated_terminal_harness(monkeypatch, roots)
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        ante=4,
        antes_cleared=3,
    )
    legal = tuple(iter_legal_actions(observation))
    continuation = _IntentTrackingContinuation()
    policy = _integrated_terminal_policy(continuation)

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == candidate.action
    assert selected in legal
    assert policy.active_intent is not None
    assert policy.active_intent.intent == StrategyIntent.STABILIZE
    assert policy.active_intent.decisions == 1
    assert policy.last_success_decision is not None
    assert policy.last_success_decision.behavior_index == 0
    assert policy.last_success_decision.executed_index == 1
    assert policy.last_success_decision.executed_action == candidate.action
    assert policy.last_success_decision.executed_intent == candidate.intent
    assert policy.counters.success_action_overrides == 1

    next_observation = to_public_observation(state("SELECTING_HAND"))
    next_legal = tuple(iter_legal_actions(next_observation))
    next_action = policy.choose_action(
        next_observation,
        lambda: iter(next_legal),
        (),
    )

    assert next_action == next_legal[-1]
    assert next_action in next_legal
    assert continuation.intent_calls == [StrategyIntent.STABILIZE]


def test_terminal_same_action_override_commits_distinct_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    behavior = StrategyCandidateRoot(LeaveShop(), None)
    option = StrategicOption(
        StrategyIntent.ECONOMY,
        LeaveShop(),
        ("synthetic_intent_override",),
    )
    candidate = StrategyCandidateRoot(option.first_action, option.intent, option)
    roots = (behavior, candidate)
    _install_integrated_terminal_harness(monkeypatch, roots)
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        ante=4,
        antes_cleared=3,
    )
    legal = tuple(iter_legal_actions(observation))
    continuation = _IntentTrackingContinuation()
    policy = _integrated_terminal_policy(continuation)

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == behavior.action == candidate.action
    assert selected in legal
    assert policy.active_intent is not None
    assert policy.active_intent.intent == StrategyIntent.ECONOMY
    assert policy.active_intent.decisions == 1
    assert policy.last_success_decision is not None
    assert policy.last_success_decision.identity_override
    assert policy.last_success_decision.behavior_action == selected
    assert policy.last_success_decision.behavior_intent is None
    assert policy.last_success_decision.executed_action == selected
    assert policy.last_success_decision.executed_intent == StrategyIntent.ECONOMY
    assert policy.counters.success_action_overrides == 0
    assert policy.counters.success_intent_only_overrides == 1


def test_terminal_same_action_override_commits_distinct_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = LeaveShop()
    behavior = StrategyCandidateRoot(action, None, route=RunRoute.VICTORY)
    candidate = StrategyCandidateRoot(
        action, None, route=RunRoute.HELD_RETRIGGER
    )
    _install_integrated_terminal_harness(monkeypatch, (behavior, candidate))
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        ante=4,
        antes_cleared=3,
    )
    legal = tuple(iter_legal_actions(observation))
    policy = _integrated_terminal_policy(_RouteOnlyContinuation())

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == action
    assert policy.active_intent is None
    assert policy.active_route is not None
    assert policy.active_route.route == RunRoute.HELD_RETRIGGER
    assert policy.last_success_decision is not None
    assert policy.last_success_decision.identity_override
    assert policy.last_success_decision.behavior_route is None
    assert policy.last_success_decision.executed_route == RunRoute.HELD_RETRIGGER
    assert policy.counters.success_action_overrides == 0
    assert policy.counters.success_intent_only_overrides == 0
    assert policy.counters.success_route_only_overrides == 1


@pytest.mark.parametrize(
    ("candidate_result", "fallback_reason"),
    [
        ("tie", "insufficient_terminal_dominance"),
        ("dead_end", "nonterminal_public_dead_end"),
        ("rejected", "rejected_root"),
    ],
)
def test_terminal_action_failures_execute_exact_behavior_identity(
    monkeypatch: pytest.MonkeyPatch,
    candidate_result: str,
    fallback_reason: str,
) -> None:
    behavior = StrategyCandidateRoot(LeaveShop(), None)
    option = StrategicOption(
        StrategyIntent.STABILIZE,
        RerollShop(),
        ("synthetic_rejected_override",),
    )
    candidate = StrategyCandidateRoot(option.first_action, option.intent, option)
    roots = (behavior, candidate)
    _install_integrated_terminal_harness(
        monkeypatch,
        roots,
        candidate_result=candidate_result,
    )
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        ante=4,
        antes_cleared=3,
    )
    legal = tuple(iter_legal_actions(observation))
    policy = _integrated_terminal_policy(_IntentTrackingContinuation())

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == behavior.action
    assert selected in legal
    assert policy.active_intent is None
    assert policy.last_strategy_selected_index == 0
    assert policy.last_success_decision is not None
    assert policy.last_success_decision.fallback_reason == fallback_reason
    assert policy.last_success_decision.behavior_index == 0
    assert policy.last_success_decision.teacher_selected_index == 0
    assert policy.last_success_decision.executed_index == 0
    assert policy.last_success_decision.behavior_action == selected
    assert policy.last_success_decision.behavior_intent is None
    assert policy.last_success_decision.executed_action == selected
    assert policy.last_success_decision.executed_intent is None
    assert not policy.last_success_decision.identity_override
    assert policy.counters.success_anchor_fallbacks == 1
    assert policy.counters.success_action_overrides == 0
    assert policy.counters.success_intent_only_overrides == 0


def test_terminal_action_selector_requires_root_adjusted_paired_dominance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_terminal_rollout_stub(monkeypatch)
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        ante=4,
        antes_cleared=3,
    )
    roots = (
        StrategyCandidateRoot(LeaveShop(), None),
        StrategyCandidateRoot(RerollShop(), StrategyIntent.ECONOMY),
    )
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=PublicStrategicPolicy(),
        success_teacher=SuccessTeacherBudget(samples=2),
        success_terminal_actions=SuccessTerminalActionBudget(max_samples=12),
    )

    selected = policy._collect_success_teacher(  # noqa: SLF001
        observation,
        (),
        roots,
        behavior_index=0,
        ordinary_index=0,
        intent_aware=False,
        engine_goal=RunGoal.VICTORY,
    )

    assert _required_positive_discordances(2, 0.05) == 5
    assert selected == 1
    assert not policy.teacher_drafts
    assert policy.last_success_decision is not None
    assert policy.last_success_decision.max_samples_used == 5
    assert policy.last_success_decision.positive_discordances == 5
    assert policy.last_success_decision.executed_intent == StrategyIntent.ECONOMY
    assert policy.counters.success_action_overrides == 1


def test_terminal_selector_cannot_bypass_scalar_specialist_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_terminal_rollout_stub(monkeypatch)
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        ante=4,
        antes_cleared=3,
    )
    roots = (
        StrategyCandidateRoot(LeaveShop(), None),
        StrategyCandidateRoot(
            RerollShop(),
            StrategyIntent.RELIABLE_HAND,
            route=RunRoute.HELD_RETRIGGER,
        ),
    )
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=PublicStrategicPolicy(),
        success_teacher=SuccessTeacherBudget(samples=2),
        success_terminal_actions=SuccessTerminalActionBudget(max_samples=12),
    )

    selected = policy._collect_success_teacher(  # noqa: SLF001
        observation,
        (),
        roots,
        behavior_index=0,
        ordinary_index=0,
        intent_aware=True,
        engine_goal=RunGoal.VICTORY,
        execution_admissible=(True, False),
    )

    assert selected == 0
    assert policy.last_success_decision is not None
    assert policy.last_success_decision.teacher_selected_index == 1
    assert policy.last_success_decision.executed_index == 0
    assert (
        policy.last_success_decision.fallback_reason
        == "specialist_not_scalar_admissible"
    )
    assert policy.active_route is None


def test_strategy_overlay_wires_terminal_specialist_admissibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    behavior = StrategyCandidateRoot(LeaveShop(), None, route=RunRoute.VICTORY)
    candidate = StrategyCandidateRoot(
        RerollShop(),
        StrategyIntent.RELIABLE_HAND,
        route=RunRoute.HELD_RETRIGGER,
    )
    _install_integrated_terminal_harness(monkeypatch, (behavior, candidate))
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        ante=4,
        antes_cleared=3,
    )
    legal = tuple(iter_legal_actions(observation))
    policy = _integrated_terminal_policy(_RouteOnlyContinuation())
    policy.enable_strategy_options = True
    policy.success_terminal_actions = SuccessTerminalActionBudget(max_samples=12)

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == LeaveShop()
    assert policy.last_decision is not None
    assert not policy.last_decision.specialist_override
    assert policy.last_success_decision is not None
    assert policy.last_success_decision.teacher_route == RunRoute.HELD_RETRIGGER
    assert policy.last_success_decision.executed_route is None
    assert (
        policy.last_success_decision.fallback_reason
        == "specialist_not_scalar_admissible"
    )
    assert policy.active_route is None


def test_terminal_action_selector_counts_same_action_intent_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_terminal_rollout_stub(monkeypatch)
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        ante=4,
        antes_cleared=3,
    )
    roots = (
        StrategyCandidateRoot(LeaveShop(), None),
        StrategyCandidateRoot(LeaveShop(), StrategyIntent.ECONOMY),
    )
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=PublicStrategicPolicy(),
        success_teacher=SuccessTeacherBudget(samples=2),
        success_terminal_actions=SuccessTerminalActionBudget(max_samples=12),
    )

    selected = policy._collect_success_teacher(  # noqa: SLF001
        observation,
        (),
        roots,
        behavior_index=0,
        ordinary_index=0,
        intent_aware=True,
        engine_goal=RunGoal.VICTORY,
    )

    assert selected == 1
    assert policy.counters.success_action_overrides == 0
    assert policy.counters.success_intent_only_overrides == 1


def test_terminal_action_selector_falls_back_on_nonterminal_dead_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_terminal_rollout_stub(monkeypatch, candidate_admissible=False)
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        ante=4,
        antes_cleared=3,
    )
    roots = (
        StrategyCandidateRoot(LeaveShop(), None),
        StrategyCandidateRoot(RerollShop(), StrategyIntent.ECONOMY),
    )
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=PublicStrategicPolicy(),
        success_teacher=SuccessTeacherBudget(samples=2),
        success_terminal_actions=SuccessTerminalActionBudget(max_samples=12),
    )

    selected = policy._collect_success_teacher(  # noqa: SLF001
        observation,
        (),
        roots,
        behavior_index=0,
        ordinary_index=0,
        intent_aware=False,
        engine_goal=RunGoal.VICTORY,
    )

    assert selected == 0
    assert policy.last_success_decision is not None
    assert policy.last_success_decision.fallback_reason == "nonterminal_public_dead_end"
    assert policy.counters.success_anchor_fallbacks == 1


def test_terminal_action_selector_keeps_early_anchor_inert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def forbidden_sample(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise AssertionError("early action anchor must not sample")

    monkeypatch.setattr(search_module, "sample_candidate", forbidden_sample)
    observation = replace(to_public_observation(state("SHOP", money=10)), ante=1)
    roots = (
        StrategyCandidateRoot(LeaveShop(), None),
        StrategyCandidateRoot(RerollShop(), StrategyIntent.ECONOMY),
    )
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=PublicStrategicPolicy(),
        success_teacher=SuccessTeacherBudget(samples=2),
        success_terminal_actions=SuccessTerminalActionBudget(max_samples=12),
    )

    assert (
        policy._collect_success_teacher(  # noqa: SLF001
            observation,
            (),
            roots,
            behavior_index=0,
            ordinary_index=0,
            intent_aware=False,
            engine_goal=RunGoal.VICTORY,
        )
        == 0
    )
    assert calls == 0
    assert policy.last_success_decision is not None
    assert policy.last_success_decision.fallback_reason == "early_anchor_inert"


def test_terminal_action_selector_enforces_compute_root_bound_without_sampling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        search_module,
        "sample_candidate",
        lambda *args, **kwargs: pytest.fail("unattainable bound must not sample"),
    )
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        ante=4,
        antes_cleared=3,
    )
    roots = tuple(
        StrategyCandidateRoot(LeaveShop(), StrategyIntent.ECONOMY) for _ in range(65)
    )
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=PublicStrategicPolicy(),
        success_teacher=SuccessTeacherBudget(samples=2),
        success_terminal_actions=SuccessTerminalActionBudget(max_samples=12),
    )

    selected = policy._collect_success_teacher(  # noqa: SLF001
        observation,
        (),
        roots,
        behavior_index=0,
        ordinary_index=0,
        intent_aware=True,
        engine_goal=RunGoal.VICTORY,
    )

    assert selected == 0
    assert policy.last_success_decision is not None
    assert policy.last_success_decision.fallback_reason == "root_compute_bound_exceeded"
    assert policy.last_success_decision.sample_evaluations == 0


def test_terminal_action_selector_skips_unattainable_statistical_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        search_module,
        "sample_candidate",
        lambda *args, **kwargs: pytest.fail("unattainable bound must not sample"),
    )
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        ante=4,
        antes_cleared=3,
    )
    roots = (
        StrategyCandidateRoot(LeaveShop(), None),
        StrategyCandidateRoot(RerollShop(), StrategyIntent.ECONOMY),
    )
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=PublicStrategicPolicy(),
        success_teacher=SuccessTeacherBudget(samples=2),
        success_terminal_actions=SuccessTerminalActionBudget(
            max_samples=12, family_alpha=1e-6
        ),
    )

    selected = policy._collect_success_teacher(  # noqa: SLF001
        observation,
        (),
        roots,
        behavior_index=0,
        ordinary_index=0,
        intent_aware=True,
        engine_goal=RunGoal.VICTORY,
    )

    assert selected == 0
    assert _required_positive_discordances(2, 1e-6) == 20
    assert policy.last_success_decision is not None
    assert (
        policy.last_success_decision.fallback_reason == "root_count_bound_unattainable"
    )
    assert policy.last_success_decision.sample_evaluations == 0


def test_terminal_determinization_unavailable_is_not_a_rejected_rollout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        search_module,
        "sample_candidate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            search_module.DeterminizationUnavailable("injected")
        ),
    )
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        ante=4,
        antes_cleared=3,
    )
    roots = (
        StrategyCandidateRoot(LeaveShop(), None),
        StrategyCandidateRoot(RerollShop(), StrategyIntent.ECONOMY),
    )
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=PublicStrategicPolicy(),
        success_teacher=SuccessTeacherBudget(samples=2),
        success_terminal_actions=SuccessTerminalActionBudget(),
    )

    selected = policy._collect_success_teacher(  # noqa: SLF001
        observation,
        (),
        roots,
        behavior_index=0,
        ordinary_index=0,
        intent_aware=True,
        engine_goal=RunGoal.VICTORY,
    )

    assert selected == 0
    assert policy.last_success_decision is not None
    assert policy.last_success_decision.unavailable
    assert policy.last_success_decision.rejected_rollouts == 0
    assert policy.counters.success_anchor_unavailable == 1
    assert policy.counters.success_teacher_rejected_rollouts == 0


def test_terminal_relation_ignores_nonterminal_progress_and_economy() -> None:
    baseline = RolloutOutcome(
        0,
        1,
        False,
        _utility(progress=1, ante=4, score=1),
        endpoint=StrategyTargetEndpoint.DEATH,
    )
    richer_loss = RolloutOutcome(
        100,
        1,
        False,
        GoalUtility(0, 1, 99, endless_ante=7, log_score=20, economy_reserve=99),
        endpoint=StrategyTargetEndpoint.DEATH,
    )
    win = _terminal_outcome(won=True)

    assert _terminal_action_relation(richer_loss, baseline, RunGoal.VICTORY) == 0
    assert _terminal_action_relation(win, baseline, RunGoal.VICTORY) == 1


def test_terminal_intent_is_committed_exactly_once() -> None:
    observation = to_public_observation(state("SHOP", money=10))
    engine = search_module.derive_engine_state(observation)
    option = StrategicOption(
        StrategyIntent.ECONOMY,
        LeaveShop(),
        ("synthetic",),
    )
    root = StrategyCandidateRoot(LeaveShop(), StrategyIntent.ECONOMY, option)
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=PublicStrategicPolicy(),
    )

    policy._commit_strategy_root(root, engine)  # noqa: SLF001

    assert policy.active_intent is not None
    assert policy.active_intent.intent == StrategyIntent.ECONOMY
    assert policy.active_intent.decisions == 1
