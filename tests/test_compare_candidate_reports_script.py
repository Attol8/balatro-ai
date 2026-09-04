from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "compare_candidate_reports.py"
    spec = importlib.util.spec_from_file_location("compare_candidate_reports_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report(
    path: Path,
    *,
    seeds=(1, 2),
    wins=(),
    survivals=(),
    provenance="evaluator_secret",
) -> None:
    payload = {
        "candidate_only": True,
        "candidate_runtime": {"dirty": False, "revision": "candidate"},
        "manifest": {
            "backend": {
                "adapter_version": "1",
                "backend_name": "Jackdaw",
                "backend_version": "jack",
                "capabilities": {"authoritative": False},
                "game_version": "game",
                "runtime_version": "Python",
            },
            "canonical_schema_version": 6,
            "trace_schema_version": 1,
            "source_digest": "source",
            "max_decisions": 800,
            "max_antes_cleared": 20,
            "max_settle_polls": 0,
            "wall_clock_limit_seconds": None,
            "profile_mode": "all_unlocked",
            "launch_fast": False,
            "launch_headless": False,
            "inference_budget": "budget",
            "run": {"deck": "RED", "stake": "WHITE", "seed": "1:2"},
        },
        "benchmark_protocol": {
            "category": "fair_public_agent",
            "seed_provenance": provenance,
            "restart_selection": False,
            "filtered_seeds": False,
            "mods": False,
        },
        "results": [
            {
                "seed": seed,
                "complete": True,
                "won": seed in wins,
                "antes_cleared": 8 if seed in wins else 5 if seed in survivals else 3,
                "survived_to_ante_6": seed in survivals,
                "ante": 9 if seed in wins else 6 if seed in survivals else 4,
                "best_hand_score": 100 if seed in wins else 10,
                "terminal_reason": "game_over",
            }
            for seed in seeds
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_compare_counts_paired_outcomes_and_incomplete_as_loss(tmp_path: Path) -> None:
    module = _load_script()
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _report(baseline, wins=(1,), survivals=(1,))
    _report(candidate, wins=(2,), survivals=(1, 2))
    value = json.loads(candidate.read_text(encoding="utf-8"))
    value["manifest"]["inference_budget"] = "different-policy-budget"
    value["manifest"]["source_digest"] = "candidate-source"
    candidate.write_text(json.dumps(value), encoding="utf-8")
    payload = json.loads(module_path_output(module, baseline, candidate))

    assert payload["baseline_only_wins"] == 1
    assert payload["candidate_only_wins"] == 1
    assert payload["both_wins"] == 0
    assert payload["both_losses"] == 0
    assert payload["raw_win_delta"] == 0
    assert payload["baseline_win_rate"] == 0.5
    assert payload["candidate_win_rate"] == 0.5
    assert payload["paired_win_rate_delta"] == 0.0
    assert payload["candidate_inference_budget"] == "different-policy-budget"
    assert payload["baseline_source_digest"] == "source"
    assert payload["candidate_source_digest"] == "candidate-source"
    assert payload["baseline_mean_antes_cleared"] == 5.5
    assert payload["candidate_mean_antes_cleared"] == 6.5
    assert payload["paired_mean_antes_cleared_delta"] == 1.0
    assert payload["paired_antes_cleared_delta_bootstrap_95"] == {
        "lower": -3.0,
        "upper": 5.0,
        "samples": 10_000,
        "seed": 0,
    }
    assert payload["baseline_survived_to_ante_6"] == 1
    assert payload["candidate_survived_to_ante_6"] == 2
    assert payload["paired_survival_rate_delta"] == 0.5
    assert payload["baseline_survival_to_ante_6_rate"] == 0.5
    assert payload["candidate_survival_to_ante_6_rate"] == 1.0
    assert payload["paired_survival_delta_bootstrap_95"] == {
        "lower": 0.0,
        "upper": 1.0,
        "samples": 10_000,
        "seed": 0,
    }
    assert payload["baseline_maximum_ante"] == 9
    assert payload["candidate_maximum_ante"] == 9
    assert payload["baseline_mean_log10_best_hand_score"] == 1.5
    assert payload["candidate_mean_log10_best_hand_score"] == 1.5
    assert [row["outcome"] for row in payload["paired"]] == [
        "baseline_only_win",
        "candidate_only_win",
    ]


def module_path_output(module, baseline: Path, candidate: Path) -> str:
    return json.dumps(module.compare_reports(baseline, candidate), sort_keys=True)


def test_compare_rejects_seed_order_and_limits_mismatch(tmp_path: Path) -> None:
    module = _load_script()
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _report(baseline)
    _report(candidate, seeds=(2, 1))
    with pytest.raises(module.ReportError, match="ordered seed panels"):
        module.compare_reports(baseline, candidate)
    _report(candidate)
    value = json.loads(candidate.read_text(encoding="utf-8"))
    value["manifest"]["max_decisions"] = 801
    candidate.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(module.ReportError, match="max_decisions"):
        module.compare_reports(baseline, candidate)


def test_compare_rejects_mixed_seed_provenance(tmp_path: Path) -> None:
    module = _load_script()
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _report(baseline)
    _report(candidate)
    value = json.loads(candidate.read_text(encoding="utf-8"))
    value["benchmark_protocol"]["seed_provenance"] = "gate"
    candidate.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(module.ReportError, match="seed_provenance"):
        module.compare_reports(baseline, candidate)


def test_compare_validates_declared_panel_against_registry(tmp_path: Path) -> None:
    module = _load_script()
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _report(baseline, seeds=(701, 702), provenance="gate")
    _report(candidate, seeds=(701, 702), provenance="gate")

    with pytest.raises(module.ReportError, match="gate panel must be exactly seeds 701-900"):
        module.compare_reports(baseline, candidate)


def test_compare_rejects_quarantined_former_gate_panel(tmp_path: Path) -> None:
    module = _load_script()
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _report(baseline, seeds=(501, 502), provenance="development")
    _report(candidate, seeds=(501, 502), provenance="development")

    with pytest.raises(module.ReportError, match="quarantined former_gate"):
        module.compare_reports(baseline, candidate)


def test_compare_rejects_noncontiguous_row_seed_set(tmp_path: Path) -> None:
    module = _load_script()
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _report(baseline, seeds=(901, 903), provenance="development")
    _report(candidate, seeds=(901, 903), provenance="development")

    with pytest.raises(module.ReportError, match="contiguous ordered seed panel"):
        module.compare_reports(baseline, candidate)


def test_compare_does_not_fabricate_score_delta_for_legacy_reports(tmp_path: Path) -> None:
    module = _load_script()
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _report(baseline)
    _report(candidate)
    for path in (baseline, candidate):
        value = json.loads(path.read_text(encoding="utf-8"))
        for result in value["results"]:
            result.pop("best_hand_score")
        path.write_text(json.dumps(value), encoding="utf-8")

    payload = module.compare_reports(baseline, candidate)

    assert not payload["best_hand_score_metrics_available"]
    assert payload["best_hand_score_pair_coverage"] == 0
    assert payload["paired_mean_log10_best_hand_score_delta"] is None
    assert payload["paired_log10_best_hand_score_delta_bootstrap_95"] is None


def test_compare_rejects_incomplete_marked_as_won(tmp_path: Path) -> None:
    module = _load_script()
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _report(baseline)
    _report(candidate)
    value = json.loads(candidate.read_text(encoding="utf-8"))
    value["results"][0]["complete"] = False
    value["results"][0]["won"] = True
    candidate.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(module.ReportError, match="incomplete run won"):
        module.compare_reports(baseline, candidate)


def test_compare_rejects_incomplete_marked_as_survived(tmp_path: Path) -> None:
    module = _load_script()
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _report(baseline)
    _report(candidate, survivals=(1,))
    value = json.loads(candidate.read_text(encoding="utf-8"))
    value["results"][0]["complete"] = False
    candidate.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(module.ReportError, match="incomplete run survived"):
        module.compare_reports(baseline, candidate)


def test_compare_rejects_survival_inconsistent_with_ante(tmp_path: Path) -> None:
    module = _load_script()
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _report(baseline)
    _report(candidate)
    value = json.loads(candidate.read_text(encoding="utf-8"))
    value["results"][0]["survived_to_ante_6"] = True
    candidate.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(module.ReportError, match="inconsistent survival metric"):
        module.compare_reports(baseline, candidate)


def test_compare_rejects_invalid_completion_reason_and_cap(tmp_path: Path) -> None:
    module = _load_script()
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _report(baseline)
    _report(candidate)
    value = json.loads(candidate.read_text(encoding="utf-8"))
    value["results"][0]["terminal_reason"] = "decision_limit"
    candidate.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(module.ReportError, match="inconsistent completion reason"):
        module.compare_reports(baseline, candidate)

    _report(candidate)
    value = json.loads(candidate.read_text(encoding="utf-8"))
    value["results"][0]["terminal_reason"] = "ante_cap"
    candidate.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(module.ReportError, match="did not reach the ante cap"):
        module.compare_reports(baseline, candidate)
