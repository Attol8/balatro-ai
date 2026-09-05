"""Public-only route residual examples and the frozen route learner loss."""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from typing import Sequence

import torch.nn.functional as F
from torch import Tensor

from balatro_ai_v2.route_learning_protocol import (
    OBJECTIVE_CONFIG,
    SPLIT_CONFIG,
)
from balatro_ai_v2.strategy_model import (
    PublicStrategyTensorizer,
    RelationalStrategyPolicyValue,
)
from balatro_ai_v2.strategy_teacher import StrategyTeacherRecord


TARGETS = (
    "search_utility",
    "current_blind_clear",
    "next_boss_clear",
    "ante8_win",
    "endless_ante",
    "log_score",
)
HEADS = TARGETS[1:]


class RouteLearningDataError(ValueError):
    """Authenticated route data cannot be admitted to learning."""


@dataclass(frozen=True, slots=True)
class RouteDatasetSplit:
    train: tuple[StrategyTeacherRecord, ...]
    calibration: tuple[StrategyTeacherRecord, ...]
    holdout: tuple[StrategyTeacherRecord, ...]
    train_groups: tuple[str, ...]
    calibration_groups: tuple[str, ...]
    holdout_groups: tuple[str, ...]

    def manifest(self) -> dict[str, object]:
        return {
            "train_batches": list(SPLIT_CONFIG["train_batches"]),
            "calibration_batches": list(SPLIT_CONFIG["calibration_batches"]),
            "holdout_batches": list(SPLIT_CONFIG["holdout_batches"]),
            "train_groups": list(self.train_groups),
            "calibration_groups": list(self.calibration_groups),
            "holdout_groups": list(self.holdout_groups),
            "train_group_sha256": _group_digest(self.train_groups),
            "calibration_group_sha256": _group_digest(self.calibration_groups),
            "holdout_group_sha256": _group_digest(self.holdout_groups),
        }


@dataclass(frozen=True, slots=True)
class RoutePairTargets:
    scalar: tuple[float, ...]
    heads: dict[str, tuple[float | None, ...]]
    masks: dict[str, tuple[bool, ...]]


@dataclass(frozen=True, slots=True)
class RoutePairedExample:
    record_index: int
    record: StrategyTeacherRecord
    specialist_index: int
    ordinary_index: int
    targets: RoutePairTargets


def _group_digest(groups: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(groups).encode()).hexdigest()


def _component_groups(component: object) -> tuple[str, ...]:
    if not isinstance(component, dict):
        raise RouteLearningDataError("merged route component is malformed")
    groups = component.get("opaque_groups")
    digest = component.get("opaque_group_sha256")
    if (
        not isinstance(groups, list)
        or not groups
        or any(
            not isinstance(group, str) or not group.startswith("origin-")
            for group in groups
        )
        or len(set(groups)) != len(groups)
        or groups != sorted(groups)
        or not isinstance(digest, str)
        or digest != _group_digest(groups)
    ):
        raise RouteLearningDataError("merged route component has invalid opaque groups")
    return tuple(groups)


def reconstruct_route_split(
    records: Sequence[StrategyTeacherRecord], merged_report: object
) -> RouteDatasetSplit:
    """Reconstruct the preregistered split from authenticated opaque membership."""

    if not isinstance(merged_report, dict):
        raise RouteLearningDataError("merged route report is malformed")
    components = merged_report.get("merged_components")
    if not isinstance(components, list) or len(components) != 5:
        raise RouteLearningDataError("merged route report has wrong component count")
    by_batch: dict[str, tuple[str, ...]] = {}
    for component in components:
        if not isinstance(component, dict):
            raise RouteLearningDataError("merged route component is malformed")
        batch = component.get("batch_id")
        if batch not in {f"batch-{i:02d}" for i in range(1, 6)} or batch in by_batch:
            raise RouteLearningDataError("merged route batch ids are invalid")
        by_batch[batch] = _component_groups(component)
    if list(by_batch) != [f"batch-{i:02d}" for i in range(1, 6)]:
        raise RouteLearningDataError("merged route batches are incomplete")
    all_groups = [group for groups in by_batch.values() for group in groups]
    if len(set(all_groups)) != len(all_groups):
        raise RouteLearningDataError("merged route groups overlap")
    record_groups = {record.run_group for record in records}
    if record_groups != set(all_groups):
        raise RouteLearningDataError("records disagree with merged opaque groups")
    split_groups = {
        "train": tuple(
            group
            for batch in SPLIT_CONFIG["train_batches"]
            for group in by_batch[batch]
        ),
        "calibration": tuple(
            group
            for batch in SPLIT_CONFIG["calibration_batches"]
            for group in by_batch[batch]
        ),
        "holdout": tuple(
            group
            for batch in SPLIT_CONFIG["holdout_batches"]
            for group in by_batch[batch]
        ),
    }
    if len(set().union(*map(set, split_groups.values()))) != len(all_groups):
        raise RouteLearningDataError("route split leaks groups")
    rows = {
        name: tuple(record for record in records if record.run_group in groups)
        for name, groups in split_groups.items()
    }
    if sum(map(len, rows.values())) != len(records):
        raise RouteLearningDataError("route split leaves records unassigned")
    return RouteDatasetSplit(
        rows["train"],
        rows["calibration"],
        rows["holdout"],
        split_groups["train"],
        split_groups["calibration"],
        split_groups["holdout"],
    )


def _targets(specialist, ordinary) -> RoutePairTargets:
    scalar = tuple(
        float(s.search_utility - o.search_utility)
        for s, o in zip(specialist.samples, ordinary.samples, strict=True)
    )
    values: dict[str, tuple[float | None, ...]] = {}
    masks: dict[str, tuple[bool, ...]] = {}
    for name in HEADS:
        paired = tuple(
            (
                None
                if getattr(s, name) is None or getattr(o, name) is None
                else float(getattr(s, name) - getattr(o, name))
            )
            for s, o in zip(specialist.samples, ordinary.samples, strict=True)
        )
        values[name] = paired
        pair_valid = all(value is not None for value in paired)
        masks[name] = (pair_valid,) * len(paired)
    return RoutePairTargets(scalar, values, masks)


def route_paired_examples(
    records: Sequence[StrategyTeacherRecord],
) -> tuple[RoutePairedExample, ...]:
    examples: list[RoutePairedExample] = []
    for record_index, record in enumerate(records):
        ordinary_by_action = [
            index
            for index, candidate in enumerate(record.candidates)
            if candidate.intent is None and candidate.route is None
        ]
        for index, candidate in enumerate(record.candidates):
            if candidate.route is None or candidate.route.value == "victory":
                continue
            matches = [
                ordinary
                for ordinary in ordinary_by_action
                if record.candidates[ordinary].action == candidate.action
            ]
            if len(matches) != 1:
                raise RouteLearningDataError(
                    "routed candidate lacks a unique ordinary comparator"
                )
            ordinary = matches[0]
            if len(candidate.samples) != len(record.candidates[ordinary].samples):
                raise RouteLearningDataError("paired route samples are unequal")
            examples.append(
                RoutePairedExample(
                    record_index,
                    record,
                    index,
                    ordinary,
                    _targets(candidate, record.candidates[ordinary]),
                )
            )
    return tuple(examples)


def route_pair_coverage(records: Sequence[StrategyTeacherRecord]) -> dict[str, object]:
    examples = route_paired_examples(records)
    return {
        "records": len(records),
        "groups": len({record.run_group for record in records}),
        "pairs": len(examples),
        "routes": dict(
            sorted(
                Counter(
                    example.record.candidates[example.specialist_index].route.value
                    for example in examples
                ).items()
            )
        ),
        "sensitive_scalar_pairs": sum(
            any(value != 0 for value in example.targets.scalar) for example in examples
        ),
        "masked_heads": {
            head: sum(not all(example.targets.masks[head]) for example in examples)
            for head in HEADS
        },
    }


def _example_weights(
    examples: Sequence[RoutePairedExample],
    *,
    head: str | None = None,
) -> tuple[float, ...]:
    eligible = tuple(
        example
        for example in examples
        if head is None or all(example.targets.masks[head])
    )
    eligible_decisions = {
        (example.record.run_group, example.record_index) for example in eligible
    }
    decisions_per_run = Counter(run_group for run_group, _ in eligible_decisions)
    pairs_per_decision = Counter(example.record_index for example in eligible)
    return tuple(
        (
            0.0
            if head is not None and not all(example.targets.masks[head])
            else 1.0
            / decisions_per_run[example.record.run_group]
            / pairs_per_decision[example.record_index]
        )
        for example in examples
    )


def route_training_loss(
    model: RelationalStrategyPolicyValue,
    records: Sequence[StrategyTeacherRecord],
) -> tuple[Tensor, dict[str, float]]:
    """Train only candidate-minus-matched-ordinary residuals."""

    if not records:
        raise ValueError("route training batch is empty")
    examples = route_paired_examples(records)
    if not examples:
        raise RouteLearningDataError("route training batch has no routed pairs")
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
        tuple(
            tuple(candidate.route for candidate in record.candidates)
            for record in records
        ),
    )
    output = model(batch)
    example_weights = _example_weights(examples)
    head_weights = {head: _example_weights(examples, head=head) for head in HEADS}
    losses: dict[str, list[Tensor]] = {name: [] for name in TARGETS}
    ordering_values: list[Tensor] = []
    ordering_weights: list[float] = []
    weights: dict[str, list[float]] = {name: [] for name in TARGETS}
    for example_index, (example, base_weight) in enumerate(
        zip(examples, example_weights, strict=True)
    ):
        row = example.record_index
        specialist = example.specialist_index
        ordinary = example.ordinary_index
        predictions = {
            "search_utility": output.policy_logits[row, specialist]
            - output.policy_logits[row, ordinary],
            "current_blind_clear": output.current_blind_survival[row, specialist]
            - output.current_blind_survival[row, ordinary],
            "next_boss_clear": output.next_boss_survival[row, specialist]
            - output.next_boss_survival[row, ordinary],
            "ante8_win": output.ante8_win[row, specialist]
            - output.ante8_win[row, ordinary],
            "endless_ante": output.endless_ante[row, specialist]
            - output.endless_ante[row, ordinary],
            "log_score": output.log_score[row, specialist]
            - output.log_score[row, ordinary],
        }
        weight = base_weight
        scalar_target = sum(example.targets.scalar) / len(example.targets.scalar)
        losses["search_utility"].append(
            F.smooth_l1_loss(
                predictions["search_utility"],
                predictions["search_utility"].new_tensor(scalar_target),
            )
        )
        weights["search_utility"].append(weight)
        if scalar_target:
            ordering_values.append(
                F.softplus(
                    -predictions["search_utility"]
                    * predictions["search_utility"].new_tensor(
                        1.0 if scalar_target > 0 else -1.0
                    )
                )
            )
            ordering_weights.append(weight)
        for head in HEADS:
            if all(example.targets.masks[head]):
                head_target = sum(example.targets.heads[head]) / len(
                    example.targets.heads[head]
                )
                losses[head].append(
                    F.smooth_l1_loss(
                        predictions[head], predictions[head].new_tensor(head_target)
                    )
                )
                weights[head].append(head_weights[head][example_index])
    result = output.policy_logits.new_zeros(())
    metrics: dict[str, float] = {}
    for name, values in losses.items():
        if not values:
            value = result.new_zeros(())
        else:
            value = sum(
                loss * weight
                for loss, weight in zip(values, weights[name], strict=True)
            ) / sum(weights[name])
        result = result + OBJECTIVE_CONFIG["weights"][name] * value
        metrics[f"{name}_loss"] = float(value.detach())
    ordering = (
        sum(
            value * weight
            for value, weight in zip(ordering_values, ordering_weights, strict=True)
        )
        / sum(ordering_weights)
        if ordering_values
        else result.new_zeros(())
    )
    result = result + OBJECTIVE_CONFIG["weights"]["ordering"] * ordering
    metrics["loss"] = float(result.detach())
    metrics["ordering_loss"] = float(ordering.detach())
    metrics["pairs"] = float(len(examples))
    return result, metrics
