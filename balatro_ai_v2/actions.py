"""Typed actions that can be performed through BalatroBot's public API.

The policy never emits simulator action IDs.  Area-specific slot wrappers make
it impossible to accidentally use, for example, a shop index as a hand index.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import combinations
from typing import Iterator, Mapping, TypeAlias

from balatro_ai_v2.consumable_rules import (
    iter_public_targets,
    public_consumable_is_usable,
)
from balatro_ai_v2.public_state import (
    HiddenJokerSlot,
    Phase,
    PublicItem,
    PublicObservation,
    PublicShopPlayingCard,
    VisiblePlayingCard,
)


@dataclass(frozen=True, slots=True, order=True)
class HandSlot:
    value: int

    def __post_init__(self) -> None:
        _validate_slot(self.value)


@dataclass(frozen=True, slots=True, order=True)
class ShopSlot:
    value: int

    def __post_init__(self) -> None:
        _validate_slot(self.value)


@dataclass(frozen=True, slots=True, order=True)
class VoucherSlot:
    value: int

    def __post_init__(self) -> None:
        _validate_slot(self.value)


@dataclass(frozen=True, slots=True, order=True)
class PackOfferSlot:
    value: int

    def __post_init__(self) -> None:
        _validate_slot(self.value)


@dataclass(frozen=True, slots=True, order=True)
class OpenedPackSlot:
    value: int

    def __post_init__(self) -> None:
        _validate_slot(self.value)


@dataclass(frozen=True, slots=True, order=True)
class JokerSlot:
    value: int

    def __post_init__(self) -> None:
        _validate_slot(self.value)


@dataclass(frozen=True, slots=True, order=True)
class ConsumableSlot:
    value: int

    def __post_init__(self) -> None:
        _validate_slot(self.value)


class BuyMode(str, Enum):
    STORE = "store"
    USE = "use"


@dataclass(frozen=True, slots=True)
class SelectBlind:
    pass


@dataclass(frozen=True, slots=True)
class SkipBlind:
    pass


@dataclass(frozen=True, slots=True)
class CashOut:
    pass


@dataclass(frozen=True, slots=True)
class LeaveShop:
    pass


@dataclass(frozen=True, slots=True)
class RerollShop:
    pass


@dataclass(frozen=True, slots=True)
class RerollBoss:
    pass


@dataclass(frozen=True, slots=True)
class PlayCards:
    cards: tuple[HandSlot, ...]

    def __post_init__(self) -> None:
        _validate_typed_selection(self.cards, HandSlot, minimum=1, maximum=5)


@dataclass(frozen=True, slots=True)
class DiscardCards:
    cards: tuple[HandSlot, ...]

    def __post_init__(self) -> None:
        _validate_typed_selection(self.cards, HandSlot, minimum=1, maximum=5)


@dataclass(frozen=True, slots=True)
class BuyShopCard:
    card: ShopSlot
    mode: BuyMode = BuyMode.STORE


@dataclass(frozen=True, slots=True)
class BuyVoucher:
    voucher: VoucherSlot


@dataclass(frozen=True, slots=True)
class BuyPack:
    pack: PackOfferSlot


@dataclass(frozen=True, slots=True)
class SellJoker:
    joker: JokerSlot


@dataclass(frozen=True, slots=True)
class SellConsumable:
    consumable: ConsumableSlot


@dataclass(frozen=True, slots=True)
class UseConsumable:
    consumable: ConsumableSlot
    targets: tuple[HandSlot, ...] = ()

    def __post_init__(self) -> None:
        _validate_typed_selection(self.targets, HandSlot, minimum=0, maximum=5)


@dataclass(frozen=True, slots=True)
class ChoosePackCard:
    card: OpenedPackSlot
    targets: tuple[HandSlot, ...] = ()

    def __post_init__(self) -> None:
        _validate_typed_selection(self.targets, HandSlot, minimum=0, maximum=5)


@dataclass(frozen=True, slots=True)
class SkipPack:
    pass


@dataclass(frozen=True, slots=True)
class ReorderHand:
    order: tuple[HandSlot, ...]

    def __post_init__(self) -> None:
        _validate_typed_selection(self.order, HandSlot, minimum=0, maximum=None)


@dataclass(frozen=True, slots=True)
class ReorderJokers:
    order: tuple[JokerSlot, ...]

    def __post_init__(self) -> None:
        _validate_typed_selection(self.order, JokerSlot, minimum=0, maximum=None)


@dataclass(frozen=True, slots=True)
class ReorderConsumables:
    order: tuple[ConsumableSlot, ...]

    def __post_init__(self) -> None:
        _validate_typed_selection(self.order, ConsumableSlot, minimum=0, maximum=None)


PublicAction: TypeAlias = (
    SelectBlind
    | SkipBlind
    | CashOut
    | LeaveShop
    | RerollShop
    | RerollBoss
    | PlayCards
    | DiscardCards
    | BuyShopCard
    | BuyVoucher
    | BuyPack
    | SellJoker
    | SellConsumable
    | UseConsumable
    | ChoosePackCard
    | SkipPack
    | ReorderHand
    | ReorderJokers
    | ReorderConsumables
)


_SELL_USE_PHASES = {Phase.SELECTING_HAND, Phase.SHOP}
_REORDER_PHASES = {Phase.SELECTING_HAND, Phase.SHOP}


def iter_legal_actions(observation: PublicObservation) -> Iterator[PublicAction]:
    """Yield concrete legal actions using public state only.

    Reordering is exposed as adjacent swaps.  This keeps each decision
    bounded while repeated legal actions can still reach every permutation.
    """

    phase = observation.phase
    if phase == Phase.BLIND_SELECT:
        selected = next((blind for blind in observation.blinds if blind.status == "SELECT"), None)
        if selected is not None:
            yield SelectBlind()
        if selected is not None and selected.kind != "BOSS":
            yield SkipBlind()
        if is_legal(observation, RerollBoss()):
            yield RerollBoss()
    elif phase == Phase.SELECTING_HAND:
        hand_slots = tuple(HandSlot(index) for index in range(len(observation.hand)))
        maximum = min(5, observation.selection_limit, len(hand_slots))
        # Put strategically useful full hands before the bounded policy-wire
        # cutoff while preserving the complete legal action set.
        for size in range(maximum, 0, -1):
            for selected in combinations(hand_slots, size):
                play = PlayCards(selected)
                if is_legal(observation, play):
                    yield play
                if observation.round.discards_left > 0:
                    discard = DiscardCards(selected)
                    if is_legal(observation, discard):
                        yield discard
    elif phase == Phase.ROUND_EVAL:
        yield CashOut()
    elif phase == Phase.SHOP:
        if _can_spend(observation, observation.round.reroll_cost):
            yield RerollShop()
        for index, item in enumerate(observation.shop):
            action = BuyShopCard(ShopSlot(index))
            if is_legal(observation, action):
                yield action
        for index, item in enumerate(observation.vouchers):
            action = BuyVoucher(VoucherSlot(index))
            if is_legal(observation, action):
                yield action
        for index, item in enumerate(observation.packs):
            action = BuyPack(PackOfferSlot(index))
            if is_legal(observation, action):
                yield action
        yield LeaveShop()
    elif phase == Phase.PACK:
        yield SkipPack()
        for index, item in enumerate(observation.opened_pack):
            if isinstance(item, VisiblePlayingCard) or item.kind.upper() == "JOKER":
                action = ChoosePackCard(OpenedPackSlot(index))
                if is_legal(observation, action):
                    yield action
            else:
                for target_indexes in iter_public_targets(observation, item, from_pack=True):
                    action = ChoosePackCard(
                        OpenedPackSlot(index),
                        tuple(HandSlot(target) for target in target_indexes),
                    )
                    if is_legal(observation, action):
                        yield action

    if phase in _SELL_USE_PHASES:
        for index, item in enumerate(observation.jokers):
            if isinstance(item, HiddenJokerSlot):
                continue
            action = SellJoker(JokerSlot(index))
            if is_legal(observation, action):
                yield action
        for index, item in enumerate(observation.consumables):
            sell = SellConsumable(ConsumableSlot(index))
            if is_legal(observation, sell):
                yield sell
            for target_indexes in iter_public_targets(observation, item, from_pack=False):
                use = UseConsumable(
                    ConsumableSlot(index),
                    tuple(HandSlot(target) for target in target_indexes),
                )
                if is_legal(observation, use):
                    yield use

    if phase in _REORDER_PHASES or observation.pack_kind == "SMODS":
        if _reorder_phase_legal(observation, "hand") and len(observation.hand) > 1:
            yield from (
                ReorderHand(order)
                for order in _adjacent_orders(HandSlot, len(observation.hand))
            )
        if (
            _reorder_phase_legal(observation, "jokers")
            and len(observation.jokers) > 1
            and not any(
                isinstance(joker, HiddenJokerSlot)
                for joker in observation.jokers
            )
        ):
            yield from (
                ReorderJokers(order)
                for order in _adjacent_orders(JokerSlot, len(observation.jokers))
            )
        if _reorder_phase_legal(observation, "consumables") and len(observation.consumables) > 1:
            yield from (
                ReorderConsumables(order)
                for order in _adjacent_orders(ConsumableSlot, len(observation.consumables))
            )


def is_legal(observation: PublicObservation, action: PublicAction) -> bool:
    phase = observation.phase
    if isinstance(action, SelectBlind):
        return phase == Phase.BLIND_SELECT and any(blind.status == "SELECT" for blind in observation.blinds)
    if isinstance(action, SkipBlind):
        return phase == Phase.BLIND_SELECT and any(
            blind.status == "SELECT" and blind.kind != "BOSS" for blind in observation.blinds
        )
    if isinstance(action, CashOut):
        return phase == Phase.ROUND_EVAL
    if isinstance(action, LeaveShop):
        return phase == Phase.SHOP
    if isinstance(action, RerollShop):
        return phase == Phase.SHOP and _can_spend(observation, observation.round.reroll_cost)
    if isinstance(action, RerollBoss):
        selectable_boss = any(
            blind.kind == "BOSS" and blind.status in {"SELECT", "UPCOMING"}
            for blind in observation.blinds
        )
        has_retcon = "v_retcon" in observation.used_vouchers
        has_unused_directors_cut = (
            "v_directors_cut" in observation.used_vouchers
            and not observation.round.boss_rerolled
        )
        return (
            phase == Phase.BLIND_SELECT
            and selectable_boss
            and _can_spend(observation, 10)
            and (has_retcon or has_unused_directors_cut)
        )
    if isinstance(action, PlayCards):
        return (
            phase == Phase.SELECTING_HAND
            and observation.round.hands_left > 0
            and _valid_hand_selection(observation, action.cards)
        )
    if isinstance(action, DiscardCards):
        return (
            phase == Phase.SELECTING_HAND
            and observation.round.hands_left > 0
            and observation.round.discards_left > 0
            and _valid_hand_selection(observation, action.cards)
        )
    if isinstance(action, BuyShopCard):
        if phase != Phase.SHOP or action.mode != BuyMode.STORE or action.card.value >= len(observation.shop):
            return False
        item = observation.shop[action.card.value]
        return _can_spend(observation, item.buy_cost) and _has_room(observation, item)
    if isinstance(action, BuyVoucher):
        return (
            phase == Phase.SHOP
            and action.voucher.value < len(observation.vouchers)
            and _can_spend(observation, observation.vouchers[action.voucher.value].buy_cost)
        )
    if isinstance(action, BuyPack):
        return (
            phase == Phase.SHOP
            and action.pack.value < len(observation.packs)
            and _can_spend(observation, observation.packs[action.pack.value].buy_cost)
        )
    if isinstance(action, SellJoker):
        return (
            phase in _SELL_USE_PHASES
            and action.joker.value < len(observation.jokers)
            and not isinstance(
                observation.jokers[action.joker.value], HiddenJokerSlot
            )
            and not observation.jokers[action.joker.value].eternal
        )
    if isinstance(action, SellConsumable):
        return phase in _SELL_USE_PHASES and action.consumable.value < len(observation.consumables)
    if isinstance(action, UseConsumable):
        if phase not in _SELL_USE_PHASES or action.consumable.value >= len(observation.consumables):
            return False
        item = observation.consumables[action.consumable.value]
        if action.targets and phase != Phase.SELECTING_HAND:
            return False
        if action.targets and not set(observation.required_hand_slots).issubset(
            target.value for target in action.targets
        ):
            return False
        return public_consumable_is_usable(
            observation,
            item,
            tuple(target.value for target in action.targets),
            from_pack=False,
        )
    if isinstance(action, ChoosePackCard):
        if phase != Phase.PACK or action.card.value >= len(observation.opened_pack):
            return False
        return _pack_offer_legal(
            observation,
            observation.opened_pack[action.card.value],
            action.targets,
        )
    if isinstance(action, SkipPack):
        return phase == Phase.PACK
    if isinstance(action, ReorderHand):
        return _reorder_phase_legal(observation, "hand") and _is_adjacent_order(
            action.order, len(observation.hand)
        )
    if isinstance(action, ReorderJokers):
        return (
            _reorder_phase_legal(observation, "jokers")
            and not any(
                isinstance(joker, HiddenJokerSlot)
                for joker in observation.jokers
            )
            and _is_adjacent_order(action.order, len(observation.jokers))
        )
    if isinstance(action, ReorderConsumables):
        return _reorder_phase_legal(observation, "consumables") and _is_adjacent_order(
            action.order, len(observation.consumables)
        )
    return False


def _pack_offer_legal(
    observation: PublicObservation,
    item: PublicItem | VisiblePlayingCard,
    targets: tuple[HandSlot, ...],
) -> bool:
    if isinstance(item, VisiblePlayingCard):
        return not targets
    if item.kind.upper() == "JOKER":
        return not targets and (
            item.edition == "NEGATIVE"
            or len(observation.jokers) < observation.joker_limit
        )
    return public_consumable_is_usable(
        observation,
        item,
        tuple(target.value for target in targets),
        from_pack=True,
    )


def _valid_hand_selection(observation: PublicObservation, cards: tuple[HandSlot, ...]) -> bool:
    return (
        1 <= len(cards) <= min(5, observation.selection_limit)
        and all(card.value < len(observation.hand) for card in cards)
        and set(observation.required_hand_slots).issubset(card.value for card in cards)
    )


def _reorder_phase_legal(observation: PublicObservation, area: str) -> bool:
    if area == "hand":
        return observation.phase == Phase.SELECTING_HAND or observation.pack_kind == "SMODS"
    return observation.phase in _REORDER_PHASES or observation.pack_kind == "SMODS"


def _adjacent_orders(wrapper: type, size: int) -> Iterator[tuple]:
    identity = [wrapper(index) for index in range(size)]
    for index in range(size - 1):
        order = identity.copy()
        order[index], order[index + 1] = order[index + 1], order[index]
        yield tuple(order)


def _is_adjacent_order(order: tuple[object, ...], size: int) -> bool:
    values = tuple(getattr(slot, "value", -1) for slot in order)
    if len(values) != size or set(values) != set(range(size)):
        return False
    displaced = [index for index, value in enumerate(values) if index != value]
    return (
        len(displaced) == 2
        and displaced[1] == displaced[0] + 1
        and values[displaced[0]] == displaced[1]
        and values[displaced[1]] == displaced[0]
    )


def _can_spend(observation: PublicObservation, cost: int | None) -> bool:
    if cost is None:
        return False
    active_credit_cards = sum(
        item.key == "j_credit_card" and not item.debuffed
        for item in observation.jokers
        if not isinstance(item, HiddenJokerSlot)
    )
    floor = -20 * active_credit_cards
    return observation.money - cost >= floor


def _has_room(
    observation: PublicObservation, item: PublicItem | PublicShopPlayingCard
) -> bool:
    if isinstance(item, PublicShopPlayingCard):
        return True
    kind = item.kind.upper()
    if kind == "JOKER":
        return item.edition == "NEGATIVE" or len(observation.jokers) < observation.joker_limit
    if kind in {"TAROT", "PLANET", "SPECTRAL"}:
        return len(observation.consumables) < observation.consumable_limit
    return False


def action_to_data(action: PublicAction) -> dict[str, object]:
    if isinstance(
        action,
        (SelectBlind, SkipBlind, CashOut, LeaveShop, RerollShop, RerollBoss, SkipPack),
    ):
        return {"type": _action_type(action)}
    if isinstance(action, (PlayCards, DiscardCards)):
        return {"type": _action_type(action), "cards": [slot.value for slot in action.cards]}
    if isinstance(action, BuyShopCard):
        return {"type": "buy_shop_card", "card": action.card.value, "mode": action.mode.value}
    if isinstance(action, BuyVoucher):
        return {"type": "buy_voucher", "voucher": action.voucher.value}
    if isinstance(action, BuyPack):
        return {"type": "buy_pack", "pack": action.pack.value}
    if isinstance(action, SellJoker):
        return {"type": "sell_joker", "joker": action.joker.value}
    if isinstance(action, SellConsumable):
        return {"type": "sell_consumable", "consumable": action.consumable.value}
    if isinstance(action, UseConsumable):
        return {
            "type": "use_consumable",
            "consumable": action.consumable.value,
            "targets": [slot.value for slot in action.targets],
        }
    if isinstance(action, ChoosePackCard):
        return {
            "type": "choose_pack_card",
            "card": action.card.value,
            "targets": [slot.value for slot in action.targets],
        }
    if isinstance(action, ReorderHand):
        return {"type": "reorder_hand", "order": [slot.value for slot in action.order]}
    if isinstance(action, ReorderJokers):
        return {"type": "reorder_jokers", "order": [slot.value for slot in action.order]}
    if isinstance(action, ReorderConsumables):
        return {"type": "reorder_consumables", "order": [slot.value for slot in action.order]}
    raise TypeError(f"unsupported public action {type(action).__name__}")


def action_from_data(data: Mapping[str, object]) -> PublicAction:
    kind = data.get("type")
    if kind == "select_blind":
        return SelectBlind()
    if kind == "skip_blind":
        return SkipBlind()
    if kind == "cash_out":
        return CashOut()
    if kind == "leave_shop":
        return LeaveShop()
    if kind == "reroll_shop":
        return RerollShop()
    if kind == "reroll_boss":
        return RerollBoss()
    if kind == "skip_pack":
        return SkipPack()
    if kind == "play_cards":
        return PlayCards(_slots(data, "cards", HandSlot))
    if kind == "discard_cards":
        return DiscardCards(_slots(data, "cards", HandSlot))
    if kind == "buy_shop_card":
        return BuyShopCard(ShopSlot(_integer(data, "card")), BuyMode(str(data.get("mode"))))
    if kind == "buy_voucher":
        return BuyVoucher(VoucherSlot(_integer(data, "voucher")))
    if kind == "buy_pack":
        return BuyPack(PackOfferSlot(_integer(data, "pack")))
    if kind == "sell_joker":
        return SellJoker(JokerSlot(_integer(data, "joker")))
    if kind == "sell_consumable":
        return SellConsumable(ConsumableSlot(_integer(data, "consumable")))
    if kind == "use_consumable":
        return UseConsumable(
            ConsumableSlot(_integer(data, "consumable")),
            _slots(data, "targets", HandSlot),
        )
    if kind == "choose_pack_card":
        return ChoosePackCard(OpenedPackSlot(_integer(data, "card")), _slots(data, "targets", HandSlot))
    if kind == "reorder_hand":
        return ReorderHand(_slots(data, "order", HandSlot))
    if kind == "reorder_jokers":
        return ReorderJokers(_slots(data, "order", JokerSlot))
    if kind == "reorder_consumables":
        return ReorderConsumables(_slots(data, "order", ConsumableSlot))
    raise ValueError(f"unknown public action type {kind!r}")


def canonical_action_from_data(data: object) -> PublicAction:
    """Parse only the exact canonical output of :func:`action_to_data`."""

    if not isinstance(data, Mapping) or not all(isinstance(key, str) for key in data):
        raise ValueError("public action must be an object with string keys")
    action = action_from_data(data)
    if action_to_data(action) != data:
        raise ValueError("public action is not in canonical form")
    return action


def _action_type(action: object) -> str:
    names = {
        SelectBlind: "select_blind",
        SkipBlind: "skip_blind",
        CashOut: "cash_out",
        LeaveShop: "leave_shop",
        RerollShop: "reroll_shop",
        RerollBoss: "reroll_boss",
        PlayCards: "play_cards",
        DiscardCards: "discard_cards",
        SkipPack: "skip_pack",
    }
    return names[type(action)]


def _integer(data: Mapping[str, object], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"action field {key!r} must be an integer")
    return value


def _slots(data: Mapping[str, object], key: str, wrapper: type) -> tuple:
    values = data.get(key)
    if not isinstance(values, list):
        raise ValueError(f"action field {key!r} must be a list")
    return tuple(wrapper(_list_integer(value, key)) for value in values)


def _list_integer(value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"action field {key!r} must contain only integers")
    return value


def _validate_slot(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"slot must be a non-negative integer, got {value!r}")


def _validate_selection(values: tuple[object, ...], *, minimum: int, maximum: int | None) -> None:
    if len(values) < minimum or (maximum is not None and len(values) > maximum):
        upper = "unbounded" if maximum is None else str(maximum)
        raise ValueError(f"selection size must be in [{minimum}, {upper}]")
    if len(values) != len(set(values)):
        raise ValueError("selection contains duplicate slots")


def _validate_typed_selection(
    values: tuple[object, ...],
    expected: type,
    *,
    minimum: int,
    maximum: int | None,
) -> None:
    if not all(isinstance(value, expected) for value in values):
        raise TypeError(f"selection requires {expected.__name__} values")
    _validate_selection(values, minimum=minimum, maximum=maximum)
