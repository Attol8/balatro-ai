"""Figure rendering is optional: the tables never need matplotlib."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("matplotlib")

from benchmarks.figures import render_all  # noqa: E402

EXPECTED = {
    "ante-reached-by-policy.svg",
    "score-vs-requirement.svg",
    "hand-score-parity.svg",
}


def test_render_all_writes_three_svgs(tmp_path: Path):
    paths = render_all(tmp_path)
    assert {path.name for path in paths} == EXPECTED
    for path in paths:
        assert path.is_file()
        head = path.read_text(encoding="utf-8")[:400]
        assert "<svg" in head
        assert "Date" not in head


def test_rendered_svgs_are_deterministic(tmp_path: Path):
    first = {path.name: path.read_bytes() for path in render_all(tmp_path / "a")}
    second = {path.name: path.read_bytes() for path in render_all(tmp_path / "b")}
    assert first == second
