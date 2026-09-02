from __future__ import annotations

import importlib.util
from pathlib import Path

import torch

from balatro_ai_v2.actions import LeaveShop
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.public_model import PublicModelConfig, PublicRecurrentPolicyValue
from balatro_ai_v2.search_distillation import (
    SearchComparison,
    comparison_from_data,
    comparison_to_data,
    distillation_loss,
)
from state_factory import state


def test_search_comparison_round_trips_only_public_fields() -> None:
    observation = to_public_observation(state("SHOP"))
    comparison = SearchComparison(observation, (LeaveShop(),), (0.25,), LeaveShop())

    restored = comparison_from_data(comparison_to_data(comparison))

    assert restored == comparison
    assert "seed" not in comparison_to_data(comparison)


def test_distillation_loss_trains_policy_and_value_heads() -> None:
    observation = to_public_observation(state("SHOP"))
    comparison = SearchComparison(
        observation,
        (LeaveShop(),),
        (0.25,),
        LeaveShop(),
    )
    model = PublicRecurrentPolicyValue(PublicModelConfig(hidden_size=16))

    loss, metrics = distillation_loss(model, (comparison,))

    assert torch.isfinite(loss)
    assert metrics["loss"] >= 0


def test_collect_and_train_cli_have_no_private_state_arguments() -> None:
    for name in ("collect_search_comparisons.py", "train_search_distillation.py"):
        path = Path(__file__).resolve().parents[1] / "scripts" / name
        spec = importlib.util.spec_from_file_location(name.replace(".", "_"), path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        destinations = {action.dest for action in module.build_parser()._actions}
        assert "snapshot" not in destinations
        assert "raw_state" not in path.read_text(encoding="utf-8")
