from __future__ import annotations

import hashlib
import importlib.util
import json
from dataclasses import replace
from pathlib import Path

import pytest

from balatro_ai_v2.actions import LeaveShop, RerollShop
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.strategy_engine import RunGoal
from balatro_ai_v2.strategy_model import load_strategy_model
from balatro_ai_v2.strategy_options import StrategyIntent
from balatro_ai_v2.strategy_teacher import (
    StrategyRolloutTarget,
    StrategyTeacherCandidate,
    StrategyTeacherDraft,
    write_teacher_records,
)
from state_factory import state


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "train_strategy_model.py"
    spec = importlib.util.spec_from_file_location("train_strategy_model_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(index: int):
    observation = to_public_observation(state("SHOP", money=10))
    if index == 3:
        observation = replace(observation, ante=9, antes_cleared=8, won=True)
    goal = RunGoal.ENDLESS if observation.won else RunGoal.VICTORY
    draft = StrategyTeacherDraft(
        observation=observation,
        candidates=(
            StrategyTeacherCandidate(
                LeaveShop(),
                None,
                (StrategyRolloutTarget(0, 0, 0, observation.antes_cleared, 1),),
            ),
            StrategyTeacherCandidate(
                RerollShop(),
                StrategyIntent.ECONOMY,
                (StrategyRolloutTarget(1, 1, float(observation.won), 9, 3),),
            ),
        ),
        selected_index=index % 2,
        baseline_index=0,
        ordinary_index=0,
        behavior_index=index % 2,
        goal=goal,
        teacher_config_digest="3" * 64,
    )
    return draft.finalize(
        run_group=f"origin-{index:032x}",
        decision_index=0,
        run_complete=True,
        run_won=observation.won,
        terminal_ante=9 if observation.won else 3,
        best_hand_score=10_000,
    )


def test_training_cli_builds_reloadable_shadow_artifact(tmp_path, monkeypatch) -> None:
    script = _load_script()
    dataset = tmp_path / "teacher.jsonl"
    model_path = tmp_path / "strategy.pt"
    training_report = tmp_path / "training.json"
    collection_report = tmp_path / "collection.json"
    records = tuple(_record(index) for index in range(4))
    dataset_digest = write_teacher_records(dataset, records)
    collection_report.write_text(
        json.dumps(
            {
                "benchmark_protocol": {
                    "seed_provenance": "development",
                    "filtered_seeds": False,
                    "panel_registry": {"verification": "registry_verified"},
                },
                "manifest": {
                    "source_digest": "a" * 64,
                    "backend": {"name": "jackdaw"},
                },
                "candidate_runtime": {
                    "revision": "candidate",
                    "data_hashes": {"centers.json": "hash"},
                },
                "search_protocol": {"version": "determinized-search-v2"},
                "results": [
                    {"complete": True, "search": {"rejected_rollouts": 0}}
                    for _ in records
                ],
                "strategy_teacher_dataset": {
                    "status": "written",
                    "mode": "dense_paired_utility",
                    "sha256": dataset_digest,
                    "contains_game_seeds": False,
                    "complete_runs_only": True,
                    "records": len(records),
                    "groups": len(records),
                    "teacher_config_digest": "3" * 64,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        script.sys,
        "argv",
        [
            "train_strategy_model.py",
            "--input-jsonl",
            str(dataset),
            "--collection-report",
            str(collection_report),
            "--output-model",
            str(model_path),
            "--report-json",
            str(training_report),
            "--epochs",
            "1",
            "--train-groups",
            "2",
            "--calibration-groups",
            "1",
            "--holdout-groups",
            "1",
            "--hidden-size",
            "16",
            "--attention-heads",
            "4",
            "--attention-layers",
            "1",
            "--feedforward-size",
            "32",
            "--max-entities",
            "128",
            "--max-actions",
            "32",
            "--diagnostic",
            "--training-objective",
            "paired-utility-only",
            "--chunk-size",
            "2",
        ],
    )

    script.main()

    model = load_strategy_model(model_path)
    report = json.loads(training_report.read_text(encoding="utf-8"))
    assert model.calibration.calibrated
    assert model.provenance["training_status"] == "trained"
    assert model.provenance["influence_mode"] == "diagnostic"
    assert report["promotion_eligible"] is False
    assert (
        report["artifact"]["sha256"]
        == hashlib.sha256(model_path.read_bytes()).hexdigest()
    )
    assert report["dataset"]["sha256"] == dataset_digest
    assert report["objective"]["trained_outputs"] == ["policy_logits"]
    assert report["loss_weights"]["current_blind"] == 0.0
    assert model.provenance["trainer"]["chunk_size"] == 2


def test_training_cli_has_no_game_seed_or_private_state_arguments() -> None:
    script = _load_script()
    destinations = {action.dest for action in script.build_parser()._actions}
    source = (
        Path(__file__).resolve().parents[1] / "scripts" / "train_strategy_model.py"
    ).read_text(encoding="utf-8")

    assert "seed_start" not in destinations
    assert "game_seed" not in destinations
    assert "raw_state" not in source


def test_empirical_policy_baseline_weights_complete_runs_equally() -> None:
    script = _load_script()
    baseline = _record(0)
    alternative = _record(1)
    evaluated = tuple(replace(baseline, decision_index=index) for index in range(9)) + (
        alternative,
    )

    metrics = script.empirical_baseline_metrics((baseline, alternative), evaluated)

    assert metrics["weighting"] == "inverse_eligible_targets_per_run_and_head"
    assert metrics["policy"]["agreement"] == pytest.approx(0.5)


def test_policy_gate_rejects_vacuous_zero_coverage() -> None:
    script = _load_script()
    baseline = script.empirical_baseline_metrics(
        (_record(0), _record(1)), (_record(2), _record(3))
    )
    model_metrics = {
        **baseline,
        "policy": {
            "agreement": 1.0,
            "recommendations": 0,
            "recommendation_groups": 0,
            "recommendation_errors": 0,
            "false_tie_overrides": 0,
            "mean_recommended_utility_gain": 0.0,
            "mean_recommendation_regret": 0.0,
        },
    }

    gate = script.calibration_gate(model_metrics, baseline)

    assert not gate["positive_recommendation_coverage"]
    assert not gate["safe_policy_recommendations"]
    assert not gate["offline_gate_passed"]


def test_non_diagnostic_training_requires_exact_preregistered_contract() -> None:
    script = _load_script()
    args = script.build_parser().parse_args(
        [
            "--input-jsonl",
            "teacher.jsonl",
            "--collection-report",
            "collection.json",
            "--output-model",
            "model.pt",
            "--training-objective",
            "paired-utility-only",
        ]
    )
    weights, objective = script._training_objective(args.training_objective)
    contract = script._training_contract(args, weights, objective)
    collection = {
        "contextual_teacher_preregistration": {
            "immutable_batches": True,
            "training": contract,
        }
    }

    script._validate_preregistered_training(collection, contract)
    changed = {**contract, "epochs": 31}
    with pytest.raises(SystemExit, match="disagree"):
        script._validate_preregistered_training(collection, changed)


def test_dense_training_gate_recomputes_coverage_from_records() -> None:
    script = _load_script()
    original = _record(0)
    record = replace(
        original,
        candidates=tuple(
            replace(candidate, samples=candidate.samples * 6)
            for candidate in original.candidates
        ),
    )
    collection = {
        "strategy_teacher_dataset": {
            "coverage": {
                "winning_source_groups": 20,
                "dense_paired_utility": {
                    "records": 1,
                    "action_sensitive_rows": 1,
                    "action_sensitive_fraction": 1.0,
                    "phase_rows": {"SHOP": 1},
                    "stored_root_max": 2,
                    "candidate_space_max": 2,
                    "subset_rows": 0,
                    "observed_victory_origin_groups": 10,
                    "postwin_rows": 100,
                    "postwin_origin_groups": 20,
                },
            }
        }
    }

    with pytest.raises(SystemExit, match="disagrees with records"):
        script._validate_dense_collection_coverage(collection, (record,))
