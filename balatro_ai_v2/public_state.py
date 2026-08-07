"""The complete policy-visible state contract.

These frozen value objects are the firewall.  Raw BalatroBot dictionaries must
never cross into a policy or online-search process.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import TypeAlias


class Phase(str, Enum):
    BLIND_SELECT = "BLIND_SELECT"
    SELECTING_HAND = "SELECTING_HAND"
    ROUND_EVAL = "ROUND_EVAL"
    SHOP = "SHOP"
    PACK = "PACK"
    GAME_OVER = "GAME_OVER"


@dataclass(frozen=True, slots=True)
class VisiblePlayingCard:
    rank: str
    suit: str
    enhancement: str | None = None
    edition: str | None = None
    seal: str | None = None
    debuffed: bool = False
    effect_text: str = ""


@dataclass(frozen=True, slots=True)
class HiddenHandCard:
    """An anonymous selectable slot; intentionally contains no identity."""


HandCard: TypeAlias = VisiblePlayingCard | HiddenHandCard


@dataclass(frozen=True, slots=True)
class DeckCardCount:
    card: VisiblePlayingCard
    count: int


@dataclass(frozen=True, slots=True)
class PublicItem:
    key: str
    label: str
    kind: str
    effect_text: str = ""
    edition: str | None = None
    eternal: bool = False
    perishable_rounds: int | None = None
    rental: bool = False
    buy_cost: int | None = None
    sell_cost: int | None = None


PublicOffer: TypeAlias = PublicItem | VisiblePlayingCard


@dataclass(frozen=True, slots=True)
class PublicBlind:
    kind: str
    status: str
    name: str
    effect: str
    score: int
    tag_name: str = ""
    tag_effect: str = ""


@dataclass(frozen=True, slots=True)
class HandStat:
    name: str
    level: int
    chips: int
    mult: int
    played: int
    played_this_round: int


@dataclass(frozen=True, slots=True)
class RoundObservation:
    chips: int
    hands_left: int
    discards_left: int
    hands_played: int
    discards_used: int
    reroll_cost: int


@dataclass(frozen=True, slots=True)
class PublicObservation:
    phase: Phase
    deck: str
    stake: str
    ante: int
    round_no: int
    money: int
    round: RoundObservation
    blinds: tuple[PublicBlind, ...]
    hand: tuple[HandCard, ...]
    hand_limit: int
    selection_limit: int
    remaining_deck: tuple[DeckCardCount, ...]
    draw_count: int
    deck_size: int
    hand_stats: tuple[HandStat, ...]
    jokers: tuple[PublicItem, ...]
    joker_limit: int
    consumables: tuple[PublicItem, ...]
    consumable_limit: int
    shop: tuple[PublicItem, ...]
    vouchers: tuple[PublicItem, ...]
    packs: tuple[PublicItem, ...]
    opened_pack: tuple[PublicOffer, ...]
    used_vouchers: tuple[str, ...]
    won: bool

    def canonical_json(self) -> str:
        return json.dumps(_json_value(self), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple | list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    return value
