from __future__ import annotations

import balatro_ai_v2.jackdaw as jackdaw
from tests.state_factory import state


def test_candidate_module_is_lazy_and_revision_is_pinned() -> None:
    assert jackdaw.JACKDAW_REVISION == "dbedc66255fe594cce7b7cccc188c8a11649d9ec"


def test_bridge_normalization_uses_candidate_state_for_balatrobot_defaults() -> None:
    raw = state()
    raw["cards"]["highlighted_limit"] = 0
    raw["cards"]["cards"][0]["cost"] = {"buy": 0, "sell": 0}
    raw["cards"]["cards"][0]["state"] = {"hidden": False, "debuff": False, "highlight": False}
    raw["cards"]["cards"][0]["modifier"] = {"edition": None, "eternal": False}
    raw["cards"]["cards"][0]["value"].pop("ability")
    raw["shop"] = {"cards": [], "count": 0, "highlighted_limit": 0, "limit": 0}
    raw["round"].pop("ancient_suit")
    raw["round"].pop("most_played_poker_hand")
    raw["round"]["hands_left"] = 0
    raw["round"]["discards_left"] = 0
    private = {
        "current_round": {
            "ancient_card": {"suit": "Hearts"},
            "most_played_poker_hand": "High Card",
        },
        "round_resets": {"hands": 4, "discards": 4},
    }

    normalized = jackdaw._normalize_jackdaw_bridge(raw, private)

    assert "shop" not in normalized
    assert normalized["cards"]["highlighted_limit"] == 5
    assert normalized["cards"]["cards"][0]["cost"] == {"buy": 1, "sell": 1}
    assert normalized["cards"]["cards"][0]["state"] == {"hidden": True}
    assert normalized["cards"]["cards"][0]["modifier"] == []
    assert normalized["cards"]["cards"][0]["value"]["ability"] == {"x_mult": 1}
    assert normalized["round"]["ancient_suit"] == "H"
    assert normalized["round"]["hands_left"] == 4
    assert "Flush Five" in normalized["hands"]
