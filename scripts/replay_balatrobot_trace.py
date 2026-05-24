from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.balatrobot.parity import replay_balatrobot_trace


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay a clean BalatroBot JSONL trace through fast parity checks")
    parser.add_argument("trace_jsonl", type=Path)
    parser.add_argument("--score-tolerance", type=int, default=0)
    parser.add_argument("--max-mismatches", type=int, default=20)
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()

    report = replay_balatrobot_trace(args.trace_jsonl, score_tolerance=args.score_tolerance)
    print(f"run_starts: {report.run_starts}")
    print(f"run_ends: {report.run_ends}")
    print(f"transitions: {report.transitions}")
    print(f"checked_transitions: {report.checked_transitions}")
    print(f"checked_scores: {report.checked_scores}")
    print(f"checked_draws: {report.checked_draws}")
    print(f"skipped: {report.skipped}")
    print(f"mismatches: {len(report.mismatches)}")
    print(f"unchecked: {len(report.unchecked)}")
    for mismatch in report.mismatches[: args.max_mismatches]:
        print(
            f"line={mismatch.line} kind={mismatch.kind} {mismatch.message}; "
            f"expected={mismatch.expected!r} actual={mismatch.actual!r}"
        )
    for unchecked in report.unchecked[: args.max_mismatches]:
        print(
            f"line={unchecked.line} unchecked state={unchecked.state} "
            f"method={unchecked.method} reason={unchecked.reason}"
        )
    if not report.passed:
        raise SystemExit(1)
    if args.require_complete and not report.complete:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
