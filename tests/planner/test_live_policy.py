from balatro_ai_v2.actions import ActionKind, GameAction
from balatro_ai_v2.planner.live_policy import _with_required_targets

import pytest


def _card(key: str, rank: str = "5", suit: str = "Hearts") -> dict:
    return {"key": key, "label": key, "rank": rank, "suit": suit, "cost": {"buy": 0, "sell": 1}}


def test_pack_select_targeted_tarot_gets_targets() -> None:
    state = {
        "pack": {"cards": [_card("c_tower")]},
        "hand": {
            "cards": [
                {"rank": "2", "suit": "Hearts"},
                {"rank": "King", "suit": "Spades"},
            ]
        },
    }
    action = _with_required_targets(state, GameAction(kind=ActionKind.PACK_SELECT, index=0))
    assert action.kind == ActionKind.PACK_SELECT
    assert action.indices
    assert len(action.indices) == 1


def test_pack_select_targeted_tarot_without_hand_raises() -> None:
    state = {"pack": {"cards": [_card("c_tower")]}, "hand": {"cards": []}}
    with pytest.raises(ValueError):
        _with_required_targets(state, GameAction(kind=ActionKind.PACK_SELECT, index=0))


def test_pack_select_joker_passes_through() -> None:
    state = {"pack": {"cards": [_card("j_joker")]}, "hand": {"cards": []}}
    action = _with_required_targets(state, GameAction(kind=ActionKind.PACK_SELECT, index=0))
    assert action.indices is None or action.indices == ()


def test_use_consumable_planet_passes_through() -> None:
    state = {"consumables": {"cards": [_card("c_pluto")]}, "hand": {"cards": []}}
    action = _with_required_targets(state, GameAction(kind=ActionKind.USE_CONSUMABLE, index=0))
    assert action.kind == ActionKind.USE_CONSUMABLE


def test_non_target_actions_unchanged() -> None:
    state: dict = {}
    action = GameAction(kind=ActionKind.NEXT_ROUND)
    assert _with_required_targets(state, action) is action
