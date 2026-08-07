from __future__ import annotations

import json
from pathlib import Path

from balatro_ai_v2.balatrobot.tracing import _row_hash
from scripts.run_differential_campaign import summarize_trace_coverage


def test_summarize_trace_coverage_is_fail_closed_for_mixed_pack_lane(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            _transition(1, "select_blind", "BLIND_SELECT"),
            _transition(2, "discard_cards", "SELECTING_HAND", discards_left=2),
            _transition(3, "play_cards", "SELECTING_HAND", discards_left=1),
            _transition(4, "cash_out", "ROUND_EVAL"),
            _transition(5, "buy_pack", "SHOP", packs=2),
            _transition(6, "skip_pack", "BUFFOON_PACK", pack=2),
            _transition(7, "leave_shop", "SHOP", packs=1),
        ],
    )

    coverage = summarize_trace_coverage(trace_path, pack_strategy="mixed")

    assert coverage["accepted_action_counts"]["buy_pack"] == 1
    assert coverage["opportunity_counts"]["action:choose_pack_card"] == 1
    assert coverage["phase_counts"]["SHOP"] == 2
    assert coverage["required_action_counts"]["choose_pack_card"] == 0
    assert coverage["coverage_complete"] is False


def test_summarize_trace_coverage_marks_pick_lane_complete(tmp_path: Path) -> None:
    trace_path = tmp_path / "trace.jsonl"
    _write_trace(
        trace_path,
        [
            _transition(1, "select_blind", "BLIND_SELECT"),
            _transition(2, "discard_cards", "SELECTING_HAND", discards_left=2),
            _transition(3, "play_cards", "SELECTING_HAND", discards_left=1),
            _transition(4, "cash_out", "ROUND_EVAL"),
            _transition(5, "buy_pack", "SHOP", packs=2),
            _transition(6, "choose_pack_card", "PLANET_PACK", pack=2),
            _transition(7, "leave_shop", "SHOP", packs=1),
        ],
    )

    coverage = summarize_trace_coverage(trace_path, pack_strategy="pick")

    assert coverage["coverage_complete"] is True
    assert coverage["accepted_action_counts"]["choose_pack_card"] == 1
    assert coverage["opportunity_counts"]["shop_with_pack_offers"] == 2


def _write_trace(path: Path, transitions: list[dict[str, object]]) -> None:
    rows = [{"event": "manifest"}] + transitions
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


def _transition(
    seq: int,
    action_type: str,
    phase: str,
    *,
    discards_left: int = 0,
    packs: int = 0,
    pack: int = 0,
) -> dict[str, object]:
    return {
        "event": "transition",
        "status": "accepted",
        "action": {"type": action_type},
        "before": {
            "canonical": {
                "state": phase,
                "blinds": {"small": {"status": "SELECT"}},
                "round": {"discards_left": discards_left},
                "packs": {"cards": [{}] * packs},
                "pack": {"cards": [{}] * pack},
            }
        },
    }
