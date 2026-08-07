from __future__ import annotations

import json
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
from balatro_ai_v2.balatrobot.tracing import AuthorityTraceWriter, TraceManifest, read_verified_trace
from balatro_ai_v2.canonical import BalatroBotCanonicalizer
from balatro_ai_v2.differential import replay_authority_trace
from scripts.run_differential_campaign import summarize_trace_coverage
from tests.state_factory import state


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


def test_incomplete_authority_trace_never_passes(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    writer = AuthorityTraceWriter(path, _manifest())
    writer.record("run_start", authority={"canonical": {}})
    writer.record("run_end", complete=False)

    report = replay_authority_trace(path, ReplayBackend())

    assert not report.observed_lockstep
    assert report.mismatch is not None
    assert report.mismatch.message == "authority trace is incomplete"


def test_trace_coverage_summary_is_fail_closed_without_required_baseline_actions(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    writer = AuthorityTraceWriter(path, _manifest())
    writer.record("run_start", authority={"canonical": {}})
    writer.record(
        "transition",
        status="accepted",
        action={"type": "buy_pack"},
        before={"canonical": {"state": "SHOP", "packs": {"cards": [{}]}, "round": {}}},
        after={"canonical": {}},
    )
    writer.record(
        "transition",
        status="accepted",
        action={"type": "skip_pack"},
        before={"canonical": {"state": "BUFFOON_PACK", "pack": {"cards": [{}]}, "round": {}}},
        after={"canonical": {}},
    )
    writer.record("run_end", complete=True)

    summary = summarize_trace_coverage(path, pack_strategy="skip")

    assert summary["accepted_action_counts"] == {"buy_pack": 1, "skip_pack": 1}
    assert summary["required_action_counts"]["select_blind"] == 0
    assert summary["opportunity_counts"]["action:buy_pack"] == 1
    assert summary["opportunity_counts"]["action:skip_pack"] == 1
    assert summary["coverage_complete"] is False


def test_trace_coverage_summary_reports_complete_pick_lane(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    writer = AuthorityTraceWriter(path, _manifest())
    writer.record("run_start", authority={"canonical": {}})
    writer.record(
        "transition",
        status="accepted",
        action={"type": "select_blind"},
        before={"canonical": {"state": "BLIND_SELECT", "blinds": {"small": {"status": "SELECT"}}, "round": {}}},
        after={"canonical": {}},
    )
    writer.record(
        "transition",
        status="accepted",
        action={"type": "discard_cards"},
        before={"canonical": {"state": "SELECTING_HAND", "round": {"discards_left": 2}}},
        after={"canonical": {}},
    )
    writer.record(
        "transition",
        status="accepted",
        action={"type": "play_cards"},
        before={"canonical": {"state": "SELECTING_HAND", "round": {"discards_left": 1}}},
        after={"canonical": {}},
    )
    writer.record(
        "transition",
        status="accepted",
        action={"type": "cash_out"},
        before={"canonical": {"state": "ROUND_EVAL", "round": {}}},
        after={"canonical": {}},
    )
    writer.record(
        "transition",
        status="accepted",
        action={"type": "buy_pack"},
        before={"canonical": {"state": "SHOP", "packs": {"cards": [{}, {}]}, "round": {}}},
        after={"canonical": {}},
    )
    writer.record(
        "transition",
        status="accepted",
        action={"type": "choose_pack_card"},
        before={"canonical": {"state": "PLANET_PACK", "pack": {"cards": [{}, {}]}, "round": {}}},
        after={"canonical": {}},
    )
    writer.record(
        "transition",
        status="accepted",
        action={"type": "leave_shop"},
        before={"canonical": {"state": "SHOP", "packs": {"cards": [{}]}, "round": {}}},
        after={"canonical": {}},
    )
    writer.record("run_end", complete=True)

    summary = summarize_trace_coverage(path, pack_strategy="pick")

    assert summary["coverage_complete"] is True
    assert summary["phase_counts"] == {
        "BLIND_SELECT": 1,
        "PLANET_PACK": 1,
        "ROUND_EVAL": 1,
        "SELECTING_HAND": 2,
        "SHOP": 2,
    }
    assert summary["required_action_counts"]["choose_pack_card"] == 1
