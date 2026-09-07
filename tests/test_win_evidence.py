"""Offline parity check against the compact first winning trajectory."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from balatro_ai.game.actions import PlayCards, action_from_data
from balatro_ai.game.codec import public_observation_from_data
from balatro_ai.game.history import HistoryStep, enrich_runtime
from balatro_ai.game.scoring import score_play


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence" / "first-win"


def _load_rows() -> list[dict[str, object]]:
    with gzip.open(EVIDENCE / "trajectory.jsonl.gz", "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def test_first_win_retains_public_scoring_and_result_evidence() -> None:
    rows = _load_rows()
    decisions = {row["index"]: row for row in rows if row["event"] == "decision"}
    transitions = {row["index"]: row for row in rows if row["event"] == "transition"}
    audit = json.loads((EVIDENCE / "scoring-audit.json").read_text())
    result = json.loads((EVIDENCE / "result.json").read_text())

    history: list[HistoryStep] = []
    prediction_differences: list[float] = []
    actual_differences: list[tuple[int, float]] = []
    source_counts = {"coach": 0, "numerical_delegate": 0, "automatic": 0}

    for index in sorted(decisions):
        decision = decisions[index]
        transition = transitions[index]
        before = public_observation_from_data(decision["observation"]["public_solver"])
        after = public_observation_from_data(transition["observation"]["public_solver"])
        action = action_from_data(decision["action"]["public_action"])
        diagnostics = decision["diagnostics"]

        if "coach_request_id" in diagnostics:
            source_counts["coach"] += 1
        elif diagnostics.get("coach_automatic"):
            source_counts["automatic"] += 1
        else:
            assert diagnostics.get("coach_delegated") is True
            source_counts["numerical_delegate"] += 1

        if isinstance(action, PlayCards):
            score, _ = score_play(enrich_runtime(before, tuple(history)), action.cards)
            prediction_differences.append(abs(float(score) - decision["predicted_score"]))
            observed = transition["observed_score"]
            if observed is not None and float(score) != observed:
                actual_differences.append((index, abs(float(score) - observed)))

        history.append(HistoryStep(before, action, after))

    assert len(decisions) == len(transitions) == audit["decisions"] == 203
    assert source_counts == audit["action_sources"] == {
        "coach": 175,
        "numerical_delegate": 5,
        "automatic": 23,
    }
    assert len(prediction_differences) == audit["play_actions_scored"] == 54
    assert max(prediction_differences) == audit["recorded_prediction_comparison"]["max_absolute_difference"] == 0
    assert sum(difference != 0 for difference in prediction_differences) == 0
    assert [index for index, _ in actual_differences] == audit["actual_game_comparison"]["discrepancy_indices"]
    assert len(actual_differences) == audit["actual_game_comparison"]["discrepancy_count"] == 18
    assert max(difference for _, difference in actual_differences) == audit["actual_game_comparison"]["max_absolute_difference"] == 0.875
    assert result["won"] is audit["won"] is True
    assert result["status"] == audit["status"] == "won"
    assert result["reason"] == audit["result_reason"] == "ante_8_cleared"
    assert result["ante_reached"] == audit["ante_reached"] == 9
