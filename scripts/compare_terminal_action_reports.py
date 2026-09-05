#!/usr/bin/env python3
"""Strict one-shot comparison for the preregistered terminal-action screen."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from compare_candidate_reports import ReportError, compare_reports


_BASE_SEARCH_FIELDS = (
    "version",
    "continuation",
    "policy_seed",
    "budget",
    "nonce",
    "phases",
    "value",
    "selection",
    "strategy_options",
    "include_reorders",
    "objective",
)
_EXPECTED_SEEDS = tuple(range(1055, 1075))
_EXPECTED_TUNING = {
    "replacement_margin": 20,
    "reserve_ante_1": 3,
    "reserve_ante_2": 6,
    "reserve_ante_3": 12,
    "sell_threshold": 65,
}
_EXPECTED_BASE_SEARCH = {
    "version": "determinized-search-v6",
    "continuation": "PublicStrategicPolicy",
    "policy_seed": "baseline-v1",
    "budget": {
        "samples": 6,
        "horizon_antes": 1,
        "max_steps": 200,
        "override_z": 1.0,
    },
    "nonce": "search-v1",
    "phases": ["BLIND_SELECT", "PACK", "SHOP"],
    "value": "rounds_cleared_plus_failed_blind_fraction;alive_at_horizon=+1",
    "selection": (
        "paired_delta_vs_continuation;override_when_mean_minus_z_se_positive"
    ),
    "strategy_options": False,
    "include_reorders": False,
    "objective": "legacy_scalar_progress",
}


def compare_terminal_action_reports(
    baseline_path: Path,
    candidate_path: Path,
    preregistration_path: Path,
) -> dict[str, Any]:
    baseline = _load(baseline_path)
    candidate = _load(candidate_path)
    preregistration, preregistration_digest = _load_preregistration(
        preregistration_path
    )
    _validate_frozen_pair(
        baseline,
        candidate,
        preregistration=preregistration,
        preregistration_digest=preregistration_digest,
    )
    comparison = compare_reports(baseline_path, candidate_path)
    diagnostics = _validate_interventions(candidate)
    interval = comparison["paired_antes_cleared_delta_bootstrap_95"]
    assert isinstance(interval, dict)
    delta = float(comparison["paired_mean_antes_cleared_delta"])
    win_delta = int(comparison["raw_win_delta"])
    passed = (
        int(comparison["candidate_wins"]) >= int(comparison["baseline_wins"])
        and delta > 0.0
        and float(interval["lower"]) >= 0.0
        and (win_delta >= 1 or delta >= 0.25)
    )
    return {
        **comparison,
        "comparison_protocol": "terminal-actions-development-v1",
        "capability_only": True,
        "authorizes_promotion": False,
        "intervention_coverage": diagnostics,
        "capability_gate_passed": passed,
    }


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"cannot load report {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReportError(f"report {path} root must be an object")
    return value


def _load_preregistration(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"cannot load preregistration {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReportError("terminal preregistration root must be an object")
    return value, hashlib.sha256(raw).hexdigest()


def _validate_frozen_pair(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    preregistration: dict[str, Any],
    preregistration_digest: str,
) -> None:
    left_manifest = baseline.get("manifest")
    right_manifest = candidate.get("manifest")
    if not isinstance(left_manifest, dict) or not isinstance(right_manifest, dict):
        raise ReportError("both terminal reports need object manifests")
    for field in ("repository_revision", "source_digest"):
        if left_manifest.get(field) != right_manifest.get(field):
            raise ReportError(f"terminal pair changed frozen source field: {field}")
    if left_manifest.get("repository_dirty") is not False or right_manifest.get(
        "repository_dirty"
    ) is not False:
        raise ReportError("terminal pair must run from a clean repository")
    if baseline.get("candidate_runtime") != candidate.get("candidate_runtime"):
        raise ReportError("terminal pair changed candidate runtime")
    implementation_revision = preregistration.get("implementation_revision")
    expected_source_digest = preregistration.get("expected_source_digest")
    if (
        preregistration.get("protocol_id") != "terminal-actions-development-v1"
        or preregistration.get("status") != "reserved"
        or preregistration.get("single_use") is not True
        or not isinstance(implementation_revision, str)
        or len(implementation_revision) != 40
        or not isinstance(expected_source_digest, str)
        or len(expected_source_digest) != 64
    ):
        raise ReportError("terminal preregistration source freeze is incomplete")
    expected_preregistration_fields = {
        "seed_start": 1055,
        "seeds": 20,
        "seed_provenance": "development",
        "deck": "RED",
        "stake": "WHITE",
        "baseline_report": (
            "runs/experiments/terminal-actions-v6/"
            "seeds1055-1074.baseline.json"
        ),
        "candidate_report": (
            "runs/experiments/terminal-actions-v6/"
            "seeds1055-1074.candidate.json"
        ),
        "strategy_tuning": _EXPECTED_TUNING,
    }
    if any(
        preregistration.get(field) != expected
        for field, expected in expected_preregistration_fields.items()
    ):
        raise ReportError("terminal preregistration changed frozen panel fields")
    if left_manifest.get("source_digest") != expected_source_digest:
        raise ReportError("terminal pair does not match preregistered source")
    if baseline.get("candidate_runtime") != preregistration.get("candidate_runtime"):
        raise ReportError("terminal pair does not match preregistered runtime")
    if left_manifest.get("backend") != preregistration.get("backend"):
        raise ReportError("terminal pair does not match preregistered backend")
    for field in (
        "backend",
        "canonical_schema_version",
        "trace_schema_version",
        "max_decisions",
        "max_antes_cleared",
        "max_settle_polls",
        "wall_clock_limit_seconds",
        "profile_mode",
        "launch_fast",
        "launch_headless",
        "run",
    ):
        if left_manifest.get(field) != right_manifest.get(field):
            raise ReportError(f"terminal pair changed manifest field: {field}")
    expected_manifest = {
        "max_decisions": 1200,
        "max_antes_cleared": 12,
        "max_settle_polls": 0,
        "wall_clock_limit_seconds": None,
        "profile_mode": "all_unlocked",
        "launch_fast": False,
        "launch_headless": False,
        "run": {"deck": "RED", "stake": "WHITE", "seed": "1055:20"},
    }
    for field, expected_value in expected_manifest.items():
        if left_manifest.get(field) != expected_value:
            raise ReportError(f"terminal pair drifted manifest field: {field}")
    if baseline.get("strategy_tuning") != _EXPECTED_TUNING or candidate.get(
        "strategy_tuning"
    ) != _EXPECTED_TUNING:
        raise ReportError("terminal pair changed preregistered strategy tuning")
    _validate_preregistration(
        baseline,
        expected_mode="baseline",
        preregistration=preregistration,
        preregistration_digest=preregistration_digest,
    )
    _validate_preregistration(
        candidate,
        expected_mode="candidate",
        preregistration=preregistration,
        preregistration_digest=preregistration_digest,
    )

    left_results = baseline.get("results")
    right_results = candidate.get("results")
    if not isinstance(left_results, list) or not isinstance(right_results, list):
        raise ReportError("terminal pair needs result arrays")
    for label, results in (("baseline", left_results), ("candidate", right_results)):
        seeds = tuple(row.get("seed") for row in results if isinstance(row, dict))
        if seeds != _EXPECTED_SEEDS:
            raise ReportError(
                f"{label} is not the frozen development panel 1055-1074"
            )
        if any(
            not isinstance(row, dict) or row.get("complete") is not True
            for row in results
        ):
            raise ReportError(f"{label} contains an incomplete run")
        _validate_run_failures(results, label=label)
        protocol = baseline.get("benchmark_protocol") if label == "baseline" else candidate.get("benchmark_protocol")
        if not isinstance(protocol, dict) or protocol.get("seed_provenance") != "development":
            raise ReportError(f"{label} is not development provenance")

    left_search = baseline.get("search_protocol")
    right_search = candidate.get("search_protocol")
    if not isinstance(left_search, dict) or not isinstance(right_search, dict):
        raise ReportError("terminal pair needs search protocol objects")
    for field in _BASE_SEARCH_FIELDS:
        if left_search.get(field) != right_search.get(field):
            raise ReportError(f"terminal pair changed base search field: {field}")
        if left_search.get(field) != _EXPECTED_BASE_SEARCH[field]:
            raise ReportError(f"terminal pair drifted preregistered field: {field}")
    _validate_success_protocol(left_search.get("success_teacher"), expected="disabled")
    _validate_success_protocol(right_search.get("success_teacher"), expected="actions")


def _validate_success_protocol(value: object, *, expected: str) -> None:
    if not isinstance(value, dict):
        raise ReportError("success terminal protocol must be an object")
    if value.get("mode") != expected:
        raise ReportError(f"expected terminal mode {expected}")
    if expected == "disabled":
        if value.get("enabled") is not False or value.get("affects_actions") is not False:
            raise ReportError("baseline terminal protocol is not disabled")
    elif (
        value.get("enabled") is not True
        or value.get("affects_actions") is not True
        or value.get("emits_teacher_rows") is not False
    ):
        raise ReportError("candidate terminal protocol is not isolated action mode")
    claimed = value.get("protocol_digest")
    if not isinstance(claimed, str) or len(claimed) != 64:
        raise ReportError("terminal protocol has no SHA-256 digest")
    canonical = dict(value)
    canonical.pop("protocol_digest")
    actual = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if claimed != actual:
        raise ReportError("terminal protocol digest mismatch")
    expected_value = _expected_success_protocol(expected)
    if canonical != expected_value:
        raise ReportError("terminal protocol differs from preregistered constants")


def _expected_success_protocol(mode: str) -> dict[str, object]:
    actions = mode == "actions"
    return {
        "enabled": actions,
        "mode": mode,
        "affects_actions": actions,
        "emits_teacher_rows": False,
        "samples": 2,
        "prewin_start_ante": 4,
        "endless_horizon_antes": 2,
        "max_steps": 600,
        "anchor_schedule": (
            "first_shop_each_ante;first_pack_each_ante_from_ante4;"
            "boss_select_ante5_plus;postwin_first_shop_and_pack_each_ante"
        ),
        "endpoint_semantics": (
            "victory_or_death_exact;endless_fixed_horizon;"
            "censored_never_exact;no_public_progress_inadmissible_for_actions"
        ),
        "terminal_action_budget": (
            {"max_samples": 12, "max_roots": 64, "family_alpha": 0.05}
            if actions
            else None
        ),
        "terminal_action_selector": (
            "root_adjusted_one_sided_sign;zero_adverse_discordances;"
            "victory=exact_win;endless=alive,ante,log_score;"
            "ties_inert;root_overflow=fail_closed_without_truncation;"
            "fallback=exact_behavior_identity"
            if actions
            else None
        ),
        "sample_nonce_stream": "search-v1:success-terminal-v1",
        "root_builder": "determinized-search-v6",
        "counter_semantics": (
            "attempted=all_scheduled_anchors;completed=no_fallback;"
            "fallback=action_mode_exact_behavior_fallback;"
            "unavailable=subset_of_fallback_without_valid_evaluation"
        ),
    }


def _validate_preregistration(
    report: dict[str, Any],
    *,
    expected_mode: str,
    preregistration: dict[str, Any],
    preregistration_digest: str,
) -> None:
    value = report.get("terminal_action_preregistration")
    expected_report = (
        "runs/experiments/terminal-actions-v6/"
        f"seeds1055-1074.{expected_mode}.json"
    )
    if value != {
        "protocol_id": "terminal-actions-development-v1",
        "sha256": preregistration_digest,
        "mode": expected_mode,
        "single_use": True,
        "declared_report": expected_report,
        "implementation_revision": preregistration.get("implementation_revision"),
        "expected_source_digest": preregistration.get("expected_source_digest"),
        "candidate_runtime": preregistration.get("candidate_runtime"),
        "backend": preregistration.get("backend"),
    }:
        raise ReportError("terminal report is not bound to the frozen preregistration")


def _validate_run_failures(results: list[Any], *, label: str) -> None:
    for row in results:
        if not isinstance(row, dict) or not isinstance(row.get("search"), dict):
            raise ReportError(f"{label} omitted search diagnostics")
        search = row["search"]
        for field in (
            "rejected_rollouts",
            "unavailable",
            "success_teacher_rejected_rollouts",
            "success_teacher_censored_rollouts",
            "success_anchor_unavailable",
        ):
            if _nonnegative_int(search, field, context=label) != 0:
                raise ReportError(f"{label} contains failed search work: {field}")


def _validate_interventions(candidate: dict[str, Any]) -> dict[str, int]:
    results = candidate["results"]
    attempted = 0
    evaluated = 0
    action_overrides = 0
    intent_only_overrides = 0
    route_only_overrides = 0
    for row in results:
        search = row.get("search")
        decisions = row.get("success_teacher_decisions")
        if not isinstance(search, dict) or not isinstance(decisions, list):
            raise ReportError("candidate omitted terminal intervention diagnostics")
        row_counts = _recompute_intervention_counts(decisions)
        counter_fields = {
            "attempted": "success_anchors_attempted",
            "completed": "success_anchors_completed",
            "fallbacks": "success_anchor_fallbacks",
            "unavailable": "success_anchor_unavailable",
            "unsupported": "success_anchor_unsupported",
            "rejected": "success_teacher_rejected_rollouts",
            "censored": "success_teacher_censored_rollouts",
            "action_overrides": "success_action_overrides",
            "intent_only_overrides": "success_intent_only_overrides",
        }
        if "success_route_only_overrides" in search:
            counter_fields["route_only_overrides"] = (
                "success_route_only_overrides"
            )
        elif row_counts["route_only_overrides"] != 0:
            raise ReportError("terminal report omits route-only override counter")
        for derived, counter in counter_fields.items():
            if (
                _nonnegative_int(search, counter, context="candidate")
                != row_counts[derived]
            ):
                raise ReportError(f"terminal counter disagrees with decisions: {counter}")
        attempted += row_counts["attempted"]
        evaluated += row_counts["evaluated"]
        action_overrides += row_counts["action_overrides"]
        intent_only_overrides += row_counts["intent_only_overrides"]
        route_only_overrides += row_counts["route_only_overrides"]
    overrides = action_overrides + intent_only_overrides + route_only_overrides
    if attempted < 20 or evaluated < 10 or overrides < 1:
        raise ReportError("candidate has insufficient terminal intervention coverage")
    return {
        "attempted_anchors": attempted,
        "evaluated_anchors": evaluated,
        "action_overrides": action_overrides,
        "intent_only_overrides": intent_only_overrides,
        "route_only_overrides": route_only_overrides,
        "identity_overrides": overrides,
    }


def _recompute_intervention_counts(decisions: list[Any]) -> dict[str, int]:
    totals = {
        "attempted": 0,
        "completed": 0,
        "fallbacks": 0,
        "unavailable": 0,
        "unsupported": 0,
        "rejected": 0,
        "censored": 0,
        "evaluated": 0,
        "action_overrides": 0,
        "intent_only_overrides": 0,
        "route_only_overrides": 0,
    }
    for decision in decisions:
        if not isinstance(decision, dict) or decision.get("affects_actions") is not True:
            raise ReportError("terminal decision has invalid action-mode schema")
        if not isinstance(decision.get("unavailable"), bool) or not isinstance(
            decision.get("unsupported"), bool
        ):
            raise ReportError("terminal decision omitted availability flags")
        if not isinstance(decision.get("identity_override"), bool):
            raise ReportError("terminal decision omitted identity flag")
        if decision.get("fallback_reason") is not None and not isinstance(
            decision.get("fallback_reason"), str
        ):
            raise ReportError("terminal decision has invalid fallback reason")
        for field in (
            "roots",
            "initial_samples",
            "max_samples_used",
            "sample_evaluations",
            "rejected_rollouts",
            "censored_rollouts",
            "behavior_index",
            "teacher_selected_index",
            "executed_index",
            "positive_discordances",
            "adverse_discordances",
            "required_positive_discordances",
        ):
            value = decision.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ReportError(f"terminal decision has invalid {field}")
        roots = int(decision["roots"])
        if roots < 1 or any(
            int(decision[field]) >= roots
            for field in ("behavior_index", "teacher_selected_index", "executed_index")
        ):
            raise ReportError("terminal decision index is outside its root set")
        behavior = decision.get("behavior")
        executed = decision.get("executed")
        teacher = decision.get("teacher_selected")
        if not all(isinstance(value, dict) for value in (behavior, executed, teacher)):
            raise ReportError("terminal decision omitted public root identities")
        identity_override = decision.get("executed_index") != decision.get(
            "behavior_index"
        )
        if decision.get("identity_override") is not identity_override:
            raise ReportError("terminal decision identity override is inconsistent")
        fallback = decision.get("fallback_reason") is not None
        if decision["unavailable"] and not fallback:
            raise ReportError("unavailable terminal decision did not fall back")
        if decision["unsupported"] and not decision["unavailable"]:
            raise ReportError("unsupported terminal decision is not unavailable")
        if fallback and (executed != behavior or identity_override):
            raise ReportError("terminal fallback did not preserve exact behavior identity")
        if identity_override and fallback:
            raise ReportError("terminal override cannot also be a fallback")
        if identity_override:
            required = max(1, math.ceil(math.log2((roots - 1) / 0.05)))
            minimum_evaluations = roots * int(decision["initial_samples"]) + 2 * max(
                0, required - int(decision["initial_samples"])
            )
            if (
                roots > 64
                or decision["initial_samples"] != 2
                or decision["max_samples_used"] > 12
                or decision["max_samples_used"] < required
                or decision["required_positive_discordances"] != required
                or decision["positive_discordances"] < required
                or decision["adverse_discordances"] != 0
                or decision["sample_evaluations"] < minimum_evaluations
                or executed == behavior
                or teacher != executed
            ):
                raise ReportError("terminal override has impossible selector evidence")
        totals["attempted"] += 1
        totals["completed"] += int(not fallback)
        totals["fallbacks"] += int(fallback)
        totals["unavailable"] += int(decision.get("unavailable") is True)
        totals["unsupported"] += int(decision.get("unsupported") is True)
        totals["rejected"] += int(decision["rejected_rollouts"])
        totals["censored"] += int(decision["censored_rollouts"])
        totals["evaluated"] += int(decision["sample_evaluations"] > 0)
        if identity_override:
            assert isinstance(behavior, dict) and isinstance(executed, dict)
            if executed.get("action") != behavior.get("action"):
                totals["action_overrides"] += 1
            elif executed.get("intent") != behavior.get("intent"):
                totals["intent_only_overrides"] += 1
            else:
                totals["route_only_overrides"] += 1
    return totals


def _nonnegative_int(
    value: dict[str, Any], field: str, *, context: str
) -> int:
    item = value.get(field)
    if isinstance(item, bool) or not isinstance(item, int) or item < 0:
        raise ReportError(f"{context} has invalid nonnegative counter: {field}")
    return item


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("preregistration", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        payload = compare_terminal_action_reports(
            args.baseline, args.candidate, args.preregistration
        )
    except ReportError as exc:
        raise SystemExit(f"invalid terminal-action comparison: {exc}") from exc
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
