from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_candidate_baselines.py"
    spec = importlib.util.spec_from_file_location("evaluate_candidate_baselines_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_candidate_baseline_cli_has_only_public_control_policies() -> None:
    parser = _load_script().build_parser()

    args = parser.parse_args(["--policy", "greedy"])

    assert args.policy == "greedy"
    assert not hasattr(args, "model")
    assert not hasattr(args, "search")
