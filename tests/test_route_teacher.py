from __future__ import annotations

import hashlib
import hmac
from copy import deepcopy

import pytest

from balatro_ai_v2.actions import LeaveShop, RerollShop
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.route_teacher import (
    RouteTeacherValidationError,
    route_teacher_candidate_identity,
    route_teacher_coverage_gate_failures,
    route_terminal_teacher_coverage,
    validate_route_teacher_component,
)
from balatro_ai_v2.strategy_engine import RunGoal, RunRoute
from balatro_ai_v2.strategy_options import StrategyIntent
from balatro_ai_v2.strategy_teacher import (
    StrategyRolloutTarget,
    StrategyTeacherCandidate,
    StrategyTeacherDraft,
)
from state_factory import state


def _component():
    key = b"k" * 32
    seed = 42
    group = "origin-" + hmac.new(
        key, str(seed).encode(), hashlib.sha256
    ).hexdigest()[:32]
    ordinary_samples = (
        StrategyRolloutTarget(1, 0, 0, None, None, search_utility=1),
        StrategyRolloutTarget(1, 1, 0, None, None, search_utility=1),
    )
    positive_samples = (
        StrategyRolloutTarget(1, 1, 0, None, None, search_utility=2),
        StrategyRolloutTarget(1, 1, 0, None, None, search_utility=2),
    )
    candidates = (
        StrategyTeacherCandidate(LeaveShop(), None, ordinary_samples),
        StrategyTeacherCandidate(RerollShop(), None, ordinary_samples),
        StrategyTeacherCandidate(
            RerollShop(),
            StrategyIntent.HELD_RETRIGGER_ENGINE,
            ordinary_samples,
            route=RunRoute.HELD_RETRIGGER,
        ),
        StrategyTeacherCandidate(
            RerollShop(),
            StrategyIntent.PLAYED_RETRIGGER_ENGINE,
            positive_samples,
            route=RunRoute.PLAYED_RETRIGGER,
        ),
    )
    record = StrategyTeacherDraft(
        observation=to_public_observation(state("SHOP", money=10)),
        candidates=candidates,
        selected_index=3,
        baseline_index=0,
        ordinary_index=0,
        behavior_index=2,
        goal=RunGoal.VICTORY,
        teacher_config_digest="1" * 64,
        candidate_space_size=len(candidates),
    ).finalize(
        run_group=group,
        decision_index=0,
        run_complete=True,
        run_won=False,
        terminal_ante=4,
        best_hand_score=100,
    )
    decision = {
        "phase": record.observation.phase.value,
        "ante": record.observation.ante,
        "goal": record.goal.value,
        "roots": len(candidates),
        "initial_samples": 2,
        "max_samples_used": 2,
        "sample_evaluations": len(candidates) * 2,
        "ordinary_index": 0,
        "behavior_index": 2,
        "teacher_selected_index": 3,
        "executed_index": 2,
        "ordinary": route_teacher_candidate_identity(candidates[0]),
        "behavior": route_teacher_candidate_identity(candidates[2]),
        "teacher_selected": route_teacher_candidate_identity(candidates[3]),
        "executed": route_teacher_candidate_identity(candidates[2]),
        "fallback_reason": None,
        "affects_actions": False,
        "unavailable": False,
        "unsupported": False,
        "identity_override": False,
        "rejected_rollouts": 0,
        "censored_rollouts": 0,
    }
    row = {
        "seed": seed,
        "complete": True,
        "won": False,
        "antes_cleared": 4,
        "best_hand_score": 100,
        "terminal_reason": "game_over",
        "terminal_error": None,
        "rejected_decisions": 0,
        "search": {
            "rejected_rollouts": 0,
            "unavailable": 0,
            "success_anchors_attempted": 1,
            "success_anchors_completed": 1,
            "success_anchor_fallbacks": 0,
            "success_anchor_unavailable": 0,
            "success_anchor_unsupported": 0,
            "success_teacher_rejected_rollouts": 0,
            "success_teacher_censored_rollouts": 0,
            "strategy_specialist_unavailable": 0,
        },
        "search_failure_reasons": {},
        "success_teacher_decisions": [decision],
    }
    return (record,), [row], key


def test_route_component_reconstructs_exact_factual_provenance() -> None:
    records, rows, key = _component()

    validate_route_teacher_component(
        records,
        rows,
        origin_key=key,
        expected_seed_start=42,
        expected_seed_count=1,
        sample_count=2,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ordinary_index", 1),
        ("behavior_index", 3),
        ("executed_index", 3),
        ("teacher_selected_index", 2),
        ("affects_actions", True),
        ("fallback_reason", "tampered"),
    ],
)
def test_route_component_rejects_tampered_decision(
    field: str, value: object
) -> None:
    records, rows, key = _component()
    tampered = deepcopy(rows)
    tampered[0]["success_teacher_decisions"][0][field] = value

    with pytest.raises(RouteTeacherValidationError):
        validate_route_teacher_component(
            records,
            tampered,
            origin_key=key,
            expected_seed_start=42,
            expected_seed_count=1,
            sample_count=2,
        )


def test_route_component_rejects_specialist_without_same_action_ordinary() -> None:
    records, rows, key = _component()
    record = records[0]
    candidates = (record.candidates[0], record.candidates[2])
    invalid = StrategyTeacherDraft(
        observation=record.observation,
        candidates=candidates,
        selected_index=1,
        baseline_index=0,
        ordinary_index=0,
        behavior_index=1,
        goal=record.goal,
        teacher_config_digest=record.teacher_config_digest,
        candidate_space_size=2,
    ).finalize(
        run_group=record.run_group,
        decision_index=0,
        run_complete=True,
        run_won=False,
        terminal_ante=4,
        best_hand_score=100,
    )

    with pytest.raises(RouteTeacherValidationError):
        validate_route_teacher_component(
            (invalid,),
            rows,
            origin_key=key,
            expected_seed_start=42,
            expected_seed_count=1,
            sample_count=2,
        )


def test_route_coverage_reports_route_phase_ante_and_per_route_pairs() -> None:
    records, _, _ = _component()

    coverage = route_terminal_teacher_coverage(records)

    assert coverage["ante_rows"] == {str(records[0].observation.ante): 1}
    assert coverage["route_diverse_rows_by_phase"] == {"SHOP": 1}
    assert coverage["matched_pairs_by_route"] == {
        "held_retrigger": 1,
        "played_retrigger": 1,
    }
    assert coverage["matched_pair_groups_by_route"] == {
        "held_retrigger": 1,
        "played_retrigger": 1,
    }
    by_route = coverage["pair_metrics_by_route"]
    assert by_route["played_retrigger"]["search_utility"]["positive_pairs"] == 1


def test_route_support_gate_reports_each_failed_dimension() -> None:
    records, _, _ = _component()
    coverage = route_terminal_teacher_coverage(records)
    gate = {
        "source_runs": 1,
        "minimum_record_groups": 1,
        "minimum_records": 1,
        "required_route_phases": ["SHOP"],
        "minimum_route_diverse_groups": 1,
        "minimum_route_diverse_rows": 1,
        "minimum_matched_pairs": 2,
        "minimum_search_utility_sensitive_pairs": 1,
        "sample_count": 2,
        "maximum_stored_roots": 4,
        "maximum_subset_rows": 0,
        "rejected_or_censored": 0,
    }

    assert route_teacher_coverage_gate_failures(coverage, gate, source_runs=1) == ()
    gate["minimum_route_diverse_groups"] = 2
    assert route_teacher_coverage_gate_failures(
        coverage, gate, source_runs=1
    ) == ("route_diverse_groups",)
