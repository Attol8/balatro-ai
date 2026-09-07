"""The rendered tables must be traceable to the evidence and byte-stable."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks import EVIDENCE_ROOT
from benchmarks.tables import (
    build_results,
    built_in_coached_rows,
    load_extra_runs,
    render_json,
    render_markdown,
    write_results,
)


def test_table_a_rows_cover_baselines_and_coached_runs():
    table = build_results()["table_a"]
    assert table["title"].endswith("Red Deck / White Stake / all unlocked")
    assert len(table["baselines"]) == 12
    assert len(table["coached"]) == 2
    high, low = table["coached"]
    assert high["policy"] == "Astra high (gpt-6-astra)"
    assert high["seed_panel"] == "D0001000"
    assert high["games_attempted"] == 1
    assert high["ante8_clears"] == 1
    assert high["median_ante"] == 9
    assert high["decisions"] == 203
    assert low["policy"] == "Astra low (gpt-6-astra)"
    assert low["seed_panel"] == "2K9H9HN"
    assert low["median_ante"] == 11
    assert "cleared Ante 8" in low["notes"][0]
    assert "endless" in low["notes"][0]


def test_table_a_footnotes_state_the_caveats():
    footnotes = " ".join(build_results()["table_a"]["footnotes"])
    assert "not win-rate estimates" in footnotes
    assert "5 of its 203 decisions" in footnotes
    assert "search-v6" in footnotes
    assert "23 automatic cashouts" in footnotes
    assert "supervised" in footnotes
    assert "adapter fixes" in footnotes
    assert "reviewed continuations" in footnotes


def test_table_b_matches_the_scoring_audit():
    audit = json.loads((EVIDENCE_ROOT / "first-win" / "scoring-audit.json").read_text())
    high, low = build_results()["table_b"]["rows"]
    assert high["plays_scored"] == audit["play_actions_scored"] == 54
    assert high["prediction_mismatches"] == 0
    assert high["max_abs_prediction_difference"] == 0.0
    assert high["sub_chip_floor_differences_vs_game"] == 18
    assert high["max_abs_difference_vs_game"] == 0.875
    assert high["derivation"] == "computed"
    cross = high["cross_check"]
    assert cross["plays_in_trajectory"] == 54
    assert cross["plays_differing_from_prediction"] == 18
    assert cross["max_abs_difference"] == 0.875

    assert low["derivation"] == "cited"
    assert low["source"] == "docs/trajectory-review.md"
    assert low["exact_after_public_correction"] == 46
    assert low["plays_with_visible_joker_identities"] == 47
    assert low["plays_scored"] == 49
    assert low["cross_check"]["plays_with_shortlist_estimate"] == 27


def test_table_c_decision_sources_and_per_ante_counts():
    table = build_results()["table_c"]
    assert table["total_decisions"] == 203
    assert table["decision_sources"] == {
        "automatic": 23,
        "coach": 175,
        "numerical_delegate": 5,
    }
    assert table["decisions_per_ante"] == {
        "1": 15,
        "2": 20,
        "3": 35,
        "4": 33,
        "5": 30,
        "6": 29,
        "7": 24,
        "8": 17,
    }
    assert sum(table["decisions_per_ante"].values()) == 203


def test_results_json_round_trips():
    results = build_results()
    text = render_json(results)
    assert text.endswith("\n")
    assert json.loads(text) == json.loads(json.dumps(results))
    assert text == render_json(json.loads(text))


def test_rendering_is_deterministic():
    first, second = build_results(), build_results()
    assert render_json(first) == render_json(second)
    assert render_markdown(first) == render_markdown(second)


def test_markdown_mentions_every_policy():
    results = build_results()
    markdown = render_markdown(results)
    for row in results["table_a"]["baselines"]:
        assert row["display_name"] in markdown
    assert "Table A" in markdown and "Table B" in markdown and "Table C" in markdown


def test_write_results_is_byte_identical_across_runs(tmp_path: Path):
    results = build_results()
    first = {path.name: path.read_bytes() for path in write_results(results, tmp_path)}
    second = {path.name: path.read_bytes() for path in write_results(build_results(), tmp_path)}
    assert first == second
    assert set(first) == {"results.json", "results.md"}


def test_extra_runs_are_grouped_by_model_and_effort(tmp_path: Path):
    for index, (effort, won, ante) in enumerate([("low", True, 9), ("low", False, 5)]):
        run_dir = tmp_path / f"run-{index}"
        run_dir.mkdir()
        (run_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "requested_model": "gpt-6-astra",
                    "requested_reasoning_effort": effort,
                    "seed": f"SEED{index}",
                }
            )
        )
        (run_dir / "result.json").write_text(
            json.dumps(
                {
                    "status": "won" if won else "lost",
                    "won": won,
                    "ante_reached": ante,
                    "decisions": 10 + index,
                    "coach_requests": 5 + index,
                    "seconds": 1.5,
                    "peak_hand_score": 100 * (index + 1),
                }
            )
        )
    rows = load_extra_runs(sorted(tmp_path.iterdir()))
    assert len(rows) == 1
    row = rows[0]
    assert row.label == "gpt-6-astra (low)"
    assert row.games == 2
    assert row.ante8_clears == 1
    assert row.seeds == ["SEED0", "SEED1"]
    assert row.decisions == 21
    assert row.peak_hand_score == 200.0

    results = build_results(extra_runs=sorted(tmp_path.iterdir()))
    labels = [entry["policy"] for entry in results["table_a"]["coached"]]
    assert labels[-1] == "gpt-6-astra (low)"
    assert len(built_in_coached_rows()) == 2
