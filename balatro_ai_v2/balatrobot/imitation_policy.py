from __future__ import annotations

from typing import Any, Sequence

from balatro_ai_v2.actions import ActionKind, GameAction
from balatro_ai_v2.balatrobot.adapter import hand_to_fast_ids
from balatro_ai_v2.fast.env import ACTION_SPACE_SIZE, DISCARD_ACTION_OFFSET, MAX_SELECTED_CARDS
from balatro_ai_v2.fast.full_game import (
    BUY_CARD_ACTION_BASE,
    BUY_PACK_ACTION_BASE,
    BUY_VOUCHER_ACTION,
    CASH_OUT_ACTION,
    MAX_CONSUMABLE_OBS,
    MAX_HAND_OBS,
    MAX_JOKER_OBS,
    MAX_PACK_OBS,
    MAX_SHOP_OBS,
    NEXT_ROUND_ACTION,
    PACK_SELECT_ACTION_BASE,
    PACK_SKIP_ACTION,
    REROLL_ACTION,
    SELECT_BLIND_ACTION,
    SELL_JOKER_ACTION_BASE,
    SKIP_BLIND_ACTION,
    USE_CONSUMABLE_ACTION_BASE,
    _ITEM_OBS_IDS,
    _JOKER_OBS_IDS,
)
from balatro_ai_v2.fast.hand import HAND_KIND_NAMES
from balatro_ai_v2.fast.run import BlindKind, RunPhase
from balatro_ai_v2.learning.imitation import ActionPolicy


def trained_tactical_action(state: dict[str, Any], policy: ActionPolicy) -> GameAction:
    observation = balatrobot_state_to_fast_observation(state)
    legal_actions = fast_legal_tactical_actions(state)
    return GameAction.from_fast_action_id(policy.predict(observation, legal_actions))


def trained_full_action(state: dict[str, Any], policy: ActionPolicy) -> GameAction:
    observation = balatrobot_state_to_full_fast_observation(state)
    legal_actions = fast_legal_full_actions(state)
    action = policy.predict(observation, legal_actions)
    return full_fast_action_to_game_action(action)


def balatrobot_state_to_full_fast_observation(state: dict[str, Any]) -> tuple[int, ...]:
    hand = hand_to_fast_ids(state) if state.get("state") == "SELECTING_HAND" else ()
    padded_hand = tuple((hand + (-1,) * MAX_HAND_OBS)[:MAX_HAND_OBS])
    round_state = state.get("round") or {}
    hands = state.get("hands") or {}
    current_score = int(round_state.get("chips") or 0)
    required_score = _active_required_score(state)
    deck_limit = int(((state.get("cards") or {}).get("limit") or 52))
    deck_count = int(((state.get("cards") or {}).get("count") or 0))
    joker_ids = tuple(_JOKER_OBS_IDS.get(key, 0) for key in _area_card_keys(state, "jokers"))
    consumable_ids = tuple(_ITEM_OBS_IDS.get(key, 0) for key in _area_card_keys(state, "consumables"))
    shop_ids = tuple(_ITEM_OBS_IDS.get(key, 0) for key in _area_card_keys(state, "shop"))
    voucher_keys = _area_card_keys(state, "vouchers")
    pack_area = "packs" if state.get("state") == "SHOP" else "pack"
    pack_ids = tuple(_ITEM_OBS_IDS.get(key, 0) for key in _area_card_keys(state, pack_area))
    return (
        int(_run_phase(state)),
        int(state.get("ante_num") or 1),
        int(_visible_blind_kind(state)),
        max(int(state.get("round_num") or 0) - 1, 0),
        int(state.get("money") or 0),
        current_score,
        required_score,
        int(round_state.get("hands_left") or 0),
        int(round_state.get("discards_left") or 0),
        max(deck_limit - deck_count, 0),
        *(
            int((hands.get(hand_name) or {}).get("level") or 1)
            for hand_name in HAND_KIND_NAMES
        ),
        *(
            int((hands.get(hand_name) or {}).get("played") or 0)
            for hand_name in HAND_KIND_NAMES
        ),
        *((joker_ids + (0,) * MAX_JOKER_OBS)[:MAX_JOKER_OBS]),
        *((consumable_ids + (0,) * MAX_CONSUMABLE_OBS)[:MAX_CONSUMABLE_OBS]),
        *((shop_ids + (0,) * MAX_SHOP_OBS)[:MAX_SHOP_OBS]),
        _ITEM_OBS_IDS.get(voucher_keys[0], 0) if voucher_keys else 0,
        *((pack_ids + (0,) * MAX_PACK_OBS)[:MAX_PACK_OBS]),
        *padded_hand,
    )


def fast_legal_full_actions(state: dict[str, Any]) -> tuple[int, ...]:
    state_name = str(state.get("state") or "")
    if state_name == "BLIND_SELECT":
        actions = [SELECT_BLIND_ACTION]
        if _selected_blind_kind(state) != BlindKind.BOSS:
            actions.append(SKIP_BLIND_ACTION)
        return tuple(actions)
    if state_name == "SELECTING_HAND":
        return fast_legal_tactical_actions(state)
    if state_name == "ROUND_EVAL":
        return (CASH_OUT_ACTION,)
    if state_name == "SHOP":
        actions: list[int] = []
        money = int(state.get("money") or 0)
        for index, card in enumerate(_area_cards(state, "consumables")[:8]):
            if str(card.get("key") or "").startswith("c_"):
                actions.append(USE_CONSUMABLE_ACTION_BASE + index)
        for index, card in enumerate(_area_cards(state, "shop")[:8]):
            if _buy_cost(card) <= money:
                actions.append(BUY_CARD_ACTION_BASE + index)
        vouchers = _area_cards(state, "vouchers")
        if vouchers and _buy_cost(vouchers[0]) <= money:
            actions.append(BUY_VOUCHER_ACTION)
        for index, card in enumerate(_area_cards(state, "packs")[:8]):
            if _buy_cost(card) <= money:
                actions.append(BUY_PACK_ACTION_BASE + index)
        for index, _card in enumerate(_area_cards(state, "jokers")[:8]):
            actions.append(SELL_JOKER_ACTION_BASE + index)
        if int((state.get("round") or {}).get("reroll_cost") or 0) <= money:
            actions.append(REROLL_ACTION)
        actions.append(NEXT_ROUND_ACTION)
        return tuple(actions)
    if state_name in _PACK_STATES:
        pack_cards = _area_cards(state, "pack")
        return tuple(PACK_SELECT_ACTION_BASE + index for index in range(min(len(pack_cards), 8))) + (PACK_SKIP_ACTION,)
    return ()


def full_fast_action_to_game_action(action: int) -> GameAction:
    if action < SELECT_BLIND_ACTION:
        return GameAction.from_fast_action_id(action)
    if action == SELECT_BLIND_ACTION:
        return GameAction(kind=ActionKind.SELECT_BLIND)
    if action == SKIP_BLIND_ACTION:
        return GameAction(kind=ActionKind.SKIP_BLIND)
    if action == CASH_OUT_ACTION:
        return GameAction(kind=ActionKind.CASH_OUT)
    if action == NEXT_ROUND_ACTION:
        return GameAction(kind=ActionKind.NEXT_ROUND)
    if action == REROLL_ACTION:
        return GameAction(kind=ActionKind.REROLL)
    if action == BUY_VOUCHER_ACTION:
        return GameAction(kind=ActionKind.BUY_VOUCHER, index=0)
    if BUY_CARD_ACTION_BASE <= action < BUY_CARD_ACTION_BASE + 8:
        return GameAction(kind=ActionKind.BUY_CARD, index=action - BUY_CARD_ACTION_BASE)
    if BUY_PACK_ACTION_BASE <= action < BUY_PACK_ACTION_BASE + 8:
        return GameAction(kind=ActionKind.BUY_PACK, index=action - BUY_PACK_ACTION_BASE)
    if SELL_JOKER_ACTION_BASE <= action < SELL_JOKER_ACTION_BASE + 8:
        return GameAction(kind=ActionKind.SELL_JOKER, index=action - SELL_JOKER_ACTION_BASE)
    if USE_CONSUMABLE_ACTION_BASE <= action < USE_CONSUMABLE_ACTION_BASE + 8:
        return GameAction(kind=ActionKind.USE_CONSUMABLE, index=action - USE_CONSUMABLE_ACTION_BASE)
    if PACK_SELECT_ACTION_BASE <= action < PACK_SELECT_ACTION_BASE + 8:
        return GameAction(kind=ActionKind.PACK_SELECT, index=action - PACK_SELECT_ACTION_BASE)
    if action == PACK_SKIP_ACTION:
        return GameAction(kind=ActionKind.PACK_SKIP)
    raise ValueError(f"unsupported full fast action id: {action}")


def game_action_to_full_fast_action(action: GameAction | None) -> int:
    if action is None:
        return NEXT_ROUND_ACTION
    if action.kind in {ActionKind.PLAY, ActionKind.DISCARD}:
        return action.to_fast_action_id()
    if action.kind == ActionKind.SELECT_BLIND:
        return SELECT_BLIND_ACTION
    if action.kind == ActionKind.SKIP_BLIND:
        return SKIP_BLIND_ACTION
    if action.kind == ActionKind.CASH_OUT:
        return CASH_OUT_ACTION
    if action.kind == ActionKind.NEXT_ROUND:
        return NEXT_ROUND_ACTION
    if action.kind == ActionKind.REROLL:
        return REROLL_ACTION
    if action.kind == ActionKind.BUY_VOUCHER:
        return BUY_VOUCHER_ACTION
    if action.kind == ActionKind.BUY_CARD:
        return BUY_CARD_ACTION_BASE + _required_action_index(action)
    if action.kind == ActionKind.BUY_PACK:
        return BUY_PACK_ACTION_BASE + _required_action_index(action)
    if action.kind == ActionKind.SELL_JOKER:
        return SELL_JOKER_ACTION_BASE + _required_action_index(action)
    if action.kind == ActionKind.USE_CONSUMABLE:
        return USE_CONSUMABLE_ACTION_BASE + _required_action_index(action)
    if action.kind == ActionKind.PACK_SELECT:
        return PACK_SELECT_ACTION_BASE + _required_action_index(action)
    if action.kind == ActionKind.PACK_SKIP:
        return PACK_SKIP_ACTION
    raise ValueError(f"unsupported game action kind: {action.kind}")


def balatrobot_state_to_fast_observation(state: dict[str, Any]) -> tuple[int, ...]:
    hand = hand_to_fast_ids(state)
    hand_limit = int(((state.get("hand") or {}).get("limit") or 8))
    joker_limit = int(((state.get("jokers") or {}).get("limit") or 5))
    padded_hand = tuple(hand + (-1,) * max(hand_limit - len(hand), 0))
    joker_ids = tuple(_JOKER_OBS_IDS.get(card_key, 0) for card_key in _joker_keys(state))
    padded_jokers = joker_ids + (0,) * max(joker_limit - len(joker_ids), 0)
    round_state = state.get("round") or {}
    hands = state.get("hands") or {}
    current_score = int(round_state.get("chips") or 0)
    required_score = _active_required_score(state)
    deck_limit = int(((state.get("cards") or {}).get("limit") or 52))
    deck_count = int(((state.get("cards") or {}).get("count") or 0))
    round_num = int(state.get("round_num") or 1)
    return (
        int(RunPhase.SELECTING_HAND),
        int(state.get("ante_num") or 1),
        int(_active_blind_kind(state)),
        max(round_num - 1, 0),
        int(state.get("money") or 0),
        current_score,
        required_score,
        int(round_state.get("hands_left") or 0),
        int(round_state.get("discards_left") or 0),
        max(deck_limit - deck_count, 0),
        *(
            int((hands.get(hand_name) or {}).get("level") or 1)
            for hand_name in HAND_KIND_NAMES
        ),
        *(
            int((hands.get(hand_name) or {}).get("played") or 0)
            for hand_name in HAND_KIND_NAMES
        ),
        *padded_jokers[:joker_limit],
        *padded_hand[:hand_limit],
    )


def fast_legal_tactical_actions(state: dict[str, Any]) -> tuple[int, ...]:
    hand_len = len(hand_to_fast_ids(state))
    highlighted_limit = min(_highlighted_limit(state), MAX_SELECTED_CARDS, hand_len)
    can_discard = int(((state.get("round") or {}).get("discards_left") or 0)) > 0
    masks = tuple(
        mask
        for mask in range(1, 1 << hand_len)
        if mask.bit_count() <= highlighted_limit
    )
    if not can_discard:
        return masks
    actions: list[int] = []
    for mask in masks:
        actions.append(mask)
        discard_action = DISCARD_ACTION_OFFSET + mask
        if discard_action < ACTION_SPACE_SIZE:
            actions.append(discard_action)
    return tuple(actions)


def _active_required_score(state: dict[str, Any]) -> int:
    blinds = state.get("blinds") or {}
    for blind in blinds.values():
        if isinstance(blind, dict) and blind.get("status") == "CURRENT":
            return int(blind.get("score") or 1)
    return 1


def _active_blind_kind(state: dict[str, Any]) -> BlindKind:
    blinds = state.get("blinds") or {}
    for name, blind in blinds.items():
        if not isinstance(blind, dict) or blind.get("status") != "CURRENT":
            continue
        blind_type = str(blind.get("type") or name).upper()
        if "BOSS" in blind_type:
            return BlindKind.BOSS
        if "BIG" in blind_type:
            return BlindKind.BIG
        return BlindKind.SMALL
    return BlindKind.SMALL


def _visible_blind_kind(state: dict[str, Any]) -> BlindKind:
    return _active_blind_kind(state) if state.get("state") != "BLIND_SELECT" else _selected_blind_kind(state)


def _selected_blind_kind(state: dict[str, Any]) -> BlindKind:
    blinds = state.get("blinds") or {}
    for name, blind in blinds.items():
        if not isinstance(blind, dict) or blind.get("status") != "SELECT":
            continue
        blind_type = str(blind.get("type") or name).upper()
        if "BOSS" in blind_type:
            return BlindKind.BOSS
        if "BIG" in blind_type:
            return BlindKind.BIG
        return BlindKind.SMALL
    return BlindKind.SMALL


def _run_phase(state: dict[str, Any]) -> RunPhase:
    state_name = str(state.get("state") or "")
    if state_name == "BLIND_SELECT":
        return RunPhase.BLIND_SELECT
    if state_name == "SELECTING_HAND":
        return RunPhase.SELECTING_HAND
    if state_name == "ROUND_EVAL":
        return RunPhase.ROUND_EVAL
    if state_name == "SHOP":
        return RunPhase.SHOP
    if state_name in _PACK_STATES:
        return RunPhase.PACK
    return RunPhase.GAME_OVER


def _highlighted_limit(state: dict[str, Any]) -> int:
    return int(((state.get("hand") or {}).get("highlighted_limit") or MAX_SELECTED_CARDS))


def _joker_keys(state: dict[str, Any]) -> tuple[str, ...]:
    return _area_card_keys(state, "jokers")


def _area_cards(state: dict[str, Any], area: str) -> list[dict[str, Any]]:
    return [
        card
        for card in ((state.get(area) or {}).get("cards") or [])
        if isinstance(card, dict)
    ]


def _area_card_keys(state: dict[str, Any], area: str) -> tuple[str, ...]:
    return tuple(str(card.get("key") or "") for card in _area_cards(state, area))


def _buy_cost(card: dict[str, Any]) -> int:
    return int(((card.get("cost") or {}).get("buy") or 0))


def _required_action_index(action: GameAction) -> int:
    if action.index is None:
        raise ValueError(f"{action.kind.value} action requires index")
    return action.index


_PACK_STATES = {
    "SMODS_BOOSTER_OPENED",
    "PLANET_PACK",
    "TAROT_PACK",
    "SPECTRAL_PACK",
    "STANDARD_PACK",
    "BUFFOON_PACK",
}
