from __future__ import annotations

import copy

import pytest

from balatro_ai_v2.route_learning_protocol import (
    ADMISSION_CONFIG,
    HOLDOUT_GATE,
    MODEL_CONFIG,
    OBJECTIVE_CONFIG,
    OPTIMIZER_CONFIG,
    ROUTE_LEARNING_COLLECTION_MODE,
    ROUTE_LEARNING_COMPARATOR,
    ROUTE_LEARNING_PROTOCOL_ID,
    SPLIT_CONFIG,
    SUPPORT_CELL_CONTRACT,
    RouteLearningProtocolError,
    validate_route_learning_preregistration,
)
from balatro_ai_v2.route_teacher_protocol import ROUTE_TEACHER_PROTOCOL_ID


def _spec():
    return {
        "protocol_id": ROUTE_LEARNING_PROTOCOL_ID,
        "status": "reserved",
        "collection_protocol_id": ROUTE_TEACHER_PROTOCOL_ID,
        "collection_mode": ROUTE_LEARNING_COLLECTION_MODE,
        "collection_schema_version": 11,
        "implementation_revision": "a" * 40,
        "expected_source_digest": "b" * 64,
        "split": copy.deepcopy(SPLIT_CONFIG),
        "comparator": ROUTE_LEARNING_COMPARATOR,
        "artifact": {
            "format_version": 1,
            "influence_mode": "shadow_only",
            "action_influence": False,
            "rollout_authority": False,
            "certificate_required": True,
        },
        "model": copy.deepcopy(MODEL_CONFIG),
        "optimizer": copy.deepcopy(OPTIMIZER_CONFIG),
        "objective": copy.deepcopy(OBJECTIVE_CONFIG),
        "admission": copy.deepcopy(ADMISSION_CONFIG),
        "holdout_gate": copy.deepcopy(HOLDOUT_GATE),
        "support_cell_contract": copy.deepcopy(SUPPORT_CELL_CONTRACT),
        "support_cells": [["played_retrigger", "victory", "PACK", 5]],
    }


def test_valid_preregistration_and_exact_311_split():
    value = validate_route_learning_preregistration(_spec())
    assert value["split"]["train_batches"] == ["batch-01", "batch-02", "batch-03"]
    assert value["split"]["calibration_batches"] == ["batch-04"]
    assert value["split"]["holdout_batches"] == ["batch-05"]


@pytest.mark.parametrize(
    "field",
    [
        "protocol_id",
        "status",
        "collection_protocol_id",
        "collection_mode",
        "comparator",
    ],
)
def test_identity_mutations_fail_closed(field):
    value = _spec()
    value[field] = "wrong"
    with pytest.raises(RouteLearningProtocolError):
        validate_route_learning_preregistration(value)


def test_unknown_keys_and_boolean_as_integer_fail_closed():
    value = _spec()
    value["unexpected"] = True
    with pytest.raises(RouteLearningProtocolError):
        validate_route_learning_preregistration(value)
    value = _spec()
    value["split"]["train_groups"] = True
    with pytest.raises(RouteLearningProtocolError):
        validate_route_learning_preregistration(value)
    value = _spec()
    value["collection_schema_version"] = True
    with pytest.raises(RouteLearningProtocolError):
        validate_route_learning_preregistration(value)


def test_configuration_and_shadow_authority_mutations_fail_closed():
    for section, key, replacement in (
        ("split", "nonce", "other"),
        ("model", "dropout", 0.1),
        ("optimizer", "training_seed", 1),
        ("objective", "weighting", "row"),
        ("admission", "minimum_positive_and_negative_by_split", False),
        ("holdout_gate", "zero_ties", False),
        ("support_cell_contract", "no_independent_field_lists", False),
    ):
        value = _spec()
        value[section][key] = replacement
        with pytest.raises(RouteLearningProtocolError):
            validate_route_learning_preregistration(value)
    value = _spec()
    value["artifact"]["action_influence"] = True
    with pytest.raises(RouteLearningProtocolError):
        validate_route_learning_preregistration(value)


def test_support_cells_are_exact_tuples_not_cartesian_field_lists():
    value = _spec()
    value["support_cells"] = {
        "routes": ["played_retrigger"],
        "goals": ["victory"],
        "phases": ["PACK"],
        "antes": [5],
    }
    with pytest.raises(RouteLearningProtocolError):
        validate_route_learning_preregistration(value)
    value = _spec()
    value["support_cells"] = [["played_retrigger", "victory", "PACK"]]
    with pytest.raises(RouteLearningProtocolError):
        validate_route_learning_preregistration(value)


def test_digest_and_revision_shape_are_strict():
    for field, bad in (
        ("implementation_revision", True),
        ("expected_source_digest", 7),
        ("expected_source_digest", "c" * 63),
    ):
        value = _spec()
        value[field] = bad
        with pytest.raises(RouteLearningProtocolError):
            validate_route_learning_preregistration(value)
