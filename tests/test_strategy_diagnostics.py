from __future__ import annotations

import json

from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.strategy_diagnostics import strategy_snapshot, summarize_strategy_results
from state_factory import state


def test_strategy_snapshot_is_stable_json_and_public_only() -> None:
    raw = state("SHOP", seed="PRIVATE-SEED", money=12)
    observation = to_public_observation(raw)

    snapshot = strategy_snapshot(observation)

    assert snapshot["schema_version"] == 4
    assert set(snapshot["routes"]) == {
        "victory",
        "held_retrigger",
        "played_retrigger",
        "consumable_duplication",
    }
    encoded = json.dumps(snapshot, sort_keys=True)

    assert snapshot["goal"] == "victory"
    assert snapshot["economy"]["cash"] == 12
    assert snapshot["boss"]["name"] == "The Head"
    assert "PRIVATE-SEED" not in encoded


def test_strategy_summary_separates_prewin_boss_and_build_failures() -> None:
    losing = strategy_snapshot(to_public_observation(state("GAME_OVER")))
    won_raw = state("GAME_OVER", won=True)
    won = strategy_snapshot(to_public_observation(won_raw))

    summary = summarize_strategy_results(
        (
            {
                "won": False,
                "strategy": losing,
                "terminal": {"terminal_blind": {"kind": "BOSS", "name": "The Head"}},
            },
            {"won": True, "strategy": won},
        )
    )

    assert summary["snapshots"] == 2
    assert summary["final_goals"] == {"endless": 1, "victory": 1}
    assert sum(summary["prewin_failures_by_terminal_boss"].values()) == 1
    assert sum(summary["prewin_failures_by_primary_hand"].values()) == 1
