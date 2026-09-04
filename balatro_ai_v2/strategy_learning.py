"""Run-group-safe learning and calibration for the relational strategy model."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass, replace
from typing import Sequence

import torch
import torch.nn.functional as F
from torch import Tensor

from balatro_ai_v2.strategy_model import (
    PublicStrategyTensorizer,
    RelationalStrategyPolicyValue,
    StrategyCalibration,
)
from balatro_ai_v2.strategy_teacher import StrategyTeacherRecord


@dataclass(frozen=True, slots=True)
class StrategyDatasetSplit:
    train: tuple[StrategyTeacherRecord, ...]
    calibration: tuple[StrategyTeacherRecord, ...]
    holdout: tuple[StrategyTeacherRecord, ...]
    train_groups: tuple[str, ...]
    calibration_groups: tuple[str, ...]
    holdout_groups: tuple[str, ...]

    def manifest(self) -> dict[str, object]:
        return {
            "train_groups": list(self.train_groups),
            "calibration_groups": list(self.calibration_groups),
            "holdout_groups": list(self.holdout_groups),
            "train_digest": _group_digest(self.train_groups),
            "calibration_digest": _group_digest(self.calibration_groups),
            "holdout_digest": _group_digest(self.holdout_groups),
        }


@dataclass(frozen=True, slots=True)
class StrategyLossWeights:
    policy: float = 0.0
    paired_utility: float = 1.0
    ordering: float = 0.25
    current_blind: float = 1.0
    next_boss: float = 1.0
    ante8: float = 1.0
    endless_ante: float = 0.5
    log_score: float = 0.5

    def __post_init__(self) -> None:
        values = (
            self.policy,
            self.paired_utility,
            self.ordering,
            self.current_blind,
            self.next_boss,
            self.ante8,
            self.endless_ante,
            self.log_score,
        )
        if any(not math.isfinite(value) or value < 0 for value in values) or not any(
            values
        ):
            raise ValueError(
                "strategy loss weights must be finite, non-negative, and non-zero"
            )


def split_teacher_records(
    records: Sequence[StrategyTeacherRecord],
    *,
    train_groups: int,
    calibration_groups: int,
    holdout_groups: int,
    nonce: str,
) -> StrategyDatasetSplit:
    """Assign whole opaque runs to deterministic, non-overlapping splits."""

    if min(train_groups, calibration_groups, holdout_groups) < 1 or not nonce:
        raise ValueError("every split needs a positive group count and a nonce")
    groups = sorted({record.run_group for record in records})
    if len(groups) != train_groups + calibration_groups + holdout_groups:
        raise ValueError("split group counts must consume the complete dataset exactly")
    ordered = sorted(
        groups,
        key=lambda group: hashlib.sha256(f"{nonce}:{group}".encode()).digest(),
    )
    train_names = tuple(ordered[:train_groups])
    calibration_names = tuple(ordered[train_groups : train_groups + calibration_groups])
    holdout_names = tuple(ordered[train_groups + calibration_groups :])
    train_set = set(train_names)
    calibration_set = set(calibration_names)
    holdout_set = set(holdout_names)
    if (
        train_set & calibration_set
        or train_set & holdout_set
        or calibration_set & holdout_set
    ):
        raise AssertionError("strategy run split overlap")

    def rows(names: set[str]) -> tuple[StrategyTeacherRecord, ...]:
        return tuple(record for record in records if record.run_group in names)

    return StrategyDatasetSplit(
        train=rows(train_set),
        calibration=rows(calibration_set),
        holdout=rows(holdout_set),
        train_groups=train_names,
        calibration_groups=calibration_names,
        holdout_groups=holdout_names,
    )


def strategy_training_loss(
    model: RelationalStrategyPolicyValue,
    records: Sequence[StrategyTeacherRecord],
    *,
    weights: StrategyLossWeights = StrategyLossWeights(),
) -> tuple[Tensor, dict[str, float]]:
    """Compute separately masked multi-task losses without blending utilities."""

    if not records:
        raise ValueError("strategy training batch is empty")
    tensorizer = PublicStrategyTensorizer(model.config)
    batch = tensorizer.tensorize(
        tuple(record.observation for record in records),
        tuple(
            tuple(candidate.action for candidate in record.candidates)
            for record in records
        ),
        tuple(
            tuple(candidate.intent for candidate in record.candidates)
            for record in records
        ),
        tuple(record.context for record in records),
    )
    output = model(batch)
    device = output.policy_logits.device
    row_weights = _run_equal_weights(records, device)
    selected = torch.tensor(
        [record.selected_index for record in records], dtype=torch.long, device=device
    )
    policy_rows = F.cross_entropy(output.policy_logits, selected, reduction="none")
    paired_utility_loss, ordering_loss = _paired_utility_losses(
        output.policy_logits, records
    )

    target_tensors: dict[str, Tensor] = {}
    target_masks: dict[str, Tensor] = {}
    target_weights: dict[str, Tensor] = {}
    for name in (
        "current_blind",
        "next_boss",
        "ante8",
        "endless_ante",
        "log_score",
    ):
        targets, mask = _candidate_target_tensors(records, name, device)
        target_tensors[name] = targets
        target_masks[name] = mask
        target_weights[name] = _run_equal_candidate_weights(records, mask, device)
    all_rows = torch.ones(len(records), dtype=torch.bool, device=device)

    losses = {
        "policy": _weighted(policy_rows, all_rows, row_weights),
        "paired_utility": paired_utility_loss,
        "ordering": ordering_loss,
        "current_blind": _weighted(
            _binary_loss(
                output.current_blind_survival, target_tensors["current_blind"]
            ),
            target_masks["current_blind"],
            target_weights["current_blind"],
        ),
        "next_boss": _weighted(
            _binary_loss(output.next_boss_survival, target_tensors["next_boss"]),
            target_masks["next_boss"],
            target_weights["next_boss"],
        ),
        "ante8": _weighted(
            _binary_loss(output.ante8_win, target_tensors["ante8"]),
            target_masks["ante8"],
            target_weights["ante8"],
        ),
        "endless_ante": _weighted(
            F.smooth_l1_loss(
                output.endless_ante, target_tensors["endless_ante"], reduction="none"
            ),
            target_masks["endless_ante"],
            target_weights["endless_ante"],
        ),
        "log_score": _weighted(
            F.smooth_l1_loss(
                output.log_score, target_tensors["log_score"], reduction="none"
            ),
            target_masks["log_score"],
            target_weights["log_score"],
        ),
    }
    total = (
        weights.policy * losses["policy"]
        + weights.paired_utility * losses["paired_utility"]
        + weights.ordering * losses["ordering"]
        + weights.current_blind * losses["current_blind"]
        + weights.next_boss * losses["next_boss"]
        + weights.ante8 * losses["ante8"]
        + weights.endless_ante * losses["endless_ante"]
        + weights.log_score * losses["log_score"]
    )
    metrics = {f"{name}_loss": float(value.detach()) for name, value in losses.items()}
    metrics["loss"] = float(total.detach())
    metrics["victory_targets"] = float(target_masks["ante8"].sum().item())
    metrics["endless_targets"] = float(target_masks["endless_ante"].sum().item())
    return total, metrics


def fit_strategy_calibration(
    model: RelationalStrategyPolicyValue,
    records: Sequence[StrategyTeacherRecord],
) -> tuple[StrategyCalibration, dict[str, object]]:
    """Fit deterministic post-hoc transforms on calibration groups only."""

    if not records:
        raise ValueError("strategy calibration split is empty")
    if model.calibration.calibrated:
        raise ValueError("strategy model is already calibrated")
    predictions = _predict(model, records)
    policy_temperature = 1.0
    current_predictions, current_targets, current_weights = _flatten_head(
        predictions["current_blind"], records, "current_blind"
    )
    current_bias, current_temperature = _binary_calibration(
        current_predictions, current_targets, current_weights
    )
    boss_predictions, boss_targets, boss_weights = _flatten_head(
        predictions["next_boss"], records, "next_boss"
    )
    boss_bias, boss_temperature = _binary_calibration(
        boss_predictions, boss_targets, boss_weights
    )
    ante8_predictions, ante8_targets, ante8_weights = _flatten_head(
        predictions["ante8"], records, "ante8"
    )
    ante8_bias, ante8_temperature = _binary_calibration(
        ante8_predictions, ante8_targets, ante8_weights
    )
    endless_predictions, endless_targets, endless_weights = _flatten_head(
        predictions["endless_ante"], records, "endless_ante"
    )
    endless_bias = _mean_residual(endless_predictions, endless_targets, endless_weights)
    score_predictions, score_targets, score_weights = _flatten_head(
        predictions["log_score"], records, "log_score"
    )
    score_bias = _mean_residual(score_predictions, score_targets, score_weights)
    provisional = StrategyCalibration(
        policy_temperature=policy_temperature,
        current_blind_bias=current_bias,
        current_blind_temperature=current_temperature,
        next_boss_bias=boss_bias,
        next_boss_temperature=boss_temperature,
        ante8_bias=ante8_bias,
        ante8_temperature=ante8_temperature,
        endless_ante_bias=endless_bias,
        log_score_bias=score_bias,
        policy_override_margin=0.0,
        calibrated=True,
    )
    model.calibration = provisional
    calibrated_predictions = _predict(model, records)
    margin = _safe_utility_margin(calibrated_predictions["policy"], records)
    calibration = replace(provisional, policy_override_margin=margin)
    model.calibration = calibration
    metrics = evaluate_strategy_model(model, records)
    metrics["error_radii"] = _error_radii(model, records)
    return calibration, metrics


def evaluate_strategy_model(
    model: RelationalStrategyPolicyValue,
    records: Sequence[StrategyTeacherRecord],
) -> dict[str, object]:
    if not records:
        raise ValueError("strategy evaluation split is empty")
    predictions = _predict(model, records)
    policy_rows = predictions["policy"]
    row_weights = _run_equal_numeric_weights(records)
    agreements = 0.0
    recommendations = 0
    recommendation_errors = 0
    false_tie_overrides = 0
    recommended_utility_gain = 0.0
    recommendation_regret = 0.0
    recommendation_weight = 0.0
    recommendation_groups: set[str] = set()
    for logits, record, row_weight in zip(
        policy_rows, records, row_weights, strict=True
    ):
        top = max(range(len(logits)), key=logits.__getitem__)
        agreements += row_weight * int(top == record.selected_index)
        margin = logits[top] - logits[record.baseline_index]
        if (
            top != record.baseline_index
            and margin > model.calibration.policy_override_margin
        ):
            recommendations += 1
            recommendation_groups.add(record.run_group)
            baseline_target = _paired_target(record, record.baseline_index)
            top_target = _paired_target(record, top)
            selected_target = _paired_target(record, record.selected_index)
            gain = top_target - baseline_target
            regret = max(0.0, selected_target - top_target)
            recommendation_errors += int(
                top != record.selected_index or gain <= 0.0 or regret > 1e-9
            )
            false_tie_overrides += int(abs(gain) <= 1e-12)
            recommended_utility_gain += row_weight * gain
            recommendation_regret += row_weight * regret
            recommendation_weight += row_weight

    flattened = {
        name: _flatten_head(predictions[name], records, name)
        for name in (
            "current_blind",
            "next_boss",
            "ante8",
            "endless_ante",
            "log_score",
        )
    }
    metrics: dict[str, object] = {
        "records": len(records),
        "groups": len({record.run_group for record in records}),
        "weighting": "inverse_eligible_targets_per_run_and_head",
        "policy": {
            "agreement": agreements / sum(row_weights),
            "recommendations": recommendations,
            "recommendation_groups": len(recommendation_groups),
            "recommendation_errors": recommendation_errors,
            "false_tie_overrides": false_tie_overrides,
            "mean_recommended_utility_gain": (
                recommended_utility_gain / recommendation_weight
                if recommendation_weight
                else 0.0
            ),
            "mean_recommendation_regret": (
                recommendation_regret / recommendation_weight
                if recommendation_weight
                else 0.0
            ),
            "override_margin": model.calibration.policy_override_margin,
        },
        "current_blind": _binary_metrics(*flattened["current_blind"]),
        "next_boss": _binary_metrics(*flattened["next_boss"]),
        "ante8": _binary_metrics(*flattened["ante8"]),
        "endless_ante": _regression_metrics(*flattened["endless_ante"]),
        "log_score": _regression_metrics(*flattened["log_score"]),
    }
    strata: dict[str, list[StrategyTeacherRecord]] = {}
    for record in records:
        key = f"{record.observation.phase.value}:ante{record.observation.ante}"
        strata.setdefault(key, []).append(record)
    metrics["strata"] = {
        key: {"records": len(rows), "teacher_selection_rate": _selection_rate(rows)}
        for key, rows in sorted(strata.items())
    }
    return metrics


def _predict(
    model: RelationalStrategyPolicyValue,
    records: Sequence[StrategyTeacherRecord],
) -> dict[str, list]:
    tensorizer = PublicStrategyTensorizer(model.config)
    batch = tensorizer.tensorize(
        tuple(record.observation for record in records),
        tuple(
            tuple(candidate.action for candidate in record.candidates)
            for record in records
        ),
        tuple(
            tuple(candidate.intent for candidate in record.candidates)
            for record in records
        ),
        tuple(record.context for record in records),
    )
    model.eval()
    with torch.no_grad():
        output = model(batch)
    return {
        "policy": [
            output.policy_logits[index, : len(record.candidates)]
            .detach()
            .cpu()
            .tolist()
            for index, record in enumerate(records)
        ],
        "current_blind": _unpadded(output.current_blind_survival, records),
        "next_boss": _unpadded(output.next_boss_survival, records),
        "ante8": _unpadded(output.ante8_win, records),
        "endless_ante": _unpadded(output.endless_ante, records),
        "log_score": _unpadded(output.log_score, records),
    }


def _selected_targets(record: StrategyTeacherRecord) -> tuple[float, float]:
    samples = record.candidates[record.selected_index].samples
    count = len(samples)
    return (
        sum(sample.current_blind_clear for sample in samples) / count,
        sum(sample.next_boss_clear for sample in samples) / count,
    )


def _unpadded(
    tensor: Tensor, records: Sequence[StrategyTeacherRecord]
) -> list[list[float]]:
    return [
        tensor[index, : len(record.candidates)].detach().cpu().tolist()
        for index, record in enumerate(records)
    ]


def _candidate_target(
    record: StrategyTeacherRecord, candidate_index: int, name: str
) -> float | None:
    field = {
        "current_blind": "current_blind_clear",
        "next_boss": "next_boss_clear",
        "ante8": "ante8_win",
        "endless_ante": "endless_ante",
        "log_score": "log_score",
    }.get(name)
    if field is None:
        raise ValueError(f"unsupported strategy target head {name!r}")
    values = [
        getattr(sample, field) for sample in record.candidates[candidate_index].samples
    ]
    admitted = [float(value) for value in values if value is not None]
    if not admitted:
        return None
    return sum(admitted) / len(admitted)


def _paired_target(record: StrategyTeacherRecord, candidate_index: int) -> float:
    candidate = record.candidates[candidate_index].samples
    baseline = record.candidates[record.baseline_index].samples
    if len(candidate) != len(baseline):
        raise ValueError("paired utility targets have unequal sample counts")
    return sum(
        sample.search_utility - baseline_sample.search_utility
        for sample, baseline_sample in zip(candidate, baseline, strict=True)
    ) / len(candidate)


def _paired_utility_losses(
    logits: Tensor,
    records: Sequence[StrategyTeacherRecord],
) -> tuple[Tensor, Tensor]:
    """Run/decision/alternative-equal paired utility and ordering losses."""

    decisions_per_run = Counter(record.run_group for record in records)
    losses: list[Tensor] = []
    ordering: list[Tensor] = []
    weights: list[float] = []
    for row, record in enumerate(records):
        alternatives = [
            index
            for index in range(len(record.candidates))
            if index != record.baseline_index
        ]
        if not alternatives:
            continue
        baseline_logit = logits[row, record.baseline_index]
        weight = 1.0 / decisions_per_run[record.run_group] / len(alternatives)
        for index in alternatives:
            target = _paired_target(record, index)
            prediction = logits[row, index] - baseline_logit
            losses.append(F.smooth_l1_loss(prediction, prediction.new_tensor(target)))
            ordering.append(
                F.softplus(-math.copysign(1.0, target) * prediction)
                if abs(target) > 1e-12
                else prediction.square()
            )
            weights.append(weight)
    if not losses:
        zero = logits.sum() * 0.0
        return zero, zero
    weight_tensor = logits.new_tensor(weights)
    return (
        torch.stack(losses).mul(weight_tensor).sum() / weight_tensor.sum(),
        torch.stack(ordering).mul(weight_tensor).sum() / weight_tensor.sum(),
    )


def _candidate_target_tensors(
    records: Sequence[StrategyTeacherRecord], name: str, device: torch.device
) -> tuple[Tensor, Tensor]:
    width = max(len(record.candidates) for record in records)
    targets = torch.zeros((len(records), width), dtype=torch.float32, device=device)
    mask = torch.zeros((len(records), width), dtype=torch.bool, device=device)
    for row, record in enumerate(records):
        for candidate_index in range(len(record.candidates)):
            value = _candidate_target(record, candidate_index, name)
            if value is not None:
                targets[row, candidate_index] = value
                mask[row, candidate_index] = True
    return targets, mask


def _run_equal_candidate_weights(
    records: Sequence[StrategyTeacherRecord], mask: Tensor, device: torch.device
) -> Tensor:
    counts: Counter[str] = Counter()
    for row, record in enumerate(records):
        counts[record.run_group] += int(mask[row].sum().item())
    weights = torch.zeros_like(mask, dtype=torch.float32, device=device)
    for row, record in enumerate(records):
        count = counts[record.run_group]
        if count:
            weights[row, mask[row]] = 1.0 / count
    return weights


def _flatten_head(
    predictions: Sequence[Sequence[float]],
    records: Sequence[StrategyTeacherRecord],
    name: str,
) -> tuple[list[float], list[float], list[float]]:
    predicted: list[float] = []
    targets: list[float] = []
    groups: list[str] = []
    for row, record in zip(predictions, records, strict=True):
        if len(row) != len(record.candidates):
            raise ValueError("strategy prediction width disagrees with candidates")
        for candidate_index, value in enumerate(row):
            target = _candidate_target(record, candidate_index, name)
            if target is not None:
                predicted.append(float(value))
                targets.append(target)
                groups.append(record.run_group)
    counts = Counter(groups)
    weights = [1.0 / counts[group] for group in groups]
    return predicted, targets, weights


def _run_equal_weights(
    records: Sequence[StrategyTeacherRecord], device: torch.device
) -> Tensor:
    counts = Counter(record.run_group for record in records)
    return torch.tensor(
        [1.0 / counts[record.run_group] for record in records],
        dtype=torch.float32,
        device=device,
    )


def _run_equal_numeric_weights(
    records: Sequence[StrategyTeacherRecord],
) -> list[float]:
    counts = Counter(record.run_group for record in records)
    return [1.0 / counts[record.run_group] for record in records]


def _weighted_mean(values: Sequence[float], weights: Sequence[float]) -> float:
    if len(values) != len(weights) or not values:
        raise ValueError("weighted metric inputs must be equally sized and non-empty")
    denominator = sum(weights)
    if denominator <= 0 or not math.isfinite(denominator):
        raise ValueError("weighted metric denominator must be positive and finite")
    return (
        sum(value * weight for value, weight in zip(values, weights, strict=True))
        / denominator
    )


def _weighted(values: Tensor, mask: Tensor, weights: Tensor) -> Tensor:
    admitted = weights * mask.float()
    if not bool(mask.any()):
        return values.sum() * 0.0
    return (values * admitted).sum() / admitted.sum()


def _binary_loss(prediction: Tensor, target: Tensor) -> Tensor:
    prediction = prediction.clamp(1e-6, 1 - 1e-6)
    return -(target * prediction.log() + (1 - target) * (1 - prediction).log())


def _tensor(values: Sequence[float], device: torch.device) -> Tensor:
    return torch.tensor(values, dtype=torch.float32, device=device)


def _group_digest(groups: tuple[str, ...]) -> str:
    return hashlib.sha256("\n".join(sorted(groups)).encode()).hexdigest()


def _policy_temperature(
    logits: Sequence[Sequence[float]],
    records,
    weights: Sequence[float],
) -> float:
    candidates = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0)

    def loss(temperature: float) -> float:
        losses = []
        for row, record in zip(logits, records, strict=True):
            scaled = torch.tensor(row) / temperature
            losses.append(
                float(
                    F.cross_entropy(
                        scaled.unsqueeze(0), torch.tensor([record.selected_index])
                    )
                )
            )
        return _weighted_mean(losses, weights)

    return min(candidates, key=loss)


def _binary_calibration(
    probabilities: Sequence[float], targets: Sequence[float], weights: Sequence[float]
) -> tuple[float, float]:
    if not probabilities:
        return 0.0, 1.0
    temperatures = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0)
    biases = (-2.0, -1.0, -0.5, 0.0, 0.5, 1.0, 2.0)
    logits = [_logit(value) for value in probabilities]

    def loss(pair: tuple[float, float]) -> float:
        bias, temperature = pair
        calibrated = [_sigmoid((value + bias) / temperature) for value in logits]
        return _binary_metrics(calibrated, targets, weights)["log_loss"]

    return min(((bias, temp) for bias in biases for temp in temperatures), key=loss)


def _mean_residual(
    predictions: Sequence[float],
    targets: Sequence[float],
    weights: Sequence[float],
) -> float:
    if not predictions:
        return 0.0
    return _weighted_mean(
        [
            target - prediction
            for prediction, target in zip(predictions, targets, strict=True)
        ],
        weights,
    )


def _safe_utility_margin(
    policy_rows: Sequence[Sequence[float]],
    records: Sequence[StrategyTeacherRecord],
) -> float:
    unsafe_margins = []
    for logits, record in zip(policy_rows, records, strict=True):
        baseline = record.baseline_index
        selected_target = _paired_target(record, record.selected_index)
        for index in range(len(logits)):
            if index == baseline:
                continue
            predicted_gain = logits[index] - logits[baseline]
            actual_gain = _paired_target(record, index)
            if (
                index != record.selected_index
                or actual_gain <= 0.0
                or actual_gain < selected_target - 1e-9
            ):
                unsafe_margins.append(predicted_gain)
    return max(0.0, max(unsafe_margins, default=0.0)) + (
        1e-6 if unsafe_margins else 0.0
    )


def _binary_metrics(
    predictions: Sequence[float],
    targets: Sequence[float],
    weights: Sequence[float],
) -> dict[str, float]:
    if not predictions:
        return {"count": 0.0, "brier": 0.0, "log_loss": 0.0}
    clipped = [min(1 - 1e-6, max(1e-6, value)) for value in predictions]
    return {
        "count": float(len(clipped)),
        "brier": _weighted_mean(
            [
                (value - target) ** 2
                for value, target in zip(clipped, targets, strict=True)
            ],
            weights,
        ),
        "log_loss": _weighted_mean(
            [
                -(target * math.log(value) + (1 - target) * math.log(1 - value))
                for value, target in zip(clipped, targets, strict=True)
            ],
            weights,
        ),
    }


def _regression_metrics(
    predictions: Sequence[float],
    targets: Sequence[float],
    weights: Sequence[float],
) -> dict[str, float]:
    if not predictions:
        return {"count": 0.0, "mae": 0.0, "rmse": 0.0}
    errors = [
        prediction - target
        for prediction, target in zip(predictions, targets, strict=True)
    ]
    return {
        "count": float(len(errors)),
        "mae": _weighted_mean([abs(error) for error in errors], weights),
        "rmse": math.sqrt(_weighted_mean([error * error for error in errors], weights)),
    }


def _error_radii(
    model: RelationalStrategyPolicyValue,
    records: Sequence[StrategyTeacherRecord],
) -> dict[str, float]:
    predictions = _predict(model, records)

    def radius(predicted: Sequence[float], actual: Sequence[float]) -> float:
        return max(
            (abs(left - right) for left, right in zip(predicted, actual, strict=True)),
            default=0.0,
        )

    result: dict[str, float] = {}
    for name in (
        "current_blind",
        "next_boss",
        "ante8",
        "endless_ante",
        "log_score",
    ):
        predicted, actual, _ = _flatten_head(predictions[name], records, name)
        result[name] = radius(predicted, actual)
    return result


def _selection_rate(records: Sequence[StrategyTeacherRecord]) -> float:
    weights = _run_equal_numeric_weights(records)
    return _weighted_mean(
        [float(record.selected_index != record.baseline_index) for record in records],
        weights,
    )


def _logit(value: float) -> float:
    clipped = min(1 - 1e-6, max(1e-6, value))
    return math.log(clipped / (1 - clipped))


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1 + exponential)


__all__ = [
    "StrategyDatasetSplit",
    "StrategyLossWeights",
    "evaluate_strategy_model",
    "fit_strategy_calibration",
    "split_teacher_records",
    "strategy_training_loss",
]
