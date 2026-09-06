from __future__ import annotations

import json
from pathlib import Path

from balatro_ai_v2.balatrobot.tracing import CANONICAL_SCHEMA_VERSION, _row_hash
from scripts.run_differential_campaign import summarize_trace_coverage


def test_coverage_uses_real_trace_sequence_and_rejects_unsafe_pack_offer(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    states = _baseline_states(pack_card={"kind": "TAROT"})
    _write_trace(
        trace_path,
        states[0],
        [
            ("select_blind", states[1]),
            ("discard_cards", states[2]),
            ("play_cards", states[3]),
            ("cash_out", states[4]),
            ("buy_pack", states[5]),
            ("skip_pack", states[6]),
            ("leave_shop", states[7]),
        ],
    )

    coverage = summarize_trace_coverage(trace_path, pack_strategy="mixed")

    assert coverage["accepted_action_counts"]["buy_pack"] == 1
    assert coverage["phase_counts"]["SHOP"] == 2
    assert coverage["opportunity_counts"].get("action:choose_pack_card", 0) == 0
    assert coverage["required_action_counts"]["choose_pack_card"] == 0
    assert coverage["coverage_complete"] is False


def test_coverage_marks_complete_public_pick_lane(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    states = _baseline_states(pack_card={"kind": "PLANET"})
    _write_trace(
        trace_path,
        states[0],
        [
            ("select_blind", states[1]),
            ("discard_cards", states[2]),
            ("play_cards", states[3]),
            ("cash_out", states[4]),
            ("buy_pack", states[5]),
            ("choose_pack_card", states[6]),
            ("leave_shop", states[7]),
        ],
    )

    coverage = summarize_trace_coverage(trace_path, pack_strategy="pick")

    assert coverage["coverage_complete"] is True
    assert coverage["accepted_action_counts"]["choose_pack_card"] == 1
    assert coverage["opportunity_counts"]["shop_with_pack_offers"] == 1
    assert coverage["opportunity_counts"]["pack_with_choices"] == 1


def test_extended_coverage_requires_reroll_and_consumable_use(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    states = _baseline_states(pack_card={"kind": "PLANET"})
    states[4]["consumables"] = [{"kind": "PLANET"}]
    states[4]["round"]["reroll_cost"] = 5
    _write_trace(
        trace_path,
        states[0],
        [
            ("select_blind", states[1]),
            ("discard_cards", states[2]),
            ("play_cards", states[3]),
            ("cash_out", states[4]),
            ("reroll_shop", states[4]),
            ("use_consumable", states[4]),
            ("buy_pack", states[5]),
            ("choose_pack_card", states[6]),
            ("leave_shop", states[7]),
        ],
    )

    coverage = summarize_trace_coverage(
        trace_path,
        pack_strategy="pick",
        coverage_mode="extended",
    )

    assert coverage["coverage_complete"] is True
    assert coverage["coverage_mode"] == "extended"
    assert coverage["required_action_counts"]["reroll_shop"] == 1
    assert coverage["required_action_counts"]["use_consumable"] == 1
    assert coverage["opportunity_counts"]["action:reroll_shop"] >= 1
    assert coverage["opportunity_counts"]["action:use_consumable"] >= 1


def test_planet_use_coverage_requires_explicit_buy_mode(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    states = _baseline_states(pack_card={"kind": "PLANET"})
    _write_trace(
        trace_path,
        states[0],
        [
            ("select_blind", states[1]),
            ("discard_cards", states[2]),
            ("play_cards", states[3]),
            ("cash_out", states[4]),
            ("reroll_shop", states[4]),
            ({"type": "buy_shop_card", "card": 0, "mode": "use"}, states[4]),
            ("leave_shop", states[7]),
        ],
    )

    coverage = summarize_trace_coverage(
        trace_path,
        pack_strategy="mixed",
        coverage_mode="planet_use",
    )

    assert coverage["coverage_complete"] is True
    assert coverage["accepted_action_counts"]["buy_shop_card_use"] == 1
    assert coverage["required_action_counts"]["buy_shop_card_use"] == 1


def test_pack_sale_coverage_requires_sale_while_pack_is_active(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    states = _baseline_states(pack_card={"kind": "JOKER"})
    _write_trace(
        trace_path,
        states[0],
        [
            ("select_blind", states[1]),
            ("discard_cards", states[2]),
            ("play_cards", states[3]),
            ("cash_out", states[4]),
            ("buy_pack", states[5]),
            ({"type": "sell_joker", "joker": 0}, states[5]),
            ("choose_pack_card", states[6]),
            ("leave_shop", states[7]),
        ],
    )

    coverage = summarize_trace_coverage(
        trace_path,
        pack_strategy="pick",
        coverage_mode="pack_sale",
    )

    assert coverage["coverage_complete"] is True
    assert coverage["accepted_action_counts"]["pack_inventory_sale"] == 1
    assert coverage["required_action_counts"]["pack_inventory_sale"] == 1


def _baseline_states(*, pack_card: dict[str, object]) -> list[dict[str, object]]:
    return [
        _public("BLIND_SELECT", blinds=[{"status": "SELECT"}]),
        _public("SELECTING_HAND", hand=[{}], discards_left=2),
        _public("SELECTING_HAND", hand=[{}], discards_left=1),
        _public("ROUND_EVAL"),
        _public("SHOP", money=6, packs=[{"buy_cost": 4}]),
        _public("PACK", opened_pack=[pack_card]),
        _public("SHOP", money=2, packs=[]),
        _public("BLIND_SELECT", blinds=[{"status": "SELECT"}]),
    ]


def _public(
    phase: str,
    *,
    blinds: list[dict[str, object]] | None = None,
    hand: list[dict[str, object]] | None = None,
    discards_left: int = 0,
    money: int = 0,
    packs: list[dict[str, object]] | None = None,
    opened_pack: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "phase": phase,
        "blinds": blinds or [],
        "hand": hand or [],
        "round": {"discards_left": discards_left},
        "money": money,
        "packs": packs or [],
        "opened_pack": opened_pack or [],
        "jokers": [],
        "joker_limit": 5,
    }


def _write_trace(
    path: Path,
    initial_public: dict[str, object],
    transitions: list[tuple[str | dict[str, object], dict[str, object]]],
) -> None:
    rows: list[dict[str, object]] = [
        {
            "event": "manifest",
            "manifest": {
                "canonical_schema_version": CANONICAL_SCHEMA_VERSION,
                "profile_mode": "all_unlocked",
            },
        },
        {"event": "run_start", "public": initial_public},
    ]
    rows.extend(
        {
            "event": "transition",
            "status": "accepted",
            "action": (
                action_type if isinstance(action_type, dict) else {"type": action_type}
            ),
            "public_after": public_after,
        }
        for action_type, public_after in transitions
    )
    previous_hash = None
    with path.open("w", encoding="utf-8") as handle:
        for seq, payload in enumerate(rows):
            row = {
                "schema_version": 1,
                "run_id": "test-run",
                "seq": seq,
                "previous_hash": previous_hash,
                **payload,
            }
            row["row_hash"] = _row_hash(row)
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            previous_hash = row["row_hash"]
