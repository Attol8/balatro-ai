from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import torch
import balatro_ai_v2.strategy_learning as strategy_learning

from balatro_ai_v2.actions import LeaveShop, RerollShop
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.strategy_engine import RunGoal
from balatro_ai_v2.strategy_learning import (
    evaluate_strategy_model,
    fit_strategy_calibration,
    split_teacher_records,
    strategy_training_loss,
)
from balatro_ai_v2.strategy_model import (
    RelationalStrategyPolicyValue,
    StrategyCalibration,
    StrategyModelConfig,
)
from balatro_ai_v2.strategy_options import StrategyIntent
from balatro_ai_v2.strategy_teacher import (
    StrategyRolloutTarget,
    StrategyTeacherCandidate,
    StrategyTeacherDraft,
)
from state_factory import state


def _record(group: int, *, selected: int = 1, endless: bool = False):
    observation = to_public_observation(state("SHOP", money=10))
    goal = RunGoal.VICTORY
    if endless:
        observation = replace(observation, ante=9, antes_cleared=8, won=True)
        goal = RunGoal.ENDLESS
    draft = StrategyTeacherDraft(
        observation=observation,
        candidates=(
            StrategyTeacherCandidate(
                LeaveShop(),
                StrategyIntent.STABILIZE,
                (StrategyRolloutTarget(0, 0, 0, observation.antes_cleared, 1),),
            ),
            StrategyTeacherCandidate(
                RerollShop(),
                StrategyIntent.ECONOMY,
                (
                    StrategyRolloutTarget(
                        1,
                        1,
                        float(endless),
                        observation.antes_cleared + 1,
                        2,
                    ),
                ),
            ),
        ),
        selected_index=selected,
        baseline_index=0,
        goal=goal,
        teacher_config_digest="1" * 64,
    )
    return draft.finalize(
        run_group=f"run-{group:06d}",
        decision_index=0,
        run_complete=True,
        run_won=endless,
        terminal_ante=9 if endless else 4,
        best_hand_score=100_000,
    )


def _model() -> RelationalStrategyPolicyValue:
    torch.manual_seed(9)
    return RelationalStrategyPolicyValue(
        StrategyModelConfig(
            hidden_size=16,
            attention_heads=4,
            attention_layers=1,
            feedforward_size=32,
            max_entities=128,
            max_actions=32,
        )
    )


def test_complete_runs_are_split_atomically_and_deterministically() -> None:
    records = tuple(_record(index, endless=index == 3) for index in range(4))

    first = split_teacher_records(
        records,
        train_groups=2,
        calibration_groups=1,
        holdout_groups=1,
        nonce="fixed-split",
    )
    second = split_teacher_records(
        records,
        train_groups=2,
        calibration_groups=1,
        holdout_groups=1,
        nonce="fixed-split",
    )

    assert first == second
    assert set(first.train_groups).isdisjoint(first.calibration_groups)
    assert set(first.train_groups).isdisjoint(first.holdout_groups)
    assert set(first.calibration_groups).isdisjoint(first.holdout_groups)
    assert set(
        first.train_groups + first.calibration_groups + first.holdout_groups
    ) == {record.run_group for record in records}
    assert all(
        len(first.manifest()[key]) == 64
        for key in ("train_digest", "calibration_digest", "holdout_digest")
    )


def test_training_loss_is_finite_and_masks_endless_heads() -> None:
    records = (_record(0), _record(1, endless=True))
    model = _model()

    loss, metrics = strategy_training_loss(model, records)

    assert torch.isfinite(loss)
    assert metrics["victory_targets"] == 4
    assert metrics["endless_targets"] == 4
    assert all(value >= 0 for key, value in metrics.items() if key.endswith("_loss"))


def test_nonselected_candidate_outcome_changes_counterfactual_value_loss() -> None:
    record = _record(0, selected=0)
    model = _model()
    with torch.no_grad():
        model.ante8_head.weight.zero_()
        model.ante8_head.bias.fill_(2.0)
    changed_sample = replace(record.candidates[1].samples[0], ante8_win=1.0)
    changed_candidate = replace(
        record.candidates[1], samples=(changed_sample,)
    )
    changed = replace(
        record,
        candidates=(record.candidates[0], changed_candidate),
    )

    original_loss, original_metrics = strategy_training_loss(model, (record,))
    changed_loss, changed_metrics = strategy_training_loss(model, (changed,))

    assert original_metrics["ante8_loss"] != changed_metrics["ante8_loss"]
    assert not torch.equal(original_loss, changed_loss)


def test_calibration_freezes_safe_margin_and_reports_every_head() -> None:
    records = (_record(0), _record(1, selected=0), _record(2, endless=True))
    model = _model()

    calibration, calibration_metrics = fit_strategy_calibration(model, records)
    holdout_metrics = evaluate_strategy_model(model, records)

    assert calibration.calibrated
    assert model.calibration == calibration
    assert calibration.policy_override_margin >= 0
    assert set(calibration_metrics["error_radii"]) == {
        "current_blind",
        "next_boss",
        "ante8",
        "endless_ante",
        "log_score",
    }
    assert set(holdout_metrics) >= {
        "policy",
        "current_blind",
        "next_boss",
        "ante8",
        "endless_ante",
        "log_score",
    }
    assert holdout_metrics["policy"]["recommendation_errors"] == 0


def test_holdout_metrics_weight_complete_runs_equally(monkeypatch) -> None:
    majority = _record(0, selected=0)
    minority = _record(1, selected=1)
    records = tuple(replace(majority, decision_index=index) for index in range(9)) + (
        minority,
    )
    predictions = {
        "policy": [[1.0, 0.0] for _ in records],
        "current_blind": [[0.5, 0.5] for _ in records],
        "next_boss": [[0.5, 0.5] for _ in records],
        "ante8": [[0.5, 0.5] for _ in records],
        "endless_ante": [[1.0, 1.0] for _ in records],
        "log_score": [[1.0, 1.0] for _ in records],
    }
    monkeypatch.setattr(strategy_learning, "_predict", lambda model, rows: predictions)
    model = SimpleNamespace(calibration=StrategyCalibration())

    metrics = evaluate_strategy_model(model, records)  # type: ignore[arg-type]

    assert metrics["weighting"] == "inverse_eligible_targets_per_run_and_head"
    assert abs(metrics["policy"]["agreement"] - 0.5) < 1e-12
