"""Behavior-inert shadow scoring for the relational strategy model."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import torch

from balatro_ai_v2.actions import PublicAction, action_to_data
from balatro_ai_v2.policy import ActionSource, PublicHistoryStep, PublicPolicy
from balatro_ai_v2.public_state import Phase, PublicObservation
from balatro_ai_v2.strategy_context import derive_public_strategy_context
from balatro_ai_v2.strategy_engine import RunRoute
from balatro_ai_v2.strategy_model import (
    PublicStrategyTensorizer,
    RelationalStrategyPolicyValue,
)
from balatro_ai_v2.strategy_options import (
    PersistentIntent,
    PersistentRoute,
    StrategyCandidateRoot,
    StrategyIntent,
    build_strategy_candidates,
)


_STRATEGIC_PHASES = frozenset({Phase.BLIND_SELECT, Phase.SHOP, Phase.PACK})


@dataclass(frozen=True, slots=True)
class ShadowCandidateScore:
    action: PublicAction
    intent: StrategyIntent | None
    route: RunRoute | None
    logit: float


@dataclass(frozen=True, slots=True)
class ShadowStrategyDecision:
    phase: str
    control_action: PublicAction
    control_intent: StrategyIntent | None
    control_route: RunRoute | None
    preferred_action: PublicAction | None
    preferred_intent: StrategyIntent | None
    preferred_route: RunRoute | None
    baseline_logit: float | None
    preferred_logit: float | None
    baseline_relative_margin: float | None
    required_margin: float
    recommendation_clears_margin: bool
    calibrated: bool
    current_blind_survival: float | None
    next_boss_survival: float | None
    ante8_win: float | None
    endless_ante: float | None
    log_score: float | None
    calibrated_heads: tuple[str, ...]
    candidates: tuple[ShadowCandidateScore, ...]
    unavailable_reason: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "control": _label(self.control_action),
            "control_intent": (
                self.control_intent.value if self.control_intent is not None else None
            ),
            "control_route": (
                self.control_route.value if self.control_route is not None else None
            ),
            "preferred": (
                _label(self.preferred_action)
                if self.preferred_action is not None
                else None
            ),
            "preferred_intent": (
                self.preferred_intent.value
                if self.preferred_intent is not None
                else None
            ),
            "preferred_route": (
                self.preferred_route.value
                if self.preferred_route is not None
                else None
            ),
            "baseline_logit": self.baseline_logit,
            "preferred_logit": self.preferred_logit,
            "baseline_relative_margin": self.baseline_relative_margin,
            "required_margin": self.required_margin,
            "margin_signal_clears_threshold": self.recommendation_clears_margin,
            "calibrated": self.calibrated,
            "calibrated_heads": list(self.calibrated_heads),
            "value_predictions": {
                "current_blind_survival": self.current_blind_survival,
                "next_boss_survival": self.next_boss_survival,
                "ante8_win": self.ante8_win,
                "endless_ante": self.endless_ante,
                "log_score": self.log_score,
            },
            "candidates": [
                {
                    "action": _label(candidate.action),
                    "intent": candidate.intent.value
                    if candidate.intent is not None
                    else None,
                    "route": candidate.route.value
                    if candidate.route is not None
                    else None,
                    "logit": candidate.logit,
                }
                for candidate in self.candidates
            ],
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass(slots=True)
class ShadowStrategyPolicy:
    """Score public choices while always executing the wrapped control action."""

    control: PublicPolicy
    model: RelationalStrategyPolicyValue
    tensorizer: PublicStrategyTensorizer | None = None
    include_reorders: bool = False
    last_decision: ShadowStrategyDecision | None = None
    decisions: list[ShadowStrategyDecision] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.tensorizer is None:
            self.tensorizer = PublicStrategyTensorizer(self.model.config)
        elif self.tensorizer.config != self.model.config:
            raise ValueError("shadow tensorizer and strategy model configs must match")
        self.model.eval()

    def reset_run(self) -> None:
        self.last_decision = None
        self.decisions = []
        reset = getattr(self.control, "reset_run", None)
        if callable(reset):
            reset()

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        actions = tuple(legal_actions())
        active_before = getattr(self.control, "active_intent", None)
        active_route_before = getattr(self.control, "active_route", None)
        control_action = self.control.choose_action(
            observation,
            lambda: iter(actions),
            history,
        )
        calibration = self.model.calibration
        self.last_decision = None
        if observation.phase not in _STRATEGIC_PHASES:
            return control_action
        try:
            if control_action not in actions:
                raise ValueError(
                    "control action is absent from the supplied legal actions"
                )
            candidates, control_pair = self._candidates(
                observation,
                actions,
                control_action,
                active_before=(
                    active_before
                    if isinstance(active_before, PersistentIntent)
                    else None
                ),
                active_route_before=(
                    active_route_before
                    if isinstance(active_route_before, PersistentRoute)
                    else None
                ),
            )
            candidate_actions = tuple(action for action, _, _ in candidates)
            candidate_intents = tuple(intent for _, intent, _ in candidates)
            candidate_routes = tuple(route for _, _, route in candidates)
            if (
                self.tensorizer is None
            ):  # pragma: no cover - established in __post_init__
                raise AssertionError("shadow tensorizer is unavailable")
            batch = self.tensorizer.tensorize(
                observations=(observation,),
                legal_actions=(candidate_actions,),
                action_intents=(candidate_intents,),
                contexts=(
                    derive_public_strategy_context(
                        observation,
                        history,
                        incoming_intent=(
                            active_before.intent
                            if isinstance(active_before, PersistentIntent)
                            else None
                        ),
                        incoming_route=(
                            active_route_before.route
                            if isinstance(active_route_before, PersistentRoute)
                            else None
                        ),
                    ),
                ),
                action_routes=(candidate_routes,),
            )
            with torch.no_grad():
                output = self.model(batch)
            if output.policy_logits.shape != (1, len(candidates)):
                raise ValueError("shadow policy logits have the wrong shape")
            if not torch.isfinite(output.policy_logits).all():
                raise ValueError("shadow policy logits are not finite")
            value_tensors = (
                output.current_blind_survival,
                output.next_boss_survival,
                output.ante8_win,
                output.endless_ante,
                output.log_score,
            )
            if any(value.shape != (1, len(candidates)) for value in value_tensors):
                raise ValueError("shadow value prediction has the wrong shape")
            if not all(torch.isfinite(value).all() for value in value_tensors):
                raise ValueError("shadow value prediction is not finite")
            calibrated_heads = _calibrated_heads(self.model)
            logits = output.policy_logits[0].detach().cpu()
            preferred_index = int(torch.argmax(logits).item())
            value_predictions = tuple(
                float(value[0, preferred_index].detach().cpu().item())
                for value in value_tensors
            )
            baseline_index = candidates.index(control_pair)
            preferred_action, preferred_intent, preferred_route = candidates[
                preferred_index
            ]
            preferred_logit = float(logits[preferred_index].item())
            baseline_logit = float(logits[baseline_index].item())
            margin = preferred_logit - baseline_logit
            clears = (
                calibration.calibrated
                and preferred_index != baseline_index
                and margin > calibration.policy_override_margin
            )
            decision = ShadowStrategyDecision(
                phase=observation.phase.value,
                control_action=control_action,
                control_intent=control_pair[1],
                control_route=control_pair[2],
                preferred_action=preferred_action,
                preferred_intent=preferred_intent,
                preferred_route=preferred_route,
                baseline_logit=baseline_logit,
                preferred_logit=preferred_logit,
                baseline_relative_margin=margin,
                required_margin=calibration.policy_override_margin,
                recommendation_clears_margin=clears,
                calibrated=calibration.calibrated,
                current_blind_survival=value_predictions[0],
                next_boss_survival=value_predictions[1],
                ante8_win=value_predictions[2],
                endless_ante=value_predictions[3],
                log_score=value_predictions[4],
                calibrated_heads=calibrated_heads,
                candidates=tuple(
                    ShadowCandidateScore(action, intent, route, float(logit.item()))
                    for (action, intent, route), logit in zip(
                        candidates, logits, strict=True
                    )
                ),
            )
        except Exception as exc:
            decision = ShadowStrategyDecision(
                phase=observation.phase.value,
                control_action=control_action,
                control_intent=None,
                control_route=None,
                preferred_action=None,
                preferred_intent=None,
                preferred_route=None,
                baseline_logit=None,
                preferred_logit=None,
                baseline_relative_margin=None,
                required_margin=calibration.policy_override_margin,
                recommendation_clears_margin=False,
                calibrated=calibration.calibrated,
                current_blind_survival=None,
                next_boss_survival=None,
                ante8_win=None,
                endless_ante=None,
                log_score=None,
                calibrated_heads=(),
                candidates=(),
                unavailable_reason=f"{type(exc).__name__}: {exc}",
            )
        self.last_decision = decision
        self.decisions.append(decision)
        return control_action

    def _candidates(
        self,
        observation: PublicObservation,
        legal_actions: tuple[PublicAction, ...],
        control_action: PublicAction,
        *,
        active_before: PersistentIntent | None,
        active_route_before: PersistentRoute | None,
    ) -> tuple[
        tuple[tuple[PublicAction, StrategyIntent | None, RunRoute | None], ...],
        tuple[PublicAction, StrategyIntent | None, RunRoute | None],
    ]:
        recorded = getattr(self.control, "last_strategy_candidates", ())
        selected_index = getattr(self.control, "last_strategy_selected_index", None)
        if recorded:
            if not all(isinstance(root, StrategyCandidateRoot) for root in recorded):
                raise ValueError(
                    "control exposed an invalid strategy candidate contract"
                )
            if not isinstance(selected_index, int) or not 0 <= selected_index < len(
                recorded
            ):
                raise ValueError("control omitted its selected strategy identity")
            identities = tuple(root.identity for root in recorded)
            control_pair = identities[selected_index]
            if control_pair[0] != control_action:
                raise ValueError("control action disagrees with its strategy identity")
            return identities, control_pair
        roots = build_strategy_candidates(
            observation,
            legal_actions,
            control_action,
            active_intent=active_before,
            active_route=active_route_before,
            include_reorders=self.include_reorders,
            intent_aware=True,
            route_aware=True,
        )
        return tuple(root.identity for root in roots), roots[0].identity


def _label(action: PublicAction) -> str:
    return json.dumps(action_to_data(action), sort_keys=True, separators=(",", ":"))


def _calibrated_heads(model: RelationalStrategyPolicyValue) -> tuple[str, ...]:
    if not model.calibration.calibrated:
        return ()
    heads = ["policy"]
    provenance = getattr(model, "provenance", {})
    try:
        metrics = provenance["calibration"]["metrics"]
    except (KeyError, TypeError):
        return tuple(heads)
    for name in (
        "current_blind",
        "next_boss",
        "ante8",
        "endless_ante",
        "log_score",
    ):
        head = metrics.get(name) if isinstance(metrics, dict) else None
        count = head.get("count") if isinstance(head, dict) else None
        if isinstance(count, int | float) and not isinstance(count, bool) and count > 0:
            heads.append(name)
    return tuple(heads)


__all__ = [
    "ShadowCandidateScore",
    "ShadowStrategyDecision",
    "ShadowStrategyPolicy",
]
