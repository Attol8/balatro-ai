from __future__ import annotations

from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")

from balatro_ai_v2.actions import iter_legal_actions  # noqa: E402
from balatro_ai_v2.balatrobot.adapter import to_public_observation  # noqa: E402
from balatro_ai_v2.strategy_continuation import (  # noqa: E402
    CertifiedUtilityContinuationPolicy,
    RolloutContinuationCertificate,
)
from balatro_ai_v2.strategy_model import (  # noqa: E402
    STRATEGY_MODEL_SCHEMA_DIGEST,
    StrategyCalibration,
    StrategyModelConfig,
)
from state_factory import state  # noqa: E402


class _FirstControl:
    def choose_action(self, observation, legal_actions, history):
        return next(legal_actions())


class _UtilityModel:
    def __init__(self, *, fail: bool = False) -> None:
        self.config = StrategyModelConfig(
            hidden_size=16,
            attention_heads=4,
            attention_layers=1,
            feedforward_size=32,
            max_entities=128,
            max_actions=128,
        )
        self.calibration = StrategyCalibration(
            policy_override_margin=0.5,
            calibrated=True,
        )
        self.provenance = {"training_status": "trained", "influence_mode": "shadow"}
        self.fail = fail

    def eval(self):
        return self

    def __call__(self, batch):
        if self.fail:
            raise RuntimeError("inference failed")
        width = batch.action_features.shape[1]
        return SimpleNamespace(
            policy_logits=torch.arange(width, dtype=torch.float32).unsqueeze(0)
        )


def _certificate() -> RolloutContinuationCertificate:
    return RolloutContinuationCertificate(
        version=1,
        model_sha256="1" * 64,
        training_report_sha256="2" * 64,
        model_schema_digest=STRATEGY_MODEL_SCHEMA_DIGEST,
        policy_margin=0.5,
        support_phases=("SHOP",),
        calibration_groups=59,
        holdout_groups=59,
        authorizes_rollout_continuation=True,
    )


def test_certified_continuation_can_override_only_supported_strategic_state() -> None:
    observation = to_public_observation(state("SHOP"))
    legal = tuple(iter_legal_actions(observation))
    policy = CertifiedUtilityContinuationPolicy(
        _FirstControl(),
        _UtilityModel(),
        _certificate(),  # type: ignore[arg-type]
    )

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == legal[-1]
    assert selected != legal[0]


def test_certified_continuation_fails_closed_on_inference_or_bad_history() -> None:
    observation = to_public_observation(state("SHOP"))
    legal = tuple(iter_legal_actions(observation))
    failing = CertifiedUtilityContinuationPolicy(
        _FirstControl(),
        _UtilityModel(fail=True),
        _certificate(),  # type: ignore[arg-type]
    )

    assert failing.choose_action(observation, lambda: iter(legal), ()) == legal[0]


def test_certificate_rejects_insufficient_independent_runs() -> None:
    with pytest.raises(ValueError, match="insufficient run support"):
        RolloutContinuationCertificate(
            version=1,
            model_sha256="1" * 64,
            training_report_sha256="2" * 64,
            model_schema_digest=STRATEGY_MODEL_SCHEMA_DIGEST,
            policy_margin=0.5,
            support_phases=("SHOP",),
            calibration_groups=15,
            holdout_groups=15,
            authorizes_rollout_continuation=True,
        )
