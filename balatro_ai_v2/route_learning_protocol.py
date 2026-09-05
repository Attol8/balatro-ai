"""Frozen, shadow-only protocol for learning route-terminal residuals.

This module intentionally contains no learner.  It is the admission boundary
for a future route learner and rejects an absent, widened, or ambiguously
typed preregistration.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from balatro_ai_v2.strategy_model import STRATEGY_MODEL_SCHEMA_DIGEST
from balatro_ai_v2.route_teacher_protocol import ROUTE_TEACHER_PROTOCOL_ID


ROUTE_LEARNING_PROTOCOL_ID = "route-terminal-learning-v1"
ROUTE_LEARNING_PREREGISTRATION = (
    "experiments/route-terminal-learning-v1-preregistration.json"
)
ROUTE_LEARNING_COLLECTION_MODE = "route_terminal_paired_utility"
ROUTE_LEARNING_COMPARATOR = "same_action_null_route_v1"
ROUTE_LEARNING_ARTIFACT_FORMAT = 1

MODEL_CONFIG = {
    "hidden_size": 64,
    "attention_heads": 4,
    "attention_layers": 2,
    "feedforward_size": 128,
    "dropout": 0.0,
    "max_entities": 256,
    "max_actions": 512,
}
OPTIMIZER_CONFIG = {
    "name": "AdamW",
    "epochs": 30,
    "training_seed": 20260905,
    "learning_rate": 0.0003,
    "weight_decay": 0.0001,
    "max_gradient_norm": 1.0,
}
OBJECTIVE_CONFIG = {
    "name": "paired_route_residual_v1",
    "comparator": ROUTE_LEARNING_COMPARATOR,
    "weights": {
        "search_utility": 1.0,
        "ordering": 0.25,
        "current_blind_clear": 1.0,
        "next_boss_clear": 1.0,
        "ante8_win": 1.0,
        "endless_ante": 0.5,
        "log_score": 0.5,
    },
    "weighting": "paired-sample-mean-then-run-decision-pair-equal",
    "target_reduction": "arithmetic-mean-before-loss-and-ordering",
    "selected_index_target": False,
    "behavior_index_target": False,
    "factual_outcome_on_siblings": False,
}
CALIBRATION_CONFIG = {
    "bias_estimator": "weighted-mean-target-minus-raw",
    "radius_estimator": "maximum-nonnegative-corrected-overprediction",
    "weighting": "run-decision-pair-sample-equal-by-head",
    "pair_label_admission": "all-paired-samples-jointly-resolved",
    "canonical_order": [
        "run_group",
        "decision_index",
        "specialist_index",
        "sample_index",
    ],
    "ordinary_anchor": "zero-after-candidate-difference",
    "scalar_lcb_tie": "not-positive-no-recommendation",
    "safety_lcb_tie": "zero-is-admissible",
    "full_rank_tie": "no-recommendation",
    "empirical_only": True,
}
SPLIT_CONFIG = {
    "nonce": "route-learning-split-v1-predeclared",
    "train_batches": ["batch-01", "batch-02", "batch-03"],
    "calibration_batches": ["batch-04"],
    "holdout_batches": ["batch-05"],
    "train_groups": 12,
    "calibration_groups": 4,
    "holdout_groups": 4,
    "train_rows": 120,
    "calibration_rows": 40,
    "holdout_rows": 40,
    "train_pairs": 60,
    "calibration_pairs": 20,
    "holdout_pairs": 20,
    "train_sensitive_pairs": 6,
    "calibration_sensitive_pairs": 2,
    "holdout_sensitive_pairs": 2,
}
ADMISSION_CONFIG = {
    "minimums": {
        "train": {"groups": 12, "rows": 120, "matched_pairs": 60, "sensitive_pairs": 6},
        "calibration": {
            "groups": 4,
            "rows": 40,
            "matched_pairs": 20,
            "sensitive_pairs": 2,
        },
        "holdout": {"groups": 4, "rows": 40, "matched_pairs": 20, "sensitive_pairs": 2},
    },
    "minimum_positive_and_negative_by_split": True,
}
HOLDOUT_GATE = {
    "minimum_safe_recommendations": 2,
    "minimum_safe_recommendation_groups": 2,
    "scalar_residual_mae_beats_zero": True,
    "balanced_sensitive_sign_accuracy_strictly_above": 0.5,
    "current_blind_residual_mae_beats_zero": True,
    "next_boss_residual_mae_beats_zero": True,
    "recommendations_positive_utility": True,
    "zero_ties": True,
    "zero_survival_regressions": True,
    "zero_victory_routes": True,
    "zero_rejected_roots": True,
    "zero_regret_against_safe_specialist": True,
    "victory_ante8_non_regression": True,
    "endless_ante_non_regression": True,
    "endless_log_score_non_regression": True,
    "all_overprediction_within_calibration_radii": True,
}
SUPPORT_CELL_CONTRACT = {
    "tuple_fields": ["route", "goal", "phase", "ante"],
    "minimum_train_pairs": 4,
    "minimum_calibration_pairs": 2,
    "minimum_holdout_pairs": 2,
    "minimum_train_groups": 2,
    "minimum_calibration_groups": 1,
    "minimum_holdout_groups": 1,
    "mixed_signs_before_holdout": True,
    "safe_positive_holdout_recommendation": True,
    "no_independent_field_lists": True,
}


class RouteLearningProtocolError(ValueError):
    """A route-learning preregistration violates its frozen contract."""


def _exact_int(value: object, minimum: int = 0) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def _exact_keys(value: object, keys: set[str], where: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise RouteLearningProtocolError(f"{where} has unknown or missing keys")
    return value


def _equal_exact(actual: object, expected: object) -> bool:
    """Compare JSON values without Python's bool/int equality trap."""

    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict):
        return set(actual) == set(expected) and all(
            _equal_exact(actual[key], expected[key]) for key in actual
        )
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(
            _equal_exact(left, right)
            for left, right in zip(actual, expected, strict=True)
        )
    return actual == expected


def validate_route_learning_preregistration(spec: object) -> dict[str, Any]:
    """Validate and return a canonical future route-learning preregistration."""

    root = _exact_keys(
        spec,
        {
            "protocol_id",
            "status",
            "collection_protocol_id",
            "collection_mode",
            "collection_schema_version",
            "collection_preregistration_sha256",
            "merger_implementation_revision",
            "merger_expected_source_digest",
            "implementation_revision",
            "expected_source_digest",
            "split",
            "comparator",
            "artifact",
            "model",
            "optimizer",
            "objective",
            "calibration",
            "admission",
            "holdout_gate",
            "support_cell_contract",
        },
        "preregistration",
    )
    if (
        root["protocol_id"] != ROUTE_LEARNING_PROTOCOL_ID
        or root["status"] != "reserved"
    ):
        raise RouteLearningProtocolError(
            "protocol is not the reserved route-learning v1"
        )
    if (
        root["collection_protocol_id"] != ROUTE_TEACHER_PROTOCOL_ID
        or root["collection_mode"] != ROUTE_LEARNING_COLLECTION_MODE
        or root["collection_schema_version"] != 11
    ):
        raise RouteLearningProtocolError("collection binding is invalid")
    for field in ("implementation_revision", "merger_implementation_revision"):
        value = root[field]
        if (
            not isinstance(value, str)
            or len(value) != 40
            or not all(c in "0123456789abcdef" for c in value)
        ):
            raise RouteLearningProtocolError(f"{field} is invalid")
    for field in (
        "expected_source_digest",
        "merger_expected_source_digest",
        "collection_preregistration_sha256",
    ):
        value = root[field]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or not all(c in "0123456789abcdef" for c in value)
        ):
            raise RouteLearningProtocolError(f"{field} is invalid")
    if (
        not _equal_exact(root["split"], SPLIT_CONFIG)
        or not _equal_exact(root["comparator"], ROUTE_LEARNING_COMPARATOR)
        or not _equal_exact(root["model"], MODEL_CONFIG)
        or not _equal_exact(root["optimizer"], OPTIMIZER_CONFIG)
        or not _equal_exact(root["objective"], OBJECTIVE_CONFIG)
        or not _equal_exact(root["calibration"], CALIBRATION_CONFIG)
        or not _equal_exact(root["admission"], ADMISSION_CONFIG)
        or not _equal_exact(root["holdout_gate"], HOLDOUT_GATE)
        or not _equal_exact(root["support_cell_contract"], SUPPORT_CELL_CONTRACT)
    ):
        raise RouteLearningProtocolError("route-learning configuration changed")
    artifact = _exact_keys(
        root["artifact"],
        {
            "format_version",
            "influence_mode",
            "action_influence",
            "rollout_authority",
            "certificate_required",
            "base_model_schema_digest",
        },
        "artifact",
    )
    if not _equal_exact(
        artifact,
        {
            "format_version": 1,
            "influence_mode": "shadow_only",
            "action_influence": False,
            "rollout_authority": False,
            "certificate_required": True,
            "base_model_schema_digest": STRATEGY_MODEL_SCHEMA_DIGEST,
        },
    ):
        raise RouteLearningProtocolError("route artifact is not shadow-only")
    return root


def load_route_learning_preregistration(
    path: Path, *, repository_root: Path
) -> tuple[dict[str, Any], str]:
    expected = (repository_root / ROUTE_LEARNING_PREREGISTRATION).resolve()
    if path.resolve() != expected:
        raise RouteLearningProtocolError(
            "route-learning preregistration path is not frozen"
        )
    try:
        raw = path.read_bytes()
        spec = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise RouteLearningProtocolError(
            "route-learning preregistration is unreadable"
        ) from exc
    return validate_route_learning_preregistration(spec), hashlib.sha256(
        raw
    ).hexdigest()
