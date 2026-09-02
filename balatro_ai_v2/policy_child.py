"""JSON-lines child process for public-only baseline policies."""

from __future__ import annotations

import argparse
import sys

from balatro_ai_v2.actions import PublicAction, is_legal, iter_legal_actions
from balatro_ai_v2.baselines import PUBLIC_BASELINE_NAMES, build_public_baseline
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.policy_wire import (
    PolicyDiagnostics,
    MAX_REQUEST_BYTES,
    PolicyResponse,
    SearchDecisionDiagnostics,
    decode_request,
    encode_response,
)
from balatro_ai_v2.blind_search import BlindSearchDecision
from balatro_ai_v2.preboss_search import PreBossSearchDecision, PublicPreBossSearchPolicy
from balatro_ai_v2.public_state import PublicObservation
from balatro_ai_v2.solver_policy import PublicRedGoldSearchPolicy


_FORBIDDEN_MODULE_PREFIXES = ("balatro_ai_v2.balatrobot", "balatro_ai_v2.jackdaw", "jackdaw")


def main() -> None:
    args = build_parser().parse_args()
    _require_public_imports_only()
    policy, _ = build_public_baseline(args.policy, args.policy_seed)
    history: list[PublicHistoryStep] = []
    pending: tuple[PublicObservation, PublicAction] | None = None
    while True:
        frame = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
        if not frame:
            return
        try:
            request = decode_request(frame)
            if request.history_length == 0:
                history.clear()
                pending = None
            else:
                if pending is None or request.history_length != len(history) + 1:
                    raise ValueError("policy child history is not a contiguous public trajectory")
                before, action = pending
                history.append(PublicHistoryStep(before, action, request.observation))
            action = policy.choose_action(
                request.observation,
                lambda: iter_legal_actions(request.observation),
                tuple(history),
            )
            if not is_legal(request.observation, action):
                raise ValueError("policy emitted an illegal public action")
            pending = (request.observation, action)
            response = PolicyResponse(
                request.request_id,
                request.observation.digest(),
                action,
                _policy_diagnostics(policy, request.observation),
            )
            sys.stdout.buffer.write(encode_response(response))
            sys.stdout.buffer.flush()
        except Exception as exc:
            print(f"policy child failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            raise SystemExit(2) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a public-only policy JSONL child")
    parser.add_argument("--policy", choices=PUBLIC_BASELINE_NAMES, required=True)
    parser.add_argument("--policy-seed", default="isolated-v1")
    return parser


def _require_public_imports_only() -> None:
    forbidden = sorted(
        name
        for name in sys.modules
        if any(name == prefix or name.startswith(f"{prefix}.") for prefix in _FORBIDDEN_MODULE_PREFIXES)
    )
    if forbidden:
        raise RuntimeError(f"policy child imported private engine modules: {forbidden}")


def _policy_diagnostics(policy: object, observation: PublicObservation) -> PolicyDiagnostics:
    """Project existing search records into the fixed, non-stateful wire form."""

    if isinstance(policy, PublicRedGoldSearchPolicy):
        if observation.phase.value == "SELECTING_HAND":
            return PolicyDiagnostics(exact_blind=_exact_diagnostics(policy.tactical.last_decision))
        return PolicyDiagnostics(preboss=_preboss_diagnostics(policy.strategic.last_decision))
    if isinstance(policy, PublicPreBossSearchPolicy):
        return PolicyDiagnostics(preboss=_preboss_diagnostics(policy.last_decision))
    return PolicyDiagnostics()


def _exact_diagnostics(decision: BlindSearchDecision | None) -> SearchDecisionDiagnostics:
    if decision is None:
        return SearchDecisionDiagnostics()
    return SearchDecisionDiagnostics(
        attempted=True,
        completed=decision.proposal_complete,
        changed=decision.selected != decision.baseline,
        incomplete_reason=_exact_incomplete_reason(decision.incomplete_reason),
    )


def _preboss_diagnostics(decision: PreBossSearchDecision | None) -> SearchDecisionDiagnostics:
    if decision is None:
        return SearchDecisionDiagnostics()
    return SearchDecisionDiagnostics(
        attempted=True,
        completed=True,
        changed=decision.selected != decision.baseline,
    )


def _exact_incomplete_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    prefixes = (
        ("decision horizon", "decision_horizon"),
        ("exact state budget", "state_budget"),
        ("future tactical baseline", "future_baseline_outside_action_space"),
        ("baseline action is not legal", "baseline_illegal"),
        ("raw proposal action budget", "raw_action_budget"),
        ("proposal action preflight", "proposal_preflight"),
        ("semantic action budget", "semantic_action_budget"),
        ("baseline semantic action", "baseline_semantic_absent"),
        ("exact evaluation omitted", "baseline_omitted"),
        ("exact transition budget", "transition_budget"),
        ("exact chance-outcome budget", "chance_outcome_budget"),
        ("exact draw distribution", "draw_distribution_budget"),
        ("exact successor probabilities", "successor_probability"),
        ("exact score budget", "score_budget"),
        ("missing public hand stat", "scoring_contract"),
    )
    return next((code for prefix, code in prefixes if reason.startswith(prefix)), "unknown")


if __name__ == "__main__":
    main()
