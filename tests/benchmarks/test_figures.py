"""Figure rendering is optional: the tables never need matplotlib."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("matplotlib")

from benchmarks.figures import render_all, score_vs_requirement  # noqa: E402
from benchmarks.trajectories import (  # noqa: E402
    load_astra_low,
    load_astra_low_headless,
)

EXPECTED = {
    "ante-reached-by-policy.svg",
    "score-vs-requirement.svg",
}


def test_render_all_writes_two_svgs(tmp_path: Path):
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


def test_score_vs_requirement_draws_one_panel_per_run(tmp_path: Path):
    runs = [
        (load_astra_low_headless(), "Astra low, seed TAF7DNTX"),
        (load_astra_low(), "Astra low, seed 2K9H9HN"),
    ]
    path = score_vs_requirement(runs, tmp_path / "two-panels.svg")
    body = path.read_text(encoding="utf-8")
    assert "TAF7DNTX" in body
    assert "2K9H9HN" in body
    assert "Ante 13 loss (endless)" in body
    assert "Ante 11 loss (endless)" in body
    single = score_vs_requirement(runs[:1], tmp_path / "one-panel.svg")
    assert "2K9H9HN" not in single.read_text(encoding="utf-8")
