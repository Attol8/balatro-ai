"""Small command surface for one game and offline evidence."""

import argparse
import json
import re
import subprocess
from pathlib import Path

from .client import BalatroBotClient
from .runner import Limits, load_resume, run_game


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="balatro", description="Balatro: Astra low + public numerical tools"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="read-only game and Codex readiness")
    doctor.add_argument("--port", type=int, default=12346)
    play = sub.add_parser("play", help="start one real game (uses model calls)")
    play.add_argument("--output", type=Path, required=True)
    play.add_argument("--coach", choices=["codex", "session"], default="codex")
    play.add_argument("--port", type=int, default=12346)
    play.add_argument(
        "--endless", action="store_true", help="continue beyond Ante 8 until loss or run limits"
    )
    play.add_argument("--seed", help="optional 1–8 alphanumeric characters; withheld from coach")
    play.add_argument(
        "--resume", type=Path, help="continue the paused game recorded in a run directory"
    )
    play.add_argument(
        "--max-calls",
        type=int,
        default=450,
        help="model calls before the run stops; the limits bound work, not price",
    )
    play.add_argument(
        "--max-actions", type=int, default=750, help="game actions before the run stops"
    )
    play.add_argument("--seconds", type=float, default=7200, help="wall-clock budget for the run")
    play.add_argument(
        "--call-seconds",
        type=float,
        default=60,
        help="per-call cap; a timed-out call is retried, not charged as progress",
    )
    inspect = sub.add_parser("inspect", help="read a result without running anything")
    inspect.add_argument("run", type=Path)
    watch = sub.add_parser("watch", help="live dashboard for a run directory (no model calls)")
    watch.add_argument("run", type=Path, help="run directory that balatro play is writing")
    watch.add_argument(
        "--host", default="127.0.0.1", help="interface to bind; local only by default"
    )
    watch.add_argument("--port", type=int, default=8765, help="port the dashboard listens on")
    next_cmd = sub.add_parser("next", help="read the outstanding public session request")
    next_cmd.add_argument("public", type=Path)
    reply = sub.add_parser("reply", help="submit a response JSON file to a session")
    reply.add_argument("public", type=Path)
    reply.add_argument("response", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            print((args.run / "result.json").read_text())
            return 0
        if args.command == "watch":
            from .watch import serve

            return serve(args.run, args.host, args.port)
        if args.command in {"next", "reply"}:
            from .coach import read_request, write_response

            if args.command == "next":
                print(json.dumps(read_request(args.public), indent=2))
            else:
                write_response(args.public, json.loads(args.response.read_text()))
            return 0
        client = BalatroBotClient(port=args.port)
        if args.command == "doctor":
            checks = {}
            for name, command in (
                ("codex_version", ["codex", "--version"]),
                ("codex_auth", ["codex", "login", "status"]),
            ):
                try:
                    p = subprocess.run(command, capture_output=True, text=True, timeout=10)
                    checks[name] = dict(ok=p.returncode == 0, detail=(p.stdout + p.stderr).strip())
                except (OSError, subprocess.TimeoutExpired) as exc:
                    checks[name] = dict(ok=False, detail=str(exc))
            try:
                health, state = client.rpc("health"), client.rpc("gamestate")
                checks["game"] = dict(
                    ok=health.get("profile_mode") == "all_unlocked"
                    and state.get("state") == "MENU",
                    profile=health.get("profile_mode"),
                    state=state.get("state"),
                )
            except Exception as exc:
                checks["game"] = dict(ok=False, detail=str(exc))
            auth = checks["codex_auth"]
            auth["ok"] = auth["ok"] and "chatgpt" in auth["detail"].lower()
            print(json.dumps(checks, indent=2))
            return 0 if all(c["ok"] for c in checks.values()) else 1
        if args.resume is not None and args.seed is not None:
            raise ValueError("--resume takes its seed from the resumed run; drop --seed")
        if args.seed is not None and re.fullmatch(r"[A-Za-z0-9]{1,8}", args.seed) is None:
            raise ValueError("seed must be 1–8 ASCII letters or digits")
        limits = Limits(args.max_calls, args.max_actions, args.seconds, args.call_seconds)
        from .coach import CodexCoach, SessionCoach

        coach = CodexCoach() if args.coach == "codex" else SessionCoach(args.output / "public")
        continuation, seed = None, args.seed
        if args.resume is not None:
            continuation = load_resume(client, args.resume)
            seed = json.loads((args.resume / "manifest.json").read_text()).get("seed")
        result = run_game(
            client,
            coach,
            args.output,
            limits=limits,
            seed=seed,
            continuation=continuation,
            endless=args.endless,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["status"] in {"won", "lost"} else 1
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"balatro: {exc}\n")
