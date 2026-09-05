from __future__ import annotations

import copy
import hashlib
from dataclasses import fields

import pytest
import torch

from balatro_ai_v2.route_learning_protocol import (
    MODEL_CONFIG,
    OBJECTIVE_CONFIG,
    ROUTE_LEARNING_ARTIFACT_FORMAT,
    SPLIT_CONFIG,
)
from balatro_ai_v2.route_model import (
    ROUTE_MODEL_KIND,
    RouteModelError,
    RouteResidualCalibration,
    load_route_model,
    save_route_model,
)
from balatro_ai_v2.strategy_model import (
    STRATEGY_MODEL_SCHEMA_DIGEST,
    RelationalStrategyPolicyValue,
    StrategyCalibration,
    StrategyModelConfig,
    StrategyModelError,
    load_strategy_model,
    save_strategy_model,
)


def _model() -> RelationalStrategyPolicyValue:
    torch.manual_seed(7)
    return RelationalStrategyPolicyValue(StrategyModelConfig(**MODEL_CONFIG))


def _calibration() -> RouteResidualCalibration:
    return RouteResidualCalibration(
        scalar_bias=0.1,
        scalar_overprediction_radius=0.2,
        current_blind_bias=0.3,
        current_blind_overprediction_radius=0.4,
        next_boss_bias=0.5,
        next_boss_overprediction_radius=0.6,
        ante8_bias=0.7,
        ante8_overprediction_radius=0.8,
        endless_ante_bias=0.9,
        endless_ante_overprediction_radius=1.0,
        log_score_bias=1.1,
        log_score_overprediction_radius=1.2,
        calibrated=True,
    )


def _groups(offset: int, count: int) -> list[str]:
    return [f"origin-{value:032x}" for value in range(offset, offset + count)]


def _group_digest(groups: list[str]) -> str:
    return hashlib.sha256("\n".join(groups).encode()).hexdigest()


def _provenance() -> dict[str, object]:
    # The producer preserves sorted groups within each canonical batch, then
    # concatenates batches in preregistered order.  That sequence need not be
    # globally lexical because the origin labels are opaque.
    train = _groups(401, 4) + _groups(1, 4) + _groups(201, 4)
    calibration = _groups(601, 4)
    holdout = _groups(801, 4)
    return {
        "training_status": "trained",
        "influence_mode": "shadow_only",
        "dataset_sha256": "a" * 64,
        "collection_report_sha256": "b" * 64,
        "collection_preregistration_sha256": "c" * 64,
        "learner_preregistration_sha256": "d" * 64,
        "teacher_config_digest": "e" * 64,
        "split": {
            "train_batches": copy.deepcopy(SPLIT_CONFIG["train_batches"]),
            "calibration_batches": copy.deepcopy(SPLIT_CONFIG["calibration_batches"]),
            "holdout_batches": copy.deepcopy(SPLIT_CONFIG["holdout_batches"]),
            "train_groups": train,
            "calibration_groups": calibration,
            "holdout_groups": holdout,
            "train_group_sha256": _group_digest(train),
            "calibration_group_sha256": _group_digest(calibration),
            "holdout_group_sha256": _group_digest(holdout),
        },
        "objective": copy.deepcopy(OBJECTIVE_CONFIG),
        "trainer_source_revision": "f" * 40,
        "trainer_source_digest": "0" * 64,
    }


def _write_valid(path):
    digest = save_route_model(
        path,
        _model(),
        calibration=_calibration(),
        provenance=_provenance(),
    )
    return digest, torch.load(path, map_location="cpu", weights_only=True)


def _write_payload(path, payload) -> None:
    torch.save(payload, path)


def test_route_model_round_trip_is_exact_and_digest_bound(tmp_path):
    path = tmp_path / "route.pt"
    digest, payload = _write_valid(path)
    loaded = load_route_model(path, device=torch.device("cpu"))

    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()
    assert payload["kind"] == ROUTE_MODEL_KIND
    assert payload["format_version"] == ROUTE_LEARNING_ARTIFACT_FORMAT
    assert payload["base_model_schema_digest"] == STRATEGY_MODEL_SCHEMA_DIGEST
    assert payload["model_config"] == MODEL_CONFIG
    assert loaded.calibration == _calibration()
    assert loaded.provenance == _provenance()
    assert loaded.model.provenance == {"training_status": "untrained"}
    assert next(loaded.model.parameters()).device.type == "cpu"
    for name, value in _model().state_dict().items():
        assert torch.equal(loaded.model.state_dict()[name], value)


def test_route_model_save_is_no_overwrite(tmp_path):
    path = tmp_path / "route.pt"
    _write_valid(path)
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        save_route_model(
            path,
            _model(),
            calibration=_calibration(),
            provenance=_provenance(),
        )
    assert path.read_bytes() == original


def test_route_and_v14_loaders_reject_each_others_artifacts(tmp_path):
    route_path = tmp_path / "route.pt"
    old_path = tmp_path / "old.pt"
    _write_valid(route_path)
    save_strategy_model(old_path, _model())

    with pytest.raises(StrategyModelError):
        load_strategy_model(route_path)
    with pytest.raises(RouteModelError):
        load_route_model(old_path)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("kind", "strategy_model"),
        ("format_version", True),
        ("format_version", ROUTE_LEARNING_ARTIFACT_FORMAT + 1),
        ("base_model_schema_digest", "0" * 64),
        ("model_config", {**MODEL_CONFIG, "hidden_size": 32}),
    ],
)
def test_route_model_identity_and_config_mutations_fail_closed(
    tmp_path, field, replacement
):
    source = tmp_path / "source.pt"
    _, payload = _write_valid(source)
    payload[field] = replacement
    target = tmp_path / f"bad-{field}.pt"
    _write_payload(target, payload)
    with pytest.raises(RouteModelError):
        load_route_model(target)


def test_route_model_payload_unknown_or_missing_fields_fail_closed(tmp_path):
    source = tmp_path / "source.pt"
    _, payload = _write_valid(source)
    missing = copy.deepcopy(payload)
    missing.pop("kind")
    extra = copy.deepcopy(payload)
    extra["unexpected"] = True
    for index, candidate in enumerate((missing, extra)):
        path = tmp_path / f"bad-fields-{index}.pt"
        _write_payload(path, candidate)
        with pytest.raises(RouteModelError):
            load_route_model(path)


@pytest.mark.parametrize(
    "field",
    [
        field.name
        for field in fields(RouteResidualCalibration)
        if field.name != "calibrated"
    ],
)
def test_nonfinite_calibration_values_fail_closed(tmp_path, field):
    source = tmp_path / "source.pt"
    _, payload = _write_valid(source)
    payload["route_residual_calibration"][field] = float("nan")
    target = tmp_path / f"bad-{field}.pt"
    _write_payload(target, payload)
    with pytest.raises(RouteModelError):
        load_route_model(target)


@pytest.mark.parametrize(
    "field",
    [
        field.name
        for field in fields(RouteResidualCalibration)
        if field.name.endswith("_overprediction_radius")
    ],
)
def test_negative_calibration_radii_fail_closed(tmp_path, field):
    source = tmp_path / "source.pt"
    _, payload = _write_valid(source)
    payload["route_residual_calibration"][field] = -0.1
    target = tmp_path / f"bad-{field}.pt"
    _write_payload(target, payload)
    with pytest.raises(RouteModelError):
        load_route_model(target)


def test_calibration_marker_and_fields_are_strict(tmp_path):
    source = tmp_path / "source.pt"
    _, payload = _write_valid(source)
    mutations = []
    false_marker = copy.deepcopy(payload)
    false_marker["route_residual_calibration"]["calibrated"] = False
    mutations.append(false_marker)
    boolean_radius = copy.deepcopy(payload)
    boolean_radius["route_residual_calibration"]["scalar_overprediction_radius"] = True
    mutations.append(boolean_radius)
    missing = copy.deepcopy(payload)
    missing["route_residual_calibration"].pop("scalar_bias")
    mutations.append(missing)
    for index, candidate in enumerate(mutations):
        path = tmp_path / f"bad-calibration-{index}.pt"
        _write_payload(path, candidate)
        with pytest.raises(RouteModelError):
            load_route_model(path)


@pytest.mark.parametrize(
    "field",
    [
        "dataset_sha256",
        "collection_report_sha256",
        "collection_preregistration_sha256",
        "learner_preregistration_sha256",
        "teacher_config_digest",
        "trainer_source_digest",
    ],
)
def test_every_provenance_digest_is_strict(tmp_path, field):
    source = tmp_path / "source.pt"
    _, payload = _write_valid(source)
    payload["route_provenance"][field] = "0" * 63
    target = tmp_path / f"bad-{field}.pt"
    _write_payload(target, payload)
    with pytest.raises(RouteModelError):
        load_route_model(target)


def test_route_provenance_identity_objective_and_fields_are_strict(tmp_path):
    source = tmp_path / "source.pt"
    _, payload = _write_valid(source)
    mutations = []
    for field, replacement in (
        ("training_status", "untrained"),
        ("influence_mode", "shadow"),
        ("trainer_source_revision", "f" * 39),
    ):
        candidate = copy.deepcopy(payload)
        candidate["route_provenance"][field] = replacement
        mutations.append(candidate)
    objective = copy.deepcopy(payload)
    objective["route_provenance"]["objective"]["selected_index_target"] = True
    mutations.append(objective)
    missing = copy.deepcopy(payload)
    missing["route_provenance"].pop("dataset_sha256")
    mutations.append(missing)
    extra = copy.deepcopy(payload)
    extra["route_provenance"]["unexpected"] = True
    mutations.append(extra)
    for index, candidate in enumerate(mutations):
        path = tmp_path / f"bad-provenance-{index}.pt"
        _write_payload(path, candidate)
        with pytest.raises(RouteModelError):
            load_route_model(path)


def test_route_split_manifest_is_authenticated(tmp_path):
    source = tmp_path / "source.pt"
    _, payload = _write_valid(source)
    mutations = []
    wrong_batches = copy.deepcopy(payload)
    wrong_batches["route_provenance"]["split"]["train_batches"].reverse()
    mutations.append(wrong_batches)
    wrong_digest = copy.deepcopy(payload)
    wrong_digest["route_provenance"]["split"]["train_group_sha256"] = "0" * 64
    mutations.append(wrong_digest)
    noncanonical_groups = copy.deepcopy(payload)
    noncanonical_groups["route_provenance"]["split"]["train_groups"].reverse()
    mutations.append(noncanonical_groups)
    overlap = copy.deepcopy(payload)
    overlap["route_provenance"]["split"]["holdout_groups"][0] = overlap[
        "route_provenance"
    ]["split"]["train_groups"][0]
    overlap["route_provenance"]["split"]["holdout_group_sha256"] = _group_digest(
        overlap["route_provenance"]["split"]["holdout_groups"]
    )
    mutations.append(overlap)
    too_few = copy.deepcopy(payload)
    too_few["route_provenance"]["split"]["calibration_groups"] = []
    too_few["route_provenance"]["split"]["calibration_group_sha256"] = _group_digest([])
    mutations.append(too_few)
    for index, candidate in enumerate(mutations):
        path = tmp_path / f"bad-split-{index}.pt"
        _write_payload(path, candidate)
        with pytest.raises(RouteModelError):
            load_route_model(path)


def test_nonfinite_or_malformed_state_dict_fails_closed(tmp_path):
    source = tmp_path / "source.pt"
    _, payload = _write_valid(source)
    parameter = next(iter(payload["state_dict"]))
    nonfinite = copy.deepcopy(payload)
    nonfinite["state_dict"][parameter].view(-1)[0] = float("inf")
    missing = copy.deepcopy(payload)
    missing["state_dict"].pop(parameter)
    non_tensor = copy.deepcopy(payload)
    non_tensor["state_dict"][parameter] = 1
    wrong_dtype = copy.deepcopy(payload)
    wrong_dtype["state_dict"][parameter] = wrong_dtype["state_dict"][parameter].to(
        torch.float64
    )
    wrong_shape = copy.deepcopy(payload)
    wrong_shape["state_dict"][parameter] = wrong_shape["state_dict"][
        parameter
    ].flatten()[:-1]
    for index, candidate in enumerate(
        (nonfinite, missing, non_tensor, wrong_dtype, wrong_shape)
    ):
        path = tmp_path / f"bad-state-{index}.pt"
        _write_payload(path, candidate)
        with pytest.raises(RouteModelError):
            load_route_model(path)


def test_save_rejects_wrong_config_and_embedded_trained_provenance(tmp_path):
    wrong_config = RelationalStrategyPolicyValue(
        StrategyModelConfig(**{**MODEL_CONFIG, "hidden_size": 32})
    )
    with pytest.raises(ValueError, match="configuration"):
        save_route_model(
            tmp_path / "wrong-config.pt",
            wrong_config,
            calibration=_calibration(),
            provenance=_provenance(),
        )

    model = _model()
    model.provenance = {"training_status": "trained"}
    with pytest.raises(ValueError, match="provenance"):
        save_route_model(
            tmp_path / "wrong-provenance.pt",
            model,
            calibration=_calibration(),
            provenance=_provenance(),
        )

    model = _model()
    model.calibration = StrategyCalibration(policy_temperature=2.0)
    with pytest.raises(ValueError, match="calibration"):
        save_route_model(
            tmp_path / "wrong-calibration.pt",
            model,
            calibration=_calibration(),
            provenance=_provenance(),
        )
