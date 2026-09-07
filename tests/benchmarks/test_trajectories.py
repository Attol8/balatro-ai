"""Both trajectory schemas must reduce to the same records with the same totals."""

from __future__ import annotations

import itertools

from benchmarks import EVIDENCE_ROOT
from benchmarks.trajectories import (
    ASTRA_LOW_HEADLESS,
    ASTRA_LOW_PANEL_SEED,
    ASTRA_LOW_RECORDED,
    SOURCE_AUTOMATIC,
    SOURCE_COACH,
    SOURCE_DELEGATE,
    Trajectory,
    astra_low_segments,
    load_astra_low,
    load_astra_low_headless,
    load_astra_low_panel_seed,
    load_astra_low_recorded,
    load_first_win,
    load_segmented_run,
    run_segments,
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


EXPECTED_HEADLESS_BOUNDS = [
    ("00", 1, 2),
    ("01", 2, 5),
    ("02", 5, 6),
    ("03", 6, 6),
    ("04", 6, 13),
]


def test_headless_run_loads_every_segment():
    segments = run_segments(EVIDENCE_ROOT / ASTRA_LOW_HEADLESS)
    assert [entry["segment"] for entry in segments] == ["00", "01", "02", "03", "04"]
    assert all(entry["part_of_completed_game"] for entry in segments)
    assert all(entry["sha256_uncompressed"]["trajectory.jsonl"] for entry in segments)


def test_headless_run_has_456_transitions_and_the_new_sources():
    run = load_astra_low_headless()
    assert run.run_id == ASTRA_LOW_HEADLESS
    assert run.seed == "TAF7DNTX"
    assert len(run.decisions) == 456
    assert run.source_counts() == {
        "automatic": 34,
        "coach": 378,
        "coach_followup": 31,
        "forced": 13,
    }
    assert sum(run.source_counts().values()) == 456


def test_headless_segments_are_contiguous_from_ante_one_to_thirteen():
    run = load_astra_low_headless()
    bounds = segment_ante_bounds(run)
    assert bounds == EXPECTED_HEADLESS_BOUNDS
    for (_, _, end), (_, start, _) in itertools.pairwise(bounds):
        assert end == start
    antes = run.ante_series()
    assert antes[0] == 1
    assert all(before <= after for before, after in itertools.pairwise(antes))
    assert run.decisions[-1].ante_after == 13


def test_headless_coach_call_health_comes_from_the_events():
    calls = load_astra_low_headless().coach_calls
    assert calls.recorded
    assert calls.responses == 386
    assert calls.responses_with_hedge_data == 219
    assert calls.hedged == 16
    assert calls.hedges_won == 14
    assert calls.timeouts == 15
    assert calls.rejected_responses == 8
    assert not load_astra_low().coach_calls.recorded


def test_headless_blind_requirements_stay_exact_integers():
    run = load_astra_low_headless()
    blinds = run.blind_series()
    assert len(blinds) == 35
    assert all(isinstance(blind.requirement, int) for blind in blinds)
    # The Ante 1 small blind was skipped for an Investment Tag.
    assert (blinds[0].ante, blinds[0].blind) == (1, "BIG")
    by_key = {(blind.ante, blind.blind): blind for blind in blinds}
    ante8_boss = by_key[(8, "BOSS")]
    assert ante8_boss.requirement == 100_000
    assert ante8_boss.best_hand_score == 180442.0
    assert ante8_boss.cleared
    final = blinds[-1]
    assert (final.ante, final.blind, final.requirement) == (13, "BOSS", 94_000_000_000)
    assert not final.cleared
    assert max(blind.best_hand_score for blind in blinds) == 134231931235.0
    _assert_requirements_increase(run)


def test_load_segmented_run_works_on_any_run_directory():
    direct = load_segmented_run(EVIDENCE_ROOT / ASTRA_LOW_HEADLESS)
    assert direct.decisions == load_astra_low_headless().decisions


EXPECTED_PANEL_SEED_BOUNDS = [("00", 1, 7), ("01", 7, 9), ("02", 9, 10), ("03", 10, 10)]


def test_panel_seed_run_has_315_transitions():
    run = load_astra_low_panel_seed()
    assert run.run_id == ASTRA_LOW_PANEL_SEED
    assert run.seed == "D0000000"
    assert len(run.decisions) == 315
    assert run.source_counts() == {
        "automatic": 19,
        "coach": 257,
        "coach_followup": 34,
        "forced": 5,
    }
    assert sum(run.source_counts().values()) == 315


def test_panel_seed_segments_are_contiguous_and_include_the_reconstructed_one():
    segments = run_segments(EVIDENCE_ROOT / ASTRA_LOW_PANEL_SEED)
    assert [entry["segment"] for entry in segments] == ["00", "01", "02", "03"]
    reconstructed = [entry["segment"] for entry in segments if entry["reconstructed_result"]]
    assert reconstructed == ["02"]
    bounds = segment_ante_bounds(load_astra_low_panel_seed())
    assert bounds == EXPECTED_PANEL_SEED_BOUNDS
    for (_, _, end), (_, start, _) in itertools.pairwise(bounds):
        assert end == start


def test_panel_seed_run_records_the_recovered_game_reply():
    calls = load_astra_low_panel_seed().coach_calls
    assert calls.recorded
    assert calls.responses == 259
    assert calls.hedged == 30
    assert calls.hedges_won == 24
    assert calls.timeouts == 5
    assert calls.rejected_responses == 0
    assert calls.rpc_timeouts == 1
    assert calls.recovered_transitions == 1


def test_panel_seed_blind_requirements_stay_below_ten_million():
    run = load_astra_low_panel_seed()
    blinds = run.blind_series()
    assert len(blinds) == 20
    assert all(isinstance(blind.requirement, int) for blind in blinds)
    assert max(blind.requirement for blind in blinds) == 1_120_000
    final = blinds[-1]
    assert (final.ante, final.blind, final.requirement) == (10, "BOSS", 1_120_000)
    assert final.hands_played == 4
    assert final.total_chips_scored == 232367.0
    assert not final.cleared
    assert max(blind.best_hand_score for blind in blinds) == 1840907.0
    _assert_requirements_increase(run)


def test_recorded_run_has_473_transitions():
    run = load_astra_low_recorded()
    assert run.run_id == ASTRA_LOW_RECORDED
    assert run.seed == "QD3F4XVW"
    assert len(run.decisions) == 473
    assert run.source_counts() == {
        "automatic": 33,
        "coach": 384,
        "coach_followup": 50,
        "forced": 6,
    }
    assert sum(run.source_counts().values()) == 473
    assert segment_ante_bounds(run) == [("00", 1, 11), ("01", 11, 11)]


def test_recorded_run_ante_series_is_not_monotone_but_ends_at_eleven():
    run = load_astra_low_recorded()
    antes = run.ante_series()
    assert antes[0] == 1
    assert max(antes) == 11
    assert run.decisions[-1].ante_after == 11
    assert not all(before <= after for before, after in itertools.pairwise(antes))
    # Every drop is exactly one ante and follows an ante-lowering voucher purchase.
    drops = run.ante_decreases()
    assert len(drops) == 2
    for record in drops:
        assert record.ante - record.ante_after == 1
        assert record.action == "buy_voucher"


def test_recorded_run_blind_series_keeps_replayed_antes_apart():
    run = load_astra_low_recorded()
    blinds = run.blind_series()
    assert len(blinds) == 34
    keys = [(blind.ante, blind.blind) for blind in blinds]
    # Hieroglyph and Petroglyph send the run back through antes 9 and 10.
    assert keys.count((9, "BOSS")) == 2
    assert keys.count((10, "BOSS")) == 2
    assert len(set(keys)) < len(keys)
    final = blinds[-1]
    assert (final.ante, final.blind, final.requirement) == (11, "BOSS", 14_400_000)
    assert final.hands_played == 5
    assert final.total_chips_scored == 7394177.0
    assert not final.cleared
    assert max(blind.best_hand_score for blind in blinds) == 7052918.0


def test_recorded_run_had_no_rejected_replies():
    calls = load_astra_low_recorded().coach_calls
    assert calls.recorded
    assert calls.responses == 385
    assert calls.hedged == 23
    assert calls.hedges_won == 16
    assert calls.timeouts == 3
    assert calls.rejected_responses == 0
    assert calls.rpc_timeouts == 0
