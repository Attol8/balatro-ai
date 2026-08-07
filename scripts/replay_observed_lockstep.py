"""Replay a complete authority trace against a fresh real Balatro run."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.balatrobot.backend import BalatroBotBackend
from balatro_ai_v2.balatrobot.client import BalatroBotClient
from balatro_ai_v2.balatrobot.process import build_launch_command, stop_balatrobot_server, wait_for_balatrobot
from balatro_ai_v2.differential import replay_authority_trace


def main() -> None:
    args = build_parser().parse_args()
    client = BalatroBotClient(host=args.host, port=args.port, timeout=args.timeout)
    process: subprocess.Popen[bytes] | None = None
    try:
        if args.launch_server:
            command = build_launch_command(
                args.launch_command,
                host=args.host,
                port=args.port,
                fast_server=args.fast_server,
                headless_server=args.headless_server,
            )
            process = subprocess.Popen(command)
            wait_for_balatrobot(
                client,
                timeout=args.launch_timeout,
                poll_delay=args.launch_poll_delay,
                process=process,
            )
            if args.post_launch_delay:
                time.sleep(args.post_launch_delay)
        else:
            client.health()

        backend = BalatroBotBackend(
            client,
            max_settle_polls=args.max_settle_polls,
            settle_poll_delay=args.settle_poll_delay,
        )
        report = replay_authority_trace(args.trace, backend)
        print(json.dumps(asdict(report), sort_keys=True))
        if not report.observed_lockstep:
            raise SystemExit(1)
    finally:
        if process is not None:
            stop_balatrobot_server(process)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify exact observed-state reproduction in real Balatro")
    parser.add_argument("trace", type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=12346)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--max-settle-polls", type=int, default=40)
    parser.add_argument("--settle-poll-delay", type=float, default=0.02)
    parser.add_argument("--launch-server", action="store_true")
    parser.add_argument(
        "--launch-command",
        default=os.environ.get("BALATROBOT_LAUNCH_COMMAND", "uvx balatrobot serve"),
    )
    parser.add_argument("--fast-server", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--headless-server", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--launch-timeout", type=float, default=45.0)
    parser.add_argument("--launch-poll-delay", type=float, default=0.2)
    parser.add_argument("--post-launch-delay", type=float, default=1.0)
    return parser


if __name__ == "__main__":
    main()
