from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.rules.coverage import build_coverage_report
from balatro_ai_v2.rules import load_rule_catalog


def main() -> None:
    parser = argparse.ArgumentParser(description="Report local fast-simulator coverage of Balatro rule objects")
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--show-missing", action="store_true")
    parser.add_argument("--source-details", action="store_true")
    args = parser.parse_args()

    catalog = load_rule_catalog()
    report = build_coverage_report(catalog)
    for row in report.rows:
        print(f"{row.name}: {row.implemented}/{row.total} ({row.percent:.1f}%)")
        if args.show_missing and row.missing:
            print("  missing:")
            for source in row.missing_sources:
                label = source.name or source.key
                print(f"    {source.key} @ {source.source_location} ({label})")
                if args.source_details:
                    if source.effect:
                        print(f"      effect: {source.effect}")
                    if source.config_hash:
                        print(f"      config_hash: {source.config_hash}")
                    for ref in source.behavior_refs[:3]:
                        print(f"      behavior: {ref.path}:{ref.line} {ref.snippet}")
                    if len(source.behavior_refs) > 3:
                        print(f"      behavior: +{len(source.behavior_refs) - 3} more refs")
            source_keys = {source.key for source in row.missing_sources}
            sourceless = [key for key in row.missing if key not in source_keys]
            if sourceless:
                print(f"    sourceless: {', '.join(sourceless)}")
    print(f"total_rule_objects: {report.implemented}/{report.total} ({report.percent:.1f}%)")
    if args.require_complete and not report.complete:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
