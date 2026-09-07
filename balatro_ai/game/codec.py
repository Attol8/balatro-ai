"""Strict JSON-compatible codec for the policy-visible state contract."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import fields

from balatro_ai.game.state import (
    DeckCardCount,
    HandCard,
    HandStat,
    HiddenHandCard,
    HiddenJokerSlot,
    Phase,
    PublicBlind,
    PublicItem,
    PublicJokerRuntime,
    PublicObservation,
    PublicOffer,
    PublicShopPlayingCard,
    RoundObservation,
    VisiblePlayingCard,
)


class PublicCodecError(ValueError):
    pass


_VISIBLE_CARD_FIELDS = {field.name for field in fields(VisiblePlayingCard)}
_ITEM_FIELDS = {field.name for field in fields(PublicItem)}
_SHOP_PLAYING_CARD_FIELDS = {field.name for field in fields(PublicShopPlayingCard)}
_JOKER_RUNTIME_FIELDS = {field.name for field in fields(PublicJokerRuntime)}
_V13_JOKER_RUNTIME_FIELDS = {
    "invisible_rounds",
    "mail_rank",
    "current_hand_size_bonus",
    "remaining_discards",
}
_V12_JOKER_RUNTIME_FIELDS = _JOKER_RUNTIME_FIELDS - _V13_JOKER_RUNTIME_FIELDS
_V11_JOKER_RUNTIME_FIELDS = _V12_JOKER_RUNTIME_FIELDS - {"castle_suit"}
_OBSERVATION_FIELDS = {field.name for field in fields(PublicObservation)}


def public_observation_to_data(observation: PublicObservation) -> dict[str, object]:
    loaded: object = json.loads(observation.canonical_json())
    if not isinstance(loaded, dict) or not all(isinstance(key, str) for key in loaded):
        raise AssertionError("public observation did not serialize to an object")
    return dict(loaded)


def public_observation_from_data(data: object) -> PublicObservation:
    raw = _object(data, "observation")
    _require_fields(raw, _OBSERVATION_FIELDS, "observation")
    return PublicObservation(
        phase=_phase(raw["phase"]),
        deck=_string(raw["deck"], "deck"),
        stake=_string(raw["stake"], "stake"),
        ante=_integer(raw["ante"], "ante"),
        round_no=_integer(raw["round_no"], "round_no"),
        money=_integer(raw["money"], "money"),
        round=_round(raw["round"]),
        blinds=tuple(_blind(value) for value in _array(raw["blinds"], "blinds", 3)),
        hand=tuple(_hand_card(value) for value in _array(raw["hand"], "hand", 32)),
        hand_limit=_integer(raw["hand_limit"], "hand_limit"),
        selection_limit=_integer(raw["selection_limit"], "selection_limit"),
        required_hand_slots=tuple(
            _integer(value, "required_hand_slots item")
            for value in _array(raw["required_hand_slots"], "required_hand_slots", 5)
        ),
        remaining_deck=tuple(
            _deck_count(value) for value in _array(raw["remaining_deck"], "remaining_deck", 512)
        ),
        full_deck=tuple(
            _deck_count(value) for value in _array(raw["full_deck"], "full_deck", 512)
        ),
        draw_count=_integer(raw["draw_count"], "draw_count"),
        deck_size=_integer(raw["deck_size"], "deck_size"),
        hand_stats=tuple(
            _hand_stat(value) for value in _array(raw["hand_stats"], "hand_stats", 32)
        ),
        jokers=tuple(
            _joker_card(value) for value in _array(raw["jokers"], "jokers", 32)
        ),
        joker_limit=_integer(raw["joker_limit"], "joker_limit"),
        consumables=tuple(
            _item(value) for value in _array(raw["consumables"], "consumables", 32)
        ),
        consumable_limit=_integer(raw["consumable_limit"], "consumable_limit"),
        shop=tuple(_shop_offer(value) for value in _array(raw["shop"], "shop", 64)),
        vouchers=tuple(_item(value) for value in _array(raw["vouchers"], "vouchers", 64)),
        packs=tuple(_item(value) for value in _array(raw["packs"], "packs", 64)),
        opened_pack=tuple(
            _offer(value) for value in _array(raw["opened_pack"], "opened_pack", 64)
        ),
        pack_kind=_optional_string(raw["pack_kind"], "pack_kind"),
        pack_choices_remaining=_integer(
            raw["pack_choices_remaining"], "pack_choices_remaining"
        ),
        used_vouchers=tuple(
            _string(value, "used_vouchers item")
            for value in _array(raw["used_vouchers"], "used_vouchers", 128)
        ),
        last_tarot_planet=_optional_string(raw["last_tarot_planet"], "last_tarot_planet"),
        antes_cleared=_integer(raw["antes_cleared"], "antes_cleared"),
        won=_boolean(raw["won"], "won"),
    )


def _phase(value: object) -> Phase:
    try:
        return Phase(_string(value, "phase"))
    except ValueError as exc:
        raise PublicCodecError(f"unknown public phase {value!r}") from exc


def _round(value: object) -> RoundObservation:
    raw = _object(value, "round")
    names = {field.name for field in fields(RoundObservation)}
    if frozenset(raw) not in {frozenset(names), frozenset(names - {"most_played_hand"})}:
        raise PublicCodecError("round fields differ from the contract")
    return RoundObservation(
        chips=_integer(raw["chips"], "round.chips"),
        hands_left=_integer(raw["hands_left"], "round.hands_left"),
        discards_left=_integer(raw["discards_left"], "round.discards_left"),
        hands_played=_integer(raw["hands_played"], "round.hands_played"),
        discards_used=_integer(raw["discards_used"], "round.discards_used"),
        reroll_cost=_integer(raw["reroll_cost"], "round.reroll_cost"),
        boss_rerolled=_boolean(raw["boss_rerolled"], "round.boss_rerolled"),
        ancient_suit=_optional_string(raw["ancient_suit"], "round.ancient_suit"),
        most_played_hand=_optional_string(
            raw.get("most_played_hand"), "round.most_played_hand"
        ),
    )


def _blind(value: object) -> PublicBlind:
    raw = _object(value, "blind")
    names = {field.name for field in fields(PublicBlind)}
    _require_fields(raw, names, "blind")
    return PublicBlind(
        kind=_string(raw["kind"], "blind.kind"),
        status=_string(raw["status"], "blind.status"),
        name=_string(raw["name"], "blind.name"),
        effect=_string(raw["effect"], "blind.effect"),
        score=_integer(raw["score"], "blind.score"),
        disabled=_boolean(raw["disabled"], "blind.disabled"),
        tag_name=_string(raw["tag_name"], "blind.tag_name"),
        tag_effect=_string(raw["tag_effect"], "blind.tag_effect"),
    )


def _hand_card(value: object) -> HandCard:
    raw = _object(value, "hand card")
    if not raw:
        return HiddenHandCard()
    return _visible_card(raw)


def _joker_card(value: object) -> PublicItem | HiddenJokerSlot:
    raw = _object(value, "joker")
    if not raw:
        return HiddenJokerSlot()
    return _item(raw)


def _visible_card(value: object) -> VisiblePlayingCard:
    raw = _object(value, "visible card")
    _require_fields(raw, _VISIBLE_CARD_FIELDS, "visible card")
    try:
        return VisiblePlayingCard(
            rank=_string(raw["rank"], "card.rank"),
            suit=_string(raw["suit"], "card.suit"),
            enhancement=_optional_string(raw["enhancement"], "card.enhancement"),
            edition=_optional_string(raw["edition"], "card.edition"),
            seal=_optional_string(raw["seal"], "card.seal"),
            debuffed=_boolean(raw["debuffed"], "card.debuffed"),
            permanent_bonus=_integer(raw["permanent_bonus"], "card.permanent_bonus"),
            effect_text=_string(raw["effect_text"], "card.effect_text"),
        )
    except ValueError as exc:
        raise PublicCodecError(str(exc)) from exc


def _deck_count(value: object) -> DeckCardCount:
    raw = _object(value, "remaining-deck entry")
    _require_fields(raw, {"card", "count"}, "remaining-deck entry")
    return DeckCardCount(_visible_card(raw["card"]), _integer(raw["count"], "deck count"))


def _hand_stat(value: object) -> HandStat:
    raw = _object(value, "hand stat")
    names = {field.name for field in fields(HandStat)}
    _require_fields(raw, names, "hand stat")
    return HandStat(
        name=_string(raw["name"], "hand stat.name"),
        level=_integer(raw["level"], "hand stat.level"),
        chips=_integer(raw["chips"], "hand stat.chips"),
        mult=_integer(raw["mult"], "hand stat.mult"),
        played=_integer(raw["played"], "hand stat.played"),
        played_this_round=_integer(raw["played_this_round"], "hand stat.played_this_round"),
    )


def _item(value: object) -> PublicItem:
    raw = _object(value, "public item")
    _require_fields(raw, _ITEM_FIELDS, "public item")
    try:
        return PublicItem(
            key=_string(raw["key"], "item.key"),
            label=_string(raw["label"], "item.label"),
            kind=_string(raw["kind"], "item.kind"),
            effect_text=_string(raw["effect_text"], "item.effect_text"),
            edition=_optional_string(raw["edition"], "item.edition"),
            eternal=_boolean(raw["eternal"], "item.eternal"),
            perishable_rounds=_optional_integer(
                raw["perishable_rounds"], "item.perishable_rounds"
            ),
            rental=_boolean(raw["rental"], "item.rental"),
            debuffed=_boolean(raw["debuffed"], "item.debuffed"),
            buy_cost=_optional_integer(raw["buy_cost"], "item.buy_cost"),
            sell_cost=_optional_integer(raw["sell_cost"], "item.sell_cost"),
            runtime=_joker_runtime(raw["runtime"]),
        )
    except ValueError as exc:
        raise PublicCodecError(str(exc)) from exc


def _joker_runtime(value: object) -> PublicJokerRuntime | None:
    if value is None:
        return None
    raw = _object(value, "joker runtime")
    if frozenset(raw) not in {
        frozenset(_V11_JOKER_RUNTIME_FIELDS),
        frozenset(_V12_JOKER_RUNTIME_FIELDS),
        frozenset(_JOKER_RUNTIME_FIELDS),
    }:
        raise PublicCodecError("joker runtime fields differ from the contract")
    try:
        return PublicJokerRuntime(
            current_mult=_optional_integer(raw["current_mult"], "runtime.current_mult"),
            current_chips=_optional_integer(raw["current_chips"], "runtime.current_chips"),
            current_x_mult=_optional_number(raw["current_x_mult"], "runtime.current_x_mult"),
            current_dollars=_optional_integer(raw["current_dollars"], "runtime.current_dollars"),
            remaining_hands=_optional_integer(raw["remaining_hands"], "runtime.remaining_hands"),
            loyalty_remaining=_optional_integer(
                raw["loyalty_remaining"], "runtime.loyalty_remaining"
            ),
            driver_tally=_optional_integer(raw["driver_tally"], "runtime.driver_tally"),
            target_hand=_optional_string(raw["target_hand"], "runtime.target_hand"),
            target_rank=_optional_string(raw["target_rank"], "runtime.target_rank"),
            target_suit=_optional_string(raw["target_suit"], "runtime.target_suit"),
            castle_suit=_optional_string(
                raw.get("castle_suit"), "runtime.castle_suit"
            ),
            invisible_rounds=_optional_integer(
                raw.get("invisible_rounds"), "runtime.invisible_rounds"
            ),
            mail_rank=_optional_string(raw.get("mail_rank"), "runtime.mail_rank"),
            current_hand_size_bonus=_optional_integer(
                raw.get("current_hand_size_bonus"),
                "runtime.current_hand_size_bonus",
            ),
            remaining_discards=_optional_integer(
                raw.get("remaining_discards"), "runtime.remaining_discards"
            ),
        )
    except ValueError as exc:
        raise PublicCodecError(str(exc)) from exc


def _offer(value: object) -> PublicOffer:
    raw = _object(value, "opened-pack offer")
    if set(raw) == _VISIBLE_CARD_FIELDS:
        return _visible_card(raw)
    if set(raw) == _ITEM_FIELDS:
        return _item(raw)
    raise PublicCodecError("opened-pack offer has unknown fields")


def _shop_offer(value: object) -> PublicItem | PublicShopPlayingCard:
    raw = _object(value, "shop offer")
    if set(raw) == _SHOP_PLAYING_CARD_FIELDS:
        buy_cost = _integer(raw["buy_cost"], "shop playing-card buy_cost")
        if buy_cost < 0:
            raise PublicCodecError("shop playing-card buy_cost must be non-negative")
        return PublicShopPlayingCard(
            card=_visible_card(raw["card"]),
            buy_cost=buy_cost,
        )
    if set(raw) == _ITEM_FIELDS:
        item = _item(raw)
        if item.kind.upper() in {"DEFAULT", "ENHANCED"}:
            raise PublicCodecError(
                "shop playing card uses legacy generic item representation"
            )
        return item
    raise PublicCodecError("shop offer has unknown fields")


def _object(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise PublicCodecError(f"{name} must be an object with string keys")
    return value


def _array(value: object, name: str, maximum: int) -> list[object]:
    if not isinstance(value, list):
        raise PublicCodecError(f"{name} must be an array")
    if len(value) > maximum:
        raise PublicCodecError(f"{name} exceeds maximum length {maximum}")
    return value


def _require_fields(raw: Mapping[str, object], expected: set[str], name: str) -> None:
    actual = set(raw)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise PublicCodecError(f"{name} fields differ: missing={missing}, extra={extra}")


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise PublicCodecError(f"{name} must be a string")
    return value


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _string(value, name)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PublicCodecError(f"{name} must be an integer")
    return value


def _optional_integer(value: object, name: str) -> int | None:
    if value is None:
        return None
    return _integer(value, name)


def _optional_number(value: object, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise PublicCodecError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise PublicCodecError(f"{name} must be a finite number")
    return result


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise PublicCodecError(f"{name} must be a boolean")
    return value
