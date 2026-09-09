import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "review_recording", Path(__file__).parents[1] / "scripts/review-recording.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_review_aligns_segments_and_escapes_embedded_trace(tmp_path):
    (tmp_path / "video-clock.json").write_text('{"capture_started_at":100}')
    (tmp_path / "gameplay.mp4").touch()
    first, second = tmp_path / "first.jsonl", tmp_path / "second.jsonl"
    first.write_text(
        json.dumps(
            dict(
                event="coach_response",
                recorded_at=105,
                response={"explanation": "</script><img onerror=alert(1)>"},
            )
        )
        + "\n"
    )
    second.write_text(json.dumps(dict(event="rpc_attempt", recorded_at=103)) + "\n")
    html = module.review(tmp_path, [first, second]).read_text()
    payload = html.split('<script id="data" type="application/json">')[1].split("</script>")[0]
    data = json.loads(payload)
    assert [row["time"] for row in data] == [3, 5]
    assert "<img" not in payload and "</script>" not in payload
    assert data[1]["data"]["response"]["explanation"] == "</script><img onerror=alert(1)>"


@pytest.mark.parametrize("timestamp", [None, True, "100", float("nan")])
def test_review_refuses_missing_or_invalid_historical_timing(tmp_path, timestamp):
    (tmp_path / "video-clock.json").write_text('{"capture_started_at":100}')
    (tmp_path / "gameplay.mp4").touch()
    trace = tmp_path / "trajectory.jsonl"
    trace.write_text(json.dumps(dict(event="transition", recorded_at=timestamp)))
    with pytest.raises(ValueError, match="recorded_at"):
        module.review(tmp_path, [trace])
