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
    "weighting": "run-decision-pair-sample-equal",
    "selected_index_target": False,
    "behavior_index_target": False,
    "factual_outcome_on_siblings": False,
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
}
SUPPORT_CELL_CONTRACT = {
    "tuple_fields": ["route", "goal", "phase", "ante"],
    "minimum_train_pairs": 1,
    "minimum_calibration_pairs": 1,
    "minimum_holdout_pairs": 1,
    "minimum_train_groups": 1,
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


def _validate_support_cells(value: object) -> None:
    if not isinstance(value, list):
        raise RouteLearningProtocolError("support_cells must be a list of exact tuples")
    for index, cell in enumerate(value):
        if (
            not isinstance(cell, list)
            or len(cell) != 4
            or not all(
                isinstance(item, (str, int)) and not isinstance(item, bool)
                for item in cell
            )
            or not isinstance(cell[3], int)
            or isinstance(cell[3], bool)
        ):
            raise RouteLearningProtocolError(
                f"support_cells[{index}] is not a route/goal/phase/ante tuple"
            )


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
            "implementation_revision",
            "expected_source_digest",
            "split",
            "comparator",
            "artifact",
            "model",
            "optimizer",
            "objective",
            "admission",
            "holdout_gate",
            "support_cell_contract",
            "support_cells",
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
    if (
        not isinstance(root["implementation_revision"], str)
        or len(root["implementation_revision"]) != 40
        or not all(c in "0123456789abcdef" for c in root["implementation_revision"])
    ):
        raise RouteLearningProtocolError("implementation revision is invalid")
    if (
        not isinstance(root["expected_source_digest"], str)
        or len(root["expected_source_digest"]) != 64
        or not all(c in "0123456789abcdef" for c in root["expected_source_digest"])
    ):
        raise RouteLearningProtocolError("source digest is invalid")
    if (
        not _equal_exact(root["split"], SPLIT_CONFIG)
        or not _equal_exact(root["comparator"], ROUTE_LEARNING_COMPARATOR)
        or not _equal_exact(root["model"], MODEL_CONFIG)
        or not _equal_exact(root["optimizer"], OPTIMIZER_CONFIG)
        or not _equal_exact(root["objective"], OBJECTIVE_CONFIG)
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
        },
    ):
        raise RouteLearningProtocolError("route artifact is not shadow-only")
    _validate_support_cells(root["support_cells"])
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
