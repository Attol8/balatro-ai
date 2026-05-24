from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from balatro_ai_v2.actions import ActionKind, GameAction
from balatro_ai_v2.balatrobot.policy_config import DEFAULT_POLICY_CONFIG, ShopPolicyConfig
from balatro_ai_v2.fast.hand import (
    FLUSH,
    FULL_HOUSE,
    HIGH_CARD,
    PAIR,
    STRAIGHT,
    THREE_OF_A_KIND,
    TWO_PAIR,
)
from balatro_ai_v2.fast.jokers import IMPLEMENTED_JOKERS


@dataclass(frozen=True, slots=True)
class ShopDecision:
    action: GameAction | None
    reason: str = "skip"


def plan_shop_action(
    state: dict[str, Any],
    *,
    config: ShopPolicyConfig = DEFAULT_POLICY_CONFIG.shop,
) -> ShopDecision:
    consumable_action = _best_consumable_action(state)
    if consumable_action is not None:
        return consumable_action

    money = int(state.get("money") or 0)
    candidates: list[tuple[float, int, str]] = []
    for index, card in enumerate(_area_cards(state, "shop")):
        cost = _buy_cost(card)
        if cost > money:
            continue
        value = _shop_card_value(state, card, config)
        if value <= cost + config.min_value_margin:
            continue
        candidates.append((value - cost, index, str(card.get("key") or "")))

    if not candidates:
        return ShopDecision(None)
    candidates.sort(reverse=True)
    _, index, key = candidates[0]
    return ShopDecision(GameAction(kind=ActionKind.BUY_CARD, index=index), f"buy {key}")


def _best_consumable_action(state: dict[str, Any]) -> ShopDecision | None:
    for index, card in enumerate(_area_cards(state, "consumables")):
        key = card.get("key")
        if key in _PLANET_TO_HAND_KIND or key in _VALUABLE_NO_TARGET_CONSUMABLES:
            return ShopDecision(
                GameAction(kind=ActionKind.USE_CONSUMABLE, index=index),
                f"use {key}",
            )
    return None


def _shop_card_value(state: dict[str, Any], card: dict[str, Any], config: ShopPolicyConfig) -> float:
    key = str(card.get("key") or "")
    card_set = str(card.get("set") or "")
    if card_set == "JOKER" or key.startswith("j_"):
        return _joker_value(state, key, config)
    if card_set == "PLANET" or key in _PLANET_TO_HAND_KIND:
        return _planet_value(state, key, config)
    if key in _VALUABLE_NO_TARGET_CONSUMABLES and _should_buy_no_target_consumable(state, key, config):
        return config.valuable_no_target_consumable_value
    return 0.0


def _joker_value(state: dict[str, Any], key: str, config: ShopPolicyConfig) -> float:
    if key not in IMPLEMENTED_JOKERS:
        return 0.0
    if key in _owned_jokers(state):
        return 0.0
    if _joker_count(state) >= _joker_limit(state):
        return 0.0

    # The value is intentionally heuristic but grounded in implemented scoring
    # surfaces. BalatroBot remains the oracle; this only decides what is worth
    # trying in a clean shop.
    values = {
        "j_joker": 18.0,
        "j_half": 16.0,
        "j_jolly": 20.0 if _hand_played(state, PAIR) else 12.0,
        "j_sly": 18.0 if _hand_played(state, PAIR) else 10.0,
        "j_mad": 18.0 if _hand_played(state, TWO_PAIR) else 10.0,
        "j_clever": 18.0 if _hand_played(state, TWO_PAIR) else 10.0,
        "j_zany": 18.0 if _hand_played(state, THREE_OF_A_KIND) else 8.0,
        "j_wily": 18.0 if _hand_played(state, THREE_OF_A_KIND) else 8.0,
        "j_crazy": 18.0 if _hand_played(state, STRAIGHT) else 10.0,
        "j_devious": 18.0 if _hand_played(state, STRAIGHT) else 10.0,
        "j_droll": 24.0 if _hand_played(state, FLUSH) else 14.0,
        "j_crafty": 24.0 if _hand_played(state, FLUSH) else 14.0,
        "j_duo": 28.0,
        "j_trio": 22.0,
        "j_tribe": 34.0 if _hand_played(state, FLUSH) else 18.0,
        "j_cavendish": 40.0,
        "j_abstract": 18.0 + 3.0 * _joker_count(state),
        "j_supernova": 14.0,
        "j_blue_joker": 18.0,
        "j_bull": 12.0 + int(state.get("money") or 0) / 2.0,
        "j_bootstraps": 10.0 + int(state.get("money") or 0) / 3.0,
        "j_stuntman": 36.0,
        "j_acrobat": 18.0,
        "j_throwback": 0.0,
    }
    values.update(dict(config.joker_value_overrides))
    return values.get(key, config.modeled_joker_fallback_value)


def _planet_value(state: dict[str, Any], key: str, config: ShopPolicyConfig) -> float:
    hand_kind = _PLANET_TO_HAND_KIND.get(key)
    if hand_kind is None:
        return 0.0
    played = _hand_played(state, hand_kind)
    if played > 0:
        return config.planet_played_base_value + config.planet_played_increment * played
    if hand_kind in _currently_common_hand_kinds(state):
        return config.planet_common_unplayed_value
    return config.planet_unplayed_value


def _currently_common_hand_kinds(state: dict[str, Any]) -> set[int]:
    hands = state.get("hands") or {}
    out: set[int] = set()
    for name, kind in _HAND_NAME_TO_KIND.items():
        if int((hands.get(name) or {}).get("played") or 0) > 0:
            out.add(kind)
    return out


def _hand_played(state: dict[str, Any], hand_kind: int) -> int:
    name = _HAND_KIND_TO_NAME[hand_kind]
    return int(((state.get("hands") or {}).get(name) or {}).get("played") or 0)


def _owned_jokers(state: dict[str, Any]) -> set[str]:
    return {
        str(card.get("key"))
        for card in _area_cards(state, "jokers")
        if isinstance(card.get("key"), str)
    }


def _joker_count(state: dict[str, Any]) -> int:
    return int((state.get("jokers") or {}).get("count") or len(_area_cards(state, "jokers")))


def _joker_limit(state: dict[str, Any]) -> int:
    return int((state.get("jokers") or {}).get("limit") or 5)


def _consumable_count(state: dict[str, Any]) -> int:
    return int((state.get("consumables") or {}).get("count") or len(_area_cards(state, "consumables")))


def _consumable_limit(state: dict[str, Any]) -> int:
    return int((state.get("consumables") or {}).get("limit") or 2)


def _should_buy_no_target_consumable(state: dict[str, Any], key: str, config: ShopPolicyConfig) -> bool:
    if _consumable_count(state) >= _consumable_limit(state):
        return False
    # High Priestess is random planet generation. It is not worth spending down
    # Bull/Bootstraps money in the early game unless the economy is already safe.
    if key == "c_high_priestess" and int(state.get("money") or 0) < config.high_priestess_min_money:
        return False
    return True


def _area_cards(state: dict[str, Any], area: str) -> list[dict[str, Any]]:
    cards = ((state.get(area) or {}).get("cards") or [])
    return [card for card in cards if isinstance(card, dict)]


def _buy_cost(card: dict[str, Any]) -> int:
    return int(((card.get("cost") or {}).get("buy") or 0))


_HAND_KIND_TO_NAME = {
    HIGH_CARD: "High Card",
    PAIR: "Pair",
    TWO_PAIR: "Two Pair",
    THREE_OF_A_KIND: "Three of a Kind",
    STRAIGHT: "Straight",
    FLUSH: "Flush",
    FULL_HOUSE: "Full House",
}
_HAND_NAME_TO_KIND = {name: kind for kind, name in _HAND_KIND_TO_NAME.items()}
_PLANET_TO_HAND_KIND = {
    "c_pluto": HIGH_CARD,
    "c_mercury": PAIR,
    "c_uranus": TWO_PAIR,
    "c_venus": THREE_OF_A_KIND,
    "c_saturn": STRAIGHT,
    "c_jupiter": FLUSH,
    "c_earth": FULL_HOUSE,
}
_VALUABLE_NO_TARGET_CONSUMABLES = {"c_high_priestess"}
