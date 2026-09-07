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


def test_table_a_rows_cover_baselines_and_all_coached_runs():
    table = build_results()["table_a"]
    assert table["title"].endswith("Red Deck / White Stake / all unlocked")
    assert len(table["baselines"]) == 12
    assert len(table["coached"]) == 4
    headless, recorded, low, panel = table["coached"]
    assert [row["seed_panel"] for row in table["coached"]] == [
        "TAF7DNTX",
        "QD3F4XVW",
        "2K9H9HN",
        "D0000000",
    ]
    assert [row["median_ante"] for row in table["coached"]] == [13, 11, 11, 10]
    # QD3F4XVW and 2K9H9HN tie on ante; the newer, cleaner game is listed first.
    assert recorded["recency"] < low["recency"]
    assert recorded["decisions"] == 473
    assert recorded["notes"] == [
        "supervised end to end, one automatic restart, game visible at speed 2, recorded"
    ]
    assert recorded["panel_seed"] is False
    assert panel["seed_panel"] == "D0000000"
    assert panel["display_name"] == "Astra low (gpt-6-astra), seed D0000000"
    assert panel["panel_seed"] is True
    assert headless["panel_seed"] is False and low["panel_seed"] is False
    assert panel["median_ante"] == 10
    assert panel["decisions"] == 315
    assert panel["notes"] == [
        "visible game, endless; on the baseline panel seed; cleared Ante 8, lost at ante 10"
    ]
    assert headless["seed_panel"] == "TAF7DNTX"
    assert headless["display_name"] == "Astra low (gpt-6-astra), seed TAF7DNTX"
    assert headless["games_attempted"] == 1
    assert headless["ante8_clears"] == 1
    assert headless["median_ante"] == 13
    assert headless["decisions"] == 456
    assert "headless" in headless["notes"][0]
    assert low["policy"] == "Astra low (gpt-6-astra)"
    assert low["display_name"] == "Astra low (gpt-6-astra), seed 2K9H9HN"
    assert low["seed_panel"] == "2K9H9HN"
    assert low["median_ante"] == 11
    assert "cleared Ante 8" in low["notes"][0]
    assert "endless" in low["notes"][0]


def test_table_a_reports_coach_calls_per_decision():
    table = build_results()["table_a"]
    headless, recorded, low, panel = table["coached"]
    assert (recorded["coach_requests"], recorded["decisions"]) == (388, 473)
    assert recorded["calls_per_decision"] == "388/473 = 0.82"
    assert (headless["coach_requests"], headless["decisions"]) == (404, 456)
    assert headless["calls_per_decision"] == "404/456 = 0.89"
    assert (low["coach_requests"], low["decisions"]) == (357, 384)
    assert low["calls_per_decision"] == "357/384 = 0.93"
    assert (panel["coach_requests"], panel["decisions"]) == (265, 315)
    assert panel["calls_per_decision"] == "265/315 = 0.84"
    assert {row["calls_per_decision"] for row in table["baselines"]} == {"-"}


def test_table_a_reports_followups_forced_moves_and_stalls():
    headless, recorded, low, panel = build_results()["table_a"]["coached"]
    assert recorded["followups_forced_stalls"] == "50 / 6 / 3"
    assert panel["followups_forced_stalls"] == "34 / 5 / 5"
    assert (panel["followup_actions"], panel["forced_actions"], panel["coach_timeouts"]) == (
        34,
        5,
        5,
    )
    assert headless["followup_actions"] == 31
    assert headless["forced_actions"] == 13
    assert headless["coach_timeouts"] == 15
    assert headless["followups_forced_stalls"] == "31 / 13 / 15"
    assert low["followups_forced_stalls"] == "-"
    assert {row["followups_forced_stalls"] for row in build_results()["table_a"]["baselines"]} == {
        "-"
    }


def test_table_a_footnotes_state_the_caveats():
    footnotes = " ".join(build_results()["table_a"]["footnotes"])
    assert "not win-rate estimates" in footnotes
    assert "headless" in footnotes
    assert "stopped and resumed four times" in footnotes
    assert "No game state or trajectory was edited" in footnotes
    assert "D0000000 is that panel's first seed" in footnotes
    assert (
        "the best heuristic (search-v5) reached ante 6 with a 14,700 peak hand; "
        "the coached run reached ante 10 with 1,840,907" in footnotes
    )
    assert "restarted three times at safe moments" in footnotes
    assert "restored from Balatro's autosave" in footnotes
    assert "QD3F4XVW, 2K9H9HN are seeds outside" in footnotes
    assert "one automatic restart after the mod refused a boss reroll" in footnotes
    assert "0 rejected replies" in footnotes
    assert "blinds at antes 9 and 10 were played twice" in footnotes
    assert "the later, cleaner game is listed first" in footnotes
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


def _block(run: str) -> dict:
    blocks = {block["run"]: block for block in build_results()["table_c"]["blocks"]}
    return blocks[run]


def test_table_c_has_a_block_per_coached_run_headless_first():
    table = build_results()["table_c"]
    assert [block["run"] for block in table["blocks"]] == [
        "astra-low-TAF7DNTX",
        "astra-low-QD3F4XVW",
        "astra-low-2K9H9HN",
        "astra-low-D0000000",
    ]
    assert table["rendered_runs"] == ["astra-low-QD3F4XVW", "astra-low-D0000000"]


def test_table_c_recorded_block():
    block = _block("astra-low-QD3F4XVW")
    assert block["total_transitions"] == 473
    assert block["reported_decisions"] == 473
    assert block["decision_sources"] == {
        "automatic": 33,
        "coach": 384,
        "coach_followup": 50,
        "forced": 6,
    }
    assert block["decisions_per_phase"] == {
        "BLIND_SELECT": 41,
        "PACK": 38,
        "ROUND_EVAL": 33,
        "SELECTING_HAND": 122,
        "SHOP": 239,
    }
    actions = {entry["action"]: entry["count"] for entry in block["decisions_per_action"]}
    assert sum(actions.values()) == 473
    assert actions["reroll_shop"] == 66
    assert actions["play_cards"] == 52
    assert actions["discard_cards"] == 51
    assert actions["buy_shop_card"] == 48
    assert actions["use_consumable"] == 47
    assert actions["cash_out"] == 33
    assert block["shop_visits"] == {
        "visits": 70,
        "actions_total": 239,
        "median_actions_per_visit": 2.0,
        "mean_actions_per_visit": 3.41,
        "max_actions_in_a_visit": 15,
    }
    assert block["coach_calls"]["rejected_responses"] == 0
    assert block["coach_calls"]["hedges_won"] == 16


def test_markdown_writes_only_the_newest_mixes_and_points_at_the_rest():
    results = build_results()
    markdown = render_markdown(results)
    table_c = markdown[markdown.index("## Table C") : markdown.index("## Table D")]
    assert "### astra-low-QD3F4XVW" in table_c
    assert "### astra-low-D0000000" in table_c
    assert "### astra-low-TAF7DNTX" not in table_c
    assert "### astra-low-2K9H9HN" not in table_c
    assert "astra-low-TAF7DNTX (456 decisions)" in table_c
    assert "astra-low-2K9H9HN (383 decisions)" in table_c
    assert "results.json" in table_c
    # Every run is still machine-readable.
    assert len(results["table_c"]["blocks"]) == 4


def test_table_c_panel_seed_block():
    block = _block("astra-low-D0000000")
    assert block["total_transitions"] == 315
    assert block["reported_decisions"] == 315
    assert "exactly" in block["note"]
    assert block["decision_sources"] == {
        "automatic": 19,
        "coach": 257,
        "coach_followup": 34,
        "forced": 5,
    }
    assert block["decisions_per_phase"] == {
        "BLIND_SELECT": 30,
        "PACK": 26,
        "ROUND_EVAL": 19,
        "SELECTING_HAND": 55,
        "SHOP": 185,
    }
    actions = {entry["action"]: entry["count"] for entry in block["decisions_per_action"]}
    assert sum(actions.values()) == 315
    assert actions["reroll_shop"] == 67
    assert actions["buy_shop_card"] == 41
    assert actions["play_cards"] == 27
    assert actions["cash_out"] == 19
    assert block["shop_visits"] == {
        "visits": 43,
        "actions_total": 185,
        "median_actions_per_visit": 3.0,
        "mean_actions_per_visit": 4.3,
        "max_actions_in_a_visit": 13,
    }
    assert block["coach_calls"]["rpc_timeouts"] == 1
    assert block["coach_calls"]["recovered_transitions"] == 1


def test_table_d_ranks_every_player_on_the_panel_seed():
    table = build_results()["table_d"]
    assert table["seed"] == "D0000000"
    rows = table["rows"]
    assert len(rows) == 13
    top = rows[0]
    assert top["kind"] == "coached"
    assert (top["ante_reached"], top["peak_hand_score"]) == (10, 1840907.0)
    by_run = {row["run"]: (row["ante_reached"], row["peak_hand_score"]) for row in rows}
    assert by_run["search-v5-001"] == (6, 14700.0)
    assert by_run["build-first-001"] == (5, 5775.0)
    assert by_run["strategic-001"] == (5, 6162.0)
    assert by_run["strategic-unlocked-001"] == (5, 6162.0)
    assert by_run["search-v6-001"] == (4, 5872.0)
    assert by_run["search-v7-002"] == (4, 4104.0)
    assert by_run["live-validation-001"] == (2, 1158.0)
    for run in (
        "search-stable-001",
        "search-v2-001",
        "search-v3-001",
        "search-v4-001",
        "search-planets-001",
    ):
        assert by_run[run] == (4, 4968.0)
    antes = [row["ante_reached"] for row in rows]
    assert antes == sorted(antes, reverse=True)
    assert table["best_baseline"]["run"] == "search-v5-001"


def test_table_c_headless_decision_sources():
    block = _block("astra-low-TAF7DNTX")
    assert block["seed"] == "TAF7DNTX"
    assert block["total_transitions"] == 456
    assert block["reported_decisions"] == 456
    assert block["decision_sources"] == {
        "automatic": 34,
        "coach": 378,
        "coach_followup": 31,
        "forced": 13,
    }
    assert "exactly" in block["note"]


def test_table_c_headless_phases_actions_and_shop():
    block = _block("astra-low-TAF7DNTX")
    assert block["decisions_per_phase"] == {
        "BLIND_SELECT": 39,
        "PACK": 47,
        "ROUND_EVAL": 34,
        "SELECTING_HAND": 95,
        "SHOP": 241,
    }
    actions = {entry["action"]: entry["count"] for entry in block["decisions_per_action"]}
    assert sum(actions.values()) == 456
    assert actions["reroll_shop"] == 73
    assert actions["use_consumable"] == 45
    assert actions["buy_pack"] == 44
    assert actions["choose_pack_card"] == 44
    assert actions["play_cards"] == 40
    assert actions["buy_shop_card"] == 40
    assert actions["cash_out"] == 34
    assert actions["reorder_hand"] == 1
    by_action = {entry["action"]: entry["sources"] for entry in block["decisions_per_action"]}
    assert by_action["cash_out"] == {"automatic": 34}
    assert set(by_action["play_cards"]) <= {"coach", "coach_followup", "forced"}
    assert block["shop_visits"] == {
        "visits": 78,
        "actions_total": 241,
        "median_actions_per_visit": 2.0,
        "mean_actions_per_visit": 3.09,
        "max_actions_in_a_visit": 13,
    }


def test_table_c_headless_coach_call_health():
    calls = _block("astra-low-TAF7DNTX")["coach_calls"]
    assert calls == {
        "recorded": True,
        "responses": 386,
        "responses_with_hedge_data": 219,
        "hedged": 16,
        "hedges_won": 14,
        "timeouts": 15,
        "rejected_responses": 8,
        "rpc_timeouts": 0,
        "recovered_transitions": 0,
    }


def test_table_c_supervised_block_is_unchanged():
    block = _block("astra-low-2K9H9HN")
    assert block["total_transitions"] == 383
    assert block["reported_decisions"] == 384
    assert "errored action" in block["note"]
    assert block["decision_sources"] == {"automatic": 30, "coach": 353}
    assert block["decisions_per_phase"] == {
        "BLIND_SELECT": 32,
        "PACK": 44,
        "ROUND_EVAL": 30,
        "SELECTING_HAND": 70,
        "SHOP": 207,
    }
    assert block["shop_visits"] == {
        "visits": 65,
        "actions_total": 207,
        "median_actions_per_visit": 2.0,
        "mean_actions_per_visit": 3.18,
        "max_actions_in_a_visit": 12,
    }
    assert not block["coach_calls"]["recorded"]


def test_segment_continuity_is_reported_for_both_runs():
    entries = build_results()["segment_continuity"]
    assert [entry["run"] for entry in entries] == [
        "astra-low-TAF7DNTX",
        "astra-low-QD3F4XVW",
        "astra-low-2K9H9HN",
        "astra-low-D0000000",
    ]
    headless = entries[0]["segments"]
    assert headless[0]["ante_start"] == 1
    assert headless[-1]["ante_end"] == 13


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
    assert len(built_in_coached_rows()) == 4
