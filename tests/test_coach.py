from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import Thread

import pytest

from balatro_ai.coach import (
    _RESPONSE_SCHEMA,
    CodexCoach,
    SessionCoach,
    read_request,
    write_response,
)
from balatro_ai.packet import compact_packet


def _packet() -> dict[str, object]:
    return {"request_id": "request-7", "instructions": "Choose one legal action."}


def _response() -> dict[str, object]:
    return {
        "request_id": "request-7",
        "action_json": '{"type":"select_blind"}',
        "plan": "Build enough score while retaining cash.",
    }


def _fake_codex(tmp_path: Path) -> Path:
    executable = tmp_path / "fake-codex"
    executable.write_text(
        """#!/usr/bin/env python3
import json, os, pathlib, sys, time
log = pathlib.Path(os.environ["FAKE_CODEX_LOG"])
with log.open("a", encoding="utf-8") as stream:
    stream.write(json.dumps({
        "argv": sys.argv[1:], "cwd": os.getcwd(),
        "stdin": sys.stdin.read(),
        "has_openai_key": "OPENAI_API_KEY" in os.environ,
        "has_anthropic_key": "ANTHROPIC_API_KEY" in os.environ,
        "codex_home": os.environ.get("CODEX_HOME"),
    }) + "\\n")
if sys.argv[1:3] == ["login", "status"]:
    print(os.environ.get("FAKE_AUTH_OUTPUT", "Logged in using ChatGPT"))
    raise SystemExit(int(os.environ.get("FAKE_AUTH_EXIT", "0")))
if os.environ.get("FAKE_SLEEP"):
    time.sleep(float(os.environ["FAKE_SLEEP"]))
if os.environ.get("FAKE_STALL_FIRST"):
    flag = pathlib.Path(os.environ["FAKE_STALL_FIRST"])
    if not flag.exists():
        flag.touch()
        time.sleep(30)
args = sys.argv[1:]
output = pathlib.Path(args[args.index("--output-last-message") + 1])
output.write_text(os.environ["FAKE_RESPONSE"], encoding="utf-8")
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def test_codex_coach_uses_fixed_isolated_bounded_command(monkeypatch, tmp_path) -> None:
    executable = _fake_codex(tmp_path)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
    monkeypatch.setenv("FAKE_RESPONSE", json.dumps(_response()))
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-leak")

    coach = CodexCoach(str(executable))
    assert coach.choose(_packet(), timeout=2) == _response()
    assert coach.last_timings["packet_seconds"] >= 0
    assert coach.last_timings["codex_seconds"] >= 0
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert calls[0]["argv"] == ["login", "status"]
    invocation = calls[1]
    args = invocation["argv"]
    assert args[:2] == ["exec", "--ignore-user-config"]
    assert "--ignore-rules" in args and "--ephemeral" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert args[args.index("-m") + 1] == "gpt-6-astra"
    assert 'model_reasoning_effort="low"' in args
    assert 'model_provider="openai"' in args
    assert 'forced_login_method="chatgpt"' in args
    assert 'web_search="disabled"' in args
    for feature in (
        "shell_tool",
        "unified_exec",
        "apps",
        "plugins",
        "multi_agent",
        "browser_use",
        "image_generation",
        "memories",
        "hooks",
        "skill_search",
        "view_image",
    ):
        assert ["--disable", feature] == args[
            args.index(
                "--disable", 0 if feature == "shell_tool" else args.index(feature) - 1
            ) : args.index(feature) + 1
        ]
    assert json.loads(invocation["stdin"]) == compact_packet(_packet())
    assert not invocation["has_openai_key"] and not invocation["has_anthropic_key"]
    assert invocation["cwd"] != os.getcwd()
    assert Path(invocation["cwd"]).exists()
    coach.close()
    assert not Path(invocation["cwd"]).exists()


def test_preflight_requires_chatgpt_and_is_cached(monkeypatch, tmp_path) -> None:
    executable = _fake_codex(tmp_path)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
    monkeypatch.setenv("FAKE_RESPONSE", json.dumps(_response()))
    monkeypatch.setenv("FAKE_AUTH_OUTPUT", "Logged in using an API key")
    coach = CodexCoach(str(executable))

    with pytest.raises(RuntimeError, match="logged in using ChatGPT"):
        coach.preflight(1)
    monkeypatch.setenv("FAKE_AUTH_OUTPUT", "Logged in using ChatGPT")
    coach.preflight(1)
    coach.preflight(1)
    assert coach.choose(_packet(), 1) == _response()
    calls = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [call["argv"][:2] for call in calls] == [
        ["login", "status"],
        ["login", "status"],
        ["exec", "--ignore-user-config"],
    ]


def test_codex_coach_requires_chatgpt_auth_and_never_runs_inference(monkeypatch, tmp_path) -> None:
    executable = _fake_codex(tmp_path)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
    monkeypatch.setenv("FAKE_RESPONSE", json.dumps(_response()))
    monkeypatch.setenv("FAKE_AUTH_EXIT", "1")

    with pytest.raises(RuntimeError, match="status 1"):
        CodexCoach(str(executable)).choose(_packet(), timeout=2)
    assert len(log.read_text(encoding="utf-8").splitlines()) == 1


def test_codex_coach_kills_timed_out_call(monkeypatch, tmp_path) -> None:
    executable = _fake_codex(tmp_path)
    monkeypatch.setenv("FAKE_CODEX_LOG", str(tmp_path / "calls.jsonl"))
    monkeypatch.setenv("FAKE_RESPONSE", json.dumps(_response()))
    monkeypatch.setenv("FAKE_SLEEP", "5")

    coach = CodexCoach(str(executable))
    coach.preflight(timeout=10)  # keep the login check out of the timed call
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="timed out"):
        coach.choose(_packet(), timeout=0.5)
    assert time.monotonic() - started < 3


def test_session_coach_publishes_atomically_and_consumes_response(tmp_path) -> None:
    public = tmp_path / "public"
    errors: list[BaseException] = []

    def answer() -> None:
        try:
            deadline = time.monotonic() + 2
            while not (public / "request.json").exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("request did not appear")
                time.sleep(0.002)
            assert read_request(public) == _packet()
            write_response(public, _response())
        except BaseException as error:
            errors.append(error)

    worker = Thread(target=answer)
    worker.start()
    assert SessionCoach(public).choose(_packet(), timeout=2) == _response()
    worker.join(timeout=2)
    assert not worker.is_alive() and not errors
    assert not (public / "request.json").exists()
    assert not (public / "response.json").exists()


def test_session_timeout_cleans_request_and_helpers_reject_bad_exchange(tmp_path) -> None:
    public = tmp_path / "public"
    with pytest.raises(TimeoutError, match="session response"):
        SessionCoach(public).choose(_packet(), timeout=0.02)
    assert not (public / "request.json").exists()

    (public / "request.json").write_text(json.dumps(_packet()), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        write_response(public, {**_response(), "request_id": "stale"})
    write_response(public, _response())
    with pytest.raises(RuntimeError, match="already pending"):
        write_response(public, _response())
    with pytest.raises(RuntimeError, match="stale"):
        SessionCoach(public).choose(_packet(), timeout=1)


def test_read_request_allows_packet_larger_than_response_limit(tmp_path) -> None:
    public = tmp_path / "public"
    public.mkdir()
    packet = {**_packet(), "instructions": "x" * 70_000}
    (public / "request.json").write_text(json.dumps(packet), encoding="utf-8")
    assert read_request(public) == packet


@pytest.mark.parametrize("timeout", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_timeout_is_rejected(timeout, tmp_path) -> None:
    with pytest.raises(ValueError, match="finite"):
        SessionCoach(tmp_path).choose(_packet(), timeout)


def test_same_workspace_fresh_context_and_no_previous_response(monkeypatch, tmp_path):
    executable = _fake_codex(tmp_path)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
    monkeypatch.setenv("FAKE_RESPONSE", json.dumps(_response()))
    coach = CodexCoach(str(executable))
    assert coach.choose(_packet(), 2) == _response()
    workspace = Path(coach._workspace.name)
    assert not (workspace / "response.json").exists()
    assert coach.choose(_packet(), 2) == _response()
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(calls) == 3  # one cached auth preflight, two independent execs
    assert calls[1]["cwd"] == calls[2]["cwd"]
    assert all("--ephemeral" in call["argv"] for call in calls[1:])
    assert all("resume" not in call["argv"] for call in calls[1:])
    coach.close()
    assert not workspace.exists()


def test_response_schema_carries_an_optional_follow_up_chain() -> None:
    assert _RESPONSE_SCHEMA["required"] == ["request_id", "action_json", "plan", "then"]
    chain = _RESPONSE_SCHEMA["properties"]["then"]
    # Strict structured output needs every key required and optionality as null.
    assert chain["type"] == ["array", "null"]
    entry = chain["items"]
    assert set(entry["properties"]) == {"action_json", "repeat", "until"}
    assert entry["required"] == ["action_json", "repeat", "until"]
    assert entry["additionalProperties"] is False
    until = entry["properties"]["until"]
    assert until["type"] == ["object", "null"]
    assert set(until["properties"]) == {"shop_has_any", "money_at_least"}
    assert until["additionalProperties"] is False


def test_session_coach_passes_a_follow_up_chain_through(tmp_path) -> None:
    public = tmp_path / "public"
    chained = {
        **_response(),
        "then": [
            {"action_json": '{"type":"leave_shop"}', "repeat": None, "until": None},
        ],
    }
    errors: list[BaseException] = []

    def answer() -> None:
        try:
            deadline = time.monotonic() + 2
            while not (public / "request.json").exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("request did not appear")
                time.sleep(0.002)
            write_response(public, chained)
        except BaseException as error:
            errors.append(error)

    worker = Thread(target=answer)
    worker.start()
    assert SessionCoach(public).choose(_packet(), timeout=2) == chained
    worker.join(timeout=2)
    assert not worker.is_alive() and not errors


def test_codex_coach_hedges_a_stalled_call(monkeypatch, tmp_path) -> None:
    executable = _fake_codex(tmp_path)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
    monkeypatch.setenv("FAKE_RESPONSE", json.dumps(_response()))
    monkeypatch.setenv("FAKE_STALL_FIRST", str(tmp_path / "stalled-once"))
    coach = CodexCoach(str(executable))
    coach.preflight(timeout=10)
    coach.hedge_after_seconds = 0.3

    started = time.monotonic()
    response = coach.choose(_packet(), timeout=20)
    elapsed = time.monotonic() - started

    assert response == _response()
    assert elapsed < 10, "the hedge must answer long before the stalled first process"
    assert coach.last_timings["hedged"] is True and coach.last_timings["winner"] == 1
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    exec_calls = [c for c in calls if c["argv"][:1] == ["exec"]]
    assert len(exec_calls) == 2 and exec_calls[0]["stdin"] == exec_calls[1]["stdin"]


def test_codex_child_gets_a_private_home_linked_to_the_login(monkeypatch, tmp_path) -> None:
    real_home = tmp_path / "real-codex"
    real_home.mkdir()
    (real_home / "auth.json").write_text('{"tokens": "real"}', encoding="utf-8")
    (real_home / "sessions").mkdir()
    monkeypatch.setenv("CODEX_HOME", str(real_home))
    executable = _fake_codex(tmp_path)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
    monkeypatch.setenv("FAKE_RESPONSE", json.dumps(_response()))

    coach = CodexCoach(str(executable))
    coach.choose(_packet(), timeout=10)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    homes = {c["codex_home"] for c in calls}
    assert len(homes) == 1
    child_home = Path(homes.pop())
    assert child_home != real_home
    assert (child_home / "auth.json").is_symlink()
    assert (child_home / "auth.json").resolve() == (real_home / "auth.json").resolve()
    assert sorted(p.name for p in child_home.iterdir()) == ["auth.json"]

    # A token refresh that replaced the link is copied back to the real home on close.
    (child_home / "auth.json").unlink()
    (child_home / "auth.json").write_text('{"tokens": "refreshed"}', encoding="utf-8")
    coach.close()
    assert (real_home / "auth.json").read_text(encoding="utf-8") == '{"tokens": "refreshed"}'


def test_codex_child_keeps_the_default_home_without_a_login_file(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing"))
    executable = _fake_codex(tmp_path)
    log = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CODEX_LOG", str(log))
    monkeypatch.setenv("FAKE_RESPONSE", json.dumps(_response()))
    CodexCoach(str(executable)).choose(_packet(), timeout=10)
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert {c["codex_home"] for c in calls} == {str(tmp_path / "missing")}
