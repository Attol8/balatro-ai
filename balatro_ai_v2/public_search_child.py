"""Process-isolated search that receives only the strict public policy wire.

Unlike ``policy_child`` this process may import the pinned candidate simulator,
but it is never given an authority backend, seed, raw frame, or save state.
Every rollout root is reconstructed from the decoded public trajectory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from balatro_ai_v2.actions import (
    PublicAction,
    is_legal,
    iter_legal_actions,
)
from balatro_ai_v2.baselines import PUBLIC_BASELINE_NAMES, build_public_baseline
from balatro_ai_v2.determinized_search import DeterminizedSearchPolicy, RolloutBudget
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.policy_wire import (
    MAX_REQUEST_BYTES,
    PolicyDiagnostics,
    PolicyResponse,
    SearchDecisionDiagnostics,
    decode_request,
    encode_response,
)
from balatro_ai_v2.public_root import construct_public_root
from balatro_ai_v2.public_state import PublicObservation
from balatro_ai_v2.strategy_tuning import StrategyTuning


def main() -> None:
    args = build_parser().parse_args()
    tuning = StrategyTuning.from_json(args.tuning_json)
    continuation, _ = build_public_baseline(
        args.continuation,
        args.policy_nonce,
        tuning,
    )
    policy = DeterminizedSearchPolicy(
        backend=None,
        continuation=continuation,
        root_factory=construct_public_root,
        nonce=args.policy_nonce,
        budget=RolloutBudget(
            samples=args.samples,
            horizon_antes=args.horizon_antes,
            max_steps=args.max_steps,
            override_z=args.override_z,
        ),
        enable_strategy_options=args.strategy_options,
    )
    history: list[PublicHistoryStep] = []
    pending: tuple[PublicObservation, PublicAction] | None = None
    decision_log = None
    if args.decision_log is not None:
        args.decision_log.parent.mkdir(parents=True, exist_ok=True)
        decision_log = args.decision_log.open("x", encoding="utf-8")
    while True:
        frame = sys.stdin.buffer.readline(MAX_REQUEST_BYTES + 1)
        if not frame:
            return
        try:
            request = decode_request(frame)
            if request.history_length == 0:
                history.clear()
                pending = None
                policy.reset_run()
            else:
                if pending is None or request.history_length != len(history) + 1:
                    raise ValueError("search history is not a contiguous public trajectory")
                before, action = pending
                history.append(PublicHistoryStep(before, action, request.observation))
            action = policy.choose_action(
                request.observation,
                lambda: iter_legal_actions(request.observation),
                tuple(history),
            )
            if not is_legal(request.observation, action):
                raise ValueError("public-root search emitted an illegal action")
            if decision_log is not None and policy.last_decision is not None:
                decision = policy.last_decision
                decision_log.write(
                    json.dumps(
                        {
                            "ante": decision.ante,
                            "baseline": decision.baseline,
                            "changed": decision.selected != decision.baseline,
                            "phase": decision.phase,
                            "rejected_rollouts": decision.rejected_rollouts,
                            "rejection_reasons": decision.rejection_reasons,
                            "roots": decision.roots,
                            "samples": decision.samples,
                            "selected": decision.selected,
                            "steps": decision.steps,
                            "unavailable_reason": decision.unavailable_reason,
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                decision_log.flush()
            pending = (request.observation, action)
            response = PolicyResponse(
                request.request_id,
                request.observation.digest(),
                action,
                PolicyDiagnostics(public_root=_search_diagnostics(policy)),
            )
            sys.stdout.buffer.write(encode_response(response))
            sys.stdout.buffer.flush()
        except Exception as exc:
            print(
                f"public search child failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
                flush=True,
            )
            raise SystemExit(2) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run public-observation-root candidate search over JSONL"
    )
    parser.add_argument("--continuation", choices=PUBLIC_BASELINE_NAMES, default="strategic")
    parser.add_argument("--policy-nonce", default="live-public-search-v1")
    parser.add_argument("--samples", type=int, default=6)
    parser.add_argument("--horizon-antes", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--override-z", type=float, default=1.0)
    parser.add_argument("--strategy-options", action="store_true")
    parser.add_argument("--tuning-json", default=StrategyTuning().canonical_json())
    parser.add_argument("--decision-log", type=Path)
    return parser


def _search_diagnostics(policy: DeterminizedSearchPolicy) -> SearchDecisionDiagnostics:
    decision = policy.last_decision
    if decision is None:
        return SearchDecisionDiagnostics()
    if decision.unavailable_reason is not None:
        return SearchDecisionDiagnostics(
            attempted=True,
            incomplete_reason="determinization_unavailable",
        )
    if decision.rejected_rollouts:
        return SearchDecisionDiagnostics(
            attempted=True,
            incomplete_reason="rejected_rollout",
        )
    return SearchDecisionDiagnostics(
        attempted=True,
        completed=True,
        changed=decision.selected != decision.baseline,
    )


if __name__ == "__main__":
    main()
