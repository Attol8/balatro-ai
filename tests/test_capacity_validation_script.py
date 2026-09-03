from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "validate_capacity_signal.py"
    spec = importlib.util.spec_from_file_location("validate_capacity_signal_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_auc_uses_half_credit_for_ties() -> None:
    module = _load_script()

    assert module._roc_auc([(2.0, True), (1.0, True), (1.0, False), (0.0, False)]) == 0.875
    assert module._roc_auc([(1.0, True)]) is None


def test_validation_reports_coverage_and_clustered_interval(tmp_path: Path) -> None:
    module = _load_script()
    path = tmp_path / "report.json"
    rows = [
        (1, [(2.0, 1, True), (1.0, 1, False)]),
        (2, [(3.0, 2, True), (0.0, 2, False)]),
    ]
    results = []
    for seed, diagnostics in rows:
        capacity = [
            {
                "phase": "SHOP",
                "available": True,
                "unavailable_reason": None,
                "margin_available": True,
                "margin_unavailable_reason": None,
                "log_margin": margin,
                "ante": ante,
                "cleared_next_boss": label,
                "model_version": 2,
                "sample_method": "test",
            }
            for margin, ante, label in diagnostics
        ]
        results.append({"seed": seed, "complete": True, "capacity_decisions": capacity})
    results[0]["capacity_decisions"].append(
        {
            "phase": "SHOP",
            "available": False,
            "unavailable_reason": "unsupported Joker j_square",
        }
    )
    path.write_text(
        json.dumps(
            {
                "candidate_only": True,
                "manifest": {
                    "source_digest": "source",
                    "run": {"deck": "RED", "stake": "WHITE", "seed": "1:2"},
                    "max_antes_cleared": 20,
                    "max_decisions": 1200,
                    "launch_fast": False,
                    "launch_headless": False,
                    "backend": {"backend_name": "Jackdaw"},
                },
                "capacity_protocol": {
                    "model_version": 2,
                    "samples": 32,
                    "sample_method": "public-digest-monte-carlo-without-replacement-v1",
                    "phases": ["BLIND_SELECT", "PACK", "SHOP"],
                    "validation_phase": "SHOP",
                    "label": "cleared_next_boss",
                },
                "results": results,
            }
        ),
        encoding="utf-8",
    )

    report = module.validate_capacity_report(
        path,
        minimum_coverage=0.75,
        bootstrap_samples=100,
        expected_seeds=(1, 2),
    )

    assert report["coverage"] == 0.8
    assert report["failure_counts"] == {"unsupported Joker j_square": 1}
    assert report["capacity_auc"] == 1.0
    assert report["ante_auc"] == 0.5
    assert report["undefined_per_seed_auc"] == 0
    assert report["paired_seed_bootstrap_95"]["valid_samples"] == 100
    assert report["passed"]


def test_validation_rejects_a_different_panel_protocol(tmp_path: Path) -> None:
    module = _load_script()
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps(
            {
                "candidate_only": True,
                "manifest": {
                    "source_digest": "source",
                    "run": {"deck": "BLUE", "stake": "WHITE", "seed": "1:1"},
                    "max_antes_cleared": 20,
                    "max_decisions": 1200,
                    "launch_fast": False,
                    "launch_headless": False,
                    "backend": {"backend_name": "Jackdaw"},
                },
                "capacity_protocol": {},
                "results": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.ValidationError, match="Red White capacity panel"):
        module.validate_capacity_report(path, expected_seeds=(1,))
