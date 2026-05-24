from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.balatrobot.client import BalatroBotClient, BalatroBotError
from balatro_ai_v2.balatrobot.policy import BalatroBotPolicy
from balatro_ai_v2.balatrobot.policy_config import load_policy_config
from balatro_ai_v2.balatrobot.runner import evaluate_balatrobot
from balatro_ai_v2.balatrobot.tracing import JsonlTraceWriter
from balatro_ai_v2.learning.imitation import load_action_policy


FAST_SERVER_ARGS = (
    "--fast",
    "--no-shaders",
    "--gamespeed",
    "10",
    "--animation-fps",
    "60",
)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    client = BalatroBotClient(host=args.host, port=args.port, timeout=args.timeout)
    server_process: subprocess.Popen[bytes] | None = None
    try:
        if args.launch_server:
            command = build_launch_command(
                args.launch_command,
                host=args.host,
                port=args.port,
                fast_server=args.fast_server,
                headless_server=args.headless_server,
            )
            try:
                server_process = subprocess.Popen(command)
            except OSError as exc:
                raise SystemExit(f"Failed to launch BalatroBot with {command!r}: {exc}") from exc
            wait_for_balatrobot(
                client,
                timeout=args.launch_timeout,
                poll_delay=args.launch_poll_delay,
                process=server_process,
            )
            if args.post_launch_delay > 0:
                time.sleep(args.post_launch_delay)
        else:
            try:
                client.health()
            except BalatroBotError as exc:
                raise SystemExit(f"BalatroBot is not reachable at {client.url}: {exc}") from exc

        seeds = [str(seed) for seed in range(args.seed_start, args.seed_start + args.seeds)]
        tactical_model = load_action_policy(args.imitation_model) if args.imitation_model is not None else None
        full_action_model = load_action_policy(args.full_action_model) if args.full_action_model is not None else None
        policy = BalatroBotPolicy(
            config=load_policy_config(args.policy_config),
            tactical_model=tactical_model,
            full_action_model=full_action_model,
        )
        trace_writer = (
            JsonlTraceWriter(args.trace_jsonl, include_states=not args.trace_compact)
            if args.trace_jsonl is not None
            else None
        )
        metrics = evaluate_balatrobot(
            seeds,
            client=client,
            deck=args.deck,
            stake=args.stake,
            max_steps=args.max_steps,
            trace=args.trace,
            policy=policy,
            trace_writer=trace_writer,
            poll_delay=args.poll_delay,
            retry_delay=args.retry_delay,
        )
        for key, value in metrics.items():
            print(f"{key}: {value}")
    finally:
        if server_process is not None:
            stop_balatrobot_server(server_process)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the red-deck agent through BalatroBot")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=12346)
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="WHITE")
    parser.add_argument("--seed-start", type=int, default=1)
    parser.add_argument("--seeds", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=800)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--poll-delay", type=float, default=0.02)
    parser.add_argument("--retry-delay", type=float, default=0.05)
    parser.add_argument("--trace", action="store_true")
    parser.add_argument("--trace-jsonl", type=Path)
    parser.add_argument("--trace-compact", action="store_true")
    parser.add_argument("--policy-config", type=Path)
    parser.add_argument(
        "--imitation-model",
        type=Path,
        help="Use a trained fast tactical policy for play/discard decisions.",
    )
    parser.add_argument(
        "--full-action-model",
        type=Path,
        help="Use a trained fast full-action policy for all BalatroBot phases.",
    )
    parser.add_argument(
        "--launch-server",
        action="store_true",
        help="Start BalatroBot before running, then stop it after evaluation.",
    )
    parser.add_argument(
        "--launch-command",
        default=os.environ.get("BALATROBOT_LAUNCH_COMMAND", "uvx balatrobot serve"),
        help="Base command used with --launch-server.",
    )
    parser.add_argument(
        "--fast-server",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="When launching BalatroBot, enable fast game settings.",
    )
    parser.add_argument(
        "--headless-server",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="When launching BalatroBot with --fast-server, hide the game window.",
    )
    parser.add_argument("--launch-timeout", type=float, default=45.0)
    parser.add_argument("--launch-poll-delay", type=float, default=0.2)
    parser.add_argument(
        "--post-launch-delay",
        type=float,
        default=1.0,
        help="Extra seconds to wait after health succeeds before sending menu/start RPCs.",
    )
    return parser


def build_launch_command(base_command: str, *, host: str, port: int, fast_server: bool, headless_server: bool = True) -> list[str]:
    command = shlex.split(base_command)
    if not command:
        raise SystemExit("--launch-command cannot be empty")
    command.extend(("--host", host, "--port", str(port)))
    if fast_server:
        if headless_server:
            command.append("--headless")
        command.extend(FAST_SERVER_ARGS)
    return command


def wait_for_balatrobot(
    client: BalatroBotClient,
    *,
    timeout: float,
    poll_delay: float,
    process: subprocess.Popen[bytes] | None = None,
) -> None:
    deadline = time.monotonic() + timeout
    last_error: BalatroBotError | None = None
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise SystemExit(f"BalatroBot exited before becoming reachable at {client.url}")
        try:
            client.health()
            return
        except BalatroBotError as exc:
            last_error = exc
            if poll_delay > 0:
                time.sleep(poll_delay)
    raise SystemExit(f"BalatroBot is not reachable at {client.url}: {last_error}")


def stop_balatrobot_server(process: subprocess.Popen[bytes], *, timeout: float = 5.0) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


if __name__ == "__main__":
    main()
