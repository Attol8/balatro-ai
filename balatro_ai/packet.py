"""Lossless compact encoding for repeated public packet rows."""

from __future__ import annotations

import json
from typing import Any

from balatro_ai.game.scoring import _RANK_CHIPS

_TABLE_NOTE = (
    '\nCompact tables use {"$columns":[keys],"$rows":[value rows]}; '
    "read each row by matching values to columns."
    "\nDeck lists use card codes: rank (2-9,T,J,Q,K,A; ? if hidden) then suit "
    "(S,H,D,C), followed in this order by optional suffixes xN copies, "
    "+enhancement, /edition, *seal, ^permanent bonus chips, ! debuffed and "
    '"effect text". A code without quoted text scores its plain rank chips. '
    "Example: KH+steel*red is a red-sealed Steel King of Hearts."
)

_DECK_FIELDS = ("remaining_deck", "full_deck")
_CARD_KEYS = (
    "debuffed",
    "edition",
    "effect_text",
    "enhancement",
    "permanent_bonus",
    "rank",
    "seal",
    "suit",
)
# Ranks are already single characters on the wire; "10" is accepted verbatim so
# no rank spelling is ever rewritten into another one.
_RANKS = frozenset({"2", "3", "4", "5", "6", "7", "8", "9", "T", "J", "Q", "K", "A", "?", "10"})
_SUITS = frozenset({"S", "H", "D", "C", "?"})
_DIGITS = frozenset("0123456789")
_TOKEN_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")
_ATTRIBUTE_SUFFIXES = (("+", "enhancement"), ("/", "edition"), ("*", "seal"))
# Plain cards score their rank chips; the wire text is derivable, so it is
# dropped and rebuilt instead of repeated for every deck entry.
_DEFAULT_CHIPS = {**_RANK_CHIPS, "10": _RANK_CHIPS["T"]}


def compact_packet(packet: dict[str, object]) -> dict[str, object]:
    """Append the wire-format note and compact repeated homogeneous rows."""

    # Stable instructions lead the wire request; per-call IDs must not break
    # the shared prefix. This changes order only, never values or information.
    order = (
        "instructions",
        "observation",
        "analysis",
        "recent_outcomes",
        "plan",
        "validation_feedback",
    )
    prepared = {key: packet[key] for key in order if key in packet}
    prepared.update(
        (key, value) for key, value in packet.items() if key not in prepared and key != "request_id"
    )
    if "request_id" in packet:
        prepared["request_id"] = packet["request_id"]
    instructions = prepared.get("instructions")
    if isinstance(instructions, str):
        prepared["instructions"] = instructions + _TABLE_NOTE
    _encode_deck_fields(prepared)
    encoded = encode_tables(prepared)
    assert isinstance(encoded, dict)
    return encoded


def encode_tables(value: Any) -> Any:
    """Recursively encode worthwhile homogeneous lists of dictionaries."""

    if isinstance(value, dict):
        return {key: encode_tables(item) for key, item in value.items()}
    if not isinstance(value, list):
        return value
    items = [encode_tables(item) for item in value]
    if len(items) < 3 or not all(isinstance(item, dict) for item in items):
        return items
    columns = list(items[0])
    if not all(isinstance(column, str) for column in columns):
        return items
    if any(set(item) != set(columns) for item in items[1:]):
        return items
    table = {
        "$columns": columns,
        "$rows": [[item[column] for column in columns] for item in items],
    }
    return table if _json_size(table) < _json_size(items) else items


def expand_packet(value: Any) -> Any:
    """Expand tables produced by :func:`encode_tables`."""

    if isinstance(value, list):
        return [expand_packet(item) for item in value]
    if not isinstance(value, dict):
        return value
    if set(value) == {"$columns", "$rows"}:
        columns, rows = value["$columns"], value["$rows"]
        if (
            isinstance(columns, list)
            and all(isinstance(column, str) for column in columns)
            and len(set(columns)) == len(columns)
            and isinstance(rows, list)
            and all(isinstance(row, list) and len(row) == len(columns) for row in rows)
        ):
            return [
                {
                    column: _expand_field(column, item)
                    for column, item in zip(columns, row, strict=True)
                }
                for row in rows
            ]
    return {key: _expand_field(key, item) for key, item in value.items()}


def _expand_field(key: str, value: Any) -> Any:
    if key in _DECK_FIELDS and isinstance(value, list) and all(isinstance(x, str) for x in value):
        return [decode_card_entry(code) for code in value]
    return expand_packet(value)


def _encode_deck_fields(prepared: dict[str, object]) -> None:
    """Replace deck compositions with card codes, in place, when encodable."""

    observation = prepared.get("observation")
    if not isinstance(observation, dict):
        return
    replacements: dict[str, object] = {}
    for field in _DECK_FIELDS:
        entries = observation.get(field)
        if not isinstance(entries, list):
            continue
        try:
            codes = [encode_card_entry(entry) for entry in entries]
        except ValueError:
            # Unexpected card shapes stay verbatim; the wire must never lose
            # information just because it cannot be shortened.
            continue
        replacements[field] = codes
    if replacements:
        prepared["observation"] = {**observation, **replacements}


def encode_card_entry(entry: object) -> str:
    """Encode one ``{"card": {...}, "count": n}`` deck entry as a card code."""

    if not isinstance(entry, dict) or set(entry) != {"card", "count"}:
        raise ValueError("deck entry must hold exactly a card and a count")
    card, count = entry["card"], entry["count"]
    if not isinstance(card, dict) or set(card) != set(_CARD_KEYS):
        raise ValueError("card must hold exactly the visible playing card fields")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("deck card count must be a positive integer")
    rank, suit = card["rank"], card["suit"]
    if rank not in _RANKS or suit not in _SUITS:
        raise ValueError(f"unsupported rank or suit: {rank!r}{suit!r}")
    parts = [rank, suit]
    if count > 1:
        parts.append(f"x{count}")
    for prefix, key in _ATTRIBUTE_SUFFIXES:
        value = card[key]
        if value is not None:
            parts.append(prefix + _encode_token(value))
    bonus = card["permanent_bonus"]
    if isinstance(bonus, bool) or not isinstance(bonus, int):
        raise ValueError("permanent bonus must be an integer")
    if bonus:
        parts.append(f"^{bonus}")
    debuffed = card["debuffed"]
    if not isinstance(debuffed, bool):
        raise ValueError("debuffed must be a boolean")
    if debuffed:
        parts.append("!")
    text = card["effect_text"]
    if not isinstance(text, str):
        raise ValueError("effect text must be a string")
    if text != _default_effect_text(rank):
        parts.append(_quote(text))
    return "".join(parts)


def decode_card_entry(code: object) -> dict[str, Any]:
    """Restore the exact deck entry that :func:`encode_card_entry` encoded."""

    if not isinstance(code, str) or not code:
        raise ValueError("card code must be a non-empty string")
    if code.startswith("10"):
        rank, position = "10", 2
    else:
        rank, position = code[0], 1
    if rank not in _RANKS:
        raise ValueError(f"unknown rank in card code: {code!r}")
    if position >= len(code) or code[position] not in _SUITS:
        raise ValueError(f"unknown suit in card code: {code!r}")
    suit = code[position]
    position += 1
    count = 1
    if position < len(code) and code[position] == "x":
        digits, position = _read_digits(code, position + 1)
        count = int(digits)
        if count < 2:
            raise ValueError(f"count suffix must exceed one in card code: {code!r}")
    attributes: dict[str, str | None] = {"enhancement": None, "edition": None, "seal": None}
    for prefix, key in _ATTRIBUTE_SUFFIXES:
        if position < len(code) and code[position] == prefix:
            position += 1
            start = position
            while position < len(code) and code[position] in _TOKEN_CHARS:
                position += 1
            if position == start:
                raise ValueError(f"empty {key} suffix in card code: {code!r}")
            attributes[key] = _decode_token(code[start:position])
    bonus = 0
    if position < len(code) and code[position] == "^":
        position += 1
        negative = position < len(code) and code[position] == "-"
        digits, position = _read_digits(code, position + int(negative))
        bonus = -int(digits) if negative else int(digits)
        if bonus == 0:
            raise ValueError(f"permanent bonus suffix must be non-zero: {code!r}")
    debuffed = position < len(code) and code[position] == "!"
    position += int(debuffed)
    if position < len(code):
        if code[position] != '"':
            raise ValueError(f"unexpected trailing text in card code: {code!r}")
        text = _unquote(code[position:])
    else:
        default = _default_effect_text(rank)
        if default is None:
            raise ValueError(f"card code needs explicit effect text: {code!r}")
        text = default
    card = {
        "debuffed": debuffed,
        "edition": attributes["edition"],
        "effect_text": text,
        "enhancement": attributes["enhancement"],
        "permanent_bonus": bonus,
        "rank": rank,
        "seal": attributes["seal"],
        "suit": suit,
    }
    return {"card": card, "count": count}


def _default_effect_text(rank: str) -> str | None:
    chips = _DEFAULT_CHIPS.get(rank)
    return None if chips is None else f"+{chips} chips"


def _read_digits(code: str, position: int) -> tuple[str, int]:
    start = position
    while position < len(code) and code[position] in _DIGITS:
        position += 1
    if position == start:
        raise ValueError(f"missing digits in card code: {code!r}")
    return code[start:position], position


def _encode_token(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("card attributes must be strings")
    token = value.lower().replace(" ", "_")
    if not token or any(character not in _TOKEN_CHARS for character in token):
        raise ValueError(f"unsupported card attribute: {value!r}")
    if _decode_token(token) != value:
        raise ValueError(f"card attribute is not reversible: {value!r}")
    return token


def _decode_token(token: str) -> str:
    return token.replace("_", " ").upper()


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _unquote(chunk: str) -> str:
    if len(chunk) < 2 or not chunk.startswith('"') or not chunk.endswith('"'):
        raise ValueError(f"unterminated effect text in card code: {chunk!r}")
    characters: list[str] = []
    position = 1
    end = len(chunk) - 1
    while position < end:
        character = chunk[position]
        if character == "\\":
            position += 1
            if position >= end or chunk[position] not in {"\\", '"'}:
                raise ValueError(f"invalid escape in effect text: {chunk!r}")
            characters.append(chunk[position])
        elif character == '"':
            raise ValueError(f"unescaped quote in effect text: {chunk!r}")
        else:
            characters.append(character)
        position += 1
    return "".join(characters)


def _json_size(value: object) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())
