import gzip
import json
import shutil
import threading
import urllib.request
from pathlib import Path

import pytest

from balatro_ai.watch import make_server, summarize

SEGMENT = Path(__file__).parents[1] / "evidence/astra-low-TAF7DNTX/segments/04"


@pytest.fixture
def segment_run(tmp_path):
    """The recorded last segment of the endless run, unpacked as a live run would write it."""
    run = tmp_path / "segment-04"
    run.mkdir()
    with gzip.open(SEGMENT / "trajectory.jsonl.gz", "rb") as archive:
        with (run / "trajectory.jsonl").open("wb") as plain:
            shutil.copyfileobj(archive, plain)
    for name in ("manifest.json", "result.json"):
        shutil.copy(SEGMENT / name, run / name)
    return run


def _transitions(run):
    lines = (run / "trajectory.jsonl").read_text().splitlines()
    return sum(1 for line in lines if json.loads(line)["event"] == "transition")


def test_segment_summary_reads_the_recorded_run(segment_run):
    summary = summarize(segment_run)
    assert summary["status"] == "finished"
    assert summary["result"]["status"] == "lost"
    assert summary["ante"] == 13
    # The whole run made 456 decisions; this segment only replays its own tail.
    assert summary["counters"]["decisions"] == _transitions(segment_run) == 256
    assert summary["peak_hand"] == 134231931235
    assert summary["counters"]["hedges_won"] == 14
    # Run totals stay with the result the runner wrote, not the segment's events.
    assert summary["result"]["coach_timeouts"] == 15
    assert summary["counters"]["timeouts"] == 2
    assert summary["blinds"][-1]["ante"] == 13
    assert summary["blinds"][-1]["requirement"] > 0


def test_segment_summary_carries_the_dashboard_panels(segment_run):
    summary = summarize(segment_run)
    assert summary["blind"]["kind"] == "BOSS"
    assert summary["plan"] and summary["jokers"]
    assert [hand["name"] for hand in summary["hand_levels"]][0] == "Flush"
    assert len(summary["hand_levels"]) == 5
    assert len(summary["feed"]) == 12
    assert summary["feed"][0]["index"] > summary["feed"][1]["index"]
    assert summary["latency"]["median"] > 0 and len(summary["latency"]["recent"]) == 60
    assert summary["counters"]["calls_per_decision"] > 0


def _event(index):
    return {
        "event": "transition",
        "source": "coach",
        "before": {"ante": 1, "round": {"chips": 0}, "money": 4},
        "after": {
            "ante": 1,
            "phase": "SELECTING_HAND",
            "money": 4,
            "round": {"chips": 100 * index, "hands_left": 3, "discards_left": 2},
            "blinds": [{"kind": "SMALL", "name": "Small Blind", "score": 300, "status": "CURRENT"}],
        },
        "action": {"type": "play_cards"},
    }


def test_tail_advances_without_rereading(tmp_path):
    run = tmp_path / "live"
    run.mkdir()
    path = run / "trajectory.jsonl"
    with path.open("w") as handle:
        for index in (1, 2):
            handle.write(json.dumps(_event(index)) + "\n")
    first = summarize(run)
    assert first["status"] == "live" and first["counters"]["decisions"] == 2
    with path.open("a") as handle:
        handle.write(json.dumps(_event(3)) + "\n")
    second = summarize(run)
    assert second["counters"]["decisions"] == 3
    assert second["blind"]["chips"] == 300
    assert len(second["blinds"]) == 1 and second["blinds"][0]["requirement"] == 300


def test_a_half_written_line_waits_for_its_newline(tmp_path):
    run = tmp_path / "partial"
    run.mkdir()
    path = run / "trajectory.jsonl"
    path.write_text(json.dumps(_event(1)) + "\n" + json.dumps(_event(2))[:40])
    assert summarize(run)["counters"]["decisions"] == 1
    path.write_text(json.dumps(_event(1)) + "\n" + json.dumps(_event(2)) + "\n")
    assert summarize(run)["counters"]["decisions"] == 2


def test_missing_trajectory_is_a_waiting_state(tmp_path):
    run = tmp_path / "empty"
    run.mkdir()
    summary = summarize(run)
    assert summary["status"] == "waiting"
    assert summary["counters"]["decisions"] == 0 and summary["blinds"] == []
    assert summary["ante"] is None and summary["blind"] is None


def _serve(run):
    server = make_server(run, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode()


def test_http_serves_the_page_and_the_state(segment_run):
    server, base = _serve(segment_run)
    try:
        page = _get(base + "/")
        assert "balatro-ai" in page and "<canvas" in page
        state = json.loads(_get(base + "/api/state"))
        for key in (
            "run",
            "status",
            "ante",
            "blind",
            "money",
            "jokers",
            "consumables",
            "hand_levels",
            "counters",
            "latency",
            "plan",
            "feed",
            "blinds",
            "peak_hand",
            "elapsed_seconds",
        ):
            assert key in state, key
        assert state["status"] == "finished" and state["ante"] == 13
        events = json.loads(_get(base + "/api/events?since=250"))
        assert events["columns"][0] == "index"
        assert [row[0] for row in events["rows"]] == [251, 252, 253, 254, 255, 256]
        assert json.loads(_get(base + "/api/events?since=0"))["last_event"] == 256
    finally:
        server.shutdown()
        server.server_close()


def test_page_supports_a_zoom_query_parameter() -> None:
    html = (Path(__file__).resolve().parents[1] / "balatro_ai" / "watch.html").read_text()
    assert 'get("zoom")' in html and "style.zoom" in html
