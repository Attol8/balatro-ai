"""Shared strict JSON-lines framing primitives."""

from __future__ import annotations

import json


class JsonlProtocolError(ValueError):
    pass


def encode_frame(payload: dict[str, object], maximum: int) -> bytes:
    try:
        encoded = (canonical_json(payload) + "\n").encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise JsonlProtocolError(f"frame is not JSON serializable: {exc}") from exc
    if len(encoded) > maximum:
        raise JsonlProtocolError(f"frame exceeds {maximum} bytes")
    return encoded


def decode_frame(frame: bytes, maximum: int) -> dict[str, object]:
    if not frame or len(frame) > maximum or not frame.endswith(b"\n"):
        raise JsonlProtocolError("frame is empty, oversized, or unterminated")
    try:
        text = frame.decode("utf-8")
        value: object = json.loads(text, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JsonlProtocolError(f"invalid JSON: {exc}") from exc
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise JsonlProtocolError("frame root must be an object")
    return dict(value)


def require_fields(raw: dict[str, object], expected: set[str], name: str) -> None:
    actual = set(raw)
    if actual != expected:
        raise JsonlProtocolError(
            f"{name} fields differ: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )


def nonnegative_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise JsonlProtocolError(f"{name} must be a non-negative integer")
    return value


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _reject_constant(value: str) -> object:
    raise JsonlProtocolError(f"invalid JSON constant {value!r}")
