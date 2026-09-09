"""Keep one real game going without an operator watching it.

A game is a sequence of runner segments under one root directory. Segment 0
starts a fresh game; every later segment resumes the previous segment's
directory, so the trajectory files chain the way ``balatro play --resume``
already chains them. Between segments the supervisor decides whether the exit
was final (won, lost, budget spent, interrupted, Codex logged out) or
recoverable (runner error, reply timeout, the process killed without writing a
result), and for a recoverable exit it puts the live game back into a playable
state: relaunch the BalatroBot server if it died, and load Balatro's autosave if
the game process died and left the mod sitting at MENU.

Nothing here writes into a segment directory: the runner owns those.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .client import BalatroBotClient
from .runner import Limits, load_resume, resolve_settings, run_game, saved_settings, write_json

DEFAULT_MAX_RESTARTS = 8
# A crashed server or a stalled Codex recovers in seconds, not milliseconds;
# doubling keeps a permanently broken host from spinning.
BACKOFF_START_SECONDS = 2.0
BACKOFF_MAX_SECONDS = 60.0
HEALTH_POLL_SECONDS = 2.0
HEALTH_WAIT_SECONDS = 120.0
# Reasons that mean the operator's budget is spent rather than something broke.
BUDGET_REASONS = ("action_limit", "coach_call_limit", "game time limit reached")
SEED_PATTERN = re.compile(r"[A-Za-z0-9]{1,8}")
SEGMENT_PATTERN = re.compile(r"segment-(\d+)$")


def validate_seed(seed):
    """Accept the same seeds ``balatro play`` accepts, and nothing else."""

    if seed is not None and SEED_PATTERN.fullmatch(seed) is None:
        raise ValueError("seed must be 1–8 ASCII letters or digits")
    return seed


def default_save_file(home=None) -> Path:
    """Where Balatro autosaves the run in progress for profile 1."""

    home = Path.home() if home is None else Path(home)
    if sys.platform == "darwin":
        return home / "Library/Application Support/Balatro/1/save.jkr"
    return home / ".local/share/Balatro/1/save.jkr"


def classify(result) -> tuple[str, str]:
    """Say what a finished segment means: ``(disposition, detail)``.

    Dispositions are ``finished`` (the game is over), ``budget`` (the operator's
    limits are spent), ``interrupted``, ``login`` (Codex needs a human) and
    ``recoverable`` (restart the runner). ``run_game`` only reports ``won`` when
    it is not endless, so a win is always the end of the game.
    """

    if not isinstance(result, dict) or not result.get("status"):
        return "recoverable", "the runner wrote no result"
    status = str(result.get("status"))
    reason = str(result.get("reason") or "")
    lowered = reason.lower()
    if status == "won":
        return "finished", reason or "ante_8_cleared"
    if status == "lost":
        return "finished", reason or "game_over"
    if status == "stopped" and reason == "interrupted":
        return "interrupted", "the run was interrupted"
    # A logged-out Codex fails identically on every restart: never loop on it.
    if "logged in" in lowered or "login" in lowered:
        return "login", reason
    if any(reason.startswith(budget) for budget in BUDGET_REASONS):
        return "budget", reason
    return "recoverable", reason or status


def segment_dirs(root) -> list[Path]:
    """Existing segment directories, oldest first."""

    found = []
    for path in Path(root).glob("segment-*"):
        match = SEGMENT_PATTERN.match(path.name)
        if match and path.is_dir():
            found.append((int(match.group(1)), path))
    return [path for _, path in sorted(found)]


def next_segment_index(root) -> int:
    """The first unused segment number; ``run_game`` refuses an existing directory."""

    indexes = [int(SEGMENT_PATTERN.match(path.name).group(1)) for path in segment_dirs(root)]
    return max(indexes, default=-1) + 1


def resume_source(root) -> Path | None:
    """The newest segment that recorded something to resume from."""

    for directory in reversed(segment_dirs(root)):
        trajectory = directory / "trajectory.jsonl"
        if trajectory.exists() and trajectory.stat().st_size > 0:
            return directory
    return None


def read_result(directory) -> dict | None:
    """The segment's own result, if it managed to write one."""

    path = Path(directory) / "result.json"
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def probe_state(client_factory) -> str | None:
    """The live game state, or ``None`` when BalatroBot cannot be reached."""

    try:
        return str(client_factory().rpc("gamestate").get("state") or "")
    except Exception:
        return None


def spawn_server(command: str, log_path: Path):
    """Start the operator's server command detached, with its output in the run root."""

    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log_path, "a")
    return subprocess.Popen(
        command,
        shell=True,
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def wait_for_health(client_factory, sleep, seconds=HEALTH_WAIT_SECONDS) -> bool:
    """Poll ``health`` until the relaunched server answers or the wait runs out."""

    for _ in range(max(1, int(seconds / HEALTH_POLL_SECONDS))):
        try:
            client_factory().rpc("health")
            return True
        except Exception:
            sleep(HEALTH_POLL_SECONDS)
    return False


def recover_game(
    client_factory, *, server_command, launcher, log_path, save_file, sleep, log, events=None
):
    """Put the live game back where a resume can continue it.

    Returns the live state name, or ``None`` when the server stays unreachable.
    """

    state = probe_state(client_factory)
    if state is None and server_command:
        log(f"relaunching the BalatroBot server: {server_command}")
        launcher(server_command, log_path)
        if wait_for_health(client_factory, sleep):
            log("the BalatroBot server answered health")
        else:
            log(f"the BalatroBot server did not answer health within {HEALTH_WAIT_SECONDS:.0f}s")
        state = probe_state(client_factory)
    # MENU means the game process itself died; Balatro autosaved the run.
    if state == "MENU" and save_file is not None and Path(save_file).exists():
        log(f"restoring the autosaved run from {save_file}")
        try:
            client_factory().rpc("load", {"path": str(save_file)})
        except Exception as exc:
            log(f"the save file could not be loaded: {exc}")
            return state
        state = probe_state(client_factory)
        log(f"the restored game is at {state}")
        if isinstance(events, dict):
            events["restores"] = int(events.get("restores", 0)) + 1
    return state


def default_runner(*, port, seed, endless, limits, model=None, deck=None, stake=None):
    """The real runner: one segment of ``balatro play``, resumed when asked."""

    def runner(directory, resume):
        from .coach import CodexCoach

        client = BalatroBotClient(port=port)
        continuation, run_seed = None, seed
        if resume is not None:
            continuation = load_resume(client, resume)
            run_seed = json.loads((Path(resume) / "manifest.json").read_text()).get("seed")
        return run_game(
            client,
            CodexCoach(model=model) if model else CodexCoach(),
            directory,
            limits=limits,
            seed=run_seed,
            deck=deck,
            stake=stake,
            continuation=continuation,
            endless=endless,
        )

    return runner


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _print_line(message):
    print(f"[{_now()}] {message}", flush=True)


def write_state(root: Path, state: dict, result: dict | None) -> dict:
    """Record the supervisor's own view and mirror the latest segment result."""

    state["updated_at"] = _now()
    write_json(root / "supervisor.json", state)
    summary = dict(
        result or {},
        segments=state["segments"],
        restarts=state["restarts"],
        stop_reason=state.get("stop_reason"),
    )
    write_json(root / "summary.json", summary)
    # `balatro inspect DIR` reads result.json, so the root carries the same view.
    write_json(root / "result.json", summary)
    return summary


def supervise(
    output,
    *,
    seed=None,
    deck=None,
    stake=None,
    endless=False,
    port=12346,
    limits=None,
    max_restarts=DEFAULT_MAX_RESTARTS,
    server_command=None,
    save_file=None,
    model=None,
    runner=None,
    client_factory=None,
    sleep=time.sleep,
    launcher=spawn_server,
    log=None,
):
    """Run one game to its end, restarting the runner around recoverable exits."""

    root = Path(output)
    resume = resume_source(root)
    deck, stake = resolve_settings(
        deck, stake, saved=saved_settings(resume) if resume is not None else None
    )
    root.mkdir(parents=True, exist_ok=True)
    limits = limits or Limits()
    client_factory = client_factory or (lambda: BalatroBotClient(port=port))
    runner = runner or default_runner(
        port=port, seed=seed, endless=endless, limits=limits, model=model, deck=deck, stake=stake
    )
    log = log or _print_line
    log_path = root / "server.log"
    if save_file is None:
        candidate = default_save_file()
        save_file = candidate if candidate.exists() else None
    state = dict(
        root=str(root),
        seed=seed,
        deck=deck,
        stake=stake,
        endless=endless,
        max_restarts=max_restarts,
        started_at=_now(),
        restarts=0,
        restores=0,
        segments=[],
        stopped=False,
        stop_reason=None,
    )
    index = next_segment_index(root)
    restarts = 0
    backoff = BACKOFF_START_SECONDS
    result = None
    stop_reason = None
    try:
        resume = resume_source(root)
        if resume is None:
            # A fresh game needs an idle table; the runner would refuse anything else.
            live = probe_state(client_factory)
            if live is None and server_command:
                log(f"relaunching the BalatroBot server: {server_command}")
                launcher(server_command, log_path)
                wait_for_health(client_factory, sleep)
                live = probe_state(client_factory)
            if live != "MENU":
                stop_reason = f"a new game needs the live game idle at MENU, found {live}"
        else:
            # Continuing a game a previous supervisor left behind.
            live = recover_game(
                client_factory,
                server_command=server_command,
                launcher=launcher,
                log_path=log_path,
                save_file=save_file,
                sleep=sleep,
                log=log,
                events=state,
            )
            stop_reason = _unplayable(live)
        while stop_reason is None:
            directory = root / f"segment-{index:02d}"
            started = _now()
            log(
                f"segment {directory.name} started"
                + (f", resuming {resume.name}" if resume else ", new game")
            )
            failure = None
            try:
                result = runner(directory, resume)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                failure = f"the runner raised {type(exc).__name__}: {exc}"
                log(failure)
                result = None
            if not isinstance(result, dict):
                # The process died without its finally block; the next resume
                # reconstructs the counters from the trajectory it left behind.
                result = read_result(directory) or dict(
                    status="error", reason=failure or "the runner wrote no result"
                )
            disposition, detail = classify(result)
            state["segments"].append(
                dict(
                    index=index,
                    directory=directory.name,
                    resumed_from=resume.name if resume else None,
                    started_at=started,
                    ended_at=_now(),
                    status=result.get("status"),
                    reason=result.get("reason"),
                    disposition=disposition,
                )
            )
            state["restarts"] = restarts
            write_state(root, state, result)
            log(
                f"segment {directory.name} ended: status {result.get('status')},"
                f" reason {result.get('reason')}"
            )
            if disposition == "finished":
                stop_reason = f"the game finished: {detail}"
            elif disposition == "budget":
                stop_reason = f"the run budget is spent: {detail}"
            elif disposition == "interrupted":
                stop_reason = "the runner was interrupted"
            elif disposition == "login":
                stop_reason = f"Codex needs a human to log in again: {detail}"
            elif restarts >= max_restarts:
                stop_reason = f"the restart limit of {max_restarts} is used up: {detail}"
            if stop_reason is not None:
                break
            restarts += 1
            state["restarts"] = restarts
            log(f"recoverable exit ({detail}); restart {restarts}/{max_restarts} in {backoff:.0f}s")
            sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_MAX_SECONDS)
            live = recover_game(
                client_factory,
                server_command=server_command,
                launcher=launcher,
                log_path=log_path,
                save_file=save_file,
                sleep=sleep,
                log=log,
                events=state,
            )
            stop_reason = _unplayable(live)
            index += 1
            resume = resume_source(root)
    except KeyboardInterrupt:
        stop_reason = "the supervisor was interrupted; the live game is untouched"
    state["stopped"] = True
    state["stop_reason"] = stop_reason
    state["restarts"] = restarts
    log(f"stopping: {stop_reason}")
    return write_state(root, state, result)


def _unplayable(live) -> str | None:
    """Why the live game cannot carry the next segment, or ``None`` if it can."""

    if live is None:
        return "the BalatroBot server is unreachable"
    if live == "MENU":
        return "the live game is at MENU and no save file could restore it"
    if live == "GAME_OVER":
        return "the game ended while the supervisor was away"
    return None
