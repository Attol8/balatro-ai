"""Certified, public-only contextual continuation for simulated rollouts."""

from __future__ import annotations

import hashlib
import json
import math
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

import torch

from balatro_ai_v2.actions import (
    PublicAction,
    ReorderConsumables,
    ReorderHand,
    ReorderJokers,
    action_to_data,
)
from balatro_ai_v2.policy import ActionSource, PublicHistoryStep, PublicPolicy
from balatro_ai_v2.public_state import Phase, PublicObservation
from balatro_ai_v2.strategy_context import derive_public_strategy_context
from balatro_ai_v2.strategy_model import (
    STRATEGY_MODEL_SCHEMA_DIGEST,
    PublicStrategyTensorizer,
    RelationalStrategyPolicyValue,
    load_strategy_model,
)


CONTINUATION_CERTIFICATE_VERSION = 1
_DIGEST = re.compile(r"[0-9a-f]{64}")
_STRATEGIC_PHASES = frozenset({Phase.BLIND_SELECT, Phase.SHOP, Phase.PACK})
_REORDERS = (ReorderHand, ReorderJokers, ReorderConsumables)


@dataclass(frozen=True, slots=True)
class RolloutContinuationCertificate:
    """Separate authority to use one immutable shadow model in rollouts."""

    version: int
    model_sha256: str
    training_report_sha256: str
    model_schema_digest: str
    policy_margin: float
    support_phases: tuple[str, ...]
    calibration_groups: int
    holdout_groups: int
    authorizes_rollout_continuation: bool

    def __post_init__(self) -> None:
        if self.version != CONTINUATION_CERTIFICATE_VERSION:
            raise ValueError("unsupported rollout continuation certificate version")
        for value in (
            self.model_sha256,
            self.training_report_sha256,
            self.model_schema_digest,
        ):
            if _DIGEST.fullmatch(value) is None:
                raise ValueError("continuation certificate digest is invalid")
        if self.model_schema_digest != STRATEGY_MODEL_SCHEMA_DIGEST:
            raise ValueError("continuation certificate model schema is stale")
        if not math.isfinite(self.policy_margin) or self.policy_margin < 0:
            raise ValueError("continuation certificate margin is invalid")
        if (
            isinstance(self.calibration_groups, bool)
            or not isinstance(self.calibration_groups, int)
            or isinstance(self.holdout_groups, bool)
            or not isinstance(self.holdout_groups, int)
            or self.calibration_groups < 59
            or self.holdout_groups < 59
        ):
            raise ValueError("continuation certificate has insufficient run support")
        if self.authorizes_rollout_continuation is not True:
            raise ValueError("certificate does not authorize rollout continuation")
        if not self.support_phases or len(set(self.support_phases)) != len(
            self.support_phases
        ):
            raise ValueError("continuation certificate support phases are invalid")
        if any(
            not isinstance(phase, str)
            or phase not in {item.value for item in _STRATEGIC_PHASES}
            for phase in self.support_phases
        ):
            raise ValueError("continuation certificate names an unsupported phase")

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "model_sha256": self.model_sha256,
            "training_report_sha256": self.training_report_sha256,
            "model_schema_digest": self.model_schema_digest,
            "policy_margin": self.policy_margin,
            "support_phases": list(self.support_phases),
            "calibration_groups": self.calibration_groups,
            "holdout_groups": self.holdout_groups,
            "authorizes_rollout_continuation": self.authorizes_rollout_continuation,
        }


@dataclass(slots=True)
class CertifiedUtilityContinuationPolicy:
    """Override a public fallback only inside certificate-supported strata."""

    control: PublicPolicy
    model: RelationalStrategyPolicyValue
    certificate: RolloutContinuationCertificate
    tensorizer: PublicStrategyTensorizer | None = None

    def __post_init__(self) -> None:
        if self.model.provenance.get("training_status") != "trained":
            raise ValueError("continuation model is not trained")
        if self.model.provenance.get("influence_mode") != "shadow":
            raise ValueError("continuation model must remain a shadow artifact")
        calibration = self.model.calibration
        if not calibration.calibrated or (
            calibration.policy_override_margin != self.certificate.policy_margin
        ):
            raise ValueError(
                "continuation certificate disagrees with model calibration"
            )
        if self.tensorizer is None:
            self.tensorizer = PublicStrategyTensorizer(self.model.config)
        elif self.tensorizer.config != self.model.config:
            raise ValueError("continuation tensorizer and model configs disagree")
        self.model.eval()

    @classmethod
    def from_artifacts(
        cls,
        *,
        control: PublicPolicy,
        model_path: Path,
        certificate_path: Path,
    ) -> CertifiedUtilityContinuationPolicy:
        model_digest = hashlib.sha256(model_path.read_bytes()).hexdigest()
        certificate = load_rollout_continuation_certificate(certificate_path)
        if model_digest != certificate.model_sha256:
            raise ValueError("continuation model digest disagrees with certificate")
        return cls(control, load_strategy_model(model_path), certificate)

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        supplied = tuple(legal_actions())
        baseline = self.control.choose_action(
            observation,
            lambda: iter(supplied),
            history,
        )
        if observation.phase.value not in self.certificate.support_phases:
            return baseline
        try:
            if baseline not in supplied:
                raise ValueError("control action is absent from supplied legal actions")
            candidates = tuple(
                sorted(
                    (
                        action
                        for action in supplied
                        if not isinstance(action, _REORDERS)
                    ),
                    key=lambda action: json.dumps(
                        action_to_data(action),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
            )
            if baseline not in candidates or len(candidates) <= 1:
                return baseline
            if len(set(candidates)) != len(candidates):
                raise ValueError("supplied legal actions contain duplicates")
            context = derive_public_strategy_context(observation, history)
            if self.tensorizer is None:  # pragma: no cover - initialized above
                raise AssertionError("continuation tensorizer is unavailable")
            batch = self.tensorizer.tensorize(
                (observation,),
                (candidates,),
                ((None,) * len(candidates),),
                (context,),
            )
            with torch.no_grad():
                logits = self.model(batch).policy_logits
            if logits.shape != (1, len(candidates)) or not torch.isfinite(logits).all():
                raise ValueError("continuation model emitted invalid utility scores")
            row = logits[0]
            preferred_index = int(torch.argmax(row).item())
            baseline_index = candidates.index(baseline)
            predicted_gain = float(
                (row[preferred_index] - row[baseline_index]).detach().cpu().item()
            )
            if (
                preferred_index != baseline_index
                and predicted_gain > self.certificate.policy_margin
            ):
                return candidates[preferred_index]
        except Exception:
            return baseline
        return baseline

    def fork_for_rollout(self, _intent=None) -> CertifiedUtilityContinuationPolicy:
        """Return an independent wrapper; the model and fallback are stateless."""

        control = deepcopy(self.control)
        if control is self.control:
            raise ValueError("rollout continuation fallback did not fork")
        return CertifiedUtilityContinuationPolicy(
            control=control,
            model=self.model,
            certificate=self.certificate,
            tensorizer=self.tensorizer,
        )


def load_rollout_continuation_certificate(
    path: Path,
) -> RolloutContinuationCertificate:
    required = {
        "version",
        "model_sha256",
        "training_report_sha256",
        "model_schema_digest",
        "policy_margin",
        "support_phases",
        "calibration_groups",
        "holdout_groups",
        "authorizes_rollout_continuation",
    }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("continuation certificate is unreadable") from exc
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("continuation certificate fields are invalid")
    try:
        return RolloutContinuationCertificate(
            version=int(payload["version"]),
            model_sha256=str(payload["model_sha256"]),
            training_report_sha256=str(payload["training_report_sha256"]),
            model_schema_digest=str(payload["model_schema_digest"]),
            policy_margin=float(payload["policy_margin"]),
            support_phases=tuple(payload["support_phases"]),
            calibration_groups=int(payload["calibration_groups"]),
            holdout_groups=int(payload["holdout_groups"]),
            authorizes_rollout_continuation=payload["authorizes_rollout_continuation"],
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("continuation certificate values are invalid") from exc


__all__ = [
    "CONTINUATION_CERTIFICATE_VERSION",
    "CertifiedUtilityContinuationPolicy",
    "RolloutContinuationCertificate",
    "load_rollout_continuation_certificate",
]
