from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from balatro_ai_v2.actions import SelectBlind, action_to_data
from balatro_ai_v2.backend import (
    AuthorityObservation,
    BackendCapabilities,
    BackendMetadata,
    RunSpec,
    StepResult,
)
from balatro_ai_v2.balatrobot.tracing import (
    AuthorityTraceWriter,
    TraceManifest,
    _git_state,
    read_verified_trace,
)
from balatro_ai_v2.canonical import BalatroBotCanonicalizer
from balatro_ai_v2.differential import replay_authority_trace
from state_factory import state


def _metadata() -> BackendMetadata:
    return BackendMetadata(
        backend_name="test",
        backend_version="1",
        adapter_version="1",
        game_version="1",
        runtime_version="1",
        capabilities=BackendCapabilities(True, False, False, False, False),
    )


def _manifest() -> TraceManifest:
    return TraceManifest(
        run_id="run-1",
        created_at="2026-01-01T00:00:00+00:00",
        repository_revision="abc",
        repository_dirty=False,
        source_digest="source",
        command=("test",),
        config_digest="config",
        policy_name="test",
        model_digest=None,
        inference_budget="none",
        backend=_metadata(),
        run=RunSpec("RED", "WHITE", "1"),
        sealed_seed_manifest_digest=None,
        max_decisions=2,
        max_settle_polls=2,
        wall_clock_limit_seconds=None,
        launch_fast=True,
        launch_headless=True,
        profile_mode="all_unlocked",
    )


def test_trace_is_exclusive_sequenced_and_hash_chained(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    writer = AuthorityTraceWriter(path, _manifest())
    writer.record("run_start", value=1)
    writer.record("run_end", complete=True)

    rows = read_verified_trace(path)

    assert [row["seq"] for row in rows] == [0, 1, 2]
    assert rows[0]["event"] == "manifest"
    with pytest.raises(FileExistsError):
        AuthorityTraceWriter(path, _manifest())


def test_trace_tampering_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    writer = AuthorityTraceWriter(path, _manifest())
    writer.record("run_end", complete=False)
    lines = path.read_text().splitlines()
    row = json.loads(lines[1])
    row["complete"] = True
    lines[1] = json.dumps(row)
    path.write_text("\n".join(lines) + "\n")

    with pytest.raises(ValueError, match="hash mismatch"):
        read_verified_trace(path)


def test_trace_rejects_old_canonical_schema(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    writer = AuthorityTraceWriter(path, replace(_manifest(), canonical_schema_version=1))
    writer.record("run_end", complete=False)

    with pytest.raises(ValueError, match="canonical schema"):
        read_verified_trace(path)


def test_trace_rejects_missing_profile_mode(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    writer = AuthorityTraceWriter(path, replace(_manifest(), profile_mode=""))
    writer.record("run_end", complete=False)

    with pytest.raises(ValueError, match="profile mode"):
        read_verified_trace(path)


def test_git_state_ignores_untracked_files_but_detects_tracked_edits(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    tracked = tmp_path / "tracked.py"
    tracked.write_text("value = 1\n")
    subprocess.run(["git", "add", "tracked.py"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=tmp_path, check=True)

    (tmp_path / "notes.md").write_text("untracked\n")
    _, dirty = _git_state(tmp_path)
    assert not dirty

    tracked.write_text("value = 2\n")
    _, dirty = _git_state(tmp_path)
    assert dirty


def test_trace_rejects_changed_run_id_even_with_valid_hash_chain(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    writer = AuthorityTraceWriter(path, _manifest())
    writer.record("run_end", complete=False)
    lines = path.read_text().splitlines()
    row = json.loads(lines[1])
    row["run_id"] = "different-run"
    row_without_hash = {key: value for key, value in row.items() if key != "row_hash"}
    from balatro_ai_v2.balatrobot import tracing

    row["row_hash"] = tracing._row_hash(row_without_hash)
    lines[1] = json.dumps(row)
    path.write_text("\n".join(lines) + "\n")

    with pytest.raises(ValueError, match="run ID changed"):
        read_verified_trace(path)


class ReplayBackend:
    metadata = _metadata()

    def __init__(self, *, changed_money: bool = False) -> None:
        self.canonicalizer = BalatroBotCanonicalizer()
        self.changed_money = changed_money
        self.current = None

    def reset(self, spec: RunSpec) -> AuthorityObservation:
        self.canonicalizer.reset()
        self.current = AuthorityObservation(self.canonicalizer.canonicalize(state()), True)
        return self.current

    def step(self, action) -> StepResult:
        terminal = state("GAME_OVER", won=True, money=5 if self.changed_money else 4)
        after = AuthorityObservation(self.canonicalizer.canonicalize(terminal), True)
        before = self.current
        self.current = after
        return StepResult("accepted", action, before, "select", {}, (), after)  # type: ignore[arg-type]

    def observe(self) -> AuthorityObservation:
        return self.current

    def close(self) -> None:
        return None


def _write_complete_trace(path: Path) -> None:
    canonicalizer = BalatroBotCanonicalizer()
    initial = canonicalizer.canonicalize(state())
    terminal = canonicalizer.canonicalize(state("GAME_OVER", won=True))
    writer = AuthorityTraceWriter(path, _manifest())
    writer.record("run_start", authority={"canonical": initial.canonical})
    writer.record(
        "transition",
        status="accepted",
        action=action_to_data(SelectBlind()),
        after={"canonical": terminal.canonical},
    )
    writer.record("run_end", complete=True, won=True)


def test_identical_backend_passes_observed_lockstep(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    _write_complete_trace(path)

    report = replay_authority_trace(path, ReplayBackend())

    assert report.observed_lockstep
    assert report.checked_transitions == 1


def test_nested_mismatch_reports_exact_json_pointer(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    _write_complete_trace(path)

    report = replay_authority_trace(path, ReplayBackend(changed_money=True))

    assert not report.observed_lockstep
    assert report.mismatch is not None
    assert report.mismatch.path == "/money"


def test_candidate_profile_mode_must_match_trace(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    _write_complete_trace(path)
    candidate = ReplayBackend()
    candidate.profile_mode = "career"

    report = replay_authority_trace(path, candidate)

    assert not report.observed_lockstep
    assert report.mismatch is not None
    assert report.mismatch.path == "/manifest/profile_mode"


def test_incomplete_authority_trace_never_passes(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    writer = AuthorityTraceWriter(path, _manifest())
    writer.record("run_start", authority={"canonical": {}})
    writer.record("run_end", complete=False)

    report = replay_authority_trace(path, ReplayBackend())

    assert not report.observed_lockstep
    assert report.mismatch is not None
    assert report.mismatch.message == "authority trace is incomplete"
