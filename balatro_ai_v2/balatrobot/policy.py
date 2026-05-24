from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from balatro_ai_v2.actions import ActionKind, GameAction
from balatro_ai_v2.balatrobot.imitation_policy import trained_full_action, trained_tactical_action
from balatro_ai_v2.balatrobot.policy_config import DEFAULT_POLICY_CONFIG, PolicyConfig
from balatro_ai_v2.balatrobot.shop_planner import plan_pack_action, plan_shop_action
from balatro_ai_v2.balatrobot.tactical_planner import best_play_action, plan_tactical_action
from balatro_ai_v2.fast.hand import FastScore
from balatro_ai_v2.learning.imitation import ActionPolicy


@dataclass(frozen=True, slots=True)
class BalatroBotPolicy:
    config: PolicyConfig = field(default=DEFAULT_POLICY_CONFIG)
    tactical_model: ActionPolicy | None = None
    full_action_model: ActionPolicy | None = None

    def blind_action(self, state: dict[str, Any]) -> GameAction:
        if self.full_action_model is not None:
            return trained_full_action(state, self.full_action_model)
        selected = _selected_blind(state)
        if selected is not None and _should_skip_blind(selected, state):
            return GameAction(kind=ActionKind.SKIP_BLIND)
        return GameAction(kind=ActionKind.SELECT_BLIND)

    def tactical_action(self, state: dict[str, Any]) -> GameAction:
        if self.full_action_model is not None:
            return trained_full_action(state, self.full_action_model)
        if self.tactical_model is not None:
            return trained_tactical_action(state, self.tactical_model)
        return plan_tactical_action(
            state,
            config=self.config.tactical,
        ).action

    def best_play(self, state: dict[str, Any]) -> tuple[GameAction, FastScore]:
        return best_play_action(state)

    def shop_action(self, state: dict[str, Any]) -> GameAction | None:
        if self.full_action_model is not None:
            return trained_full_action(state, self.full_action_model)
        return plan_shop_action(state, config=self.config.shop).action

    def pack_action(self, state: dict[str, Any]) -> GameAction:
        if self.full_action_model is not None:
            return trained_full_action(state, self.full_action_model)
        return plan_pack_action(state, config=self.config.shop).action

    def round_eval_action(self, state: dict[str, Any]) -> GameAction:
        if self.full_action_model is not None:
            return trained_full_action(state, self.full_action_model)
        return GameAction(kind=ActionKind.CASH_OUT)


def _selected_blind(state: dict[str, Any]) -> dict[str, Any] | None:
    blinds = state.get("blinds") or {}
    for blind in blinds.values():
        if isinstance(blind, dict) and blind.get("status") == "SELECT":
            return blind
    return None


def _should_skip_blind(blind: dict[str, Any], state: dict[str, Any]) -> bool:
    if str(blind.get("type") or "").upper() == "BOSS":
        return False
    tag_name = str(blind.get("tag_name") or "")
    if tag_name in {"Negative Tag", "Polychrome Tag", "Holographic Tag", "Foil Tag"}:
        return not _late_skip_is_dangerous(state)
    if tag_name == "Orbital Tag":
        return int(state.get("ante_num") or 0) >= 3 and not _late_skip_is_dangerous(state)
    if tag_name in {"Economy Tag", "Investment Tag", "Coupon Tag"}:
        return int(state.get("money") or 0) < 12 and not _late_skip_is_dangerous(state)
    return False


def _late_skip_is_dangerous(state: dict[str, Any]) -> bool:
    if int(state.get("ante_num") or 0) < 4:
        return False
    return not _has_late_skip_carry(state)


def _has_late_skip_carry(state: dict[str, Any]) -> bool:
    owned = {
        str(card.get("key") or "")
        for card in (((state.get("jokers") or {}).get("cards") or []))
        if isinstance(card, dict)
    }
    if owned & {
        "j_cavendish",
        "j_duo",
        "j_trio",
        "j_order",
        "j_tribe",
        "j_blackboard",
        "j_card_sharp",
        "j_constellation",
        "j_acrobat",
        "j_stuntman",
    }:
        return True
    money = int(state.get("money") or 0)
    if money >= 20 and owned & {"j_bull", "j_bootstraps"}:
        return True
    return False
