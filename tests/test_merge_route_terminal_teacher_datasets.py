from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from balatro_ai_v2.actions import iter_legal_actions
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.route_teacher import route_terminal_teacher_coverage
from balatro_ai_v2.strategy_engine import RunGoal, RunRoute
from balatro_ai_v2.strategy_teacher import (
    StrategyRolloutTarget,
    StrategyTeacherCandidate,
    StrategyTeacherDraft,
    write_teacher_records,
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


def test_publisher_is_no_overwrite_and_binds_digest(tmp_path, monkeypatch):
    module = _module()
    key = b"k" * 32
    records = (_record(1, key),)
    report = {
        "strategy_teacher_dataset": {"sha256": None},
        "manifest": {"source_digest": "s", "repository_revision": "r", "backend": {}},
    }
    merger_source = {
        "repository_revision": "m",
        "repository_dirty": False,
        "source_digest": "x",
    }
    monkeypatch.setattr(module, "_capture_merger_source", lambda *_: merger_source)
    dataset = tmp_path / "bundle/teacher.jsonl"
    output = tmp_path / "bundle/report.json"
    module._publish_bundle(dataset, output, records, report, tmp_path, merger_source)
    assert dataset.exists() and output.exists()
    assert (
        json.loads(output.read_text())["strategy_teacher_dataset"]["sha256"]
        == hashlib.sha256(dataset.read_bytes()).hexdigest()
    )
    with pytest.raises(SystemExit, match="overwrite"):
        module._publish_bundle(
            dataset, output, records, report, tmp_path, merger_source
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


def test_actual_batch_report_shape_has_collection_flags_only_in_binding(tmp_path):
    module = _module()
    record = _record(1, b"k" * 32)
    dataset = tmp_path / "teacher.jsonl"
    report = tmp_path / "report.json"
    digest = write_teacher_records(dataset, (record,))
    report.write_text(
        json.dumps(
            {
                "strategy_teacher_dataset": {
                    "mode": "route_terminal_paired_utility",
                    "schema_version": 11,
                    "status": "written",
                    "sha256": digest,
                    "records": 1,
                    "groups": 1,
                    "contains_game_seeds": False,
                    "complete_runs_only": True,
                    "teacher_config_digest": "a" * 64,
                },
                "results": [],
            }
        )
    )
    _, _, loaded_report, loaded_records, _ = module._load_component(dataset, report)
    assert loaded_report["strategy_teacher_dataset"]["records"] == len(loaded_records)


def test_component_binding_flags_remain_mandatory(tmp_path):
    module = _module()
    component = (
        tmp_path / "teacher",
        tmp_path / "report",
        {
            "route_terminal_teacher_preregistration": {
                "protocol_id": module.ROUTE_TEACHER_PROTOCOL_ID,
                "sha256": "p" * 64,
                "immutable_batches": True,
                "collection_only": True,
                "training_authorized": True,
            }
        },
        (),
        "d" * 64,
    )
    components = (component,) * 5
    with pytest.raises(SystemExit, match="lacks distinct binding"):
        module._validate_components(components, {}, "p" * 64, b"k" * 32, tmp_path)


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
        (record, record),
        "e" * 64,
    )
    merger_source = {
        "repository_revision": "m",
        "repository_dirty": False,
        "source_digest": "x",
    }
    merged = module._merged_report(
        (component,), (record, record), {"records": 2}, "p" * 64, merger_source
    )
    assert merged["collection_summary"]["training_authorized"] is False
    assert len(merged["merged_components"][0]["opaque_group_sha256"]) == 64
    assert merged["merged_components"][0]["opaque_groups"] == [record.run_group]
    assert (
        merged["merged_components"][0]["opaque_group_sha256"]
        == hashlib.sha256(record.run_group.encode()).hexdigest()
    )
    assert merged["manifest"]["merger_source"] == merger_source


def test_components_are_canonicalized_by_frozen_batch_order(tmp_path):
    module = _module()

    def component(batch_id):
        return (
            tmp_path / f"{batch_id}.jsonl",
            tmp_path / f"{batch_id}.json",
            {"route_terminal_teacher_preregistration": {"batch_id": batch_id}},
            (),
            "d" * 64,
        )

    ordered = module._canonical_components(
        (component("batch-05"), component("batch-01"), component("batch-03"))
    )
    assert [
        row[2]["route_terminal_teacher_preregistration"]["batch_id"] for row in ordered
    ] == ["batch-01", "batch-03", "batch-05"]


def test_publisher_discards_stage_if_merger_source_changes(tmp_path, monkeypatch):
    module = _module()
    record = _record(1, b"k" * 32)
    expected = {
        "repository_revision": "m",
        "repository_dirty": False,
        "source_digest": "x",
    }
    changed = {**expected, "source_digest": "y"}
    monkeypatch.setattr(module, "_capture_merger_source", lambda *_: changed)
    report = {
        "strategy_teacher_dataset": {"sha256": None},
        "manifest": {"repository_revision": "c"},
    }
    dataset = tmp_path / "bundle/teacher.jsonl"
    output = tmp_path / "bundle/report.json"
    with pytest.raises(SystemExit, match="source changed"):
        module._publish_bundle(dataset, output, (record,), report, tmp_path, expected)
    assert not dataset.parent.exists()


def test_publisher_rejects_identical_dataset_and_report_paths(tmp_path):
    module = _module()
    output = tmp_path / "bundle/output.json"
    with pytest.raises(SystemExit, match="must be distinct"):
        module._publish_bundle(output, output, (), {}, tmp_path, {})


def test_publisher_does_not_replace_racing_destination(tmp_path, monkeypatch):
    module = _module()
    record = _record(1, b"k" * 32)
    expected = {
        "repository_revision": "m",
        "repository_dirty": False,
        "source_digest": "x",
    }
    dataset = tmp_path / "bundle/teacher.jsonl"
    output = tmp_path / "bundle/report.json"
    destination = dataset.parent

    def capture(_root):
        destination.mkdir(parents=True)
        (destination / "sentinel").write_text("keep")
        return expected

    monkeypatch.setattr(module, "_capture_merger_source", capture)
    with pytest.raises(SystemExit, match="overwrite"):
        module._publish_bundle(
            dataset,
            output,
            (record,),
            {"strategy_teacher_dataset": {"sha256": None}},
            tmp_path,
            expected,
        )
    assert (destination / "sentinel").read_text() == "keep"
    assert not dataset.exists() and not output.exists()


def test_main_captures_merger_source_before_loading_inputs(tmp_path, monkeypatch):
    module = _module()
    calls = []
    args = SimpleNamespace(
        repository_root=tmp_path,
        output_jsonl=tmp_path / "bundle/teacher.jsonl",
        output_report=tmp_path / "bundle/report.json",
        preregistration_json=tmp_path / "prereg.json",
        origin_key_file=tmp_path / "key",
        input=(),
    )
    parser = SimpleNamespace(parse_args=lambda: args)
    monkeypatch.setattr(module, "build_parser", lambda: parser)
    monkeypatch.setattr(
        module,
        "_capture_merger_source",
        lambda _root: calls.append("capture")
        or {
            "repository_revision": "m",
            "repository_dirty": False,
            "source_digest": "x",
        },
    )

    def reject_inputs(*_args):
        calls.append("load")
        raise RuntimeError("stop")

    monkeypatch.setattr(module, "_load_preregistration", reject_inputs)
    with pytest.raises(RuntimeError, match="stop"):
        module.main()
    assert calls == ["capture", "load"]


def test_tensorization_preflight_supplies_route_features(monkeypatch):
    module = _module()
    record = _record(1, b"k" * 32)
    seen = []

    class Batch:
        def validate(self):
            seen.append("validated")

    class Tensorizer:
        def __init__(self, _config):
            pass

        def tensorize(self, *_args):
            seen.append(_args[4])
            return Batch()

    monkeypatch.setattr(module, "PublicStrategyTensorizer", Tensorizer)
    module._tensorization_preflight((record,), {})
    assert seen[0] == ((None, RunRoute.PLAYED_RETRIGGER),)
    assert seen[1] == "validated"
