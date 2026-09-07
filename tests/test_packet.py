from __future__ import annotations

import gzip
import json
from pathlib import Path

from balatro_ai.packet import compact_packet, encode_tables, expand_packet


def _latest_recorded_packets() -> list[dict[str, object]]:
    # Use tracked evidence, never an active or Git-ignored run directory.
    path = Path(__file__).resolve().parents[1] / "evidence/first-win/trajectory.jsonl.gz"
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        events = [json.loads(line) for line in stream]
    return [
        dict(
            instructions="Choose one legal action.",
            observation=event["observation"]["public_solver"],
        )
        for event in events
        if event["event"] == "decision"
    ]


def _size(value: object) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode())


def test_recorded_public_packets_round_trip_exactly() -> None:
    for packet in _latest_recorded_packets():
        assert expand_packet(encode_tables(packet)) == packet


def test_realistic_public_packets_are_smaller() -> None:
    packets = _latest_recorded_packets()
    original = sum(_size(packet) for packet in packets)
    compact = sum(_size(encode_tables(packet)) for packet in packets)
    assert compact < original
    assert original - compact > 100_000


def test_homogeneous_rows_recurse_and_preserve_column_order() -> None:
    value = [
        {"slot": index, "card": {"rank": rank, "flags": [True, None]}}
        for index, rank in enumerate(("A", "K", "Q"))
    ]
    encoded = encode_tables(value)
    assert encoded["$columns"] == ["slot", "card"]
    assert expand_packet(encoded) == value


def test_mixed_dictionary_rows_remain_structural_lists() -> None:
    value = [{"a": 1}, {"a": 2, "b": 3}, {"a": 4}]
    assert encode_tables(value) == value
    non_json_object_keys = [{1: "a"}, {1: "b"}, {1: "c"}]
    assert encode_tables(non_json_object_keys) == non_json_object_keys


def test_short_or_larger_tagged_form_is_not_used() -> None:
    short = [{"long_field": 1}, {"long_field": 2}]
    tiny = [{"x": 1}, {"x": 2}, {"x": 3}]
    assert encode_tables(short) == short
    assert encode_tables(tiny) == tiny


def test_compact_packet_adds_decoder_note_without_mutating_input() -> None:
    packet = {"instructions": "Choose one action.", "rows": [{"long_name": i} for i in range(3)]}
    compact = compact_packet(packet)
    assert packet["instructions"] == "Choose one action."
    assert "$columns" in compact["instructions"]
    expanded = expand_packet(compact)
    assert expanded["rows"] == packet["rows"]


def test_unique_id_is_after_identical_prompt_prefix():
    first = {
        "request_id": "unique-A",
        "plan": "Retain chips",
        "instructions": "Rules",
        "observation": {"phase": "SHOP"},
    }
    second = dict(first, request_id="unique-B")
    wire_a = json.dumps(compact_packet(first), separators=(",", ":"))
    wire_b = json.dumps(compact_packet(second), separators=(",", ":"))
    assert wire_a.startswith('{"instructions":')
    assert wire_a.split('"request_id":')[0] == wire_b.split('"request_id":')[0]
    assert list(compact_packet(first))[-1] == "request_id"
    assert expand_packet(compact_packet(first))["observation"] == first["observation"]
