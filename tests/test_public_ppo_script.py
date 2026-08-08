from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

torch = pytest.importorskip("torch")

from balatro_ai_v2.balatrobot.adapter import to_public_observation  # noqa: E402
from balatro_ai_v2.public_env_process import PublicTransition  # noqa: E402
from state_factory import state  # noqa: E402


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "train_public_ppo.py"
    spec = importlib.util.spec_from_file_location("train_public_ppo_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_generalized_advantage_estimate_stops_at_episode_boundaries() -> None:
    script = _load_script()
    rewards = torch.tensor([[0.0], [1.0], [5.0]])
    terminated = torch.tensor([[False], [True], [False]])
    truncated = torch.zeros_like(terminated)
    values = torch.zeros_like(rewards)

    advantages, returns = script.generalized_advantage_estimate(
        rewards,
        terminated,
        truncated,
        values,
        torch.tensor([2.0]),
        torch.zeros_like(values),
        gamma=1.0,
        gae_lambda=1.0,
    )

    assert advantages[:, 0].tolist() == [1.0, 1.0, 7.0]
    assert torch.equal(advantages, returns)


def test_truncation_bootstraps_without_crossing_episode_boundary() -> None:
    script = _load_script()
    rewards = torch.tensor([[0.0], [9.0]])
    terminated = torch.tensor([[False], [False]])
    truncated = torch.tensor([[True], [False]])
    values = torch.tensor([[1.0], [0.0]])
    truncation_values = torch.tensor([[3.0], [0.0]])

    advantages, returns = script.generalized_advantage_estimate(
        rewards,
        terminated,
        truncated,
        values,
        torch.tensor([2.0]),
        truncation_values,
        gamma=1.0,
        gae_lambda=1.0,
    )

    assert advantages[:, 0].tolist() == [2.0, 11.0]
    assert returns[:, 0].tolist() == [3.0, 11.0]


def test_public_progress_reward_uses_only_bounded_round_delta() -> None:
    script = _load_script()
    before = to_public_observation(state("SELECTING_HAND"))
    after = to_public_observation(state("GAME_OVER", won=False))
    transition = PublicTransition(after, -1, True, False, "game_over", False, 1)

    reward = script._training_reward(before, transition, "public_progress_v1", 0.25)

    assert reward == -0.75
    assert script._training_reward(before, transition, "sparse_terminal_v1", 0.25) == -1.0


def test_public_ppo_cli_defaults_are_bounded_and_public() -> None:
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
        ]
    )

    assert args.training_reward == "sparse_terminal_v1"
    assert args.workers == 4
    assert args.max_episode_steps == 800
    assert not hasattr(args, "model_seed")
    assert not hasattr(args, "snapshot")


def test_public_ppo_argument_validation_rejects_invalid_bounds() -> None:
    script = _load_script()
    args = SimpleNamespace(
        workers=0,
        updates=1,
        rollout_steps=1,
        max_episode_steps=1,
        hidden_size=1,
        ppo_epochs=1,
        minibatch_size=1,
        environment_timeout=1.0,
        learning_rate=1e-3,
        max_gradient_norm=1.0,
        gamma=0.99,
        gae_lambda=0.95,
        clip_ratio=0.2,
        progress_reward=0.0,
        value_coefficient=0.5,
        entropy_coefficient=0.01,
    )

    with pytest.raises(SystemExit, match="must be positive"):
        script._validate_args(args)


def test_public_ppo_source_has_no_private_engine_imports() -> None:
    path = Path(__file__).resolve().parents[1] / "scripts" / "train_public_ppo.py"
    source = path.read_text(encoding="utf-8")

    assert "balatro_ai_v2.jackdaw" not in source
    assert "balatro_ai_v2.balatrobot" not in source
    assert "snapshot" not in source
    assert "raw_state" not in source
