from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.balatrobot.parity import replay_balatrobot_trace
from balatro_ai_v2.rules import load_rule_catalog
from balatro_ai_v2.rules.coverage import build_coverage_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Fail unless a trace and the local simulator satisfy game parity gates")
    parser.add_argument("trace_jsonl", type=Path)
    parser.add_argument("--score-tolerance", type=int, default=0)
    parser.add_argument("--show-missing", action="store_true")
    parser.add_argument("--source-details", action="store_true")
    parser.add_argument(
        "--require-complete",
        action="store_true",
        help="Fail unless every transition is checked with zero mismatches (this is already the default; the flag exists so documented commands are explicit).",
    )
    args = parser.parse_args()

    trace_report = replay_balatrobot_trace(args.trace_jsonl, score_tolerance=args.score_tolerance)
    print("trace:")
    print(f"  run_starts: {trace_report.run_starts}")
    print(f"  run_ends: {trace_report.run_ends}")
    print(f"  transitions: {trace_report.checked_transitions}/{trace_report.transitions}")
    print(f"  checked_scores: {trace_report.checked_scores}")
    print(f"  checked_draws: {trace_report.checked_draws}")
    print(f"  mismatches: {len(trace_report.mismatches)}")
    print(f"  unchecked: {len(trace_report.unchecked)}")
    for mismatch in trace_report.mismatches[:20]:
        print(
            f"  mismatch line={mismatch.line} kind={mismatch.kind} {mismatch.message}; "
            f"expected={mismatch.expected!r} actual={mismatch.actual!r}"
        )
    for unchecked in trace_report.unchecked[:20]:
        print(
            f"  unchecked line={unchecked.line} state={unchecked.state} "
            f"method={unchecked.method} reason={unchecked.reason}"
        )

    coverage_report = build_coverage_report(load_rule_catalog())
    print("rules:")
    for row in coverage_report.rows:
        print(f"  {row.name}: {row.implemented}/{row.total} ({row.percent:.1f}%)")
        if args.show_missing and row.missing:
            print("    missing:")
            for source in row.missing_sources:
                label = source.name or source.key
                print(f"      {source.key} @ {source.source_location} ({label})")
                if args.source_details:
                    if source.effect:
                        print(f"        effect: {source.effect}")
                    if source.config_hash:
                        print(f"        config_hash: {source.config_hash}")
                    for ref in source.behavior_refs[:3]:
                        print(f"        behavior: {ref.path}:{ref.line} {ref.snippet}")
                    if len(source.behavior_refs) > 3:
                        print(f"        behavior: +{len(source.behavior_refs) - 3} more refs")
            source_keys = {source.key for source in row.missing_sources}
            sourceless = [key for key in row.missing if key not in source_keys]
            if sourceless:
                print(f"      sourceless: {', '.join(sourceless)}")
    print(f"  total_rule_objects: {coverage_report.implemented}/{coverage_report.total} ({coverage_report.percent:.1f}%)")

    if not trace_report.complete:
        raise SystemExit(1)
    if not coverage_report.complete:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
