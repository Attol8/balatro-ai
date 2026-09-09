"""Bounded single-decision coach checks; never connects to a game."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from importlib.resources import files
from pathlib import Path

from .analysis import analyze
from .coach import CodexCoach
from .game.actions import action_to_data, canonical_action_from_data, is_legal
from .game.codec import public_observation_from_data, public_observation_to_data
from .runner import validate_response, write_json


def run_probes(cases_path, output, *, max_calls=0, call_seconds=60, coach=None):
    """Prepare all cases; optionally ask at most eight isolated decisions, once each.

    Oracles and rationales are evaluation metadata and never enter coach packets.
    A pass checks the first action only; follow-ups are recorded but never executed.
    """
    if not 0 <= max_calls <= 8:
        raise ValueError("max_calls must be between 0 and 8")
    if not 0 < call_seconds <= 120:
        raise ValueError("call_seconds must be in (0, 120]")
    source = Path(cases_path).read_bytes()
    cases = json.loads(source)
    if not isinstance(cases, list) or not 1 <= len(cases) <= 32:
        raise ValueError("expected 1–32 cases")
    if max_calls > len(cases):
        raise ValueError("max_calls exceeds the number of cases")
    instructions = files("balatro_ai").joinpath("prompts/coach.md").read_text()
    prepared = []
    ids = set()
    for case in cases:
        case_id = case["id"]
        if not isinstance(case_id, str) or case_id in ids:
            raise ValueError("case IDs must be unique strings")
        ids.add(case_id)
        observation = public_observation_from_data(case["observation"])
        accepted = case["accepted_actions"]
        if not accepted or any(
            not is_legal(observation, canonical_action_from_data(action)) for action in accepted
        ):
            raise ValueError(f"{case_id}: oracle must contain legal actions")
        if case["objective"] not in {"ante8", "endless"}:
            raise ValueError("unknown probe objective")
        prompt = instructions
        if case["objective"] == "endless":
            prompt = prompt.replace(
                "Your objective is to clear Ante 8.",
                "Your objective is to survive as far as possible in endless mode, beyond Ante 8. "
                "Seek enough multiplicative scaling for rising targets; clearing Ante 8 is a milestone, not the stopping point.",
            )
        packet = dict(
            request_id=f"{len(prepared):08x}",
            instructions=prompt,
            plan="",
            validation_feedback=None,
            observation=public_observation_to_data(observation),
            analysis=analyze(observation),
            recent_outcomes=[],
        )
        prepared.append((case, observation, packet))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    summary = dict(
        kind="isolated_decision_probes",
        cases_sha256=hashlib.sha256(source).hexdigest(),
        instructions_sha256=hashlib.sha256(instructions.encode()).hexdigest(),
        model=getattr(coach, "model", None),
        reasoning_effort=getattr(coach, "reasoning_effort", None),
        max_calls=max_calls,
        call_seconds=call_seconds,
        calls=0,
        passed=0,
        failed=0,
        prepared=len(cases),
        results=[],
        limitations="Constructed/local decisions; first action only; no game execution or win-rate evidence.",
    )
    write_json(output / "cases.json", cases)
    write_json(output / "packets.json", [p for _, _, p in prepared])
    write_json(output / "result.json", summary)
    if max_calls and coach is None:
        raise ValueError("a coach is required for model calls")
    for case, observation, packet in prepared[:max_calls]:
        row = dict(id=case["id"], status="error")
        started = time.monotonic()
        summary["calls"] += 1
        try:
            response = coach.choose(packet, timeout=call_seconds)
            row["response"] = response
            action, _, followups = validate_response(response, packet["request_id"], observation)
            actual = action_to_data(action)
            row.update(action=actual, followups_not_executed=len(followups))
            row["status"] = "passed" if actual in case["accepted_actions"] else "failed"
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        row["seconds"] = round(time.monotonic() - started, 3)
        summary["passed" if row["status"] == "passed" else "failed"] += 1
        summary["results"].append(row)
        write_json(output / "result.json", summary)
        print(f"{case['id']}: {row['status']}", flush=True)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cases", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-calls", type=int, default=0, help="0 prepares offline; maximum 8")
    parser.add_argument("--call-seconds", type=float, default=60)
    parser.add_argument("--model", default="gpt-6-astra")
    args = parser.parse_args(argv)
    coach = CodexCoach(model=args.model) if args.max_calls else None
    if coach:
        # One actual inference attempt per case: no speculative hedge or retry.
        coach.allow_second_attempt = False
    try:
        summary = run_probes(
            args.cases,
            args.output,
            max_calls=args.max_calls,
            call_seconds=args.call_seconds,
            coach=coach,
        )
        print(json.dumps(summary, indent=2))
        return 1 if summary["failed"] else 0
    finally:
        if coach:
            coach.close()


if __name__ == "__main__":
    raise SystemExit(main())
