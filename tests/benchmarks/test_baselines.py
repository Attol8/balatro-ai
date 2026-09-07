"""The recorded baseline panels must keep reporting exactly what is on disk."""

from __future__ import annotations

from benchmarks import FULL_PANEL_SIZE
from benchmarks.baselines import load_panels

EXPECTED_ANTE8_CLEARS = {
    "strategic-unlocked-001": 0,
    "build-first-001": 1,
    "search-planets-001": 1,
    "search-stable-001": 1,
    "search-v2-001": 1,
    "search-v3-001": 2,
    "search-v4-001": 3,
    "search-v5-001": 3,
    "search-v6-001": 3,
    "search-v7-002": 2,
    "live-validation-001": 0,
    "strategic-001": 0,
}

FULL_PANELS = {
    "strategic-unlocked-001",
    "build-first-001",
    "search-planets-001",
    "search-stable-001",
    "search-v2-001",
    "search-v3-001",
    "search-v4-001",
    "search-v5-001",
    "search-v6-001",
    "search-v7-002",
}

EXPECTED_REACHED_ANTE8 = {
    "build-first-001": 3,
    "live-validation-001": 0,
    "search-planets-001": 4,
    "search-stable-001": 4,
    "search-v2-001": 2,
    "search-v3-001": 5,
    "search-v4-001": 7,
    "search-v5-001": 6,
    "search-v6-001": 7,
    "search-v7-002": 5,
    "strategic-001": 0,
    "strategic-unlocked-001": 0,
}


def test_twelve_panels_are_present():
    panels = load_panels()
    assert len(panels) == 12
    assert {panel.run_dir for panel in panels} == set(EXPECTED_ANTE8_CLEARS)


def test_ante8_clears_match_the_recorded_summaries():
    for panel in load_panels():
        expected = EXPECTED_ANTE8_CLEARS[panel.run_dir]
        assert panel.ante8_clears == expected, panel.run_dir
        assert panel.reported_ante_8_wins == expected, panel.run_dir


def test_reached_ante8_or_more():
    for panel in load_panels():
        assert panel.reached_ante8_or_more == EXPECTED_REACHED_ANTE8[panel.run_dir], panel.run_dir
        assert panel.reached_ante8_or_more >= panel.ante8_clears


def test_full_panels_are_twenty_games_on_the_standard_seeds():
    for panel in load_panels():
        if panel.run_dir not in FULL_PANELS:
            continue
        assert panel.requested == FULL_PANEL_SIZE
        assert panel.attempted == FULL_PANEL_SIZE
        assert panel.completed == FULL_PANEL_SIZE
        assert panel.seeds_label == "D0000000-D0000019"
        assert not panel.partial


def test_partial_panels():
    panels = {panel.run_dir: panel for panel in load_panels()}
    live = panels["live-validation-001"]
    assert live.policy == "baseline-v1"
    assert live.requested == FULL_PANEL_SIZE
    assert live.attempted == 11
    assert live.completed == 10
    assert live.partial
    assert any("errored" in note for note in live.notes)

    strategic = panels["strategic-001"]
    assert strategic.attempted == 10
    assert strategic.completed == 10
    assert strategic.partial


def test_errors_are_attempted_but_not_completed():
    panels = {panel.run_dir: panel for panel in load_panels()}
    live = panels["live-validation-001"]
    errored = [game for game in live.games if game.status == "error"]
    assert len(errored) == 1
    assert live.attempted - live.completed == len(errored)
    assert all(game.completed for game in live.games if game.status != "error")


def test_every_panel_is_red_deck_white_stake():
    for panel in load_panels():
        assert panel.deck == "RED", panel.run_dir
        assert panel.stake == "WHITE", panel.run_dir
        assert panel.git_revision


def test_only_the_career_panel_is_not_all_unlocked():
    profiles = {panel.run_dir: panel.profile_mode for panel in load_panels()}
    assert profiles.pop("strategic-001") == "career"
    assert set(profiles.values()) == {"all_unlocked"}


def test_panels_are_sorted_by_clears_then_median_ante():
    keys = [(-panel.ante8_clears, -panel.median_ante) for panel in load_panels()]
    assert keys == sorted(keys)
