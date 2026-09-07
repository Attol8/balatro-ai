"""Command line entry point: ``python -m benchmarks``.

Reads the recorded evidence, writes ``results.json`` and ``results.md`` and, when
matplotlib is installed, the three SVG figures.  Extra directories produced by
``balatro play`` can be folded in as additional coached rows with ``--runs``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import DEFAULT_OUTPUT, EVIDENCE_ROOT
from .tables import build_results, write_results


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks",
        description="Build the offline Balatro benchmark tables and figures.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="output directory (default: benchmarks/results)",
    )
    parser.add_argument(
        "--runs",
        type=Path,
        nargs="+",
        action="extend",
        default=[],
        metavar="DIR",
        help="extra 'balatro play' run directories to ingest as coached rows",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=EVIDENCE_ROOT,
        help="evidence root (default: <repo>/evidence)",
    )
    parser.add_argument(
        "--no-figures",
        action="store_true",
        help="skip the SVG figures even when matplotlib is available",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    missing = [str(path) for path in args.runs if not (path / "result.json").is_file()]
    if missing:
        print(f"no result.json in: {', '.join(missing)}", file=sys.stderr)
        return 2
    results = build_results(args.evidence, list(args.runs))
    written = write_results(results, args.out)
    if not args.no_figures:
        try:
            from .figures import render_all
        except ImportError:
            print("matplotlib is not installed; skipping figures", file=sys.stderr)
        else:
            written += render_all(args.out, args.evidence)
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
