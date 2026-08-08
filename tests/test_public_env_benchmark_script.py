from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_public_env.py"
    spec = importlib.util.spec_from_file_location("benchmark_public_env_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_environment_benchmark_requires_explicit_worker_and_candidate() -> None:
    parser = _load_script().build_parser()

    args = parser.parse_args(
        [
            "--worker-python",
            "/python3.12",
            "--candidate-root",
            "/candidate",
            "--policy",
            "greedy",
        ]
    )

    assert args.worker_python == Path("/python3.12")
    assert args.candidate_root == Path("/candidate")
    assert args.max_decisions == 800
    assert not hasattr(args, "model")
    assert not hasattr(args, "seed")


def test_public_environment_benchmark_has_no_private_engine_imports() -> None:
    path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_public_env.py"
    source = path.read_text(encoding="utf-8")

    assert "balatro_ai_v2.jackdaw" not in source
    assert "balatro_ai_v2.balatrobot" not in source


def test_expected_report_comparison_selects_the_requested_seed_panel(tmp_path: Path) -> None:
    script = _load_script()
    expected = tmp_path / "expected.json"
    rows = [
        {"seed": 1, "complete": True},
        {"seed": 2, "complete": True},
    ]
    expected.write_text(json.dumps({"results": rows}), encoding="utf-8")

    assert script._compare_expected(expected, rows[:1]) is True
    assert script._compare_expected(expected, [{"seed": 1, "complete": False}]) is False
