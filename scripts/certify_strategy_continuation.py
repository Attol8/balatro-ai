#!/usr/bin/env python3
"""Issue separate rollout-only authority for a frozen strategy shadow model."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.strategy_continuation import (
    CONTINUATION_CERTIFICATE_VERSION,
    RolloutContinuationCertificate,
)
from balatro_ai_v2.strategy_model import (
    STRATEGY_MODEL_SCHEMA_DIGEST,
    load_strategy_model,
)


def main() -> None:
    args = build_parser().parse_args()
    if args.output_json.exists():
        raise SystemExit(f"refusing to overwrite existing output: {args.output_json}")
    try:
        report_bytes = args.training_report.read_bytes()
        report = json.loads(report_bytes)
        model_bytes = args.model.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("training report or model is unreadable") from exc
    model_digest = hashlib.sha256(model_bytes).hexdigest()
    report_digest = hashlib.sha256(report_bytes).hexdigest()
    try:
        artifact = report["artifact"]
        split = report["split"]
        holdout = report["holdout_metrics"]
        policy = holdout["policy"]
        gate = report["calibration_gate"]
        calibration = report["calibration"]
    except (KeyError, TypeError) as exc:
        raise SystemExit("training report is missing certification evidence") from exc
    if (
        report.get("candidate_only") is not True
        or report.get("influence_mode") != "shadow"
        or report.get("promotion_eligible") is not False
        or not isinstance(artifact, dict)
        or artifact.get("sha256") != model_digest
        or artifact.get("schema_digest") != STRATEGY_MODEL_SCHEMA_DIGEST
        or not isinstance(split, dict)
        or not isinstance(holdout, dict)
        or not isinstance(policy, dict)
        or not isinstance(gate, dict)
        or gate.get("offline_gate_passed") is not True
        or gate.get("authorizes_action_influence") is not False
        or gate.get("zero_recommendation_errors") is not True
        or gate.get("zero_false_tie_overrides") is not True
        or gate.get("non_positive_recommendation_regret") is not True
        or gate.get("positive_recommended_utility_gain") is not True
        or int(policy.get("recommendations", 0)) < 1
        or int(policy.get("recommendation_groups", 0)) < 59
        or int(policy.get("recommendation_errors", -1)) != 0
        or int(policy.get("false_tie_overrides", -1)) != 0
        or float(policy.get("mean_recommendation_regret", 1.0)) > 0.0
        or float(policy.get("mean_recommended_utility_gain", 0.0)) <= 0.0
    ):
        raise SystemExit("training report did not pass the rollout continuation gate")
    calibration_groups = len(split.get("calibration_groups", ()))
    holdout_groups = len(split.get("holdout_groups", ()))
    if calibration_groups < 59 or holdout_groups < 59:
        raise SystemExit(
            "rollout certification requires 59 calibration and holdout runs"
        )
    strata = holdout.get("strata")
    if not isinstance(strata, dict):
        raise SystemExit("holdout report has no support strata")
    support_phases = tuple(dict.fromkeys(args.support_phase))
    present_phases = {str(key).split(":", 1)[0] for key in strata}
    if not support_phases or any(
        phase not in present_phases for phase in support_phases
    ):
        raise SystemExit("requested continuation phase lacks holdout support")
    model = load_strategy_model(args.model)
    if model.provenance.get("influence_mode") != "shadow":
        raise SystemExit("model artifact is not immutable shadow-only evidence")
    certificate = RolloutContinuationCertificate(
        version=CONTINUATION_CERTIFICATE_VERSION,
        model_sha256=model_digest,
        training_report_sha256=report_digest,
        model_schema_digest=STRATEGY_MODEL_SCHEMA_DIGEST,
        policy_margin=float(calibration["policy_override_margin"]),
        support_phases=support_phases,
        calibration_groups=calibration_groups,
        holdout_groups=holdout_groups,
        authorizes_rollout_continuation=True,
    )
    encoded = json.dumps(certificate.as_dict(), sort_keys=True, separators=(",", ":"))
    _publish_exclusive(args.output_json, encoded + "\n")
    print(encoded)


def _publish_exclusive(path: Path, encoded: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--training-report", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument(
        "--support-phase",
        action="append",
        choices=("BLIND_SELECT", "SHOP", "PACK"),
        required=True,
    )
    return parser


if __name__ == "__main__":
    main()
