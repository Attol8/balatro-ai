"""The rendered tables must be traceable to the evidence and byte-stable."""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.tables import (
    build_results,
    built_in_coached_rows,
    load_extra_runs,
    render_json,
    render_markdown,
    write_results,
)


def test_table_a_rows_cover_baselines_and_the_coached_run():
    table = build_results()["table_a"]
    assert table["title"].endswith("Red Deck / White Stake / all unlocked")
    assert len(table["baselines"]) == 12
    assert len(table["coached"]) == 1
    (low,) = table["coached"]
    assert low["policy"] == "Astra low (gpt-6-astra)"
    assert low["games_attempted"] == 1
    assert low["ante8_clears"] == 1
    assert low["seed_panel"] == "2K9H9HN"
    assert low["median_ante"] == 11
    assert "cleared Ante 8" in low["notes"][0]
    assert "endless" in low["notes"][0]


def test_table_a_reports_coach_calls_per_decision():
    table = build_results()["table_a"]
    (low,) = table["coached"]
    assert low["coach_requests"] == 357
    assert low["decisions"] == 384
    assert low["calls_per_decision"] == "357/384 = 0.93"
    assert {row["calls_per_decision"] for row in table["baselines"]} == {"-"}


def test_table_a_footnotes_state_the_caveats():
    footnotes = " ".join(build_results()["table_a"]["footnotes"])
    assert "not a win-rate estimate" in footnotes
    assert "outside the D0000000-D0000019 baseline panel" in footnotes
    assert "supervised" in footnotes
    assert "adapter fixes" in footnotes
    assert "reviewed continuations" in footnotes


def test_table_b_reports_only_the_low_run():
    rows = build_results()["table_b"]["rows"]
    assert len(rows) == 1
    (low,) = rows
    assert low["run"] == "astra-low-2K9H9HN"
    assert low["derivation"] == "cited"
    assert low["source"] == "docs/trajectory-review.md"
    assert low["exact_after_public_correction"] == 46
    assert low["plays_with_visible_joker_identities"] == 47
    assert low["plays_scored"] == 49
    assert low["cross_check"]["plays_with_shortlist_estimate"] == 27
    assert low["cross_check"]["shortlist_estimates_within_1_chip"] == 15


def test_table_c_decision_mix_in_the_low_run():
    table = build_results()["table_c"]
    assert table["title"] == "Decision mix in the Astra-low run"
    assert table["run"] == "astra-low-2K9H9HN"
    assert table["total_transitions"] == 383
    assert table["reported_decisions"] == 384
    assert "errored action" in table["note"]
    assert table["decision_sources"] == {"automatic": 30, "coach": 353}
    assert sum(table["decision_sources"].values()) == table["total_transitions"]


def test_table_c_decisions_per_phase():
    table = build_results()["table_c"]
    assert table["decisions_per_phase"] == {
        "BLIND_SELECT": 32,
        "PACK": 44,
        "ROUND_EVAL": 30,
        "SELECTING_HAND": 70,
        "SHOP": 207,
    }
    assert sum(table["decisions_per_phase"].values()) == 383


def test_table_c_decisions_per_action_type():
    table = build_results()["table_c"]
    actions = {entry["action"]: entry["count"] for entry in table["decisions_per_action"]}
    assert actions == {
        "reroll_shop": 72,
        "play_cards": 49,
        "buy_pack": 35,
        "choose_pack_card": 33,
        "use_consumable": 31,
        "select_blind": 30,
        "cash_out": 30,
        "leave_shop": 30,
        "buy_shop_card": 27,
        "reorder_jokers": 11,
        "skip_pack": 9,
        "discard_cards": 8,
        "sell_joker": 8,
        "buy_voucher": 5,
        "sell_consumable": 3,
        "reroll_boss": 1,
        "skip_blind": 1,
    }
    assert sum(actions.values()) == 383
    by_action = {entry["action"]: entry["sources"] for entry in table["decisions_per_action"]}
    assert by_action["cash_out"] == {"automatic": 30}
    assert by_action["play_cards"] == {"coach": 49}
    counts = [entry["count"] for entry in table["decisions_per_action"]]
    assert counts == sorted(counts, reverse=True)


def test_table_c_shop_visits():
    shop = build_results()["table_c"]["shop_visits"]
    assert shop == {
        "visits": 65,
        "actions_total": 207,
        "median_actions_per_visit": 2.0,
        "mean_actions_per_visit": 3.18,
        "max_actions_in_a_visit": 12,
    }


def test_results_never_mention_the_unpublished_run():
    text = render_json(build_results())
    assert "D0001000" not in text
    assert "first-win" not in text
    markdown = render_markdown(build_results())
    assert "D0001000" not in markdown


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
    assert row.calls_per_decision == "11/21 = 0.52"
    assert len(built_in_coached_rows()) == 1
