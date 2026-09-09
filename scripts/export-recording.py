#!/usr/bin/env python3
"""Export private gameplay and recorded public explanations as a shareable MP4.

Requires Pillow in the invoking Python and the local balatro-virtual-recording
Docker image. The raw capture is never modified; no screen capture is performed.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import subprocess
import tempfile
from pathlib import Path

IMAGE = "balatro-virtual-recording:local"


def finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def load_events(recording, traces):
    anchor = json.loads((recording / "video-clock.json").read_text())["capture_started_at"]
    if not finite(anchor):
        raise ValueError("Invalid capture_started_at")
    events = []
    for trace in traces:
        previous = -math.inf
        for number, line in enumerate(trace.read_text().splitlines(), 1):
            if not line.strip():
                continue
            event = json.loads(line)
            stamp = event.get("recorded_at")
            if not finite(stamp) or stamp < previous:
                raise ValueError(f"{trace}:{number}: invalid or decreasing recorded_at")
            previous = stamp
            events.append(dict(time=stamp - anchor, trace=str(trace.resolve()), data=event))
    if not events:
        raise ValueError("No trajectory events")
    return sorted(events, key=lambda row: row["time"])


def window(events, duration, max_seconds=None):
    if not finite(duration) or duration <= 0:
        raise ValueError("Invalid media duration")
    if max_seconds is not None and (not finite(max_seconds) or max_seconds <= 0):
        raise ValueError("max-seconds must be positive and finite")
    actions = [
        r for r in events if r["data"].get("event") in ("start", "rpc_attempt", "transition")
    ]
    transitions = [r for r in actions if r["data"].get("event") == "transition"]
    if not actions or not transitions:
        raise ValueError("Need a recorded action and transition to identify the game window")
    if any(r["time"] < 0 or r["time"] > duration for r in actions):
        raise ValueError("An action lies outside the video; refusing an incomplete export")
    start = max(0, actions[0]["time"] - 1)
    end = min(duration, max(transitions[-1]["time"], actions[-1]["time"]) + 3)
    speed = max(1.0, (end - start) / max_seconds) if max_seconds else 1.0
    return start, end, speed


def panels(events):
    state = dict(
        status="Waiting for first recorded action",
        action="",
        explanation="",
        plan="No strategy recorded yet.",
        resources="",
    )
    pending = None
    trace = None
    result = []
    for row in events:
        d = row["data"]
        kind = d.get("event")
        if row["trace"] != trace:
            pending = None
            trace = row["trace"]
        if kind in ("coach_request", "coach_rejected", "coach_timeout"):
            pending = None
            if kind == "coach_request" and isinstance(d.get("observation"), dict):
                state["resources"] = resource_label(d["observation"])
                result.append((row["time"], copy.deepcopy(state)))
            if kind != "coach_request":
                state.update(
                    status="Proposal rejected"
                    if kind == "coach_rejected"
                    else "Response timed out",
                    explanation="No action explanation available.",
                )
        if kind == "coach_response":
            response = d.get("response", {})
            try:
                action = json.loads(response.get("action_json", ""))
            except (ValueError, TypeError):
                action = None
            pending = (action, response.get("explanation", "")) if action else None
            if response.get("plan") and response["plan"] != "=":
                state["plan"] = str(response["plan"])
            state.update(
                status="Bot proposal · awaiting validation",
                action=action_label(action),
                explanation=str(response.get("explanation") or "No explanation recorded."),
            )
        elif kind in ("rpc_attempt", "transition", "start"):
            action = d.get("action")
            explanation = (
                pending[1]
                if d.get("source") == "coach" and pending and pending[0] == action
                else ""
            )
            state.update(
                status=("Executed" if kind == "transition" else "Sending action")
                + (f" · {d['source']}" if d.get("source") else ""),
                action=action_label(
                    action or {"type": d.get("method", kind), **d.get("params", {})}
                ),
                explanation=str(explanation or "No per-action explanation recorded."),
            )
            if kind == "transition":
                state["resources"] = resource_label(d.get("after", {}))
                pending = None
        else:
            continue
        result.append((row["time"], copy.deepcopy(state)))
    return result


def action_label(action):
    if not isinstance(action, dict):
        return ""
    kind = str(action.get("type", "action"))
    name = kind.replace("_", " ").capitalize()
    fields = []

    def readable(value):
        if isinstance(value, dict):
            return "; ".join(f"{str(k).replace('_', ' ')}: {readable(v)}" for k, v in value.items())
        if isinstance(value, list):
            return ", ".join(readable(v) for v in value)
        return str(value).replace("_", " ")

    def position(value):
        # Invalid/noninteger fields must not be silently interpreted as slots.
        return (
            str(value + 1)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
            else readable(value)
        )

    slots = {
        "card": "Shop card" if kind == "buy_shop_card" else "Pack card",
        "voucher": "Voucher",
        "pack": "Pack",
        "joker": "Joker",
        "consumable": "Consumable",
    }
    for key, value in action.items():
        if key == "type":
            continue
        if key in ("cards", "targets", "order") and isinstance(value, list):
            if not value:
                continue
            label = {
                "cards": "Card positions",
                "targets": "Target card positions",
                "order": "New order of positions",
            }[key]
            fields.append(f"{label} {', '.join(position(v) for v in value)} (from the left)")
        elif key in slots:
            fields.append(f"{slots[key]} position {position(value)} (from the left)")
        else:
            fields.append(f"{key.replace('_', ' ').capitalize()}: {readable(value)}")
    return name + (" · " + " · ".join(fields) if fields else "")


def resource_label(state):
    parts = [str(state["phase"]).replace("_", " ").title()] if state.get("phase") else []
    for key, label in [("ante", "Ante"), ("money", "$"), ("round_no", "Round")]:
        if key in state:
            parts.append(f"{label} {state[key]}")
    for container in [state, state.get("round", {}), state.get("current_round", {})]:
        if isinstance(container, dict):
            for key, label in [
                ("chips", "Score"),
                ("score", "Score"),
                ("hands_left", "Hands"),
                ("discards_left", "Discards"),
            ]:
                if key in container:
                    parts.append(f"{label} {container[key]}")
    return "  ·  ".join(dict.fromkeys(parts))


def render_panel(path, state, speed):
    from PIL import Image, ImageDraw, ImageFont

    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    font_path = next((p for p in candidates if Path(p).is_file()), None)

    def font(size):
        return (
            ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default(size=size)
        )

    im = Image.new("RGB", (640, 720), "#101a22")
    draw = ImageDraw.Draw(im)
    draw.rectangle((0, 0, 5, 720), fill="#e8b75c")

    def block(text, y, bottom, size=23, color="#eef3f5"):
        # Fit all recorded text rather than silently truncating the explanation.
        for fitted in range(size, 7, -1):
            f = font(fitted)
            lines = []
            for paragraph in str(text).splitlines() or [""]:
                line = ""
                for word in paragraph.split():
                    if draw.textlength((line + " " + word).strip(), font=f) > 568 and line:
                        lines.append(line)
                        line = ""
                    # Long unbroken JSON tokens must also wrap.
                    for char in (" " if line else "") + word:
                        if draw.textlength(line + char, font=f) > 568:
                            lines.append(line)
                            line = ""
                        line += char
                lines.append(line)
            if len(lines) * (fitted + 6) <= bottom - y:
                break
        if len(lines) * (fitted + 6) > bottom - y:
            raise ValueError("Recorded text cannot fit the panel; export requires a larger layout")
        for line in lines:
            draw.text((34, y), line, font=f, fill=color)
            y += fitted + 6

    block("BALATRO  /  BOT PLAY", 25, 58, 25, "#e8b75c")
    block(f"{speed:.3f}× playback · full action chronology", 67, 93, 17, "#a9bbc8")
    block(state["resources"] or "Awaiting recorded game state", 111, 162, 19, "#a9bbc8")
    draw.line((34, 176, 606, 176), fill="#34424c")
    block(state["status"], 192, 225, 20, "#e8b75c")
    block(state["action"], 236, 308, 26)
    block(state["explanation"], 318, 480, 24)
    draw.line((34, 493, 606, 493), fill="#34424c")
    block("RECORDED STRATEGY", 511, 540, 18, "#e8b75c")
    block(state["plan"], 549, 681, 22)
    block("Public bot explanations · recorded alongside gameplay", 694, 719, 14, "#a9bbc8")
    im.save(path)


def docker(recording, work, command):
    return [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--entrypoint",
        command[0],
        "-v",
        f"{recording}:/recording:ro",
        "-v",
        f"{work}:/export",
        IMAGE,
        *command[1:],
    ]


def probe(recording, work, path):
    result = subprocess.run(
        docker(
            recording,
            work,
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        ),
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def export(recording, traces, output, max_seconds=None):
    recording, output = recording.resolve(), output.resolve()
    if not (recording / "gameplay.mp4").is_file():
        raise ValueError("Missing gameplay.mp4")
    if output.exists() or output.suffix.lower() != ".mp4":
        raise ValueError("Output must be a new .mp4 path")
    events = load_events(recording, traces)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".recording-export-", dir=output.parent) as temp:
        work = Path(temp)
        info = probe(recording, work, "/recording/gameplay.mp4")
        video = next(s for s in info["streams"] if s["codec_type"] == "video")
        if (video["width"], video["height"]) != (1280, 720):
            raise ValueError("Expected 1280x720 gameplay capture")
        start, end, speed = window(events, float(info["format"]["duration"]), max_seconds)
        snapshots = panels(events)
        initial = dict(
            status="Waiting for first recorded action",
            action="",
            explanation="",
            plan="No strategy recorded yet.",
            resources="",
        )
        for t, state in snapshots:
            if t <= start:
                initial = state
        segments = [(start, initial)] + [(t, s) for t, s in snapshots if start < t < end]
        concat = []
        for i, (t, state) in enumerate(segments):
            name = f"panel-{i:06d}.png"
            render_panel(work / name, state, speed)
            until = segments[i + 1][0] if i + 1 < len(segments) else end
            concat.extend([f"file '{name}'", f"duration {(until - t) / speed:.9f}"])
        concat.append(f"file 'panel-{len(segments) - 1:06d}.png'")
        (work / "panels.txt").write_text("\n".join(concat) + "\n")
        expected = (end - start) / speed
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-nostdin",
            "-ss",
            str(start),
            "-t",
            str(end - start),
            "-i",
            "/recording/gameplay.mp4",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            "/export/panels.txt",
            "-filter_complex",
            f"[0:v]setpts=(PTS-STARTPTS)/{speed},fps=30,format=yuv420p[game];[1:v]fps=30,format=yuv420p[panel];[game][panel]hstack=inputs=2[v]",
            "-map",
            "[v]",
            "-t",
            str(expected),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "21",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            "/export/video.mp4",
        ]
        subprocess.run(docker(recording, work, command), check=True)
        verified = probe(recording, work, "/export/video.mp4")
        result_video = next(s for s in verified["streams"] if s["codec_type"] == "video")
        if (result_video["width"], result_video["height"]) != (1920, 720) or abs(
            float(verified["format"]["duration"]) - expected
        ) > 0.2:
            raise ValueError("Export verification failed")
        (work / "video.mp4").replace(output)
        metadata = dict(
            source=str(recording / "gameplay.mp4"),
            traces=[str(p.resolve()) for p in traces],
            start_seconds=start,
            end_seconds=end,
            playback_multiplier=speed,
            output_duration=expected,
            panel_count=len(segments),
            probe=verified,
        )
        output.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--trace", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--max-seconds", type=float, help="Uniformly accelerate to fit; never remove actions"
    )
    args = parser.parse_args()
    print(export(args.recording, args.trace, args.output, args.max_seconds))


if __name__ == "__main__":
    main()
