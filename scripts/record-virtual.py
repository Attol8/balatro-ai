#!/usr/bin/env python3
"""Record Balatro in a private Docker display; never capture the host desktop."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import time
import uuid
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

IMAGE = "balatro-virtual-recording:local"
LABEL = "balatro-ai.virtual-recording"
CONTEXT = Path(__file__).resolve().parent / "virtual-recording"


def docker(*args: str, capture: bool = False) -> str:
    result = subprocess.run(
        ["docker", *args], check=True, text=True, stdout=subprocess.PIPE if capture else None
    )
    return result.stdout.strip() if capture else ""


def inspect(container: str) -> dict:
    return json.loads(docker("inspect", container, capture=True))[0]


def save(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n")


def start(args: argparse.Namespace) -> None:
    game = args.game.expanduser().resolve(strict=True)
    mods = args.mods.expanduser().resolve(strict=True)
    if not game.is_file() or not all((mods / name).is_dir() for name in ("smods", "BalatroBot")):
        raise ValueError(
            "Provide a Balatro.love file and a Mods directory containing smods/BalatroBot"
        )
    if any("," in str(path) for path in (game, mods, args.output.resolve())):
        raise ValueError("Docker mount paths must not contain commas")
    docker("image", "inspect", IMAGE, capture=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    name = "balatro-record-" + uuid.uuid4().hex[:12]
    command = [
        "run",
        "--detach",
        "--name",
        name,
        "--init",
        "--label",
        LABEL + "=true",
        "--cpus",
        "2",
        "--memory",
        "2g",
        "--shm-size",
        "256m",
        "--publish",
        f"127.0.0.1:{args.port}:12346",
        "--env",
        f"RECORD_SECONDS={args.seconds}",
        "--mount",
        f"type=bind,source={game},target=/game/Balatro.love,readonly",
        "--mount",
        f"type=bind,source={mods / 'smods'},target=/mods/smods,readonly",
        "--mount",
        f"type=bind,source={mods / 'BalatroBot'},target=/mods/BalatroBot,readonly",
        "--mount",
        f"type=bind,source={output},target=/recording",
        IMAGE,
    ]
    container = docker(*command, capture=True)
    manifest = {
        "container": container,
        "name": name,
        "image": IMAGE,
        "port": args.port,
        "record_seconds": args.seconds,
        "game": str(game),
        "mods": str(mods),
        "host_display_capture": False,
        "status": "starting",
    }
    save(output / "recording.json", manifest)
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            state = inspect(container)
            if not state["State"]["Running"]:
                raise RuntimeError("Container exited; inspect game.log and container.log")
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "health"}).encode()
            request = Request(
                f"http://127.0.0.1:{args.port}",
                data=body,
                headers={"Content-Type": "application/json"},
            )
            try:
                with urlopen(request, timeout=2) as response:
                    health = json.load(response)
                if "result" in health:
                    save(output / "health.json", health)
                    manifest.update(status="recording", image_id=state["Image"])
                    save(output / "recording.json", manifest)
                    print(f"Recording privately to {output / 'gameplay.mp4'}")
                    print(f"Bot API: 127.0.0.1:{args.port}; automatic stop after {args.seconds}s")
                    return
            except (URLError, OSError, ValueError):
                pass
            time.sleep(1)
        raise RuntimeError("Bot API did not become ready within 90 seconds")
    except BaseException:
        docker("stop", "--time", "30", container)
        (output / "container.log").write_text(docker("logs", container, capture=True))
        manifest["status"] = "failed"
        save(output / "recording.json", manifest)
        raise


def stop(args: argparse.Namespace) -> None:
    output = args.output.resolve()
    manifest = json.loads((output / "recording.json").read_text())
    container = manifest["container"]
    state = inspect(container)
    if state["Config"]["Labels"].get(LABEL) != "true":
        raise ValueError("Refusing to stop a container without this recorder's label")
    if state["State"]["Running"]:
        docker("stop", "--time", "30", container)
    state = inspect(container)
    (output / "container.log").write_text(docker("logs", container, capture=True))
    manifest.update(status="stopped", exit_code=state["State"]["ExitCode"])
    save(output / "recording.json", manifest)
    print(f"Stopped; recording and isolated container saves retained in {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="Build Linux runtime; does not launch the game")
    launch = sub.add_parser("start", help="Start private rendering and recording, without bot play")
    launch.add_argument("output", type=Path, help="New output directory")
    launch.add_argument(
        "--game",
        type=Path,
        default=Path.home()
        / (
            "Library/Application Support/Steam/steamapps/common/Balatro/"
            "Balatro.app/Contents/Resources/Balatro.love"
        ),
    )
    launch.add_argument(
        "--mods", type=Path, default=Path.home() / "Library/Application Support/Balatro/Mods"
    )
    launch.add_argument("--port", type=int, default=12347)
    launch.add_argument("--seconds", type=int, default=3600)
    shutdown = sub.add_parser(
        "stop", help="Finalize video and stop this output directory's container"
    )
    shutdown.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        docker("build", "--tag", IMAGE, str(CONTEXT))
    elif args.command == "start":
        if not 1 <= args.port <= 65535 or not 10 <= args.seconds <= 43200:
            parser.error("port must be 1–65535; seconds must be 10–43200")
        start(args)
    else:
        stop(args)


if __name__ == "__main__":
    main()
