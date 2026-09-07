"""Lossless compact encoding for repeated public packet rows."""

from __future__ import annotations

import json
from typing import Any

_TABLE_NOTE = (
    "\nCompact tables use {\"$columns\":[keys],\"$rows\":[value rows]}; "
    "read each row by matching values to columns."
)


def compact_packet(packet: dict[str, object]) -> dict[str, object]:
    """Append the wire-format note and compact repeated homogeneous rows."""

    # Stable instructions lead the wire request; per-call IDs must not break
    # the shared prefix. This changes order only, never values or information.
    order = ("instructions", "observation", "analysis", "recent_outcomes", "plan",
             "validation_feedback")
    prepared = {key: packet[key] for key in order if key in packet}
    prepared.update((key, value) for key, value in packet.items()
                    if key not in prepared and key != "request_id")
    if "request_id" in packet:
        prepared["request_id"] = packet["request_id"]
    instructions = prepared.get("instructions")
    if isinstance(instructions, str):
        prepared["instructions"] = instructions + _TABLE_NOTE
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
                {column: expand_packet(item) for column, item in zip(columns, row, strict=True)}
                for row in rows
            ]
    return {key: expand_packet(item) for key, item in value.items()}


def _json_size(value: object) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())
