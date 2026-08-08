from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_public_model.py"
    spec = importlib.util.spec_from_file_location("evaluate_public_model_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_public_model_evaluation_requires_frozen_model_and_worker() -> None:
    parser = _load_script().build_parser()

    args = parser.parse_args(
        [
            "--worker-python",
            "/python3.12",
            "--candidate-root",
            "/candidate",
            "--model",
            "/model.pt",
        ]
    )

    assert args.model == Path("/model.pt")
    assert args.seeds == 20
    assert args.max_decisions == 800
    assert not hasattr(args, "training_seed")
    assert not hasattr(args, "policy_seed")


def test_public_model_evaluation_source_has_no_private_engine_imports() -> None:
    path = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_public_model.py"
    source = path.read_text(encoding="utf-8")

    assert "balatro_ai_v2.jackdaw" not in source
    assert "balatro_ai_v2.balatrobot" not in source
    assert "snapshot" not in source
