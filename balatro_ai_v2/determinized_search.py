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

import gc
import json
import hashlib
import math
import sys
import time
from collections import Counter
from contextlib import contextmanager
from copy import deepcopy
from collections.abc import Callable, Iterator, Sequence
from dataclasses import asdict, dataclass, field, is_dataclass

from balatro_ai_v2.actions import (
    PlayCards,
    PublicAction,
    ReorderConsumables,
    ReorderHand,
    ReorderJokers,
    action_to_data,
    iter_legal_actions,
)
from balatro_ai_v2.determinize import (
    STRATEGIC_PHASES,
    DeterminizationUnavailable,
    FrozenJackdawBackend,
    freeze_backend,
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
from balatro_ai_v2.strategy_engine import (
    GoalUtility,
    PublicEngineState,
    RunGoal,
    RunRoute,
    derive_engine_state,
)
from balatro_ai_v2.strategy_context import derive_public_strategy_context
from balatro_ai_v2.strategy_options import (
    PersistentIntent,
    PersistentRoute,
    StrategyCandidateRoot,
    StrategyIntent,
    build_strategy_candidates,
)
from balatro_ai_v2.strategy_teacher import (
    DENSE_TEACHER_MAX_ROOTS,
    DENSE_TEACHER_SUBSET_CONTRACT,
    STRATEGY_TEACHER_SCHEMA_VERSION,
    StrategyRolloutTarget,
    StrategyTargetEndpoint,
    StrategyTeacherCandidate,
    StrategyTeacherDraft,
)


SEARCH_VERSION = "determinized-search-v21"
_REORDER_TYPES = (ReorderHand, ReorderJokers, ReorderConsumables)
STRATEGY_SPECIALIST_MAX_ROOTS = 128


@dataclass(slots=True)
class _TimingBucket:
    count: int = 0
    total_ns: int = 0
    max_ns: int = 0

    def add(self, elapsed_ns: int) -> None:
        self.count += 1
        self.total_ns += elapsed_ns
        self.max_ns = max(self.max_ns, elapsed_ns)

    def as_dict(self) -> dict[str, int | float]:
        return {
            "count": self.count,
            "seconds": self.total_ns / 1_000_000_000,
            "max_seconds": self.max_ns / 1_000_000_000,
        }


@dataclass(slots=True)
class SearchTimingCollector:
    """Opt-in evaluator timing that never enters search or teacher semantics."""

    buckets: dict[str, _TimingBucket] = field(default_factory=dict)
    terminal_anchor_count: int = 0
    terminal_anchor_net_allocated_blocks: int = 0
    terminal_anchor_max_positive_net_allocated_blocks: int = 0
    gc_collections: Counter[int] = field(default_factory=Counter)
    gc_total_ns: int = 0
    gc_max_ns: int = 0

    def reset(self) -> None:
        self.buckets.clear()
        self.terminal_anchor_count = 0
        self.terminal_anchor_net_allocated_blocks = 0
        self.terminal_anchor_max_positive_net_allocated_blocks = 0
        self.gc_collections.clear()
        self.gc_total_ns = 0
        self.gc_max_ns = 0

    def record(self, path: str, stage: str, elapsed_ns: int) -> None:
        if elapsed_ns < 0:
            raise ValueError("search timing duration cannot be negative")
        self.buckets.setdefault(f"{path}.{stage}", _TimingBucket()).add(elapsed_ns)

    @contextmanager
    def terminal_anchor(self) -> Iterator[None]:
        """Observe one terminal anchor without forcing or rescheduling GC."""

        anchor_started = time.perf_counter_ns()
        blocks_started = (
            sys.getallocatedblocks() if hasattr(sys, "getallocatedblocks") else None
        )
        gc_started: dict[int, int] = {}

        def observe_gc(phase: str, info: dict[str, int]) -> None:
            generation = int(info.get("generation", -1))
            if phase == "start":
                gc_started[generation] = time.perf_counter_ns()
            elif phase == "stop":
                started = gc_started.pop(generation, None)
                if started is not None:
                    elapsed = time.perf_counter_ns() - started
                    self.gc_collections[generation] += 1
                    self.gc_total_ns += elapsed
                    self.gc_max_ns = max(self.gc_max_ns, elapsed)

        gc.callbacks.append(observe_gc)
        try:
            yield
        finally:
            if observe_gc in gc.callbacks:
                gc.callbacks.remove(observe_gc)
            blocks_finished = (
                sys.getallocatedblocks()
                if blocks_started is not None and hasattr(sys, "getallocatedblocks")
                else None
            )
            if blocks_started is not None and blocks_finished is not None:
                delta = blocks_finished - blocks_started
                self.terminal_anchor_net_allocated_blocks += delta
                self.terminal_anchor_max_positive_net_allocated_blocks = max(
                    self.terminal_anchor_max_positive_net_allocated_blocks,
                    delta,
                )
            self.terminal_anchor_count += 1
            self.record(
                "success_teacher",
                "anchor_total",
                time.perf_counter_ns() - anchor_started,
            )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "clock": "perf_counter_ns",
            "buckets": {
                name: bucket.as_dict() for name, bucket in sorted(self.buckets.items())
            },
            "allocation": {
                "metric": "net_allocated_blocks",
                "terminal_anchors": self.terminal_anchor_count,
                "net_blocks": self.terminal_anchor_net_allocated_blocks,
                "max_positive_anchor_net_blocks": (
                    self.terminal_anchor_max_positive_net_allocated_blocks
                ),
            },
            "gc": {
                "collections_by_generation": {
                    str(generation): count
                    for generation, count in sorted(self.gc_collections.items())
                },
                "seconds": self.gc_total_ns / 1_000_000_000,
                "max_seconds": self.gc_max_ns / 1_000_000_000,
            },
        }


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
        if (
            min(
                self.samples,
                self.prewin_start_ante,
                self.endless_horizon_antes,
                self.max_steps,
            )
            < 1
        ):
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
class SuccessTerminalActionBudget:
    """Conservative paired racing rule for terminal action influence."""

    max_samples: int = 12
    max_roots: int = 64
    family_alpha: float = 0.05

    def __post_init__(self) -> None:
        if min(self.max_samples, self.max_roots) < 1:
            raise ValueError("terminal action budgets must be positive")
        if not 0.0 < self.family_alpha < 1.0:
            raise ValueError("terminal action family alpha must be in (0, 1)")

    def canonical(self) -> str:
        return (
            f"max_samples={self.max_samples};max_roots={self.max_roots};"
            f"family_alpha={self.family_alpha};"
            "selector=root_adjusted_one_sided_sign;adverse_discordances=0;"
            "victory_component=exact_win;"
            "endless_components=alive_at_horizon,endless_ante,log_best_hand_score;"
            "ties_are_not_evidence;early_anchors_inert;root_overflow=fail_closed;"
            "no_public_progress=censored_for_actions"
        )


@dataclass(frozen=True, slots=True)
class RolloutOutcome:
    value: float
    steps: int
    rejected: bool
    goal_utility: GoalUtility | None = None
    rejection_reason: str | None = None
    endpoint: StrategyTargetEndpoint = StrategyTargetEndpoint.HORIZON
    terminal_action_admissible: bool = True


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
    baseline_intent: str | None = None
    baseline_route: str | None = None
    selected_intent: str | None = None
    selected_route: str | None = None
    ordinary_selected: str | None = None
    ordinary_selected_intent: str | None = None
    ordinary_selected_route: str | None = None
    specialist_override: bool = False
    specialist_unavailable_reason: str | None = None
    ordinary_roots: int = 0
    specialist_roots: int = 0
    specialist_roots_generated: int = 0
    specialist_paired_mean_delta: float = 0.0
    specialist_paired_lower_bound: float = 0.0
    best_specialist: str | None = None
    best_specialist_paired_mean_delta: float = 0.0
    best_specialist_paired_lower_bound: float = 0.0
    best_specialist_rejected: bool = False
    goal_values: tuple[tuple[str, tuple[float, ...]], ...] = ()
    rejection_reasons: tuple[tuple[str, int], ...] = ()

    @property
    def changed(self) -> bool:
        return self.selected != self.baseline

    @property
    def identity_changed(self) -> bool:
        return self.changed or (
            self.selected_intent,
            self.selected_route,
        ) != (
            self.baseline_intent,
            self.baseline_route,
        )

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
            "baseline_intent": self.baseline_intent,
            "baseline_route": self.baseline_route,
            "selected_intent": self.selected_intent,
            "selected_route": self.selected_route,
            "ordinary_selected": self.ordinary_selected,
            "ordinary_selected_intent": self.ordinary_selected_intent,
            "ordinary_selected_route": self.ordinary_selected_route,
            "specialist_override": self.specialist_override,
            "specialist_unavailable_reason": self.specialist_unavailable_reason,
            "ordinary_roots": self.ordinary_roots,
            "specialist_roots": self.specialist_roots,
            "specialist_roots_generated": self.specialist_roots_generated,
            "specialist_paired_mean_delta": self.specialist_paired_mean_delta,
            "specialist_paired_lower_bound": self.specialist_paired_lower_bound,
            "best_specialist": self.best_specialist,
            "best_specialist_paired_mean_delta": (
                self.best_specialist_paired_mean_delta
            ),
            "best_specialist_paired_lower_bound": (
                self.best_specialist_paired_lower_bound
            ),
            "best_specialist_rejected": self.best_specialist_rejected,
            "identity_changed": self.identity_changed,
            "goal_values": [[label, list(value)] for label, value in self.goal_values],
            "rejection_reasons": [list(pair) for pair in self.rejection_reasons],
        }


@dataclass(frozen=True, slots=True)
class SuccessTeacherDecision:
    """Public aggregate diagnostics for one sparse success anchor."""

    phase: str
    ante: int
    goal: str
    roots: int
    initial_samples: int
    max_samples_used: int
    sample_evaluations: int
    steps: int
    max_root_cumulative_steps: int
    seconds: float
    rejected_rollouts: int
    censored_rollouts: int
    endpoint_counts: tuple[tuple[str, int], ...]
    action_kind_counts: tuple[tuple[str, int], ...]
    intent_counts: tuple[tuple[str, int], ...]
    route_counts: tuple[tuple[str, int], ...]
    ordinary_index: int
    behavior_index: int
    teacher_selected_index: int
    executed_index: int
    ordinary_action: PublicAction
    ordinary_intent: StrategyIntent | None
    ordinary_route: RunRoute | None
    behavior_action: PublicAction
    behavior_intent: StrategyIntent | None
    behavior_route: RunRoute | None
    teacher_action: PublicAction
    teacher_intent: StrategyIntent | None
    teacher_route: RunRoute | None
    executed_action: PublicAction
    executed_intent: StrategyIntent | None
    executed_route: RunRoute | None
    fallback_reason: str | None
    affects_actions: bool
    unavailable: bool = False
    unsupported: bool = False
    positive_discordances: int = 0
    adverse_discordances: int = 0
    required_positive_discordances: int = 0

    @property
    def identity_override(self) -> bool:
        return self.executed_index != self.behavior_index

    def as_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "ante": self.ante,
            "goal": self.goal,
            "roots": self.roots,
            "initial_samples": self.initial_samples,
            "max_samples_used": self.max_samples_used,
            "sample_evaluations": self.sample_evaluations,
            "steps": self.steps,
            "max_root_cumulative_steps": self.max_root_cumulative_steps,
            "seconds": self.seconds,
            "rejected_rollouts": self.rejected_rollouts,
            "censored_rollouts": self.censored_rollouts,
            "endpoint_counts": dict(self.endpoint_counts),
            "action_kind_counts": dict(self.action_kind_counts),
            "intent_counts": dict(self.intent_counts),
            "route_counts": dict(self.route_counts),
            "ordinary_index": self.ordinary_index,
            "behavior_index": self.behavior_index,
            "teacher_selected_index": self.teacher_selected_index,
            "executed_index": self.executed_index,
            "ordinary": {
                "action": action_to_data(self.ordinary_action),
                "intent": self.ordinary_intent.value
                if self.ordinary_intent is not None
                else None,
                "route": self.ordinary_route.value
                if self.ordinary_route is not None
                else None,
            },
            "behavior": {
                "action": action_to_data(self.behavior_action),
                "intent": self.behavior_intent.value
                if self.behavior_intent is not None
                else None,
                "route": self.behavior_route.value
                if self.behavior_route is not None
                else None,
            },
            "teacher_selected": {
                "action": action_to_data(self.teacher_action),
                "intent": self.teacher_intent.value
                if self.teacher_intent is not None
                else None,
                "route": self.teacher_route.value
                if self.teacher_route is not None
                else None,
            },
            "executed": {
                "action": action_to_data(self.executed_action),
                "intent": self.executed_intent.value
                if self.executed_intent is not None
                else None,
                "route": self.executed_route.value
                if self.executed_route is not None
                else None,
            },
            "fallback_reason": self.fallback_reason,
            "affects_actions": self.affects_actions,
            "unavailable": self.unavailable,
            "unsupported": self.unsupported,
            "identity_override": self.identity_override,
            "positive_discordances": self.positive_discordances,
            "adverse_discordances": self.adverse_discordances,
            "required_positive_discordances": self.required_positive_discordances,
        }


@dataclass(slots=True)
class SearchCounters:
    strategic_decisions: int = 0
    searched: int = 0
    changed: int = 0
    strategy_identity_changes: int = 0
    strategy_route_selections: Counter[str] = field(default_factory=Counter)
    strategy_route_transitions: Counter[str] = field(default_factory=Counter)
    strategy_specialist_challenges: int = 0
    strategy_specialist_roots_generated: int = 0
    strategy_specialist_overrides: int = 0
    strategy_specialist_unavailable: int = 0
    strategy_route_abandonments: int = 0
    strategy_victory_escapes: int = 0
    unavailable: int = 0
    rollout_steps: int = 0
    rejected_rollouts: int = 0
    seconds: float = 0.0
    success_teacher_steps: int = 0
    success_teacher_rejected_rollouts: int = 0
    success_teacher_seconds: float = 0.0
    success_anchors_attempted: int = 0
    success_anchors_completed: int = 0
    success_anchor_fallbacks: int = 0
    success_anchor_unavailable: int = 0
    success_anchor_unsupported: int = 0
    success_teacher_censored_rollouts: int = 0
    success_action_overrides: int = 0
    success_intent_only_overrides: int = 0
    success_route_only_overrides: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "strategic_decisions": self.strategic_decisions,
            "searched": self.searched,
            "changed": self.changed,
            "strategy_identity_changes": self.strategy_identity_changes,
            "strategy_route_selections": dict(
                sorted(self.strategy_route_selections.items())
            ),
            "strategy_route_transitions": dict(
                sorted(self.strategy_route_transitions.items())
            ),
            "strategy_specialist_challenges": self.strategy_specialist_challenges,
            "strategy_specialist_roots_generated": (
                self.strategy_specialist_roots_generated
            ),
            "strategy_specialist_overrides": self.strategy_specialist_overrides,
            "strategy_specialist_unavailable": self.strategy_specialist_unavailable,
            "strategy_route_abandonments": self.strategy_route_abandonments,
            "strategy_victory_escapes": self.strategy_victory_escapes,
            "unavailable": self.unavailable,
            "rollout_steps": self.rollout_steps,
            "rejected_rollouts": self.rejected_rollouts,
            "seconds": self.seconds,
            "success_teacher_steps": self.success_teacher_steps,
            "success_teacher_rejected_rollouts": self.success_teacher_rejected_rollouts,
            "success_teacher_seconds": self.success_teacher_seconds,
            "success_anchors_attempted": self.success_anchors_attempted,
            "success_anchors_completed": self.success_anchors_completed,
            "success_anchor_fallbacks": self.success_anchor_fallbacks,
            "success_anchor_unavailable": self.success_anchor_unavailable,
            "success_anchor_unsupported": self.success_anchor_unsupported,
            "success_teacher_censored_rollouts": self.success_teacher_censored_rollouts,
            "success_action_overrides": self.success_action_overrides,
            "success_intent_only_overrides": self.success_intent_only_overrides,
            "success_route_only_overrides": self.success_route_only_overrides,
            "steps_per_second": (self.rollout_steps / self.seconds)
            if self.seconds > 0
            else 0.0,
        }


@dataclass(slots=True)
class DeterminizedSearchPolicy:
    """Roots at strategic decisions, valued by paired determinized rollouts."""

    backend: JackdawBackend | None
    continuation: PublicPolicy
    root_factory: Callable[
        [PublicObservation, Sequence[PublicHistoryStep], str, int],
        JackdawBackend,
    ] | None = None
    rollout_continuation: PublicPolicy | None = None
    nonce: str = "search-v1"
    budget: RolloutBudget = RolloutBudget()
    enable_strategy_options: bool = False
    collect_dense_teacher: bool = False
    include_reorders: bool = False
    success_teacher: SuccessTeacherBudget | None = None
    success_terminal_actions: SuccessTerminalActionBudget | None = None
    timing: SearchTimingCollector | None = None
    last_decision: SearchDecision | None = None
    counters: SearchCounters = field(default_factory=SearchCounters)
    decisions: list[SearchDecision] = field(default_factory=list)
    teacher_drafts: list[StrategyTeacherDraft] = field(default_factory=list)
    success_decisions: list[SuccessTeacherDecision] = field(default_factory=list)
    last_success_decision: SuccessTeacherDecision | None = None
    active_intent: PersistentIntent | None = None
    active_route: PersistentRoute | None = None
    last_strategy_candidates: tuple[StrategyCandidateRoot, ...] = ()
    last_strategy_selected_index: int | None = None
    _success_shop_antes: set[int] = field(default_factory=set)
    _success_pack_antes: set[int] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.success_terminal_actions is None:
            return
        if self.success_teacher is None:
            raise ValueError("terminal actions require a success teacher budget")
        if self.success_teacher.samples > self.success_terminal_actions.max_samples:
            raise ValueError("initial terminal samples exceed the action sample cap")

    def reset_run(self) -> None:
        self.last_decision = None
        self.counters = SearchCounters()
        self.decisions = []
        self.teacher_drafts = []
        self.success_decisions = []
        self.last_success_decision = None
        self.active_intent = None
        self.active_route = None
        self.last_strategy_candidates = ()
        self.last_strategy_selected_index = None
        self._success_shop_antes = set()
        self._success_pack_antes = set()
        if self.timing is not None:
            self.timing.reset()

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        if (
            self.active_route is not None
            and self.active_route.route == RunRoute.VICTORY
        ):
            self.active_intent = None
            self.active_route = None
        choose_for_route = getattr(
            self.continuation, "choose_action_for_strategy", None
        )
        choose_for_intent = getattr(
            self.continuation, "choose_action_for_intent", None
        )
        if self.enable_strategy_options and observation.phase in STRATEGIC_PHASES:
            baseline = self.continuation.choose_action(
                observation, legal_actions, history
            )
        elif self.active_route is not None and callable(choose_for_route):
            try:
                baseline = choose_for_route(
                    observation,
                    legal_actions,
                    history,
                    self.active_intent.intent
                    if self.active_intent is not None
                    else None,
                    self.active_route.route,
                )
            except Exception:
                self.active_intent = None
                self.active_route = None
                baseline = self.continuation.choose_action(
                    observation, legal_actions, history
                )
        elif self.active_intent is not None and callable(choose_for_intent):
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
        self.last_success_decision = None
        self.last_strategy_candidates = ()
        self.last_strategy_selected_index = None
        if observation.phase not in STRATEGIC_PHASES:
            return baseline
        self.counters.strategic_decisions += 1
        success_anchor = self.success_teacher is not None and self._is_success_anchor(
            observation
        )
        if self.enable_strategy_options:
            captured_legal_actions = tuple(legal_actions())
            return self._choose_strategy_option(
                observation,
                baseline,
                history,
                captured_legal_actions,
                success_anchor=success_anchor,
            )
        captured_legal_actions = tuple(legal_actions())
        roots = [
            action
            for action in captured_legal_actions
            if not isinstance(action, _REORDER_TYPES)
        ]
        if baseline not in roots:
            roots.append(baseline)
        if self.collect_dense_teacher and len(roots) > DENSE_TEACHER_MAX_ROOTS:
            raise ValueError("dense teacher root set exceeds the complete-root cap")
        if len(roots) <= 1:
            if success_anchor:
                engine = derive_engine_state(observation)
                self._record_unavailable_success_anchor(
                    observation,
                    StrategyCandidateRoot(baseline, None),
                    engine.goal,
                    "single_root",
                )
            return baseline

        started = time.perf_counter()
        frozen_samples: list[FrozenJackdawBackend] = []
        try:
            for index in range(self.budget.samples):
                sample = self._sample_root(observation, history, self.nonce, index)
                try:
                    frozen_samples.append(freeze_backend(sample))
                finally:
                    sample.close()
        except DeterminizationUnavailable as exc:
            self.counters.unavailable += 1
            self._record(
                observation, roots, baseline, baseline, {}, 0, 0, started, str(exc)
            )
            if success_anchor:
                engine = derive_engine_state(observation)
                self._record_unavailable_success_anchor(
                    observation,
                    StrategyCandidateRoot(baseline, None),
                    engine.goal,
                    "determinization_unavailable",
                )
            return baseline

        values: list[list[float]] = [[] for _ in roots]
        outcomes: list[list[RolloutOutcome]] = [[] for _ in roots]
        steps = 0
        rejected = 0
        rejection_reasons: Counter[str] = Counter()
        prefix_best_hand_score = _public_best_hand_score(history)
        try:
            for frozen_sample in frozen_samples:
                for index, root in enumerate(roots):
                    clone = self._clone_for_rollout(frozen_sample, "ordinary")
                    try:
                        outcome = self._rollout(
                            clone,
                            observation,
                            history,
                            root,
                            prefix_best_hand_score=prefix_best_hand_score,
                            timing_path="ordinary",
                        )
                    finally:
                        self._close_rollout_clone(clone, "ordinary")
                    values[index].append(outcome.value)
                    outcomes[index].append(outcome)
                    steps += outcome.steps
                    rejected += int(outcome.rejected)
                    if outcome.rejection_reason is not None:
                        rejection_reasons[
                            f"{_label(root)}|{outcome.rejection_reason}"
                        ] += 1
        except DeterminizationUnavailable as exc:
            self.counters.unavailable += 1
            self._record(
                observation,
                roots,
                baseline,
                baseline,
                {},
                steps,
                rejected,
                started,
                str(exc),
                tuple(sorted(rejection_reasons.items())),
            )
            if success_anchor:
                engine = derive_engine_state(observation)
                self._record_unavailable_success_anchor(
                    observation,
                    StrategyCandidateRoot(baseline, None),
                    engine.goal,
                    "determinization_unavailable",
                )
            return baseline

        count = len(frozen_samples)
        means = {index: sum(values[index]) / count for index in range(len(roots))}
        baseline_index = roots.index(baseline)
        selected_index = select_paired_root(
            values, baseline_index, self.budget.override_z
        )
        selected = roots[selected_index]
        if self.collect_dense_teacher and rejected == 0:
            engine = derive_engine_state(observation)
            teacher_indexes = _dense_teacher_indexes(
                roots,
                baseline_index=baseline_index,
                selected_index=selected_index,
                limit=DENSE_TEACHER_MAX_ROOTS,
            )
            self.teacher_drafts.append(
                StrategyTeacherDraft(
                    observation=observation,
                    context=derive_public_strategy_context(
                        observation,
                        history,
                        incoming_intent=(
                            self.active_intent.intent
                            if self.active_intent is not None
                            else None
                        ),
                        incoming_route=(
                            self.active_route.route
                            if self.active_route is not None
                            else None
                        ),
                    ),
                    candidates=tuple(
                        StrategyTeacherCandidate(
                            action=root,
                            intent=None,
                            samples=tuple(
                                _teacher_target(
                                    outcome,
                                    engine.antes_cleared,
                                    engine.goal,
                                )
                                for outcome in root_outcomes
                            ),
                        )
                        for root, root_outcomes in (
                            (roots[index], outcomes[index]) for index in teacher_indexes
                        )
                    ),
                    selected_index=teacher_indexes.index(selected_index),
                    baseline_index=teacher_indexes.index(baseline_index),
                    ordinary_index=teacher_indexes.index(baseline_index),
                    behavior_index=teacher_indexes.index(selected_index),
                    goal=engine.goal,
                    teacher_config_digest=_teacher_config_digest(self),
                    candidate_space_size=len(roots),
                )
            )
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
            tuple(sorted(rejection_reasons.items())),
        )
        if success_anchor:
            engine = derive_engine_state(observation)
            unsupported = _strategy_unsupported(engine)
            if unsupported:
                self._record_unavailable_success_anchor(
                    observation,
                    StrategyCandidateRoot(selected, None),
                    engine.goal,
                    f"unsupported_public_state:{','.join(unsupported)}",
                    unsupported=True,
                )
            else:
                rollout_continuation = self.rollout_continuation or self.continuation
                route_aware = callable(
                    getattr(rollout_continuation, "choose_action_for_strategy", None)
                )
                intent_aware = (
                    route_aware
                    or callable(
                        getattr(
                            rollout_continuation, "choose_action_for_intent", None
                        )
                    )
                ) and callable(
                    getattr(rollout_continuation, "fork_for_rollout", None)
                )
                candidates = build_strategy_candidates(
                    observation,
                    captured_legal_actions,
                    selected,
                    active_intent=self.active_intent,
                    active_route=self.active_route,
                    include_reorders=self.include_reorders,
                    intent_aware=intent_aware,
                    route_aware=route_aware,
                    engine=engine,
                )
                if candidates and candidates[0].route == RunRoute.VICTORY:
                    candidates = (
                        StrategyCandidateRoot(candidates[0].action, None),
                        *candidates[1:],
                    )
                self.last_strategy_candidates = candidates
                self.last_strategy_selected_index = 0
                if len(candidates) > 1:
                    effective_index = self._collect_success_teacher(
                        observation,
                        history,
                        candidates,
                        behavior_index=0,
                        ordinary_index=0,
                        intent_aware=intent_aware,
                        engine_goal=engine.goal,
                    )
                    self.last_strategy_selected_index = effective_index
                    if self.success_terminal_actions is not None:
                        effective_root = candidates[effective_index]
                        self._commit_strategy_root(effective_root, engine)
                        selected = effective_root.action
                else:
                    self._record_unavailable_success_anchor(
                        observation,
                        candidates[0],
                        engine.goal,
                        "single_root",
                    )
        if (
            self.success_terminal_actions is not None
            and self.last_success_decision is None
            and selected != baseline
        ):
            self.active_intent = None
            self.active_route = None
        return selected

    def _choose_strategy_option(
        self,
        observation: PublicObservation,
        baseline: PublicAction,
        history: tuple[PublicHistoryStep, ...],
        legal_actions: tuple[PublicAction, ...],
        *,
        success_anchor: bool,
    ) -> PublicAction:
        """Overlay paired specialist challengers on exact ordinary search."""

        engine = derive_engine_state(observation)
        unsupported = _strategy_unsupported(engine)
        rollout_continuation = self.rollout_continuation or self.continuation
        has_intent_chooser = callable(
            getattr(rollout_continuation, "choose_action_for_intent", None)
        )
        has_rollout_fork = callable(
            getattr(rollout_continuation, "fork_for_rollout", None)
        )
        has_route_chooser = callable(
            getattr(rollout_continuation, "choose_action_for_strategy", None)
        )
        intent_aware = (has_intent_chooser or has_route_chooser) and has_rollout_fork
        specialist_unavailable_reason: str | None = None
        if unsupported:
            specialist_unavailable_reason = (
                f"unsupported_public_state:{','.join(unsupported)}"
            )
        elif not has_route_chooser:
            specialist_unavailable_reason = "route_continuation_unavailable"
        elif not has_rollout_fork:
            specialist_unavailable_reason = "route_continuation_missing_rollout_fork"
        if specialist_unavailable_reason is not None:
            self.counters.strategy_specialist_unavailable += 1

        ordinary_actions = [
            action
            for action in legal_actions
            if not isinstance(action, _REORDER_TYPES)
        ]
        if baseline not in ordinary_actions:
            ordinary_actions.append(baseline)
        ordinary_roots = tuple(
            _SearchRoot(action, None, None, None)
            for action in ordinary_actions
        )
        ordinary_count = len(ordinary_roots)
        baseline_index = ordinary_actions.index(baseline)
        if ordinary_count == 1 and specialist_unavailable_reason is not None:
            self.last_strategy_candidates = ordinary_roots
            self.last_strategy_selected_index = 0
            self.counters.strategy_route_abandonments += int(
                self.active_route is not None
            )
            self.active_intent = None
            self.active_route = None
            if success_anchor:
                self._record_unavailable_success_anchor(
                    observation,
                    ordinary_roots[0],
                    engine.goal,
                    "single_root",
                )
            return baseline
        started = time.perf_counter()
        frozen_samples: list[FrozenJackdawBackend] = []
        try:
            for index in range(self.budget.samples):
                sample = self._sample_root(observation, history, self.nonce, index)
                try:
                    frozen_samples.append(freeze_backend(sample))
                finally:
                    sample.close()
        except DeterminizationUnavailable as exc:
            self.counters.unavailable += 1
            root = ordinary_roots[baseline_index]
            self._record_strategy(
                observation,
                ordinary_roots,
                baseline,
                root,
                root,
                (),
                0,
                0,
                started,
                str(exc),
            )
            if success_anchor:
                self._record_unavailable_success_anchor(
                    observation,
                    root,
                    engine.goal,
                    "determinization_unavailable",
                )
            self.counters.strategy_route_abandonments += int(
                self.active_route is not None
            )
            self.active_intent = None
            self.active_route = None
            return baseline

        roots = list(ordinary_roots)
        utilities: list[list[GoalUtility]] = [[] for _ in roots]
        outcomes: list[list[RolloutOutcome]] = [[] for _ in roots]
        scalar_values: list[list[float]] = [[] for _ in roots]
        steps = 0
        rejected = 0
        root_rejected = [False for _ in roots]
        rejection_reasons: Counter[str] = Counter()
        prefix_best_hand_score = _public_best_hand_score(history)

        def retain_outcome(index: int, outcome: RolloutOutcome) -> None:
            nonlocal steps, rejected
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
                    f"{_root_label(roots[index])}|{outcome.rejection_reason}"
                ] += 1

        try:
            for frozen_sample in frozen_samples:
                for index, root in enumerate(ordinary_roots):
                    clone = self._clone_for_rollout(
                        frozen_sample, "strategy_ordinary"
                    )
                    try:
                        outcome = self._rollout(
                            clone,
                            observation,
                            history,
                            root.action,
                            prefix_best_hand_score=prefix_best_hand_score,
                            timing_path="strategy_ordinary",
                        )
                    finally:
                        self._close_rollout_clone(clone, "strategy_ordinary")
                    retain_outcome(index, outcome)
        except DeterminizationUnavailable as exc:
            self.counters.unavailable += 1
            root = ordinary_roots[baseline_index]
            self._record_strategy(
                observation,
                ordinary_roots,
                baseline,
                root,
                root,
                (),
                steps,
                rejected,
                started,
                str(exc),
            )
            if success_anchor:
                self._record_unavailable_success_anchor(
                    observation,
                    root,
                    engine.goal,
                    "determinization_unavailable",
                )
            self.counters.strategy_route_abandonments += int(
                self.active_route is not None
            )
            self.active_intent = None
            self.active_route = None
            return baseline

        ordinary_index = select_paired_root(
            scalar_values[:ordinary_count],
            baseline_index=baseline_index,
            override_z=self.budget.override_z,
        )
        ordinary_root = roots[ordinary_index]
        specialist_generated_count = 0

        if specialist_unavailable_reason is None:
            seen = {root.identity for root in roots}
            specialist_roots: list[_SearchRoot] = []
            try:
                if self.active_route is not None:
                    retained_intent = (
                        self.active_intent.intent
                        if self.active_intent is not None
                        else None
                    )
                    retained_continuation = rollout_continuation.fork_for_rollout(
                        retained_intent,
                        self.active_route.route,
                    )
                    if retained_continuation is rollout_continuation:
                        raise ValueError(
                            "route continuation fork returned its shared instance"
                        )
                    retained_chooser = getattr(
                        retained_continuation, "choose_action_for_strategy", None
                    )
                    if not callable(retained_chooser):
                        raise ValueError(
                            "route continuation fork lost strategy capability"
                        )
                    retained_action = retained_chooser(
                        observation,
                        lambda: iter(legal_actions),
                        history,
                        retained_intent,
                        self.active_route.route,
                    )
                    if retained_action not in ordinary_actions:
                        raise ValueError(
                            "route continuation selected an inadmissible root"
                        )
                    retained_root = _SearchRoot(
                        retained_action,
                        retained_intent,
                        None,
                        self.active_route.route,
                    )
                    specialist_roots.append(retained_root)
                    seen.add(retained_root.identity)
                option_roots = build_strategy_candidates(
                    observation,
                    legal_actions,
                    ordinary_root.action,
                    active_intent=self.active_intent,
                    active_route=self.active_route,
                    include_reorders=self.include_reorders,
                    intent_aware=intent_aware,
                    route_aware=True,
                    engine=engine,
                )
                for root in option_roots:
                    if root.route in (None, RunRoute.VICTORY):
                        continue
                    if (
                        self.active_route is not None
                        and root.route == self.active_route.route
                    ):
                        continue
                    if root.identity not in seen:
                        specialist_roots.append(root)
                        seen.add(root.identity)
                specialist_generated_count = len(specialist_roots)
                if len(specialist_roots) > STRATEGY_SPECIALIST_MAX_ROOTS:
                    specialist_unavailable_reason = (
                        "specialist_root_bound_exceeded:"
                        f"{len(specialist_roots)}>{STRATEGY_SPECIALIST_MAX_ROOTS}"
                    )
                    self.counters.strategy_specialist_unavailable += 1
                    specialist_roots = []
            except Exception as exc:
                specialist_unavailable_reason = _exception_reason(
                    "specialist_builder_exception", exc
                )
                self.counters.strategy_specialist_unavailable += 1
                specialist_roots = []
            roots.extend(specialist_roots)
            utilities.extend([] for _ in specialist_roots)
            outcomes.extend([] for _ in specialist_roots)
            scalar_values.extend([] for _ in specialist_roots)
            root_rejected.extend(False for _ in specialist_roots)
            try:
                for frozen_sample in frozen_samples:
                    for index in range(ordinary_count, len(roots)):
                        root = roots[index]
                        clone = self._clone_for_rollout(
                            frozen_sample, "strategy_specialist"
                        )
                        try:
                            outcome = self._rollout(
                                clone,
                                observation,
                                history,
                                root.action,
                                intent=root.intent,
                                route=root.route,
                                isolate_continuation=True,
                                prefix_best_hand_score=prefix_best_hand_score,
                                timing_path="strategy_specialist",
                            )
                        finally:
                            self._close_rollout_clone(
                                clone, "strategy_specialist"
                            )
                        retain_outcome(index, outcome)
            except DeterminizationUnavailable:
                specialist_unavailable_reason = "specialist_determinization_unavailable"
                self.counters.strategy_specialist_unavailable += 1
                roots = roots[:ordinary_count]
                utilities = utilities[:ordinary_count]
                outcomes = outcomes[:ordinary_count]
                scalar_values = scalar_values[:ordinary_count]
                root_rejected = root_rejected[:ordinary_count]

        self.last_strategy_candidates = tuple(roots)
        specialist_evidence = {
            index: _paired_delta_evidence(
                scalar_values[index],
                scalar_values[ordinary_index],
                self.budget.override_z,
            )
            for index in range(ordinary_count, len(roots))
        }
        best_specialist_index = (
            max(
                specialist_evidence,
                key=lambda index: (specialist_evidence[index][0], -index),
            )
            if specialist_evidence
            else None
        )
        challenger_indexes = (ordinary_index, *range(ordinary_count, len(roots)))
        challenger_selected = select_paired_root(
            [scalar_values[index] for index in challenger_indexes],
            baseline_index=0,
            override_z=self.budget.override_z,
            admissible=(
                True,
                *(not root_rejected[index] for index in challenger_indexes[1:]),
            ),
        )
        selected_index = challenger_indexes[challenger_selected]
        selected_root = roots[selected_index]
        paired_mean, paired_lower = _paired_delta_evidence(
            scalar_values[selected_index],
            scalar_values[ordinary_index],
            self.budget.override_z,
        )
        self.last_strategy_selected_index = selected_index
        selected = selected_root.action
        if (
            not any(root_rejected)
            and self.success_teacher is None
            and specialist_unavailable_reason is None
        ):
            self.teacher_drafts.append(
                StrategyTeacherDraft(
                    observation=observation,
                    context=derive_public_strategy_context(
                        observation,
                        history,
                        incoming_intent=(
                            self.active_intent.intent
                            if self.active_intent is not None
                            else None
                        ),
                        incoming_route=(
                            self.active_route.route
                            if self.active_route is not None
                            else None
                        ),
                    ),
                    candidates=tuple(
                        StrategyTeacherCandidate(
                            action=root.action,
                            intent=root.intent,
                            route=root.route,
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
                    baseline_index=ordinary_index,
                    ordinary_index=ordinary_index,
                    behavior_index=selected_index,
                    goal=engine.goal,
                    teacher_config_digest=_teacher_config_digest(self),
                )
            )
        self.counters.searched += 1
        self.counters.changed += int(selected != baseline)
        specialist_override = selected_index != ordinary_index
        self.counters.strategy_specialist_challenges += len(roots) - ordinary_count
        self.counters.strategy_specialist_roots_generated += (
            specialist_generated_count
        )
        self.counters.strategy_specialist_overrides += int(specialist_override)
        count = len(frozen_samples)
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
            tuple(roots),
            baseline,
            ordinary_root,
            selected_root,
            goal_means,
            steps,
            rejected,
            started,
            None,
            specialist_unavailable_reason=specialist_unavailable_reason,
            ordinary_root_count=ordinary_count,
            specialist_root_count=len(roots) - ordinary_count,
            specialist_root_generated_count=specialist_generated_count,
            specialist_paired_mean_delta=paired_mean,
            specialist_paired_lower_bound=paired_lower,
            best_specialist=(
                _root_label(roots[best_specialist_index])
                if best_specialist_index is not None
                else None
            ),
            best_specialist_paired_mean_delta=(
                specialist_evidence[best_specialist_index][0]
                if best_specialist_index is not None
                else 0.0
            ),
            best_specialist_paired_lower_bound=(
                specialist_evidence[best_specialist_index][1]
                if best_specialist_index is not None
                else 0.0
            ),
            best_specialist_rejected=(
                root_rejected[best_specialist_index]
                if best_specialist_index is not None
                else False
            ),
            scalar_means={
                _root_label(root): sum(values) / count
                for root, values in zip(roots, scalar_values, strict=True)
            },
            rejection_reasons=tuple(sorted(rejection_reasons.items())),
        )
        effective_index = selected_index
        if success_anchor:
            effective_index = self._collect_success_teacher(
                observation,
                history,
                tuple(roots),
                behavior_index=selected_index,
                ordinary_index=ordinary_index,
                intent_aware=intent_aware,
                engine_goal=engine.goal,
                execution_admissible=tuple(
                    root.route is None or index == selected_index
                    for index, root in enumerate(roots)
                ),
            )
        effective_root = roots[effective_index]
        self.last_strategy_selected_index = effective_index
        incoming_route = (
            self.active_route.route.value
            if self.active_route is not None
            else RunRoute.VICTORY.value
        )
        executed_route = (
            effective_root.route.value
            if effective_root.route is not None
            else RunRoute.VICTORY.value
        )
        self.counters.strategy_identity_changes += int(
            effective_root.action != baseline
            or effective_root.intent is not None
            or effective_root.route is not None
        )
        leaving_route = self.active_route is not None and effective_root.route is None
        self.counters.strategy_victory_escapes += int(
            leaving_route and specialist_unavailable_reason is None
        )
        self.counters.strategy_route_abandonments += int(
            leaving_route and specialist_unavailable_reason is not None
        )
        self.counters.strategy_route_selections[executed_route] += 1
        self.counters.strategy_route_transitions[
            f"{incoming_route}->{executed_route}"
        ] += 1
        self._commit_strategy_root(effective_root, engine)
        return effective_root.action

    def _commit_strategy_root(
        self,
        root: StrategyCandidateRoot,
        engine: PublicEngineState,
    ) -> None:
        if root.route == RunRoute.VICTORY:
            self.active_intent = None
            self.active_route = None
            return
        if root.option is None:
            self.active_intent = None
        elif self.active_intent is None:
            self.active_intent = PersistentIntent.start(root.option, engine)
        else:
            self.active_intent = self.active_intent.advance(root.option, engine)
        if root.route is None:
            self.active_route = None
        else:
            evidence = (
                root.option.evidence
                if root.option is not None
                else ("explicit_route_fallback",)
            )
            if self.active_route is None:
                self.active_route = PersistentRoute.start(
                    root.route, engine, evidence
                )
            else:
                self.active_route = self.active_route.advance(
                    root.route, engine, evidence
                )

    def _record_unavailable_success_anchor(
        self,
        observation: PublicObservation,
        root: StrategyCandidateRoot,
        goal: RunGoal,
        reason: str,
        *,
        unsupported: bool = False,
    ) -> None:
        """Record a scheduled anchor that cannot admit terminal evaluation."""

        self.counters.success_anchors_attempted += 1
        self.counters.success_anchor_unavailable += 1
        self.counters.success_anchor_unsupported += int(unsupported)
        if self.success_terminal_actions is not None:
            self.counters.success_anchor_fallbacks += 1
        action_kind = str(action_to_data(root.action)["type"])
        decision = SuccessTeacherDecision(
            phase=observation.phase.value,
            ante=observation.ante,
            goal=goal.value,
            roots=1,
            initial_samples=self.success_teacher.samples
            if self.success_teacher is not None
            else 0,
            max_samples_used=0,
            sample_evaluations=0,
            steps=0,
            max_root_cumulative_steps=0,
            seconds=0.0,
            rejected_rollouts=0,
            censored_rollouts=0,
            endpoint_counts=(),
            action_kind_counts=((action_kind, 1),),
            intent_counts=((root.intent.value if root.intent else "none", 1),),
            route_counts=((root.route.value if root.route else "none", 1),),
            ordinary_index=0,
            behavior_index=0,
            teacher_selected_index=0,
            executed_index=0,
            ordinary_action=root.action,
            ordinary_intent=root.intent,
            ordinary_route=root.route,
            behavior_action=root.action,
            behavior_intent=root.intent,
            behavior_route=root.route,
            teacher_action=root.action,
            teacher_intent=root.intent,
            teacher_route=root.route,
            executed_action=root.action,
            executed_intent=root.intent,
            executed_route=root.route,
            fallback_reason=reason,
            affects_actions=self.success_terminal_actions is not None,
            unavailable=True,
            unsupported=unsupported,
        )
        self.last_success_decision = decision
        self.success_decisions.append(decision)

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
        ordinary_index: int,
        intent_aware: bool,
        engine_goal: RunGoal,
        execution_admissible: Sequence[bool] | None = None,
    ) -> int:
        if self.timing is None:
            return self._collect_success_teacher_inner(
                observation,
                history,
                roots,
                behavior_index=behavior_index,
                ordinary_index=ordinary_index,
                intent_aware=intent_aware,
                engine_goal=engine_goal,
                execution_admissible=execution_admissible,
            )
        with self.timing.terminal_anchor():
            return self._collect_success_teacher_inner(
                observation,
                history,
                roots,
                behavior_index=behavior_index,
                ordinary_index=ordinary_index,
                intent_aware=intent_aware,
                engine_goal=engine_goal,
                execution_admissible=execution_admissible,
            )

    def _collect_success_teacher_inner(
        self,
        observation: PublicObservation,
        history: tuple[PublicHistoryStep, ...],
        roots: Sequence[StrategyCandidateRoot],
        *,
        behavior_index: int,
        ordinary_index: int,
        intent_aware: bool,
        engine_goal: RunGoal,
        execution_admissible: Sequence[bool] | None = None,
    ) -> int:
        """Evaluate a sparse terminal anchor and return the public root to execute."""

        budget = self.success_teacher
        if budget is None:  # pragma: no cover - caller guard
            return behavior_index
        reference_index = ordinary_index
        if not 0 <= reference_index < len(roots):
            raise ValueError("success teacher ordinary index is out of range")
        teacher_started = time.perf_counter()
        outcomes: list[list[RolloutOutcome]] = [[] for _ in roots]
        root_steps = [0 for _ in roots]
        endpoint_counts: Counter[str] = Counter()
        action_kind_counts = Counter(
            str(action_to_data(root.action)["type"]) for root in roots
        )
        intent_counts = Counter(
            root.intent.value if root.intent is not None else "none" for root in roots
        )
        route_counts = Counter(
            root.route.value if root.route is not None else "none" for root in roots
        )
        self.counters.success_anchors_attempted += 1
        terminal_objective = (
            observation.won or observation.ante >= budget.prewin_start_ante
        )
        prefix_best_hand_score = _public_best_hand_score(history)
        action_budget = self.success_terminal_actions
        required_positive = (
            _required_positive_discordances(len(roots), action_budget.family_alpha)
            if action_budget is not None
            else 0
        )

        def finish(
            *,
            teacher_index: int,
            executed_index: int,
            fallback_reason: str | None,
            positive_discordances: int = 0,
            adverse_discordances: int = 0,
            unavailable: bool = False,
        ) -> int:
            seconds = time.perf_counter() - teacher_started
            self.counters.seconds += seconds
            self.counters.success_teacher_seconds += seconds
            if unavailable:
                self.counters.success_anchor_unavailable += 1
            elif fallback_reason is None:
                self.counters.success_anchors_completed += 1
            if action_budget is not None and fallback_reason is not None:
                self.counters.success_anchor_fallbacks += 1
            behavior_root = roots[behavior_index]
            ordinary_root = roots[reference_index]
            teacher_root = roots[teacher_index]
            executed_root = roots[executed_index]
            if action_budget is not None and executed_index != behavior_index:
                if executed_root.action != behavior_root.action:
                    self.counters.success_action_overrides += 1
                elif executed_root.intent != behavior_root.intent:
                    self.counters.success_intent_only_overrides += 1
                else:
                    self.counters.success_route_only_overrides += 1
            decision = SuccessTeacherDecision(
                phase=observation.phase.value,
                ante=observation.ante,
                goal=engine_goal.value,
                roots=len(roots),
                initial_samples=budget.samples,
                max_samples_used=max((len(row) for row in outcomes), default=0),
                sample_evaluations=sum(len(row) for row in outcomes),
                steps=sum(root_steps),
                max_root_cumulative_steps=max(root_steps, default=0),
                seconds=seconds,
                rejected_rollouts=sum(
                    outcome.rejected for row in outcomes for outcome in row
                ),
                censored_rollouts=sum(
                    outcome.endpoint == StrategyTargetEndpoint.CENSORED
                    for row in outcomes
                    for outcome in row
                ),
                endpoint_counts=tuple(sorted(endpoint_counts.items())),
                action_kind_counts=tuple(sorted(action_kind_counts.items())),
                intent_counts=tuple(sorted(intent_counts.items())),
                route_counts=tuple(sorted(route_counts.items())),
                ordinary_index=reference_index,
                behavior_index=behavior_index,
                teacher_selected_index=teacher_index,
                executed_index=executed_index,
                ordinary_action=ordinary_root.action,
                ordinary_intent=ordinary_root.intent,
                ordinary_route=ordinary_root.route,
                behavior_action=behavior_root.action,
                behavior_intent=behavior_root.intent,
                behavior_route=behavior_root.route,
                teacher_action=teacher_root.action,
                teacher_intent=teacher_root.intent,
                teacher_route=teacher_root.route,
                executed_action=executed_root.action,
                executed_intent=executed_root.intent,
                executed_route=executed_root.route,
                fallback_reason=fallback_reason,
                affects_actions=action_budget is not None,
                unavailable=unavailable,
                positive_discordances=positive_discordances,
                adverse_discordances=adverse_discordances,
                required_positive_discordances=required_positive,
            )
            self.last_success_decision = decision
            self.success_decisions.append(decision)
            return executed_index

        if action_budget is not None and not terminal_objective:
            return finish(
                teacher_index=behavior_index,
                executed_index=behavior_index,
                fallback_reason="early_anchor_inert",
            )
        if action_budget is not None and len(roots) > action_budget.max_roots:
            return finish(
                teacher_index=behavior_index,
                executed_index=behavior_index,
                fallback_reason="root_compute_bound_exceeded",
                unavailable=True,
            )
        if action_budget is not None and required_positive > action_budget.max_samples:
            return finish(
                teacher_index=behavior_index,
                executed_index=behavior_index,
                fallback_reason="root_count_bound_unattainable",
                unavailable=True,
            )

        def evaluate_sample(sample_index: int, root_indexes: Sequence[int]) -> None:
            sample_started = (
                time.perf_counter_ns() if self.timing is not None else None
            )
            try:
                sample = self._sample_root(
                    observation,
                    history,
                    f"{self.nonce}:success-terminal-v1",
                    sample_index,
                )
                try:
                    frozen_sample = freeze_backend(sample)
                finally:
                    sample.close()
            finally:
                if sample_started is not None and self.timing is not None:
                    self.timing.record(
                        "success_teacher",
                        "sample_and_freeze",
                        time.perf_counter_ns() - sample_started,
                    )
            for root_index in root_indexes:
                root = roots[root_index]
                clone = self._clone_for_rollout(frozen_sample, "success_teacher")
                try:
                    outcome = self._rollout(
                        clone,
                        observation,
                        history,
                        root.action,
                        intent=root.intent if intent_aware else None,
                        route=root.route,
                        isolate_continuation=True,
                        success_goal=engine_goal if terminal_objective else None,
                        max_steps=(
                            budget.max_steps
                            if terminal_objective
                            else self.budget.max_steps
                        ),
                        endless_horizon_antes=budget.endless_horizon_antes,
                        prefix_best_hand_score=prefix_best_hand_score,
                        timing_path="success_teacher",
                    )
                finally:
                    self._close_rollout_clone(clone, "success_teacher")
                outcomes[root_index].append(outcome)
                root_steps[root_index] += outcome.steps
                endpoint_counts[outcome.endpoint.value] += 1
                self.counters.success_teacher_steps += outcome.steps
                self.counters.rollout_steps += outcome.steps
                if outcome.rejected:
                    self.counters.success_teacher_rejected_rollouts += 1
                    self.counters.rejected_rollouts += 1
                if outcome.endpoint == StrategyTargetEndpoint.CENSORED:
                    self.counters.success_teacher_censored_rollouts += 1

        try:
            for sample_index in range(budget.samples):
                evaluate_sample(sample_index, tuple(range(len(roots))))
        except DeterminizationUnavailable:
            return finish(
                teacher_index=behavior_index,
                executed_index=behavior_index,
                fallback_reason="determinization_unavailable",
                unavailable=True,
            )

        flat_outcomes = tuple(outcome for row in outcomes for outcome in row)
        if any(outcome.rejected for outcome in flat_outcomes):
            return finish(
                teacher_index=behavior_index,
                executed_index=behavior_index,
                fallback_reason="rejected_root",
            )
        if any(
            outcome.endpoint == StrategyTargetEndpoint.CENSORED
            for outcome in flat_outcomes
        ):
            return finish(
                teacher_index=behavior_index,
                executed_index=behavior_index,
                fallback_reason="censored_root",
            )
        utilities = tuple(
            tuple(outcome.goal_utility for outcome in row) for row in outcomes
        )
        if any(utility is None for row in utilities for utility in row):
            raise AssertionError("success teacher rollout omitted goal utility")
        typed_utilities = tuple(
            tuple(utility for utility in row if utility is not None)
            for row in utilities
        )
        if action_budget is None:
            selected_index = _select_goal_root(
                typed_utilities,
                baseline_index=reference_index,
                goal=engine_goal,
                override_z=self.budget.override_z,
            )
            self.teacher_drafts.append(
                StrategyTeacherDraft(
                    observation=observation,
                    context=derive_public_strategy_context(
                        observation,
                        history,
                        incoming_intent=(
                            self.active_intent.intent
                            if self.active_intent is not None
                            else None
                        ),
                        incoming_route=(
                            self.active_route.route
                            if self.active_route is not None
                            else None
                        ),
                    ),
                    candidates=tuple(
                        StrategyTeacherCandidate(
                            action=root.action,
                            intent=root.intent,
                            route=root.route,
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
                    baseline_index=reference_index,
                    ordinary_index=reference_index,
                    behavior_index=behavior_index,
                    goal=engine_goal,
                    teacher_config_digest=_teacher_config_digest(self),
                    candidate_space_size=len(roots),
                )
            )
            return finish(
                teacher_index=selected_index,
                executed_index=behavior_index,
                fallback_reason=None,
            )

        if any(not outcome.terminal_action_admissible for outcome in flat_outcomes):
            return finish(
                teacher_index=behavior_index,
                executed_index=behavior_index,
                fallback_reason="nonterminal_public_dead_end",
            )

        positive = Counter[int]()
        adverse = Counter[int]()
        survivors: set[int] = set()
        for root_index in range(len(roots)):
            if root_index == behavior_index:
                continue
            for outcome, baseline_outcome in zip(
                outcomes[root_index], outcomes[behavior_index], strict=True
            ):
                relation = _terminal_action_relation(
                    outcome, baseline_outcome, engine_goal
                )
                positive[root_index] += int(relation > 0)
                adverse[root_index] += int(relation < 0)
            if adverse[root_index] == 0 and positive[root_index] > 0:
                survivors.add(root_index)

        def qualified_indexes() -> tuple[int, ...]:
            return tuple(
                index
                for index in survivors
                if adverse[index] == 0 and positive[index] >= required_positive
            )

        sample_index = budget.samples
        qualified = qualified_indexes()
        try:
            while (
                not qualified and survivors and sample_index < action_budget.max_samples
            ):
                evaluated = (behavior_index, *sorted(survivors))
                evaluate_sample(sample_index, evaluated)
                baseline_outcome = outcomes[behavior_index][-1]
                if (
                    baseline_outcome.rejected
                    or baseline_outcome.endpoint == StrategyTargetEndpoint.CENSORED
                    or not baseline_outcome.terminal_action_admissible
                ):
                    return finish(
                        teacher_index=behavior_index,
                        executed_index=behavior_index,
                        fallback_reason="inadmissible_additional_sample",
                    )
                for root_index in tuple(survivors):
                    outcome = outcomes[root_index][-1]
                    if (
                        outcome.rejected
                        or outcome.endpoint == StrategyTargetEndpoint.CENSORED
                        or not outcome.terminal_action_admissible
                    ):
                        return finish(
                            teacher_index=behavior_index,
                            executed_index=behavior_index,
                            fallback_reason="inadmissible_additional_sample",
                        )
                    relation = _terminal_action_relation(
                        outcome, baseline_outcome, engine_goal
                    )
                    positive[root_index] += int(relation > 0)
                    adverse[root_index] += int(relation < 0)
                    if adverse[root_index] > 0:
                        survivors.remove(root_index)
                sample_index += 1
                qualified = qualified_indexes()
        except DeterminizationUnavailable:
            return finish(
                teacher_index=behavior_index,
                executed_index=behavior_index,
                fallback_reason="determinization_unavailable",
                unavailable=True,
            )

        if not qualified:
            return finish(
                teacher_index=behavior_index,
                executed_index=behavior_index,
                fallback_reason="insufficient_terminal_dominance",
            )

        teacher_selected_index = max(
            qualified,
            key=lambda index: (
                positive[index],
                _mean_terminal_action_key(outcomes[index], engine_goal),
                -index,
            ),
        )
        executable = (
            qualified
            if execution_admissible is None
            else tuple(index for index in qualified if execution_admissible[index])
        )
        if not executable:
            return finish(
                teacher_index=teacher_selected_index,
                executed_index=behavior_index,
                fallback_reason="specialist_not_scalar_admissible",
                positive_discordances=positive[teacher_selected_index],
                adverse_discordances=adverse[teacher_selected_index],
            )
        selected_index = max(
            executable,
            key=lambda index: (
                positive[index],
                _mean_terminal_action_key(outcomes[index], engine_goal),
                -index,
            ),
        )
        return finish(
            teacher_index=teacher_selected_index,
            executed_index=selected_index,
            fallback_reason=None,
            positive_discordances=positive[selected_index],
            adverse_discordances=adverse[selected_index],
        )

    def _clone_for_rollout(
        self,
        frozen_sample: FrozenJackdawBackend,
        timing_path: str,
    ) -> JackdawBackend:
        if self.timing is None:
            return frozen_sample.clone()
        started = time.perf_counter_ns()
        try:
            return frozen_sample.clone()
        finally:
            self.timing.record(
                timing_path,
                "clone",
                time.perf_counter_ns() - started,
            )

    def _sample_root(
        self,
        observation: PublicObservation,
        history: Sequence[PublicHistoryStep],
        nonce: str,
        index: int,
    ) -> JackdawBackend:
        if self.root_factory is not None:
            return self.root_factory(observation, history, nonce, index)
        return sample_candidate(
            self.backend,  # type: ignore[arg-type]
            observation,
            history,
            sample_seed(observation, nonce, index),
        )

    def _close_rollout_clone(
        self,
        clone: JackdawBackend,
        timing_path: str,
    ) -> None:
        if self.timing is None:
            clone.close()
            return
        started = time.perf_counter_ns()
        try:
            clone.close()
        finally:
            self.timing.record(
                timing_path,
                "close",
                time.perf_counter_ns() - started,
            )

    def _rollout(
        self,
        clone: JackdawBackend,
        observation: PublicObservation,
        history: Sequence[PublicHistoryStep],
        root: PublicAction,
        *,
        intent: StrategyIntent | None = None,
        route: RunRoute | None = None,
        isolate_continuation: bool = False,
        success_goal: RunGoal | None = None,
        max_steps: int | None = None,
        endless_horizon_antes: int = 2,
        prefix_best_hand_score: int | None = None,
        timing_path: str | None = None,
    ) -> RolloutOutcome:
        if route == RunRoute.VICTORY:
            intent = None
            route = None
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
        best_hand_score = (
            _public_best_hand_score(history)
            if prefix_best_hand_score is None
            else prefix_best_hand_score
        )
        continuation = self.rollout_continuation or self.continuation
        if isolate_continuation:
            fork = getattr(continuation, "fork_for_rollout", None)
            if callable(fork):
                try:
                    if route is not None and callable(
                        getattr(continuation, "choose_action_for_strategy", None)
                    ):
                        continuation = fork(intent, route)
                    else:
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
                    continuation = deepcopy(continuation)
                except Exception as exc:
                    value = _progress_value(current, start_rounds)
                    return RolloutOutcome(
                        value,
                        steps,
                        True,
                        _goal_utility(current, value, best_hand_score, alive=False),
                        _exception_reason("copy_exception", exc),
                    )
            if continuation is (self.rollout_continuation or self.continuation):
                value = _progress_value(current, start_rounds)
                return RolloutOutcome(
                    value,
                    steps,
                    True,
                    _goal_utility(current, value, best_hand_score, alive=False),
                    "fork_returned_shared_instance",
                )
            if route is not None and not callable(
                getattr(continuation, "choose_action_for_strategy", None)
            ):
                value = _progress_value(current, start_rounds)
                return RolloutOutcome(
                    value,
                    steps,
                    True,
                    _goal_utility(current, value, best_hand_score, alive=False),
                    "fork_lost_route_capability",
                )
            if route is None and intent is not None and not callable(
                getattr(continuation, "choose_action_for_intent", None)
            ):
                value = _progress_value(current, start_rounds)
                return RolloutOutcome(
                    value,
                    steps,
                    True,
                    _goal_utility(current, value, best_hand_score, alive=False),
                    "fork_lost_intent_capability",
                )
        while True:
            step_started = (
                time.perf_counter_ns()
                if timing_path is not None and self.timing is not None
                else None
            )
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
            finally:
                if (
                    step_started is not None
                    and timing_path is not None
                    and self.timing is not None
                ):
                    stage = (
                        "root_step"
                        if steps == 0
                        else "continuation_step_play"
                        if isinstance(action, PlayCards)
                        else "continuation_step_other"
                    )
                    self.timing.record(
                        timing_path,
                        stage,
                        time.perf_counter_ns() - step_started,
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
                value = _progress_value(current, start_rounds)
                return RolloutOutcome(
                    value,
                    steps,
                    True,
                    _goal_utility(current, value, best_hand_score, alive=False),
                    "missing_public_projection",
                )
            trajectory.append(PublicHistoryStep(current, action, after))
            if isinstance(action, PlayCards):
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
            choose_started = (
                time.perf_counter_ns()
                if timing_path is not None and self.timing is not None
                else None
            )
            try:
                choose_for_strategy = getattr(
                    continuation, "choose_action_for_strategy", None
                )
                choose_for_intent = getattr(
                    continuation, "choose_action_for_intent", None
                )
                if route is not None and callable(choose_for_strategy):
                    action = choose_for_strategy(
                        current,
                        lambda: iter_legal_actions(current),
                        tuple(trajectory),
                        intent,
                        route,
                    )
                elif intent is not None and callable(choose_for_intent):
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
                    terminal_action_admissible=False,
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
            finally:
                if (
                    choose_started is not None
                    and timing_path is not None
                    and self.timing is not None
                ):
                    self.timing.record(
                        timing_path,
                        "continuation_choose",
                        time.perf_counter_ns() - choose_started,
                    )

    def _record_strategy(
        self,
        observation: PublicObservation,
        roots: Sequence[_SearchRoot],
        baseline: PublicAction,
        ordinary: _SearchRoot,
        selected: _SearchRoot,
        goal_values: tuple[tuple[str, tuple[float, ...]], ...],
        steps: int,
        rejected: int,
        started: float,
        unavailable_reason: str | None,
        *,
        scalar_means: dict[str, float] | None = None,
        rejection_reasons: tuple[tuple[str, int], ...] = (),
        specialist_unavailable_reason: str | None = None,
        ordinary_root_count: int | None = None,
        specialist_root_count: int = 0,
        specialist_root_generated_count: int = 0,
        specialist_paired_mean_delta: float = 0.0,
        specialist_paired_lower_bound: float = 0.0,
        best_specialist: str | None = None,
        best_specialist_paired_mean_delta: float = 0.0,
        best_specialist_paired_lower_bound: float = 0.0,
        best_specialist_rejected: bool = False,
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
            baseline_intent=None,
            baseline_route=None,
            selected_intent=(
                selected.intent.value if selected.intent is not None else None
            ),
            selected_route=(
                selected.route.value if selected.route is not None else None
            ),
            ordinary_selected=_label(ordinary.action),
            ordinary_selected_intent=(
                ordinary.intent.value if ordinary.intent is not None else None
            ),
            ordinary_selected_route=(
                ordinary.route.value if ordinary.route is not None else None
            ),
            specialist_override=selected.identity != ordinary.identity,
            specialist_unavailable_reason=specialist_unavailable_reason,
            ordinary_roots=(
                len(roots) if ordinary_root_count is None else ordinary_root_count
            ),
            specialist_roots=specialist_root_count,
            specialist_roots_generated=specialist_root_generated_count,
            specialist_paired_mean_delta=specialist_paired_mean_delta,
            specialist_paired_lower_bound=specialist_paired_lower_bound,
            best_specialist=best_specialist,
            best_specialist_paired_mean_delta=best_specialist_paired_mean_delta,
            best_specialist_paired_lower_bound=best_specialist_paired_lower_bound,
            best_specialist_rejected=best_specialist_rejected,
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
        rejection_reasons: tuple[tuple[str, int], ...] = (),
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
            ordinary_selected=_label(selected),
            ordinary_roots=len(roots),
            unavailable_reason=unavailable_reason,
            rejection_reasons=rejection_reasons,
        )
        self.last_decision = decision
        self.decisions.append(decision)


def select_paired_root(
    values: Sequence[Sequence[float]],
    baseline_index: int,
    override_z: float,
    admissible: Sequence[bool] | None = None,
) -> int:
    """Override the continuation only on significant paired evidence.

    Roots share samples, so each root has a per-sample delta against the
    continuation's own choice.  A root is eligible when its mean delta minus
    ``override_z`` standard errors is still positive.  Among eligible roots the
    largest mean wins; otherwise the continuation's choice stands.  Without
    this, near-ties at easy antes are decided by rollout noise.
    """

    baseline_values = values[baseline_index]
    best_index = baseline_index
    best_mean = None
    for index, root_values in enumerate(values):
        if index == baseline_index:
            continue
        if admissible is not None and not admissible[index]:
            continue
        mean, lower = _paired_delta_evidence(
            root_values, baseline_values, override_z
        )
        if mean <= 0:
            continue
        if lower <= 0:
            continue
        if best_mean is None or mean > best_mean:
            best_mean = mean
            best_index = index
    return best_index


def _paired_delta_evidence(
    root_values: Sequence[float],
    baseline_values: Sequence[float],
    override_z: float,
) -> tuple[float, float]:
    """Return the paired mean delta and the selector's lower confidence bound."""

    deltas = [
        root - base
        for root, base in zip(root_values, baseline_values, strict=True)
    ]
    if not deltas:
        return 0.0, 0.0
    mean = sum(deltas) / len(deltas)
    if len(deltas) == 1:
        return mean, mean
    variance = sum((delta - mean) ** 2 for delta in deltas) / (len(deltas) - 1)
    lower = mean - override_z * math.sqrt(variance) / math.sqrt(len(deltas))
    return mean, lower


def _dense_teacher_indexes(
    roots: Sequence[PublicAction],
    *,
    baseline_index: int,
    selected_index: int,
    limit: int,
) -> tuple[int, ...]:
    """Retain the complete deployable root set or fail closed above the cap."""

    if (
        limit < 2
        or not 0 <= baseline_index < len(roots)
        or not 0 <= selected_index < len(roots)
    ):
        raise ValueError("dense teacher subset inputs are invalid")
    if len(roots) <= limit:
        return tuple(range(len(roots)))
    raise ValueError("dense teacher root set exceeds the complete-root cap")


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


def _required_positive_discordances(root_count: int, family_alpha: float) -> int:
    """Return the zero-adverse sign count needed after searching sibling roots."""

    comparisons = max(1, root_count - 1)
    return max(1, math.ceil(math.log2(comparisons / family_alpha)))


def _terminal_action_key(
    outcome: RolloutOutcome,
    goal: RunGoal,
) -> tuple[float, ...]:
    utility = outcome.goal_utility
    if utility is None:
        raise ValueError("terminal action rollout omitted goal utility")
    if goal == RunGoal.VICTORY:
        return (float(outcome.endpoint == StrategyTargetEndpoint.VICTORY),)
    return (
        utility.alive_probability,
        utility.endless_ante,
        utility.log_score,
    )


def _terminal_action_relation(
    outcome: RolloutOutcome,
    baseline: RolloutOutcome,
    goal: RunGoal,
) -> int:
    candidate_key = _terminal_action_key(outcome, goal)
    baseline_key = _terminal_action_key(baseline, goal)
    return (candidate_key > baseline_key) - (candidate_key < baseline_key)


def _mean_terminal_action_key(
    outcomes: Sequence[RolloutOutcome],
    goal: RunGoal,
) -> tuple[float, ...]:
    keys = tuple(_terminal_action_key(outcome, goal) for outcome in outcomes)
    return tuple(
        sum(key[index] for key in keys) / len(keys) for index in range(len(keys[0]))
    )


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
            search_utility=outcome.value,
            endpoint=StrategyTargetEndpoint.CENSORED,
        )
    ante8_win: float | None = None
    if goal == RunGoal.VICTORY:
        if utility.win_probability == 1.0:
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
        search_utility=outcome.value,
        endpoint=outcome.endpoint,
    )


def _public_best_hand_score(history: Sequence[PublicHistoryStep]) -> int:
    """Recover the largest public scoring delta from the typed prefix."""

    return max(
        (
            max(0, step.after.round.chips - step.before.round.chips)
            for step in history
            if isinstance(step.action, PlayCards)
        ),
        default=0,
    )


def _teacher_config_digest(policy: DeterminizedSearchPolicy) -> str:
    continuation_config = (
        asdict(policy.continuation) if is_dataclass(policy.continuation) else None
    )
    rollout_continuation = policy.rollout_continuation or policy.continuation
    rollout_continuation_config = (
        asdict(rollout_continuation) if is_dataclass(rollout_continuation) else None
    )
    payload = {
        "search_version": SEARCH_VERSION,
        "teacher_schema_version": STRATEGY_TEACHER_SCHEMA_VERSION,
        "budget": policy.budget.canonical(),
        "nonce": policy.nonce,
        "strategy_options": policy.enable_strategy_options,
        "dense_teacher": policy.collect_dense_teacher,
        "dense_teacher_max_roots": DENSE_TEACHER_MAX_ROOTS,
        "dense_teacher_subset": DENSE_TEACHER_SUBSET_CONTRACT,
        "include_reorders": policy.include_reorders,
        "success_teacher": (
            policy.success_teacher.canonical()
            if policy.success_teacher is not None
            else None
        ),
        "success_terminal_actions": (
            policy.success_terminal_actions.canonical()
            if policy.success_terminal_actions is not None
            else None
        ),
        "continuation_type": (
            f"{type(policy.continuation).__module__}."
            f"{type(policy.continuation).__qualname__}"
        ),
        "continuation_config": continuation_config,
        "rollout_continuation_type": (
            f"{type(rollout_continuation).__module__}."
            f"{type(rollout_continuation).__qualname__}"
        ),
        "rollout_continuation_config": rollout_continuation_config,
        "backend": (
            asdict(policy.backend.metadata)
            if policy.backend is not None
            else {
                "public_root_factory": (
                    f"{policy.root_factory.__module__}."
                    f"{policy.root_factory.__qualname__}"
                    if policy.root_factory is not None
                    else None
                )
            }
        ),
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
    intent = root.intent.value if root.intent is not None else "baseline"
    route = root.route.value if root.route is not None else "none"
    return f"{label}|intent={intent}|route={route}"
