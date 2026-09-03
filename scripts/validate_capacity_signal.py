#!/usr/bin/env python3
"""Validate whether public capacity predicts the next boss beyond ante alone."""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from pathlib import Path
from typing import Any


class ValidationError(ValueError):
    """The input is not a complete, comparable capacity report."""


def validate_capacity_report(
    path: Path,
    *,
    minimum_coverage: float = 0.95,
    bootstrap_samples: int = 10_000,
    expected_seeds: tuple[int, ...] = tuple(range(1, 201)),
) -> dict[str, Any]:
    report = _load(path)
    _validate_protocol(report, expected_seeds)
    results = report.get("results")
    if not isinstance(results, list) or not results:
        raise ValidationError("report must contain non-empty results")
    seeds: list[int] = []
    rows_by_seed: dict[int, list[tuple[float, float, bool]]] = {}
    failures: Counter[str] = Counter()
    total = 0
    available = 0
    margin_available = 0
    model_versions: set[int] = set()
    sample_methods: set[str] = set()
    for index, result in enumerate(results):
        if not isinstance(result, dict) or result.get("complete") is not True:
            raise ValidationError(f"results[{index}] is incomplete or malformed")
        seed = result.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int) or seed in rows_by_seed:
            raise ValidationError(f"results[{index}] has an invalid or duplicate seed")
        seeds.append(seed)
        rows_by_seed[seed] = []
        diagnostics = result.get("capacity_decisions")
        if not isinstance(diagnostics, list):
            raise ValidationError(f"results[{index}] has no capacity diagnostics")
        for diagnostic in diagnostics:
            if not isinstance(diagnostic, dict) or diagnostic.get("phase") != "SHOP":
                continue
            total += 1
            if diagnostic.get("available") is not True:
                reason = diagnostic.get("unavailable_reason")
                failures[str(reason or "missing unavailable reason")] += 1
                continue
            available += 1
            if diagnostic.get("margin_available") is not True:
                reason = diagnostic.get("margin_unavailable_reason")
                failures[f"margin: {reason or 'missing unavailable reason'}"] += 1
                continue
            margin = diagnostic.get("log_margin")
            ante = diagnostic.get("ante")
            label = diagnostic.get("cleared_next_boss")
            version = diagnostic.get("model_version")
            method = diagnostic.get("sample_method")
            if (
                isinstance(margin, bool)
                or not isinstance(margin, int | float)
                or not math.isfinite(margin)
                or isinstance(ante, bool)
                or not isinstance(ante, int)
                or not isinstance(label, bool)
                or isinstance(version, bool)
                or not isinstance(version, int)
                or not isinstance(method, str)
                or not method
            ):
                raise ValidationError(f"results[{index}] has a malformed available capacity row")
            margin_available += 1
            model_versions.add(version)
            sample_methods.add(method)
            # Later antes are harder, so orient the baseline such that larger
            # scores predict success, matching the capacity-score convention.
            rows_by_seed[seed].append((float(margin), float(-ante), label))
    if total == 0:
        raise ValidationError("report contains no shop capacity decisions")
    if len(model_versions) > 1:
        raise ValidationError("report mixes capacity model versions")

    rows = [row for seed_rows in rows_by_seed.values() for row in seed_rows]
    capacity_auc = _roc_auc([(row[0], row[2]) for row in rows])
    ante_auc = _roc_auc([(row[1], row[2]) for row in rows])
    per_seed_auc = {
        str(seed): {
            "capacity_auc": _roc_auc([(row[0], row[2]) for row in rows_by_seed[seed]]),
            "ante_auc": _roc_auc([(row[1], row[2]) for row in rows_by_seed[seed]]),
        }
        for seed in seeds
    }
    deltas = _cluster_bootstrap_deltas(
        seeds,
        rows_by_seed,
        samples=bootstrap_samples,
    )
    interval = (
        (deltas[int(0.025 * len(deltas))], deltas[min(len(deltas) - 1, int(0.975 * len(deltas)))])
        if deltas
        else (None, None)
    )
    coverage = available / total
    margin_coverage = margin_available / total
    passed = bool(
        coverage >= minimum_coverage
        and margin_coverage >= minimum_coverage
        and capacity_auc is not None
        and ante_auc is not None
        and interval[0] is not None
        and interval[0] > 0
    )
    return {
        "report": str(path),
        "source_digest": report["manifest"]["source_digest"],
        "runs": len(results),
        "shop_rows": total,
        "available_shop_rows": available,
        "coverage": coverage,
        "margin_available_shop_rows": margin_available,
        "margin_coverage": margin_coverage,
        "minimum_coverage": minimum_coverage,
        "failure_counts": dict(sorted(failures.items())),
        "capacity_model_versions": sorted(model_versions),
        "sample_methods": sorted(sample_methods),
        "capacity_auc": capacity_auc,
        "ante_auc": ante_auc,
        "per_seed_auc": per_seed_auc,
        "undefined_per_seed_auc": sum(
            value["capacity_auc"] is None or value["ante_auc"] is None
            for value in per_seed_auc.values()
        ),
        "auc_delta": (
            capacity_auc - ante_auc
            if capacity_auc is not None and ante_auc is not None
            else None
        ),
        "paired_seed_bootstrap_95": {
            "lower": interval[0],
            "upper": interval[1],
            "valid_samples": len(deltas),
            "requested_samples": bootstrap_samples,
            "seed": 0,
        },
        "passed": passed,
    }


def _roc_auc(rows: list[tuple[float, bool]]) -> float | None:
    positives = sum(label for _, label in rows)
    negatives = len(rows) - positives
    if not positives or not negatives:
        return None
    grouped: dict[float, list[int]] = {}
    for score, label in rows:
        counts = grouped.setdefault(score, [0, 0])
        counts[int(label)] += 1
    negative_below = 0
    wins = 0.0
    for score in sorted(grouped):
        negative_count, positive_count = grouped[score]
        wins += positive_count * (negative_below + 0.5 * negative_count)
        negative_below += negative_count
    return wins / (positives * negatives)


def _cluster_bootstrap_deltas(
    seeds: list[int],
    rows_by_seed: dict[int, list[tuple[float, float, bool]]],
    *,
    samples: int,
) -> list[float]:
    rng = random.Random(0)
    deltas: list[float] = []
    for _ in range(samples):
        drawn = [seeds[rng.randrange(len(seeds))] for _ in seeds]
        rows = [row for seed in drawn for row in rows_by_seed[seed]]
        capacity_auc = _roc_auc([(row[0], row[2]) for row in rows])
        ante_auc = _roc_auc([(row[1], row[2]) for row in rows])
        if capacity_auc is not None and ante_auc is not None:
            deltas.append(capacity_auc - ante_auc)
    return sorted(deltas)


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("candidate_only") is not True:
        raise ValidationError("input is not a candidate-only evaluator report")
    manifest = value.get("manifest")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("source_digest"), str):
        raise ValidationError("report has no source digest")
    return value


def _validate_protocol(report: dict[str, Any], expected_seeds: tuple[int, ...]) -> None:
    manifest = report["manifest"]
    run = manifest.get("run")
    backend = manifest.get("backend")
    protocol = report.get("capacity_protocol")
    expected_seed_spec = f"{expected_seeds[0]}:{len(expected_seeds)}" if expected_seeds else ""
    if (
        not isinstance(run, dict)
        or run.get("deck") != "RED"
        or run.get("stake") != "WHITE"
        or run.get("seed") != expected_seed_spec
        or manifest.get("max_antes_cleared") != 20
        or manifest.get("max_decisions") != 1200
        or manifest.get("launch_fast") is not False
        or manifest.get("launch_headless") is not False
        or not isinstance(backend, dict)
        or backend.get("backend_name") != "Jackdaw"
    ):
        raise ValidationError("report does not match the Red White capacity panel protocol")
    if protocol != {
        "model_version": 2,
        "samples": 32,
        "sample_method": "public-digest-monte-carlo-without-replacement-v1",
        "phases": ["BLIND_SELECT", "PACK", "SHOP"],
        "validation_phase": "SHOP",
        "label": "cleared_next_boss",
    }:
        raise ValidationError("report has an unknown capacity diagnostic protocol")
    results = report.get("results")
    if isinstance(results, list):
        actual_seeds = tuple(result.get("seed") for result in results if isinstance(result, dict))
        if actual_seeds != expected_seeds:
            raise ValidationError("report seed panel is incomplete or out of order")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--minimum-coverage", type=float, default=0.95)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not 0 <= args.minimum_coverage <= 1 or args.bootstrap_samples <= 0:
        raise SystemExit("coverage must be in [0,1] and bootstrap samples positive")
    payload = validate_capacity_report(
        args.report,
        minimum_coverage=args.minimum_coverage,
        bootstrap_samples=args.bootstrap_samples,
    )
    print(json.dumps(payload, sort_keys=True))
    if not payload["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
