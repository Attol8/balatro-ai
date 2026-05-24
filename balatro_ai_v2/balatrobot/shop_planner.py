from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from balatro_ai_v2.actions import ActionKind, GameAction
from balatro_ai_v2.balatrobot.policy_config import DEFAULT_POLICY_CONFIG, ShopPolicyConfig
from balatro_ai_v2.fast.boosters import BoosterKind, booster_spec
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
    replacement_action = _best_joker_replacement_action(state, config)
    if replacement_action is not None:
        return replacement_action

    candidates: list[tuple[float, int, str]] = []
    pack_candidates: list[tuple[float, int, str]] = []
    for index, card in enumerate(_area_cards(state, "shop")):
        cost = _buy_cost(card)
        if cost > money:
            continue
        if _is_joker_card(card) and _joker_count(state) >= _joker_limit(state):
            continue
        value = _shop_card_value(state, card, config)
        if value <= cost + config.min_value_margin:
            continue
        candidates.append((value - cost, index, str(card.get("key") or "")))
    for index, card in enumerate(_area_cards(state, "packs")):
        cost = _buy_cost(card)
        if cost > money:
            continue
        value = _pack_value(state, card, config)
        if value <= cost + config.min_value_margin:
            continue
        pack_candidates.append((value - cost, index, str(card.get("key") or "")))

    if not candidates and not pack_candidates:
        if _should_reroll_shop(state, config):
            return ShopDecision(GameAction(kind=ActionKind.REROLL), "reroll dead shop")
        return ShopDecision(None)
    if not candidates:
        pack_candidates.sort(reverse=True)
        _, index, key = pack_candidates[0]
        return ShopDecision(GameAction(kind=ActionKind.BUY_PACK, index=index), f"buy {key}")
    candidates.sort(reverse=True)
    _, index, key = candidates[0]
    return ShopDecision(GameAction(kind=ActionKind.BUY_CARD, index=index), f"buy {key}")


def plan_pack_action(
    state: dict[str, Any],
    *,
    config: ShopPolicyConfig = DEFAULT_POLICY_CONFIG.shop,
) -> ShopDecision:
    candidates: list[tuple[float, int, str]] = []
    for index, card in enumerate(_booster_cards(state)):
        value = _pack_card_value(state, card, config)
        if value <= 0:
            continue
        candidates.append((value, index, str(card.get("key") or "")))
    if not candidates:
        return ShopDecision(GameAction(kind=ActionKind.PACK_SKIP), "skip pack")
    candidates.sort(reverse=True)
    _, index, key = candidates[0]
    return ShopDecision(GameAction(kind=ActionKind.PACK_SELECT, index=index), f"pick {key}")


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
    if _is_joker_card(card):
        return _joker_value(state, key, config)
    if card_set == "PLANET" or key in _PLANET_TO_HAND_KIND:
        return _planet_value(state, key, config)
    if key in _VALUABLE_NO_TARGET_CONSUMABLES and _should_buy_no_target_consumable(state, key, config):
        return config.valuable_no_target_consumable_value
    return 0.0


def _pack_card_value(state: dict[str, Any], card: dict[str, Any], config: ShopPolicyConfig) -> float:
    key = str(card.get("key") or "")
    card_set = str(card.get("set") or "")
    if _is_joker_card(card):
        return _joker_value(state, key, config)
    if card_set == "PLANET" or key in _PLANET_TO_HAND_KIND:
        return _planet_value(state, key, config)
    if key in _VALUABLE_NO_TARGET_CONSUMABLES and _should_buy_no_target_consumable(state, key, config):
        return config.valuable_no_target_consumable_value
    if card_set == "DEFAULT":
        return _playing_card_value(card)
    return 0.0


def _pack_value(state: dict[str, Any], card: dict[str, Any], config: ShopPolicyConfig) -> float:
    key = str(card.get("key") or "")
    try:
        spec = booster_spec(key)
    except NotImplementedError:
        return 0.0
    if spec.kind == BoosterKind.BUFFOON:
        if _joker_count(state) >= _joker_limit(state):
            return 0.0
        return config.buffoon_pack_base_value + 2.0 * (spec.size - 2) + 4.0 * (spec.choices - 1)
    if spec.kind == BoosterKind.CELESTIAL:
        if _consumable_count(state) >= _consumable_limit(state):
            return 0.0
        return config.celestial_pack_base_value + 1.5 * (spec.size - 3) + 4.0 * (spec.choices - 1)
    if spec.kind == BoosterKind.STANDARD:
        return config.standard_pack_base_value + 1.0 * (spec.size - 3) + 3.0 * (spec.choices - 1)
    if spec.kind == BoosterKind.ARCANA:
        if _consumable_count(state) >= _consumable_limit(state):
            return 0.0
        return config.arcana_pack_base_value + 1.5 * (spec.size - 3) + 4.0 * (spec.choices - 1)
    if spec.kind == BoosterKind.SPECTRAL:
        if _consumable_count(state) >= _consumable_limit(state):
            return 0.0
        return config.spectral_pack_base_value + 2.0 * (spec.size - 2) + 4.0 * (spec.choices - 1)
    return 0.0


def _joker_value(state: dict[str, Any], key: str, config: ShopPolicyConfig) -> float:
    if key not in IMPLEMENTED_JOKERS:
        return 0.0
    if key in _owned_jokers(state):
        return 0.0
    if _joker_count(state) >= _joker_limit(state):
        return 0.0
    return _joker_base_value(state, key, config)

def _joker_base_value(state: dict[str, Any], key: str, config: ShopPolicyConfig) -> float:
    # The value is intentionally heuristic but grounded in implemented scoring
    # surfaces. BalatroBot remains the oracle; this only decides what is worth
    # trying in a clean shop.
    ante = int(state.get("ante_num") or 1)
    played_flush = _hand_played(state, FLUSH)
    played_pair = _hand_played(state, PAIR)
    played_straight = _hand_played(state, STRAIGHT)
    xmult_need = 10.0 if ante >= 4 and not _has_strong_xmult(state) else 0.0
    values = {
        "j_joker": 16.0,
        "j_half": 16.0,
        "j_scholar": 18.0,
        "j_jolly": 20.0 if played_pair else 12.0,
        "j_sly": 18.0 if played_pair else 10.0,
        "j_mad": 18.0 if _hand_played(state, TWO_PAIR) else 10.0,
        "j_clever": 18.0 if _hand_played(state, TWO_PAIR) else 10.0,
        "j_zany": 18.0 if _hand_played(state, THREE_OF_A_KIND) else 8.0,
        "j_wily": 18.0 if _hand_played(state, THREE_OF_A_KIND) else 8.0,
        "j_crazy": 18.0 if played_straight else 10.0,
        "j_devious": 18.0 if played_straight else 10.0,
        "j_droll": 24.0 if played_flush else 14.0,
        "j_crafty": 24.0 if played_flush else 14.0,
        "j_duo": 34.0 + xmult_need,
        "j_trio": 28.0 + xmult_need,
        "j_order": 32.0 + xmult_need if played_straight else 18.0 + xmult_need,
        "j_tribe": 42.0 + xmult_need if played_flush else 22.0 + xmult_need,
        "j_blackboard": 30.0 + xmult_need,
        "j_card_sharp": 30.0 + xmult_need,
        "j_cavendish": 46.0 + xmult_need,
        "j_abstract": 18.0 + 3.0 * _joker_count(state),
        "j_supernova": 14.0,
        "j_blue_joker": 18.0,
        "j_bull": 20.0 + int(state.get("money") or 0) / 2.0,
        "j_bootstraps": 10.0 + int(state.get("money") or 0) / 3.0,
        "j_stuntman": 36.0,
        "j_acrobat": 18.0,
        "j_mystic_summit": 16.0,
        "j_raised_fist": 24.0,
        "j_green_joker": 22.0,
        "j_runner": 24.0 if played_straight else 14.0,
        "j_trousers": 24.0 if _hand_played(state, TWO_PAIR) else 14.0,
        "j_constellation": 24.0 + xmult_need,
        "j_throwback": 0.0,
    }
    values.update(dict(config.joker_value_overrides))
    return values.get(key, config.modeled_joker_fallback_value) + _open_joker_slot_bonus(state)


def _open_joker_slot_bonus(state: dict[str, Any]) -> float:
    if _joker_count(state) >= _joker_limit(state):
        return 0.0
    ante = int(state.get("ante_num") or 1)
    if ante >= 4:
        return 14.0
    if ante >= 3:
        return 8.0
    return 0.0


def _best_joker_replacement_action(state: dict[str, Any], config: ShopPolicyConfig) -> ShopDecision | None:
    if _joker_count(state) < _joker_limit(state):
        return None
    owned = _owned_joker_replacement_values(state, config)
    if not owned:
        return None

    money = int(state.get("money") or 0)
    best: tuple[float, float, int, float, str, int, str] | None = None
    for shop_index, card in enumerate(_area_cards(state, "shop")):
        if not _is_joker_card(card):
            continue
        key = str(card.get("key") or "")
        if key in _owned_jokers(state) or key not in IMPLEMENTED_JOKERS:
            continue
        cost = _buy_cost(card)
        value = _joker_base_value(state, key, config)
        for owned_index, owned_key, owned_value, sell_value in owned:
            if money + sell_value < cost:
                continue
            improvement = value - owned_value
            net_gain = improvement - max(cost - sell_value, 0)
            if improvement <= config.replacement_min_value_margin:
                continue
            candidate = (improvement, -owned_value, -owned_index, net_gain, owned_key, shop_index, key)
            if best is None or candidate > best:
                best = candidate
    if best is None:
        return None
    _, _, negative_owned_index, _, owned_key, _, key = best
    owned_index = -negative_owned_index
    return ShopDecision(GameAction(kind=ActionKind.SELL_JOKER, index=owned_index), f"sell {owned_key} for {key}")


def _owned_joker_replacement_values(
    state: dict[str, Any],
    config: ShopPolicyConfig,
) -> list[tuple[int, str, float, int]]:
    out: list[tuple[int, str, float, int]] = []
    for index, card in enumerate(_area_cards(state, "jokers")):
        key = str(card.get("key") or "")
        if not key or key not in IMPLEMENTED_JOKERS:
            continue
        value = _joker_base_value(state, key, config) + _owned_scaling_bonus(card)
        sell_value = int(((card.get("cost") or {}).get("sell") or 0))
        out.append((index, key, value, sell_value))
    out.sort(key=lambda item: item[2])
    return out


def _owned_scaling_bonus(card: dict[str, Any]) -> float:
    ability = (card.get("value") or {}).get("ability") or {}
    if not isinstance(ability, dict):
        return 0.0
    key = str(card.get("key") or "")
    if key == "j_square":
        return float(ability.get("chips") or ability.get("extra") or 0) / 4.0
    if key in {"j_ride_the_bus", "j_green_joker", "j_trousers"}:
        return float(ability.get("mult") or ability.get("extra") or 0)
    if key == "j_runner":
        return float(ability.get("chips") or ability.get("extra") or 0) / 8.0
    return 0.0


def _should_reroll_shop(state: dict[str, Any], config: ShopPolicyConfig) -> bool:
    reroll_cost = int(((state.get("round") or {}).get("reroll_cost") or 5))
    money = int(state.get("money") or 0)
    if reroll_cost <= 0:
        return True
    if reroll_cost > config.reroll_max_cost or money - reroll_cost < config.reroll_min_money_after:
        return False
    if _has_valuable_unaffordable_shop_item(state, config):
        return False
    ante = int(state.get("ante_num") or 1)
    has_open_slot = _joker_count(state) < _joker_limit(state)
    if has_open_slot and ante <= 5:
        return True
    return ante >= 3 and not _has_strong_xmult(state)


def _has_valuable_unaffordable_shop_item(state: dict[str, Any], config: ShopPolicyConfig) -> bool:
    money = int(state.get("money") or 0)
    for card in _area_cards(state, "shop"):
        cost = _buy_cost(card)
        if cost <= money:
            continue
        value = _shop_card_value(state, card, config)
        if value > cost + config.min_value_margin + 6.0:
            return True
    return False


def _has_strong_xmult(state: dict[str, Any]) -> bool:
    strong = {
        "j_cavendish",
        "j_duo",
        "j_trio",
        "j_order",
        "j_tribe",
        "j_blackboard",
        "j_card_sharp",
        "j_constellation",
        "j_acrobat",
    }
    return bool(_owned_jokers(state) & strong)


def _planet_value(state: dict[str, Any], key: str, config: ShopPolicyConfig) -> float:
    hand_kind = _PLANET_TO_HAND_KIND.get(key)
    if hand_kind is None:
        return 0.0
    played = _hand_played(state, hand_kind)
    if played > 0:
        value = config.planet_played_base_value + config.planet_played_increment * played
        if _needs_late_joker_slot_filled(state):
            return min(value, config.planet_played_base_value)
        return value
    if hand_kind in _currently_common_hand_kinds(state):
        value = config.planet_common_unplayed_value
    else:
        value = config.planet_unplayed_value
    if _needs_late_joker_slot_filled(state):
        return min(value, 6.0)
    return value


def _needs_late_joker_slot_filled(state: dict[str, Any]) -> bool:
    return int(state.get("ante_num") or 1) >= 4 and _joker_count(state) < _joker_limit(state)


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


def _is_joker_card(card: dict[str, Any]) -> bool:
    key = str(card.get("key") or "")
    return str(card.get("set") or "") == "JOKER" or key.startswith("j_")


def _booster_cards(state: dict[str, Any]) -> list[dict[str, Any]]:
    cards = _area_cards(state, "pack")
    if cards:
        return cards
    return _area_cards(state, "packs")


def _playing_card_value(card: dict[str, Any]) -> float:
    value = card.get("value") or {}
    rank_name = str(value.get("rank") or "")
    rank_value = {
        "A": 11,
        "K": 10,
        "Q": 10,
        "J": 10,
        "T": 10,
    }.get(rank_name, int(rank_name) if rank_name.isdigit() else 0)
    return float(rank_value)


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
