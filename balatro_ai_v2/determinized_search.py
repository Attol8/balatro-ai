"""Search at strategic decisions by determinized Jackdaw rollouts.

Parent-only.  ``DeterminizedSearchPolicy`` implements ``PublicPolicy`` for
the evaluator parent: it reads the public observation like any policy, but
values each legal strategic action by rolling sampled futures forward in the
candidate simulator. An admitted active strategy intent is revalidated through
the public continuation between strategic roots.

The decision sees per-root scalar values and aggregate diagnostics only.
Sampled states never leave this module.
"""

from __future__ import annotations

import json
import hashlib
import math
import time
from collections import Counter
from copy import deepcopy
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, is_dataclass

from balatro_ai_v2.actions import (
    PublicAction,
    ReorderConsumables,
    ReorderHand,
    ReorderJokers,
    action_to_data,
    iter_legal_actions,
)
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.determinize import (
    STRATEGIC_PHASES,
    DeterminizationUnavailable,
    clone_backend,
    sample_candidate,
    sample_seed,
)
from balatro_ai_v2.jackdaw import JackdawBackend
from balatro_ai_v2.policy import (
    ActionSource,
    NoPublicProgressAction,
    PublicHistoryStep,
    PublicPolicy,
)
from balatro_ai_v2.public_state import Phase, PublicObservation
from balatro_ai_v2.strategy_engine import GoalUtility, RunGoal, derive_engine_state
from balatro_ai_v2.strategy_options import (
    PersistentIntent,
    StrategyCandidateRoot,
    StrategyIntent,
    build_strategy_candidates,
)
from balatro_ai_v2.strategy_teacher import (
    StrategyRolloutTarget,
    StrategyTargetEndpoint,
    StrategyTeacherCandidate,
    StrategyTeacherDraft,
)


SEARCH_VERSION = "determinized-search-v5"
_REORDER_TYPES = (ReorderHand, ReorderJokers, ReorderConsumables)


@dataclass(frozen=True, slots=True)
class RolloutBudget:
    samples: int = 8
    horizon_antes: int = 2
    max_steps: int = 200
    override_z: float = 1.0

    def __post_init__(self) -> None:
        if self.samples < 1 or self.horizon_antes < 1 or self.max_steps < 1:
            raise ValueError("rollout budget values must be positive")
        if self.override_z < 0:
            raise ValueError("override_z must be non-negative")

    def canonical(self) -> str:
        return (
            f"samples={self.samples};horizon_antes={self.horizon_antes};"
            f"max_steps={self.max_steps};override_z={self.override_z}"
        )


@dataclass(frozen=True, slots=True)
class SuccessTeacherBudget:
    """Terminal objective labels collected without changing behavior."""

    samples: int = 2
    prewin_start_ante: int = 4
    endless_horizon_antes: int = 2
    max_steps: int = 600

    def __post_init__(self) -> None:
        if min(
            self.samples,
            self.prewin_start_ante,
            self.endless_horizon_antes,
            self.max_steps,
        ) < 1:
            raise ValueError("success teacher budget values must be positive")

    def canonical(self) -> str:
        return (
            f"samples={self.samples};prewin_start_ante={self.prewin_start_ante};"
            f"endless_horizon_antes={self.endless_horizon_antes};"
            f"max_steps={self.max_steps};anchors=first_shop_each_ante,"
            "first_pack_each_ante_from_ante4,boss_select_ante5_plus,"
            "postwin_first_shop_and_pack_each_ante"
        )


@dataclass(frozen=True, slots=True)
class RolloutOutcome:
    value: float
    steps: int
    rejected: bool
    goal_utility: GoalUtility | None = None
    rejection_reason: str | None = None
    endpoint: StrategyTargetEndpoint = StrategyTargetEndpoint.HORIZON


_SearchRoot = StrategyCandidateRoot


@dataclass(frozen=True, slots=True)
class SearchDecision:
    phase: str
    ante: int
    roots: int
    samples: int
    steps: int
    seconds: float
    rejected_rollouts: int
    values: tuple[tuple[str, float], ...]
    baseline: str
    selected: str
    unavailable_reason: str | None = None
    goal: str | None = None
    selected_intent: str | None = None
    goal_values: tuple[tuple[str, tuple[float, ...]], ...] = ()
    rejection_reasons: tuple[tuple[str, int], ...] = ()

    @property
    def changed(self) -> bool:
        return self.selected != self.baseline

    def as_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "ante": self.ante,
            "roots": self.roots,
            "samples": self.samples,
            "steps": self.steps,
            "seconds": self.seconds,
            "rejected_rollouts": self.rejected_rollouts,
            "values": [list(pair) for pair in self.values],
            "baseline": self.baseline,
            "selected": self.selected,
            "changed": self.changed,
            "unavailable_reason": self.unavailable_reason,
            "goal": self.goal,
            "selected_intent": self.selected_intent,
            "goal_values": [[label, list(value)] for label, value in self.goal_values],
            "rejection_reasons": [list(pair) for pair in self.rejection_reasons],
        }


@dataclass(slots=True)
class SearchCounters:
    strategic_decisions: int = 0
    searched: int = 0
    changed: int = 0
    unavailable: int = 0
    rollout_steps: int = 0
    rejected_rollouts: int = 0
    seconds: float = 0.0
    success_teacher_steps: int = 0
    success_teacher_rejected_rollouts: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "strategic_decisions": self.strategic_decisions,
            "searched": self.searched,
            "changed": self.changed,
            "unavailable": self.unavailable,
            "rollout_steps": self.rollout_steps,
            "rejected_rollouts": self.rejected_rollouts,
            "seconds": self.seconds,
            "success_teacher_steps": self.success_teacher_steps,
            "success_teacher_rejected_rollouts": self.success_teacher_rejected_rollouts,
            "steps_per_second": (self.rollout_steps / self.seconds)
            if self.seconds > 0
            else 0.0,
        }


@dataclass(slots=True)
class DeterminizedSearchPolicy:
    """Roots at strategic decisions, valued by paired determinized rollouts."""

    backend: JackdawBackend
    continuation: PublicPolicy
    nonce: str = "search-v1"
    budget: RolloutBudget = RolloutBudget()
    enable_strategy_options: bool = False
    include_reorders: bool = False
    success_teacher: SuccessTeacherBudget | None = None
    last_decision: SearchDecision | None = None
    counters: SearchCounters = field(default_factory=SearchCounters)
    decisions: list[SearchDecision] = field(default_factory=list)
    teacher_drafts: list[StrategyTeacherDraft] = field(default_factory=list)
    active_intent: PersistentIntent | None = None
    last_strategy_candidates: tuple[StrategyCandidateRoot, ...] = ()
    last_strategy_selected_index: int | None = None
    _success_shop_antes: set[int] = field(default_factory=set)
    _success_pack_antes: set[int] = field(default_factory=set)

    def reset_run(self) -> None:
        self.last_decision = None
        self.counters = SearchCounters()
        self.decisions = []
        self.teacher_drafts = []
        self.active_intent = None
        self.last_strategy_candidates = ()
        self.last_strategy_selected_index = None
        self._success_shop_antes = set()
        self._success_pack_antes = set()

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        choose_for_intent = getattr(self.continuation, "choose_action_for_intent", None)
        if self.active_intent is not None and callable(choose_for_intent):
            try:
                baseline = choose_for_intent(
                    observation,
                    legal_actions,
                    history,
                    self.active_intent.intent,
                )
            except Exception:
                # Intent assistance is optional. Its failure clears the stale
                # intent and returns to the ordinary public continuation.
                self.active_intent = None
                baseline = self.continuation.choose_action(
                    observation, legal_actions, history
                )
        else:
            baseline = self.continuation.choose_action(
                observation, legal_actions, history
            )
        self.last_decision = None
        self.last_strategy_candidates = ()
        self.last_strategy_selected_index = None
        if observation.phase not in STRATEGIC_PHASES:
            return baseline
        self.counters.strategic_decisions += 1
        if self.enable_strategy_options:
            return self._choose_strategy_option(observation, baseline, history)
        roots = [
            action
            for action in legal_actions()
            if not isinstance(action, _REORDER_TYPES)
        ]
        if baseline not in roots:
            roots.append(baseline)
        if len(roots) <= 1:
            return baseline

        started = time.perf_counter()
        samples: list[JackdawBackend] = []
        try:
            for index in range(self.budget.samples):
                samples.append(
                    sample_candidate(
                        self.backend,
                        observation,
                        history,
                        sample_seed(observation, self.nonce, index),
                    )
                )
        except DeterminizationUnavailable as exc:
            self.counters.unavailable += 1
            self._record(
                observation, roots, baseline, baseline, {}, 0, 0, started, str(exc)
            )
            return baseline

        values: list[list[float]] = [[] for _ in roots]
        steps = 0
        rejected = 0
        for sample in samples:
            for index, root in enumerate(roots):
                clone = clone_backend(sample)
                outcome = self._rollout(clone, observation, history, root)
                clone.close()
                values[index].append(outcome.value)
                steps += outcome.steps
                rejected += int(outcome.rejected)
            sample.close()

        count = len(samples)
        means = {index: sum(values[index]) / count for index in range(len(roots))}
        baseline_index = roots.index(baseline)
        selected_index = _select_root(values, baseline_index, self.budget.override_z)
        selected = roots[selected_index]
        self.counters.searched += 1
        self.counters.changed += int(selected != baseline)
        self._record(
            observation,
            roots,
            baseline,
            selected,
            {_label(roots[index]): value for index, value in means.items()},
            steps,
            rejected,
            started,
            None,
        )
        if self.success_teacher is not None and self._is_success_anchor(observation):
            engine = derive_engine_state(observation)
            unsupported = _strategy_unsupported(engine)
            if unsupported:
                self.counters.success_teacher_rejected_rollouts += 1
                self.counters.rejected_rollouts += 1
            else:
                intent_aware = callable(
                    getattr(self.continuation, "choose_action_for_intent", None)
                ) and callable(getattr(self.continuation, "fork_for_rollout", None))
                candidates = build_strategy_candidates(
                    observation,
                    tuple(iter_legal_actions(observation)),
                    selected,
                    include_reorders=self.include_reorders,
                    intent_aware=intent_aware,
                    engine=engine,
                )
                self.last_strategy_candidates = candidates
                self.last_strategy_selected_index = 0
                if len(candidates) > 1:
                    self._collect_success_teacher(
                        observation,
                        history,
                        candidates,
                        behavior_index=0,
                        intent_aware=intent_aware,
                        engine_goal=engine.goal,
                    )
        return selected

    def _choose_strategy_option(
        self,
        observation: PublicObservation,
        baseline: PublicAction,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        """Search legal option first-actions while retaining paired samples."""

        engine = derive_engine_state(observation)
        unsupported = _strategy_unsupported(engine)
        if unsupported:
            self.counters.unavailable += 1
            started = time.perf_counter()
            root = _SearchRoot(baseline, None)
            self._record_strategy(
                observation,
                (root,),
                baseline,
                root,
                (),
                0,
                0,
                started,
                ",".join(unsupported),
            )
            return baseline
        has_intent_chooser = callable(
            getattr(self.continuation, "choose_action_for_intent", None)
        )
        has_rollout_fork = callable(
            getattr(self.continuation, "fork_for_rollout", None)
        )
        if has_intent_chooser and not has_rollout_fork:
            self.counters.unavailable += 1
            started = time.perf_counter()
            root = _SearchRoot(baseline, None)
            self._record_strategy(
                observation,
                (root,),
                baseline,
                root,
                (),
                0,
                0,
                started,
                "intent_continuation_missing_rollout_fork",
            )
            return baseline
        intent_aware = has_intent_chooser and has_rollout_fork
        legal_actions = tuple(iter_legal_actions(observation))
        roots = build_strategy_candidates(
            observation,
            legal_actions,
            baseline,
            active_intent=self.active_intent,
            include_reorders=self.include_reorders,
            intent_aware=intent_aware,
            engine=engine,
        )
        self.last_strategy_candidates = roots
        if len(roots) <= 1:
            self.last_strategy_selected_index = 0
            return baseline

        started = time.perf_counter()
        samples: list[JackdawBackend] = []
        try:
            for index in range(self.budget.samples):
                samples.append(
                    sample_candidate(
                        self.backend,
                        observation,
                        history,
                        sample_seed(observation, self.nonce, index),
                    )
                )
        except DeterminizationUnavailable as exc:
            for sample in samples:
                sample.close()
            self.counters.unavailable += 1
            self._record_strategy(
                observation, roots, baseline, roots[0], (), 0, 0, started, str(exc)
            )
            return baseline

        utilities: list[list[GoalUtility]] = [[] for _ in roots]
        outcomes: list[list[RolloutOutcome]] = [[] for _ in roots]
        scalar_values: list[list[float]] = [[] for _ in roots]
        steps = 0
        rejected = 0
        root_rejected = [False for _ in roots]
        rejection_reasons: Counter[str] = Counter()
        for sample in samples:
            for index, root in enumerate(roots):
                clone = clone_backend(sample)
                intent = (
                    root.option.intent
                    if intent_aware and root.option is not None
                    else None
                )
                outcome = self._rollout(
                    clone,
                    observation,
                    history,
                    root.action,
                    intent=intent,
                    isolate_continuation=True,
                )
                clone.close()
                if outcome.goal_utility is None:
                    raise AssertionError("strategy rollout produced no goal utility")
                utilities[index].append(outcome.goal_utility)
                outcomes[index].append(outcome)
                scalar_values[index].append(outcome.value)
                steps += outcome.steps
                rejected += int(outcome.rejected)
                root_rejected[index] = root_rejected[index] or outcome.rejected
                if outcome.rejection_reason is not None:
                    rejection_reasons[
                        f"{_root_label(root)}|{outcome.rejection_reason}"
                    ] += 1
            sample.close()

        selected_index = _select_goal_root(
            utilities,
            baseline_index=0,
            goal=engine.goal,
            override_z=self.budget.override_z,
            admissible=tuple(not value for value in root_rejected),
        )
        selected_root = roots[selected_index]
        self.last_strategy_selected_index = selected_index
        selected = selected_root.action
        if not any(root_rejected) and self.success_teacher is None:
            self.teacher_drafts.append(
                StrategyTeacherDraft(
                    observation=observation,
                    candidates=tuple(
                        StrategyTeacherCandidate(
                            action=root.action,
                            intent=root.intent,
                            samples=tuple(
                                _teacher_target(
                                    outcome,
                                    engine.antes_cleared,
                                    engine.goal,
                                )
                                for outcome in root_outcomes
                            ),
                        )
                        for root, root_outcomes in zip(roots, outcomes, strict=True)
                    ),
                    selected_index=selected_index,
                    baseline_index=0,
                    goal=engine.goal,
                    teacher_config_digest=_teacher_config_digest(self),
                )
            )
        if self.success_teacher is not None and self._is_success_anchor(observation):
            self._collect_success_teacher(
                observation,
                history,
                roots,
                behavior_index=selected_index,
                intent_aware=intent_aware,
                engine_goal=engine.goal,
            )
        if intent_aware and selected_root.option is not None:
            if self.active_intent is None:
                self.active_intent = PersistentIntent.start(
                    selected_root.option, engine
                )
            else:
                self.active_intent = self.active_intent.advance(
                    selected_root.option, engine
                )
        else:
            self.active_intent = None
        self.counters.searched += 1
        self.counters.changed += int(selected != baseline)
        count = len(samples)
        goal_means = tuple(
            (
                _root_label(root),
                tuple(
                    sum(
                        utility.ordering_key(engine.goal)[component]
                        for utility in root_values
                    )
                    / count
                    for component in range(
                        len(root_values[0].ordering_key(engine.goal))
                    )
                ),
            )
            for root, root_values in zip(roots, utilities, strict=True)
        )
        self._record_strategy(
            observation,
            roots,
            baseline,
            selected_root,
            goal_means,
            steps,
            rejected,
            started,
            None,
            scalar_means={
                _root_label(root): sum(values) / count
                for root, values in zip(roots, scalar_values, strict=True)
            },
            rejection_reasons=tuple(sorted(rejection_reasons.items())),
        )
        return selected

    def _is_success_anchor(self, observation: PublicObservation) -> bool:
        budget = self.success_teacher
        if budget is None:
            return False
        if observation.phase == Phase.SHOP:
            if observation.ante in self._success_shop_antes:
                return False
            self._success_shop_antes.add(observation.ante)
            return True
        if observation.phase == Phase.PACK:
            if observation.ante in self._success_pack_antes:
                return False
            self._success_pack_antes.add(observation.ante)
            return observation.won or observation.ante >= budget.prewin_start_ante
        if observation.phase == Phase.BLIND_SELECT and observation.ante >= 5:
            return any(
                blind.kind == "BOSS" and blind.status == "SELECT"
                for blind in observation.blinds
            )
        return False

    def _collect_success_teacher(
        self,
        observation: PublicObservation,
        history: tuple[PublicHistoryStep, ...],
        roots: Sequence[StrategyCandidateRoot],
        *,
        behavior_index: int,
        intent_aware: bool,
        engine_goal: RunGoal,
    ) -> None:
        """Evaluate terminal objectives while leaving the behavior choice intact."""

        budget = self.success_teacher
        if budget is None:  # pragma: no cover - caller guard
            return
        teacher_started = time.perf_counter()
        samples: list[JackdawBackend] = []
        outcomes: list[list[RolloutOutcome]] = [[] for _ in roots]
        terminal_objective = observation.won or observation.ante >= budget.prewin_start_ante
        try:
            for sample_index in range(budget.samples):
                samples.append(
                    sample_candidate(
                        self.backend,
                        observation,
                        history,
                        sample_seed(
                            observation,
                            f"{self.nonce}:success-terminal-v1",
                            sample_index,
                        ),
                    )
                )
            for sample in samples:
                for root_index, root in enumerate(roots):
                    clone = clone_backend(sample)
                    try:
                        outcome = self._rollout(
                            clone,
                            observation,
                            history,
                            root.action,
                            intent=root.intent if intent_aware else None,
                            isolate_continuation=True,
                            success_goal=engine_goal if terminal_objective else None,
                            max_steps=(
                                budget.max_steps
                                if terminal_objective
                                else self.budget.max_steps
                            ),
                            endless_horizon_antes=budget.endless_horizon_antes,
                        )
                    finally:
                        clone.close()
                    outcomes[root_index].append(outcome)
                    self.counters.success_teacher_steps += outcome.steps
                    self.counters.rollout_steps += outcome.steps
                    if outcome.rejected:
                        self.counters.success_teacher_rejected_rollouts += 1
                        self.counters.rejected_rollouts += 1
        except DeterminizationUnavailable:
            self.counters.success_teacher_rejected_rollouts += len(roots)
            self.counters.rejected_rollouts += len(roots)
            return
        finally:
            for sample in samples:
                sample.close()
            self.counters.seconds += time.perf_counter() - teacher_started
        if any(outcome.rejected for row in outcomes for outcome in row):
            return
        utilities = tuple(
            tuple(outcome.goal_utility for outcome in row) for row in outcomes
        )
        if any(utility is None for row in utilities for utility in row):
            raise AssertionError("success teacher rollout omitted goal utility")
        typed_utilities = tuple(
            tuple(utility for utility in row if utility is not None) for row in utilities
        )
        selected_index = _select_goal_root(
            typed_utilities,
            baseline_index=behavior_index,
            goal=engine_goal,
            override_z=self.budget.override_z,
        )
        self.teacher_drafts.append(
            StrategyTeacherDraft(
                observation=observation,
                candidates=tuple(
                    StrategyTeacherCandidate(
                        action=root.action,
                        intent=root.intent,
                        samples=tuple(
                            _teacher_target(
                                outcome,
                                observation.antes_cleared,
                                engine_goal,
                            )
                            for outcome in row
                        ),
                    )
                    for root, row in zip(roots, outcomes, strict=True)
                ),
                selected_index=selected_index,
                baseline_index=behavior_index,
                goal=engine_goal,
                teacher_config_digest=_teacher_config_digest(self),
            )
        )

    def _rollout(
        self,
        clone: JackdawBackend,
        observation: PublicObservation,
        history: Sequence[PublicHistoryStep],
        root: PublicAction,
        *,
        intent: StrategyIntent | None = None,
        isolate_continuation: bool = False,
        success_goal: RunGoal | None = None,
        max_steps: int | None = None,
        endless_horizon_antes: int = 2,
    ) -> RolloutOutcome:
        start_rounds = observation.round_no
        start_antes = observation.antes_cleared
        horizon = (
            start_antes + endless_horizon_antes
            if success_goal == RunGoal.ENDLESS
            else None
            if success_goal == RunGoal.VICTORY
            else start_antes + self.budget.horizon_antes
        )
        step_limit = self.budget.max_steps if max_steps is None else max_steps
        trajectory = list(history)
        current = observation
        action = root
        steps = 0
        best_hand_score = _public_best_hand_score(history)
        continuation = self.continuation
        if isolate_continuation:
            fork = getattr(self.continuation, "fork_for_rollout", None)
            if callable(fork):
                try:
                    continuation = fork(intent)
                except Exception as exc:
                    value = _progress_value(current, start_rounds)
                    return RolloutOutcome(
                        value,
                        steps,
                        True,
                        _goal_utility(current, value, best_hand_score, alive=False),
                        _exception_reason("fork_exception", exc),
                    )
            else:
                try:
                    continuation = deepcopy(self.continuation)
                except Exception as exc:
                    value = _progress_value(current, start_rounds)
                    return RolloutOutcome(
                        value,
                        steps,
                        True,
                        _goal_utility(current, value, best_hand_score, alive=False),
                        _exception_reason("copy_exception", exc),
                    )
            if continuation is self.continuation:
                value = _progress_value(current, start_rounds)
                return RolloutOutcome(
                    value,
                    steps,
                    True,
                    _goal_utility(current, value, best_hand_score, alive=False),
                    "fork_returned_shared_instance",
                )
        while True:
            try:
                result = clone.step(action)
            except Exception as exc:
                value = _progress_value(current, start_rounds)
                return RolloutOutcome(
                    value,
                    steps,
                    True,
                    _goal_utility(current, value, best_hand_score, alive=False),
                    _exception_reason("step_exception", exc),
                )
            steps += 1
            if result.status != "accepted" or result.after is None:
                value = _progress_value(current, start_rounds)
                return RolloutOutcome(
                    value,
                    steps,
                    True,
                    _goal_utility(current, value, best_hand_score, alive=False),
                    f"step_{result.status}",
                )
            after = clone.current_public
            if after is None:
                after = to_public_observation(
                    json.loads(result.after.observed.raw_json)
                )
            trajectory.append(PublicHistoryStep(current, action, after))
            if action_to_data(action)["type"] == "play_cards":
                best_hand_score = max(
                    best_hand_score,
                    max(0, after.round.chips - current.round.chips),
                )
            if after.terminal:
                value = _progress_value(current, start_rounds, after)
                return RolloutOutcome(
                    value,
                    steps,
                    False,
                    _goal_utility(after, value, best_hand_score),
                    endpoint=StrategyTargetEndpoint.DEATH,
                )
            current = after
            if success_goal == RunGoal.VICTORY and current.won:
                value = float(current.round_no - start_rounds) + 1.0
                return RolloutOutcome(
                    value,
                    steps,
                    False,
                    _goal_utility(
                        current, value, best_hand_score, horizon_reached=True
                    ),
                    endpoint=StrategyTargetEndpoint.VICTORY,
                )
            if horizon is not None and current.antes_cleared >= horizon:
                value = float(current.round_no - start_rounds) + 1.0
                return RolloutOutcome(
                    value,
                    steps,
                    False,
                    _goal_utility(
                        current, value, best_hand_score, horizon_reached=True
                    ),
                )
            if steps >= step_limit:
                value = _progress_value(current, start_rounds)
                truncated = isolate_continuation
                return RolloutOutcome(
                    value,
                    steps,
                    truncated,
                    _goal_utility(current, value, best_hand_score, alive=not truncated),
                    "max_steps" if truncated else None,
                    StrategyTargetEndpoint.CENSORED
                    if truncated
                    else StrategyTargetEndpoint.HORIZON,
                )
            try:
                choose_for_intent = getattr(
                    continuation, "choose_action_for_intent", None
                )
                if intent is not None and callable(choose_for_intent):
                    action = choose_for_intent(
                        current,
                        lambda: iter_legal_actions(current),
                        tuple(trajectory),
                        intent,
                    )
                else:
                    action = continuation.choose_action(
                        current, lambda: iter_legal_actions(current), tuple(trajectory)
                    )
            except NoPublicProgressAction:
                # Vanilla can leave an exhausted blind in SELECTING_HAND with
                # no scoring action. That is an observable losing leaf, not a
                # malformed simulation or continuation failure.
                value = _progress_value(current, start_rounds)
                return RolloutOutcome(
                    value,
                    steps,
                    False,
                    _goal_utility(current, value, best_hand_score, alive=False),
                    endpoint=StrategyTargetEndpoint.DEATH,
                )
            except Exception as exc:  # all other continuation failures reject the root
                value = _progress_value(current, start_rounds)
                return RolloutOutcome(
                    value,
                    steps,
                    True,
                    _goal_utility(current, value, best_hand_score, alive=False),
                    _exception_reason("continuation_exception", exc),
                )

    def _record_strategy(
        self,
        observation: PublicObservation,
        roots: Sequence[_SearchRoot],
        baseline: PublicAction,
        selected: _SearchRoot,
        goal_values: tuple[tuple[str, tuple[float, ...]], ...],
        steps: int,
        rejected: int,
        started: float,
        unavailable_reason: str | None,
        *,
        scalar_means: dict[str, float] | None = None,
        rejection_reasons: tuple[tuple[str, int], ...] = (),
    ) -> None:
        seconds = time.perf_counter() - started
        self.counters.rollout_steps += steps
        self.counters.rejected_rollouts += rejected
        self.counters.seconds += seconds
        engine = derive_engine_state(observation)
        decision = SearchDecision(
            phase=observation.phase.value,
            ante=observation.ante,
            roots=len(roots),
            samples=self.budget.samples if unavailable_reason is None else 0,
            steps=steps,
            seconds=seconds,
            rejected_rollouts=rejected,
            values=tuple(sorted((scalar_means or {}).items())),
            baseline=_label(baseline),
            selected=_label(selected.action),
            unavailable_reason=unavailable_reason,
            goal=engine.goal.value,
            selected_intent=(
                selected.option.intent.value if selected.option is not None else None
            ),
            goal_values=tuple(sorted(goal_values)),
            rejection_reasons=rejection_reasons,
        )
        self.last_decision = decision
        self.decisions.append(decision)

    def _record(
        self,
        observation: PublicObservation,
        roots: Sequence[PublicAction],
        baseline: PublicAction,
        selected: PublicAction,
        values: dict[str, float],
        steps: int,
        rejected: int,
        started: float,
        unavailable_reason: str | None,
    ) -> None:
        seconds = time.perf_counter() - started
        self.counters.rollout_steps += steps
        self.counters.rejected_rollouts += rejected
        self.counters.seconds += seconds
        decision = SearchDecision(
            phase=observation.phase.value,
            ante=observation.ante,
            roots=len(roots),
            samples=self.budget.samples if unavailable_reason is None else 0,
            steps=steps,
            seconds=seconds,
            rejected_rollouts=rejected,
            values=tuple(sorted(values.items())),
            baseline=_label(baseline),
            selected=_label(selected),
            unavailable_reason=unavailable_reason,
        )
        self.last_decision = decision
        self.decisions.append(decision)


def _select_root(
    values: Sequence[Sequence[float]], baseline_index: int, override_z: float
) -> int:
    """Override the continuation only on significant paired evidence.

    Roots share samples, so each root has a per-sample delta against the
    continuation's own choice.  A root is eligible when its mean delta minus
    ``override_z`` standard errors is still positive.  Among eligible roots the
    largest mean wins; otherwise the continuation's choice stands.  Without
    this, near-ties at easy antes are decided by rollout noise.
    """

    baseline_values = values[baseline_index]
    count = len(baseline_values)
    best_index = baseline_index
    best_mean = None
    for index, root_values in enumerate(values):
        if index == baseline_index:
            continue
        deltas = [
            root - base for root, base in zip(root_values, baseline_values, strict=True)
        ]
        mean = sum(deltas) / count
        if mean <= 0:
            continue
        if count > 1:
            variance = sum((delta - mean) ** 2 for delta in deltas) / (count - 1)
            lower = mean - override_z * (variance**0.5) / (count**0.5)
        else:
            lower = mean
        if lower <= 0:
            continue
        if best_mean is None or mean > best_mean:
            best_mean = mean
            best_index = index
    return best_index


def _select_goal_root(
    values: Sequence[Sequence[GoalUtility]],
    baseline_index: int,
    goal: RunGoal,
    override_z: float,
    admissible: Sequence[bool] | None = None,
) -> int:
    """Select on the first non-tied goal component with paired evidence.

    A lower-priority component is considered only when every paired sample is
    exactly tied on all higher-priority components.  An uncertain higher-level
    delta therefore retains the baseline instead of allowing score or economy
    to trade against survival.
    """

    baseline_values = values[baseline_index]
    count = len(baseline_values)
    if count == 0:
        return baseline_index
    component_count = len(baseline_values[0].ordering_key(goal))
    eligible: list[int] = []
    for index, root_values in enumerate(values):
        if index == baseline_index:
            continue
        if admissible is not None and not admissible[index]:
            continue
        for component in range(component_count):
            deltas = [
                root.ordering_key(goal)[component] - base.ordering_key(goal)[component]
                for root, base in zip(root_values, baseline_values, strict=True)
            ]
            if all(delta == 0 for delta in deltas):
                continue
            mean = sum(deltas) / count
            if count > 1:
                variance = sum((delta - mean) ** 2 for delta in deltas) / (count - 1)
                lower = mean - override_z * math.sqrt(variance / count)
            else:
                lower = mean
            if lower > 0:
                eligible.append(index)
            break
    if not eligible:
        return baseline_index

    def mean_key(index: int) -> tuple[float, ...]:
        keys = [utility.ordering_key(goal) for utility in values[index]]
        return tuple(
            sum(key[component] for key in keys) / count
            for component in range(component_count)
        )

    return max(eligible, key=mean_key)


def _progress_value(
    last_alive: PublicObservation,
    start_rounds: int,
    terminal: PublicObservation | None = None,
) -> float:
    """Rounds cleared within the horizon plus the fraction of the failed blind scored."""

    rounds = float(last_alive.round_no - start_rounds)
    current = next(
        (blind for blind in last_alive.blinds if blind.status == "CURRENT"), None
    )
    if current is None or current.score <= 0:
        return rounds
    chips = (
        terminal.round.chips
        if terminal is not None and terminal.round.chips > last_alive.round.chips
        else last_alive.round.chips
    )
    return rounds + min(0.99, max(0.0, chips / current.score))


def _goal_utility(
    observation: PublicObservation,
    progress: float,
    best_hand_score: int,
    *,
    horizon_reached: bool = False,
    alive: bool | None = None,
) -> GoalUtility:
    fractional_progress = progress - math.floor(progress)
    return GoalUtility(
        win_probability=float(observation.won),
        current_blind_clear_probability=1.0 if horizon_reached else fractional_progress,
        survival_progress=progress,
        endless_ante=float(observation.antes_cleared),
        log_score=math.log10(max(1, best_hand_score)),
        economy_reserve=float(observation.money),
        alive_probability=float(not observation.terminal if alive is None else alive),
    )


def _teacher_target(
    outcome: RolloutOutcome,
    starting_antes_cleared: int,
    goal: RunGoal,
) -> StrategyRolloutTarget:
    """Strip a sampled trajectory to public scalar supervision only."""

    utility = outcome.goal_utility
    if utility is None:
        raise ValueError("teacher rollout omitted its goal utility")
    if outcome.rejected or outcome.endpoint == StrategyTargetEndpoint.CENSORED:
        return StrategyRolloutTarget(
            current_blind_clear=float(utility.survival_progress >= 1.0),
            next_boss_clear=float(utility.endless_ante > starting_antes_cleared),
            ante8_win=None,
            endless_ante=None,
            log_score=None,
            endpoint=StrategyTargetEndpoint.CENSORED,
        )
    ante8_win: float | None = None
    if goal == RunGoal.VICTORY:
        if outcome.endpoint == StrategyTargetEndpoint.VICTORY:
            ante8_win = 1.0
        elif outcome.endpoint == StrategyTargetEndpoint.DEATH:
            ante8_win = utility.win_probability
    endless_ante = utility.endless_ante if goal == RunGoal.ENDLESS else None
    log_score = utility.log_score if goal == RunGoal.ENDLESS else None
    return StrategyRolloutTarget(
        current_blind_clear=float(utility.survival_progress >= 1.0),
        next_boss_clear=float(utility.endless_ante > starting_antes_cleared),
        ante8_win=ante8_win,
        endless_ante=endless_ante,
        log_score=log_score,
        endpoint=outcome.endpoint,
    )


def _public_best_hand_score(history: Sequence[PublicHistoryStep]) -> int:
    """Recover the largest public scoring delta from the typed prefix."""

    return max(
        (
            max(0, step.after.round.chips - step.before.round.chips)
            for step in history
            if action_to_data(step.action)["type"] == "play_cards"
        ),
        default=0,
    )


def _teacher_config_digest(policy: DeterminizedSearchPolicy) -> str:
    continuation_config = (
        asdict(policy.continuation) if is_dataclass(policy.continuation) else None
    )
    payload = {
        "search_version": SEARCH_VERSION,
        "budget": policy.budget.canonical(),
        "nonce": policy.nonce,
        "strategy_options": policy.enable_strategy_options,
        "include_reorders": policy.include_reorders,
        "success_teacher": (
            policy.success_teacher.canonical()
            if policy.success_teacher is not None
            else None
        ),
        "continuation_type": (
            f"{type(policy.continuation).__module__}."
            f"{type(policy.continuation).__qualname__}"
        ),
        "continuation_config": continuation_config,
        "backend": asdict(policy.backend.metadata),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _strategy_unsupported(engine) -> list[str]:
    unsupported: list[str] = []
    if engine.scoring.unknown_joker_slots:
        unsupported.append("unknown_owned_joker")
    if engine.consumables.unknown_keys:
        unsupported.append("unknown_owned_consumable")
    if engine.economy.unknown_used_vouchers:
        unsupported.append("unknown_used_voucher")
    if engine.boss.name is not None and not engine.boss.known:
        unsupported.append("unknown_visible_boss")
    return unsupported


def _label(action: PublicAction) -> str:
    return json.dumps(action_to_data(action), sort_keys=True, separators=(",", ":"))


def _exception_reason(prefix: str, exc: Exception) -> str:
    message = " ".join(str(exc).split())[:160]
    return (
        f"{prefix}:{type(exc).__name__}:{message}"
        if message
        else f"{prefix}:{type(exc).__name__}"
    )


def _root_label(root: _SearchRoot) -> str:
    label = _label(root.action)
    if root.option is None:
        return f"{label}|intent=baseline"
    return f"{label}|intent={root.option.intent.value}"
