from balatro_ai_v2.actions import ActionKind, GameAction
from balatro_ai_v2.fast.env import DISCARD_ACTION_OFFSET


def test_tactical_action_round_trips_fast_id() -> None:
    action = GameAction(ActionKind.PLAY, indices=(0, 2, 4))

    action_id = action.to_fast_action_id()

    assert action_id == 0b10101
    assert GameAction.from_fast_action_id(action_id) == action


def test_discard_action_round_trips_fast_id() -> None:
    action = GameAction(ActionKind.DISCARD, indices=(1, 3))

    action_id = action.to_fast_action_id()

    assert action_id == DISCARD_ACTION_OFFSET + 0b1010
    assert GameAction.from_fast_action_id(action_id) == action


def test_play_action_converts_to_balatrobot_rpc() -> None:
    action = GameAction(ActionKind.PLAY, indices=(0, 2, 4))

    assert action.to_balatrobot_rpc() == ("play", {"cards": [0, 2, 4]})


def test_shop_action_converts_to_balatrobot_rpc() -> None:
    action = GameAction(ActionKind.BUY_VOUCHER, index=1)

    assert action.to_balatrobot_rpc() == ("buy", {"voucher": 1})

