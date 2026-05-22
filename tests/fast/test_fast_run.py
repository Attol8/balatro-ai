import pytest

from balatro_ai_v2.fast.run import (
    BlindKind,
    FastRunState,
    RunPhase,
    blind_required_score,
    round_reward,
)


def test_blind_required_score_uses_small_big_boss_multipliers() -> None:
    assert blind_required_score(1, BlindKind.SMALL) == 300
    assert blind_required_score(1, BlindKind.BIG) == 450
    assert blind_required_score(1, BlindKind.BOSS) == 600


def test_round_reward_includes_blind_hands_and_interest() -> None:
    assert round_reward(BlindKind.SMALL, money=14, hands_remaining=2) == 3 + 2 + 2
    assert round_reward(BlindKind.BIG, money=100, hands_remaining=0) == 4 + 5


def test_run_progresses_through_blinds_and_antes() -> None:
    run = FastRunState().reset(seed=1)

    assert run.phase == RunPhase.BLIND_SELECT
    assert run.blind_kind == BlindKind.SMALL

    run.select_blind()
    assert run.phase == RunPhase.SELECTING_HAND
    assert len(run.hand) == run.hand_size

    run.phase = RunPhase.ROUND_EVAL
    reward = run.finish_round()
    assert reward > 0
    assert run.phase == RunPhase.SHOP

    run.next_round()
    assert run.phase == RunPhase.BLIND_SELECT
    assert run.blind_kind == BlindKind.BIG


def test_reroll_shop_cost_increases() -> None:
    run = FastRunState(money=20).reset(seed=1)
    run.money = 20
    run.phase = RunPhase.SHOP

    assert run.reroll_shop() == 5
    assert run.money == 15
    assert run.shop.reroll_cost == 6


def test_invalid_phase_actions_raise() -> None:
    run = FastRunState().reset(seed=1)

    with pytest.raises(ValueError):
        run.finish_round()
