from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_jackdaw_rollouts.py"
    spec = importlib.util.spec_from_file_location("benchmark_jackdaw_rollouts_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rollout_benchmark_cli_is_candidate_only_and_bounded() -> None:
    module = _load_script()
    args = module.build_parser().parse_args(["--seed", "7", "--repeats", "25"])

    assert args.seed == 7
    assert args.repeats == 25
    assert not hasattr(args, "snapshot")
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "candidate_only" in source
    assert "fixture_public_digest" in source
