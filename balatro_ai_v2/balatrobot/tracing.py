from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from balatro_ai_v2.actions import GameAction


@dataclass(frozen=True, slots=True)
class JsonlTraceWriter:
    path: Path
    include_states: bool = True

    def record(self, event: str, **payload: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")

    def state_payload(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.include_states:
            return state
        return summarize_state(state)


def action_payload(action: GameAction | None = None, *, method: str | None = None, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if action is None:
        return {
            "method": method,
            "params": params or {},
        }
    rpc_method, rpc_params = action.to_balatrobot_rpc()
    return {
        "kind": action.kind.value,
        "indices": list(action.indices),
        "index": action.index,
        "method": rpc_method,
        "params": rpc_params,
    }


def summarize_state(state: dict[str, Any]) -> dict[str, Any]:
    round_info = state.get("round") or {}
    return {
        "state": state.get("state"),
        "seed": state.get("seed"),
        "ante": state.get("ante_num"),
        "round": state.get("round_num"),
        "money": state.get("money"),
        "chips": round_info.get("chips"),
        "hands_left": round_info.get("hands_left"),
        "discards_left": round_info.get("discards_left"),
        "won": state.get("won"),
        "blind": _current_blind(state),
        "hand": _area_keys(state, "hand"),
        "shop": _area_keys(state, "shop"),
        "jokers": _area_keys(state, "jokers"),
        "consumables": _area_keys(state, "consumables"),
    }


def _area_keys(state: dict[str, Any], area: str) -> list[str]:
    return [
        str(card.get("key"))
        for card in ((state.get(area) or {}).get("cards") or [])
        if isinstance(card, dict) and card.get("key") is not None
    ]


def _current_blind(state: dict[str, Any]) -> dict[str, Any] | None:
    blinds = state.get("blinds") or {}
    for blind in blinds.values():
        if isinstance(blind, dict) and blind.get("status") == "CURRENT":
            return {
                "type": blind.get("type"),
                "name": blind.get("name"),
                "score": blind.get("score"),
                "effect": blind.get("effect"),
            }
    return None
