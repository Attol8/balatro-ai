"""JSON-lines child process for public-only baseline policies."""

from __future__ import annotations

import argparse
import sys

from balatro_ai_v2.actions import PublicAction, is_legal, iter_legal_actions
from balatro_ai_v2.baselines import PUBLIC_BASELINE_NAMES, build_public_baseline
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.policy_wire import (
    MAX_REQUEST_BYTES,
    PolicyResponse,
    decode_request,
    encode_response,
)
from balatro_ai_v2.public_state import PublicObservation


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
            response = PolicyResponse(request.request_id, request.observation.digest(), action)
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


if __name__ == "__main__":
    main()
