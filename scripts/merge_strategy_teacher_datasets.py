#!/usr/bin/env python3
"""Merge immutable dense-teacher batches without weakening their provenance."""

from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import math
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.actions import (
    ReorderConsumables,
    ReorderHand,
    ReorderJokers,
    iter_legal_actions,
)
from balatro_ai_v2.strategy_model import (
    PublicStrategyTensorizer,
    StrategyModelConfig,
)
from balatro_ai_v2.balatrobot.tracing import source_snapshot
from balatro_ai_v2.strategy_teacher import (
    StrategyTargetEndpoint,
    StrategyTeacherRecord,
    teacher_records_from_bytes,
    write_teacher_records,
)


_BATCH_STARTS = tuple(range(1975, 2275, 50))
_BATCH_SIZE = 50
_EXPECTED_SEEDS = set(range(1975, 2275))
_EXPECTED_BUDGET = {
    "samples": 6,
    "horizon_antes": 1,
    "max_steps": 200,
    "override_z": 1.0,
}
_REORDER_ACTIONS = (ReorderHand, ReorderJokers, ReorderConsumables)
_PROTOCOL_ID = "contextual-continuation-development-v4"
_NONCE = "contextual-continuation-v12-frozen"
_SEARCH_VERSION = "determinized-search-v14"
_EXPECTED_SEARCH = {
    **_EXPECTED_BUDGET,
    "max_decisions": 1200,
    "ante_cap": 12,
    "workers": 6,
    "nonce": _NONCE,
    "continuation": "strategic",
    "policy_seed": "baseline-v1",
    "strategy_options": False,
    "include_reorders": False,
    "dense_teacher": True,
}
_EXPECTED_TRAINING = {
    "split_nonce": "strategy-split-v3-predeclared",
    "train_groups": 182,
    "calibration_groups": 59,
    "holdout_groups": 59,
    "epochs": 30,
    "training_seed": 20260904,
    "hidden_size": 64,
    "attention_heads": 4,
    "attention_layers": 2,
    "feedforward_size": 128,
    "max_entities": 256,
    "max_actions": 512,
    "learning_rate": 0.0003,
    "weight_decay": 0.0001,
    "max_gradient_norm": 1.0,
    "device": "cpu",
}
_EXPECTED_COVERAGE_GATE = {
    "groups": 300,
    "minimum_records": 2000,
    "required_phases": ["BLIND_SELECT", "SHOP", "PACK"],
    "minimum_action_sensitive_fraction": 0.4,
    "maximum_stored_roots": 512,
    "maximum_subset_rows": 0,
    "minimum_winning_source_groups": 20,
    "minimum_observed_victory_groups": 10,
    "minimum_postwin_rows": 100,
    "minimum_postwin_groups": 20,
    "rejected_or_censored": 0,
}
_EXPECTED_FIRST_100_GATE = {
    "minimum_action_sensitive_fraction": 0.4,
    "minimum_observed_victory_groups": 10,
    "rejected_or_censored": 0,
}


def main() -> None:
    args = build_parser().parse_args()
    for path in (args.output_jsonl, args.output_report):
        if path.exists():
            raise SystemExit(f"refusing to overwrite existing output: {path}")
    repository_root = args.repository_root.resolve()
    preregistration, preregistration_digest, origin_key = _load_preregistration(
        args.preregistration_json,
        args.origin_key_file,
        repository_root=repository_root,
    )
    components = tuple(
        _load_component(Path(dataset), Path(report)) for dataset, report in args.input
    )
    _validate_components(
        components,
        preregistration=preregistration,
        preregistration_digest=preregistration_digest,
        origin_key=origin_key,
        repository_root=repository_root,
    )
    expected_manifest = components[0][2]["manifest"]
    _verify_merger_checkout(expected_manifest, repository_root)
    records = tuple(record for component in components for record in component[3])
    _tensorization_preflight(records, preregistration)
    _validate_coverage_gates(components, records, preregistration)
    report = _merged_report(components, records, args.output_jsonl)
    _verify_merger_checkout(expected_manifest, repository_root)
    dataset_digest = _publish_merged_bundle(
        args.output_jsonl,
        args.output_report,
        records,
        report,
        expected_manifest=expected_manifest,
        repository_root=repository_root,
    )
    print(
        json.dumps(
            {
                "dataset_sha256": dataset_digest,
                "records": len(records),
                "groups": len({record.run_group for record in records}),
                "components": len(components),
            },
            sort_keys=True,
        )
    )


def _verify_merger_checkout(
    expected_manifest: dict[str, object], repository_root: Path
) -> None:
    revision, dirty, digest = source_snapshot(repository_root)
    if (
        dirty
        or revision != expected_manifest.get("repository_revision")
        or digest != expected_manifest.get("source_digest")
    ):
        raise SystemExit("merger checkout differs from the collection source freeze")


def _load_component(
    dataset_path: Path,
    report_path: Path,
) -> tuple[
    Path,
    Path,
    dict[str, object],
    tuple[StrategyTeacherRecord, ...],
    str,
]:
    try:
        dataset_bytes = dataset_path.read_bytes()
        dataset_digest = hashlib.sha256(dataset_bytes).hexdigest()
        report_bytes = report_path.read_bytes()
        report = json.loads(report_bytes)
        records = teacher_records_from_bytes(dataset_bytes)
        teacher = report["strategy_teacher_dataset"]
        benchmark = report["benchmark_protocol"]
        manifest = report["manifest"]
        results = report["results"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"invalid teacher component {dataset_path}: {exc}") from exc
    if (
        not isinstance(report, dict)
        or not isinstance(teacher, dict)
        or teacher.get("mode") != "dense_paired_utility"
        or teacher.get("status") != "written"
        or teacher.get("sha256") != dataset_digest
        or teacher.get("records") != len(records)
        or teacher.get("groups") != len({record.run_group for record in records})
        or {record.teacher_config_digest for record in records}
        != {teacher.get("teacher_config_digest")}
        or teacher.get("complete_runs_only") is not True
        or teacher.get("contains_game_seeds") is not False
        or not isinstance(benchmark, dict)
        or benchmark.get("seed_provenance") != "development"
        or benchmark.get("filtered_seeds") is not False
        or not isinstance(manifest, dict)
        or manifest.get("repository_dirty") is not False
        or manifest.get("max_antes_cleared") != 12
        or manifest.get("max_decisions") != 1200
        or not isinstance(manifest.get("run"), dict)
        or manifest["run"].get("deck") != "RED"
        or manifest["run"].get("stake") != "WHITE"
        or not isinstance(results, list)
        or len(results) != teacher.get("groups")
        or len({row.get("seed") for row in results if isinstance(row, dict)})
        != len(results)
        or any(
            not isinstance(row, dict)
            or row.get("complete") is not True
            or isinstance(row.get("seed"), bool)
            or not isinstance(row.get("seed"), int)
            or not isinstance(row.get("won"), bool)
            or not isinstance(row.get("search"), dict)
            or row["search"].get("rejected_rollouts") != 0
            for row in results
        )
        or any(
            len(candidate.samples) != 6
            or any(
                sample.endpoint == StrategyTargetEndpoint.CENSORED
                for sample in candidate.samples
            )
            for record in records
            for candidate in record.candidates
        )
        or any(
            len(record.candidates) > 512
            or record.candidate_space_size != len(record.candidates)
            for record in records
        )
    ):
        raise SystemExit(f"teacher component is not merge-eligible: {dataset_path}")
    return (
        dataset_path,
        report_path,
        report,
        records,
        hashlib.sha256(report_bytes).hexdigest(),
    )


def _validate_components(
    components,
    *,
    preregistration: dict[str, object],
    preregistration_digest: str,
    origin_key: bytes,
    repository_root: Path,
) -> None:
    if len(components) != len(_BATCH_STARTS):
        raise SystemExit("merge requires exactly six immutable teacher batches")
    first = components[0][2]
    first_binding = first.get("contextual_teacher_preregistration")
    if not isinstance(first_binding, dict) or not isinstance(
        first_binding.get("sha256"), str
    ):
        raise SystemExit("teacher component lacks contextual preregistration")
    try:
        fixed = _fixed_protocol(first, first_binding)
    except (KeyError, TypeError) as exc:
        raise SystemExit("teacher component protocol is incomplete") from exc
    if (
        fixed["candidate_runtime"] != preregistration["candidate_runtime"]
        or fixed["source_digest"] != preregistration["expected_source_digest"]
        or fixed["backend"] != preregistration["backend"]
        or fixed["strategy_tuning"] != preregistration["strategy_tuning"]
        or fixed["preregistration_sha256"] != preregistration_digest
    ):
        raise SystemExit("teacher components disagree with their preregistration")
    _validate_source_freeze(fixed, preregistration, repository_root)
    seeds: set[int] = set()
    groups: set[str] = set()
    batch_ids: set[str] = set()
    for dataset_path, report_path, report, records, _ in components:
        path = dataset_path
        binding = report.get("contextual_teacher_preregistration")
        panel = report["benchmark_protocol"].get("panel_registry")
        search = report["search_protocol"]
        manifest = report["manifest"]
        if (
            not isinstance(binding, dict)
            or binding.get("protocol_id") != _PROTOCOL_ID
            or binding.get("sha256") != preregistration_digest
            or binding.get("immutable_batches") is not True
            or not isinstance(binding.get("batch_id"), str)
            or not isinstance(panel, dict)
            or panel.get("verification") != "registry_verified"
            or panel.get("count") != _BATCH_SIZE
            or search.get("version") != _SEARCH_VERSION
            or search.get("budget") != _EXPECTED_BUDGET
            or search.get("nonce") != _NONCE
            or search.get("continuation") != "strategic"
            or search.get("policy_seed") != "baseline-v1"
            or search.get("phases") != ["BLIND_SELECT", "PACK", "SHOP"]
            or search.get("strategy_options") is not False
            or search.get("include_reorders") is not False
            or report["benchmark_protocol"].get("restart_selection") is not False
            or report["benchmark_protocol"].get("mods") is not False
            or manifest.get("max_antes_cleared") != 12
            or manifest.get("max_decisions") != 1200
        ):
            raise SystemExit(f"teacher component violates frozen protocol: {path}")
        try:
            candidate = _fixed_protocol(report, binding)
        except (KeyError, TypeError) as exc:
            raise SystemExit(
                f"teacher component protocol is incomplete: {path}"
            ) from exc
        if candidate != fixed:
            raise SystemExit(f"teacher component protocol mismatch: {path}")
        component_seeds = {int(row["seed"]) for row in report["results"]}
        component_groups = {record.run_group for record in records}
        seed_start = binding.get("seed_start")
        declared_batch = next(
            (
                batch
                for batch in preregistration["batches"]
                if isinstance(batch, dict) and batch.get("seed_start") == seed_start
            ),
            None,
        )
        if (
            seed_start not in _BATCH_STARTS
            or binding.get("seeds") != _BATCH_SIZE
            or component_seeds != set(range(seed_start, seed_start + _BATCH_SIZE))
            or len(component_groups) != _BATCH_SIZE
            or sum(bool(row["won"]) for row in report["results"])
            != len({record.run_group for record in records if record.run_won})
            or not isinstance(declared_batch, dict)
            or binding.get("batch_id") != declared_batch.get("batch_id")
            or dataset_path.resolve()
            != (repository_root / str(declared_batch.get("teacher_jsonl"))).resolve()
            or report_path.resolve()
            != (repository_root / str(declared_batch.get("report_json"))).resolve()
        ):
            raise SystemExit(f"teacher component has the wrong batch panel: {path}")
        if seeds & component_seeds or groups & component_groups:
            raise SystemExit("teacher components overlap seeds or origin families")
        if binding["batch_id"] in batch_ids:
            raise SystemExit("teacher components repeat a preregistered batch")
        seeds.update(component_seeds)
        groups.update(component_groups)
        batch_ids.add(binding["batch_id"])
        _validate_component_records(
            report,
            records,
            origin_key=origin_key,
        )
    if seeds != _EXPECTED_SEEDS:
        raise SystemExit("teacher components do not cover the frozen seed union")


def _validate_source_freeze(
    fixed: dict[str, object],
    preregistration: dict[str, object],
    repository_root: Path,
) -> None:
    implementation_revision = str(preregistration["implementation_revision"])
    collection_revision = fixed["repository_revision"]
    if not isinstance(collection_revision, str) or len(collection_revision) != 40:
        raise SystemExit("teacher component repository revision is invalid")
    try:
        subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                implementation_revision,
                collection_revision,
            ],
            cwd=repository_root,
            check=True,
            capture_output=True,
        )
        changed = subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                implementation_revision,
                collection_revision,
            ],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("cannot verify teacher implementation ancestry") from exc
    if set(changed) != {"experiments/contextual-continuation-v12-preregistration.json"}:
        raise SystemExit("teacher collection revision changed implementation source")


def _load_preregistration(
    path: Path,
    origin_key_path: Path,
    *,
    repository_root: Path,
) -> tuple[dict[str, object], str, bytes]:
    expected_path = (
        repository_root / "experiments/contextual-continuation-v12-preregistration.json"
    ).resolve()
    if path.resolve() != expected_path:
        raise SystemExit("contextual preregistration path is not frozen")
    try:
        raw = path.read_bytes()
        spec = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid contextual preregistration: {exc}") from exc
    if not isinstance(spec, dict):
        raise SystemExit("contextual preregistration root must be an object")
    expected_batches = [
        {
            "batch_id": f"batch-{index:02d}",
            "seed_start": seed_start,
            "seeds": _BATCH_SIZE,
            "teacher_jsonl": (
                "runs/experiments/contextual-continuation-v12/"
                f"batch-{index:02d}/teacher.jsonl"
            ),
            "report_json": (
                "runs/experiments/contextual-continuation-v12/"
                f"batch-{index:02d}/report.json"
            ),
        }
        for index, seed_start in enumerate(_BATCH_STARTS, start=1)
    ]
    origin = spec.get("origin_mapping")
    if (
        spec.get("protocol_id") != _PROTOCOL_ID
        or spec.get("status") != "reserved"
        or spec.get("immutable_batches") is not True
        or spec.get("seed_provenance") != "development"
        or spec.get("deck") != "RED"
        or spec.get("stake") != "WHITE"
        or spec.get("search") != _EXPECTED_SEARCH
        or spec.get("training") != _EXPECTED_TRAINING
        or spec.get("coverage_gate") != _EXPECTED_COVERAGE_GATE
        or spec.get("first_100_kill_gate") != _EXPECTED_FIRST_100_GATE
        or spec.get("batches") != expected_batches
        or not isinstance(origin, dict)
        or origin.get("algorithm") != "hmac-sha256-truncated-128"
        or origin.get("key_path")
        != "runs/secrets/contextual-continuation-v12-origin.key"
    ):
        raise SystemExit("contextual preregistration changed the frozen protocol")
    for field, length in (
        ("implementation_revision", 40),
        ("expected_source_digest", 64),
    ):
        value = spec.get(field)
        if (
            not isinstance(value, str)
            or len(value) != length
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise SystemExit(f"contextual preregistration has invalid {field}")
    expected_key_path = (repository_root / str(origin["key_path"])).resolve()
    if origin_key_path.resolve() != expected_key_path:
        raise SystemExit("contextual origin key path is not preregistered")
    try:
        origin_key = origin_key_path.read_bytes()
    except OSError as exc:
        raise SystemExit("contextual origin key is unreadable") from exc
    if (
        len(origin_key) != 32
        or origin.get("key_sha256") != hashlib.sha256(origin_key).hexdigest()
        or not isinstance(spec.get("candidate_runtime"), dict)
        or not isinstance(spec.get("backend"), dict)
        or not isinstance(spec.get("strategy_tuning"), dict)
    ):
        raise SystemExit("contextual preregistration provenance is invalid")
    return spec, hashlib.sha256(raw).hexdigest(), origin_key


def _validate_component_records(
    report: dict[str, object],
    records: tuple[StrategyTeacherRecord, ...],
    *,
    origin_key: bytes,
) -> None:
    results = report["results"]
    assert isinstance(results, list)
    expected_groups: dict[str, dict[str, object]] = {}
    for row in results:
        assert isinstance(row, dict)
        search = row.get("search")
        if (
            row.get("complete") is not True
            or row.get("terminal_reason") not in {"game_over", "ante_cap"}
            or row.get("terminal_error") is not None
            or row.get("rejected_decisions") != 0
            or not isinstance(row.get("best_hand_score"), int)
            or isinstance(row.get("best_hand_score"), bool)
            or int(row["best_hand_score"]) < 0
            or not isinstance(search, dict)
            or search.get("rejected_rollouts") != 0
            or search.get("unavailable") != 0
            or not isinstance(search.get("searched"), int)
            or isinstance(search.get("searched"), bool)
            or int(search["searched"]) < 0
            or row.get("search_failure_reasons") != {}
        ):
            raise SystemExit("teacher component contains a failed originating run")
        seed = int(row["seed"])
        group = (
            "origin-"
            + hmac.new(origin_key, str(seed).encode(), hashlib.sha256).hexdigest()[:32]
        )
        expected_groups[group] = row
    by_group: dict[str, list[StrategyTeacherRecord]] = {}
    for record in records:
        by_group.setdefault(record.run_group, []).append(record)
    if set(by_group) != set(expected_groups):
        raise SystemExit("teacher component origin mapping is invalid")
    for group, group_records in by_group.items():
        row = expected_groups[group]
        search = row["search"]
        assert isinstance(search, dict)
        ordered = sorted(group_records, key=lambda record: record.decision_index)
        if [record.decision_index for record in ordered] != list(
            range(len(ordered))
        ) or len(ordered) != int(search["searched"]):
            raise SystemExit("teacher component decision sequence is incomplete")
        expected_log_score = math.log10(max(1, int(row["best_hand_score"])))
        for record in ordered:
            if (
                record.run_won is not row["won"]
                or record.terminal_ante != row["antes_cleared"]
                or not math.isclose(
                    record.run_log_score,
                    expected_log_score,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            ):
                raise SystemExit("teacher record outcome disagrees with its run")
            legal_roots = tuple(
                action
                for action in iter_legal_actions(record.observation)
                if not isinstance(action, _REORDER_ACTIONS)
            )
            candidate_actions = tuple(
                candidate.action for candidate in record.candidates
            )
            if (
                not legal_roots
                or candidate_actions != legal_roots
                or record.candidate_space_size != len(legal_roots)
                or any(candidate.intent is not None for candidate in record.candidates)
                or any(len(candidate.samples) != 6 for candidate in record.candidates)
                or any(
                    sample.endpoint == StrategyTargetEndpoint.CENSORED
                    for candidate in record.candidates
                    for sample in candidate.samples
                )
                or record.selected_index != _recompute_selected(record)
            ):
                raise SystemExit("teacher record violates the complete-root contract")


def _recompute_selected(record: StrategyTeacherRecord) -> int:
    baseline_values = tuple(
        sample.search_utility
        for sample in record.candidates[record.baseline_index].samples
    )
    best_index = record.baseline_index
    best_mean: float | None = None
    for index, candidate in enumerate(record.candidates):
        if index == record.baseline_index:
            continue
        deltas = tuple(
            sample.search_utility - baseline
            for sample, baseline in zip(candidate.samples, baseline_values, strict=True)
        )
        mean = sum(deltas) / len(deltas)
        if mean <= 0.0:
            continue
        variance = sum((delta - mean) ** 2 for delta in deltas) / (len(deltas) - 1)
        lower = mean - math.sqrt(variance / len(deltas))
        if lower > 0.0 and (best_mean is None or mean > best_mean):
            best_index = index
            best_mean = mean
    return best_index


def _tensorization_preflight(
    records: tuple[StrategyTeacherRecord, ...], spec: dict[str, object]
) -> None:
    training = spec["training"]
    assert isinstance(training, dict)
    tensorizer = PublicStrategyTensorizer(
        StrategyModelConfig(
            hidden_size=int(training["hidden_size"]),
            attention_heads=int(training["attention_heads"]),
            attention_layers=int(training["attention_layers"]),
            feedforward_size=int(training["feedforward_size"]),
            max_entities=int(training["max_entities"]),
            max_actions=int(training["max_actions"]),
        )
    )
    try:
        for offset in range(0, len(records), 32):
            chunk = records[offset : offset + 32]
            batch = tensorizer.tensorize(
                tuple(record.observation for record in chunk),
                tuple(
                    tuple(candidate.action for candidate in record.candidates)
                    for record in chunk
                ),
                tuple(
                    tuple(candidate.intent for candidate in record.candidates)
                    for record in chunk
                ),
                tuple(record.context for record in chunk),
            )
            batch.validate()
    except (RuntimeError, TypeError, ValueError) as exc:
        raise SystemExit(f"teacher tensorization preflight failed: {exc}") from exc


def _validate_coverage_gates(
    components,
    records: tuple[StrategyTeacherRecord, ...],
    spec: dict[str, object],
) -> None:
    results = [row for _, _, report, _, _ in components for row in report["results"]]
    coverage = _coverage(records, results)
    dense = coverage["dense_paired_utility"]
    assert isinstance(dense, dict)
    gate = spec["coverage_gate"]
    assert isinstance(gate, dict)
    phase_rows = dense["phase_rows"]
    assert isinstance(phase_rows, dict)
    if (
        len({record.run_group for record in records}) != int(gate["groups"])
        or len(records) < int(gate["minimum_records"])
        or any(phase_rows.get(phase, 0) <= 0 for phase in gate["required_phases"])
        or float(dense["action_sensitive_fraction"])
        < float(gate["minimum_action_sensitive_fraction"])
        or int(dense["stored_root_max"]) > int(gate["maximum_stored_roots"])
        or int(dense["subset_rows"]) > int(gate["maximum_subset_rows"])
        or int(coverage["winning_source_groups"])
        < int(gate["minimum_winning_source_groups"])
        or int(dense["observed_victory_origin_groups"])
        < int(gate["minimum_observed_victory_groups"])
        or int(dense["postwin_rows"]) < int(gate["minimum_postwin_rows"])
        or int(dense["postwin_origin_groups"]) < int(gate["minimum_postwin_groups"])
        or int(gate["rejected_or_censored"]) != 0
    ):
        raise SystemExit("merged teacher dataset failed its coverage gate")

    first_components = sorted(
        components,
        key=lambda component: int(
            component[2]["contextual_teacher_preregistration"]["seed_start"]
        ),
    )[:2]
    first_records = tuple(
        record for component in first_components for record in component[3]
    )
    first_results = [
        row for component in first_components for row in component[2]["results"]
    ]
    first_dense = _coverage(first_records, first_results)["dense_paired_utility"]
    assert isinstance(first_dense, dict)
    first_gate = spec["first_100_kill_gate"]
    assert isinstance(first_gate, dict)
    if (
        float(first_dense["action_sensitive_fraction"])
        < float(first_gate["minimum_action_sensitive_fraction"])
        or int(first_dense["observed_victory_origin_groups"])
        < int(first_gate["minimum_observed_victory_groups"])
        or int(first_gate["rejected_or_censored"]) != 0
    ):
        raise SystemExit("merged teacher dataset failed its first-100 gate")


def _fixed_protocol(
    report: dict[str, object], binding: dict[str, object]
) -> dict[str, object]:
    return {
        "search_protocol": report["search_protocol"],
        "strategy_tuning": report["strategy_tuning"],
        "candidate_runtime": report["candidate_runtime"],
        "source_digest": report["manifest"]["source_digest"],
        "backend": report["manifest"]["backend"],
        "repository_revision": report["manifest"]["repository_revision"],
        "teacher_config_digest": report["strategy_teacher_dataset"][
            "teacher_config_digest"
        ],
        "preregistration_sha256": binding["sha256"],
    }


def _merged_report(components, records, output_jsonl: Path) -> dict[str, object]:
    report = copy.deepcopy(components[0][2])
    results = sorted(
        (row for _, _, component, _, _ in components for row in component["results"]),
        key=lambda row: int(row["seed"]),
    )
    report["summary"] = {
        "runs": len(results),
        "complete": sum(bool(row["complete"]) for row in results),
        "wins": sum(bool(row["won"]) for row in results),
        "mean_antes_cleared": sum(int(row["antes_cleared"]) for row in results)
        / len(results),
        "merged_component_reports": len(components),
    }
    report["benchmark_protocol"]["panel_registry"] = {
        "verification": "component_registries_verified",
        "provenance": "development",
        "count": len(results),
    }
    report["merged_components"] = [
        {
            "report_sha256": report_digest,
            "dataset_sha256": component["strategy_teacher_dataset"]["sha256"],
            "batch_id": component["contextual_teacher_preregistration"]["batch_id"],
        }
        for _, _, component, _, report_digest in components
    ]
    teacher = report["strategy_teacher_dataset"]
    teacher.update(
        {
            "path": str(output_jsonl.resolve()),
            "sha256": None,
            "records": len(records),
            "groups": len({record.run_group for record in records}),
            "coverage": _coverage(records, results),
        }
    )
    report["collection_summary"] = {
        "complete_groups": len(results),
        "rejected_rollouts": 0,
        "winning_source_groups": sum(bool(row["won"]) for row in results),
    }
    report["contextual_teacher_preregistration"] = {
        "protocol_id": _PROTOCOL_ID,
        "sha256": components[0][2]["contextual_teacher_preregistration"]["sha256"],
        "immutable_batches": True,
        "batch_ids": sorted(
            component["contextual_teacher_preregistration"]["batch_id"]
            for _, _, component, _, _ in components
        ),
    }
    source_manifest = components[0][2]["manifest"]
    report["manifest"] = {
        "kind": "contextual_teacher_merge_v1",
        "source_digest": source_manifest["source_digest"],
        "repository_revision": source_manifest["repository_revision"],
        "repository_dirty": False,
        "backend": source_manifest["backend"],
        "component_count": len(components),
    }
    report.pop("results", None)
    return report


def _coverage(records, results) -> dict[str, object]:
    phases = Counter(record.observation.phase.value for record in records)
    sensitive = 0
    for record in records:
        baseline = record.candidates[record.baseline_index].samples
        sensitive += int(
            any(
                abs(
                    sum(
                        sample.search_utility - base.search_utility
                        for sample, base in zip(
                            candidate.samples, baseline, strict=True
                        )
                    )
                    / len(candidate.samples)
                )
                > 1e-12
                for candidate in record.candidates
            )
        )
    postwin = tuple(record for record in records if record.goal.value == "endless")
    victory_groups = {
        record.run_group
        for record in records
        if any(
            sample.ante8_win == 1.0
            for candidate in record.candidates
            for sample in candidate.samples
        )
    }
    return {
        "winning_source_groups": sum(bool(row["won"]) for row in results),
        "losing_source_groups": sum(not bool(row["won"]) for row in results),
        "dense_paired_utility": {
            "records": len(records),
            "action_sensitive_rows": sensitive,
            "action_sensitive_fraction": sensitive / len(records),
            "phase_rows": dict(sorted(phases.items())),
            "stored_root_max": max(len(record.candidates) for record in records),
            "candidate_space_max": max(
                record.candidate_space_size for record in records
            ),
            "subset_rows": sum(
                record.candidate_space_size > len(record.candidates)
                for record in records
            ),
            "subset_contract": "complete_roots;max512;overflow=fail_closed",
            "observed_victory_origin_groups": len(victory_groups),
            "postwin_rows": len(postwin),
            "postwin_origin_groups": len({record.run_group for record in postwin}),
        },
    }


def _publish_json_exclusive(path: Path, encoded: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def _publish_merged_bundle(
    output_jsonl: Path,
    output_report: Path,
    records: tuple[StrategyTeacherRecord, ...],
    report: dict[str, object],
    *,
    expected_manifest: dict[str, object],
    repository_root: Path,
) -> str:
    """Publish both immutable merge artifacts with one directory rename."""

    final_directory = output_jsonl.parent.resolve()
    if output_report.parent.resolve() != final_directory:
        raise SystemExit("merged teacher outputs must share one bundle directory")
    if final_directory.exists():
        raise SystemExit(f"refusing to overwrite existing bundle: {final_directory}")
    final_directory.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(
        tempfile.mkdtemp(
            prefix=f".{final_directory.name}.",
            suffix=".tmp",
            dir=final_directory.parent,
        )
    )
    staged_dataset = staged / output_jsonl.name
    staged_report = staged / output_report.name
    try:
        dataset_digest = write_teacher_records(staged_dataset, records)
        report["strategy_teacher_dataset"]["sha256"] = dataset_digest
        _publish_json_exclusive(
            staged_report,
            json.dumps(report, sort_keys=True, allow_nan=False) + "\n",
        )
        _verify_merger_checkout(expected_manifest, repository_root)
        os.rename(staged, final_directory)
        return dataset_digest
    except BaseException:
        staged_dataset.unlink(missing_ok=True)
        staged_report.unlink(missing_ok=True)
        try:
            staged.rmdir()
        except OSError:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        nargs=2,
        action="append",
        metavar=("DATASET_JSONL", "COLLECTION_REPORT"),
        required=True,
    )
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument("--preregistration-json", type=Path, required=True)
    parser.add_argument("--origin-key-file", type=Path, required=True)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    return parser


if __name__ == "__main__":
    main()
