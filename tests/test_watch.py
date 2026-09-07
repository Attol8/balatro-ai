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
    # Isolate the fixture: the recorded manifest points at a run directory that may
    # still exist on a developer machine, and the watch would follow it.
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    manifest.pop("continuation_of", None)
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
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
    assert len(summary["feed"]) == 24
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


def _page() -> str:
    return (Path(__file__).resolve().parents[1] / "balatro_ai" / "watch.html").read_text()


def test_page_supports_a_zoom_query_parameter() -> None:
    html = _page()
    assert 'get("zoom")' in html and "style.zoom" in html


def test_the_stat_tiles_are_off_unless_asked_for() -> None:
    """The game window beside the dashboard already shows them; ?tiles=1 brings them back."""
    html = _page()
    assert "#tiles, #jokers-panel { display: none; }" in html
    assert 'params.get("tiles") === "1"' in html
    # The numbers stay on screen, small, in the header line.
    assert 'id="statline"' in html and "renderStatLine" in html


def test_the_page_holds_its_last_state_when_the_server_goes_away() -> None:
    html = _page()
    assert 'id="reconnect"' in html and "connected(false)" in html
    assert "setInterval(poll, 2000);" in html


def test_watch_follows_continuation_chain(tmp_path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    for directory in (first, second):
        directory.mkdir()
    (first / "manifest.json").write_text(json.dumps({"seed": "X"}), encoding="utf-8")
    (second / "manifest.json").write_text(
        json.dumps({"seed": "X", "continuation_of": str(first)}), encoding="utf-8"
    )

    def transition(ante, chips_before, chips_after):
        state = {
            "ante": ante,
            "phase": "SELECTING_HAND",
            "money": 4,
            "round_no": ante,
            "round": {"chips": chips_before, "hands_left": 3, "discards_left": 3},
            "blinds": [{"kind": "SMALL", "name": "Small Blind", "status": "CURRENT", "score": 300}],
            "jokers": [],
            "consumables": [],
            "hand_stats": [],
        }
        after = dict(state, round=dict(state["round"], chips=chips_after))
        return json.dumps(
            {
                "event": "transition",
                "before": state,
                "action": {"type": "play_cards", "cards": [0]},
                "after": after,
                "source": "coach",
            }
        )

    (first / "trajectory.jsonl").write_text(
        transition(1, 0, 100) + "\n" + transition(1, 100, 250) + "\n"
    )
    (second / "trajectory.jsonl").write_text(transition(2, 0, 900) + "\n")
    summary = summarize(second)
    assert summary["counters"]["decisions"] == 3
    assert summary["peak_hand"] == 900
    assert summary["ante"] == 2


def _segment(root, name, *, continued=None, adjusted=False):
    directory = root / name
    directory.mkdir(parents=True)
    manifest = {"seed": "X"}
    if continued is not None:
        manifest["continuation_of"] = str(continued)
        manifest["resume_adjusted"] = adjusted
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def _play(directory, ante, chips):
    """One transition per call, appended the way the runner writes them."""
    state = {
        "ante": ante,
        "phase": "SELECTING_HAND",
        "money": 4,
        "round": {"chips": 0, "hands_left": 3, "discards_left": 3},
        "blinds": [{"kind": "SMALL", "name": "Small Blind", "status": "CURRENT", "score": 300}],
    }
    after = dict(state, round=dict(state["round"], chips=chips))
    line = json.dumps(
        {
            "event": "transition",
            "before": state,
            "action": {"type": "play_cards"},
            "after": after,
            "source": "coach",
        }
    )
    with (directory / "trajectory.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def test_a_game_root_keeps_the_past_while_the_next_segment_starts(tmp_path):
    """The gap between segments is the moment the dashboard used to go blank."""
    root = tmp_path / "game"
    first = _segment(root, "segment-00")
    _play(first, 1, 100)
    _play(first, 1, 250)
    (first / "result.json").write_text(json.dumps({"status": "error", "seconds": 30}))
    _segment(root, "segment-01", continued=first, adjusted=True)

    waiting = summarize(root)
    assert waiting["status"] == "resuming"
    assert waiting["counters"]["decisions"] == 2 and waiting["peak_hand"] == 250
    assert waiting["result"] is None  # a segment ending is not the game ending
    assert waiting["game"]["segments"] == 2
    assert waiting["game"]["segment"] == "segment-01"
    assert waiting["game"]["resumed"] and waiting["game"]["restored"]

    _play(root / "segment-01", 2, 900)
    live = summarize(root)
    assert live["status"] == "live"
    assert live["counters"]["decisions"] == 3 and live["peak_hand"] == 900
    assert live["ante"] == 2 and live["game"]["segments"] == 2


def test_a_game_root_switches_to_the_newest_segment(tmp_path):
    root = tmp_path / "game"
    first = _segment(root, "segment-00")
    _play(first, 1, 100)
    assert summarize(root)["counters"]["decisions"] == 1

    second = _segment(root, "segment-01", continued=first)
    _play(second, 2, 400)
    assert summarize(root)["counters"]["decisions"] == 2

    _play(second, 2, 500)  # the old tail keeps growing until the next one appears
    third = _segment(root, "segment-02", continued=second)
    _play(third, 3, 700)
    summary = summarize(root)
    assert summary["counters"]["decisions"] == 4 and summary["peak_hand"] == 700
    assert summary["game"]["segments"] == 3 and summary["game"]["segment"] == "segment-02"
    assert summary["ante"] == 3


def test_a_game_root_reads_the_supervisor_summary(tmp_path):
    root = tmp_path / "game"
    first = _segment(root, "segment-00")
    _play(first, 1, 100)
    (root / "summary.json").write_text(
        json.dumps({"status": "running", "segments": 4, "restarts": 3}), encoding="utf-8"
    )
    summary = summarize(root)
    assert summary["game"] == dict(
        segments=4,
        restarts=3,
        supervisor="running",
        segment="segment-00",
        resumed=False,
        restored=False,
        over=False,
    )
    assert summary["status"] == "live"

    (root / "summary.json").write_text(json.dumps({"status": "stopped"}), encoding="utf-8")
    assert summarize(root)["status"] == "finished"


def test_a_game_root_with_nothing_written_yet_is_waiting(tmp_path):
    root = tmp_path / "game"
    _segment(root, "segment-00")
    summary = summarize(root)
    assert summary["status"] == "waiting" and summary["counters"]["decisions"] == 0


def test_a_continuation_directory_without_a_trajectory_is_resuming(tmp_path):
    """Single-directory mode: the runner has made the directory but not the file."""
    first = tmp_path / "first"
    first.mkdir()
    (first / "manifest.json").write_text(json.dumps({"seed": "X"}), encoding="utf-8")
    _play(first, 1, 250)
    second = tmp_path / "second"
    second.mkdir()
    (second / "manifest.json").write_text(
        json.dumps({"seed": "X", "continuation_of": str(first)}), encoding="utf-8"
    )
    summary = summarize(second)
    assert summary["status"] == "resuming"
    assert summary["counters"]["decisions"] == 1 and summary["peak_hand"] == 250
    assert summary["game"]["segments"] == 2 and summary["game"]["resumed"]
