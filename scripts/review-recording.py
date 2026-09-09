#!/usr/bin/env python3
"""Build a local, synchronized video/trajectory review page from recorded events."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def review(recording: Path, traces: list[Path]) -> Path:
    clock = json.loads((recording / "video-clock.json").read_text())
    anchor = clock["capture_started_at"]
    if (
        isinstance(anchor, bool)
        or not isinstance(anchor, (float, int))
        or not math.isfinite(anchor)
    ):
        raise ValueError("Invalid video clock")
    if not (recording / "gameplay.mp4").is_file():
        raise ValueError("Missing gameplay.mp4")
    events = []
    for trace in traces:
        for number, line in enumerate(trace.read_text().splitlines(), 1):
            if not line.strip():
                continue
            event = json.loads(line)
            stamp = event.get("recorded_at")
            if (
                isinstance(stamp, bool)
                or not isinstance(stamp, (float, int))
                or not math.isfinite(stamp)
            ):
                raise ValueError(
                    f"{trace}:{number}: event has no valid recorded_at timestamp; historical timing cannot be reconstructed"
                )
            events.append(dict(time=stamp - anchor, trace=trace.parent.name, data=event))
    if not events:
        raise ValueError("No trajectory events")
    events.sort(key=lambda event: event["time"])
    # Embedded data must never be interpreted as markup or executable script.
    payload = (
        json.dumps(events, allow_nan=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    template = Path(__file__).with_name("virtual-recording").joinpath("review.html").read_text()
    output = recording / "review.html"
    output.write_text(template.replace("__EVENT_DATA__", payload))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument(
        "--trace",
        type=Path,
        action="append",
        required=True,
        help="Trajectory JSONL; repeat for resumed segments",
    )
    args = parser.parse_args()
    print(review(args.recording, args.trace))


if __name__ == "__main__":
    main()
