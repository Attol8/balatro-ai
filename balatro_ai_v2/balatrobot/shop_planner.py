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
from balatro_ai_v2.fast.joker_money import DOLLAR_BONUS_JOKERS, MONEY_EVENT_JOKERS
from balatro_ai_v2.fast.joker_run_rules import RUN_EFFECT_JOKERS


@dataclass(frozen=True, slots=True)
class ShopDecision:
    action: GameAction | None
    reason: str = "skip"


def plan_shop_action(
    state: dict[str, Any],
    *,
    config: ShopPolicyConfig = DEFAULT_POLICY_CONFIG.shop,
) -> ShopDecision:
    consumable_action = plan_consumable_action(state, config=config)
    if consumable_action is not None:
        return consumable_action

    money = int(state.get("money") or 0)
    replacement_action = _best_joker_replacement_action(state, config)
    if replacement_action is not None:
        return replacement_action
    sell_to_afford_action = _best_sell_to_afford_joker_action(state, config)
    if sell_to_afford_action is not None:
        return sell_to_afford_action

    candidates: list[tuple[float, float, int, int, ActionKind, str]] = []
    for index, card in enumerate(_area_cards(state, "shop")):
        cost = _buy_cost(card)
        if cost > money:
            continue
        if _is_joker_card(card) and not _can_add_joker_card(state, card):
            continue
        value = _shop_card_value(state, card, config)
        if value <= cost + config.min_value_margin:
            continue
        candidates.append((value - cost, value, 30, -index, ActionKind.BUY_CARD, str(card.get("key") or "")))
    for index, card in enumerate(_area_cards(state, "packs")):
        cost = _buy_cost(card)
        if cost > money:
            continue
        value = _pack_value(state, card, config)
        if value <= cost + config.min_value_margin:
            continue
        candidates.append((value - cost, value, 20, -index, ActionKind.BUY_PACK, str(card.get("key") or "")))
    for index, card in enumerate(_area_cards(state, "vouchers")):
        cost = _buy_cost(card)
        if cost > money:
            continue
        key = str(card.get("key") or "")
        value = _voucher_value(state, key, config)
        if value <= cost + config.min_value_margin:
            continue
        candidates.append((value - cost, value, 40, -index, ActionKind.BUY_VOUCHER, key))

    if not candidates:
        if _should_reroll_shop(state, config):
            return ShopDecision(GameAction(kind=ActionKind.REROLL), "reroll dead shop")
        return ShopDecision(None)
    candidates.sort(reverse=True)
    _, _, _, negative_index, kind, key = candidates[0]
    return ShopDecision(GameAction(kind=kind, index=-negative_index), f"buy {key}")


def plan_pack_action(
    state: dict[str, Any],
    *,
    config: ShopPolicyConfig = DEFAULT_POLICY_CONFIG.shop,
) -> ShopDecision:
    candidates: list[tuple[float, int, str, tuple[int, ...]]] = []
    for index, card in enumerate(_booster_cards(state)):
        value, targets = _pack_card_value_and_targets(state, card, config)
        if value <= 0:
            continue
        candidates.append((value, index, str(card.get("key") or ""), targets))
    if not candidates:
        return ShopDecision(GameAction(kind=ActionKind.PACK_SKIP), "skip pack")
    candidates.sort(reverse=True)
    _, index, key, targets = candidates[0]
    return ShopDecision(GameAction(kind=ActionKind.PACK_SELECT, index=index, indices=targets), f"pick {key}")


def plan_consumable_action(
    state: dict[str, Any],
    *,
    config: ShopPolicyConfig = DEFAULT_POLICY_CONFIG.shop,
) -> ShopDecision | None:
    for index, card in enumerate(_area_cards(state, "consumables")):
        key = str(card.get("key") or "")
        if key in _PLANET_TO_HAND_KIND or _no_target_tarot_value(state, key, config, held=True) > 0:
            return ShopDecision(
                GameAction(kind=ActionKind.USE_CONSUMABLE, index=index),
                f"use {key}",
            )
    return None


def _shop_card_value(state: dict[str, Any], card: dict[str, Any], config: ShopPolicyConfig) -> float:
    key = str(card.get("key") or "")
    card_set = str(card.get("set") or "")
    if _is_joker_card(card):
        return _joker_value(state, key, config, can_add=_can_add_joker_card(state, card))
    if card_set == "PLANET" or key in _PLANET_TO_HAND_KIND:
        return _planet_value(state, key, config)
    if _is_tarot_card(card):
        return _shop_tarot_value(state, key, config)
    return 0.0


def _pack_card_value(state: dict[str, Any], card: dict[str, Any], config: ShopPolicyConfig) -> float:
    value, _ = _pack_card_value_and_targets(state, card, config)
    return value


def _pack_card_value_and_targets(
    state: dict[str, Any],
    card: dict[str, Any],
    config: ShopPolicyConfig,
) -> tuple[float, tuple[int, ...]]:
    key = str(card.get("key") or "")
    card_set = str(card.get("set") or "")
    if _is_joker_card(card):
        return _joker_value(state, key, config, can_add=_can_add_joker_card(state, card)), ()
    if card_set == "PLANET" or key in _PLANET_TO_HAND_KIND:
        return _planet_value(state, key, config), ()
    if _is_tarot_card(card):
        return _pack_tarot_value_and_targets(state, key, config)
    if card_set == "DEFAULT":
        return _playing_card_value(card), ()
    return 0.0, ()


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
        if _needs_late_carry_upgrade(state):
            return 0.0
        if _consumable_count(state) >= _consumable_limit(state):
            return 0.0
        return config.celestial_pack_base_value + 1.5 * (spec.size - 3) + 4.0 * (spec.choices - 1)
    if spec.kind == BoosterKind.STANDARD:
        if _needs_late_carry_upgrade(state):
            return 0.0
        return config.standard_pack_base_value + 1.0 * (spec.size - 3) + 3.0 * (spec.choices - 1)
    if spec.kind == BoosterKind.ARCANA:
        if _needs_late_carry_upgrade(state):
            return 0.0
        if _buy_cost(card) > 0 and int(state.get("money") or 0) - _buy_cost(card) < config.reroll_min_money_after:
            return 0.0
        return config.arcana_pack_base_value + 1.5 * (spec.size - 3) + 4.0 * (spec.choices - 1)
    if spec.kind == BoosterKind.SPECTRAL:
        if _consumable_count(state) >= _consumable_limit(state):
            return 0.0
        return config.spectral_pack_base_value + 2.0 * (spec.size - 2) + 4.0 * (spec.choices - 1)
    return 0.0


def _voucher_value(state: dict[str, Any], key: str, config: ShopPolicyConfig) -> float:
    if not key or key in _owned_vouchers(state):
        return 0.0
    ante = int(state.get("ante_num") or 1)
    money = int(state.get("money") or 0)
    values = {
        "v_overstock_norm": 18.0,
        "v_overstock_plus": 14.0,
        "v_clearance_sale": 24.0,
        "v_liquidation": 26.0,
        "v_reroll_surplus": 14.0,
        "v_reroll_glut": 16.0,
        "v_crystal_ball": 10.0,
        "v_grabber": 30.0,
        "v_nacho_tong": 28.0,
        "v_wasteful": 14.0,
        "v_recyclomancy": 12.0,
        "v_planet_merchant": 14.0,
        "v_planet_tycoon": 12.0,
        "v_tarot_merchant": 14.0,
        "v_tarot_tycoon": 12.0,
        "v_seed_money": 10.0 + min(money, 25) / 5.0,
        "v_money_tree": 12.0 + min(money, 40) / 5.0,
        "v_telescope": 14.0,
        "v_observatory": 18.0,
        "v_antimatter": 30.0,
        "v_hone": 12.0,
        "v_glow_up": 12.0,
        "v_omen_globe": 8.0,
        "v_magic_trick": 4.0,
        "v_illusion": 6.0,
        "v_paint_brush": 24.0,
        "v_palette": 20.0,
        "v_directors_cut": 10.0 if ante >= 5 else 5.0,
        "v_retcon": 12.0 if ante >= 5 else 6.0,
        "v_hieroglyph": 12.0 if ante <= 4 else 3.0,
        "v_petroglyph": 8.0 if ante <= 4 else 2.0,
        "v_blank": 0.0,
    }
    value = values.get(key, 0.0)
    if _needs_late_carry_upgrade(state) and key not in {"v_antimatter", "v_paint_brush", "v_palette"}:
        return min(value, 10.0)
    if _needs_late_joker_slot_filled(state) and key in {"v_planet_merchant", "v_tarot_merchant", "v_telescope"}:
        return min(value, 8.0)
    return value


def _joker_value(state: dict[str, Any], key: str, config: ShopPolicyConfig, *, can_add: bool | None = None) -> float:
    if not _modeled_joker(key):
        return 0.0
    if key in _owned_jokers(state):
        return 0.0
    if can_add is None:
        can_add = _joker_count(state) < _joker_limit(state)
    if not can_add:
        return 0.0
    return _joker_base_value(state, key, config)

def _joker_base_value(
    state: dict[str, Any],
    key: str,
    config: ShopPolicyConfig,
    *,
    include_open_slot_bonus: bool = True,
) -> float:
    # The value is intentionally heuristic but grounded in implemented scoring
    # surfaces. BalatroBot remains the oracle; this only decides what is worth
    # trying in a clean shop.
    ante = int(state.get("ante_num") or 1)
    played_flush = _hand_played(state, FLUSH)
    played_pair = _hand_played(state, PAIR)
    played_two_pair = _hand_played(state, TWO_PAIR)
    played_three = _hand_played(state, THREE_OF_A_KIND)
    played_straight = _hand_played(state, STRAIGHT)
    xmult_need = 10.0 if ante >= 4 and not _has_strong_xmult(state) else 0.0
    values = {
        "j_joker": 16.0,
        "j_half": 16.0,
        "j_scholar": 18.0,
        "j_jolly": _type_joker_value(12.0, played_pair, per_play=2.0),
        "j_sly": _type_joker_value(10.0, played_pair, per_play=2.5),
        "j_mad": _type_joker_value(10.0, played_two_pair, per_play=2.0),
        "j_clever": _type_joker_value(10.0, played_two_pair, per_play=2.5),
        "j_zany": _type_joker_value(8.0, played_three, per_play=2.0),
        "j_wily": _type_joker_value(8.0, played_three, per_play=2.5),
        "j_crazy": _type_joker_value(10.0, played_straight, per_play=2.0),
        "j_devious": _type_joker_value(10.0, played_straight, per_play=2.5),
        "j_droll": _type_joker_value(14.0, played_flush, per_play=2.0),
        "j_crafty": _type_joker_value(14.0, played_flush, per_play=2.5),
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
        "j_rocket": 24.0 + min(ante, 6) * 2.0,
        "j_to_the_moon": 18.0 if int(state.get("money") or 0) >= 8 else 10.0,
        "j_golden": 18.0,
        "j_cloud_9": 16.0,
        "j_satellite": 14.0,
        "j_delayed_grat": 12.0,
        "j_chaos": 14.0,
        "j_drunkard": 12.0,
        "j_juggler": 14.0,
        "j_merry_andy": 10.0,
        "j_astronomer": 24.0,
        "j_certificate": 8.0,
        "j_stuntman": 36.0,
        "j_acrobat": 18.0,
        "j_mystic_summit": 16.0,
        "j_raised_fist": 24.0,
        "j_green_joker": 22.0,
        "j_ride_the_bus": 22.0,
        "j_runner": 24.0 if played_straight else 14.0,
        "j_trousers": 24.0 if _hand_played(state, TWO_PAIR) else 14.0,
        "j_constellation": 24.0 + xmult_need,
        "j_throwback": 0.0,
    }
    values.update(dict(config.joker_value_overrides))
    open_slot_bonus = _open_joker_slot_bonus(state) if include_open_slot_bonus else 0.0
    return values.get(key, config.modeled_joker_fallback_value) + open_slot_bonus


def _open_joker_slot_bonus(state: dict[str, Any]) -> float:
    if _joker_count(state) >= _joker_limit(state):
        return 0.0
    ante = int(state.get("ante_num") or 1)
    if ante >= 4:
        return 14.0
    if ante >= 3:
        return 8.0
    return 0.0


def _type_joker_value(base: float, played: int, *, per_play: float) -> float:
    if played <= 0:
        return base
    return base + 8.0 + per_play * min(played, 12)


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
        if key in _owned_jokers(state) or not _modeled_joker(key):
            continue
        cost = _buy_cost(card)
        value = _joker_base_value(state, key, config, include_open_slot_bonus=False)
        for owned_index, owned_key, owned_value, sell_value in owned:
            if money + sell_value < cost:
                continue
            improvement = value - owned_value
            net_gain = improvement - max(cost - sell_value, 0)
            if improvement <= _replacement_min_value_margin(state, config, key):
                continue
            candidate = (improvement, -owned_value, -owned_index, net_gain, owned_key, shop_index, key)
            if best is None or candidate > best:
                best = candidate
    if best is None:
        return None
    _, _, negative_owned_index, _, owned_key, _, key = best
    owned_index = -negative_owned_index
    return ShopDecision(GameAction(kind=ActionKind.SELL_JOKER, index=owned_index), f"sell {owned_key} for {key}")


def _best_sell_to_afford_joker_action(state: dict[str, Any], config: ShopPolicyConfig) -> ShopDecision | None:
    money = int(state.get("money") or 0)
    owned = _owned_joker_replacement_values(state, config)
    if not owned:
        return None
    best: tuple[float, float, int, str, str] | None = None
    for card in _area_cards(state, "shop"):
        if not _is_joker_card(card):
            continue
        key = str(card.get("key") or "")
        if key in _owned_jokers(state) or not _modeled_joker(key):
            continue
        cost = _buy_cost(card)
        if cost <= money:
            continue
        value = _joker_base_value(state, key, config, include_open_slot_bonus=False)
        for owned_index, owned_key, owned_value, sell_value in owned:
            if money + sell_value < cost:
                continue
            improvement = value - owned_value
            net_gain = improvement - (cost - money)
            if improvement <= _replacement_min_value_margin(state, config, key):
                continue
            candidate = (improvement, net_gain, -owned_index, owned_key, key)
            if best is None or candidate > best:
                best = candidate
    if best is None:
        return None
    _, _, negative_owned_index, owned_key, key = best
    owned_index = -negative_owned_index
    return ShopDecision(GameAction(kind=ActionKind.SELL_JOKER, index=owned_index), f"sell {owned_key} to afford {key}")


def _owned_joker_replacement_values(
    state: dict[str, Any],
    config: ShopPolicyConfig,
) -> list[tuple[int, str, float, int]]:
    out: list[tuple[int, str, float, int]] = []
    for index, card in enumerate(_area_cards(state, "jokers")):
        key = str(card.get("key") or "")
        if not key or not _modeled_joker(key):
            continue
        value = _joker_base_value(state, key, config, include_open_slot_bonus=False) + _owned_scaling_bonus(card)
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


def _replacement_min_value_margin(state: dict[str, Any], config: ShopPolicyConfig, target_key: str) -> float:
    if _needs_late_carry_upgrade(state) and target_key in IMPLEMENTED_JOKERS:
        return 1.0
    return config.replacement_min_value_margin


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
    return _needs_late_carry_upgrade(state) or (ante >= 3 and not _has_strong_xmult(state))


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


def _needs_late_carry_upgrade(state: dict[str, Any]) -> bool:
    return int(state.get("ante_num") or 1) >= 4 and not _has_strong_xmult(state)


def _planet_value(state: dict[str, Any], key: str, config: ShopPolicyConfig) -> float:
    hand_kind = _PLANET_TO_HAND_KIND.get(key)
    if hand_kind is None:
        return 0.0
    played = _hand_played(state, hand_kind)
    if _needs_late_carry_upgrade(state):
        return 0.0
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


def _shop_tarot_value(state: dict[str, Any], key: str, config: ShopPolicyConfig) -> float:
    if _consumable_count(state) >= _consumable_limit(state):
        return 0.0
    if _needs_late_carry_upgrade(state) and key not in {"c_judgement", "c_hermit", "c_temperance"}:
        return 0.0
    return max(_no_target_tarot_value(state, key, config), _targeted_tarot_hold_value(key))


def _pack_tarot_value(state: dict[str, Any], key: str, config: ShopPolicyConfig) -> float:
    value, _ = _pack_tarot_value_and_targets(state, key, config)
    return value


def _pack_tarot_value_and_targets(
    state: dict[str, Any],
    key: str,
    config: ShopPolicyConfig,
) -> tuple[float, tuple[int, ...]]:
    no_target_value = _no_target_tarot_value(state, key, config)
    if no_target_value > 0:
        return no_target_value, ()
    targets = _targeted_tarot_targets(state, key)
    if not targets:
        return 0.0, ()
    return _targeted_tarot_value(state, key, targets), targets


def _no_target_tarot_value(
    state: dict[str, Any],
    key: str,
    config: ShopPolicyConfig,
    *,
    held: bool = False,
) -> float:
    money = int(state.get("money") or 0)
    joker_count = _joker_count(state)
    joker_room = joker_count < _joker_limit(state)
    consumable_room = _consumable_count(state) < _consumable_limit(state)
    if key == "c_high_priestess":
        if held:
            return config.valuable_no_target_consumable_value
        return config.valuable_no_target_consumable_value if _should_buy_no_target_consumable(state, key, config) else 0.0
    if key == "c_hermit":
        return float(min(money, 20))
    if key == "c_temperance":
        sell_total = sum(int(((card.get("cost") or {}).get("sell") or 0)) for card in _area_cards(state, "jokers"))
        return float(min(sell_total, 50))
    if key == "c_emperor":
        if held:
            return 0.0
        return 10.0 if consumable_room else 0.0
    if key == "c_judgement":
        return 24.0 if joker_room else 0.0
    if key == "c_wheel_of_fortune":
        return 0.0
    return 0.0


def _targeted_tarot_hold_value(key: str) -> float:
    if key in {"c_hanged_man", "c_death"}:
        return 12.0
    if key in {"c_empress", "c_heirophant", "c_magician", "c_justice", "c_chariot"}:
        return 10.0
    if key in {"c_world", "c_sun", "c_moon", "c_star", "c_strength"}:
        return 8.0
    if key in {"c_lovers", "c_tower", "c_devil"}:
        return 6.0
    return 0.0


def _targeted_tarot_value(state: dict[str, Any], key: str, targets: tuple[int, ...]) -> float:
    if not targets:
        return 0.0
    if key == "c_hanged_man":
        return 16.0
    if key == "c_death":
        return 14.0
    if key == "c_empress":
        return 14.0
    if key == "c_heirophant":
        return 12.0
    if key in {"c_justice", "c_chariot"}:
        return 12.0
    if key == "c_magician":
        return 8.0
    if key == "c_strength":
        return 8.0
    if key in {"c_world", "c_sun", "c_moon", "c_star"}:
        return _suit_conversion_value(state, targets)
    if key in {"c_lovers", "c_tower", "c_devil"}:
        return 6.0
    return 0.0


def _targeted_tarot_targets(state: dict[str, Any], key: str) -> tuple[int, ...]:
    hand = _area_cards(state, "hand")
    if not hand:
        return ()
    ranked = sorted(range(len(hand)), key=lambda index: (_playing_card_value(hand[index]), -index))
    reverse_ranked = tuple(reversed(ranked))
    if key == "c_hanged_man":
        return tuple(ranked[:2]) if len(ranked) >= 2 else ()
    if key == "c_death":
        if len(ranked) < 2:
            return ()
        return (ranked[0], reverse_ranked[0])
    if key in {"c_heirophant", "c_empress", "c_magician"}:
        return reverse_ranked[: min(2, len(reverse_ranked))]
    if key in {"c_justice", "c_chariot", "c_lovers"}:
        return reverse_ranked[:1]
    if key in {"c_tower", "c_devil"}:
        return tuple(ranked[:1])
    if key == "c_strength":
        non_aces = [index for index in reverse_ranked if _rank_name(hand[index]) != "A"]
        return tuple(non_aces[:2])
    if key in {"c_world", "c_sun", "c_moon", "c_star"}:
        target_suit = _TAROT_TO_SUIT[key]
        off_suit = [index for index in ranked if _suit_name(hand[index]) != target_suit]
        same_suit_count = sum(1 for card in hand if _suit_name(card) == target_suit)
        if same_suit_count < 2:
            return ()
        return tuple(off_suit[: min(3, len(off_suit))])
    return ()


def _suit_conversion_value(state: dict[str, Any], targets: tuple[int, ...]) -> float:
    if not targets:
        return 0.0
    return 6.0 + 2.0 * len(targets)


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


def _owned_vouchers(state: dict[str, Any]) -> set[str]:
    return {
        str(card.get("key"))
        for card in _area_cards(state, "used_vouchers")
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


def _is_tarot_card(card: dict[str, Any]) -> bool:
    key = str(card.get("key") or "")
    return str(card.get("set") or "") == "TAROT" or key in _NO_TARGET_TAROTS or key in _TARGETED_TAROTS


def _modeled_joker(key: str) -> bool:
    return (
        key in IMPLEMENTED_JOKERS
        or key in DOLLAR_BONUS_JOKERS
        or key in MONEY_EVENT_JOKERS
        or key in RUN_EFFECT_JOKERS
        or key in _NON_SCORING_JOKER_VALUES
    )


def _can_add_joker_card(state: dict[str, Any], card: dict[str, Any]) -> bool:
    return _joker_count(state) < _joker_limit(state) or _is_negative_edition(card)


def _is_negative_edition(card: dict[str, Any]) -> bool:
    values: list[str] = []
    modifier = card.get("modifier")
    if isinstance(modifier, dict):
        values.extend(str(value) for value in modifier.values())
        values.extend(str(key) for key in modifier.keys())
    elif isinstance(modifier, list):
        values.extend(str(value) for value in modifier)
    state = card.get("state")
    if isinstance(state, dict):
        values.extend(str(value) for value in state.values())
        values.extend(str(key) for key in state.keys())
    elif isinstance(state, list):
        values.extend(str(value) for value in state)
    return any(value.lower() in {"negative", "e_negative"} for value in values)


def _booster_cards(state: dict[str, Any]) -> list[dict[str, Any]]:
    cards = _area_cards(state, "pack")
    if str(state.get("state") or "") in _PACK_STATES:
        return cards
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


def _rank_name(card: dict[str, Any]) -> str:
    return str((card.get("value") or {}).get("rank") or "")


def _suit_name(card: dict[str, Any]) -> str:
    return str((card.get("value") or {}).get("suit") or "")


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

_PACK_STATES = {
    "SMODS_BOOSTER_OPENED",
    "PLANET_PACK",
    "TAROT_PACK",
    "SPECTRAL_PACK",
    "STANDARD_PACK",
    "BUFFOON_PACK",
}
_NO_TARGET_TAROTS = {
    "c_high_priestess",
    "c_hermit",
    "c_temperance",
    "c_emperor",
    "c_judgement",
    "c_wheel_of_fortune",
}
_TARGETED_TAROTS = {
    "c_world",
    "c_sun",
    "c_moon",
    "c_star",
    "c_heirophant",
    "c_empress",
    "c_lovers",
    "c_justice",
    "c_chariot",
    "c_tower",
    "c_devil",
    "c_magician",
    "c_strength",
    "c_hanged_man",
    "c_death",
}
_TAROT_TO_SUIT = {
    "c_world": "S",
    "c_sun": "H",
    "c_moon": "C",
    "c_star": "D",
}
_NON_SCORING_JOKER_VALUES = {
    "j_rocket",
    "j_to_the_moon",
    "j_golden",
    "j_cloud_9",
    "j_satellite",
    "j_delayed_grat",
    "j_chaos",
    "j_drunkard",
    "j_juggler",
    "j_merry_andy",
    "j_astronomer",
    "j_certificate",
}
