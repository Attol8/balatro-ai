import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "recording_export", Path(__file__).parents[1] / "scripts/export-recording.py"
)
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def row(time, event, trace="one", **kwargs):
    return dict(time=time, trace=trace, data=dict(event=event, **kwargs))


def test_alignment_and_uniform_speed(tmp_path):
    (tmp_path / "video-clock.json").write_text(json.dumps({"capture_started_at": 1000}))
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        "\n".join(
            json.dumps(x)
            for x in [
                {"event": "rpc_attempt", "recorded_at": 1010},
                {"event": "transition", "recorded_at": 1110},
            ]
        )
    )
    events = exporter.load_events(tmp_path, [trace])
    assert [x["time"] for x in events] == [10, 110]
    start, end, speed = exporter.window(events, 120, 52)
    assert (start, end, speed) == (9, 113, 2)
    assert (events[1]["time"] - start) / speed == 50.5


def test_window_clamps_tail_and_rejects_missing_footage():
    events = [row(1, "rpc_attempt"), row(99, "transition")]
    assert exporter.window(events, 100) == (0, 100, 1)
    with pytest.raises(ValueError, match="outside"):
        exporter.window(events, 98)
    with pytest.raises(ValueError):
        exporter.window(events, 100, float("nan"))


def test_explanation_only_follows_own_coach_action():
    action = {"type": "play", "cards": [1, 3]}
    proposal = row(
        1,
        "coach_response",
        response={
            "action_json": json.dumps(action),
            "explanation": "Play these cards.",
            "plan": "Build chips.",
        },
    )
    sending = row(2, "rpc_attempt", source="coach", action=action)
    executed = row(3, "transition", source="coach", action=action, after={"ante": 1})
    result = exporter.panels([proposal, sending, executed])
    assert result[-1][1]["explanation"] == "Play these cards."
    for boundary in [row(1.5, "coach_rejected"), row(1.5, "coach_request")]:
        assert (
            exporter.panels([proposal, boundary, sending])[-1][1]["explanation"]
            == "No per-action explanation recorded."
        )
    for changed in [
        row(2, "rpc_attempt", source="forced", action=action),
        row(2, "rpc_attempt", trace="resumed", source="coach", action=action),
        row(2, "rpc_attempt", source="coach", action={"type": "discard"}),
    ]:
        state = exporter.panels([proposal, changed])[-1][1]
        assert state["explanation"] == "No per-action explanation recorded."
        assert state["plan"] == "Build chips."


def test_plan_equals_preserves_previous_strategy():
    states = exporter.panels(
        [
            row(1, "coach_response", response={"plan": "Prioritize chips."}),
            row(2, "coach_response", response={"plan": "="}),
        ]
    )
    assert states[-1][1]["plan"] == "Prioritize chips."


def test_invalid_timestamp_rejected(tmp_path):
    (tmp_path / "video-clock.json").write_text('{"capture_started_at": 1000}')
    trace = tmp_path / "trace.jsonl"
    trace.write_text('{"recorded_at": true}')
    with pytest.raises(ValueError, match="recorded_at"):
        exporter.load_events(tmp_path, [trace])


@pytest.mark.parametrize(
    "action, expected",
    [
        (
            {"type": "play_cards", "cards": [0, 2, 4]},
            "Play cards · Card positions 1, 3, 5 (from the left)",
        ),
        (
            {"type": "discard_cards", "cards": [1]},
            "Discard cards · Card positions 2 (from the left)",
        ),
        (
            {"type": "buy_shop_card", "card": 0, "mode": "store"},
            "Buy shop card · Shop card position 1 (from the left) · Mode: store",
        ),
        (
            {"type": "use_consumable", "consumable": 1, "targets": [0, 4]},
            "Use consumable · Consumable position 2 (from the left) · Target card positions 1, 5 (from the left)",
        ),
        (
            {"type": "reorder_jokers", "order": [2, 0, 1]},
            "Reorder jokers · New order of positions 3, 1, 2 (from the left)",
        ),
        ({"type": "select_blind"}, "Select blind"),
        ({"type": "start", "deck": "BLACK", "stake": "GOLD"}, "Start · Deck: BLACK · Stake: GOLD"),
    ],
)
def test_readable_action_labels(action, expected):
    assert exporter.action_label(action) == expected


def test_request_refreshes_recorded_resources():
    state = exporter.panels(
        [
            row(
                1,
                "coach_request",
                observation={
                    "phase": "SELECTING_HAND",
                    "ante": 2,
                    "money": 8,
                    "round": {"chips": 150, "hands_left": 2, "discards_left": 1},
                },
            )
        ]
    )[-1][1]
    assert "Ante 2" in state["resources"]
    assert "Score 150" in state["resources"]
    assert "Hands 2" in state["resources"]
