"""PlannerPolicy: drive the live BalatroBot game with the planner core.

Same surface as BalatroBotPolicy. Every decision mirrors the live state into
a FastFullGameEnv, asks PlannerCore, and maps the fast action id back to a
GameAction. Any mirror failure or illegal mapping falls back to the heuristic
planners and is logged so divergences can be triaged.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any

from balatro_ai_v2.actions import ActionKind, GameAction
from balatro_ai_v2.balatrobot.imitation_policy import (
    _area_cards,
    fast_legal_full_actions,
    full_fast_action_to_game_action,
)
from balatro_ai_v2.balatrobot.policy import BalatroBotPolicy
from balatro_ai_v2.balatrobot.shop_planner import _targeted_tarot_targets
from balatro_ai_v2.fast.consumables import TAROT_TARGET_LIMITS
from balatro_ai_v2.planner.core import PlannerConfig, PlannerCore
from balatro_ai_v2.planner.mirror import mirror_live_state


@dataclass(slots=True)
class PlannerPolicy:
    config: PlannerConfig = field(default_factory=lambda: PlannerConfig(determinizations=3))
    deck_key: str = "b_red"
    fallback: BalatroBotPolicy = field(default_factory=BalatroBotPolicy)
    log_fallbacks: bool = True
    fallback_count: int = field(default=0, init=False)
    _core: PlannerCore = field(init=False)

    def __post_init__(self) -> None:
        self._core = PlannerCore(config=self.config)

    def blind_action(self, state: dict[str, Any]) -> GameAction:
        return self._decide(state, default=lambda: self.fallback.blind_action(state))

    def tactical_action(self, state: dict[str, Any]) -> GameAction:
        return self._decide(state, default=lambda: self.fallback.tactical_action(state))

    def shop_action(self, state: dict[str, Any]) -> GameAction | None:
        return self._decide(state, default=lambda: self.fallback.shop_action(state))

    def pack_action(self, state: dict[str, Any]) -> GameAction:
        return self._decide(state, default=lambda: self.fallback.pack_action(state))

    def round_eval_action(self, state: dict[str, Any]) -> GameAction:
        return GameAction(kind=ActionKind.CASH_OUT)

    def _decide(self, state: dict[str, Any], *, default) -> GameAction:
        try:
            env = mirror_live_state(state, deck_key=self.deck_key)
            action_id = self._core.decide(env)
            legal = fast_legal_full_actions(state)
            if action_id not in legal:
                raise ValueError(
                    f"planner chose illegal action {action_id} (legal: {sorted(legal)[:12]}...)"
                )
            return _with_required_targets(state, full_fast_action_to_game_action(action_id))
        except Exception as exc:  # noqa: BLE001 - live runs must never crash on a mirror gap
            self.fallback_count += 1
            if self.log_fallbacks:
                print(
                    f"[planner-fallback] state={state.get('state')} ante={state.get('ante_num')} "
                    f"error={exc}",
                    file=sys.stderr,
                )
            return default()


def _with_required_targets(state: dict[str, Any], action: GameAction) -> GameAction:
    """Attach target cards to actions that need them in the live RPC.

    The fast env applies targeted tarots abstractly; the live game requires
    explicit target hand cards. Raising when no targets exist routes the
    decision to the heuristic fallback instead of crashing the run.
    """
    if action.kind == ActionKind.PACK_SELECT:
        area = "pack"
    elif action.kind == ActionKind.USE_CONSUMABLE:
        area = "consumables"
    else:
        return action
    cards = _area_cards(state, area)
    if action.index is None or not 0 <= action.index < len(cards):
        return action
    key = str(cards[action.index].get("key") or "")
    if key not in TAROT_TARGET_LIMITS:
        return action
    targets = _targeted_tarot_targets(state, key)
    if not targets:
        raise ValueError(f"{key} requires hand targets but none are available")
    return GameAction(kind=action.kind, index=action.index, indices=targets)
