"""Project BalatroBot snapshots to the information available to a player."""

from __future__ import annotations

from math import isfinite
from typing import Any


_PRIVATE_FIELDS = frozenset({"seed", "discard", "poker_hand_iteration_order"})
_AREA_FIELDS = frozenset({"hand", "jokers", "consumables", "shop", "vouchers", "packs", "pack"})
_MAP_FIELDS = _AREA_FIELDS | frozenset({"state", "modifier", "value", "ability", "cost", "round", "hands", "blinds", "used_vouchers"})


def numeric(value: Any, default: float = 0.0) -> float:
    """Read a finite game number; only a missing value uses the default."""
    candidate = default if value is None else value
    if isinstance(candidate, bool) or not isinstance(candidate, (int, float, str)):
        raise ValueError(f"invalid game number: {candidate!r}")
    try:
        result = float(candidate)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"invalid game number: {candidate!r}") from exc
    if not isfinite(result):
        raise ValueError(f"game number must be finite: {candidate!r}")
    return result


def public_observation(raw: dict[str, Any]) -> dict[str, Any]:
    """Copy public state, excluding draw order and face-down card identities.

    The top-level ``cards`` area is the private ordered draw pile. The
    separately exported ``deck_composition`` is the public, unordered deck
    inventory and remains available. Lua encodes empty tables as lists, so
    known mapping fields are normalized before handing them to policies.
    """
    if not isinstance(raw, dict):
        raise ValueError("BalatroBot observation must be an object")
    return _project({key: value for key, value in raw.items() if key != "cards"})


def _project(value: Any, field: str | None = None) -> Any:
    if field == "public_solver":
        # The typed contract uses arrays named hand/jokers rather than API
        # areas. Validate its whitelist without applying Lua-map normalization.
        from balatro_ai_v2.solver.public_codec import public_observation_from_data, public_observation_to_data
        return public_observation_to_data(public_observation_from_data(value))
    if isinstance(value, list):
        if not value and field in _MAP_FIELDS:
            return {}
        return [_project(item) for item in value]
    if not isinstance(value, dict):
        if value is None and field in _MAP_FIELDS:
            return {}
        return value

    card_state = value.get("state")
    if isinstance(card_state, dict) and card_state.get("hidden") is True:
        # IDs, descriptions, modifiers, costs and even a card's set can reveal
        # its identity. Preserve only anonymous occupancy and forced selection.
        visible_state = {"hidden": True}
        if card_state.get("forced_selection") is True:
            visible_state["forced_selection"] = True
        return {"state": visible_state}

    result = {
        key: _project(item, key)
        for key, item in value.items()
        if key not in _PRIVATE_FIELDS
    }
    if field in {"hands", "blinds"}:
        result = {key: {} if item == [] or item is None else item for key, item in result.items()}
    if field in _AREA_FIELDS:
        if result.get("cards") is None or result.get("cards") == {}:
            result["cards"] = []
    return result


def active_blind(state: dict[str, Any]) -> dict[str, Any]:
    """Return the current blind, or an empty object outside a blind."""
    blinds = state.get("blinds")
    if not isinstance(blinds, dict):
        return {}
    for name in ("small", "big", "boss"):
        blind = blinds.get(name)
        if isinstance(blind, dict) and blind.get("status") == "CURRENT":
            return blind
    return {}
