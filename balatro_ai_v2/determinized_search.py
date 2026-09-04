"""Search at strategic decisions by determinized Jackdaw rollouts.

Parent-only.  ``DeterminizedSearchPolicy`` implements ``PublicPolicy`` for
the evaluator parent: it reads the public observation like any policy, but
values each legal strategic action by rolling sampled futures forward in the
candidate simulator.  Tactical decisions are delegated to the continuation
policy unchanged.

The decision sees per-root scalar values and aggregate diagnostics only.
Sampled states never leave this module.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field

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
from balatro_ai_v2.policy import ActionSource, PublicHistoryStep, PublicPolicy
from balatro_ai_v2.public_state import PublicObservation


SEARCH_VERSION = "determinized-search-v1"
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
class RolloutOutcome:
    value: float
    steps: int
    rejected: bool


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

    def as_dict(self) -> dict[str, object]:
        return {
            "strategic_decisions": self.strategic_decisions,
            "searched": self.searched,
            "changed": self.changed,
            "unavailable": self.unavailable,
            "rollout_steps": self.rollout_steps,
            "rejected_rollouts": self.rejected_rollouts,
            "seconds": self.seconds,
            "steps_per_second": (self.rollout_steps / self.seconds) if self.seconds > 0 else 0.0,
        }


@dataclass(slots=True)
class DeterminizedSearchPolicy:
    """Roots at strategic decisions, valued by paired determinized rollouts."""

    backend: JackdawBackend
    continuation: PublicPolicy
    nonce: str = "search-v1"
    budget: RolloutBudget = RolloutBudget()
    last_decision: SearchDecision | None = None
    counters: SearchCounters = field(default_factory=SearchCounters)
    decisions: list[SearchDecision] = field(default_factory=list)

    def reset_run(self) -> None:
        self.last_decision = None
        self.counters = SearchCounters()
        self.decisions = []

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        baseline = self.continuation.choose_action(observation, legal_actions, history)
        self.last_decision = None
        if observation.phase not in STRATEGIC_PHASES:
            return baseline
        self.counters.strategic_decisions += 1
        roots = [action for action in legal_actions() if not isinstance(action, _REORDER_TYPES)]
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
            self._record(observation, roots, baseline, baseline, {}, 0, 0, started, str(exc))
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
        return selected

    def _rollout(
        self,
        clone: JackdawBackend,
        observation: PublicObservation,
        history: Sequence[PublicHistoryStep],
        root: PublicAction,
    ) -> RolloutOutcome:
        start_rounds = observation.round_no
        start_antes = observation.antes_cleared
        horizon = start_antes + self.budget.horizon_antes
        trajectory = list(history)
        current = observation
        action = root
        steps = 0
        while True:
            result = clone.step(action)
            steps += 1
            if result.status != "accepted" or result.after is None:
                return RolloutOutcome(_progress_value(current, start_rounds), steps, True)
            after = clone.current_public
            if after is None:
                after = to_public_observation(json.loads(result.after.observed.raw_json))
            trajectory.append(PublicHistoryStep(current, action, after))
            if after.terminal:
                return RolloutOutcome(_progress_value(current, start_rounds, after), steps, False)
            current = after
            if current.antes_cleared >= horizon:
                return RolloutOutcome(float(current.round_no - start_rounds) + 1.0, steps, False)
            if steps >= self.budget.max_steps:
                return RolloutOutcome(_progress_value(current, start_rounds), steps, False)
            try:
                action = self.continuation.choose_action(
                    current, lambda: iter_legal_actions(current), tuple(trajectory)
                )
            except Exception:  # a continuation failure inside a sample fails closed for that rollout only
                return RolloutOutcome(_progress_value(current, start_rounds), steps, True)

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


def _select_root(values: Sequence[Sequence[float]], baseline_index: int, override_z: float) -> int:
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
        deltas = [root - base for root, base in zip(root_values, baseline_values, strict=True)]
        mean = sum(deltas) / count
        if mean <= 0:
            continue
        if count > 1:
            variance = sum((delta - mean) ** 2 for delta in deltas) / (count - 1)
            lower = mean - override_z * (variance ** 0.5) / (count ** 0.5)
        else:
            lower = mean
        if lower <= 0:
            continue
        if best_mean is None or mean > best_mean:
            best_mean = mean
            best_index = index
    return best_index


def _progress_value(
    last_alive: PublicObservation,
    start_rounds: int,
    terminal: PublicObservation | None = None,
) -> float:
    """Rounds cleared within the horizon plus the fraction of the failed blind scored."""

    rounds = float(last_alive.round_no - start_rounds)
    current = next((blind for blind in last_alive.blinds if blind.status == "CURRENT"), None)
    if current is None or current.score <= 0:
        return rounds
    chips = terminal.round.chips if terminal is not None and terminal.round.chips > last_alive.round.chips else last_alive.round.chips
    return rounds + min(0.99, max(0.0, chips / current.score))


def _label(action: PublicAction) -> str:
    return json.dumps(action_to_data(action), sort_keys=True, separators=(",", ":"))
