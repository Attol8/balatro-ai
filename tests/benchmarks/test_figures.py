"""Figure rendering is optional: the tables never need matplotlib."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("matplotlib")

from benchmarks.figures import render_all, score_vs_requirement  # noqa: E402
from benchmarks.trajectories import (  # noqa: E402
    load_astra_low,
    load_astra_low_headless,
    load_astra_low_panel_seed,
    load_astra_low_recorded,
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
        (load_astra_low_recorded(), "Astra low, seed QD3F4XVW"),
        (load_astra_low(), "Astra low, seed 2K9H9HN"),
        (load_astra_low_panel_seed(), "Astra low, seed D0000000"),
    ]
    path = score_vs_requirement(runs, tmp_path / "two-panels.svg")
    body = path.read_text(encoding="utf-8")
    assert "TAF7DNTX" in body
    assert "QD3F4XVW" in body
    assert "D0000000" in body
    assert "2K9H9HN" in body
    assert "Ante 13 loss (endless)" in body
    assert "Ante 10 loss (endless)" in body
    assert body.count("Ante 11 loss (endless)") == 2
    assert "Ante 11 loss (endless)" in body
    single = score_vs_requirement(runs[:1], tmp_path / "one-panel.svg")
    assert "2K9H9HN" not in single.read_text(encoding="utf-8")


def test_headline_strip_marks_the_panel_seed_star(tmp_path: Path):
    body = (render_all(tmp_path)[0]).read_text(encoding="utf-8")
    assert "4 coached games, 1 on a panel seed" in body
    assert "Coached game on a panel seed" in body
    assert "n=1, endless after win" in body
