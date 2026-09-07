"""Both trajectory schemas must reduce to the same records with the same totals."""

from __future__ import annotations

import itertools

from benchmarks.trajectories import (
    SOURCE_AUTOMATIC,
    SOURCE_COACH,
    SOURCE_DELEGATE,
    Trajectory,
    astra_low_segments,
    load_astra_low,
    load_first_win,
    segment_ante_bounds,
)

EXPECTED_DECISIONS_PER_ANTE = {1: 15, 2: 20, 3: 35, 4: 33, 5: 30, 6: 29, 7: 24, 8: 17}
EXPECTED_SEGMENT_BOUNDS = [
    ("00", 1, 2),
    ("01", 2, 3),
    ("02", 3, 4),
    ("03", 4, 6),
    ("04", 6, 6),
    ("05", 6, 9),
    ("06", 9, 11),
]
BLIND_ORDER = {"SMALL": 0, "BIG": 1, "BOSS": 2}


def _assert_requirements_increase(trajectory: Trajectory) -> None:
    blinds = trajectory.blind_series()
    by_ante: dict[int, list] = {}
    for blind in blinds:
        by_ante.setdefault(blind.ante, []).append(blind)
    for ante, played in by_ante.items():
        order = [BLIND_ORDER[blind.blind] for blind in played]
        assert order == sorted(order), ante
        requirements = [blind.requirement for blind in played]
        assert requirements == sorted(set(requirements)), ante
    smalls = [blind.requirement for blind in blinds if blind.blind == "SMALL"]
    assert smalls == sorted(set(smalls))


def test_first_win_decision_split():
    high = load_first_win()
    assert high.seed == "D0001000"
    assert len(high.decisions) == 203
    sources = high.source_counts()
    assert sources == {
        SOURCE_AUTOMATIC: 23,
        SOURCE_COACH: 175,
        SOURCE_DELEGATE: 5,
    }
    assert sources[SOURCE_COACH] + sources[SOURCE_DELEGATE] + sources[SOURCE_AUTOMATIC] == 203


def test_first_win_decisions_per_ante():
    assert load_first_win().decisions_per_ante() == EXPECTED_DECISIONS_PER_ANTE
    assert sum(EXPECTED_DECISIONS_PER_ANTE.values()) == 203


def test_first_win_plays_carry_both_scores():
    plays = load_first_win().plays
    assert len(plays) == 54
    assert all(play.predicted_score is not None for play in plays)
    assert all(play.observed_score is not None for play in plays)
    assert all(not play.predicted_is_estimate for play in plays)
    differences = [abs((play.observed_score or 0) - (play.predicted_score or 0)) for play in plays]
    assert sum(1 for diff in differences if diff > 0) == 18
    assert max(differences) == 0.875


def test_first_win_blind_series():
    high = load_first_win()
    blinds = high.blind_series()
    assert len(blinds) == 24
    assert blinds[0].ante == 1 and blinds[0].requirement == 300
    final = blinds[-1]
    assert (final.ante, final.blind, final.requirement) == (8, "BOSS", 300000)
    assert final.total_chips_scored == 415042.0
    assert max(blind.best_hand_score for blind in blinds) == 446698.0
    _assert_requirements_increase(high)


def test_first_win_ante_series_is_non_decreasing():
    antes = load_first_win().ante_series()
    assert antes[0] == 1
    assert antes[-1] == 8
    assert all(before <= after for before, after in itertools.pairwise(antes))
    assert segment_ante_bounds(load_first_win()) == [("first-win", 1, 9)]


def test_astra_low_uses_only_completed_game_segments():
    segments = astra_low_segments()
    assert [entry["segment"] for entry in segments] == [
        "00",
        "01",
        "02",
        "03",
        "04",
        "05",
        "06",
    ]
    assert all("interrupted" not in entry["segment"] for entry in segments)
    assert all(entry["sha256_uncompressed"]["trajectory.jsonl"] for entry in segments)


def test_astra_low_segments_are_contiguous():
    low = load_astra_low()
    bounds = segment_ante_bounds(low)
    assert bounds == EXPECTED_SEGMENT_BOUNDS
    for (_, _, end), (_, start, _) in itertools.pairwise(bounds):
        assert end == start


def test_astra_low_ante_series_runs_from_one_to_eleven():
    low = load_astra_low()
    antes = low.ante_series()
    assert antes[0] == 1
    assert low.decisions[-1].ante_after == 11
    assert all(before <= after for before, after in itertools.pairwise(antes))
    assert max(antes) == 11


def test_astra_low_plays_and_blinds():
    low = load_astra_low()
    assert low.seed == "2K9H9HN"
    assert len(low.decisions) == 383
    assert low.source_counts() == {"automatic": 30, "coach": 353}
    plays = low.plays
    assert len(plays) == 49
    assert all(play.observed_score is not None for play in plays)
    estimated = [play for play in plays if play.predicted_is_estimate]
    assert len(estimated) == 27
    blinds = low.blind_series()
    assert len(blinds) == 31
    final = blinds[-1]
    assert (final.ante, final.blind, final.requirement) == (11, "BIG", 10800000)
    assert final.best_hand_score == 1239454.0
    assert final.total_chips_scored == 3350514.0
    assert not final.cleared
    _assert_requirements_increase(low)
