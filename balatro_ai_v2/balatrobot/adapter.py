"""One-way adapters between privileged BalatroBot data and public contracts."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from balatro_ai_v2.actions import (
    BuyPack,
    BuyShopCard,
    BuyVoucher,
    CashOut,
    ChoosePackCard,
    DiscardCards,
    LeaveShop,
    PlayCards,
    PublicAction,
    ReorderConsumables,
    ReorderHand,
    ReorderJokers,
    RerollShop,
    SelectBlind,
    SellConsumable,
    SellJoker,
    SkipBlind,
    SkipPack,
    UseConsumable,
    is_legal,
)
from balatro_ai_v2.public_state import (
    DeckCardCount,
    HandCard,
    HandStat,
    HiddenHandCard,
    Phase,
    PublicBlind,
    PublicItem,
    PublicObservation,
    PublicOffer,
    RoundObservation,
    VisiblePlayingCard,
)


JsonObject = dict[str, Any]

_PACK_PHASES = {
    "SMODS_BOOSTER_OPENED",
    "PLANET_PACK",
    "TAROT_PACK",
    "SPECTRAL_PACK",
    "STANDARD_PACK",
    "BUFFOON_PACK",
}
_EDITIONS = {"FOIL", "HOLO", "HOLOGRAPHIC", "POLYCHROME", "NEGATIVE"}
_ENHANCEMENTS = {"BONUS", "MULT", "WILD", "GLASS", "STEEL", "STONE", "GOLD", "LUCKY"}
_SEALS = {"RED", "BLUE", "GOLD", "GOLD SEAL", "PURPLE"}


class ObservationError(ValueError):
    """Raw state is missing or internally inconsistent."""


class IllegalPublicAction(ValueError):
    """The action is not legal under the policy-visible observation."""


def to_public_observation(raw: Mapping[str, Any]) -> PublicObservation:
    """Whitelist-build a policy observation without mutating ``raw``."""

    raw_phase = _required_string(raw, "state")
    try:
        phase = Phase.PACK if raw_phase in _PACK_PHASES else Phase(raw_phase)
    except ValueError as exc:
        raise ObservationError(f"unsupported Balatro state {raw_phase!r}") from exc

    hand_area = _area(raw, "hand")
    deck_area = _area(raw, "cards")
    hand = tuple(_hand_card(card) for card in hand_area["cards"])
    deck_cards = [_playing_card(card, respect_hidden=False) for card in deck_area["cards"]]
    deck_counts = Counter(deck_cards)

    round_raw = _required_mapping(raw, "round")
    blinds_raw = _required_mapping(raw, "blinds")
    hands_raw = _required_mapping(raw, "hands")
    joker_area = _area(raw, "jokers")
    consumable_area = _area(raw, "consumables")

    return PublicObservation(
        phase=phase,
        deck=_required_string(raw, "deck"),
        stake=_required_string(raw, "stake"),
        ante=_required_int(raw, "ante_num"),
        round_no=_required_int(raw, "round_num"),
        money=_required_int(raw, "money"),
        round=RoundObservation(
            chips=_required_int(round_raw, "chips"),
            hands_left=_required_int(round_raw, "hands_left"),
            discards_left=_required_int(round_raw, "discards_left"),
            hands_played=_required_int(round_raw, "hands_played"),
            discards_used=_required_int(round_raw, "discards_used"),
            reroll_cost=_required_int(round_raw, "reroll_cost"),
        ),
        blinds=tuple(
            sorted(
                (_blind(value) for value in blinds_raw.values()),
                key=lambda blind: ("SMALL", "BIG", "BOSS").index(blind.kind),
            )
        ),
        hand=hand,
        hand_limit=_required_int(hand_area, "limit"),
        selection_limit=_required_int(hand_area, "highlighted_limit"),
        remaining_deck=tuple(
            DeckCardCount(card=card, count=count)
            for card, count in sorted(deck_counts.items(), key=lambda pair: _playing_card_sort_key(pair[0]))
        ),
        draw_count=_required_int(deck_area, "count"),
        deck_size=_required_int(deck_area, "limit"),
        hand_stats=tuple(
            sorted((_hand_stat(name, value) for name, value in hands_raw.items()), key=lambda hand: hand.name)
        ),
        jokers=tuple(_item(card) for card in joker_area["cards"]),
        joker_limit=_required_int(joker_area, "limit"),
        consumables=tuple(_item(card) for card in consumable_area["cards"]),
        consumable_limit=_required_int(consumable_area, "limit"),
        shop=_items_from_optional_area(raw, "shop") if phase == Phase.SHOP else (),
        vouchers=_items_from_optional_area(raw, "vouchers") if phase == Phase.SHOP else (),
        packs=_items_from_optional_area(raw, "packs") if phase == Phase.SHOP else (),
        opened_pack=_offers_from_optional_area(raw, "pack") if phase == Phase.PACK else (),
        used_vouchers=_string_tuple(raw.get("used_vouchers", ()), "used_vouchers"),
        won=_required_bool(raw, "won"),
    )


def action_to_rpc(action: PublicAction, observation: PublicObservation) -> tuple[str, JsonObject]:
    if not is_legal(observation, action):
        raise IllegalPublicAction(f"{action!r} is not legal in {observation.phase.value}")
    if isinstance(action, SelectBlind):
        return "select", {}
    if isinstance(action, SkipBlind):
        return "skip", {}
    if isinstance(action, CashOut):
        return "cash_out", {}
    if isinstance(action, LeaveShop):
        return "next_round", {}
    if isinstance(action, RerollShop):
        return "reroll", {}
    if isinstance(action, PlayCards):
        return "play", {"cards": [slot.value for slot in action.cards]}
    if isinstance(action, DiscardCards):
        return "discard", {"cards": [slot.value for slot in action.cards]}
    if isinstance(action, BuyShopCard):
        return "buy", {"card": action.card.value}
    if isinstance(action, BuyVoucher):
        return "buy", {"voucher": action.voucher.value}
    if isinstance(action, BuyPack):
        return "buy", {"pack": action.pack.value}
    if isinstance(action, SellJoker):
        return "sell", {"joker": action.joker.value}
    if isinstance(action, SellConsumable):
        return "sell", {"consumable": action.consumable.value}
    if isinstance(action, UseConsumable):
        params: JsonObject = {"consumable": action.consumable.value}
        if action.targets:
            params["cards"] = [slot.value for slot in action.targets]
        return "use", params
    if isinstance(action, ChoosePackCard):
        params = {"card": action.card.value}
        if action.targets:
            params["targets"] = [slot.value for slot in action.targets]
        return "pack", params
    if isinstance(action, SkipPack):
        return "pack", {"skip": True}
    if isinstance(action, ReorderHand):
        return "rearrange", {"hand": [slot.value for slot in action.order]}
    if isinstance(action, ReorderJokers):
        return "rearrange", {"jokers": [slot.value for slot in action.order]}
    if isinstance(action, ReorderConsumables):
        return "rearrange", {"consumables": [slot.value for slot in action.order]}
    raise TypeError(f"unsupported public action {type(action).__name__}")


def _area(raw: Mapping[str, Any], name: str) -> JsonObject:
    area = _required_mapping(raw, name)
    cards = area.get("cards")
    if not isinstance(cards, list) or not all(isinstance(card, Mapping) for card in cards):
        raise ObservationError(f"{name}.cards must be a list of objects")
    count = _required_int(area, "count")
    if count != len(cards):
        raise ObservationError(f"unsettled {name}: count={count}, cards={len(cards)}")
    return dict(area)


def _optional_area(raw: Mapping[str, Any], name: str) -> JsonObject | None:
    if name not in raw:
        return None
    return _area(raw, name)


def _items_from_optional_area(raw: Mapping[str, Any], name: str) -> tuple[PublicItem, ...]:
    area = _optional_area(raw, name)
    return () if area is None else tuple(_item(card) for card in area["cards"])


def _offers_from_optional_area(raw: Mapping[str, Any], name: str) -> tuple[PublicOffer, ...]:
    area = _optional_area(raw, name)
    if area is None:
        return ()
    return tuple(_playing_card(card, respect_hidden=False) if _is_playing(card) else _item(card) for card in area["cards"])


def _hand_card(raw: Mapping[str, Any]) -> HandCard:
    state = raw.get("state")
    if isinstance(state, Mapping) and bool(state.get("hidden")):
        return HiddenHandCard()
    return _playing_card(raw, respect_hidden=True)


def _playing_card(raw: Mapping[str, Any], *, respect_hidden: bool) -> VisiblePlayingCard:
    state = raw.get("state")
    if respect_hidden and isinstance(state, Mapping) and bool(state.get("hidden")):
        raise ObservationError("hidden card identity reached playing-card adapter")
    value = _required_mapping(raw, "value")
    modifiers = _modifier_table(raw)
    return VisiblePlayingCard(
        rank=_required_string(value, "rank"),
        suit=_required_string(value, "suit"),
        enhancement=_named_modifier(modifiers, "enhancement", _ENHANCEMENTS),
        edition=_named_modifier(modifiers, "edition", _EDITIONS),
        seal=_named_modifier(modifiers, "seal", _SEALS),
        debuffed=isinstance(state, Mapping) and bool(state.get("debuff")),
        effect_text=str(value.get("effect") or ""),
    )


def _item(raw: Mapping[str, Any]) -> PublicItem:
    value = _required_mapping(raw, "value")
    cost = _required_mapping(raw, "cost")
    modifiers = _modifier_table(raw)
    edition = _named_modifier(modifiers, "edition", _EDITIONS)
    eternal = modifiers.get("eternal", False)
    rental = modifiers.get("rental", False)
    perishable = modifiers.get("perishable")
    if not isinstance(eternal, bool) or not isinstance(rental, bool):
        raise ObservationError("joker eternal/rental modifiers must be boolean")
    if perishable is not None and (isinstance(perishable, bool) or not isinstance(perishable, int) or perishable < 0):
        raise ObservationError("joker perishable modifier must be a non-negative integer")
    return PublicItem(
        key=_required_string(raw, "key"),
        label=_required_string(raw, "label"),
        kind=_required_string(raw, "set").upper(),
        effect_text=str(value.get("effect") or ""),
        edition=edition,
        eternal=eternal,
        perishable_rounds=perishable,
        rental=rental,
        buy_cost=_optional_int(cost, "buy"),
        sell_cost=_optional_int(cost, "sell"),
    )


def _blind(raw: object) -> PublicBlind:
    if not isinstance(raw, Mapping):
        raise ObservationError("blind must be an object")
    return PublicBlind(
        kind=_required_string(raw, "type"),
        status=_required_string(raw, "status"),
        name=_required_string(raw, "name"),
        effect=str(raw.get("effect") or ""),
        score=_required_int(raw, "score"),
        tag_name=str(raw.get("tag_name") or ""),
        tag_effect=str(raw.get("tag_effect") or ""),
    )


def _hand_stat(name: object, raw: object) -> HandStat:
    if not isinstance(name, str) or not isinstance(raw, Mapping):
        raise ObservationError("poker-hand state must be a named object")
    return HandStat(
        name=name,
        level=_required_int(raw, "level"),
        chips=_required_int(raw, "chips"),
        mult=_required_int(raw, "mult"),
        played=_required_int(raw, "played"),
        played_this_round=_required_int(raw, "played_this_round"),
    )


def _modifier_table(raw: Mapping[str, Any]) -> Mapping[str, object]:
    modifiers = raw.get("modifier", ())
    if isinstance(modifiers, Mapping):
        if not all(isinstance(key, str) for key in modifiers):
            raise ObservationError("card modifier keys must be strings")
        return modifiers
    if isinstance(modifiers, Sequence) and not isinstance(modifiers, str):
        # Older BalatroBot traces serialized modifiers as a flat list. Keep
        # support for forensic replay without exposing arbitrary fields.
        values = [str(value).upper() for value in modifiers]
        return {
            "enhancement": next((value for value in values if value in _ENHANCEMENTS), None),
            "edition": next((value for value in values if value in _EDITIONS), None),
            "seal": next((value for value in values if value in _SEALS), None),
        }
    raise ObservationError("card modifier must be a table")


def _named_modifier(modifiers: Mapping[str, object], key: str, allowed: set[str]) -> str | None:
    value = modifiers.get(key)
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ObservationError(f"card modifier {key} must be a string")
    normalized = value.upper()
    if normalized not in allowed:
        raise ObservationError(f"unknown {key} modifier {normalized!r}")
    return normalized


def _is_playing(raw: Mapping[str, Any]) -> bool:
    return str(raw.get("set") or "").upper() in {"DEFAULT", "ENHANCED"}


def _playing_card_sort_key(card: VisiblePlayingCard) -> tuple[object, ...]:
    return (
        card.rank,
        card.suit,
        card.enhancement or "",
        card.edition or "",
        card.seal or "",
        card.debuffed,
        card.effect_text,
    )


def _required_mapping(raw: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = raw.get(key)
    if not isinstance(value, Mapping):
        raise ObservationError(f"{key} must be an object")
    return value


def _required_string(raw: Mapping[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ObservationError(f"{key} must be a non-empty string")
    return value


def _required_int(raw: Mapping[str, Any], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ObservationError(f"{key} must be an integer")
    return value


def _optional_int(raw: Mapping[str, Any], key: str) -> int | None:
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ObservationError(f"{key} must be an integer or null")
    return value


def _required_bool(raw: Mapping[str, Any], key: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise ObservationError(f"{key} must be a boolean")
    return value


def _string_tuple(value: object, path: str) -> tuple[str, ...]:
    if isinstance(value, Mapping) and all(isinstance(item, str) for item in value):
        return tuple(sorted(value))
    if not isinstance(value, Sequence) or isinstance(value, str) or not all(isinstance(item, str) for item in value):
        raise ObservationError(f"{path} must be a string-keyed table")
    return tuple(sorted(value))
