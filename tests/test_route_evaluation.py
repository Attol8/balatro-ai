from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace

import pytest
import torch

import balatro_ai_v2.route_evaluation as evaluation
from balatro_ai_v2.actions import LeaveShop
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.route_learning import RouteDatasetSplit
from balatro_ai_v2.route_learning_protocol import CALIBRATION_CONFIG, HOLDOUT_GATE
from balatro_ai_v2.route_model import RouteResidualCalibration
from balatro_ai_v2.strategy_engine import RunGoal, RunRoute
from balatro_ai_v2.strategy_model import RelationalStrategyPolicyValue
from balatro_ai_v2.strategy_teacher import (
    StrategyRolloutTarget,
    StrategyTargetEndpoint,
    StrategyTeacherCandidate,
    StrategyTeacherDraft,
)
from state_factory import state


def _absolute_binary(delta: float) -> tuple[float, float]:
    if delta == 1.0:
        return 0.0, 1.0
    if delta == -1.0:
        return 1.0, 0.0
    if delta == 0.0:
        return 1.0, 1.0
    raise ValueError("test binary delta must be -1, 0, or 1")


def _record(
    group: int,
    decision: int,
    *,
    scalar: tuple[float, float] = (1.0, 1.0),
    current: tuple[float, float] = (1.0, 1.0),
    boss: tuple[float, float] = (1.0, 1.0),
    ante8: tuple[float, float] | None = (1.0, 1.0),
    endless: tuple[float, float] | None = (1.0, 1.0),
    score: tuple[float, float] | None = (1.0, 1.0),
    route: RunRoute = RunRoute.PLAYED_RETRIGGER,
    goal: RunGoal = RunGoal.VICTORY,
    behavior_specialist: bool = False,
    ordinary_endpoints: tuple[StrategyTargetEndpoint, StrategyTargetEndpoint] = (
        StrategyTargetEndpoint.DEATH,
        StrategyTargetEndpoint.DEATH,
    ),
    specialist_endpoints: tuple[StrategyTargetEndpoint, StrategyTargetEndpoint] = (
        StrategyTargetEndpoint.VICTORY,
        StrategyTargetEndpoint.VICTORY,
    ),
    ante: int = 4,
):
    ante = max(ante, 9) if goal == RunGoal.ENDLESS else ante
    observation = to_public_observation(state("SHOP", money=10))
    observation = replace(
        observation,
        ante=ante,
        antes_cleared=ante - 1,
        won=goal == RunGoal.ENDLESS,
    )
    action = LeaveShop()

    def samples(*, specialist: bool):
        result = []
        for index in range(2):
            current_base, current_specialist = _absolute_binary(current[index])
            boss_base, boss_specialist = _absolute_binary(boss[index])
            ante_base, ante_specialist = (
                _absolute_binary(ante8[index]) if ante8 is not None else (None, None)
            )
            result.append(
                StrategyRolloutTarget(
                    current_blind_clear=(
                        current_specialist if specialist else current_base
                    ),
                    next_boss_clear=boss_specialist if specialist else boss_base,
                    ante8_win=ante_specialist if specialist else ante_base,
                    endless_ante=(
                        None
                        if endless is None
                        else 5.0 + (endless[index] if specialist else 0.0)
                    ),
                    log_score=(
                        None
                        if score is None
                        else 5.0 + (score[index] if specialist else 0.0)
                    ),
                    search_utility=5.0 + (scalar[index] if specialist else 0.0),
                    endpoint=(
                        specialist_endpoints[index]
                        if specialist
                        else ordinary_endpoints[index]
                    ),
                )
            )
        return tuple(result)

    candidates = (
        StrategyTeacherCandidate(action, None, samples(specialist=False)),
        StrategyTeacherCandidate(
            action,
            None,
            samples(specialist=True),
            route,
        ),
    )
    return StrategyTeacherDraft(
        observation=observation,
        candidates=candidates,
        selected_index=1,
        baseline_index=0,
        ordinary_index=0,
        behavior_index=1 if behavior_specialist else 0,
        goal=goal,
        teacher_config_digest="a" * 64,
        candidate_space_size=2,
    ).finalize(
        run_group=f"origin-{group:032x}",
        decision_index=decision,
        run_complete=True,
        run_won=goal == RunGoal.ENDLESS,
        terminal_ante=ante,
        best_hand_score=100,
    )


def _split(train, calibration, holdout) -> RouteDatasetSplit:
    def groups(rows):
        return tuple(sorted({row.run_group for row in rows}))

    return RouteDatasetSplit(
        tuple(train),
        tuple(calibration),
        tuple(holdout),
        groups(train),
        groups(calibration),
        groups(holdout),
    )


def _model(seed: int = 7) -> RelationalStrategyPolicyValue:
    torch.manual_seed(seed)
    return RelationalStrategyPolicyValue()


def _raw_from_targets(example) -> dict[str, float]:
    raw = {
        "scalar": sum(example.targets.scalar) / len(example.targets.scalar),
    }
    for head in evaluation.ROUTE_RESIDUAL_HEADS[1:]:
        values = evaluation._target_values(example, head)
        raw[head] = 0.0 if values is None else sum(values) / len(values)
    return raw


def _patch_predictions(monkeypatch, overrides=None):
    overrides = overrides or {}

    def predict(_model, records):
        result = []
        for example in evaluation._canonical_examples(records):
            key = (
                example.record.run_group,
                example.record.decision_index,
                example.record.candidates[example.specialist_index].route.value,
            )
            raw = {**_raw_from_targets(example), **overrides.get(key, {})}
            result.append(evaluation._Prediction(example, raw))
        return tuple(result)

    monkeypatch.setattr(evaluation, "_predict_examples", predict)


def _supported_panel(*, current_sensitive: bool = True):
    train = []
    calibration = []
    holdout = []
    for goal_index, goal in enumerate((RunGoal.VICTORY, RunGoal.ENDLESS)):
        missing = {
            "ante8": None if goal == RunGoal.ENDLESS else (1.0, 1.0),
            "endless": None if goal == RunGoal.VICTORY else (1.0, 1.0),
            "score": None if goal == RunGoal.VICTORY else (1.0, 1.0),
        }
        base = 100 * goal_index
        positive_current = (1.0, 1.0) if current_sensitive else (0.0, 0.0)
        negative_current = (-1.0, -1.0) if current_sensitive else (0.0, 0.0)
        train.extend(
            [
                _record(
                    base + 1,
                    0,
                    current=positive_current,
                    goal=goal,
                    **missing,
                ),
                _record(
                    base + 1,
                    1,
                    scalar=(-1.0, -1.0),
                    current=negative_current,
                    boss=(-1.0, -1.0),
                    goal=goal,
                    **missing,
                ),
                _record(
                    base + 2,
                    0,
                    current=positive_current,
                    goal=goal,
                    **missing,
                ),
                _record(
                    base + 2,
                    1,
                    scalar=(-1.0, -1.0),
                    current=negative_current,
                    boss=(-1.0, -1.0),
                    goal=goal,
                    **missing,
                ),
            ]
        )
        calibration.extend(
            [
                _record(
                    base + 3,
                    0,
                    current=positive_current,
                    goal=goal,
                    **missing,
                ),
                _record(
                    base + 3,
                    1,
                    scalar=(-1.0, -1.0),
                    current=negative_current,
                    boss=(-1.0, -1.0),
                    goal=goal,
                    **missing,
                ),
            ]
        )
        holdout.extend(
            [
                _record(
                    base + 4,
                    0,
                    current=positive_current,
                    goal=goal,
                    **missing,
                ),
                _record(
                    base + 5,
                    0,
                    scalar=(-1.0, -1.0),
                    current=negative_current,
                    boss=(-1.0, -1.0),
                    goal=goal,
                    **missing,
                ),
            ]
        )
    return _split(train, calibration, holdout)


def test_exact_tensorization_is_finite_and_input_order_independent():
    torch.manual_seed(5)
    model = RelationalStrategyPolicyValue()
    rows = (_record(2, 0), _record(1, 0))
    first = evaluation._predict_examples(model, rows)
    second = evaluation._predict_examples(model, tuple(reversed(rows)))
    assert [row.example.record.run_group for row in first] == sorted(
        row.example.record.run_group for row in first
    )
    assert [row.raw for row in first] == [row.raw for row in second]
    assert model.training


def test_calibration_uses_weighted_bias_and_maximum_one_sided_radius(monkeypatch):
    rows = (_record(1, 0, scalar=(0.0, 0.0)), _record(2, 0, scalar=(0.0, 0.0)))
    overrides = {
        (rows[0].run_group, 0, RunRoute.PLAYED_RETRIGGER.value): {"scalar": 0.0},
        (rows[1].run_group, 0, RunRoute.PLAYED_RETRIGGER.value): {"scalar": 4.0},
    }
    _patch_predictions(monkeypatch, overrides)
    calibration, evidence = evaluation.fit_route_residual_calibration(
        _model(), _split((), rows, ())
    )
    metrics = evidence.metrics
    assert calibration.scalar_bias == pytest.approx(-2.0)
    assert calibration.scalar_overprediction_radius == pytest.approx(2.0)
    assert metrics["scalar"]["max_overprediction"] == pytest.approx(2.0)
    assert metrics["scalar"]["empirical_only"] is True
    assert metrics["current_blind"]["overprediction_radius"] == 0.0


def test_masked_pair_is_never_partially_admitted(monkeypatch):
    complete = _record(1, 0)
    mismatched = _record(2, 0)
    specialist = mismatched.candidates[1]
    changed_samples = (
        replace(specialist.samples[0], ante8_win=None),
        specialist.samples[1],
    )
    mismatched = replace(
        mismatched,
        candidates=(
            mismatched.candidates[0],
            replace(specialist, samples=changed_samples),
        ),
    )
    _patch_predictions(monkeypatch)
    _, evidence = evaluation.fit_route_residual_calibration(
        _model(), _split((), (complete, mismatched), ())
    )
    metrics = evidence.metrics
    assert metrics["ante8"]["pairs"] == 1
    assert metrics["ante8"]["eligible_samples"] == 2
    assert metrics["ante8"]["masked_pairs"] == 1
    assert metrics["ante8"]["null_mismatch_pairs"] == 1
    assert metrics["scalar"]["pairs"] == 2


def test_calibration_fails_when_any_head_has_no_support(monkeypatch):
    row = _record(1, 0, ante8=None)
    _patch_predictions(monkeypatch)
    with pytest.raises(evaluation.RouteEvaluationError, match="ante8 has no support"):
        evaluation.fit_route_residual_calibration(
            _model(), _split((), (row,), ())
        )


def test_support_cells_do_not_authorize_cartesian_crosses():
    train = [
        _record(
            1 + index // 2,
            index % 2,
            scalar=((1.0, 1.0) if index % 2 == 0 else (-1.0, -1.0)),
        )
        for index in range(4)
    ]
    calibration = [
        _record(3, index, scalar=((1.0, 1.0) if index == 0 else (-1.0, -1.0)))
        for index in range(2)
    ]
    holdout = [_record(4, index, ante=5) for index in range(2)]
    cells = evaluation.route_support_cells(_split(train, calibration, holdout))
    assert len(cells) == 2
    assert not any(cell["structurally_admitted"] for cell in cells)


def test_cancelled_sensitive_pairs_do_not_supply_mixed_signs():
    train = [
        _record(1 + index // 2, index % 2, scalar=(1.0, -1.0)) for index in range(4)
    ]
    calibration = [_record(3, index, scalar=(1.0, -1.0)) for index in range(2)]
    holdout = [_record(4, index) for index in range(2)]
    (cell,) = evaluation.route_support_cells(_split(train, calibration, holdout))
    assert cell["train"]["cancelled_sensitive_pairs"] == 4
    assert cell["mixed_signs_before_holdout"] is False
    assert cell["structurally_admitted"] is False


def test_holdout_beats_literal_zero_and_is_shuffle_deterministic(monkeypatch):
    split = _supported_panel()
    _patch_predictions(monkeypatch)
    model = _model()
    calibration, calibration_evidence = evaluation.fit_route_residual_calibration(
        model, split
    )
    report = evaluation.evaluate_route_holdout(
        model, split, calibration, calibration_evidence=calibration_evidence
    )
    shuffled = _split(
        tuple(reversed(split.train)),
        tuple(reversed(split.calibration)),
        tuple(reversed(split.holdout)),
    )
    assert report == evaluation.evaluate_route_holdout(
        model,
        shuffled,
        calibration,
        calibration_evidence=calibration_evidence,
    )
    assert report["zero_baseline"]["residual"] == 0.0
    assert report["zero_baseline"]["fitted"] is False
    assert report["calibration_contract"] == CALIBRATION_CONFIG
    assert report["holdout_heads"]["scalar"]["model_mae"] == 0.0
    assert report["holdout_heads"]["scalar"]["zero_mae"] == 1.0
    assert report["scalar_sign"]["balanced_accuracy"] == 1.0
    assert report["recommendations"]["recommendations"] == 2
    assert report["recommendations"]["recommendation_groups"] == 2
    assert set(report["gate"]) - {"passed"} == set(HOLDOUT_GATE)
    assert report["gate"]["passed"] is True
    json.dumps(report, allow_nan=False, sort_keys=True)


def test_public_boundaries_reject_malformed_or_leaking_split(monkeypatch):
    split = _supported_panel()
    _patch_predictions(monkeypatch)
    model = _model()

    wrong_membership = replace(
        split,
        calibration_groups=(*split.calibration_groups, "origin-ffffffffffffffffffffffffffffffff"),
    )
    with pytest.raises(evaluation.RouteEvaluationError, match="declared groups"):
        evaluation.fit_route_residual_calibration(model, wrong_membership)

    overlapping = _split(split.train, split.train, split.holdout)
    with pytest.raises(evaluation.RouteEvaluationError, match="groups overlap"):
        evaluation.fit_route_residual_calibration(model, overlapping)

    malformed = replace(split, calibration=list(split.calibration))
    with pytest.raises(evaluation.RouteEvaluationError, match="records are malformed"):
        evaluation.fit_route_residual_calibration(model, malformed)

    calibration, evidence = evaluation.fit_route_residual_calibration(model, split)
    with pytest.raises(evaluation.RouteEvaluationError, match="declared groups"):
        evaluation.evaluate_route_holdout(
            model,
            wrong_membership,
            calibration,
            calibration_evidence=evidence,
        )


def test_holdout_requires_exact_calibration_partition_model_and_parameters(
    monkeypatch,
):
    split = _supported_panel()
    _patch_predictions(monkeypatch)
    model = _model()
    calibration, evidence = evaluation.fit_route_residual_calibration(model, split)

    with pytest.raises(evaluation.RouteEvaluationError, match="evidence is missing"):
        evaluation.evaluate_route_holdout(model, split, calibration)

    first = split.calibration[0]
    specialist = first.candidates[1]
    changed_specialist = replace(
        specialist,
        samples=(
            replace(
                specialist.samples[0],
                search_utility=specialist.samples[0].search_utility + 0.25,
            ),
            specialist.samples[1],
        ),
    )
    changed_split = replace(
        split,
        calibration=(
            replace(
                first,
                candidates=(first.candidates[0], changed_specialist),
            ),
            *split.calibration[1:],
        ),
    )
    with pytest.raises(evaluation.RouteEvaluationError, match="wrong partition"):
        evaluation.evaluate_route_holdout(
            model,
            changed_split,
            calibration,
            calibration_evidence=evidence,
        )

    with pytest.raises(evaluation.RouteEvaluationError, match="model digest"):
        evaluation.evaluate_route_holdout(
            _model(8),
            split,
            calibration,
            calibration_evidence=evidence,
        )

    changed_calibration = replace(
        calibration,
        scalar_bias=calibration.scalar_bias + 0.25,
    )
    with pytest.raises(evaluation.RouteEvaluationError, match="parameters disagree"):
        evaluation.evaluate_route_holdout(
            model,
            split,
            changed_calibration,
            calibration_evidence=evidence,
        )

    forged_metrics = deepcopy(evidence.metrics)
    forged_metrics["scalar"]["bias"] = changed_calibration.scalar_bias
    forged_evidence = replace(
        evidence,
        parameters={
            **evidence.parameters,
            "scalar_bias": changed_calibration.scalar_bias,
        },
        metrics=forged_metrics,
    )
    with pytest.raises(evaluation.RouteEvaluationError, match="frozen fit"):
        evaluation.evaluate_route_holdout(
            model,
            split,
            changed_calibration,
            calibration_evidence=forged_evidence,
        )


def test_calibration_evidence_rejects_unknown_or_nonfinite_metrics(monkeypatch):
    split = _supported_panel()
    _patch_predictions(monkeypatch)
    _, evidence = evaluation.fit_route_residual_calibration(_model(), split)

    unknown = deepcopy(evidence.metrics)
    unknown["scalar"]["unexpected"] = 1
    with pytest.raises(evaluation.RouteEvaluationError, match="metric fields"):
        replace(evidence, metrics=unknown)

    nonfinite = deepcopy(evidence.metrics)
    nonfinite["scalar"]["bias"] = float("nan")
    with pytest.raises(evaluation.RouteEvaluationError, match="metric value"):
        replace(evidence, metrics=nonfinite)

    wrong_types = {
        **evidence.parameters,
        "scalar_bias": 0,
    }
    with pytest.raises(evaluation.RouteEvaluationError, match="parameter types"):
        replace(evidence, parameters=wrong_types)


def test_current_blind_mae_is_diagnostic_when_target_is_constant(monkeypatch):
    split = _supported_panel(current_sensitive=False)
    _patch_predictions(monkeypatch)
    model = _model()
    calibration, evidence = evaluation.fit_route_residual_calibration(model, split)
    report = evaluation.evaluate_route_holdout(
        model, split, calibration, calibration_evidence=evidence
    )
    assert report["holdout_heads"]["current_blind"]["beats_zero"] is False
    assert report["gate"]["current_blind_residual_mae_diagnostic_only"] is True
    assert report["gate"]["passed"] is True


def test_nonrecommended_root_still_breaks_radius_gate(monkeypatch):
    split = _supported_panel()
    negative = next(
        row
        for row in split.holdout
        if sum(
            row.candidates[1].samples[index].search_utility
            - row.candidates[0].samples[index].search_utility
            for index in range(2)
        )
        < 0
    )
    overrides = {
        (
            negative.run_group,
            negative.decision_index,
            RunRoute.PLAYED_RETRIGGER.value,
        ): {"scalar": 2.0, "current_blind": -1.0},
    }
    _patch_predictions(monkeypatch, overrides)
    model = _model()
    calibration, evidence = evaluation.fit_route_residual_calibration(model, split)
    report = evaluation.evaluate_route_holdout(
        model, split, calibration, calibration_evidence=evidence
    )
    assert report["holdout_heads"]["scalar"]["radius_violations"] == 2
    assert report["gate"]["all_overprediction_within_calibration_radii"] is False


def test_behavior_specialist_is_not_a_recommendation_opportunity(monkeypatch):
    row = _record(1, 0, behavior_specialist=True)
    _patch_predictions(monkeypatch)
    predictions = evaluation._predict_examples(object(), (row,))
    report, _ = evaluation._recommendations(
        predictions,
        RouteResidualCalibration(calibrated=True),
        {evaluation._cell(predictions[0].example)},
    )
    assert report["opportunities"] == 0
    assert report["recommendations"] == 0


def test_lcb_zero_and_full_key_ties_never_recommend(monkeypatch):
    boundary = _record(1, 0)
    _patch_predictions(
        monkeypatch,
        {(boundary.run_group, 0, RunRoute.PLAYED_RETRIGGER.value): {"scalar": 1.0}},
    )
    predictions = evaluation._predict_examples(object(), (boundary,))
    report, _ = evaluation._recommendations(
        predictions,
        RouteResidualCalibration(scalar_overprediction_radius=1.0, calibrated=True),
        {evaluation._cell(predictions[0].example)},
    )
    assert report["recommendations"] == 0

    second = replace(boundary.candidates[1], route=RunRoute.HELD_RETRIGGER)
    tied = replace(
        boundary,
        candidates=(*boundary.candidates, second),
        candidate_space_size=3,
    )
    _patch_predictions(monkeypatch)
    predictions = evaluation._predict_examples(object(), (tied,))
    report, _ = evaluation._recommendations(
        predictions,
        RouteResidualCalibration(calibrated=True),
        {evaluation._cell(row.example) for row in predictions},
    )
    assert report["full_key_ties"] == 1
    assert report["recommendations"] == 0


def test_one_adverse_survival_sample_fails_despite_positive_mean(monkeypatch):
    row = _record(1, 0, current=(-1.0, 1.0))
    _patch_predictions(
        monkeypatch,
        {(row.run_group, 0, RunRoute.PLAYED_RETRIGGER.value): {"current_blind": 0.0}},
    )
    predictions = evaluation._predict_examples(object(), (row,))
    report, _ = evaluation._recommendations(
        predictions,
        RouteResidualCalibration(calibrated=True),
        {evaluation._cell(predictions[0].example)},
    )
    assert report["recommendations"] == 1
    assert report["survival_regressions"] == 1
    assert report["safe_positive_recommendations"] == 0


def test_balanced_sign_requires_both_classes_and_treats_predicted_zero_wrong(
    monkeypatch,
):
    positive = _record(1, 0)
    _patch_predictions(
        monkeypatch,
        {(positive.run_group, 0, RunRoute.PLAYED_RETRIGGER.value): {"scalar": 0.0}},
    )
    predictions = evaluation._predict_examples(object(), (positive,))
    metrics = evaluation._scalar_sign_metrics(predictions, 0.0)
    assert metrics["positive_recall"] == 0.0
    assert metrics["negative_recall"] is None
    assert metrics["balanced_accuracy"] is None
    assert metrics["passes"] is False


def test_sign_weights_are_recomputed_after_insensitive_pairs(monkeypatch):
    first = _record(1, 0)
    insensitive = _record(
        1,
        0,
        scalar=(0.0, 0.0),
        route=RunRoute.HELD_RETRIGGER,
    ).candidates[1]
    first = replace(
        first,
        candidates=(*first.candidates, insensitive),
        candidate_space_size=3,
    )
    second = _record(2, 0)
    _patch_predictions(
        monkeypatch,
        {
            (second.run_group, 0, RunRoute.PLAYED_RETRIGGER.value): {
                "scalar": -1.0
            }
        },
    )
    predictions = evaluation._predict_examples(object(), (first, second))
    metrics = evaluation._scalar_sign_metrics(predictions, 0.0)
    assert metrics["positive_recall"] == 0.5


def test_unsafe_high_terminal_value_is_excluded_from_regret(monkeypatch):
    ordinary = _record(1, 0)
    unsafe = _record(
        1,
        0,
        scalar=(3.0, 3.0),
        current=(-1.0, -1.0),
        route=RunRoute.HELD_RETRIGGER,
    ).candidates[1]
    row = replace(
        ordinary,
        candidates=(*ordinary.candidates, unsafe),
        candidate_space_size=3,
    )
    overrides = {
        (row.run_group, 0, RunRoute.PLAYED_RETRIGGER.value): {"scalar": 2.0},
        (row.run_group, 0, RunRoute.HELD_RETRIGGER.value): {
            "scalar": 3.0,
            "current_blind": -1.0,
        },
    }
    _patch_predictions(monkeypatch, overrides)
    predictions = evaluation._predict_examples(object(), (row,))
    report, _ = evaluation._recommendations(
        predictions,
        RouteResidualCalibration(calibrated=True),
        {evaluation._cell(item.example) for item in predictions},
    )
    assert report["recommendations"] == 1
    assert report["regrets"] == 0
    assert report["traces"][0]["route"] == RunRoute.PLAYED_RETRIGGER.value


def test_regret_compares_observed_safe_same_action_outside_admitted_cells(monkeypatch):
    ordinary = _record(
        1,
        0,
        goal=RunGoal.ENDLESS,
        ante8=None,
        endless=(1.0, 1.0),
        score=(1.0, 1.0),
    )
    better = _record(
        1,
        0,
        goal=RunGoal.ENDLESS,
        ante8=None,
        endless=(3.0, 3.0),
        score=(3.0, 3.0),
        route=RunRoute.HELD_RETRIGGER,
    ).candidates[1]
    row = replace(
        ordinary,
        candidates=(*ordinary.candidates, better),
        candidate_space_size=3,
    )
    _patch_predictions(monkeypatch)
    predictions = evaluation._predict_examples(object(), (row,))
    played_cell = evaluation._cell(predictions[0].example)
    report, _ = evaluation._recommendations(
        predictions,
        RouteResidualCalibration(calibrated=True),
        {played_cell},
    )
    assert report["recommendations"] == 1
    assert report["regrets"] == 1
    assert report["safe_positive_recommendations"] == 0
    assert report["traces"][0]["best_safe_candidate_index"] == 2


def test_recommendation_aggregation_is_group_equal(monkeypatch):
    many = [_record(1, index, scalar=(1.0, 1.0)) for index in range(3)]
    one = _record(2, 0, scalar=(3.0, 3.0))
    rows = (*many, one)
    _patch_predictions(monkeypatch)
    predictions = evaluation._predict_examples(object(), rows)
    report, _ = evaluation._recommendations(
        predictions,
        RouteResidualCalibration(calibrated=True),
        {evaluation._cell(item.example) for item in predictions},
    )
    assert report["recommendations"] == 4
    assert report["mean_scalar_gain_run_equal"] == 2.0
