"""Policy runner that never exposes privileged authority state."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Protocol

from balatro_ai_v2.actions import (
    CashOut,
    HandSlot,
    LeaveShop,
    PlayCards,
    PublicAction,
    SelectBlind,
    SkipPack,
    action_to_data,
    is_legal,
    iter_legal_actions,
)
from balatro_ai_v2.backend import AuthorityObservation, GameBackend, RunSpec
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.balatrobot.backend import UnsettledStateError
from balatro_ai_v2.balatrobot.tracing import AuthorityTraceWriter
from balatro_ai_v2.public_state import Phase, PublicObservation


ActionSource = Callable[[], Iterator[PublicAction]]


@dataclass(frozen=True, slots=True)
class PublicHistoryStep:
    before: PublicObservation
    action: PublicAction
    after: PublicObservation


class PublicPolicy(Protocol):
    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction: ...


@dataclass(frozen=True, slots=True)
class RunResult:
    complete: bool
    won: bool
    ante: int
    round_no: int
    decisions: int
    rejected_decisions: int
    terminal_reason: str
    final_observation: PublicObservation | None


@dataclass(slots=True)
class AuthorityRunner:
    backend: GameBackend
    policy: PublicPolicy
    max_decisions: int = 800
    trace: AuthorityTraceWriter | None = None

    def run(self, spec: RunSpec) -> RunResult:
        history: list[PublicHistoryStep] = []
        rejected = 0
        final: PublicObservation | None = None
        terminal_reason = "policy_error"
        try:
            authority = self.backend.reset(spec)
            public = _public(authority)
            final = public
            self._record("run_start", authority=_authority_data(authority), public=json.loads(public.canonical_json()))
            for _ in range(self.max_decisions):
                if public.phase == Phase.GAME_OVER:
                    terminal_reason = "game_over"
                    break
                try:
                    action = self.policy.choose_action(
                        public,
                        lambda: iter_legal_actions(public),
                        tuple(history),
                    )
                except Exception as exc:  # the trace must close even for model failures
                    terminal_reason = "policy_error"
                    self._record("policy_error", error=f"{type(exc).__name__}: {exc}")
                    break
                if not is_legal(public, action):
                    terminal_reason = "policy_error"
                    self._record("policy_error", error=f"policy emitted illegal action {action!r}")
                    break

                result = self.backend.step(action)
                transition: dict[str, object] = {
                    "before_canonical_digest": authority.observed.canonical_digest,
                    "action": action_to_data(action),
                    "rpc_method": result.rpc_method,
                    "rpc_params": result.rpc_params,
                    "status": result.status,
                    "rpc_observations": [json.loads(value) for value in result.rpc_observations],
                    "error": result.error,
                }
                if result.status == "rejected":
                    rejected += 1
                    terminal_reason = "rejected_action"
                    self._record("transition", **transition)
                    break
                if result.status == "transport_error" or result.after is None:
                    terminal_reason = "transport_error"
                    self._record("transition", **transition)
                    break

                after_public = _public(result.after)
                transition.update(
                    after=_authority_data(result.after),
                    public_after=json.loads(after_public.canonical_json()),
                )
                self._record("transition", **transition)
                history.append(PublicHistoryStep(before=public, action=action, after=after_public))
                authority = result.after
                public = after_public
                final = public
                if public.phase == Phase.GAME_OVER:
                    terminal_reason = "game_over"
                    break
            else:
                terminal_reason = "decision_limit"
        except UnsettledStateError as exc:
            terminal_reason = "unsettled"
            self._record("authority_error", error=str(exc))

        complete = terminal_reason == "game_over" and final is not None
        result = RunResult(
            complete=complete,
            won=bool(final.won) if complete else False,
            ante=final.ante if final is not None else 0,
            round_no=final.round_no if final is not None else 0,
            decisions=len(history),
            rejected_decisions=rejected,
            terminal_reason=terminal_reason,
            final_observation=final,
        )
        self._record(
            "run_end",
            complete=result.complete,
            won=result.won,
            ante=result.ante,
            round_no=result.round_no,
            accepted_decisions=result.decisions,
            rejected_decisions=result.rejected_decisions,
            terminal_reason=result.terminal_reason,
            final_public_digest=final.digest() if final is not None else None,
        )
        return result

    def _record(self, event: str, **payload: object) -> None:
        if self.trace is not None:
            self.trace.record(event, **payload)


class NoBuySmokePolicy:
    """A public-only integration smoke test, deliberately not a solver."""

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        del legal_actions, history
        if observation.phase == Phase.BLIND_SELECT:
            return SelectBlind()
        if observation.phase == Phase.SELECTING_HAND:
            size = min(5, observation.selection_limit, len(observation.hand))
            return PlayCards(tuple(HandSlot(index) for index in range(size)))
        if observation.phase == Phase.ROUND_EVAL:
            return CashOut()
        if observation.phase == Phase.SHOP:
            return LeaveShop()
        if observation.phase == Phase.PACK:
            return SkipPack()
        raise RuntimeError(f"no smoke action for {observation.phase.value}")


def _public(authority: AuthorityObservation) -> PublicObservation:
    raw = json.loads(authority.observed.raw_json)
    if not isinstance(raw, dict):
        raise AssertionError("authority state root is not an object")
    return to_public_observation(raw)


def _authority_data(authority: AuthorityObservation) -> dict[str, object]:
    return {
        "raw": json.loads(authority.observed.raw_json),
        "canonical": json.loads(authority.observed.canonical_json),
        "raw_digest": authority.observed.raw_digest,
        "canonical_digest": authority.observed.canonical_digest,
        "settled": authority.settled,
        "poll_count": len(authority.polls) - 1,
    }
