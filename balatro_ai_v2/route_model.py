"""Strict shadow-only artifact envelope for route-terminal residual models."""

from __future__ import annotations

import hashlib
import json
import math
import os
import pickle
import re
import tempfile
from copy import deepcopy
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Mapping

import torch
from torch import Tensor

from balatro_ai_v2.route_learning_protocol import (
    MODEL_CONFIG,
    OBJECTIVE_CONFIG,
    ROUTE_LEARNING_ARTIFACT_FORMAT,
    SPLIT_CONFIG,
)
from balatro_ai_v2.strategy_model import (
    STRATEGY_MODEL_SCHEMA_DIGEST,
    RelationalStrategyPolicyValue,
    StrategyCalibration,
    StrategyModelConfig,
)


ROUTE_MODEL_KIND = "route_terminal_residual"
ROUTE_RESIDUAL_HEADS = (
    "scalar",
    "current_blind",
    "next_boss",
    "ante8",
    "endless_ante",
    "log_score",
)

_DIGEST = re.compile(r"[0-9a-f]{64}")
_REVISION = re.compile(r"[0-9a-f]{40}")
_ORIGIN_GROUP = re.compile(r"origin-[0-9a-f]{32}")
_PAYLOAD_FIELDS = {
    "kind",
    "format_version",
    "base_model_schema_digest",
    "model_config",
    "route_residual_calibration",
    "route_provenance",
    "state_dict",
}
_PROVENANCE_FIELDS = {
    "training_status",
    "influence_mode",
    "dataset_sha256",
    "collection_report_sha256",
    "collection_preregistration_sha256",
    "learner_preregistration_sha256",
    "teacher_config_digest",
    "split",
    "objective",
    "trainer_source_revision",
    "trainer_source_digest",
}
_SPLIT_FIELDS = {
    "train_batches",
    "calibration_batches",
    "holdout_batches",
    "train_groups",
    "calibration_groups",
    "holdout_groups",
    "train_group_sha256",
    "calibration_group_sha256",
    "holdout_group_sha256",
}


class RouteModelError(RuntimeError):
    """A route model artifact violates its isolated public contract."""


@dataclass(frozen=True, slots=True)
class RouteResidualCalibration:
    """Post-training calibration for the six paired route residual heads."""

    scalar_bias: float = 0.0
    scalar_overprediction_radius: float = 0.0
    current_blind_bias: float = 0.0
    current_blind_overprediction_radius: float = 0.0
    next_boss_bias: float = 0.0
    next_boss_overprediction_radius: float = 0.0
    ante8_bias: float = 0.0
    ante8_overprediction_radius: float = 0.0
    endless_ante_bias: float = 0.0
    endless_ante_overprediction_radius: float = 0.0
    log_score_bias: float = 0.0
    log_score_overprediction_radius: float = 0.0
    calibrated: bool = False

    def __post_init__(self) -> None:
        for field in fields(self):
            if field.name == "calibrated":
                continue
            value = getattr(self, field.name)
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not math.isfinite(float(value))
            ):
                raise ValueError(f"route calibration {field.name} must be finite")
            if field.name.endswith("_overprediction_radius") and value < 0:
                raise ValueError(f"route calibration {field.name} must be non-negative")
        if not isinstance(self.calibrated, bool):
            raise ValueError("route calibration calibrated marker must be boolean")


@dataclass(frozen=True, slots=True)
class RouteResidualArtifact:
    """Loaded route model plus its separate calibration and provenance."""

    model: RelationalStrategyPolicyValue
    calibration: RouteResidualCalibration
    provenance: dict[str, object]

    def __post_init__(self) -> None:
        _validate_model(self.model)
        if not isinstance(self.calibration, RouteResidualCalibration):
            raise ValueError("route artifact calibration has the wrong type")
        if self.calibration.calibrated is not True:
            raise ValueError("route artifact calibration is not complete")
        normalized = _normalize_provenance(self.provenance)
        object.__setattr__(self, "provenance", normalized)


def save_route_model(
    path: Path,
    model: RelationalStrategyPolicyValue,
    *,
    calibration: RouteResidualCalibration,
    provenance: Mapping[str, object],
) -> str:
    """Publish one immutable route artifact and return its SHA-256 digest."""

    artifact = RouteResidualArtifact(
        model=model,
        calibration=calibration,
        provenance=dict(provenance),
    )
    state_dict = dict(artifact.model.state_dict())
    _validate_state_dict(state_dict)
    payload = {
        "kind": ROUTE_MODEL_KIND,
        "format_version": ROUTE_LEARNING_ARTIFACT_FORMAT,
        "base_model_schema_digest": STRATEGY_MODEL_SCHEMA_DIGEST,
        "model_config": asdict(artifact.model.config),
        "route_residual_calibration": asdict(artifact.calibration),
        "route_provenance": deepcopy(artifact.provenance),
        "state_dict": state_dict,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            torch.save(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_route_model(
    path: Path,
    *,
    device: torch.device | str = "cpu",
) -> RouteResidualArtifact:
    """Load only the exact current route-terminal residual artifact format."""

    try:
        payload = torch.load(path, map_location=device, weights_only=True)
    except (
        OSError,
        RuntimeError,
        EOFError,
        ValueError,
        TypeError,
        pickle.UnpicklingError,
    ) as exc:
        raise RouteModelError(f"cannot load route model artifact: {exc}") from exc
    if type(payload) is not dict or set(payload) != _PAYLOAD_FIELDS:
        raise RouteModelError("route model artifact fields are invalid")
    if (
        type(payload["kind"]) is not str
        or payload["kind"] != ROUTE_MODEL_KIND
        or type(payload["format_version"]) is not int
        or payload["format_version"] != ROUTE_LEARNING_ARTIFACT_FORMAT
        or type(payload["base_model_schema_digest"]) is not str
        or payload["base_model_schema_digest"] != STRATEGY_MODEL_SCHEMA_DIGEST
        or type(payload["model_config"]) is not dict
        or not _equal_exact(payload["model_config"], MODEL_CONFIG)
        or type(payload["route_residual_calibration"]) is not dict
        or type(payload["route_provenance"]) is not dict
        or type(payload["state_dict"]) is not dict
    ):
        raise RouteModelError("route model artifact identity or payload is invalid")
    try:
        calibration_fields = {field.name for field in fields(RouteResidualCalibration)}
        if set(payload["route_residual_calibration"]) != calibration_fields:
            raise ValueError("route residual calibration fields are invalid")
        calibration = RouteResidualCalibration(**payload["route_residual_calibration"])
        if calibration.calibrated is not True:
            raise ValueError("route residual calibration is incomplete")
        provenance = _normalize_provenance(payload["route_provenance"])
        model = RelationalStrategyPolicyValue(_model_config()).to(device)
        _validate_state_dict(payload["state_dict"])
        _validate_state_schema(payload["state_dict"], model.state_dict())
        model.load_state_dict(payload["state_dict"], strict=True)
        _validate_model(model)
    except (KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise RouteModelError(
            f"route model artifact values are invalid: {exc}"
        ) from exc
    return RouteResidualArtifact(model, calibration, provenance)


def _model_config() -> StrategyModelConfig:
    return StrategyModelConfig(**MODEL_CONFIG)


def _validate_model(model: object) -> None:
    if not isinstance(model, RelationalStrategyPolicyValue):
        raise ValueError("route artifact model has the wrong type")
    if not _equal_exact(asdict(model.config), MODEL_CONFIG):
        raise ValueError("route artifact model configuration is not frozen")
    if model.calibration != StrategyCalibration():
        raise ValueError("route artifact embedded model calibration must stay default")
    if model.provenance != {"training_status": "untrained"}:
        raise ValueError("route artifact embedded model provenance must stay untrained")
    _validate_state_dict(model.state_dict())


def _validate_state_dict(state_dict: Mapping[str, object]) -> None:
    if not isinstance(state_dict, Mapping) or not state_dict:
        raise ValueError("route model state must be a non-empty mapping")
    if not all(isinstance(key, str) for key in state_dict):
        raise ValueError("route model state keys must be strings")
    for key, value in state_dict.items():
        if not isinstance(value, Tensor):
            raise ValueError(f"route model parameter {key!r} is not a tensor")
        if (value.is_floating_point() or value.is_complex()) and not torch.isfinite(
            value
        ).all():
            raise ValueError(f"route model parameter {key!r} is not finite")


def _validate_state_schema(
    state_dict: Mapping[str, object], expected: Mapping[str, Tensor]
) -> None:
    if set(state_dict) != set(expected):
        raise ValueError("route model state keys do not match the frozen model")
    for key, reference in expected.items():
        value = state_dict[key]
        if not isinstance(value, Tensor):
            raise ValueError(f"route model parameter {key!r} is not a tensor")
        if (
            value.shape != reference.shape
            or value.dtype != reference.dtype
            or value.layout != reference.layout
        ):
            raise ValueError(
                f"route model parameter {key!r} does not match the frozen schema"
            )


def _normalize_provenance(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != _PROVENANCE_FIELDS:
        raise ValueError("route provenance fields are invalid")
    provenance = deepcopy(value)
    if (
        type(provenance["training_status"]) is not str
        or provenance["training_status"] != "trained"
        or type(provenance["influence_mode"]) is not str
        or provenance["influence_mode"] != "shadow_only"
    ):
        raise ValueError("route provenance is not trained shadow-only evidence")
    for name in (
        "dataset_sha256",
        "collection_report_sha256",
        "collection_preregistration_sha256",
        "learner_preregistration_sha256",
        "teacher_config_digest",
        "trainer_source_digest",
    ):
        item = provenance[name]
        if type(item) is not str or _DIGEST.fullmatch(item) is None:
            raise ValueError(f"route provenance {name} must be SHA-256")
    revision = provenance["trainer_source_revision"]
    if type(revision) is not str or _REVISION.fullmatch(revision) is None:
        raise ValueError("route provenance trainer source revision is invalid")
    if not _equal_exact(provenance["objective"], OBJECTIVE_CONFIG):
        raise ValueError("route provenance objective changed")
    provenance["split"] = _normalize_split(provenance["split"])
    try:
        encoded = json.dumps(provenance, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("route provenance is not exactly JSON-safe") from exc
    if json.loads(encoded) != provenance:
        raise ValueError("route provenance does not round trip exactly")
    return provenance


def _normalize_split(value: object) -> dict[str, object]:
    if type(value) is not dict or set(value) != _SPLIT_FIELDS:
        raise ValueError("route provenance split fields are invalid")
    split = deepcopy(value)
    for name in ("train", "calibration", "holdout"):
        batches = split[f"{name}_batches"]
        expected_batches = SPLIT_CONFIG[f"{name}_batches"]
        if not _equal_exact(batches, expected_batches):
            raise ValueError("route provenance split batches changed")
        groups = split[f"{name}_groups"]
        if (
            type(groups) is not list
            or len(groups) < int(SPLIT_CONFIG[f"{name}_groups"])
            or len(set(groups)) != len(groups)
            or not all(
                type(group) is str and _ORIGIN_GROUP.fullmatch(group) is not None
                for group in groups
            )
        ):
            raise ValueError("route provenance split groups are invalid")
        expected_digest = hashlib.sha256("\n".join(groups).encode()).hexdigest()
        digest = split[f"{name}_group_sha256"]
        if type(digest) is not str or digest != expected_digest:
            raise ValueError("route provenance split group digest is invalid")
    group_sets = [
        set(split[f"{name}_groups"]) for name in ("train", "calibration", "holdout")
    ]
    if any(
        group_sets[left] & group_sets[right] for left, right in ((0, 1), (0, 2), (1, 2))
    ):
        raise ValueError("route provenance split groups overlap")
    return split


def _equal_exact(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(
            _equal_exact(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _equal_exact(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


__all__ = [
    "ROUTE_MODEL_KIND",
    "ROUTE_RESIDUAL_HEADS",
    "RouteModelError",
    "RouteResidualArtifact",
    "RouteResidualCalibration",
    "load_route_model",
    "save_route_model",
]
