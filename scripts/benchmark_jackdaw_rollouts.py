#!/usr/bin/env python3
"""Measure evaluator-only Jackdaw clone and public-step costs.

This benchmark intentionally keeps the cloned game state inside this process.
Only aggregate timings and public-state digests are emitted, so its output can
be used to size search without becoming a private-state input path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.actions import PlayCards, iter_legal_actions
from balatro_ai_v2.backend import RunSpec
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.jackdaw import JackdawBackend, JackdawUnavailable, verify_jackdaw_runtime


def main() -> None:
    args = build_parser().parse_args()
    if args.repeats < 1 or args.seed < 0:
        raise SystemExit("--repeats must be positive and --seed must be non-negative")

    source: JackdawBackend | None = None
    try:
        runtime = verify_jackdaw_runtime()
        source = JackdawBackend()
        before, action = _selecting_hand_fixture(source, RunSpec(args.deck, args.stake, str(args.seed)))
        game_state = source._backend._gs
        if game_state is None:
            raise RuntimeError("Jackdaw did not expose an evaluator fixture state")

        clone_times: list[int] = []
        step_times: list[int] = []
        projection_times: list[int] = []
        for _ in range(args.repeats):
            started = time.perf_counter_ns()
            cloned_state = deepcopy(game_state)
            clone_times.append(time.perf_counter_ns() - started)

            clone = JackdawBackend()
            try:
                clone._backend._gs = cloned_state
                clone._current = before
                started = time.perf_counter_ns()
                result = clone.step(action)
                step_times.append(time.perf_counter_ns() - started)
                if result.status != "accepted" or result.after is None:
                    raise RuntimeError(f"fixture action was rejected: {result.error}")
                started = time.perf_counter_ns()
                to_public_observation(json.loads(result.after.observed.raw_json))
                projection_times.append(time.perf_counter_ns() - started)
            finally:
                clone.close()

        payload = {
            "candidate_only": True,
            "runtime": runtime,
            "fixture": {
                "deck": args.deck,
                "stake": args.stake,
                "phase": to_public_observation(json.loads(before.observed.raw_json)).phase.value,
                "action_kind": type(action).__name__,
            },
            "repeats": args.repeats,
            "summary": {
                "clone_ns": _summary(clone_times),
                "step_ns": _summary(step_times),
                "public_projection_ns": _summary(projection_times),
                "clone_plus_step_p50_ns": statistics.median(clone_times)
                + statistics.median(step_times),
                "fixture_public_digest": _digest(before.observed.raw_json),
            },
        }
        encoded = json.dumps(payload, sort_keys=True)
        print(encoded)
        if args.report_json is not None:
            args.report_json.parent.mkdir(parents=True, exist_ok=True)
            with args.report_json.open("x", encoding="utf-8") as handle:
                handle.write(encoded + "\n")
    except JackdawUnavailable as exc:
        raise SystemExit(f"Jackdaw candidate unavailable: {exc}") from exc
    finally:
        if source is not None:
            source.close()


def _selecting_hand_fixture(backend: JackdawBackend, spec: RunSpec):
    before = backend.reset(spec)
    for _ in range(32):
        observation = to_public_observation(json.loads(before.observed.raw_json))
        if observation.phase.value == "SELECTING_HAND":
            action = next(
                (candidate for candidate in iter_legal_actions(observation) if isinstance(candidate, PlayCards)),
                None,
            )
            if action is None:
                raise RuntimeError("fixture has no legal play action")
            return before, action
        action = next(iter(iter_legal_actions(observation)), None)
        if action is None:
            raise RuntimeError("fixture has no legal action")
        result = backend.step(action)
        if result.status != "accepted" or result.after is None:
            raise RuntimeError(f"fixture setup action was rejected: {result.error}")
        before = result.after
    raise RuntimeError("could not reach a selecting-hand fixture")


def _summary(values: list[int]) -> dict[str, float]:
    return {
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "p95": _percentile(values, 0.95),
    }


def _percentile(values: list[int], fraction: float) -> float:
    ordered = sorted(values)
    return float(ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))])


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="WHITE")
    parser.add_argument("--repeats", type=int, default=100)
    parser.add_argument("--report-json", type=Path)
    return parser


if __name__ == "__main__":
    main()
