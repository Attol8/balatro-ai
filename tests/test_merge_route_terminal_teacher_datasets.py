from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from balatro_ai_v2.actions import iter_legal_actions
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.route_teacher import route_terminal_teacher_coverage
from balatro_ai_v2.strategy_engine import RunGoal, RunRoute
from balatro_ai_v2.strategy_teacher import (
    StrategyRolloutTarget,
    StrategyTeacherCandidate,
    StrategyTeacherDraft,
)
from state_factory import state


def _module():
    path = (
        Path(__file__).parents[1] / "scripts/merge_route_terminal_teacher_datasets.py"
    )
    spec = importlib.util.spec_from_file_location("route_merger", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(seed: int, key: bytes):
    observation = to_public_observation(state("SHOP", money=10))
    action = next(iter(iter_legal_actions(observation)))

    def target(utility):
        return tuple(
            StrategyRolloutTarget(1, 1, 1, 2, 2, search_utility=utility)
            for _ in range(2)
        )

    draft = StrategyTeacherDraft(
        observation=observation,
        candidates=(
            StrategyTeacherCandidate(action, None, target(1)),
            StrategyTeacherCandidate(
                action, None, target(2), RunRoute.PLAYED_RETRIGGER
            ),
        ),
        selected_index=1,
        baseline_index=0,
        ordinary_index=0,
        behavior_index=1,
        goal=RunGoal.VICTORY,
        teacher_config_digest="a" * 64,
        candidate_space_size=2,
    )
    group = "origin-" + hashlib.sha256(key + str(seed).encode()).hexdigest()[:32]
    return draft.finalize(
        run_group=group,
        decision_index=0,
        run_complete=True,
        run_won=False,
        terminal_ante=4,
        best_hand_score=100,
    )


def test_route_coverage_exposes_exact_pairs_and_gate_rejects_empty_support():
    key = b"k" * 32
    records = tuple(_record(seed, key) for seed in range(5))
    coverage = route_terminal_teacher_coverage(records)
    assert coverage["matched_pairs"] == 5
    assert coverage["route_diverse_rows"] == 5
    module = _module()
    failures = module.route_teacher_coverage_gate_failures(
        coverage,
        {
            "source_runs": 5,
            "minimum_record_groups": 1,
            "minimum_records": 1,
            "required_phases": ["SHOP"],
            "required_route_phases": ["SHOP"],
            "required_goals": ["victory"],
            "minimum_route_diverse_groups": 1,
            "minimum_route_diverse_rows": 1,
            "minimum_matched_pairs": 1,
            "minimum_search_utility_sensitive_pairs": 1,
            "sample_count": 2,
            "maximum_stored_roots": 512,
            "maximum_subset_rows": 0,
            "rejected_or_censored": 0,
        },
        source_runs=5,
    )
    assert failures == ()


def test_publisher_is_no_overwrite_and_binds_digest(tmp_path):
    module = _module()
    key = b"k" * 32
    records = (_record(1, key),)
    report = {
        "strategy_teacher_dataset": {"sha256": None},
        "manifest": {"source_digest": "s", "repository_revision": "r", "backend": {}},
    }
    dataset = tmp_path / "bundle/teacher.jsonl"
    output = tmp_path / "bundle/report.json"
    module._publish_bundle(
        dataset, output, records, report, tmp_path, report["manifest"]
    )
    assert dataset.exists() and output.exists()
    assert (
        json.loads(output.read_text())["strategy_teacher_dataset"]["sha256"]
        == hashlib.sha256(dataset.read_bytes()).hexdigest()
    )
    with pytest.raises(SystemExit, match="overwrite"):
        module._publish_bundle(
            dataset, output, records, report, tmp_path, report["manifest"]
        )


def test_schema_or_mode_is_rejected_by_component_loader(tmp_path):
    module = _module()
    dataset = tmp_path / "teacher.jsonl"
    report = tmp_path / "report.json"
    dataset.write_text("{}\n")
    report.write_text(
        json.dumps({"strategy_teacher_dataset": {"mode": "dense_paired_utility"}})
    )
    with pytest.raises(SystemExit, match="invalid route teacher component"):
        module._load_component(dataset, report)


def test_merged_report_keeps_opaque_component_membership(tmp_path):
    module = _module()
    record = _record(1, b"k" * 32)
    component_report = {
        "route_terminal_teacher_preregistration": {"batch_id": "batch-01"},
        "strategy_teacher_dataset": {
            "sha256": "d" * 64,
            "teacher_config_digest": "a" * 64,
        },
        "manifest": {
            "source_digest": "s",
            "repository_revision": "r",
            "backend": {},
        },
    }
    component = (
        tmp_path / "teacher",
        tmp_path / "report",
        component_report,
        (record,),
        "e" * 64,
    )
    merged = module._merged_report((component,), (record,), {"records": 1}, "p" * 64)
    assert merged["collection_summary"]["training_authorized"] is False
    assert len(merged["merged_components"][0]["opaque_group_sha256"]) == 64
