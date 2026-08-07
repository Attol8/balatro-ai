"""Strict canonicalization for privileged, observed BalatroBot state.

This is intentionally named *observed* state: BalatroBot does not expose the
complete RNG or event queues, so matching it cannot prove snapshot fidelity.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


_TOP_LEVEL_FIELDS = {
    "ante_num",
    "blinds",
    "cards",
    "consumables",
    "deck",
    "hand",
    "hands",
    "jokers",
    "money",
    "pack",
    "packs",
    "round",
    "round_num",
    "seed",
    "shop",
    "stake",
    "state",
    "used_vouchers",
    "vouchers",
    "won",
}
_REQUIRED_TOP_LEVEL_FIELDS = {
    "ante_num",
    "blinds",
    "cards",
    "consumables",
    "deck",
    "hand",
    "hands",
    "jokers",
    "money",
    "round",
    "round_num",
    "seed",
    "stake",
    "state",
    "used_vouchers",
    "won",
}
_AREA_FIELDS = {"cards", "count", "highlighted_limit", "limit"}
_CARD_FIELDS = {"cost", "id", "key", "label", "modifier", "set", "state", "value"}
_COST_FIELDS = {"buy", "sell"}
_VALUE_FIELDS = {"ability", "effect", "rarity", "rank", "suit"}
_HAND_FIELDS = {"chips", "example", "level", "mult", "order", "played", "played_this_round"}
_BLIND_FIELDS = {"effect", "name", "score", "status", "tag_effect", "tag_name", "type"}
_ROUND_FIELDS = {
    "ancient_suit",
    "chips",
    "discards_left",
    "discards_used",
    "hands_left",
    "hands_played",
    "most_played_poker_hand",
    "reroll_cost",
}


class CanonicalizationError(ValueError):
    """The authority schema changed or contained non-canonical data."""


@dataclass(frozen=True, slots=True)
class CanonicalObservedState:
    raw_json: str
    canonical_json: str
    raw_digest: str
    canonical_digest: str

    @property
    def canonical(self) -> dict[str, Any]:
        value = json.loads(self.canonical_json)
        if not isinstance(value, dict):
            raise AssertionError("canonical state root is not an object")
        return value


class BalatroBotCanonicalizer:
    """Stateful raw-ID normalization for one run."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._entity_ids: dict[tuple[str, str], str] = {}
        self._initialized = False
        self._spawn_index = 0

    def canonicalize(self, raw: Mapping[str, Any]) -> CanonicalObservedState:
        _validate_state(raw)
        raw_json = _canonical_json(raw)
        self._assign_new_entities(raw)
        canonical = self._normalize(raw, path=())
        if not isinstance(canonical, dict):
            raise AssertionError("normalized state root is not an object")
        canonical_json = _canonical_json(canonical)
        self._initialized = True
        return CanonicalObservedState(
            raw_json=raw_json,
            canonical_json=canonical_json,
            raw_digest=_sha256(raw_json),
            canonical_digest=_sha256(canonical_json),
        )

    def _assign_new_entities(self, raw: Mapping[str, Any]) -> None:
        unseen: list[tuple[tuple[str, str], str, str]] = []
        for card in _walk_cards(raw):
            raw_id = card.get("id")
            if raw_id is None:
                raise CanonicalizationError("card is missing id")
            identity = _raw_identity(raw_id)
            if identity in self._entity_ids:
                continue
            kind = str(card.get("set") or "UNKNOWN")
            key = str(card.get("key") or "UNKNOWN")
            unseen.append((identity, kind, key))

        grouped: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
        for identity, kind, key in unseen:
            grouped[(kind, key)].append(identity)
        for (kind, key), identities in sorted(grouped.items()):
            identities.sort()
            for occurrence, identity in enumerate(identities):
                if self._initialized:
                    stable = f"spawn:{self._spawn_index}:{kind}:{key}"
                    self._spawn_index += 1
                else:
                    stable = f"initial:{kind}:{key}:{occurrence}"
                self._entity_ids[identity] = stable

    def _normalize(self, value: object, *, path: tuple[str, ...]) -> object:
        if isinstance(value, Mapping):
            normalized: dict[str, object] = {}
            for key, child in value.items():
                key_string = str(key)
                if _is_presentation_field(path, key_string):
                    continue
                if key_string == "id" and _is_card_path(path):
                    normalized[key_string] = self._entity_ids[_raw_identity(child)]
                else:
                    normalized[key_string] = self._normalize(child, path=(*path, key_string))
            return normalized
        if isinstance(value, list):
            if not value and _empty_lua_map_path(path):
                return {}
            return [self._normalize(child, path=(*path, "*")) for child in value]
        if isinstance(value, bool) or value is None or isinstance(value, str):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                raise CanonicalizationError(f"non-finite number at {'/'.join(path)}")
            if value == 0:
                return 0
            if value.is_integer():
                return int(value)
            return value
        raise CanonicalizationError(f"unsupported value {type(value).__name__} at {'/'.join(path)}")


def _validate_state(raw: Mapping[str, Any]) -> None:
    keys = set(raw)
    unknown = keys - _TOP_LEVEL_FIELDS
    missing = _REQUIRED_TOP_LEVEL_FIELDS - keys
    if unknown:
        raise CanonicalizationError(f"unknown top-level fields: {sorted(unknown)}")
    if missing:
        raise CanonicalizationError(f"missing top-level fields: {sorted(missing)}")

    for area_name in ("cards", "consumables", "hand", "jokers", "pack", "packs", "shop", "vouchers"):
        if area_name not in raw:
            continue
        area = _expect_mapping(raw[area_name], area_name)
        _reject_unknown(area, _AREA_FIELDS, area_name)
        cards = area.get("cards")
        if not isinstance(cards, list):
            raise CanonicalizationError(f"{area_name}.cards must be a list")
        for index, card_value in enumerate(cards):
            card = _expect_mapping(card_value, f"{area_name}.cards[{index}]")
            _reject_unknown(card, _CARD_FIELDS, f"{area_name}.cards[{index}]")
            cost = _expect_mapping(card.get("cost"), f"{area_name}.cards[{index}].cost")
            _reject_unknown(cost, _COST_FIELDS, f"{area_name}.cards[{index}].cost")
            value = _expect_mapping(card.get("value"), f"{area_name}.cards[{index}].value")
            _reject_unknown(value, _VALUE_FIELDS, f"{area_name}.cards[{index}].value")
            if not isinstance(card.get("state"), Mapping | list):
                raise CanonicalizationError(f"{area_name}.cards[{index}].state must be a table")
            if not isinstance(card.get("modifier"), Mapping | list):
                raise CanonicalizationError(f"{area_name}.cards[{index}].modifier must be a table")

    hands = _expect_mapping(raw["hands"], "hands")
    for name, hand_value in hands.items():
        hand = _expect_mapping(hand_value, f"hands.{name}")
        _reject_unknown(hand, _HAND_FIELDS, f"hands.{name}")
    blinds = _expect_mapping(raw["blinds"], "blinds")
    for name, blind_value in blinds.items():
        blind = _expect_mapping(blind_value, f"blinds.{name}")
        _reject_unknown(blind, _BLIND_FIELDS, f"blinds.{name}")
    round_state = _expect_mapping(raw["round"], "round")
    _reject_unknown(round_state, _ROUND_FIELDS, "round")


def _walk_cards(raw: Mapping[str, Any]) -> Sequence[Mapping[str, Any]]:
    cards: list[Mapping[str, Any]] = []
    for area_name in ("cards", "consumables", "hand", "jokers", "pack", "packs", "shop", "vouchers"):
        area = raw.get(area_name)
        if not isinstance(area, Mapping):
            continue
        values = area.get("cards")
        if isinstance(values, list):
            cards.extend(card for card in values if isinstance(card, Mapping))
    return cards


def _is_presentation_field(path: tuple[str, ...], key: str) -> bool:
    if _is_card_path(path) and key == "label":
        return True
    if path and path[-1] == "value" and _is_card_path(path[:-1]) and key == "effect":
        return True
    if len(path) >= 2 and path[-2] == "hands" and key == "example":
        return True
    if len(path) >= 2 and path[-2] == "blinds" and key in {"effect", "tag_effect"}:
        return True
    return False


def _is_card_path(path: tuple[str, ...]) -> bool:
    return len(path) >= 3 and path[-2:] == ("cards", "*")


def _empty_lua_map_path(path: tuple[str, ...]) -> bool:
    return bool(path) and path[-1] in {"modifier", "state", "used_vouchers"}


def _raw_identity(value: object) -> tuple[str, str]:
    return type(value).__name__, repr(value)


def _expect_mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CanonicalizationError(f"{path} must be an object")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = set(value) - allowed
    if unknown:
        raise CanonicalizationError(f"unknown fields at {path}: {sorted(unknown)}")


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CanonicalizationError(f"state is not canonical JSON: {exc}") from exc


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
