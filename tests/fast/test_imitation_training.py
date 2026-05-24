import json

from balatro_ai_v2.fast.full_game import FastFullGameEnv
from balatro_ai_v2.fast.run import RunPhase
from balatro_ai_v2.learning.imitation import (
    ImitationRunAgent,
    load_action_policy,
    train_linear_policy,
    train_nearest_neighbor_policy,
)
from balatro_ai_v2.learning.trajectories import TrajectoryStep, collect_oracle_trajectories


def test_collect_oracle_trajectories_records_legal_actions() -> None:
    steps = list(collect_oracle_trajectories([1], max_steps=3))

    assert len(steps) == 3
    assert all(step.action in step.legal_actions for step in steps)
    assert steps[0].seed == 1
    assert steps[0].observation


def test_trajectory_step_round_trips_jsonable_payload() -> None:
    step = next(collect_oracle_trajectories([1], max_steps=1))

    restored = TrajectoryStep.from_jsonable(json.loads(json.dumps(step.to_jsonable())))

    assert restored == step


def test_train_linear_policy_learns_oracle_actions_on_small_dataset() -> None:
    steps = list(collect_oracle_trajectories([1], max_steps=8))

    policy, metrics = train_linear_policy(steps, epochs=12, learning_rate=0.2)

    assert metrics["examples"] == 8
    assert 0.0 <= metrics["train_accuracy"] <= 1.0
    assert policy.predict(steps[0].observation, steps[0].legal_actions) in steps[0].legal_actions


def test_train_nearest_neighbor_policy_memorizes_oracle_actions() -> None:
    steps = list(collect_oracle_trajectories([1], max_steps=8))

    policy, metrics = train_nearest_neighbor_policy(steps)

    assert metrics["train_accuracy"] == 1.0
    assert policy.predict(steps[0].observation, steps[0].legal_actions) == steps[0].action


def test_saved_imitation_policy_can_drive_fast_env(tmp_path) -> None:
    steps = list(collect_oracle_trajectories([1], max_steps=8))
    policy, _ = train_nearest_neighbor_policy(steps)
    model_path = tmp_path / "policy.json"
    policy.save(model_path)

    agent = ImitationRunAgent(load_action_policy(model_path))
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=1)
    result = None
    for _ in range(4):
        result = env.step(agent.act(env))
        if result.info["selected"] or env.run.phase == RunPhase.GAME_OVER:
            break

    assert result is not None
    assert result.info["selected"]
