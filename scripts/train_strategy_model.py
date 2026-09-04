#!/usr/bin/env python3
"""Train and calibrate the relational strategy model on complete public runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import torch

from balatro_ai_v2.strategy_learning import (
    StrategyLossWeights,
    evaluate_strategy_model,
    fit_strategy_calibration,
    split_teacher_records,
    strategy_training_loss,
)
from balatro_ai_v2.strategy_model import (
    STRATEGY_MODEL_SCHEMA_DIGEST,
    RelationalStrategyPolicyValue,
    StrategyModelConfig,
    save_strategy_model,
)
from balatro_ai_v2.strategy_teacher import read_teacher_records


def main() -> None:
    args = build_parser().parse_args()
    _validate_args(args)
    for path in (args.output_model, args.report_json):
        if path is not None and path.exists():
            raise SystemExit(f"refusing to overwrite existing output: {path}")

    dataset_digest = hashlib.sha256(args.input_jsonl.read_bytes()).hexdigest()
    records = read_teacher_records(args.input_jsonl)
    collection_digest, collection = _load_collection_report(
        args.collection_report,
        dataset_digest,
        records,
    )
    teacher_config_digest = collection["strategy_teacher_dataset"][
        "teacher_config_digest"
    ]
    if {record.teacher_config_digest for record in records} != {teacher_config_digest}:
        raise SystemExit("teacher records disagree with the collection configuration")
    split = split_teacher_records(
        records,
        train_groups=args.train_groups,
        calibration_groups=args.calibration_groups,
        holdout_groups=args.holdout_groups,
        nonce=args.split_nonce,
    )
    torch.manual_seed(args.training_seed)
    config = StrategyModelConfig(
        hidden_size=args.hidden_size,
        attention_heads=args.attention_heads,
        attention_layers=args.attention_layers,
        feedforward_size=args.feedforward_size,
        dropout=0.0,
        max_entities=args.max_entities,
        max_actions=args.max_actions,
    )
    model = RelationalStrategyPolicyValue(config).to(args.device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=args.learning_rate,
        weight_decay=args.weight_decay,
    )
    loss_weights = StrategyLossWeights()
    losses: list[dict[str, float]] = []
    for _ in range(args.epochs):
        model.train()
        loss, metrics = strategy_training_loss(model, split.train, weights=loss_weights)
        if not torch.isfinite(loss):
            raise RuntimeError("strategy training loss became non-finite")
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        gradient_norm = torch.nn.utils.clip_grad_norm_(
            model.parameters(), args.max_gradient_norm
        )
        if not torch.isfinite(gradient_norm):
            raise RuntimeError("strategy training gradient became non-finite")
        optimizer.step()
        metrics["gradient_norm"] = float(gradient_norm)
        losses.append(metrics)

    calibration, calibration_metrics = fit_strategy_calibration(
        model, split.calibration
    )
    holdout_metrics = evaluate_strategy_model(model, split.holdout)
    baseline_metrics = empirical_baseline_metrics(split.train, split.holdout)
    gate = calibration_gate(holdout_metrics, baseline_metrics)
    split_manifest = split.manifest()
    provenance = {
        "training_status": "trained",
        "influence_mode": "shadow",
        "dataset_sha256": dataset_digest,
        "collection_report_sha256": collection_digest,
        "teacher_config_digest": teacher_config_digest,
        "strategy_model_schema_digest": STRATEGY_MODEL_SCHEMA_DIGEST,
        "split": split_manifest,
        "trainer": {
            "training_seed": args.training_seed,
            "split_nonce": args.split_nonce,
            "epochs": args.epochs,
            "learning_rate": args.learning_rate,
            "weight_decay": args.weight_decay,
            "max_gradient_norm": args.max_gradient_norm,
            "device": args.device,
            "python_version": platform.python_version(),
            "torch_version": str(torch.__version__),
            "source_digest": collection["manifest"]["source_digest"],
            "loss_weights": asdict(loss_weights),
        },
        "calibration": {
            "parameters": asdict(calibration),
            "metrics": calibration_metrics,
            "holdout_metrics": holdout_metrics,
            "empirical_baseline_metrics": baseline_metrics,
            "gate": gate,
        },
    }
    model.provenance = provenance
    artifact_digest = save_strategy_model(args.output_model, model)
    report = {
        "candidate_only": True,
        "influence_mode": "shadow",
        "promotion_eligible": False,
        "dataset": {
            "path": str(args.input_jsonl.resolve()),
            "sha256": dataset_digest,
            "records": len(records),
            "groups": len({record.run_group for record in records}),
            "collection_report_sha256": collection_digest,
        },
        "split": split_manifest,
        "config": asdict(config),
        "loss_weights": asdict(loss_weights),
        "losses": losses,
        "calibration": asdict(calibration),
        "calibration_metrics": calibration_metrics,
        "holdout_metrics": holdout_metrics,
        "empirical_baseline_metrics": baseline_metrics,
        "calibration_gate": gate,
        "artifact": {
            "path": str(args.output_model.resolve()),
            "sha256": artifact_digest,
            "schema_digest": STRATEGY_MODEL_SCHEMA_DIGEST,
        },
    }
    encoded = json.dumps(report, sort_keys=True, allow_nan=False)
    print(encoded)
    if args.report_json is not None:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        with args.report_json.open("x", encoding="utf-8") as handle:
            handle.write(encoded + "\n")


def empirical_baseline_metrics(train, evaluated) -> dict[str, object]:
    """Fit simple train-only constants and score them on another run split."""

    def candidate_targets(records, field):
        rows = []
        for record in records:
            for candidate in record.candidates:
                values = [
                    getattr(sample, field)
                    for sample in candidate.samples
                    if getattr(sample, field) is not None
                ]
                if values:
                    rows.append(
                        (record.run_group, sum(float(value) for value in values) / len(values))
                    )
        counts: dict[str, int] = {}
        for group, _ in rows:
            counts[group] = counts.get(group, 0) + 1
        return (
            [value for _, value in rows],
            [1.0 / counts[group] for group, _ in rows],
        )

    train = tuple(train)
    evaluated = tuple(evaluated)
    evaluated_weights = _run_equal_weights(evaluated)
    train_current, train_current_weights = candidate_targets(
        train, "current_blind_clear"
    )
    train_boss, train_boss_weights = candidate_targets(train, "next_boss_clear")
    train_victory, train_victory_weights = candidate_targets(train, "ante8_win")
    train_endless, train_endless_weights = candidate_targets(train, "endless_ante")
    train_score, train_score_weights = candidate_targets(train, "log_score")
    evaluated_current, evaluated_current_weights = candidate_targets(
        evaluated, "current_blind_clear"
    )
    evaluated_boss, evaluated_boss_weights = candidate_targets(
        evaluated, "next_boss_clear"
    )
    evaluated_victory, evaluated_victory_weights = candidate_targets(
        evaluated, "ante8_win"
    )
    evaluated_endless, evaluated_endless_weights = candidate_targets(
        evaluated, "endless_ante"
    )
    evaluated_score, evaluated_score_weights = candidate_targets(
        evaluated, "log_score"
    )
    baseline_agreement = _weighted_mean(
        [float(record.baseline_index == record.selected_index) for record in evaluated],
        evaluated_weights,
    )
    return {
        "policy": {"agreement": baseline_agreement},
        "weighting": "inverse_eligible_targets_per_run_and_head",
        "current_blind": _constant_binary(
            train_current,
            evaluated_current,
            train_current_weights,
            evaluated_current_weights,
        ),
        "next_boss": _constant_binary(
            train_boss, evaluated_boss, train_boss_weights, evaluated_boss_weights
        ),
        "ante8": _constant_binary(
            train_victory,
            evaluated_victory,
            train_victory_weights,
            evaluated_victory_weights,
        ),
        "endless_ante": _constant_regression(
            train_endless,
            evaluated_endless,
            train_endless_weights,
            evaluated_endless_weights,
        ),
        "log_score": _constant_regression(
            train_score,
            evaluated_score,
            train_score_weights,
            evaluated_score_weights,
        ),
    }


def calibration_gate(
    model_metrics: dict[str, object],
    baseline_metrics: dict[str, object],
) -> dict[str, object]:
    """Report strict offline gates; never promote directly from this trainer."""

    head_checks: dict[str, bool] = {}
    for name in ("current_blind", "next_boss", "ante8"):
        model_head = model_metrics[name]
        baseline_head = baseline_metrics[name]
        assert isinstance(model_head, dict) and isinstance(baseline_head, dict)
        head_checks[name] = bool(model_head["count"]) and (
            float(model_head["brier"]) < float(baseline_head["brier"])
        )
    for name in ("endless_ante", "log_score"):
        model_head = model_metrics[name]
        baseline_head = baseline_metrics[name]
        assert isinstance(model_head, dict) and isinstance(baseline_head, dict)
        head_checks[name] = bool(model_head["count"]) and (
            float(model_head["mae"]) < float(baseline_head["mae"])
        )
    policy = model_metrics["policy"]
    baseline_policy = baseline_metrics["policy"]
    assert isinstance(policy, dict) and isinstance(baseline_policy, dict)
    positive_coverage = int(policy["recommendations"]) > 0
    policy_improves = float(policy["agreement"]) > float(baseline_policy["agreement"])
    zero_recommendation_errors = int(policy["recommendation_errors"]) == 0
    safe_policy = positive_coverage and policy_improves and zero_recommendation_errors
    all_heads = all(head_checks.values())
    return {
        "safe_policy_recommendations": safe_policy,
        "positive_recommendation_coverage": positive_coverage,
        "policy_agreement_beats_baseline": policy_improves,
        "zero_recommendation_errors": zero_recommendation_errors,
        "head_improvements": head_checks,
        "all_heads_beat_train_only_baselines": all_heads,
        "offline_gate_passed": safe_policy and all_heads,
        "authorizes_action_influence": False,
    }


def _load_collection_report(path: Path, dataset_digest: str, records) -> tuple[str, dict]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
        teacher = report["strategy_teacher_dataset"]
        benchmark = report["benchmark_protocol"]
        manifest = report["manifest"]
        runtime = report["candidate_runtime"]
        search = report["search_protocol"]
        results = report["results"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SystemExit("collection report is invalid") from exc
    if (
        not isinstance(report, dict)
        or not isinstance(teacher, dict)
        or not isinstance(benchmark, dict)
        or not isinstance(manifest, dict)
        or not isinstance(runtime, dict)
        or not isinstance(search, dict)
        or teacher.get("status") != "written"
        or teacher.get("sha256") != dataset_digest
        or teacher.get("contains_game_seeds") is not False
        or teacher.get("complete_runs_only") is not True
        or teacher.get("records") != len(records)
        or teacher.get("groups") != len({record.run_group for record in records})
        or not isinstance(teacher.get("teacher_config_digest"), str)
        or benchmark.get("seed_provenance") != "development"
        or benchmark.get("filtered_seeds") is not False
        or not isinstance(benchmark.get("panel_registry"), dict)
        or benchmark["panel_registry"].get("verification") != "registry_verified"
        or not isinstance(manifest.get("source_digest"), str)
        or not isinstance(manifest.get("backend"), dict)
        or not isinstance(runtime.get("revision"), str)
        or not isinstance(runtime.get("data_hashes"), dict)
        or not isinstance(search.get("version"), str)
        or not isinstance(results, list)
        or len(results) != teacher.get("groups")
        or any(
            not isinstance(row, dict)
            or row.get("complete") is not True
            or not isinstance(row.get("search"), dict)
            or row["search"].get("rejected_rollouts") != 0
            for row in results
        )
    ):
        raise SystemExit(
            "collection report does not bind a valid public teacher dataset"
        )
    success_teacher = search.get("success_teacher")
    if (
        isinstance(success_teacher, dict)
        and success_teacher.get("enabled") is True
        and success_teacher.get("affects_actions") is not False
    ):
        raise SystemExit("success teacher report does not prove action-inert collection")
    if isinstance(success_teacher, dict) and success_teacher.get("enabled") is True:
        coverage = teacher.get("coverage")
        if (
            not isinstance(coverage, dict)
            or coverage.get("training_coverage_passed") is not True
        ):
            raise SystemExit("success teacher dataset does not meet frozen coverage")
    return digest, report


def _constant_binary(
    train: list[float],
    evaluated: list[float],
    train_weights: list[float],
    evaluated_weights: list[float],
) -> dict[str, float]:
    if not train or not evaluated:
        return {"count": 0.0, "brier": 0.0, "log_loss": 0.0}
    prediction = min(1 - 1e-6, max(1e-6, _weighted_mean(train, train_weights)))
    return {
        "count": float(len(evaluated)),
        "brier": _weighted_mean(
            [(prediction - target) ** 2 for target in evaluated],
            evaluated_weights,
        ),
        "log_loss": _weighted_mean(
            [
                -(
                    target * math.log(prediction)
                    + (1 - target) * math.log(1 - prediction)
                )
                for target in evaluated
            ],
            evaluated_weights,
        ),
    }


def _constant_regression(
    train: list[float],
    evaluated: list[float],
    train_weights: list[float],
    evaluated_weights: list[float],
) -> dict[str, float]:
    if not train or not evaluated:
        return {"count": 0.0, "mae": 0.0, "rmse": 0.0}
    prediction = _weighted_mean(train, train_weights)
    errors = [prediction - target for target in evaluated]
    return {
        "count": float(len(evaluated)),
        "mae": _weighted_mean([abs(error) for error in errors], evaluated_weights),
        "rmse": math.sqrt(
            _weighted_mean([error * error for error in errors], evaluated_weights)
        ),
    }


def _run_equal_weights(records) -> list[float]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.run_group] = counts.get(record.run_group, 0) + 1
    return [1.0 / counts[record.run_group] for record in records]


def _weighted_mean(values: list[float], weights: list[float]) -> float:
    if len(values) != len(weights) or not values:
        raise ValueError("weighted inputs must be equally sized and non-empty")
    return sum(
        value * weight for value, weight in zip(values, weights, strict=True)
    ) / sum(weights)


def _validate_args(args: argparse.Namespace) -> None:
    integer_names = (
        "epochs",
        "training_seed",
        "train_groups",
        "calibration_groups",
        "holdout_groups",
        "hidden_size",
        "attention_heads",
        "attention_layers",
        "feedforward_size",
        "max_entities",
        "max_actions",
    )
    if any(getattr(args, name) < 1 for name in integer_names):
        raise SystemExit("training counts and model dimensions must be positive")
    if (
        not math.isfinite(args.learning_rate)
        or args.learning_rate <= 0
        or not math.isfinite(args.weight_decay)
        or args.weight_decay < 0
        or not math.isfinite(args.max_gradient_norm)
        or args.max_gradient_norm <= 0
    ):
        raise SystemExit("optimizer parameters are invalid")
    if args.split_nonce != "strategy-split-v2-predeclared":
        raise SystemExit("--split-nonce is frozen for this expert-iteration protocol")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-jsonl", type=Path, required=True)
    parser.add_argument("--collection-report", type=Path, required=True)
    parser.add_argument("--output-model", type=Path, required=True)
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--training-seed", type=int, default=20260904)
    parser.add_argument("--train-groups", type=int, default=8)
    parser.add_argument("--calibration-groups", type=int, default=2)
    parser.add_argument("--holdout-groups", type=int, default=2)
    parser.add_argument("--split-nonce", default="strategy-split-v2-predeclared")
    parser.add_argument("--hidden-size", type=int, default=64)
    parser.add_argument("--attention-heads", type=int, default=4)
    parser.add_argument("--attention-layers", type=int, default=2)
    parser.add_argument("--feedforward-size", type=int, default=128)
    parser.add_argument("--max-entities", type=int, default=256)
    parser.add_argument("--max-actions", type=int, default=512)
    parser.add_argument("--learning-rate", type=float, default=3e-4)
    parser.add_argument("--weight-decay", type=float, default=1e-4)
    parser.add_argument("--max-gradient-norm", type=float, default=1.0)
    parser.add_argument("--device", default="cpu")
    return parser


if __name__ == "__main__":
    main()
