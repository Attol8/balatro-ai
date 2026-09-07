from __future__ import annotations

import gzip
import json
import statistics
from pathlib import Path

import pytest

from balatro_ai.packet import (
    compact_packet,
    decode_card_entry,
    encode_card_entry,
    encode_tables,
    expand_packet,
)


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


def _card(**overrides: object) -> dict[str, object]:
    card = {
        "debuffed": False,
        "edition": None,
        "effect_text": "+2 chips",
        "enhancement": None,
        "permanent_bonus": 0,
        "rank": "2",
        "seal": None,
        "suit": "C",
    }
    card.update(overrides)
    return card


_SYNTHETIC_ENTRIES = [
    {"card": _card(), "count": 1},
    {"card": _card(), "count": 2},
    {"card": _card(rank="T", effect_text="+10 chips"), "count": 4},
    {"card": _card(rank="10", effect_text="+10 chips"), "count": 1},
    {"card": _card(rank="10", effect_text=""), "count": 3},
    {"card": _card(rank="A", suit="H", effect_text="+11 chips"), "count": 1},
    {"card": _card(effect_text=""), "count": 1},
    {"card": _card(enhancement="STEEL", effect_text="+2 chips X1.5 Mult"), "count": 1},
    {"card": _card(edition="POLYCHROME"), "count": 1},
    {"card": _card(edition="HOLOGRAPHIC"), "count": 1},
    {"card": _card(seal="RED"), "count": 1},
    {"card": _card(seal="GOLD SEAL"), "count": 1},
    {"card": _card(permanent_bonus=30, effect_text="+2 chips +30 extra chips"), "count": 1},
    {"card": _card(permanent_bonus=-4), "count": 1},
    {"card": _card(debuffed=True, effect_text="Scores no chips"), "count": 1},
    {"card": _card(effect_text='say "hi" \\ now'), "count": 1},
    {
        "card": _card(
            rank="K",
            suit="S",
            enhancement="LUCKY",
            edition="NEGATIVE",
            seal="PURPLE",
            permanent_bonus=12,
            debuffed=True,
            effect_text="+10 chips 1 in 5 chance for +20 Mult",
        ),
        "count": 7,
    },
    {
        "card": _card(rank="?", suit="?", enhancement="STONE", effect_text="+50 chips"),
        "count": 2,
    },
]


def test_card_entries_round_trip_through_every_suffix() -> None:
    for entry in _SYNTHETIC_ENTRIES:
        code = encode_card_entry(entry)
        assert decode_card_entry(code) == entry
        assert list(decode_card_entry(code)["card"]) == list(entry["card"])


def test_card_code_grammar_is_the_documented_one() -> None:
    assert encode_card_entry({"card": _card(), "count": 1}) == "2C"
    assert (
        encode_card_entry(
            {"card": _card(rank="K", suit="H", enhancement="STEEL", seal="RED"), "count": 1}
        )
        == 'KH+steel*red"+2 chips"'
    )
    assert (
        encode_card_entry({"card": _card(rank="K", suit="H", effect_text="+10 chips"), "count": 1})
        == "KH"
    )
    assert encode_card_entry({"card": _card(effect_text=""), "count": 3}) == '2Cx3""'


def test_malformed_card_codes_are_rejected() -> None:
    malformed = [
        "",
        "2",
        "2X",
        "1C",
        "2Cx",
        "2Cx1",
        "2C+",
        "2C^",
        "2C^0",
        "2C+steel/foil*red^2!extra",
        '2C"unterminated',
        '2C"bad"quote"',
        '2C"trailing\\"',
        "2C!!",
        "2C/foil+steel",
        123,
    ]
    for code in malformed:
        with pytest.raises(ValueError):
            decode_card_entry(code)


def test_unencodable_deck_entries_stay_verbatim() -> None:
    deck = [{"card": {"rank": "2"}, "count": 1}] * 3
    packet = {"instructions": "Go.", "observation": {"full_deck": deck}}
    compact = compact_packet(packet)
    assert expand_packet(compact)["observation"]["full_deck"] == deck


def test_compact_packet_documents_card_codes() -> None:
    compact = compact_packet({"instructions": "Choose one legal action."})
    assert "card codes" in compact["instructions"]
    assert "KH+steel*red" in compact["instructions"]


def _recorded_coach_packets() -> list[dict[str, object]]:
    root = Path(__file__).resolve().parents[1]
    packets: list[dict[str, object]] = []
    for path in sorted(root.glob("evidence/astra-low-2K9H9HN/segments/0*/trajectory.jsonl.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            for line in stream:
                event = json.loads(line)
                if event.get("event") != "coach_request":
                    continue
                packets.append({key: value for key, value in event.items() if key != "event"})
    return packets


def test_recorded_coach_packets_round_trip_and_halve_the_wire() -> None:
    packets = _recorded_coach_packets()
    assert len(packets) > 300
    before: list[int] = []
    tables_only: list[int] = []
    after: list[int] = []
    for packet in packets:
        compact = compact_packet(packet)
        wire = json.dumps(compact, separators=(",", ":"))
        restored = expand_packet(json.loads(wire))
        # Everything but the appended decoder note must survive untouched.
        expected = dict(packet)
        assert restored.pop("instructions").startswith(expected.pop("instructions"))
        assert restored == expected
        before.append(_size(packet))
        tables_only.append(_size(encode_tables(packet)))
        after.append(len(wire.encode()))
    print(
        f"\ncoach packets={len(packets)}"
        f"\n  raw     median={statistics.median(before):.0f} max={max(before)}"
        f"\n  tables  median={statistics.median(tables_only):.0f} max={max(tables_only)}"
        f"\n  codes   median={statistics.median(after):.0f} max={max(after)}"
    )
    assert statistics.median(after) < 11_000
