from __future__ import annotations

from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")

from balatro_ai_v2.actions import iter_legal_actions  # noqa: E402
from balatro_ai_v2.balatrobot.adapter import to_public_observation  # noqa: E402
from balatro_ai_v2.strategy_model import StrategyCalibration, StrategyModelConfig  # noqa: E402
from balatro_ai_v2.strategy_shadow import ShadowStrategyPolicy  # noqa: E402
from state_factory import state  # noqa: E402


class _FirstControl:
    resets = 0

    def choose_action(self, observation, legal_actions, history):
        return next(legal_actions())

    def reset_run(self) -> None:
        self.resets += 1


class _DescendingModel:
    def __init__(self, calibration: StrategyCalibration) -> None:
        self.config = StrategyModelConfig(
            hidden_size=32,
            attention_heads=4,
            attention_layers=1,
            feedforward_size=64,
            max_entities=128,
            max_actions=128,
        )
        self.calibration = calibration
        self.training = True

    def eval(self):
        self.training = False
        return self

    def __call__(self, batch):
        width = batch.action_features.shape[1]
        logits = torch.arange(width, dtype=torch.float32).unsqueeze(0)
        def values(value):
            return torch.full((1, width), value, dtype=torch.float32)
        return SimpleNamespace(
            policy_logits=logits,
            current_blind_survival=values(0.8),
            next_boss_survival=values(0.6),
            ante8_win=values(0.4),
            endless_ante=values(7.0),
            log_score=values(12.0),
        )


class _FailingModel(_DescendingModel):
    def __call__(self, batch):
        raise RuntimeError("shadow inference failed")


def _observation(phase: str):
    return to_public_observation(state(phase))


def test_shadow_scores_deduplicated_intent_options_but_returns_control() -> None:
    observation = _observation("SHOP")
    legal = tuple(iter_legal_actions(observation))
    control = _FirstControl()
    model = _DescendingModel(
        StrategyCalibration(
            policy_override_margin=0.5,
            calibrated=True,
        )
    )
    policy = ShadowStrategyPolicy(control, model)  # type: ignore[arg-type]

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == legal[0]
    assert model.training is False
    decision = policy.last_decision
    assert decision is not None
    assert decision.control_action == selected
    assert decision.control_intent is None
    assert decision.preferred_intent is not None
    assert decision.baseline_relative_margin is not None
    assert decision.baseline_relative_margin > decision.required_margin
    assert decision.recommendation_clears_margin
    assert decision.current_blind_survival == pytest.approx(0.8)
    assert decision.next_boss_survival == pytest.approx(0.6)
    assert decision.ante8_win == pytest.approx(0.4)
    assert decision.endless_ante == pytest.approx(7.0)
    assert decision.log_score == pytest.approx(12.0)
    assert decision.calibrated_heads == ("policy",)
    assert decision.as_dict()["value_predictions"] == {
        "current_blind_survival": pytest.approx(0.8),
        "next_boss_survival": pytest.approx(0.6),
        "ante8_win": pytest.approx(0.4),
        "endless_ante": pytest.approx(7.0),
        "log_score": pytest.approx(12.0),
    }
    triples = tuple(
        (candidate.action, candidate.intent, candidate.route)
        for candidate in decision.candidates
    )
    assert len(triples) == len(set(triples))
    assert any(action == selected and intent is None for action, intent, _ in triples)
    assert decision.unavailable_reason is None


def test_uncalibrated_shadow_never_clears_margin() -> None:
    observation = _observation("SHOP")
    legal = tuple(iter_legal_actions(observation))
    policy = ShadowStrategyPolicy(
        _FirstControl(),
        _DescendingModel(StrategyCalibration()),  # type: ignore[arg-type]
    )

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == legal[0]
    assert policy.last_decision is not None
    assert policy.last_decision.preferred_intent is not None
    assert not policy.last_decision.calibrated
    assert not policy.last_decision.recommendation_clears_margin


def test_non_strategic_shadow_does_not_score_out_of_distribution_actions() -> None:
    observation = _observation("SELECTING_HAND")
    legal = tuple(iter_legal_actions(observation))
    policy = ShadowStrategyPolicy(
        _FirstControl(),
        _DescendingModel(StrategyCalibration()),  # type: ignore[arg-type]
    )

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == legal[0]
    assert policy.last_decision is None
    assert policy.decisions == []


def test_shadow_inference_failure_records_unavailable_and_returns_control() -> None:
    observation = _observation("SHOP")
    legal = tuple(iter_legal_actions(observation))
    policy = ShadowStrategyPolicy(
        _FirstControl(),
        _FailingModel(StrategyCalibration(calibrated=True)),  # type: ignore[arg-type]
    )

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == legal[0]
    assert policy.last_decision is not None
    assert policy.last_decision.preferred_action is None
    assert policy.last_decision.current_blind_survival is None
    assert policy.last_decision.calibrated_heads == ()
    assert not policy.last_decision.recommendation_clears_margin
    assert "shadow inference failed" in (policy.last_decision.unavailable_reason or "")


def test_shadow_reset_clears_diagnostics_and_resets_control() -> None:
    observation = _observation("SHOP")
    legal = tuple(iter_legal_actions(observation))
    control = _FirstControl()
    policy = ShadowStrategyPolicy(
        control,
        _DescendingModel(StrategyCalibration()),  # type: ignore[arg-type]
    )
    policy.choose_action(observation, lambda: iter(legal), ())

    policy.reset_run()

    assert policy.last_decision is None
    assert policy.decisions == []
    assert control.resets >= 1
