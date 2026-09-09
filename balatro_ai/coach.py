"""Bounded model and session-file transports for public coach packets."""

from __future__ import annotations

import json
import math
import os
import queue
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from .packet import compact_packet

_MAX_REQUEST_BYTES = 1_000_000
_MAX_RESPONSE_BYTES = 65_536
_POLL_INTERVAL = 0.05
_DISABLED_FEATURES = (
    "shell_tool",
    "unified_exec",
    "apps",
    "plugins",
    "multi_agent",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "in_app_browser",
    "computer_use",
    "tool_suggest",
    "unbounded_connection_retries",
    "image_generation",
    "memories",
    "hooks",
    "skill_search",
    "view_image",
)
# Strict structured output requires every property in "required" and expresses
# an optional field as a nullable type; bounds (six entries, repeat 1-6) are
# enforced by the runner, which keeps this schema free of unsupported keywords.
_FOLLOWUP_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "action_json": {"type": "string"},
        "repeat": {"type": ["integer", "null"]},
        "until": {
            "type": ["object", "null"],
            "properties": {
                "shop_has_any": {"type": ["array", "null"], "items": {"type": "string"}},
                "money_at_least": {"type": ["integer", "null"]},
            },
            "required": ["shop_has_any", "money_at_least"],
            "additionalProperties": False,
        },
    },
    "required": ["action_json", "repeat", "until"],
    "additionalProperties": False,
}
_RESPONSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "request_id": {"type": "string"},
        "action_json": {"type": "string"},
        "plan": {"type": "string"},
        "explanation": {"type": ["string", "null"]},
        "then": {"type": ["array", "null"], "items": _FOLLOWUP_SCHEMA},
    },
    "required": ["request_id", "action_json", "plan", "explanation", "then"],
    "additionalProperties": False,
}


class CodexCoach:
    """Make one ephemeral Astra-low Codex CLI call per packet."""

    model = "gpt-6-astra"
    reasoning_effort = "low"

    # A second identical process starts if the first has not answered by then; the
    # first valid answer wins. Live calls take ~9 s; service stalls take minutes.
    hedge_after_seconds = 20.0
    allow_second_attempt = True

    def __init__(self, codex_executable: str = "codex", model: str | None = None) -> None:
        self.codex_executable = codex_executable
        if model:
            self.model = model
        self._preflight_complete = False
        self._workspace = None

    def close(self):
        """Remove the isolated workspace when the run ends."""
        if self._workspace is not None:
            sync_codex_home(Path(self._workspace.name))
            self._workspace.cleanup()
            self._workspace = None

    def _codex_home(self) -> Path | None:
        if self._workspace is None:
            self._workspace = tempfile.TemporaryDirectory(prefix="balatro-coach-")
        return prepare_codex_home(Path(self._workspace.name))

    def preflight(self, timeout: float) -> None:
        """Require installed Codex authentication through ChatGPT, without inference."""

        if self._preflight_complete:
            return
        executable = shutil.which(self.codex_executable)
        if executable is None:
            raise RuntimeError(f"Codex CLI is unavailable: {self.codex_executable}")
        with tempfile.TemporaryDirectory(prefix="balatro-coach-auth-") as directory:
            workdir = Path(directory)
            output_path = workdir / "login-status.txt"
            _run_process(
                [executable, "login", "status"],
                cwd=workdir,
                environment=_sanitized_environment(self._codex_home()),
                timeout=_remaining(_deadline(timeout)),
                captured_output=output_path,
            )
            output = _read_bounded(output_path, _MAX_RESPONSE_BYTES).decode(
                "utf-8", errors="replace"
            )
        if "Logged in using ChatGPT" not in output:
            raise RuntimeError("Codex CLI must be logged in using ChatGPT")
        self._preflight_complete = True

    def choose(self, packet: dict[str, object], timeout: float) -> dict[str, object]:
        deadline = _deadline(timeout)
        prepare_started = time.monotonic()
        prompt = _encode_bounded(compact_packet(packet))
        self.last_request_bytes = len(prompt)
        self.last_timings = {"packet_seconds": time.monotonic() - prepare_started}
        executable = shutil.which(self.codex_executable)
        if executable is None:
            raise RuntimeError(f"Codex CLI is unavailable: {self.codex_executable}")
        environment = _sanitized_environment(self._codex_home())

        if not self._preflight_complete:
            self.preflight(_remaining(deadline))

        if self._workspace is None:
            self._workspace = tempfile.TemporaryDirectory(prefix="balatro-coach-")
        workdir = Path(self._workspace.name)
        try:
            schema_path = workdir / "response.schema.json"
            for stale in workdir.glob("response.*.json"):
                stale.unlink(missing_ok=True)
            schema_path.write_text(
                json.dumps(_RESPONSE_SCHEMA, separators=(",", ":")),
                encoding="utf-8",
            )
            # --output-last-message and the trailing "-" are appended per attempt.
            command = [
                executable,
                "exec",
                "--ignore-user-config",
                "--ignore-rules",
                "--ephemeral",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--output-schema",
                str(schema_path),
                "-m",
                self.model,
                "-c",
                f'model_reasoning_effort="{self.reasoning_effort}"',
                "-c",
                'model_provider="openai"',
                "-c",
                'forced_login_method="chatgpt"',
                "-c",
                'web_search="disabled"',
            ]
            for feature in _DISABLED_FEATURES:
                command.extend(("--disable", feature))
            execution_started = time.monotonic()
            response, hedged, winner = _run_hedged(
                command,
                cwd=workdir,
                environment=environment,
                deadline=deadline,
                stdin=prompt,
                hedge_after=self.hedge_after_seconds,
                allow_second_attempt=self.allow_second_attempt,
            )
            self.last_timings["codex_seconds"] = time.monotonic() - execution_started
            self.last_timings["hedged"] = hedged
            self.last_timings["winner"] = winner
            return response

        except BaseException:
            self.close()
            raise
        finally:
            for stale in workdir.glob("response.*.json"):
                stale.unlink(missing_ok=True)


class SessionCoach:
    """Exchange one public packet through atomic JSON files."""

    def __init__(self, public_dir: Path) -> None:
        self.public_dir = Path(public_dir)

    def choose(self, packet: dict[str, object], timeout: float) -> dict[str, object]:
        deadline = _deadline(timeout)
        encoded = _encode_bounded(packet)
        self.public_dir.mkdir(parents=True, exist_ok=True)
        response_path = self.public_dir / "response.json"
        if response_path.exists():
            raise RuntimeError("a stale session response is already pending")
        _atomic_write(self.public_dir / "request.json", encoded)
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("timed out waiting for session response")
                try:
                    response = _read_json_object(response_path)
                except FileNotFoundError:
                    time.sleep(min(_POLL_INTERVAL, remaining))
                    continue
                response_path.unlink()
                return response
        finally:
            # A late reply is deliberately rejected rather than reused by a
            # future request. A stopped run is never automatically resumed.
            _remove_matching_request(self.public_dir, packet)


def read_request(public_dir: Path) -> dict[str, object]:
    """Read the current public session request for ``balatro next``."""

    return _read_json_object(Path(public_dir) / "request.json", limit=_MAX_REQUEST_BYTES)


def write_response(public_dir: Path, response: dict[str, object]) -> None:
    """Atomically publish a raw session response for ``balatro reply``."""

    directory = Path(public_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "response.json"
    if target.exists():
        raise RuntimeError("a session response is already pending")
    request = read_request(directory)
    if response.get("request_id") != request.get("request_id"):
        raise ValueError("response request_id does not match the outstanding request")
    _atomic_write(target, _encode_bounded(response, limit=_MAX_RESPONSE_BYTES))


def _run_hedged(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    deadline: float,
    stdin: bytes,
    hedge_after: float,
    allow_second_attempt: bool = True,
) -> tuple[dict[str, object], bool, int]:
    """Run one Codex call, starting a second identical process if the first stalls.

    The first process that exits cleanly with a valid JSON reply wins and the other
    is killed. Both processes receive byte-identical input, so either reply is a
    valid answer to the same request. Nothing here touches the game.
    """

    finished: queue.Queue[tuple[int, int | None, BaseException | None]] = queue.Queue()
    processes: list[subprocess.Popen[bytes]] = []
    outputs: list[Path] = []
    logs: list[Path] = []
    handles: list[Any] = []

    def start(index: int) -> None:
        output_path = cwd / f"response.{index}.json"
        log_path = cwd / f"codex-output.{index}.log"
        output_path.unlink(missing_ok=True)
        handle = log_path.open("wb")
        handles.append(handle)
        process = subprocess.Popen(
            [*command, "--output-last-message", str(output_path), "-"],
            cwd=cwd,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        processes.append(process)
        outputs.append(output_path)
        logs.append(log_path)

        def wait() -> None:
            try:
                process.communicate(stdin)
                finished.put((index, process.returncode, None))
            except BaseException as exc:  # noqa: BLE001 - reported to the caller
                finished.put((index, None, exc))

        threading.Thread(target=wait, name=f"codex-attempt-{index}", daemon=True).start()

    def kill_all() -> None:
        for process in processes:
            _kill_process_group(process)
        for handle in handles:
            handle.close()

    try:
        start(0)
        hedged = False
        failures: list[str] = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Codex CLI timed out; codex output tail: {_tail(logs[0])}")
            wait_for = (
                remaining if hedged or not allow_second_attempt else min(remaining, hedge_after)
            )
            try:
                index, return_code, error = finished.get(timeout=max(0.0, wait_for))
            except queue.Empty:
                if allow_second_attempt and not hedged and deadline - time.monotonic() > 0:
                    hedged = True
                    start(1)
                continue
            if error is None and return_code == 0:
                try:
                    return _read_json_object(outputs[index]), hedged, index
                except (OSError, ValueError) as exc:
                    failures.append(f"attempt {index}: invalid reply: {exc}")
            else:
                failures.append(
                    f"attempt {index}: {error if error is not None else f'status {return_code}'}"
                )
            live = [p for p in processes if p.poll() is None]
            if not live:
                if allow_second_attempt and not hedged and deadline - time.monotonic() > 0:
                    # The only process failed outright; one more try is cheaper than
                    # surfacing a transport blip as a rejected decision.
                    hedged = True
                    start(1)
                    continue
                raise RuntimeError("Codex CLI failed: " + "; ".join(failures))
    finally:
        kill_all()


def _tail(path: Path, limit: int = 1500) -> str:
    """Return the last characters of a captured child log, or a placeholder."""

    try:
        data = path.read_bytes()
    except OSError:
        return "(no output captured)"
    text = data[-limit:].decode("utf-8", errors="replace").strip()
    return " ".join(text.split()) or "(empty output)"


def _run_process(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout: float,
    stdin: bytes | None = None,
    captured_output: Path | None = None,
) -> None:
    output_stream = captured_output.open("wb") if captured_output is not None else None
    try:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=environment,
            stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
            stdout=output_stream if output_stream is not None else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if output_stream is not None else subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            return_code = _communicate(process, stdin, timeout)
        except BaseException:
            _kill_process_group(process)
            raise
    finally:
        if output_stream is not None:
            output_stream.close()
    if return_code != 0:
        raise RuntimeError(f"Codex CLI exited with status {return_code}")


def _communicate(process: subprocess.Popen[bytes], stdin: bytes, timeout: float) -> int:
    try:
        process.communicate(stdin, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _kill_process_group(process)
        raise TimeoutError("Codex CLI timed out") from exc
    return process.returncode


def _kill_process_group(process: subprocess.Popen[Any]) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait()


def _sanitized_environment(codex_home: Path | None = None) -> dict[str, str]:
    environment = {key: value for key, value in os.environ.items() if "API_KEY" not in key.upper()}
    # Surface the CLI's own warnings (retries, rate limits) in the captured log tail.
    environment.setdefault("RUST_LOG", "warn")
    if codex_home is not None:
        environment["CODEX_HOME"] = str(codex_home)
    return environment


def _default_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def prepare_codex_home(workdir: Path) -> Path | None:
    """Give the Codex child a private home holding only the login file.

    The user's real Codex home can hold gigabytes of session history that the CLI
    scans at startup (logged as "state db discrepancy ... falling_back"). The child
    gets an empty home with `auth.json` linked to the real file, so the login is
    shared and nothing else is. Returns None when no login file exists, in which
    case the default home is used unchanged.
    """

    source = _default_codex_home() / "auth.json"
    if not source.exists():
        return None
    home = workdir / "codex-home"
    home.mkdir(parents=True, exist_ok=True)
    link = home / "auth.json"
    if link.is_symlink():
        return home
    if link.exists():
        # A token refresh replaced the link with a real file: keep the real home current.
        shutil.copyfile(link, source)
        link.unlink()
    link.symlink_to(source)
    return home


def sync_codex_home(workdir: Path) -> None:
    """Copy a refreshed login back to the real home before the workspace is removed."""

    link = workdir / "codex-home" / "auth.json"
    if link.exists() and not link.is_symlink():
        shutil.copyfile(link, _default_codex_home() / "auth.json")


def _encode_bounded(value: object, *, limit: int = _MAX_REQUEST_BYTES) -> bytes:
    encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > limit:
        raise ValueError(f"JSON payload exceeds {limit} bytes")
    return encoded


def _read_json_object(path: Path, *, limit: int = _MAX_RESPONSE_BYTES) -> dict[str, object]:
    raw = _read_bounded(path, limit)
    value = json.loads(raw)
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError("response must be a JSON object")
    return value


def _read_bounded(path: Path, limit: int) -> bytes:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        raise
    if size > limit:
        raise ValueError(f"JSON file exceeds {limit} bytes")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ValueError(f"JSON file exceeds {limit} bytes")
    return raw


def _atomic_write(target: Path, content: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _deadline(timeout: float) -> float:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    return time.monotonic() + timeout


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Codex CLI timed out: coach deadline expired")
    return remaining


def _remove_matching_request(directory: Path, packet: dict[str, object]) -> None:
    path = directory / "request.json"
    try:
        current = _read_json_object(path, limit=_MAX_REQUEST_BYTES)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return
    if current.get("request_id") == packet.get("request_id"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
