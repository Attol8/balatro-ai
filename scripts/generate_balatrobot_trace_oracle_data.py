from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.learning.balatrobot_traces import write_balatrobot_trace_oracle_data


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate oracle imitation data from real BalatroBot JSONL traces")
    parser.add_argument("trace_jsonl", type=Path, nargs="+")
    parser.add_argument("--output-jsonl", type=Path, default=Path("runs/balatrobot_trace_oracle.jsonl"))
    parser.add_argument("--strict", action="store_true", help="Fail if the oracle emits an illegal action for a trace state.")
    args = parser.parse_args()

    stats = write_balatrobot_trace_oracle_data(
        args.trace_jsonl,
        args.output_jsonl,
        strict=args.strict,
    )
    print(f"output_jsonl: {args.output_jsonl}")
    print(f"examples: {stats.examples}")
    print(f"skipped: {stats.skipped}")
    print(f"illegal: {stats.illegal}")


if __name__ == "__main__":
    main()
