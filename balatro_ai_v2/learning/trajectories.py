from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

from balatro_ai_v2.fast.full_game import FastFullGameEnv, FullGameStepResult, SearchRunAgent


@dataclass(frozen=True, slots=True)
class TrajectoryStep:
    seed: int
    step: int
    observation: tuple[int, ...]
    legal_actions: tuple[int, ...]
    action: int
    reward: float
    terminated: bool
    won: bool
    rounds_cleared: int
    info: dict[str, int | bool | str | tuple[int, ...]]

    def to_jsonable(self) -> dict:
        return {
            "seed": self.seed,
            "step": self.step,
            "observation": list(self.observation),
            "legal_actions": list(self.legal_actions),
            "action": self.action,
            "reward": self.reward,
            "terminated": self.terminated,
            "won": self.won,
            "rounds_cleared": self.rounds_cleared,
            "info": self.info,
        }

    @classmethod
    def from_jsonable(cls, data: dict) -> "TrajectoryStep":
        info = data.get("info") or {}
        if isinstance(info, dict):
            info = {
                key: tuple(value) if key in {"selected", "jokers"} and isinstance(value, list) else value
                for key, value in info.items()
            }
        return cls(
            seed=int(data["seed"]),
            step=int(data["step"]),
            observation=tuple(int(value) for value in data["observation"]),
            legal_actions=tuple(int(value) for value in data["legal_actions"]),
            action=int(data["action"]),
            reward=float(data["reward"]),
            terminated=bool(data["terminated"]),
            won=bool(data["won"]),
            rounds_cleared=int(data["rounds_cleared"]),
            info=info,
        )


def collect_oracle_trajectories(
    seeds: Iterable[int],
    *,
    deck_key: str = "b_red",
    max_steps: int = 600,
    agent: SearchRunAgent | None = None,
) -> Iterator[TrajectoryStep]:
    oracle = agent or SearchRunAgent()
    for seed in seeds:
        env = FastFullGameEnv(deck_key=deck_key)
        env.reset(seed=seed)
        step = 0
        terminated = False
        while not terminated and step < max_steps:
            observation = env.observation()
            legal_actions = env.legal_action_ids()
            action = oracle.act(env)
            if action not in legal_actions:
                raise ValueError(f"oracle emitted illegal action {action} for seed={seed} step={step}")
            result: FullGameStepResult = env.step(action)
            terminated = result.terminated
            yield TrajectoryStep(
                seed=int(seed),
                step=step,
                observation=observation,
                legal_actions=legal_actions,
                action=action,
                reward=result.reward,
                terminated=terminated,
                won=env.won,
                rounds_cleared=env.rounds_cleared,
                info=result.info,
            )
            step += 1
