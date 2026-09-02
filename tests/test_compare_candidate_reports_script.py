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


def _report(path: Path, *, seeds=(1, 2), wins=()) -> None:
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
            "max_settle_polls": 0,
            "wall_clock_limit_seconds": None,
            "profile_mode": "all_unlocked",
            "launch_fast": False,
            "launch_headless": False,
            "inference_budget": "budget",
            "run": {"deck": "RED", "stake": "WHITE", "seed": "1:2"},
        },
        "results": [
            {
                "seed": seed,
                "complete": True,
                "won": seed in wins,
                "terminal_reason": "won" if seed in wins else "game_over",
            }
            for seed in seeds
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_compare_counts_paired_outcomes_and_incomplete_as_loss(tmp_path: Path) -> None:
    module = _load_script()
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    _report(baseline, wins=(1,))
    _report(candidate, wins=(2,))
    value = json.loads(candidate.read_text(encoding="utf-8"))
    value["manifest"]["inference_budget"] = "different-policy-budget"
    candidate.write_text(json.dumps(value), encoding="utf-8")
    payload = json.loads(module_path_output(module, baseline, candidate))

    assert payload["baseline_only_wins"] == 1
    assert payload["candidate_only_wins"] == 1
    assert payload["both_wins"] == 0
    assert payload["both_losses"] == 0
    assert payload["raw_win_delta"] == 0
    assert payload["candidate_inference_budget"] == "different-policy-budget"
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
