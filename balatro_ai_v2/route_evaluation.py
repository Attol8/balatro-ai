"""Deterministic calibration and holdout gates for route residual models.

The functions in this module are deliberately offline and shadow-only.  They
score the exact stored candidate roots; they neither rebuild candidates nor
authorize an action or a certificate.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Iterable, Sequence

import torch

from balatro_ai_v2.route_learning import (
    RouteDatasetSplit,
    RoutePairedExample,
    _example_weights,
    route_paired_examples,
)
from balatro_ai_v2.route_learning_protocol import (
    CALIBRATION_CONFIG,
    HOLDOUT_GATE,
    SUPPORT_CELL_CONTRACT,
)
from balatro_ai_v2.route_model import RouteResidualCalibration
from balatro_ai_v2.strategy_engine import RunGoal, RunRoute
from balatro_ai_v2.strategy_model import (
    PublicStrategyTensorizer,
    RelationalStrategyPolicyValue,
)
from balatro_ai_v2.strategy_teacher import (
    StrategyTargetEndpoint,
    StrategyTeacherRecord,
)


ROUTE_RESIDUAL_HEADS = (
    "scalar",
    "current_blind",
    "next_boss",
    "ante8",
    "endless_ante",
    "log_score",
)
_TARGET_FOR_HEAD = {
    "scalar": "search_utility",
    "current_blind": "current_blind_clear",
    "next_boss": "next_boss_clear",
    "ante8": "ante8_win",
    "endless_ante": "endless_ante",
    "log_score": "log_score",
}
_CALIBRATION_FIELDS = {
    head: (f"{head}_bias", f"{head}_overprediction_radius")
    for head in ROUTE_RESIDUAL_HEADS
}
_WEIGHTING = str(CALIBRATION_CONFIG["weighting"])
_SIGN_WEIGHTING = "run-decision-pair-equal"

RouteSupportCell = tuple[str, str, str, int]


class RouteEvaluationError(ValueError):
    """The route model or its evaluation data cannot be evaluated safely."""


@dataclass(frozen=True, slots=True)
class _Prediction:
    example: RoutePairedExample
    raw: dict[str, float]


@dataclass(frozen=True, slots=True)
class _Atom:
    prediction: _Prediction
    sample_index: int
    target: float
    weight: float


def _canonical_records(
    records: Sequence[StrategyTeacherRecord],
) -> tuple[StrategyTeacherRecord, ...]:
    ordered = tuple(
        sorted(records, key=lambda row: (row.run_group, row.decision_index))
    )
    identities = [(row.run_group, row.decision_index) for row in ordered]
    if len(set(identities)) != len(identities):
        raise RouteEvaluationError("route evaluation contains duplicate decisions")
    return ordered


def _canonical_examples(
    records: Sequence[StrategyTeacherRecord],
) -> tuple[RoutePairedExample, ...]:
    examples = route_paired_examples(_canonical_records(records))
    return tuple(
        sorted(
            examples,
            key=lambda example: (
                example.record.run_group,
                example.record.decision_index,
                example.specialist_index,
            ),
        )
    )


def _predict_examples(
    model: RelationalStrategyPolicyValue,
    records: Sequence[StrategyTeacherRecord],
) -> tuple[_Prediction, ...]:
    ordered = _canonical_records(records)
    examples = _canonical_examples(ordered)
    if not examples:
        raise RouteEvaluationError("route evaluation split has no specialist pairs")
    tensorizer = PublicStrategyTensorizer(model.config)
    batch = tensorizer.tensorize(
        tuple(record.observation for record in ordered),
        tuple(
            tuple(candidate.action for candidate in record.candidates)
            for record in ordered
        ),
        tuple(
            tuple(candidate.intent for candidate in record.candidates)
            for record in ordered
        ),
        tuple(record.context for record in ordered),
        tuple(
            tuple(candidate.route for candidate in record.candidates)
            for record in ordered
        ),
    )
    training = model.training
    model.eval()
    try:
        with torch.no_grad():
            output = model(batch)
    finally:
        model.train(training)
    rows = {
        "scalar": output.policy_logits,
        "current_blind": output.current_blind_survival,
        "next_boss": output.next_boss_survival,
        "ante8": output.ante8_win,
        "endless_ante": output.endless_ante,
        "log_score": output.log_score,
    }
    predictions: list[_Prediction] = []
    for example in examples:
        raw = {
            head: float(
                (
                    values[example.record_index, example.specialist_index]
                    - values[example.record_index, example.ordinary_index]
                )
                .detach()
                .cpu()
                .item()
            )
            for head, values in rows.items()
        }
        if any(not math.isfinite(value) for value in raw.values()):
            raise RouteEvaluationError("route model produced a non-finite residual")
        predictions.append(_Prediction(example, raw))
    return tuple(predictions)


def _target_values(example: RoutePairedExample, head: str) -> tuple[float, ...] | None:
    if head == "scalar":
        return example.targets.scalar
    target_name = _TARGET_FOR_HEAD[head]
    if not all(example.targets.masks[target_name]):
        return None
    values = example.targets.heads[target_name]
    if any(value is None for value in values):
        raise RouteEvaluationError("route target mask admits a null sample")
    return tuple(float(value) for value in values if value is not None)


def _pair_weights(predictions: Sequence[_Prediction], head: str) -> tuple[float, ...]:
    examples = tuple(prediction.example for prediction in predictions)
    target_name = None if head == "scalar" else _TARGET_FOR_HEAD[head]
    return _example_weights(examples, head=target_name)


def _atoms(predictions: Sequence[_Prediction], head: str) -> tuple[_Atom, ...]:
    atoms: list[_Atom] = []
    for prediction, pair_weight in zip(
        predictions, _pair_weights(predictions, head), strict=True
    ):
        values = _target_values(prediction.example, head)
        if values is None:
            continue
        if not values:
            raise RouteEvaluationError("route pair has no paired samples")
        for sample_index, target in enumerate(values):
            atoms.append(
                _Atom(prediction, sample_index, target, pair_weight / len(values))
            )
    return tuple(atoms)


def _head_counts(predictions: Sequence[_Prediction], head: str) -> dict[str, int]:
    eligible: list[_Prediction] = []
    masked = 0
    null_mismatch_pairs = 0
    null_mismatch_samples = 0
    both_null_samples = 0
    target_name = _TARGET_FOR_HEAD[head]
    for prediction in predictions:
        example = prediction.example
        specialist = example.record.candidates[example.specialist_index]
        ordinary = example.record.candidates[example.ordinary_index]
        mismatched = 0
        both_null = 0
        for specialist_sample, ordinary_sample in zip(
            specialist.samples, ordinary.samples, strict=True
        ):
            left = getattr(specialist_sample, target_name)
            right = getattr(ordinary_sample, target_name)
            mismatched += int((left is None) != (right is None))
            both_null += int(left is None and right is None)
        null_mismatch_samples += mismatched
        both_null_samples += both_null
        if _target_values(example, head) is None:
            masked += 1
            null_mismatch_pairs += int(mismatched > 0)
        else:
            eligible.append(prediction)
    return {
        "groups": len({row.example.record.run_group for row in eligible}),
        "decisions": len(
            {
                (row.example.record.run_group, row.example.record.decision_index)
                for row in eligible
            }
        ),
        "pairs": len(eligible),
        "eligible_samples": sum(
            len(_target_values(row.example, head) or ()) for row in eligible
        ),
        "masked_pairs": masked,
        "null_mismatch_pairs": null_mismatch_pairs,
        "null_mismatch_samples": null_mismatch_samples,
        "both_null_samples": both_null_samples,
    }


def _weighted_mean(values: Iterable[tuple[float, float]]) -> float:
    rows = tuple(values)
    if not rows:
        raise RouteEvaluationError("weighted route metric has no observations")
    denominator = math.fsum(weight for _, weight in rows)
    if not math.isfinite(denominator) or denominator <= 0.0:
        raise RouteEvaluationError("route metric weights are invalid")
    value = math.fsum(item * weight for item, weight in rows) / denominator
    if not math.isfinite(value):
        raise RouteEvaluationError("route metric is non-finite")
    return value


def fit_route_residual_calibration(
    model: RelationalStrategyPolicyValue,
    records: Sequence[StrategyTeacherRecord],
) -> tuple[RouteResidualCalibration, dict[str, object]]:
    """Fit frozen additive biases and empirical one-sided radii."""

    predictions = _predict_examples(model, records)
    values: dict[str, float | bool] = {"calibrated": True}
    metrics: dict[str, object] = {}
    for head in ROUTE_RESIDUAL_HEADS:
        atoms = _atoms(predictions, head)
        counts = (
            {
                "groups": len(
                    {atom.prediction.example.record.run_group for atom in atoms}
                ),
                "decisions": len(
                    {
                        (
                            atom.prediction.example.record.run_group,
                            atom.prediction.example.record.decision_index,
                        )
                        for atom in atoms
                    }
                ),
                "pairs": len({id(atom.prediction) for atom in atoms}),
                "eligible_samples": len(atoms),
                "masked_pairs": 0,
                "null_mismatch_pairs": 0,
                "null_mismatch_samples": 0,
                "both_null_samples": 0,
            }
            if head == "scalar"
            else _head_counts(predictions, head)
        )
        if not atoms or counts["groups"] < 1 or counts["pairs"] < 1:
            raise RouteEvaluationError(f"route calibration head {head} has no support")
        bias = _weighted_mean(
            (
                atom.target - atom.prediction.raw[head],
                atom.weight,
            )
            for atom in atoms
        )
        overpredictions = tuple(
            max(0.0, atom.prediction.raw[head] + bias - atom.target) for atom in atoms
        )
        radius = max(overpredictions, default=0.0)
        bias_field, radius_field = _CALIBRATION_FIELDS[head]
        values[bias_field] = bias
        values[radius_field] = radius
        metrics[head] = {
            "bias": bias,
            "overprediction_radius": radius,
            **counts,
            "weighting": _WEIGHTING,
            "max_overprediction": radius,
            "empirical_only": True,
        }
    calibration = RouteResidualCalibration(**values)
    return calibration, metrics


def _cell(example: RoutePairedExample) -> RouteSupportCell:
    route = example.record.candidates[example.specialist_index].route
    if route is None or route == RunRoute.VICTORY:
        raise RouteEvaluationError("route example does not identify a specialist")
    return (
        route.value,
        example.record.goal.value,
        example.record.observation.phase.value,
        example.record.observation.ante,
    )


def _cell_data(cell: RouteSupportCell) -> dict[str, object]:
    return {
        "route": cell[0],
        "goal": cell[1],
        "phase": cell[2],
        "ante": cell[3],
    }


def _cell_split_metrics(
    examples: Sequence[RoutePairedExample],
) -> dict[RouteSupportCell, dict[str, object]]:
    by_cell: dict[RouteSupportCell, list[RoutePairedExample]] = defaultdict(list)
    for example in examples:
        by_cell[_cell(example)].append(example)
    result: dict[RouteSupportCell, dict[str, object]] = {}
    for cell, rows in by_cell.items():
        signs = Counter()
        cancelled_sensitive = 0
        for row in rows:
            mean = math.fsum(row.targets.scalar) / len(row.targets.scalar)
            if mean > 0.0:
                signs["positive"] += 1
            elif mean < 0.0:
                signs["negative"] += 1
            else:
                signs["zero"] += 1
                cancelled_sensitive += int(
                    any(value != 0.0 for value in row.targets.scalar)
                )
        result[cell] = {
            "pairs": len(rows),
            "groups": len({row.record.run_group for row in rows}),
            "positive_pairs": signs["positive"],
            "negative_pairs": signs["negative"],
            "zero_pairs": signs["zero"],
            "cancelled_sensitive_pairs": cancelled_sensitive,
        }
    return result


def route_support_cells(split: RouteDatasetSplit) -> tuple[dict[str, object], ...]:
    """Return exact, sorted support cells without authorizing Cartesian products."""

    names = ("train", "calibration", "holdout")
    metrics = {
        name: _cell_split_metrics(_canonical_examples(getattr(split, name)))
        for name in names
    }
    cells = sorted(set().union(*(set(rows) for rows in metrics.values())))
    reports: list[dict[str, object]] = []
    for cell in cells:
        by_split = {
            name: metrics[name].get(
                cell,
                {
                    "pairs": 0,
                    "groups": 0,
                    "positive_pairs": 0,
                    "negative_pairs": 0,
                    "zero_pairs": 0,
                    "cancelled_sensitive_pairs": 0,
                },
            )
            for name in names
        }
        mixed = (
            int(by_split["train"]["positive_pairs"])
            + int(by_split["calibration"]["positive_pairs"])
            >= 1
            and int(by_split["train"]["negative_pairs"])
            + int(by_split["calibration"]["negative_pairs"])
            >= 1
        )
        admitted = (
            int(by_split["train"]["pairs"])
            >= int(SUPPORT_CELL_CONTRACT["minimum_train_pairs"])
            and int(by_split["calibration"]["pairs"])
            >= int(SUPPORT_CELL_CONTRACT["minimum_calibration_pairs"])
            and int(by_split["holdout"]["pairs"])
            >= int(SUPPORT_CELL_CONTRACT["minimum_holdout_pairs"])
            and int(by_split["train"]["groups"])
            >= int(SUPPORT_CELL_CONTRACT["minimum_train_groups"])
            and int(by_split["calibration"]["groups"])
            >= int(SUPPORT_CELL_CONTRACT["minimum_calibration_groups"])
            and int(by_split["holdout"]["groups"])
            >= int(SUPPORT_CELL_CONTRACT["minimum_holdout_groups"])
            and mixed
        )
        reports.append(
            {
                **_cell_data(cell),
                "train": by_split["train"],
                "calibration": by_split["calibration"],
                "holdout": by_split["holdout"],
                "mixed_signs_before_holdout": mixed,
                "structurally_admitted": admitted,
                "safe_positive_holdout_recommendations": 0,
                "certifiable": False,
            }
        )
    return tuple(reports)


def _calibration_value(
    calibration: RouteResidualCalibration, head: str
) -> tuple[float, float]:
    bias_field, radius_field = _CALIBRATION_FIELDS[head]
    return (
        float(getattr(calibration, bias_field)),
        float(getattr(calibration, radius_field)),
    )


def _holdout_head_metrics(
    predictions: Sequence[_Prediction],
    calibration: RouteResidualCalibration,
    head: str,
) -> dict[str, object]:
    atoms = _atoms(predictions, head)
    counts = (
        {
            "groups": len({atom.prediction.example.record.run_group for atom in atoms}),
            "decisions": len(
                {
                    (
                        atom.prediction.example.record.run_group,
                        atom.prediction.example.record.decision_index,
                    )
                    for atom in atoms
                }
            ),
            "pairs": len({id(atom.prediction) for atom in atoms}),
            "eligible_samples": len(atoms),
            "masked_pairs": 0,
            "null_mismatch_pairs": 0,
            "null_mismatch_samples": 0,
            "both_null_samples": 0,
        }
        if head == "scalar"
        else _head_counts(predictions, head)
    )
    bias, radius = _calibration_value(calibration, head)
    if not atoms:
        return {
            **counts,
            "bias": bias,
            "overprediction_radius": radius,
            "weighting": _WEIGHTING,
            "model_mae": None,
            "zero_mae": None,
            "mae_improvement": None,
            "beats_zero": False,
            "max_overprediction": None,
            "radius_violations": 0,
            "within_calibration_radius": False,
        }
    errors = tuple(
        (abs(atom.prediction.raw[head] + bias - atom.target), atom.weight)
        for atom in atoms
    )
    zero_errors = tuple((abs(atom.target), atom.weight) for atom in atoms)
    model_mae = _weighted_mean(errors)
    zero_mae = _weighted_mean(zero_errors)
    overpredictions = tuple(
        max(0.0, atom.prediction.raw[head] + bias - atom.target) for atom in atoms
    )
    violations = sum(value > radius for value in overpredictions)
    return {
        **counts,
        "bias": bias,
        "overprediction_radius": radius,
        "weighting": _WEIGHTING,
        "model_mae": model_mae,
        "zero_mae": zero_mae,
        "mae_improvement": zero_mae - model_mae,
        "beats_zero": model_mae < zero_mae,
        "max_overprediction": max(overpredictions),
        "radius_violations": violations,
        "within_calibration_radius": violations == 0,
    }


def _scalar_sign_metrics(
    predictions: Sequence[_Prediction], bias: float
) -> dict[str, object]:
    pair_weights = _pair_weights(predictions, "scalar")
    rows: list[tuple[int, int, float]] = []
    cancelled_sensitive = 0
    zeros = 0
    for prediction, weight in zip(predictions, pair_weights, strict=True):
        target = math.fsum(prediction.example.targets.scalar) / len(
            prediction.example.targets.scalar
        )
        if target == 0.0:
            zeros += 1
            cancelled_sensitive += int(
                any(value != 0.0 for value in prediction.example.targets.scalar)
            )
            continue
        actual = 1 if target > 0.0 else -1
        corrected = prediction.raw["scalar"] + bias
        predicted = 1 if corrected > 0.0 else -1 if corrected < 0.0 else 0
        rows.append((actual, predicted, weight))
    positive = tuple(row for row in rows if row[0] > 0)
    negative = tuple(row for row in rows if row[0] < 0)

    def recall(items: Sequence[tuple[int, int, float]]) -> float | None:
        if not items:
            return None
        return _weighted_mean(
            (float(actual == predicted), weight) for actual, predicted, weight in items
        )

    positive_recall = recall(positive)
    negative_recall = recall(negative)
    balanced = (
        None
        if positive_recall is None or negative_recall is None
        else (positive_recall + negative_recall) / 2.0
    )
    threshold = float(HOLDOUT_GATE["balanced_sensitive_sign_accuracy_strictly_above"])
    return {
        "positive_pairs": len(positive),
        "negative_pairs": len(negative),
        "zero_pairs": zeros,
        "cancelled_sensitive_pairs": cancelled_sensitive,
        "weighting": _SIGN_WEIGHTING,
        "positive_recall": positive_recall,
        "negative_recall": negative_recall,
        "balanced_accuracy": balanced,
        "passes": balanced is not None and balanced > threshold,
    }


def _required_heads(goal: RunGoal) -> tuple[str, ...]:
    common = ("scalar", "current_blind", "next_boss")
    return (
        (*common, "ante8")
        if goal == RunGoal.VICTORY
        else (
            *common,
            "endless_ante",
            "log_score",
        )
    )


def _prediction_key(lower: dict[str, float], goal: RunGoal) -> tuple[float, ...]:
    if goal == RunGoal.VICTORY:
        return (
            lower["ante8"],
            lower["next_boss"],
            lower["current_blind"],
            lower["scalar"],
        )
    return (
        lower["endless_ante"],
        lower["next_boss"],
        lower["current_blind"],
        lower["scalar"],
        lower["log_score"],
    )


def _observed_safe(prediction: _Prediction) -> bool:
    example = prediction.example
    required = _required_heads(example.record.goal)
    if any(_target_values(example, head) is None for head in required):
        return False
    scalar = _target_values(example, "scalar")
    if scalar is None or math.fsum(scalar) / len(scalar) <= 0.0:
        return False
    for head in required[1:]:
        values = _target_values(example, head)
        if values is None or any(value < 0.0 for value in values):
            return False
    return True


def _available_target_key(
    prediction: _Prediction,
) -> tuple[tuple[str, ...], tuple[float, ...]]:
    example = prediction.example
    candidate = example.record.candidates[example.specialist_index]
    if example.record.goal == RunGoal.VICTORY:
        values = tuple(
            float(sample.endpoint == StrategyTargetEndpoint.VICTORY)
            for sample in candidate.samples
        )
        return ("victory_endpoint",), (math.fsum(values) / len(values),)
    alive = tuple(
        float(sample.endpoint != StrategyTargetEndpoint.DEATH)
        for sample in candidate.samples
    )
    endless = tuple(
        float(sample.endless_ante)
        for sample in candidate.samples
        if sample.endless_ante is not None
    )
    score = tuple(
        float(sample.log_score)
        for sample in candidate.samples
        if sample.log_score is not None
    )
    if len(endless) != len(candidate.samples) or len(score) != len(candidate.samples):
        raise RouteEvaluationError("endless regret key has unresolved targets")
    return (
        ("alive_endpoint", "endless_ante", "log_score"),
        (
            math.fsum(alive) / len(alive),
            math.fsum(endless) / len(endless),
            math.fsum(score) / len(score),
        ),
    )


def _recommendations(
    predictions: Sequence[_Prediction],
    calibration: RouteResidualCalibration,
    admitted_cells: set[RouteSupportCell],
) -> tuple[dict[str, object], Counter[RouteSupportCell]]:
    by_decision: dict[tuple[str, int], list[_Prediction]] = defaultdict(list)
    for prediction in predictions:
        record = prediction.example.record
        by_decision[(record.run_group, record.decision_index)].append(prediction)
    traces: list[dict[str, object]] = []
    opportunities = 0
    full_key_ties = 0
    unsupported_candidates = 0
    unresolved_guards = Counter[str]()
    cell_recommendations: Counter[RouteSupportCell] = Counter()
    for decision in sorted(by_decision):
        rows = sorted(
            by_decision[decision], key=lambda row: row.example.specialist_index
        )
        record = rows[0].example.record
        behavior = record.candidates[record.behavior_index]
        if behavior.intent is not None or behavior.route is not None:
            continue
        opportunities += 1
        eligible: list[tuple[tuple[float, ...], _Prediction, dict[str, float]]] = []
        for prediction in rows:
            example = prediction.example
            candidate = record.candidates[example.specialist_index]
            if (
                candidate.route is None
                or candidate.route == RunRoute.VICTORY
                or candidate.action != behavior.action
                or example.ordinary_index != record.behavior_index
                or _cell(example) not in admitted_cells
            ):
                unsupported_candidates += 1
                continue
            required = _required_heads(record.goal)
            missing = [
                head for head in required if _target_values(example, head) is None
            ]
            if missing:
                unresolved_guards.update(missing)
                continue
            lower = {}
            for head in ROUTE_RESIDUAL_HEADS:
                bias, radius = _calibration_value(calibration, head)
                lower[head] = prediction.raw[head] + bias - radius
            if not (
                lower["scalar"] > 0.0
                and lower["current_blind"] >= 0.0
                and lower["next_boss"] >= 0.0
                and (
                    lower["ante8"] >= 0.0
                    if record.goal == RunGoal.VICTORY
                    else lower["endless_ante"] >= 0.0 and lower["log_score"] >= 0.0
                )
            ):
                continue
            eligible.append((_prediction_key(lower, record.goal), prediction, lower))
        if not eligible:
            continue
        top_key = max(key for key, _, _ in eligible)
        winners = [row for row in eligible if row[0] == top_key]
        if len(winners) != 1:
            full_key_ties += 1
            continue
        _, recommendation, lower = winners[0]
        example = recommendation.example
        scalar_values = _target_values(example, "scalar")
        if scalar_values is None:  # pragma: no cover - scalar is always complete
            raise AssertionError("scalar route target is unexpectedly missing")
        scalar_gain = math.fsum(scalar_values) / len(scalar_values)
        ties = int(scalar_gain == 0.0)
        positive = int(scalar_gain > 0.0)
        survival_regressions = 0
        for head in ("current_blind", "next_boss"):
            values = _target_values(example, head)
            survival_regressions += int(
                values is None or any(value < 0.0 for value in values)
            )
        ante8_regression = 0
        endless_ante_regression = 0
        endless_log_score_regression = 0
        if record.goal == RunGoal.VICTORY:
            values = _target_values(example, "ante8")
            ante8_regression = int(
                values is None or any(value < 0.0 for value in values)
            )
        else:
            values = _target_values(example, "endless_ante")
            endless_ante_regression = int(
                values is None or any(value < 0.0 for value in values)
            )
            values = _target_values(example, "log_score")
            endless_log_score_regression = int(
                values is None or any(value < 0.0 for value in values)
            )

        same_action_safe = [
            row
            for row in rows
            if row.example.record.candidates[row.example.specialist_index].action
            == behavior.action
            and _cell(row.example) in admitted_cells
            and _observed_safe(row)
        ]
        regret = False
        regret_head: str | None = None
        regret_amount = 0.0
        best_index: int | None = None
        if same_action_safe:
            keyed = [(*_available_target_key(row), row) for row in same_action_safe]
            best_names, best_key, best = max(
                keyed, key=lambda row: (row[1], -row[2].example.specialist_index)
            )
            names, recommended_key = _available_target_key(recommendation)
            if names != best_names:
                raise RouteEvaluationError("route regret keys disagree within a goal")
            best_index = best.example.specialist_index
            if recommended_key < best_key:
                regret = True
                for name, best_value, selected_value in zip(
                    names, best_key, recommended_key, strict=True
                ):
                    if selected_value != best_value:
                        regret_head = name
                        regret_amount = best_value - selected_value
                        break
        cell = _cell(example)
        safe_positive = (
            positive == 1
            and ties == 0
            and survival_regressions == 0
            and ante8_regression == 0
            and endless_ante_regression == 0
            and endless_log_score_regression == 0
            and not regret
        )
        cell_recommendations[cell] += int(safe_positive)
        candidate = record.candidates[example.specialist_index]
        traces.append(
            {
                "run_group": record.run_group,
                "decision_index": record.decision_index,
                "candidate_index": example.specialist_index,
                "best_safe_candidate_index": best_index,
                "cell": _cell_data(cell),
                "goal": record.goal.value,
                "route": candidate.route.value if candidate.route is not None else None,
                "lower_bounds": {head: lower[head] for head in ROUTE_RESIDUAL_HEADS},
                "scalar_gain": scalar_gain,
                "positive_utility": positive == 1,
                "tie": ties == 1,
                "survival_regressions": survival_regressions,
                "ante8_regression": ante8_regression == 1,
                "endless_ante_regression": endless_ante_regression == 1,
                "endless_log_score_regression": endless_log_score_regression == 1,
                "victory_route": candidate.route == RunRoute.VICTORY,
                "rejected_root": False,
                "regret": regret,
                "regret_head": regret_head,
                "regret_amount": regret_amount,
                "safe_positive": safe_positive,
            }
        )
    groups = {trace["run_group"] for trace in traces}
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for trace in traces:
        grouped[str(trace["run_group"])].append(trace)

    def run_equal(field: str) -> float | None:
        if not grouped:
            return None
        return math.fsum(
            math.fsum(float(row[field]) for row in rows) / len(rows)
            for rows in grouped.values()
        ) / len(grouped)

    return (
        {
            "opportunities": opportunities,
            "recommendations": len(traces),
            "recommendation_groups": len(groups),
            "full_key_ties": full_key_ties,
            "unsupported_candidates": unsupported_candidates,
            "unresolved_required_guards": dict(sorted(unresolved_guards.items())),
            "positive_utility": sum(bool(row["positive_utility"]) for row in traces),
            "ties": sum(bool(row["tie"]) for row in traces),
            "survival_regressions": sum(
                int(row["survival_regressions"]) for row in traces
            ),
            "victory_routes": sum(bool(row["victory_route"]) for row in traces),
            "rejected_roots": sum(bool(row["rejected_root"]) for row in traces),
            "regrets": sum(bool(row["regret"]) for row in traces),
            "victory_ante8_regressions": sum(
                bool(row["ante8_regression"]) for row in traces
            ),
            "endless_ante_regressions": sum(
                bool(row["endless_ante_regression"]) for row in traces
            ),
            "endless_log_score_regressions": sum(
                bool(row["endless_log_score_regression"]) for row in traces
            ),
            "safe_positive_recommendations": sum(
                bool(row["safe_positive"]) for row in traces
            ),
            "safe_positive_groups": len(
                {row["run_group"] for row in traces if row["safe_positive"]}
            ),
            "mean_scalar_gain_run_equal": run_equal("scalar_gain"),
            "mean_regret_amount_run_equal": run_equal("regret_amount"),
            "weighting": "run-recommendation-equal",
            "traces": traces,
        },
        cell_recommendations,
    )


def evaluate_route_holdout(
    model: RelationalStrategyPolicyValue,
    split: RouteDatasetSplit,
    calibration: RouteResidualCalibration,
    *,
    calibration_metrics: dict[str, object] | None = None,
) -> dict[str, object]:
    """Evaluate the untouched holdout under the frozen conservative rule."""

    if calibration.calibrated is not True:
        raise RouteEvaluationError("route holdout calibration is incomplete")
    predictions = _predict_examples(model, split.holdout)
    heads = {
        head: _holdout_head_metrics(predictions, calibration, head)
        for head in ROUTE_RESIDUAL_HEADS
    }
    scalar_bias, _ = _calibration_value(calibration, "scalar")
    sign = _scalar_sign_metrics(predictions, scalar_bias)
    cells = list(route_support_cells(split))
    admitted = {
        (
            str(row["route"]),
            str(row["goal"]),
            str(row["phase"]),
            int(row["ante"]),
        )
        for row in cells
        if row["structurally_admitted"] is True
    }
    recommendations, cell_recommendations = _recommendations(
        predictions, calibration, admitted
    )
    for row in cells:
        cell = (
            str(row["route"]),
            str(row["goal"]),
            str(row["phase"]),
            int(row["ante"]),
        )
        safe = cell_recommendations[cell]
        row["safe_positive_holdout_recommendations"] = safe
        row["certifiable"] = row["structurally_admitted"] is True and safe > 0

    count = int(recommendations["recommendations"])
    gate = {
        "minimum_safe_recommendations": int(
            recommendations["safe_positive_recommendations"]
        )
        >= int(HOLDOUT_GATE["minimum_safe_recommendations"]),
        "minimum_safe_recommendation_groups": int(
            recommendations["safe_positive_groups"]
        )
        >= int(HOLDOUT_GATE["minimum_safe_recommendation_groups"]),
        "scalar_residual_mae_beats_zero": heads["scalar"]["beats_zero"] is True,
        "balanced_sensitive_sign_accuracy_strictly_above": sign["passes"] is True,
        "current_blind_residual_mae_diagnostic_only": heads["current_blind"][
            "model_mae"
        ]
        is not None,
        "next_boss_residual_mae_beats_zero": heads["next_boss"]["beats_zero"] is True,
        "recommendations_positive_utility": int(recommendations["positive_utility"])
        == count,
        "zero_ties": int(recommendations["ties"]) == 0,
        "zero_survival_regressions": int(recommendations["survival_regressions"]) == 0,
        "zero_victory_routes": int(recommendations["victory_routes"]) == 0,
        "zero_rejected_roots": int(recommendations["rejected_roots"]) == 0,
        "zero_regret_against_safe_specialist": int(recommendations["regrets"]) == 0,
        "victory_ante8_non_regression": int(
            recommendations["victory_ante8_regressions"]
        )
        == 0,
        "endless_ante_non_regression": int(recommendations["endless_ante_regressions"])
        == 0,
        "endless_log_score_non_regression": int(
            recommendations["endless_log_score_regressions"]
        )
        == 0,
        "all_overprediction_within_calibration_radii": all(
            row["within_calibration_radius"] is True for row in heads.values()
        ),
    }
    return {
        "calibration_contract": deepcopy(CALIBRATION_CONFIG),
        "calibration": {
            "parameters": asdict(calibration),
            "metrics": calibration_metrics,
        },
        "zero_baseline": {
            "residual": 0.0,
            "fitted": False,
            "contract": "literal_zero_on_identical_eligible_atoms",
        },
        "support_cells": cells,
        "holdout_heads": heads,
        "scalar_sign": sign,
        "recommendations": recommendations,
        "gate": {**gate, "passed": all(gate.values())},
    }


__all__ = [
    "RouteEvaluationError",
    "evaluate_route_holdout",
    "fit_route_residual_calibration",
    "route_support_cells",
]
