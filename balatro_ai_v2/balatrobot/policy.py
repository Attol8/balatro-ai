from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from balatro_ai_v2.actions import GameAction
from balatro_ai_v2.balatrobot.policy_config import DEFAULT_POLICY_CONFIG, PolicyConfig
from balatro_ai_v2.balatrobot.shop_planner import plan_shop_action
from balatro_ai_v2.balatrobot.tactical_planner import best_play_action, plan_tactical_action
from balatro_ai_v2.fast.hand import FLUSH, FastScore


@dataclass(frozen=True, slots=True)
class BalatroBotPolicy:
    target_hand_kind: int = FLUSH
    config: PolicyConfig = field(default=DEFAULT_POLICY_CONFIG)

    def tactical_action(self, state: dict[str, Any]) -> GameAction:
        return plan_tactical_action(
            state,
            config=self.config.tactical,
        ).action

    def best_play(self, state: dict[str, Any]) -> tuple[GameAction, FastScore]:
        return best_play_action(state)

    def shop_action(self, state: dict[str, Any]) -> GameAction | None:
        return plan_shop_action(state, config=self.config.shop).action
