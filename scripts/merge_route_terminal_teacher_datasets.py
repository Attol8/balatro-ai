#!/usr/bin/env python3
"""Merge immutable route-terminal teacher batches without weakening provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.balatrobot.tracing import source_snapshot
from balatro_ai_v2.route_teacher import (
    RouteTeacherValidationError,
    route_teacher_coverage_gate_failures,
    route_terminal_teacher_coverage,
    validate_route_teacher_component,
)
from balatro_ai_v2.route_teacher_protocol import (
    ROUTE_TEACHER_BATCHES,
    ROUTE_TEACHER_BATCH_SIZE,
    ROUTE_TEACHER_ORIGIN_KEY,
    ROUTE_TEACHER_PREREGISTRATION,
    ROUTE_TEACHER_PROTOCOL_ID,
    ROUTE_TEACHER_SEARCH,
    ROUTE_TEACHER_TERMINAL,
)
from balatro_ai_v2.strategy_model import PublicStrategyTensorizer, StrategyModelConfig
from balatro_ai_v2.strategy_teacher import (
    STRATEGY_TEACHER_SCHEMA_VERSION,
    teacher_records_from_bytes,
    write_teacher_records,
)


def main() -> None:
    args = build_parser().parse_args()
    root = args.repository_root.resolve()
    merger_source = _capture_merger_source(root)
    if args.output_jsonl.resolve() == args.output_report.resolve():
        raise SystemExit("merged dataset and report paths must be distinct")
    if args.output_jsonl.parent.resolve() != args.output_report.parent.resolve():
        raise SystemExit("merged outputs must share one bundle directory")
    if args.output_jsonl.exists() or args.output_report.exists():
        raise SystemExit("refusing to overwrite existing output")
    spec, prereg_digest, key = _load_preregistration(
        args.preregistration_json, args.origin_key_file, root
    )
    components = _canonical_components(
        _load_component(Path(dataset), Path(report)) for dataset, report in args.input
    )
    _validate_components(components, spec, prereg_digest, key, root)
    _validate_merger_ancestry(
        root,
        str(components[0][2]["manifest"]["repository_revision"]),
        str(merger_source["repository_revision"]),
    )
    records = tuple(record for component in components for record in component[3])
    _tensorization_preflight(records, spec)
    coverage = route_terminal_teacher_coverage(records)
    failures = route_teacher_coverage_gate_failures(
        coverage,
        spec["coverage_gate"],
        source_runs=len(
            {int(row["seed"]) for c in components for row in c[2]["results"]}
        ),
    )
    if failures:
        raise SystemExit("route teacher coverage gate failed: " + ",".join(failures))
    report = _merged_report(components, records, coverage, prereg_digest, merger_source)
    _publish_bundle(
        args.output_jsonl,
        args.output_report,
        records,
        report,
        root,
        merger_source,
    )
    print(
        json.dumps(
            {"records": len(records), "groups": len({r.run_group for r in records})},
            sort_keys=True,
        )
    )


def _load_preregistration(path: Path, key_path: Path, root: Path):
    expected = (root / ROUTE_TEACHER_PREREGISTRATION).resolve()
    if (
        path.resolve() != expected
        or key_path.resolve() != (root / ROUTE_TEACHER_ORIGIN_KEY).resolve()
    ):
        raise SystemExit("route-terminal preregistration or key path is not frozen")
    try:
        raw = path.read_bytes()
        spec = json.loads(raw)
        key = key_path.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid route-terminal preregistration: {exc}") from exc
    if not isinstance(spec, dict) or len(key) != 32:
        raise SystemExit("invalid route-terminal provenance")
    origin = spec.get("origin_mapping")
    if (
        spec.get("protocol_id") != ROUTE_TEACHER_PROTOCOL_ID
        or spec.get("status") != "reserved"
        or spec.get("immutable_batches") is not True
        or spec.get("collection_only") is not True
        or spec.get("training_authorized") is not False
        or spec.get("schema_version") != STRATEGY_TEACHER_SCHEMA_VERSION
        or spec.get("search") != ROUTE_TEACHER_SEARCH
        or spec.get("terminal_teacher") != ROUTE_TEACHER_TERMINAL
        or spec.get("batches") != list(ROUTE_TEACHER_BATCHES)
        or not isinstance(origin, dict)
        or origin.get("key_path") != ROUTE_TEACHER_ORIGIN_KEY
        or origin.get("key_sha256") != hashlib.sha256(key).hexdigest()
    ):
        raise SystemExit("route-terminal preregistration changed the frozen protocol")
    return spec, hashlib.sha256(raw).hexdigest(), key


def _load_component(dataset: Path, report_path: Path):
    try:
        dataset_bytes = dataset.read_bytes()
        report_bytes = report_path.read_bytes()
        report = json.loads(report_bytes)
        records = teacher_records_from_bytes(dataset_bytes)
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise SystemExit(f"invalid route teacher component: {dataset}") from exc
    teacher = (
        report.get("strategy_teacher_dataset") if isinstance(report, dict) else None
    )
    if (
        not isinstance(report, dict)
        or not isinstance(teacher, dict)
        or teacher.get("mode") != "route_terminal_paired_utility"
        or teacher.get("schema_version") != STRATEGY_TEACHER_SCHEMA_VERSION
        or teacher.get("status") != "written"
        or teacher.get("contains_game_seeds") is not False
        or teacher.get("complete_runs_only") is not True
        or teacher.get("sha256") != hashlib.sha256(dataset_bytes).hexdigest()
        or teacher.get("records") != len(records)
        or teacher.get("groups") != len({r.run_group for r in records})
        or not isinstance(teacher.get("teacher_config_digest"), str)
        or {r.teacher_config_digest for r in records}
        != {teacher["teacher_config_digest"]}
        or not isinstance(report.get("results"), list)
    ):
        raise SystemExit(f"route teacher component is not merge-eligible: {dataset}")
    return (
        dataset,
        report_path,
        report,
        records,
        hashlib.sha256(report_bytes).hexdigest(),
    )


def _canonical_components(components):
    order = {
        batch["batch_id"]: index for index, batch in enumerate(ROUTE_TEACHER_BATCHES)
    }
    loaded = tuple(components)
    try:
        return tuple(
            sorted(
                loaded,
                key=lambda component: order[
                    component[2]["route_terminal_teacher_preregistration"]["batch_id"]
                ],
            )
        )
    except (KeyError, TypeError) as exc:
        raise SystemExit("route component batch binding is invalid") from exc


def _validate_components(
    components, spec, prereg_digest: str, key: bytes, root: Path
) -> None:
    if len(components) != len(ROUTE_TEACHER_BATCHES):
        raise SystemExit("merge requires exactly five route-terminal batches")
    seeds: set[int] = set()
    groups: set[str] = set()
    batch_ids: set[str] = set()
    fixed = None
    for dataset, report_path, report, records, _ in components:
        binding = report.get("route_terminal_teacher_preregistration")
        if (
            not isinstance(binding, dict)
            or binding.get("protocol_id") != ROUTE_TEACHER_PROTOCOL_ID
            or binding.get("sha256") != prereg_digest
            or binding.get("immutable_batches") is not True
            or binding.get("collection_only") is not True
            or binding.get("training_authorized") is not False
        ):
            raise SystemExit(f"route component lacks distinct binding: {dataset}")
        batch = next(
            (
                b
                for b in ROUTE_TEACHER_BATCHES
                if b["batch_id"] == binding.get("batch_id")
            ),
            None,
        )
        if (
            batch is None
            or binding.get("seed_start") != batch["seed_start"]
            or binding.get("seeds") != ROUTE_TEACHER_BATCH_SIZE
        ):
            raise SystemExit(f"route component batch mismatch: {dataset}")
        if (
            dataset.resolve() != (root / str(batch["teacher_jsonl"])).resolve()
            or report_path.resolve() != (root / str(batch["report_json"])).resolve()
        ):
            raise SystemExit(f"route component path mismatch: {dataset}")
        manifest = report.get("manifest")
        if (
            not isinstance(manifest, dict)
            or manifest.get("repository_dirty") is not False
        ):
            raise SystemExit(f"route component manifest is dirty: {dataset}")
        current_fixed = (
            report.get("search_protocol"),
            report.get("strategy_tuning"),
            report.get("candidate_runtime"),
            manifest.get("source_digest"),
            manifest.get("backend"),
            manifest.get("repository_revision"),
            report["strategy_teacher_dataset"]["teacher_config_digest"],
        )
        search_protocol = report.get("search_protocol")
        success_protocol = (
            search_protocol.get("success_teacher")
            if isinstance(search_protocol, dict)
            else None
        )
        if (
            not isinstance(search_protocol, dict)
            or search_protocol.get("version") != "determinized-search-v16"
            or search_protocol.get("continuation") != "PublicStrategicPolicy"
            or not isinstance(search_protocol.get("budget"), dict)
            or any(
                search_protocol["budget"].get(k) != ROUTE_TEACHER_SEARCH[k]
                for k in ("samples", "horizon_antes", "max_steps", "override_z")
            )
            or search_protocol.get("policy_seed") != ROUTE_TEACHER_SEARCH["policy_seed"]
            or search_protocol.get("nonce") != ROUTE_TEACHER_SEARCH["nonce"]
            or search_protocol.get("strategy_options") is not True
            or search_protocol.get("include_reorders") is not False
            or search_protocol.get("phases") != ["BLIND_SELECT", "PACK", "SHOP"]
            or not isinstance(success_protocol, dict)
            or success_protocol.get("enabled") is not True
            or success_protocol.get("mode") != "collect"
            or success_protocol.get("emits_teacher_rows") is not True
            or success_protocol.get("terminal_action_budget") is not None
            or success_protocol.get("terminal_action_selector") is not None
            or success_protocol.get("root_builder") != "determinized-search-v16"
            or success_protocol.get("sample_nonce_stream")
            != f"{search_protocol['nonce']}:success-terminal-v1"
            or any(
                success_protocol.get(k) != v
                for k, v in ROUTE_TEACHER_TERMINAL.items()
                if k != "affects_actions"
            )
            or success_protocol.get("affects_actions") is not False
            or report.get("candidate_runtime") != spec.get("candidate_runtime")
            or report.get("strategy_tuning") != spec.get("strategy_tuning")
            or manifest.get("backend") != spec.get("backend")
            or manifest.get("source_digest") != spec.get("expected_source_digest")
            or manifest.get("max_decisions") != 1200
            or manifest.get("max_antes_cleared") != 20
            or manifest.get("profile_mode") != "all_unlocked"
            or manifest.get("run", {}).get("deck") != "RED"
            or manifest.get("run", {}).get("stake") != "WHITE"
            or manifest.get("run", {}).get("seed")
            != f"{binding.get('seed_start')}:{ROUTE_TEACHER_BATCH_SIZE}"
        ):
            raise SystemExit(f"route component violates frozen protocol: {dataset}")
        if fixed is None:
            fixed = current_fixed
        elif current_fixed != fixed:
            raise SystemExit(f"route component configuration mismatch: {dataset}")
        try:
            validate_route_teacher_component(
                tuple(records),
                report["results"],
                origin_key=key,
                expected_seed_start=int(batch["seed_start"]),
                expected_seed_count=ROUTE_TEACHER_BATCH_SIZE,
                sample_count=int(ROUTE_TEACHER_TERMINAL["samples"]),
            )
        except RouteTeacherValidationError as exc:
            raise SystemExit(
                f"route component record validation failed: {dataset}: {exc}"
            ) from exc
        component_seeds = {int(row["seed"]) for row in report["results"]}
        if (
            seeds & component_seeds
            or groups & {r.run_group for r in records}
            or binding["batch_id"] in batch_ids
        ):
            raise SystemExit("route components overlap seeds, groups, or batches")
        seeds.update(component_seeds)
        groups.update(r.run_group for r in records)
        batch_ids.add(binding["batch_id"])
    expected = set(
        range(
            ROUTE_TEACHER_BATCHES[0]["seed_start"],
            ROUTE_TEACHER_BATCHES[-1]["seed_start"] + ROUTE_TEACHER_BATCH_SIZE,
        )
    )
    if seeds != expected or batch_ids != {b["batch_id"] for b in ROUTE_TEACHER_BATCHES}:
        raise SystemExit("route components do not cover the frozen seed union")
    _validate_source_freeze(fixed, spec, root)


def _validate_source_freeze(fixed, spec, root: Path) -> None:
    if fixed[3] != spec.get("expected_source_digest"):
        raise SystemExit("route component source freeze mismatch")
    implementation_revision = spec.get("implementation_revision")
    if (
        not isinstance(implementation_revision, str)
        or len(implementation_revision) != 40
    ):
        raise SystemExit("route preregistration implementation revision is invalid")
    try:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", implementation_revision, fixed[5]],
            cwd=root,
            check=True,
            capture_output=True,
        )
        changed = subprocess.run(
            ["git", "diff", "--name-only", implementation_revision, fixed[5]],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("cannot verify route collection ancestry") from exc
    if set(changed) != {ROUTE_TEACHER_PREREGISTRATION}:
        raise SystemExit("route collection revision changed implementation source")


def _capture_merger_source(root: Path) -> dict[str, object]:
    revision, dirty, digest = source_snapshot(root)
    if dirty:
        raise SystemExit("route merger checkout is dirty")
    return {
        "repository_revision": revision,
        "repository_dirty": False,
        "source_digest": digest,
    }


def _validate_merger_ancestry(
    root: Path, collection_revision: str, merger_revision: str
) -> None:
    try:
        subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                collection_revision,
                merger_revision,
            ],
            cwd=root,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(
            "route merger does not descend from the collection source"
        ) from exc


def _tensorization_preflight(records, spec) -> None:
    runtime = spec["training"] if isinstance(spec.get("training"), dict) else {}
    config = StrategyModelConfig(
        hidden_size=int(runtime.get("hidden_size", 64)),
        attention_heads=int(runtime.get("attention_heads", 4)),
        attention_layers=int(runtime.get("attention_layers", 2)),
        feedforward_size=int(runtime.get("feedforward_size", 128)),
        max_entities=int(runtime.get("max_entities", 256)),
        max_actions=int(runtime.get("max_actions", 512)),
    )
    tensorizer = PublicStrategyTensorizer(config)
    for offset in range(0, len(records), 32):
        chunk = records[offset : offset + 32]
        batch = tensorizer.tensorize(
            tuple(r.observation for r in chunk),
            tuple(tuple(c.action for c in r.candidates) for r in chunk),
            tuple(tuple(c.intent for c in r.candidates) for r in chunk),
            tuple(r.context for r in chunk),
            tuple(tuple(c.route for c in r.candidates) for r in chunk),
        )
        batch.validate()


def _merged_report(components, records, coverage, prereg_digest, merger_source):
    base = json.loads(json.dumps(components[0][2]))
    base.pop("results", None)
    base["summary"] = {
        "runs": len(ROUTE_TEACHER_BATCHES) * ROUTE_TEACHER_BATCH_SIZE,
        "complete": True,
        "merged_component_reports": len(components),
    }
    merged_components = []
    for component in components:
        opaque_groups = sorted({record.run_group for record in component[3]})
        merged_components.append(
            {
                "batch_id": component[2]["route_terminal_teacher_preregistration"][
                    "batch_id"
                ],
                "report_sha256": component[4],
                "dataset_sha256": component[2]["strategy_teacher_dataset"]["sha256"],
                "opaque_group_sha256": hashlib.sha256(
                    "\n".join(opaque_groups).encode()
                ).hexdigest(),
                "opaque_groups": opaque_groups,
            }
        )
    base["merged_components"] = merged_components
    base["strategy_teacher_dataset"].update(
        {
            "path": None,
            "sha256": None,
            "records": len(records),
            "groups": len({r.run_group for r in records}),
            "coverage": {"route_terminal_paired_utility": coverage},
        }
    )
    base["route_terminal_teacher_preregistration"] = {
        "protocol_id": ROUTE_TEACHER_PROTOCOL_ID,
        "sha256": prereg_digest,
        "immutable_batches": True,
        "batch_ids": sorted(c["batch_id"] for c in base["merged_components"]),
        "collection_only": True,
        "training_authorized": False,
    }
    base["collection_summary"] = {
        "complete_groups": len({r.run_group for r in records}),
        "rejected_or_censored": 0,
        "training_authorized": False,
    }
    base["manifest"] = {
        "kind": "route_terminal_teacher_merge_v1",
        "source_digest": components[0][2]["manifest"]["source_digest"],
        "repository_revision": components[0][2]["manifest"]["repository_revision"],
        "repository_dirty": False,
        "backend": components[0][2]["manifest"]["backend"],
        "component_count": len(components),
        "merger_source": merger_source,
    }
    return base


def _publish_bundle(
    dataset: Path, report: Path, records, payload, root: Path, merger_source
) -> None:
    if dataset.resolve() == report.resolve():
        raise SystemExit("merged dataset and report paths must be distinct")
    final = dataset.parent.resolve()
    if final.exists():
        raise SystemExit(f"refusing to overwrite existing bundle: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(
        tempfile.mkdtemp(prefix=f".{final.name}.", suffix=".tmp", dir=final.parent)
    )
    try:
        digest = write_teacher_records(staged / dataset.name, records)
        payload["strategy_teacher_dataset"]["sha256"] = digest
        (staged / report.name).write_text(
            json.dumps(payload, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        current = _capture_merger_source(root)
        if current != merger_source:
            raise SystemExit("route merger source changed before bundle publication")
        os.rename(staged, final)
    except BaseException:
        for path in staged.iterdir():
            path.unlink(missing_ok=True)
        staged.rmdir()
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        nargs=2,
        action="append",
        required=True,
        metavar=("DATASET_JSONL", "COLLECTION_REPORT"),
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
