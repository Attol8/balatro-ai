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


OBSCURED_CARD_ATTRIBUTE = "?"

_PUBLIC_ITEM_KINDS = frozenset(
    {"JOKER", "TAROT", "PLANET", "SPECTRAL", "VOUCHER", "BOOSTER"}
)
_JOKER_KINDS = frozenset({"JOKER"})
_CONSUMABLE_KINDS = frozenset({"TAROT", "PLANET", "SPECTRAL"})
_VOUCHER_KINDS = frozenset({"VOUCHER"})
_BOOSTER_KINDS = frozenset({"BOOSTER"})
_SHOP_ITEM_KINDS = frozenset({"JOKER", "TAROT", "PLANET", "SPECTRAL"})
_OPENED_PACK_ITEM_KINDS = _SHOP_ITEM_KINDS


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
    permanent_bonus: int = 0
    effect_text: str = ""

    def __post_init__(self) -> None:
        obscured = (
            self.rank == OBSCURED_CARD_ATTRIBUTE
            or self.suit == OBSCURED_CARD_ATTRIBUTE
        )
        if self.enhancement == "STONE":
            if (
                self.rank != OBSCURED_CARD_ATTRIBUTE
                or self.suit != OBSCURED_CARD_ATTRIBUTE
            ):
                raise ValueError("Stone cards must obscure their base rank and suit")
        elif obscured:
            raise ValueError("only Stone cards may obscure rank and suit")


@dataclass(frozen=True, slots=True)
class HiddenHandCard:
    """An anonymous selectable slot; intentionally contains no identity."""

    pass


HandCard: TypeAlias = VisiblePlayingCard | HiddenHandCard


@dataclass(frozen=True, slots=True)
class HiddenJokerSlot:
    """An anonymous occupied Joker position while its card is face down."""

    pass


@dataclass(frozen=True, slots=True)
class DeckCardCount:
    card: VisiblePlayingCard
    count: int


@dataclass(frozen=True, slots=True)
class PublicJokerRuntime:
    """Fixed, tooltip-visible mutable values for an admitted Joker mechanic."""

    current_mult: int | None = None
    current_chips: int | None = None
    current_x_mult: float | None = None
    current_dollars: int | None = None
    remaining_hands: int | None = None
    loyalty_remaining: int | None = None
    driver_tally: int | None = None
    target_hand: str | None = None


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
    debuffed: bool = False
    buy_cost: int | None = None
    sell_cost: int | None = None
    runtime: PublicJokerRuntime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str):
            raise ValueError("public item kind must be a string")
        if self.kind != self.kind.upper():
            raise ValueError("public item kind must use canonical uppercase")
        if self.kind in {"DEFAULT", "ENHANCED"}:
            raise ValueError(
                "playing cards cannot use the generic public item representation"
            )
        if self.kind not in _PUBLIC_ITEM_KINDS:
            raise ValueError(f"unsupported public item kind {self.kind!r}")
        if self.runtime is not None and self.kind != "JOKER":
            raise ValueError("only Jokers may carry Joker runtime")


PublicOffer: TypeAlias = PublicItem | VisiblePlayingCard
JokerCard: TypeAlias = PublicItem | HiddenJokerSlot


@dataclass(frozen=True, slots=True)
class PublicShopPlayingCard:
    """A fully visible playing card offered for sale in a Magic Trick shop."""

    card: VisiblePlayingCard
    buy_cost: int

    def __post_init__(self) -> None:
        if not isinstance(self.card, VisiblePlayingCard):
            raise ValueError("shop playing-card offer must contain a visible card")
        if (
            isinstance(self.buy_cost, bool)
            or not isinstance(self.buy_cost, int)
            or self.buy_cost < 0
        ):
            raise ValueError("shop playing-card buy cost must be non-negative")


PublicShopOffer: TypeAlias = PublicItem | PublicShopPlayingCard


@dataclass(frozen=True, slots=True)
class PublicBlind:
    kind: str
    status: str
    name: str
    effect: str
    score: int
    disabled: bool
    tag_name: str = ""
    tag_effect: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.disabled, bool):
            raise ValueError("blind disabled state must be boolean")
        if self.disabled and (self.kind != "BOSS" or self.status != "CURRENT"):
            raise ValueError("only the current boss blind may be disabled")


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
    boss_rerolled: bool
    ancient_suit: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.boss_rerolled, bool):
            raise ValueError("boss_rerolled must be boolean")


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
    required_hand_slots: tuple[int, ...]
    remaining_deck: tuple[DeckCardCount, ...]
    draw_count: int
    deck_size: int
    hand_stats: tuple[HandStat, ...]
    jokers: tuple[JokerCard, ...]
    joker_limit: int
    consumables: tuple[PublicItem, ...]
    consumable_limit: int
    shop: tuple[PublicShopOffer, ...]
    vouchers: tuple[PublicItem, ...]
    packs: tuple[PublicItem, ...]
    opened_pack: tuple[PublicOffer, ...]
    pack_kind: str | None
    pack_choices_remaining: int
    used_vouchers: tuple[str, ...]
    last_tarot_planet: str | None
    antes_cleared: int
    won: bool

    def __post_init__(self) -> None:
        visible_jokers = tuple(
            joker for joker in self.jokers if isinstance(joker, PublicItem)
        )
        if any(
            not isinstance(joker, (PublicItem, HiddenJokerSlot))
            for joker in self.jokers
        ):
            raise ValueError("jokers must contain visible items or anonymous slots")
        _validate_item_zone("jokers", visible_jokers, _JOKER_KINDS)
        hidden_jokers = sum(
            isinstance(joker, HiddenJokerSlot) for joker in self.jokers
        )
        if hidden_jokers:
            amber_active = (
                self.phase == Phase.SELECTING_HAND
                and any(
                    blind.kind == "BOSS"
                    and blind.status == "CURRENT"
                    and blind.name == "Amber Acorn"
                    and not blind.disabled
                    for blind in self.blinds
                )
            )
            if not amber_active or hidden_jokers != len(self.jokers):
                raise ValueError(
                    "anonymous Joker slots require every Joker to be hidden "
                    "by active Amber Acorn"
                )
        _validate_item_zone("consumables", self.consumables, _CONSUMABLE_KINDS)
        _validate_item_zone("vouchers", self.vouchers, _VOUCHER_KINDS)
        _validate_item_zone("packs", self.packs, _BOOSTER_KINDS)
        if any(
            not isinstance(offer, (PublicItem, PublicShopPlayingCard))
            for offer in self.shop
        ):
            raise ValueError("shop offers must use a recognized public representation")
        _validate_item_zone(
            "shop",
            tuple(offer for offer in self.shop if isinstance(offer, PublicItem)),
            _SHOP_ITEM_KINDS,
        )
        if any(
            not isinstance(offer, (PublicItem, VisiblePlayingCard))
            for offer in self.opened_pack
        ):
            raise ValueError(
                "opened-pack offers must use a recognized public representation"
            )
        _validate_item_zone(
            "opened_pack",
            tuple(
                offer for offer in self.opened_pack if isinstance(offer, PublicItem)
            ),
            _OPENED_PACK_ITEM_KINDS,
        )
        if tuple(sorted(set(self.required_hand_slots))) != self.required_hand_slots:
            raise ValueError("required hand slots must be unique and increasing")
        if any(slot < 0 or slot >= len(self.hand) for slot in self.required_hand_slots):
            raise ValueError("required hand slot is outside the visible hand")
        if self.required_hand_slots and self.phase != Phase.SELECTING_HAND:
            raise ValueError("required hand slots are valid only while selecting a hand")
        if self.phase == Phase.SELECTING_HAND:
            cerulean_enabled = any(
                blind.kind == "BOSS"
                and blind.status == "CURRENT"
                and blind.name == "Cerulean Bell"
                and not blind.disabled
                for blind in self.blinds
            )
            if cerulean_enabled and len(self.required_hand_slots) != 1:
                raise ValueError(
                    "enabled current Cerulean Bell requires one forced hand slot"
                )
            if not cerulean_enabled and self.required_hand_slots:
                raise ValueError(
                    "forced hand slots require an enabled current Cerulean Bell"
                )
        pack_kinds = {"ARCANA", "CELESTIAL", "SPECTRAL", "STANDARD", "BUFFOON", "SMODS"}
        if self.phase == Phase.PACK:
            if self.pack_kind not in pack_kinds or self.pack_choices_remaining <= 0:
                raise ValueError("pack observations require a kind and remaining choice")
        elif self.pack_kind is not None or self.pack_choices_remaining != 0:
            raise ValueError("pack metadata is valid only while a pack is open")
        if self.antes_cleared < 0:
            raise ValueError("antes cleared must be non-negative")
        if self.won and self.antes_cleared < 8:
            raise ValueError("a won run must have cleared at least eight antes")

    @property
    def terminal(self) -> bool:
        """A run ends only on game over; wins continue into Endless."""

        return self.phase == Phase.GAME_OVER

    def canonical_json(self) -> str:
        return json.dumps(_json_value(self), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def _validate_item_zone(
    zone: str,
    items: tuple[PublicItem, ...],
    admitted_kinds: frozenset[str],
) -> None:
    if any(not isinstance(item, PublicItem) for item in items):
        raise ValueError(f"{zone} must contain public items")
    invalid = sorted({item.kind for item in items if item.kind not in admitted_kinds})
    if invalid:
        raise ValueError(f"{zone} contains unsupported public item kinds: {invalid}")


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
