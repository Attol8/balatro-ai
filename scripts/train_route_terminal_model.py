#!/usr/bin/env python3
"""Train the frozen one-shot route-terminal residual model."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch

from balatro_ai_v2.balatrobot.tracing import source_snapshot
from balatro_ai_v2.route_evaluation import (
    evaluate_route_holdout,
    fit_route_residual_calibration,
)
from balatro_ai_v2.route_learning import (
    RouteDatasetSplit,
    reconstruct_route_split,
    route_split_admission_report,
    route_training_loss,
)
from balatro_ai_v2.route_learning_protocol import (
    ADMISSION_CONFIG,
    CALIBRATION_CONFIG,
    HOLDOUT_GATE,
    MODEL_CONFIG,
    OBJECTIVE_CONFIG,
    OPTIMIZER_CONFIG,
    ROUTE_LEARNING_COLLECTION_MODE,
    ROUTE_LEARNING_PREREGISTRATION,
    SPLIT_CONFIG,
    SUPPORT_CELL_CONTRACT,
    load_route_learning_preregistration,
)
from balatro_ai_v2.route_model import load_route_model, save_route_model
from balatro_ai_v2.route_teacher import (
    route_teacher_coverage_gate_failures,
    route_terminal_teacher_coverage,
)
from balatro_ai_v2.route_teacher_protocol import (
    ROUTE_TEACHER_BATCHES,
    ROUTE_TEACHER_COVERAGE_GATE,
    ROUTE_TEACHER_ORIGIN_KEY,
    ROUTE_TEACHER_PILOT_GATE,
    ROUTE_TEACHER_PREREGISTRATION,
    ROUTE_TEACHER_PROTOCOL_ID,
    ROUTE_TEACHER_SEARCH,
    ROUTE_TEACHER_TERMINAL,
)
from balatro_ai_v2.strategy_model import (
    RelationalStrategyPolicyValue,
    StrategyModelConfig,
)
from balatro_ai_v2.strategy_teacher import (
    STRATEGY_TEACHER_SCHEMA_VERSION,
    StrategyTeacherRecord,
    teacher_records_from_bytes,
)


_REPORT_SCHEMA_VERSION = 1
_DIGEST_LENGTH = 64
_REVISION_LENGTH = 40
_ORIGIN_GROUP = re.compile(r"origin-[0-9a-f]{32}")


@dataclass(frozen=True, slots=True)
class _Source:
    revision: str
    digest: str


@dataclass(frozen=True, slots=True)
class _Inputs:
    records: tuple[StrategyTeacherRecord, ...]
    merged_report: dict[str, object]
    dataset_digest: str
    merged_report_digest: str
    collection_preregistration: dict[str, object]
    collection_preregistration_digest: str
    learner_preregistration: dict[str, object]
    learner_preregistration_digest: str
    teacher_config_digest: str


def main() -> None:
    args = build_parser().parse_args()
    _validate_args(args)
    root = args.repository_root.resolve()
    source = _capture_source(root)
    _validate_output_paths(args.output_model, args.report_json)
    inputs = _load_inputs(args, root, source)
    split = reconstruct_route_split(inputs.records, inputs.merged_report)
    admission = route_split_admission_report(split)
    report = _base_report(args, source, inputs, split, admission)
    if admission.get("passed") is not True:
        report["status"] = "rejected"
        report["rejection_reason"] = "split_admission_failed"
        _publish_report_only(args.report_json, report, root, source)
        _print_result(report, args.report_json)
        return

    model, losses = _train(split)
    report["training"] = {
        "started": True,
        "epochs_completed": len(losses),
        "losses": losses,
    }
    calibration, calibration_evidence = fit_route_residual_calibration(model, split)
    evaluation = evaluate_route_holdout(
        model,
        split,
        calibration,
        calibration_evidence=calibration_evidence,
    )
    report["evaluation"] = evaluation
    report["gate"] = evaluation["gate"]
    if (
        not isinstance(evaluation.get("gate"), dict)
        or evaluation["gate"].get("passed") is not True
    ):
        report["status"] = "rejected"
        report["rejection_reason"] = "holdout_gate_failed"
        _publish_report_only(args.report_json, report, root, source)
        _print_result(report, args.report_json)
        return

    provenance = _route_provenance(inputs, split, source)
    report["status"] = "passed"
    report["rejection_reason"] = None
    artifact_digest, report_digest = _publish_pass_bundle(
        args.output_model,
        args.report_json,
        model,
        calibration,
        provenance,
        report,
        root,
        source,
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "model_sha256": artifact_digest,
                "report_sha256": report_digest,
            },
            sort_keys=True,
            allow_nan=False,
        )
    )


def _validate_args(args: argparse.Namespace) -> None:
    actual_model = {
        "hidden_size": args.hidden_size,
        "attention_heads": args.attention_heads,
        "attention_layers": args.attention_layers,
        "feedforward_size": args.feedforward_size,
        "dropout": 0.0,
        "max_entities": args.max_entities,
        "max_actions": args.max_actions,
    }
    actual_optimizer = {
        "name": "AdamW",
        "epochs": args.epochs,
        "training_seed": args.training_seed,
        "learning_rate": args.learning_rate,
        "weight_decay": args.weight_decay,
        "max_gradient_norm": args.max_gradient_norm,
    }
    if actual_model != MODEL_CONFIG or actual_optimizer != OPTIMIZER_CONFIG:
        raise SystemExit("route trainer configuration is frozen")
    if args.device != "cpu":
        raise SystemExit("route trainer device is frozen to cpu")


def _validate_output_paths(model: Path, report: Path) -> None:
    if model.resolve() == report.resolve():
        raise SystemExit("route model and report paths must be distinct")
    if model.parent.resolve() != report.parent.resolve():
        raise SystemExit("route model and report must share one bundle directory")
    if model.exists() or report.exists() or model.parent.exists():
        raise SystemExit("refusing to overwrite existing route output bundle")


def _capture_source(root: Path) -> _Source:
    revision, dirty, digest = source_snapshot(root)
    if dirty or not _is_revision(revision) or not _is_digest(digest):
        raise SystemExit("route trainer checkout is dirty")
    return _Source(revision, digest)


def _load_inputs(args: argparse.Namespace, root: Path, source: _Source) -> _Inputs:
    learner, learner_digest = load_route_learning_preregistration(
        args.learner_preregistration_json, repository_root=root
    )
    _validate_source_bindings(root, source, learner)
    collection, collection_digest = _load_collection_preregistration(
        args.collection_preregistration_json, root
    )
    if learner["collection_preregistration_sha256"] != collection_digest:
        raise SystemExit("learner preregistration does not bind collection protocol")
    try:
        dataset_bytes = args.input_jsonl.read_bytes()
        report_bytes = args.collection_report.read_bytes()
        merged_report = json.loads(report_bytes)
        records = teacher_records_from_bytes(dataset_bytes)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise SystemExit("route training inputs are unreadable") from exc
    dataset_digest = hashlib.sha256(dataset_bytes).hexdigest()
    report_digest = hashlib.sha256(report_bytes).hexdigest()
    teacher_config_digest = _validate_merged_bundle(
        records,
        merged_report,
        dataset_digest,
        learner,
        collection,
        collection_digest,
        root,
    )
    return _Inputs(
        records,
        merged_report,
        dataset_digest,
        report_digest,
        collection,
        collection_digest,
        learner,
        learner_digest,
        teacher_config_digest,
    )


def _load_collection_preregistration(
    path: Path, root: Path
) -> tuple[dict[str, object], str]:
    expected = (root / ROUTE_TEACHER_PREREGISTRATION).resolve()
    if path.resolve() != expected:
        raise SystemExit("collection preregistration path is not frozen")
    try:
        raw = path.read_bytes()
        spec = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("collection preregistration is unreadable") from exc
    origin = spec.get("origin_mapping") if isinstance(spec, dict) else None
    if (
        not isinstance(spec, dict)
        or set(spec)
        != {
            "protocol_id",
            "status",
            "immutable_batches",
            "collection_only",
            "training_authorized",
            "schema_version",
            "implementation_revision",
            "expected_source_digest",
            "seed_provenance",
            "deck",
            "stake",
            "candidate_runtime",
            "backend",
            "strategy_tuning",
            "search",
            "terminal_teacher",
            "origin_mapping",
            "batches",
            "pilot_gate",
            "coverage_gate",
        }
        or spec.get("protocol_id") != ROUTE_TEACHER_PROTOCOL_ID
        or spec.get("status") != "reserved"
        or spec.get("immutable_batches") is not True
        or spec.get("collection_only") is not True
        or spec.get("training_authorized") is not False
        or spec.get("schema_version") != STRATEGY_TEACHER_SCHEMA_VERSION
        or spec.get("search") != ROUTE_TEACHER_SEARCH
        or spec.get("terminal_teacher") != ROUTE_TEACHER_TERMINAL
        or spec.get("batches") != list(ROUTE_TEACHER_BATCHES)
        or spec.get("pilot_gate") != ROUTE_TEACHER_PILOT_GATE
        or spec.get("coverage_gate") != ROUTE_TEACHER_COVERAGE_GATE
        or spec.get("seed_provenance") != "development"
        or spec.get("deck") != "RED"
        or spec.get("stake") != "WHITE"
        or not _is_revision(spec.get("implementation_revision"))
        or not _is_digest(spec.get("expected_source_digest"))
        or not isinstance(origin, dict)
        or set(origin) != {"algorithm", "key_path", "key_sha256"}
        or origin.get("algorithm") != "hmac-sha256-truncated-128"
        or origin.get("key_path") != ROUTE_TEACHER_ORIGIN_KEY
        or not _is_digest(origin.get("key_sha256"))
        or not isinstance(spec.get("candidate_runtime"), dict)
        or not isinstance(spec.get("backend"), dict)
        or not isinstance(spec.get("strategy_tuning"), dict)
    ):
        raise SystemExit("collection preregistration changed the frozen protocol")
    return spec, hashlib.sha256(raw).hexdigest()


def _validate_source_bindings(
    root: Path, source: _Source, learner: dict[str, object]
) -> None:
    if source.digest != learner.get("expected_source_digest"):
        raise SystemExit("route trainer source digest disagrees with preregistration")
    _validate_frozen_revision(
        root,
        learner.get("implementation_revision"),
        source.revision,
        ROUTE_LEARNING_PREREGISTRATION,
        "trainer",
    )


def _validate_merged_bundle(
    records: Sequence[StrategyTeacherRecord],
    report: object,
    dataset_digest: str,
    learner: dict[str, object],
    collection: dict[str, object],
    collection_digest: str,
    root: Path,
) -> str:
    if not isinstance(report, dict):
        raise SystemExit("merged route report is malformed")
    teacher = report.get("strategy_teacher_dataset")
    binding = report.get("route_terminal_teacher_preregistration")
    manifest = report.get("manifest")
    summary = report.get("summary")
    collection_summary = report.get("collection_summary")
    if (
        not isinstance(teacher, dict)
        or teacher.get("status") != "written"
        or teacher.get("mode") != ROUTE_LEARNING_COLLECTION_MODE
        or teacher.get("schema_version") != STRATEGY_TEACHER_SCHEMA_VERSION
        or teacher.get("sha256") != dataset_digest
        or teacher.get("records") != len(records)
        or teacher.get("groups") != len({record.run_group for record in records})
        or teacher.get("contains_game_seeds") is not False
        or teacher.get("complete_runs_only") is not True
        or teacher.get("collection_only") is not True
        or teacher.get("training_authorized") is not False
        or not isinstance(binding, dict)
        or binding.get("protocol_id") != ROUTE_TEACHER_PROTOCOL_ID
        or binding.get("sha256") != collection_digest
        or binding.get("immutable_batches") is not True
        or binding.get("collection_only") is not True
        or binding.get("training_authorized") is not False
        or binding.get("batch_ids")
        != [batch["batch_id"] for batch in ROUTE_TEACHER_BATCHES]
        or not isinstance(manifest, dict)
        or manifest.get("kind") != "route_terminal_teacher_merge_v1"
        or manifest.get("repository_dirty") is not False
        or manifest.get("component_count") != len(ROUTE_TEACHER_BATCHES)
        or not _is_revision(manifest.get("repository_revision"))
        or manifest.get("source_digest") != collection.get("expected_source_digest")
        or report.get("candidate_runtime") != collection.get("candidate_runtime")
        or report.get("strategy_tuning") != collection.get("strategy_tuning")
        or manifest.get("backend") != collection.get("backend")
        or not isinstance(summary, dict)
        or summary.get("runs")
        != sum(int(batch["seeds"]) for batch in ROUTE_TEACHER_BATCHES)
        or summary.get("complete") is not True
        or summary.get("merged_component_reports") != len(ROUTE_TEACHER_BATCHES)
        or not isinstance(collection_summary, dict)
        or collection_summary.get("rejected_or_censored") != 0
        or collection_summary.get("training_authorized") is not False
    ):
        raise SystemExit("merged route report violates the training contract")
    components = report.get("merged_components")
    if not isinstance(components, list) or len(components) != len(
        ROUTE_TEACHER_BATCHES
    ):
        raise SystemExit("merged route report has the wrong component count")
    expected_ids = [batch["batch_id"] for batch in ROUTE_TEACHER_BATCHES]
    groups: list[str] = []
    for component, batch_id in zip(components, expected_ids, strict=True):
        if not isinstance(component, dict) or set(component) != {
            "batch_id",
            "report_sha256",
            "dataset_sha256",
            "opaque_group_sha256",
            "opaque_groups",
        }:
            raise SystemExit("merged route component fields are invalid")
        opaque = component["opaque_groups"]
        if (
            component["batch_id"] != batch_id
            or not _is_digest(component["report_sha256"])
            or not _is_digest(component["dataset_sha256"])
            or not isinstance(opaque, list)
            or not opaque
            or opaque != sorted(opaque)
            or len(set(opaque)) != len(opaque)
            or any(
                not isinstance(group, str) or _ORIGIN_GROUP.fullmatch(group) is None
                for group in opaque
            )
            or component["opaque_group_sha256"]
            != hashlib.sha256("\n".join(opaque).encode()).hexdigest()
        ):
            raise SystemExit("merged route component binding is invalid")
        groups.extend(opaque)
    if len(set(groups)) != len(groups) or set(groups) != {
        record.run_group for record in records
    }:
        raise SystemExit("merged route component groups disagree with records")
    config_digests = {record.teacher_config_digest for record in records}
    teacher_config = teacher.get("teacher_config_digest")
    if config_digests != {teacher_config} or not _is_digest(teacher_config):
        raise SystemExit("merged route teacher configuration is inconsistent")
    merger = manifest.get("merger_source")
    if (
        not isinstance(merger, dict)
        or merger.get("repository_dirty") is not False
        or not _is_revision(merger.get("repository_revision"))
        or merger.get("source_digest") != learner.get("merger_expected_source_digest")
    ):
        raise SystemExit("merged route report disagrees with frozen merger source")
    _validate_frozen_revision(
        root,
        collection.get("implementation_revision"),
        manifest.get("repository_revision"),
        ROUTE_TEACHER_PREREGISTRATION,
        "collection",
    )
    _validate_frozen_revision(
        root,
        learner.get("merger_implementation_revision"),
        merger.get("repository_revision"),
        ROUTE_LEARNING_PREREGISTRATION,
        "merger",
    )
    coverage_container = teacher.get("coverage")
    coverage = (
        coverage_container.get(ROUTE_LEARNING_COLLECTION_MODE)
        if isinstance(coverage_container, dict)
        else None
    )
    recomputed = route_terminal_teacher_coverage(records)
    if coverage != recomputed:
        raise SystemExit("merged route coverage disagrees with authenticated records")
    failures = route_teacher_coverage_gate_failures(
        recomputed,
        ROUTE_TEACHER_COVERAGE_GATE,
        source_runs=sum(int(batch["seeds"]) for batch in ROUTE_TEACHER_BATCHES),
    )
    if failures:
        raise SystemExit(
            "merged route records fail frozen coverage: " + ",".join(failures)
        )
    return str(teacher_config)


def _validate_frozen_revision(
    root: Path,
    implementation: object,
    runtime: object,
    allowed_preregistration: str,
    label: str,
) -> None:
    if not _is_revision(implementation) or not _is_revision(runtime):
        raise SystemExit(f"route {label} revision is invalid")
    try:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", implementation, runtime],
            cwd=root,
            check=True,
            capture_output=True,
        )
        changed = subprocess.run(
            ["git", "diff", "--name-only", implementation, runtime],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"cannot verify route {label} ancestry") from exc
    if set(changed) != {allowed_preregistration}:
        raise SystemExit(f"route {label} revision changed implementation source")


def _train(
    split: RouteDatasetSplit,
) -> tuple[RelationalStrategyPolicyValue, list[dict[str, float | int]]]:
    torch.manual_seed(int(OPTIMIZER_CONFIG["training_seed"]))
    model = RelationalStrategyPolicyValue(StrategyModelConfig(**MODEL_CONFIG)).to("cpu")
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(OPTIMIZER_CONFIG["learning_rate"]),
        weight_decay=float(OPTIMIZER_CONFIG["weight_decay"]),
    )
    losses: list[dict[str, float | int]] = []
    for epoch in range(int(OPTIMIZER_CONFIG["epochs"])):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        loss, metrics = route_training_loss(model, split.train)
        if not torch.isfinite(loss):
            raise RuntimeError("route training loss became non-finite")
        loss.backward()
        gradients = [
            parameter.grad
            for parameter in model.parameters()
            if parameter.grad is not None
        ]
        if not gradients or any(
            not torch.isfinite(gradient).all() for gradient in gradients
        ):
            raise RuntimeError("route training gradient became non-finite")
        gradient_norm = torch.nn.utils.clip_grad_norm_(
            model.parameters(), float(OPTIMIZER_CONFIG["max_gradient_norm"])
        )
        if not torch.isfinite(gradient_norm):
            raise RuntimeError("route training gradient norm became non-finite")
        optimizer.step()
        if any(not torch.isfinite(parameter).all() for parameter in model.parameters()):
            raise RuntimeError("route training parameter became non-finite")
        losses.append(
            {
                "epoch": epoch + 1,
                **{key: float(value) for key, value in metrics.items()},
                "gradient_norm": float(gradient_norm.detach().cpu().item()),
            }
        )
    return model, losses


def _route_provenance(
    inputs: _Inputs, split: RouteDatasetSplit, source: _Source
) -> dict[str, object]:
    return {
        "training_status": "trained",
        "influence_mode": "shadow_only",
        "dataset_sha256": inputs.dataset_digest,
        "collection_report_sha256": inputs.merged_report_digest,
        "collection_preregistration_sha256": inputs.collection_preregistration_digest,
        "learner_preregistration_sha256": inputs.learner_preregistration_digest,
        "teacher_config_digest": inputs.teacher_config_digest,
        "split": split.manifest(),
        "objective": deepcopy(OBJECTIVE_CONFIG),
        "trainer_source_revision": source.revision,
        "trainer_source_digest": source.digest,
    }


def _base_report(
    args: argparse.Namespace,
    source: _Source,
    inputs: _Inputs,
    split: RouteDatasetSplit,
    admission: dict[str, object],
) -> dict[str, object]:
    return {
        "kind": "route_terminal_model_training_v1",
        "schema_version": _REPORT_SCHEMA_VERSION,
        "status": "running",
        "rejection_reason": None,
        "shadow_only": True,
        "promotion_eligible": False,
        "action_authority": False,
        "rollout_authority": False,
        "certificate_created": False,
        "source": {
            "repository_revision": source.revision,
            "repository_dirty": False,
            "source_digest": source.digest,
        },
        "inputs": {
            "dataset": {
                "path": str(args.input_jsonl.resolve()),
                "sha256": inputs.dataset_digest,
                "records": len(inputs.records),
                "groups": len({record.run_group for record in inputs.records}),
                "schema_version": STRATEGY_TEACHER_SCHEMA_VERSION,
                "mode": ROUTE_LEARNING_COLLECTION_MODE,
                "teacher_config_digest": inputs.teacher_config_digest,
            },
            "collection_report": {
                "path": str(args.collection_report.resolve()),
                "sha256": inputs.merged_report_digest,
            },
            "collection_preregistration": {
                "path": str(args.collection_preregistration_json.resolve()),
                "sha256": inputs.collection_preregistration_digest,
            },
            "learner_preregistration": {
                "path": str(args.learner_preregistration_json.resolve()),
                "sha256": inputs.learner_preregistration_digest,
            },
        },
        "config": {
            "model": deepcopy(MODEL_CONFIG),
            "optimizer": deepcopy(OPTIMIZER_CONFIG),
            "objective": deepcopy(OBJECTIVE_CONFIG),
            "calibration": deepcopy(CALIBRATION_CONFIG),
            "split": deepcopy(SPLIT_CONFIG),
            "admission": deepcopy(ADMISSION_CONFIG),
            "holdout_gate": deepcopy(HOLDOUT_GATE),
            "support_cells": deepcopy(SUPPORT_CELL_CONTRACT),
            "device": "cpu",
        },
        "split": split.manifest(),
        "admission": admission,
        "training": {"started": False, "epochs_completed": 0, "losses": []},
        "evaluation": None,
        "gate": None,
        "artifact": {
            "status": "absent",
            "path": str(args.output_model.resolve()),
            "sha256": None,
        },
        "environment": {
            "python_version": platform.python_version(),
            "torch_version": str(torch.__version__),
            "platform": platform.platform(),
        },
        "command": list(sys.argv),
    }


def _publish_report_only(
    report_path: Path,
    report: dict[str, object],
    root: Path,
    expected_source: _Source,
) -> str:
    return _publish_directory_bundle(
        report_path.parent,
        {report_path.name: _encode_report(report)},
        root,
        expected_source,
    )[report_path.name]


def _publish_pass_bundle(
    model_path: Path,
    report_path: Path,
    model: RelationalStrategyPolicyValue,
    calibration,
    provenance: dict[str, object],
    report: dict[str, object],
    root: Path,
    expected_source: _Source,
) -> tuple[str, str]:
    final = model_path.parent.resolve()
    final.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(
        tempfile.mkdtemp(prefix=f".{final.name}.", suffix=".tmp", dir=final.parent)
    )
    try:
        staged_model = staged / model_path.name
        artifact_digest = save_route_model(
            staged_model, model, calibration=calibration, provenance=provenance
        )
        loaded = load_route_model(staged_model, device="cpu")
        if (
            hashlib.sha256(staged_model.read_bytes()).hexdigest() != artifact_digest
            or loaded.calibration != calibration
            or loaded.provenance != provenance
        ):
            raise RuntimeError("staged route artifact failed reload verification")
        report["artifact"] = {
            "status": "written",
            "path": str(model_path.resolve()),
            "sha256": artifact_digest,
        }
        report_bytes = _encode_report(report)
        staged_report = staged / report_path.name
        staged_report.write_bytes(report_bytes)
        _fsync_file(staged_report)
        if (
            hashlib.sha256(staged_report.read_bytes()).hexdigest()
            != hashlib.sha256(report_bytes).hexdigest()
            or json.loads(staged_report.read_bytes()) != report
        ):
            raise RuntimeError("staged route report failed digest verification")
        if _capture_source(root) != expected_source:
            raise SystemExit("route trainer source changed before publication")
        os.rename(staged, final)
        return artifact_digest, hashlib.sha256(report_bytes).hexdigest()
    except BaseException:
        shutil.rmtree(staged, ignore_errors=True)
        raise


def _publish_directory_bundle(
    final: Path,
    files: dict[str, bytes],
    root: Path,
    expected_source: _Source,
) -> dict[str, str]:
    final = final.resolve()
    if final.exists():
        raise SystemExit("refusing to overwrite existing route output bundle")
    final.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(
        tempfile.mkdtemp(prefix=f".{final.name}.", suffix=".tmp", dir=final.parent)
    )
    try:
        for name, value in files.items():
            path = staged / name
            path.write_bytes(value)
            _fsync_file(path)
        if _capture_source(root) != expected_source:
            raise SystemExit("route trainer source changed before publication")
        digests = {
            name: hashlib.sha256((staged / name).read_bytes()).hexdigest()
            for name in files
        }
        os.rename(staged, final)
        return digests
    except BaseException:
        shutil.rmtree(staged, ignore_errors=True)
        raise


def _encode_report(report: dict[str, object]) -> bytes:
    return (json.dumps(report, sort_keys=True, allow_nan=False) + "\n").encode()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _print_result(report: dict[str, object], path: Path) -> None:
    print(
        json.dumps(
            {
                "status": report["status"],
                "rejection_reason": report["rejection_reason"],
                "report_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            },
            sort_keys=True,
            allow_nan=False,
        )
    )


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _DIGEST_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_revision(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _REVISION_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--collection-report", type=Path, required=True)
    parser.add_argument("--collection-preregistration-json", type=Path, required=True)
    parser.add_argument("--learner-preregistration-json", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, required=True)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--epochs", type=int, default=OPTIMIZER_CONFIG["epochs"])
    parser.add_argument(
        "--training-seed", type=int, default=OPTIMIZER_CONFIG["training_seed"]
    )
    parser.add_argument(
        "--learning-rate", type=float, default=OPTIMIZER_CONFIG["learning_rate"]
    )
    parser.add_argument(
        "--weight-decay", type=float, default=OPTIMIZER_CONFIG["weight_decay"]
    )
    parser.add_argument(
        "--max-gradient-norm",
        type=float,
        default=OPTIMIZER_CONFIG["max_gradient_norm"],
    )
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--hidden-size", type=int, default=MODEL_CONFIG["hidden_size"])
    parser.add_argument(
        "--attention-heads", type=int, default=MODEL_CONFIG["attention_heads"]
    )
    parser.add_argument(
        "--attention-layers", type=int, default=MODEL_CONFIG["attention_layers"]
    )
    parser.add_argument(
        "--feedforward-size", type=int, default=MODEL_CONFIG["feedforward_size"]
    )
    parser.add_argument(
        "--max-entities", type=int, default=MODEL_CONFIG["max_entities"]
    )
    parser.add_argument("--max-actions", type=int, default=MODEL_CONFIG["max_actions"])
    return parser


if __name__ == "__main__":
    main()
