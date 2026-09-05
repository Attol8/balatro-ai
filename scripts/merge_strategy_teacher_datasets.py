#!/usr/bin/env python3
"""Merge immutable dense-teacher batches without weakening their provenance."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.strategy_teacher import (
    StrategyTargetEndpoint,
    StrategyTeacherRecord,
    read_teacher_records,
    write_teacher_records,
)


_BATCH_STARTS = tuple(range(1375, 1675, 50))
_BATCH_SIZE = 50
_EXPECTED_SEEDS = set(range(1375, 1675))
_EXPECTED_BUDGET = {
    "samples": 6,
    "horizon_antes": 1,
    "max_steps": 200,
    "override_z": 1.0,
}


def main() -> None:
    args = build_parser().parse_args()
    for path in (args.output_jsonl, args.output_report):
        if path.exists():
            raise SystemExit(f"refusing to overwrite existing output: {path}")
    components = tuple(
        _load_component(Path(dataset), Path(report)) for dataset, report in args.input
    )
    _validate_components(components)
    records = tuple(record for component in components for record in component[2])
    report = _merged_report(components, records, args.output_jsonl)
    dataset_digest = write_teacher_records(args.output_jsonl, records)
    report["strategy_teacher_dataset"]["sha256"] = dataset_digest
    try:
        _publish_json_exclusive(
            args.output_report,
            json.dumps(report, sort_keys=True, allow_nan=False) + "\n",
        )
    except BaseException:
        args.output_jsonl.unlink(missing_ok=True)
        raise
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


def _load_component(
    dataset_path: Path,
    report_path: Path,
) -> tuple[Path, dict[str, object], tuple[StrategyTeacherRecord, ...], str]:
    try:
        dataset_digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
        report_bytes = report_path.read_bytes()
        report = json.loads(report_bytes)
        records = read_teacher_records(dataset_path)
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
        report_path,
        report,
        records,
        hashlib.sha256(report_bytes).hexdigest(),
    )


def _validate_components(components) -> None:
    if len(components) != len(_BATCH_STARTS):
        raise SystemExit("merge requires exactly six immutable teacher batches")
    first = components[0][1]
    first_binding = first.get("contextual_teacher_preregistration")
    if not isinstance(first_binding, dict) or not isinstance(
        first_binding.get("sha256"), str
    ):
        raise SystemExit("teacher component lacks contextual preregistration")
    try:
        fixed = _fixed_protocol(first, first_binding)
    except (KeyError, TypeError) as exc:
        raise SystemExit("teacher component protocol is incomplete") from exc
    seeds: set[int] = set()
    groups: set[str] = set()
    batch_ids: set[str] = set()
    for path, report, records, _ in components:
        binding = report.get("contextual_teacher_preregistration")
        panel = report["benchmark_protocol"].get("panel_registry")
        search = report["search_protocol"]
        manifest = report["manifest"]
        if (
            not isinstance(binding, dict)
            or binding.get("protocol_id") != "contextual-continuation-development-v2"
            or binding.get("immutable_batches") is not True
            or not isinstance(binding.get("batch_id"), str)
            or not isinstance(panel, dict)
            or panel.get("verification") != "registry_verified"
            or panel.get("count") != _BATCH_SIZE
            or search.get("version") != "determinized-search-v10"
            or search.get("budget") != _EXPECTED_BUDGET
            or search.get("nonce") != "contextual-continuation-v10-frozen"
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
        if (
            seed_start not in _BATCH_STARTS
            or binding.get("seeds") != _BATCH_SIZE
            or component_seeds != set(range(seed_start, seed_start + _BATCH_SIZE))
            or len(component_groups) != _BATCH_SIZE
            or sum(bool(row["won"]) for row in report["results"])
            != len({record.run_group for record in records if record.run_won})
        ):
            raise SystemExit(f"teacher component has the wrong batch panel: {path}")
        if seeds & component_seeds or groups & component_groups:
            raise SystemExit("teacher components overlap seeds or origin families")
        if binding["batch_id"] in batch_ids:
            raise SystemExit("teacher components repeat a preregistered batch")
        seeds.update(component_seeds)
        groups.update(component_groups)
        batch_ids.add(binding["batch_id"])
    if seeds != _EXPECTED_SEEDS:
        raise SystemExit("teacher components do not cover the frozen seed union")


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
    report = copy.deepcopy(components[0][1])
    results = sorted(
        (row for _, component, _, _ in components for row in component["results"]),
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
        for path, component, _, report_digest in components
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
        "protocol_id": "contextual-continuation-development-v2",
        "sha256": components[0][1]["contextual_teacher_preregistration"]["sha256"],
        "immutable_batches": True,
        "batch_ids": sorted(
            component["contextual_teacher_preregistration"]["batch_id"]
            for _, component, _, _ in components
        ),
    }
    source_manifest = components[0][1]["manifest"]
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
    return parser


if __name__ == "__main__":
    main()
