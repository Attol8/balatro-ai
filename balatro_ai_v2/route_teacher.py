"""Shared public-only coverage for route-terminal teacher datasets."""

from __future__ import annotations

import hashlib
import hmac
import math
from collections import Counter

from balatro_ai_v2.actions import action_to_data
from balatro_ai_v2.strategy_engine import RunRoute
from balatro_ai_v2.strategy_teacher import (
    StrategyTargetEndpoint,
    StrategyTeacherCandidate,
    StrategyTeacherRecord,
)


ROUTE_TERMINAL_TARGETS = (
    "search_utility",
    "current_blind_clear",
    "next_boss_clear",
    "ante8_win",
    "endless_ante",
    "log_score",
)


class RouteTeacherValidationError(ValueError):
    """A route teacher component violates its public provenance contract."""


def route_teacher_candidate_identity(
    candidate: StrategyTeacherCandidate,
) -> dict[str, object]:
    return {
        "action": action_to_data(candidate.action),
        "intent": candidate.intent.value if candidate.intent is not None else None,
        "route": candidate.route.value if candidate.route is not None else None,
    }


def _exact_int(value: object, *, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _valid_record_roots(record: StrategyTeacherRecord, sample_count: int) -> bool:
    identities = tuple(
        (candidate.action, candidate.intent, candidate.route)
        for candidate in record.candidates
    )
    ordinary_by_action: Counter[object] = Counter(
        candidate.action
        for candidate in record.candidates
        if candidate.intent is None and candidate.route is None
    )
    return (
        record.candidate_space_size == len(record.candidates)
        and record.baseline_index == record.ordinary_index
        and record.candidates[record.ordinary_index].intent is None
        and record.candidates[record.ordinary_index].route is None
        and len(set(identities)) == len(identities)
        and all(
            candidate.route != RunRoute.VICTORY
            and len(candidate.samples) == sample_count
            and all(
                sample.endpoint != StrategyTargetEndpoint.CENSORED
                for sample in candidate.samples
            )
            and (
                (candidate.route is None and candidate.intent is None)
                or (
                    candidate.route is not None
                    and ordinary_by_action[candidate.action] == 1
                )
            )
            for candidate in record.candidates
        )
    )


def _valid_decision(
    decision: object,
    record: StrategyTeacherRecord,
    sample_count: int,
) -> bool:
    if not isinstance(decision, dict):
        return False
    indexes = (
        ("ordinary", "ordinary_index", record.ordinary_index),
        ("behavior", "behavior_index", record.behavior_index),
        ("teacher_selected", "teacher_selected_index", record.selected_index),
        ("executed", "executed_index", record.behavior_index),
    )
    counts = {
        "ante": record.observation.ante,
        "roots": len(record.candidates),
        "initial_samples": sample_count,
        "max_samples_used": sample_count,
        "sample_evaluations": len(record.candidates) * sample_count,
        "rejected_rollouts": 0,
        "censored_rollouts": 0,
    }
    return (
        decision.get("phase") == record.observation.phase.value
        and decision.get("goal") == record.goal.value
        and all(
            _exact_int(decision.get(name)) and decision.get(name) == expected
            for name, expected in counts.items()
        )
        and decision.get("affects_actions") is False
        and decision.get("identity_override") is False
        and decision.get("fallback_reason") is None
        and decision.get("unavailable") is False
        and decision.get("unsupported") is False
        and all(
            _exact_int(decision.get(index_name))
            and decision.get(index_name) == index
            and decision.get(identity_name)
            == route_teacher_candidate_identity(record.candidates[index])
            for identity_name, index_name, index in indexes
        )
    )


def validate_route_teacher_component(
    records: tuple[StrategyTeacherRecord, ...],
    results: object,
    *,
    origin_key: bytes,
    expected_seed_start: int,
    expected_seed_count: int,
    sample_count: int,
) -> None:
    """Reconstruct records from public source rows and their HMAC families."""

    if (
        len(origin_key) != 32
        or not isinstance(results, list)
        or len(results) != expected_seed_count
    ):
        raise RouteTeacherValidationError("route component panel is invalid")
    expected_seeds = set(
        range(expected_seed_start, expected_seed_start + expected_seed_count)
    )
    if {
        row.get("seed") for row in results if isinstance(row, dict)
    } != expected_seeds:
        raise RouteTeacherValidationError("route component seeds are invalid")

    rows_by_group: dict[str, tuple[dict[str, object], list[object]]] = {}
    for row in results:
        if not isinstance(row, dict):
            raise RouteTeacherValidationError("route component row is invalid")
        search = row.get("search")
        decisions = row.get("success_teacher_decisions")
        if (
            row.get("complete") is not True
            or row.get("terminal_reason") not in {"game_over", "ante_cap"}
            or row.get("terminal_error") is not None
            or row.get("rejected_decisions") != 0
            or not isinstance(row.get("won"), bool)
            or not _exact_int(row.get("antes_cleared"))
            or not _exact_int(row.get("best_hand_score"))
            or not isinstance(search, dict)
            or not isinstance(decisions, list)
            or not _exact_int(search.get("success_anchors_attempted"))
            or search.get("success_anchors_attempted") != len(decisions)
            or search.get("success_anchors_completed") != len(decisions)
            or any(
                not _exact_int(search.get(name)) or search.get(name) != 0
                for name in (
                    "rejected_rollouts",
                    "unavailable",
                    "success_anchor_fallbacks",
                    "success_anchor_unavailable",
                    "success_anchor_unsupported",
                    "success_teacher_rejected_rollouts",
                    "success_teacher_censored_rollouts",
                    "strategy_specialist_unavailable",
                )
            )
            or row.get("search_failure_reasons") != {}
        ):
            raise RouteTeacherValidationError(
                "route component contains a failed source run"
            )
        seed = int(row["seed"])
        group = "origin-" + hmac.new(
            origin_key, str(seed).encode(), hashlib.sha256
        ).hexdigest()[:32]
        if decisions:
            rows_by_group[group] = (row, decisions)

    by_group: dict[str, list[StrategyTeacherRecord]] = {}
    for record in records:
        by_group.setdefault(record.run_group, []).append(record)
    if set(by_group) != set(rows_by_group):
        raise RouteTeacherValidationError("route component origin mapping is invalid")
    for group, group_records in by_group.items():
        row, decisions = rows_by_group[group]
        ordered = sorted(group_records, key=lambda record: record.decision_index)
        if [record.decision_index for record in ordered] != list(
            range(len(ordered))
        ) or len(ordered) != len(decisions):
            raise RouteTeacherValidationError(
                "route component decision sequence is incomplete"
            )
        expected_log_score = math.log10(max(1, int(row["best_hand_score"])))
        for record, decision in zip(ordered, decisions, strict=True):
            if (
                record.run_won is not row["won"]
                or record.terminal_ante != row["antes_cleared"]
                or not math.isclose(
                    record.run_log_score,
                    expected_log_score,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                or not _valid_record_roots(record, sample_count)
                or not _valid_decision(decision, record, sample_count)
            ):
                raise RouteTeacherValidationError(
                    "route teacher record disagrees with its source report"
                )


def _empty_pair_metrics() -> dict[str, dict[str, int]]:
    return {
        target: {
            "sensitive_pairs": 0,
            "positive_pairs": 0,
            "negative_pairs": 0,
            "zero_pairs": 0,
            "null_mismatch_pairs": 0,
        }
        for target in ROUTE_TERMINAL_TARGETS
    }


def _record_pair(
    metrics: dict[str, dict[str, int]],
    specialist: StrategyTeacherCandidate,
    ordinary: StrategyTeacherCandidate,
) -> None:
    for target in ROUTE_TERMINAL_TARGETS:
        deltas: list[float] = []
        null_mismatch = False
        for specialist_sample, ordinary_sample in zip(
            specialist.samples, ordinary.samples, strict=True
        ):
            specialist_value = getattr(specialist_sample, target)
            ordinary_value = getattr(ordinary_sample, target)
            if (specialist_value is None) != (ordinary_value is None):
                null_mismatch = True
            elif specialist_value is not None:
                deltas.append(float(specialist_value) - float(ordinary_value))
        metric = metrics[target]
        sensitive = null_mismatch or any(delta != 0.0 for delta in deltas)
        metric["sensitive_pairs"] += int(sensitive)
        metric["null_mismatch_pairs"] += int(null_mismatch)
        signed_delta = sum(deltas)
        if signed_delta > 0.0:
            metric["positive_pairs"] += 1
        elif signed_delta < 0.0:
            metric["negative_pairs"] += 1
        else:
            metric["zero_pairs"] += 1


def route_terminal_teacher_coverage(
    records: tuple[StrategyTeacherRecord, ...],
) -> dict[str, object]:
    """Summarize exact route/null-route paired support without private state."""

    phase_rows: Counter[str] = Counter()
    ante_rows: Counter[int] = Counter()
    goal_rows: Counter[str] = Counter()
    route_roots: Counter[str] = Counter()
    route_groups: dict[str, set[str]] = {}
    route_diverse_groups: set[str] = set()
    route_diverse_by_phase: Counter[str] = Counter()
    route_diverse_by_ante: Counter[int] = Counter()
    sample_count_roots: Counter[int] = Counter()
    matched_pairs = 0
    matched_pairs_by_route: Counter[str] = Counter()
    matched_pair_groups_by_route: dict[str, set[str]] = {}
    matched_pair_samples: list[int] = []
    route_diverse_rows = 0
    censored_rows = 0
    censored_samples = 0
    sample_count_mismatch_rows = 0
    pair_metrics = _empty_pair_metrics()
    pair_metrics_by_route: dict[str, dict[str, dict[str, int]]] = {}

    for record in records:
        phase = record.observation.phase.value
        ante = record.observation.ante
        phase_rows[phase] += 1
        ante_rows[ante] += 1
        goal_rows[record.goal.value] += 1
        row_routes = {candidate.route for candidate in record.candidates}
        non_victory_routes = {
            route
            for route in row_routes
            if route is not None and route != RunRoute.VICTORY
        }
        if non_victory_routes and len(row_routes) > 1:
            route_diverse_rows += 1
            route_diverse_groups.add(record.run_group)
            route_diverse_by_phase[phase] += 1
            route_diverse_by_ante[ante] += 1

        sample_counts = {len(candidate.samples) for candidate in record.candidates}
        sample_count_mismatch_rows += int(len(sample_counts) > 1)
        row_censored = False
        ordinary_by_action: dict[object, list[StrategyTeacherCandidate]] = {}
        for candidate in record.candidates:
            sample_count_roots[len(candidate.samples)] += 1
            if candidate.route is not None and candidate.route != RunRoute.VICTORY:
                route = candidate.route.value
                route_roots[route] += 1
                route_groups.setdefault(route, set()).add(record.run_group)
            elif candidate.route is None and candidate.intent is None:
                ordinary_by_action.setdefault(candidate.action, []).append(candidate)
            candidate_censored = sum(
                sample.endpoint == StrategyTargetEndpoint.CENSORED
                for sample in candidate.samples
            )
            censored_samples += candidate_censored
            row_censored |= bool(candidate_censored)
        censored_rows += int(row_censored)

        for specialist in record.candidates:
            if specialist.route is None or specialist.route == RunRoute.VICTORY:
                continue
            route = specialist.route.value
            route_metrics = pair_metrics_by_route.setdefault(
                route, _empty_pair_metrics()
            )
            for ordinary in ordinary_by_action.get(specialist.action, ()):
                matched_pairs += 1
                matched_pairs_by_route[route] += 1
                matched_pair_groups_by_route.setdefault(route, set()).add(
                    record.run_group
                )
                matched_pair_samples.append(len(specialist.samples))
                _record_pair(pair_metrics, specialist, ordinary)
                _record_pair(route_metrics, specialist, ordinary)

    return {
        "records": len(records),
        "groups": len({record.run_group for record in records}),
        "phase_rows": dict(sorted(phase_rows.items())),
        "ante_rows": {str(ante): rows for ante, rows in sorted(ante_rows.items())},
        "goal_rows": dict(sorted(goal_rows.items())),
        "roots_by_non_victory_route": dict(sorted(route_roots.items())),
        "groups_by_non_victory_route": {
            route: len(groups) for route, groups in sorted(route_groups.items())
        },
        "route_diverse_rows": route_diverse_rows,
        "route_diverse_groups": len(route_diverse_groups),
        "route_diverse_rows_by_phase": dict(sorted(route_diverse_by_phase.items())),
        "route_diverse_rows_by_ante": {
            str(ante): rows
            for ante, rows in sorted(route_diverse_by_ante.items())
        },
        "matched_pairs": matched_pairs,
        "matched_pairs_by_route": dict(sorted(matched_pairs_by_route.items())),
        "matched_pair_groups_by_route": {
            route: len(groups)
            for route, groups in sorted(matched_pair_groups_by_route.items())
        },
        "pair_contract": (
            "nonvictory_route_minus_exact_action_null_intent_null_route;"
            "sample_order_paired;null_mismatch_sensitive;"
            "sign=sum_jointly_resolved_deltas"
        ),
        "pair_metrics": pair_metrics,
        "pair_metrics_by_route": {
            route: metrics for route, metrics in sorted(pair_metrics_by_route.items())
        },
        "stored_root_max": max(
            (len(record.candidates) for record in records), default=0
        ),
        "candidate_space_max": max(
            (record.candidate_space_size for record in records), default=0
        ),
        "subset_rows": sum(
            record.candidate_space_size > len(record.candidates)
            for record in records
        ),
        "censored_rows": censored_rows,
        "censored_samples": censored_samples,
        "sample_count_roots": {
            str(count): roots for count, roots in sorted(sample_count_roots.items())
        },
        "sample_count_min": min(sample_count_roots, default=0),
        "sample_count_max": max(sample_count_roots, default=0),
        "sample_count_mismatch_rows": sample_count_mismatch_rows,
        "matched_pair_sample_count_min": min(matched_pair_samples, default=0),
        "matched_pair_sample_count_max": max(matched_pair_samples, default=0),
    }


def route_teacher_coverage_gate_failures(
    coverage: object,
    gate: object,
    *,
    source_runs: int,
) -> tuple[str, ...]:
    """Return stable fail-closed reasons for a preregistered support gate."""

    if not isinstance(coverage, dict) or not isinstance(gate, dict):
        return ("malformed_coverage",)
    try:
        phase_rows = coverage["phase_rows"]
        route_phase_rows = coverage["route_diverse_rows_by_phase"]
        goal_rows = coverage["goal_rows"]
        search_metric = coverage["pair_metrics"]["search_utility"]
        assert isinstance(phase_rows, dict)
        assert isinstance(route_phase_rows, dict)
        assert isinstance(goal_rows, dict)
        assert isinstance(search_metric, dict)
        failures: list[str] = []
        checks = (
            (source_runs == int(gate["source_runs"]), "source_runs"),
            (
                int(coverage["groups"]) >= int(gate["minimum_record_groups"]),
                "record_groups",
            ),
            (
                int(coverage["records"]) >= int(gate["minimum_records"]),
                "records",
            ),
            (
                int(coverage["route_diverse_groups"])
                >= int(gate["minimum_route_diverse_groups"]),
                "route_diverse_groups",
            ),
            (
                int(coverage["route_diverse_rows"])
                >= int(gate["minimum_route_diverse_rows"]),
                "route_diverse_rows",
            ),
            (
                int(coverage["matched_pairs"])
                >= int(gate["minimum_matched_pairs"]),
                "matched_pairs",
            ),
            (
                int(search_metric["sensitive_pairs"])
                >= int(gate["minimum_search_utility_sensitive_pairs"]),
                "search_utility_sensitive_pairs",
            ),
            (
                int(coverage["sample_count_min"]) == int(gate["sample_count"])
                and int(coverage["sample_count_max"])
                == int(gate["sample_count"])
                and int(coverage["sample_count_mismatch_rows"]) == 0,
                "sample_count",
            ),
            (
                int(coverage["stored_root_max"])
                <= int(gate["maximum_stored_roots"]),
                "stored_roots",
            ),
            (
                int(coverage["subset_rows"]) <= int(gate["maximum_subset_rows"]),
                "subset_rows",
            ),
            (
                int(gate["rejected_or_censored"]) == 0
                and int(coverage["censored_rows"]) == 0
                and int(coverage["censored_samples"]) == 0,
                "rejected_or_censored",
            ),
        )
        failures.extend(name for passed, name in checks if not passed)
        failures.extend(
            f"phase:{phase}"
            for phase in gate.get("required_phases", ())
            if int(phase_rows.get(phase, 0)) <= 0
        )
        failures.extend(
            f"route_phase:{phase}"
            for phase in gate.get("required_route_phases", ())
            if int(route_phase_rows.get(phase, 0)) <= 0
        )
        failures.extend(
            f"goal:{goal}"
            for goal in gate.get("required_goals", ())
            if int(goal_rows.get(goal, 0)) <= 0
        )
        for gate_name, metric_name in (
            ("minimum_search_utility_positive_pairs", "positive_pairs"),
            ("minimum_search_utility_negative_pairs", "negative_pairs"),
        ):
            if gate_name in gate and int(search_metric[metric_name]) < int(
                gate[gate_name]
            ):
                failures.append(metric_name)
        return tuple(failures)
    except (AssertionError, KeyError, TypeError, ValueError):
        return ("malformed_coverage",)
