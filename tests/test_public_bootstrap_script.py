from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from balatro_ai_v2.balatrobot.adapter import to_public_observation
from state_factory import state


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_public_model.py"
    spec = importlib.util.spec_from_file_location("bootstrap_public_model_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_public_bootstrap_cli_is_bounded_to_public_behavior_policies() -> None:
    parser = _load_script().build_parser()

    args = parser.parse_args(
        [
            "--worker-python",
            "/python3.12",
            "--candidate-root",
            "/candidate",
            "--output-model",
            "/model.pt",
        ]
    )

    assert args.policy == "greedy"
    assert args.episodes == 100
    assert args.max_decisions == 800
    assert not hasattr(args, "snapshot")
    assert not hasattr(args, "oracle")


def test_strategic_bootstrap_trains_only_shop_and_pack_decisions() -> None:
    script = _load_script()
    parser = script.build_parser()
    args = parser.parse_args(
        [
            "--worker-python",
            "/python3.12",
            "--candidate-root",
            "/candidate",
            "--output-model",
            "/model.pt",
            "--policy",
            "strategic",
        ]
    )

    assert script._behavior_scope(args.policy) == "shop_pack"
    assert script._include_behavior_step(args.policy, to_public_observation(state("SHOP")))
    assert not script._include_behavior_step(
        args.policy,
        to_public_observation(state("SELECTING_HAND")),
    )


def test_public_bootstrap_source_has_no_private_engine_imports() -> None:
    path = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_public_model.py"
    source = path.read_text(encoding="utf-8")

    assert "balatro_ai_v2.jackdaw" not in source
    assert "balatro_ai_v2.balatrobot" not in source
    assert "snapshot" not in source
    assert "raw_state" not in source
