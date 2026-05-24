from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StakeRule:
    key: str
    name: str
    order: int
    level: int
    no_small_blind_reward: bool = False
    scaling: int = 1
    enable_eternals_in_shop: bool = False
    discard_delta: int = 0
    enable_perishables_in_shop: bool = False
    enable_rentals_in_shop: bool = False


STAKE_RULES: dict[str, StakeRule] = {
    "stake_white": StakeRule("stake_white", "White Chip", 1, 1),
    "stake_red": StakeRule("stake_red", "Red Chip", 2, 2, no_small_blind_reward=True),
    "stake_green": StakeRule("stake_green", "Green Chip", 3, 3, no_small_blind_reward=True, scaling=2),
    "stake_black": StakeRule(
        "stake_black", "Black Chip", 4, 4, no_small_blind_reward=True, scaling=2, enable_eternals_in_shop=True
    ),
    "stake_blue": StakeRule(
        "stake_blue",
        "Blue Chip",
        5,
        5,
        no_small_blind_reward=True,
        scaling=2,
        enable_eternals_in_shop=True,
        discard_delta=-1,
    ),
    "stake_purple": StakeRule(
        "stake_purple",
        "Purple Chip",
        6,
        6,
        no_small_blind_reward=True,
        scaling=3,
        enable_eternals_in_shop=True,
        discard_delta=-1,
    ),
    "stake_orange": StakeRule(
        "stake_orange",
        "Orange Chip",
        7,
        7,
        no_small_blind_reward=True,
        scaling=3,
        enable_eternals_in_shop=True,
        discard_delta=-1,
        enable_perishables_in_shop=True,
    ),
    "stake_gold": StakeRule(
        "stake_gold",
        "Gold Chip",
        8,
        8,
        no_small_blind_reward=True,
        scaling=3,
        enable_eternals_in_shop=True,
        discard_delta=-1,
        enable_perishables_in_shop=True,
        enable_rentals_in_shop=True,
    ),
}

IMPLEMENTED_STAKES = frozenset(STAKE_RULES)


def stake_rule(key: str) -> StakeRule:
    try:
        return STAKE_RULES[key]
    except KeyError as exc:
        raise NotImplementedError(f"stake is not implemented: {key}") from exc
