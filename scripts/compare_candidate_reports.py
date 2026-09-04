#!/usr/bin/env python3
"""Compare two paired reports produced by ``evaluate_candidate_baselines``."""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.evaluation_protocol import (
    PanelValidationError,
    SeedPanelValidation,
    validate_seed_panel,
)


class ReportError(ValueError):
    """A report is malformed or cannot be compared fairly."""


_MANIFEST_FIELDS = (
    "canonical_schema_version",
    "trace_schema_version",
    "max_decisions",
    "max_antes_cleared",
    "max_settle_polls",
    "wall_clock_limit_seconds",
    "profile_mode",
    "launch_fast",
    "launch_headless",
)


def compare_reports(baseline_path: Path, candidate_path: Path) -> dict[str, Any]:
    baseline = _load(baseline_path)
    candidate = _load(candidate_path)
    _check_compatible(baseline, candidate)
    ante_cap = baseline["manifest"]["max_antes_cleared"]
    baseline_results = _results(baseline, baseline_path, ante_cap=ante_cap)
    candidate_results = _results(candidate, candidate_path, ante_cap=ante_cap)
    baseline_seeds = [row["seed"] for row in baseline_results]
    candidate_seeds = [row["seed"] for row in candidate_results]
    if baseline_seeds != candidate_seeds:
        raise ReportError("reports do not have identical ordered seed panels")
    baseline_panel = _validate_report_seed_panel(
        baseline, baseline_results, baseline_path
    )
    _validate_report_seed_panel(candidate, candidate_results, candidate_path)

    rows: list[dict[str, Any]] = []
    counts = {
        "baseline_only_wins": 0,
        "candidate_only_wins": 0,
        "both_wins": 0,
        "both_losses": 0,
    }
    survival_deltas: list[int] = []
    ante_deltas: list[int] = []
    log_score_deltas: list[float] = []
    score_metrics_available = all(
        "best_hand_score" in left and "best_hand_score" in right
        for left, right in zip(baseline_results, candidate_results)
    )
    for left, right in zip(baseline_results, candidate_results):
        baseline_win = _win(left)
        candidate_win = _win(right)
        baseline_survival = _survived(left)
        candidate_survival = _survived(right)
        survival_deltas.append(int(candidate_survival) - int(baseline_survival))
        baseline_antes = _antes_cleared(left)
        candidate_antes = _antes_cleared(right)
        ante_deltas.append(candidate_antes - baseline_antes)
        baseline_score = _best_hand_score(left) if score_metrics_available else None
        candidate_score = _best_hand_score(right) if score_metrics_available else None
        baseline_log_score = (
            math.log10(max(1, baseline_score)) if baseline_score is not None else None
        )
        candidate_log_score = (
            math.log10(max(1, candidate_score)) if candidate_score is not None else None
        )
        if baseline_log_score is not None and candidate_log_score is not None:
            log_score_deltas.append(candidate_log_score - baseline_log_score)
        if baseline_win and candidate_win:
            outcome = "both_win"
            counts["both_wins"] += 1
        elif baseline_win:
            outcome = "baseline_only_win"
            counts["baseline_only_wins"] += 1
        elif candidate_win:
            outcome = "candidate_only_win"
            counts["candidate_only_wins"] += 1
        else:
            outcome = "both_loss"
            counts["both_losses"] += 1
        rows.append(
            {
                "seed": left["seed"],
                "baseline_complete": left["complete"],
                "baseline_terminal_reason": left["terminal_reason"],
                "baseline_win": baseline_win,
                "baseline_antes_cleared": baseline_antes,
                "baseline_survived_to_ante_6": baseline_survival,
                "candidate_complete": right["complete"],
                "candidate_terminal_reason": right["terminal_reason"],
                "candidate_win": candidate_win,
                "candidate_antes_cleared": candidate_antes,
                "candidate_survived_to_ante_6": candidate_survival,
                "antes_cleared_delta": candidate_antes - baseline_antes,
                "baseline_best_hand_score": baseline_score,
                "candidate_best_hand_score": candidate_score,
                "log10_best_hand_score_delta": (
                    candidate_log_score - baseline_log_score
                    if candidate_log_score is not None and baseline_log_score is not None
                    else None
                ),
                "outcome": outcome,
            }
        )
    survival_interval = _bootstrap_mean_interval(survival_deltas)
    ante_interval = _bootstrap_mean_interval(ante_deltas)
    log_score_interval = (
        _bootstrap_mean_interval(log_score_deltas) if log_score_deltas else None
    )
    baseline_survivals = sum(_survived(row) for row in baseline_results)
    candidate_survivals = sum(_survived(row) for row in candidate_results)
    baseline_wins = sum(row["baseline_win"] for row in rows)
    candidate_wins = sum(row["candidate_win"] for row in rows)
    baseline_mean_antes = sum(_antes_cleared(row) for row in baseline_results) / len(rows)
    candidate_mean_antes = sum(_antes_cleared(row) for row in candidate_results) / len(rows)
    baseline_mean_log_score = (
        sum(math.log10(max(1, _best_hand_score(row))) for row in baseline_results) / len(rows)
        if score_metrics_available
        else None
    )
    candidate_mean_log_score = (
        sum(math.log10(max(1, _best_hand_score(row))) for row in candidate_results) / len(rows)
        if score_metrics_available
        else None
    )
    return {
        "baseline": str(baseline_path),
        "candidate": str(candidate_path),
        "baseline_source_digest": baseline["manifest"]["source_digest"],
        "candidate_source_digest": candidate["manifest"]["source_digest"],
        "deck": baseline["manifest"]["run"]["deck"],
        "stake": baseline["manifest"]["run"]["stake"],
        "baseline_inference_budget": baseline["manifest"]["inference_budget"],
        "candidate_inference_budget": candidate["manifest"]["inference_budget"],
        "seed_panel": baseline_panel.as_dict(),
        "runs": len(rows),
        "baseline_mean_antes_cleared": baseline_mean_antes,
        "candidate_mean_antes_cleared": candidate_mean_antes,
        "paired_mean_antes_cleared_delta": candidate_mean_antes - baseline_mean_antes,
        "paired_antes_cleared_delta_bootstrap_95": {
            "lower": ante_interval[0],
            "upper": ante_interval[1],
            "samples": 10_000,
            "seed": 0,
        },
        "baseline_maximum_ante": max(int(row["ante"]) for row in baseline_results),
        "candidate_maximum_ante": max(int(row["ante"]) for row in candidate_results),
        "best_hand_score_metrics_available": score_metrics_available,
        "best_hand_score_pair_coverage": len(log_score_deltas),
        "baseline_mean_log10_best_hand_score": baseline_mean_log_score,
        "candidate_mean_log10_best_hand_score": candidate_mean_log_score,
        "paired_mean_log10_best_hand_score_delta": (
            candidate_mean_log_score - baseline_mean_log_score
            if candidate_mean_log_score is not None and baseline_mean_log_score is not None
            else None
        ),
        "paired_log10_best_hand_score_delta_bootstrap_95": (
            {
                "lower": log_score_interval[0],
                "upper": log_score_interval[1],
                "samples": 10_000,
                "seed": 0,
            }
            if log_score_interval is not None
            else None
        ),
        **counts,
        "baseline_wins": baseline_wins,
        "candidate_wins": candidate_wins,
        "baseline_win_rate": baseline_wins / len(rows),
        "candidate_win_rate": candidate_wins / len(rows),
        "paired_win_rate_delta": (candidate_wins - baseline_wins) / len(rows),
        "raw_win_delta": candidate_wins - baseline_wins,
        "baseline_survived_to_ante_6": baseline_survivals,
        "candidate_survived_to_ante_6": candidate_survivals,
        "baseline_survival_to_ante_6_rate": baseline_survivals / len(rows),
        "candidate_survival_to_ante_6_rate": candidate_survivals / len(rows),
        "paired_survival_rate_delta": (candidate_survivals - baseline_survivals) / len(rows),
        "paired_survival_delta_bootstrap_95": {
            "lower": survival_interval[0],
            "upper": survival_interval[1],
            "samples": 10_000,
            "seed": 0,
        },
        "paired": rows,
    }


def _load(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"cannot load report {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReportError(f"report {path} root must be an object")
    if value.get("candidate_only") is not True:
        raise ReportError(f"report {path} is not a candidate-only evaluator report")
    if not isinstance(value.get("manifest"), dict):
        raise ReportError(f"report {path} is missing an object manifest")
    return value


def _check_compatible(left: dict[str, Any], right: dict[str, Any]) -> None:
    left_manifest = left["manifest"]
    right_manifest = right["manifest"]
    for field in _MANIFEST_FIELDS:
        if field not in left_manifest or field not in right_manifest:
            raise ReportError(f"manifest is missing required comparison field: {field}")
        if left_manifest.get(field) != right_manifest.get(field):
            raise ReportError(f"incompatible manifest field: {field}")
    for label, manifest in (("baseline", left_manifest), ("candidate", right_manifest)):
        source_digest = manifest.get("source_digest")
        if not isinstance(source_digest, str) or not source_digest:
            raise ReportError(f"{label} manifest has no source digest")
    left_backend = left_manifest.get("backend")
    right_backend = right_manifest.get("backend")
    if not isinstance(left_backend, dict) or not isinstance(right_backend, dict):
        raise ReportError("manifest.backend must be an object in both reports")
    if left_backend != right_backend:
        raise ReportError("incompatible backend metadata")
    left_runtime = left.get("candidate_runtime")
    right_runtime = right.get("candidate_runtime")
    if not isinstance(left_runtime, dict) or not isinstance(right_runtime, dict):
        raise ReportError("candidate_runtime must be an object in both reports")
    if left_runtime != right_runtime:
        raise ReportError("incompatible candidate runtime")
    left_protocol = left.get("benchmark_protocol")
    right_protocol = right.get("benchmark_protocol")
    if not isinstance(left_protocol, dict) or not isinstance(right_protocol, dict):
        raise ReportError("benchmark_protocol must be an object in both reports")
    for field in (
        "category",
        "seed_provenance",
        "restart_selection",
        "filtered_seeds",
        "mods",
    ):
        if left_protocol.get(field) != right_protocol.get(field):
            raise ReportError(f"incompatible benchmark protocol field: {field}")
    for name in ("deck", "stake", "seed"):
        left_run = left_manifest.get("run")
        right_run = right_manifest.get("run")
        if not isinstance(left_run, dict) or not isinstance(right_run, dict):
            raise ReportError("manifest.run must be an object in both reports")
        if name not in left_run or name not in right_run:
            raise ReportError(f"manifest.run is missing required field: {name}")
        if left_run.get(name) != right_run.get(name):
            raise ReportError(f"incompatible run field: {name}")
    for manifest in (left_manifest, right_manifest):
        budget = manifest.get("inference_budget")
        if not isinstance(budget, str) or not budget:
            raise ReportError("manifest.inference_budget must be a non-empty string")


def _results(
    report: dict[str, Any], path: Path, *, ante_cap: int
) -> list[dict[str, Any]]:
    values = report.get("results")
    if not isinstance(values, list) or not values:
        raise ReportError(f"report {path} must contain a non-empty results array")
    result: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise ReportError(f"report {path} results[{index}] must be an object")
        for field in (
            "seed",
            "complete",
            "won",
            "antes_cleared",
            "survived_to_ante_6",
            "ante",
            "terminal_reason",
        ):
            if field not in value:
                raise ReportError(f"report {path} results[{index}] is missing {field}")
        seed = value["seed"]
        if isinstance(seed, bool) or not isinstance(seed, int) or seed in seen:
            raise ReportError(f"report {path} has invalid or duplicate seed at results[{index}]")
        if (
            not isinstance(value["complete"], bool)
            or not isinstance(value["won"], bool)
            or not isinstance(value["survived_to_ante_6"], bool)
        ):
            raise ReportError(
                f"report {path} results[{index}] has non-boolean completion/win/survival"
            )
        if not isinstance(value["terminal_reason"], str) or not value["terminal_reason"]:
            raise ReportError(f"report {path} results[{index}] has invalid terminal_reason")
        if value["won"] and not value["complete"]:
            raise ReportError(f"report {path} results[{index}] marks an incomplete run won")
        if value["survived_to_ante_6"] and not value["complete"]:
            raise ReportError(f"report {path} results[{index}] marks an incomplete run survived")
        terminal_reason = value["terminal_reason"]
        terminal_complete = terminal_reason in {"game_over", "ante_cap"}
        if value["complete"] != terminal_complete:
            raise ReportError(
                f"report {path} results[{index}] has inconsistent completion reason"
            )
        ante = value["ante"]
        if isinstance(ante, bool) or not isinstance(ante, int) or ante < 0:
            raise ReportError(f"report {path} results[{index}] has invalid ante")
        antes_cleared = value["antes_cleared"]
        if (
            isinstance(antes_cleared, bool)
            or not isinstance(antes_cleared, int)
            or antes_cleared < 0
        ):
            raise ReportError(f"report {path} results[{index}] has invalid antes_cleared")
        if not value["complete"] and antes_cleared != 0:
            raise ReportError(
                f"report {path} results[{index}] gives an incomplete run non-zero antes"
            )
        if value["won"] and antes_cleared < 8:
            raise ReportError(f"report {path} results[{index}] has inconsistent win metric")
        if antes_cleared > ante_cap:
            raise ReportError(f"report {path} results[{index}] exceeds the ante cap")
        if terminal_reason == "ante_cap" and antes_cleared != ante_cap:
            raise ReportError(f"report {path} results[{index}] did not reach the ante cap")
        expected_survival = value["complete"] and ante >= 6
        if value["survived_to_ante_6"] != expected_survival:
            raise ReportError(f"report {path} results[{index}] has inconsistent survival metric")
        if value["won"] and not expected_survival:
            raise ReportError(f"report {path} results[{index}] marks a pre-Ante-6 run won")
        if "best_hand_score" in value:
            score = value["best_hand_score"]
            if isinstance(score, bool) or not isinstance(score, int) or score < 0:
                raise ReportError(f"report {path} results[{index}] has invalid best_hand_score")
        seen.add(seed)
        result.append(value)
    return result


def _validate_report_seed_panel(
    report: dict[str, Any], results: list[dict[str, Any]], path: Path
) -> SeedPanelValidation:
    protocol = report.get("benchmark_protocol")
    if not isinstance(protocol, dict):
        raise ReportError(f"report {path} has no benchmark_protocol object")
    provenance = protocol.get("seed_provenance")
    if not isinstance(provenance, str):
        raise ReportError(f"report {path} has no declared seed provenance")
    seeds = [row["seed"] for row in results]
    expected = list(range(seeds[0], seeds[0] + len(seeds)))
    if seeds != expected:
        raise ReportError(f"report {path} results are not a contiguous ordered seed panel")
    try:
        return validate_seed_panel(seeds[0], len(seeds), provenance)
    except PanelValidationError as exc:
        raise ReportError(f"report {path} has invalid seed panel: {exc}") from exc


def _win(result: dict[str, Any]) -> bool:
    # An incomplete run is explicitly a loss, even if a malformed producer set won.
    return bool(result["complete"] and result["won"])


def _survived(result: dict[str, Any]) -> bool:
    return bool(result["complete"] and result["survived_to_ante_6"])


def _antes_cleared(result: dict[str, Any]) -> int:
    return int(result["antes_cleared"]) if result["complete"] else 0


def _best_hand_score(result: dict[str, Any]) -> int:
    """Read a validated public chip-delta metric."""

    return int(result["best_hand_score"])


def _bootstrap_mean_interval(
    values: list[int] | list[float],
    *,
    samples: int = 10_000,
    seed: int = 0,
) -> tuple[float, float]:
    """Return a deterministic paired percentile interval for a mean delta."""

    rng = random.Random(seed)
    size = len(values)
    means = sorted(
        sum(values[rng.randrange(size)] for _ in range(size)) / size
        for _ in range(samples)
    )
    lower = means[int(0.025 * samples)]
    upper = means[min(samples - 1, int(0.975 * samples))]
    return lower, upper


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        result = compare_reports(args.baseline, args.candidate)
    except ReportError as exc:
        raise SystemExit(f"error: {exc}") from exc
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
