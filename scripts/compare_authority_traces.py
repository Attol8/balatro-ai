"""Fail unless two fresh authority traces have the same canonical trajectory."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.differential import compare_authority_traces


def main() -> None:
    args = build_parser().parse_args()
    report = compare_authority_traces(args.first, args.second)
    print(json.dumps(asdict(report), sort_keys=True))
    if not report.observed_lockstep:
        raise SystemExit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare repeated fresh Balatro authority runs")
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    return parser


if __name__ == "__main__":
    main()
