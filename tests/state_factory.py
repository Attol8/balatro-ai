from __future__ import annotations

from copy import deepcopy
from typing import Any


def playing_card(
    key: str,
    *,
    card_id: int,
    hidden: bool = False,
    modifier: list[str] | None = None,
    debuffed: bool = False,
    permanent_bonus: int = 0,
) -> dict[str, Any]:
    suit, rank = key.split("_", 1)
    state: dict[str, bool] | list[object] = {}
    if hidden or debuffed:
        state = {"hidden": hidden, "debuff": debuffed}
    value = {
        "ability": {"x_mult": 1},
        "effect": f"+{rank} chips",
        "rank": rank,
        "suit": suit,
    }
    if permanent_bonus:
        value["perma_bonus"] = permanent_bonus
    return {
        "cost": {"buy": 1, "sell": 1},
        "id": card_id,
        "key": key,
        "label": "Base Card",
        "modifier": modifier or [],
        "set": "DEFAULT",
        "state": state,
        "value": value,
    }


def item_card(
    key: str,
    *,
    card_id: int,
    kind: str,
    buy: int = 3,
    sell: int = 1,
    effect: str = "Public effect",
    modifier: list[str] | None = None,
    ability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "cost": {"buy": buy, "sell": sell},
        "id": card_id,
        "key": key,
        "label": key,
        "modifier": modifier or [],
        "set": kind,
        "state": {},
        "value": {
            "ability": ability or {"x_mult": 1},
            "effect": effect,
            "rarity": 1,
        },
    }


def state(
    phase: str = "BLIND_SELECT",
    *,
    seed: str = "TEST-SEED",
    won: bool = False,
    money: int = 4,
) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "ante_num": 1,
        "blinds": {
            "small": {
                "effect": "",
                "name": "Small Blind",
                "score": 300,
                "status": "SELECT" if phase == "BLIND_SELECT" else "CURRENT",
                "tag_effect": "Gain money",
                "tag_name": "Investment Tag",
                "type": "SMALL",
            },
            "big": {
                "effect": "",
                "name": "Big Blind",
                "score": 450,
                "status": "UPCOMING",
                "tag_effect": "",
                "tag_name": "",
                "type": "BIG",
            },
            "boss": {
                "effect": "Debuffs hearts",
                "name": "The Head",
                "score": 600,
                "status": "UPCOMING",
                "tag_effect": "",
                "tag_name": "",
                "type": "BOSS",
            },
        },
        "cards": {
            "cards": [
                playing_card("S_A", card_id=1, hidden=True),
                playing_card("H_K", card_id=2, hidden=True),
                playing_card("D_2", card_id=3, hidden=True),
            ],
            "count": 3,
            "highlighted_limit": 5,
            "limit": 52,
        },
        "consumables": {"cards": [], "count": 0, "highlighted_limit": 1, "limit": 2},
        "deck": "RED",
        "discard": {"cards": [], "count": 0, "highlighted_limit": 5, "limit": 500},
        "hand": {"cards": [], "count": 0, "highlighted_limit": 5, "limit": 8},
        "hands": {
            "High Card": {
                "chips": 5,
                "example": [["S_A", True]],
                "level": 1,
                "mult": 1,
                "order": 12,
                "played": 0,
                "played_this_round": 0,
            }
        },
        "jokers": {"cards": [], "count": 0, "highlighted_limit": 1, "limit": 5},
        "money": money,
        "last_tarot_planet": "",
        "pack_choices_remaining": 0,
        "round": {
            "ancient_suit": "H",
            "chips": 0,
            "discards_left": 4,
            "discards_used": 0,
            "hands_left": 4,
            "hands_played": 0,
            "most_played_poker_hand": "High Card",
            "reroll_cost": 5,
        },
        "round_num": 0,
        "seed": seed,
        "stake": "WHITE",
        "state": phase,
        "used_vouchers": [],
        "poker_hand_iteration_order": ["High Card"],
        "won": won,
    }
    if phase == "SELECTING_HAND":
        hand_cards = [
            playing_card("S_Q", card_id=4),
            playing_card("H_J", card_id=5),
            playing_card("C_T", card_id=6),
        ]
        raw["hand"] = {"cards": hand_cards, "count": 3, "highlighted_limit": 5, "limit": 8}
        raw["cards"]["cards"] = raw["cards"]["cards"][:2]
        raw["cards"]["count"] = 2
        raw["round_num"] = 1
    elif phase == "ROUND_EVAL":
        raw["round_num"] = 1
        raw["round"]["chips"] = 300
    elif phase == "SHOP":
        raw["round_num"] = 1
        raw["shop"] = {
            "cards": [item_card("j_joker", card_id=20, kind="JOKER", buy=2)],
            "count": 1,
            "highlighted_limit": 1,
            "limit": 2,
        }
        raw["vouchers"] = {
            "cards": [item_card("v_grabber", card_id=21, kind="VOUCHER", buy=10)],
            "count": 1,
            "highlighted_limit": 1,
            "limit": 1,
        }
        raw["packs"] = {
            "cards": [item_card("p_buffoon_normal_1", card_id=22, kind="BOOSTER", buy=4)],
            "count": 1,
            "highlighted_limit": 1,
            "limit": 2,
        }
    elif phase in {"BUFFOON_PACK", "TAROT_PACK", "PLANET_PACK", "SPECTRAL_PACK", "STANDARD_PACK"}:
        raw["round_num"] = 1
        raw["pack_choices_remaining"] = 1
        raw["pack"] = {
            "cards": [item_card("j_joker", card_id=30, kind="JOKER")],
            "count": 1,
            "highlighted_limit": 1,
            "limit": 2,
        }
    elif phase == "GAME_OVER":
        raw["ante_num"] = 8 if won else 2
        raw["round_num"] = 24 if won else 4
    return deepcopy(raw)
