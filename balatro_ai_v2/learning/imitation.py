from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol, Sequence

from balatro_ai_v2.fast.cards import chips as card_chips, rank, suit
from balatro_ai_v2.fast.env import DISCARD_ACTION_OFFSET
from balatro_ai_v2.fast.full_game import (
    BUY_CARD_ACTION_BASE,
    BUY_PACK_ACTION_BASE,
    BUY_VOUCHER_ACTION,
    CASH_OUT_ACTION,
    NEXT_ROUND_ACTION,
    PACK_SELECT_ACTION_BASE,
    PACK_SKIP_ACTION,
    REROLL_ACTION,
    SELECT_BLIND_ACTION,
    SELL_JOKER_ACTION_BASE,
    SKIP_BLIND_ACTION,
    USE_CONSUMABLE_ACTION_BASE,
    FastFullGameEnv,
)
from balatro_ai_v2.fast.hand import HAND_KIND_NAMES, score_cards_with_levels
from balatro_ai_v2.learning.trajectories import TrajectoryStep


class ActionPolicy(Protocol):
    def predict(self, observation: Sequence[int], legal_actions: Sequence[int]) -> int: ...


@dataclass(slots=True)
class LinearActionPolicy:
    weights: list[float]

    @classmethod
    def new(cls, feature_count: int) -> "LinearActionPolicy":
        return cls(weights=[0.0] * feature_count)

    def predict(self, observation: Sequence[int], legal_actions: Sequence[int]) -> int:
        if not legal_actions:
            raise ValueError("legal_actions must not be empty")
        return max(legal_actions, key=lambda action: self._score(observation, action))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "feature_count": len(self.weights),
                    "model_type": "linear_state_action_ranker",
                    "weights": self.weights,
                },
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "LinearActionPolicy":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(weights=[float(value) for value in data["weights"]])

    def _score(self, observation: Sequence[int], action: int) -> float:
        features = action_features(observation, action)
        return sum(weight * value for weight, value in zip(self.weights, features))


@dataclass(slots=True)
class NearestNeighborActionPolicy:
    examples: list[tuple[tuple[float, ...], int]]

    def predict(self, observation: Sequence[int], legal_actions: Sequence[int]) -> int:
        if not legal_actions:
            raise ValueError("legal_actions must not be empty")
        legal = set(legal_actions)
        features = observation_features(observation)
        candidates = (example for example in self.examples if example[1] in legal)
        nearest = min(candidates, key=lambda example: _squared_distance(features, example[0]), default=None)
        if nearest is None:
            return legal_actions[0]
        return nearest[1]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "model_type": "nearest_neighbor",
                    "examples": [
                        {"features": list(features), "action": action}
                        for features, action in self.examples
                    ],
                },
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "NearestNeighborActionPolicy":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            examples=[
                (tuple(float(value) for value in row["features"]), int(row["action"]))
                for row in data["examples"]
            ]
        )


@dataclass(slots=True)
class ImitationRunAgent:
    policy: ActionPolicy

    def act(self, env: FastFullGameEnv) -> int:
        return self.policy.predict(env.observation(), env.legal_action_ids())


def train_linear_policy(
    steps: Iterable[TrajectoryStep],
    *,
    epochs: int = 5,
    learning_rate: float = 0.1,
) -> tuple[LinearActionPolicy, dict[str, float | int]]:
    data = list(steps)
    if not data:
        raise ValueError("cannot train imitation policy from empty data")
    feature_count = len(action_features(data[0].observation, data[0].action))
    policy = LinearActionPolicy.new(feature_count)
    updates = 0
    for _ in range(epochs):
        for step in data:
            predicted = policy.predict(step.observation, step.legal_actions)
            if predicted == step.action:
                continue
            target_features = action_features(step.observation, step.action)
            predicted_features = action_features(step.observation, predicted)
            _add_scaled(policy.weights, target_features, learning_rate)
            _add_scaled(policy.weights, predicted_features, -learning_rate)
            updates += 1
    accuracy = imitation_accuracy(policy, data)
    return policy, {
        "examples": len(data),
        "epochs": epochs,
        "updates": updates,
        "train_accuracy": accuracy,
    }


def train_nearest_neighbor_policy(steps: Iterable[TrajectoryStep]) -> tuple[NearestNeighborActionPolicy, dict[str, float | int]]:
    data = list(steps)
    if not data:
        raise ValueError("cannot train imitation policy from empty data")
    policy = NearestNeighborActionPolicy(
        examples=[(observation_features(step.observation), step.action) for step in data]
    )
    return policy, {
        "examples": len(data),
        "train_accuracy": imitation_accuracy(policy, data),
    }


def load_action_policy(path: Path) -> ActionPolicy:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("model_type") == "nearest_neighbor":
        return NearestNeighborActionPolicy.load(path)
    return LinearActionPolicy.load(path)


def imitation_accuracy(policy: ActionPolicy, steps: Iterable[TrajectoryStep]) -> float:
    total = 0
    correct = 0
    for step in steps:
        total += 1
        correct += int(policy.predict(step.observation, step.legal_actions) == step.action)
    return correct / max(total, 1)


def observation_features(observation: Sequence[int]) -> tuple[float, ...]:
    features = [1.0]
    for index, value in enumerate(observation):
        features.append(_scale_observation_value(index, int(value)))
    return tuple(features)


def action_features(observation: Sequence[int], action: int) -> tuple[float, ...]:
    action_kind_features = _action_kind_features(action)
    if action >= SELECT_BLIND_ACTION:
        return tuple(
            [
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                int(observation[4]) / 100.0,
                int(observation[7]) / 5.0,
                int(observation[8]) / 5.0,
                *([0.0] * 4),
                *([0.0] * 4),
                *([0.0] * len(HAND_KIND_NAMES)),
                *([0.0] * 8),
                *action_kind_features,
            ]
        )
    is_discard = action >= DISCARD_ACTION_OFFSET
    mask = action - DISCARD_ACTION_OFFSET if is_discard else action
    levels = tuple(int(value) for value in observation[10 : 10 + len(HAND_KIND_NAMES)])
    hand = tuple(int(value) for value in observation[-8:] if int(value) >= 0)
    selected = tuple(card for index, card in enumerate(hand) if mask & (1 << index))
    held = tuple(card for index, card in enumerate(hand) if not mask & (1 << index))
    selected_score = score_cards_with_levels(tuple(sorted(selected)), levels) if selected else None
    remaining = max(int(observation[6]) - int(observation[5]), 1)
    selected_chips = sum(card_chips(card) for card in selected)
    held_chips = sum(card_chips(card) for card in held)
    rank_counts = _rank_buckets(selected)
    suit_counts = _suit_counts(selected)
    hand_kind_features = [0.0] * len(HAND_KIND_NAMES)
    if selected_score is not None and not is_discard:
        hand_kind_features[selected_score.kind] = 1.0
    score_total = 0 if selected_score is None or is_discard else selected_score.total
    score_chips = 0 if selected_score is None or is_discard else selected_score.chips
    score_mult = 0 if selected_score is None or is_discard else selected_score.mult
    selected_positions = [1.0 if mask & (1 << index) else 0.0 for index in range(8)]
    return tuple(
        [
            1.0,
            0.0 if is_discard else 1.0,
            1.0 if is_discard else 0.0,
            len(selected) / 5.0,
            len(held) / 8.0,
            selected_chips / 60.0,
            held_chips / 90.0,
            score_total / remaining,
            score_chips / 500.0,
            score_mult / 50.0,
            int(observation[4]) / 100.0,
            int(observation[7]) / 5.0,
            int(observation[8]) / 5.0,
            *rank_counts,
            *suit_counts,
            *hand_kind_features,
            *selected_positions,
            *action_kind_features,
        ]
    )


def _action_kind_features(action: int) -> tuple[float, ...]:
    buckets = [0.0] * 12
    if action < DISCARD_ACTION_OFFSET:
        buckets[0] = 1.0
    elif action < SELECT_BLIND_ACTION:
        buckets[1] = 1.0
    elif action == SELECT_BLIND_ACTION:
        buckets[2] = 1.0
    elif action == SKIP_BLIND_ACTION:
        buckets[3] = 1.0
    elif action == CASH_OUT_ACTION:
        buckets[4] = 1.0
    elif action == NEXT_ROUND_ACTION:
        buckets[5] = 1.0
    elif action == REROLL_ACTION:
        buckets[6] = 1.0
    elif action == BUY_VOUCHER_ACTION:
        buckets[11] = 1.0
    elif BUY_CARD_ACTION_BASE <= action < BUY_CARD_ACTION_BASE + 8:
        buckets[7] = 1.0
    elif BUY_PACK_ACTION_BASE <= action < BUY_PACK_ACTION_BASE + 8:
        buckets[8] = 1.0
    elif SELL_JOKER_ACTION_BASE <= action < SELL_JOKER_ACTION_BASE + 8:
        buckets[9] = 1.0
    elif USE_CONSUMABLE_ACTION_BASE <= action < USE_CONSUMABLE_ACTION_BASE + 8:
        buckets[10] = 1.0
    elif PACK_SELECT_ACTION_BASE <= action < PACK_SELECT_ACTION_BASE + 8 or action == PACK_SKIP_ACTION:
        buckets[8] = 1.0
    return tuple(buckets)


def _scale_observation_value(index: int, value: int) -> float:
    if value < 0:
        return 0.0
    if index == 0:
        return value / 5.0
    if index in {1, 2, 3, 7, 8}:
        return value / 10.0
    if index in {4, 9}:
        return value / 100.0
    if index in {5, 6}:
        return value / 100_000.0
    if 10 <= index < 22:
        return value / 20.0
    if 22 <= index < 34:
        return value / 30.0
    return value / 60.0


def _add_scaled(weights: list[float], features: Sequence[float], scale: float) -> None:
    for index, value in enumerate(features):
        weights[index] += scale * value


def _rank_buckets(cards: Sequence[int]) -> tuple[float, float, float, float]:
    if not cards:
        return (0.0, 0.0, 0.0, 0.0)
    low = sum(1 for card in cards if rank(card) <= 3)
    mid = sum(1 for card in cards if 4 <= rank(card) <= 8)
    face = sum(1 for card in cards if 9 <= rank(card) <= 11)
    ace = sum(1 for card in cards if rank(card) == 12)
    return (low / 5.0, mid / 5.0, face / 5.0, ace / 5.0)


def _suit_counts(cards: Sequence[int]) -> tuple[float, float, float, float]:
    return tuple(sum(1 for card in cards if suit(card) == target_suit) / 5.0 for target_suit in range(4))


def _squared_distance(left: Sequence[float], right: Sequence[float]) -> float:
    return sum((a - b) ** 2 for a, b in zip(left, right))
