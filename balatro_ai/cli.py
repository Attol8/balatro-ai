"""Small command surface for one game and offline evidence."""

import argparse
import json
import re
import subprocess
from pathlib import Path

from .client import BalatroBotClient
from .runner import DECKS, STAKES, Limits, load_resume, resolve_settings, run_game, saved_settings


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
    play.add_argument("--model", default="gpt-6-astra", help="Codex model for the codex coach")
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
        "--rpc-seconds",
        type=float,
        help="game API timeout; increase for slow rendered recordings (default 60)",
    )
    play.add_argument(
        "--call-seconds",
        type=float,
        default=60,
        help="per-call cap; a timed-out call is retried, not charged as progress",
    )
    keep = sub.add_parser(
        "supervise", help="keep one real game going across runner restarts (uses model calls)"
    )
    keep.add_argument("--output", type=Path, required=True, help="game root holding the segments")
    keep.add_argument("--port", type=int, default=12346)
    keep.add_argument("--endless", action="store_true", help="continue beyond Ante 8")
    keep.add_argument("--seed", help="optional 1–8 alphanumeric characters; withheld from coach")
    keep.add_argument("--model", default=None, help="Codex model (default gpt-6-astra)")
    keep.add_argument("--max-calls", type=int, default=450, help="model calls per segment")
    keep.add_argument("--max-actions", type=int, default=750, help="game actions per segment")
    keep.add_argument("--seconds", type=float, default=7200, help="wall-clock budget per segment")
    keep.add_argument("--call-seconds", type=float, default=60, help="per-call cap")
    keep.add_argument(
        "--max-restarts", type=int, default=8, help="recoverable runner exits to absorb"
    )
    keep.add_argument(
        "--server-command", help="shell command that starts BalatroBot when it is unreachable"
    )
    keep.add_argument(
        "--save-file", type=Path, help="Balatro autosave to load when the game process died"
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
    for command in (play, keep):
        command.add_argument(
            "--deck", type=str.upper, choices=DECKS, help="deck (default RED; inherited on resume)"
        )
        command.add_argument(
            "--stake",
            type=str.upper,
            choices=STAKES,
            help="stake (default WHITE; inherited on resume)",
        )
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
        if args.command == "supervise":
            from .supervise import supervise, validate_seed

            validate_seed(args.seed)
            summary = supervise(
                args.output,
                seed=args.seed,
                deck=args.deck,
                stake=args.stake,
                endless=args.endless,
                port=args.port,
                limits=Limits(args.max_calls, args.max_actions, args.seconds, args.call_seconds),
                max_restarts=args.max_restarts,
                server_command=args.server_command,
                save_file=args.save_file,
                model=args.model,
            )
            print(json.dumps(summary, indent=2))
            return 0 if summary.get("status") in {"won", "lost"} else 1
        rpc_seconds = getattr(args, "rpc_seconds", None)
        if rpc_seconds is not None:
            import math

            if not math.isfinite(rpc_seconds) or rpc_seconds <= 0:
                raise ValueError("--rpc-seconds must be positive and finite")
        client = (
            BalatroBotClient(port=args.port, timeout=rpc_seconds)
            if rpc_seconds is not None
            else BalatroBotClient(port=args.port)
        )
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
        deck, stake = resolve_settings(
            args.deck,
            args.stake,
            saved=saved_settings(args.resume) if args.resume is not None else None,
        )
        limits = Limits(args.max_calls, args.max_actions, args.seconds, args.call_seconds)
        from .coach import CodexCoach, SessionCoach

        if args.coach == "codex":
            coach = CodexCoach() if args.model == "gpt-6-astra" else CodexCoach(model=args.model)
        else:
            coach = SessionCoach(args.output / "public")
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
            deck=deck,
            stake=stake,
            continuation=continuation,
            endless=args.endless,
        )
        print(json.dumps(result, indent=2))
        return 0 if result["status"] in {"won", "lost"} else 1
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"balatro: {exc}\n")
