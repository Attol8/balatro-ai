import pytest

from balatro_ai_v2.fast.env import (
    ACTION_SPACE_SIZE,
    DISCARD_ACTION_OFFSET,
    FastBalatroEnv,
)


def test_reset_is_deterministic() -> None:
    env = FastBalatroEnv()

    first = env.reset(seed=42)
    second = env.reset(seed=42)

    assert first == second


def test_legal_action_mask_has_fixed_size_and_valid_actions() -> None:
    env = FastBalatroEnv()
    env.reset(seed=1)

    mask = env.action_mask()

    assert len(mask) == ACTION_SPACE_SIZE
    assert mask[0] == 0
    assert mask[1] == 1
    assert mask[DISCARD_ACTION_OFFSET + 1] == 1


def test_sample_legal_action_is_deterministic_for_seed() -> None:
    first = FastBalatroEnv()
    second = FastBalatroEnv()
    first.reset(seed=9)
    second.reset(seed=9)

    assert [first.sample_legal_action() for _ in range(5)] == [
        second.sample_legal_action() for _ in range(5)
    ]


def test_step_play_updates_score_and_replaces_cards() -> None:
    env = FastBalatroEnv(required_score=10_000)
    env.reset(seed=2)
    original_hand = tuple(env.hand or ())

    result = env.step(0b11111)

    assert result.info["hand_score"] > 0
    assert env.score == result.info["hand_score"]
    assert env.hands_remaining == env.hands - 1
    assert len(env.hand or ()) == env.hand_size
    assert tuple(env.hand or ())[:3] == original_hand[5:]


def test_discard_updates_only_discard_count_and_replaces_cards() -> None:
    env = FastBalatroEnv(required_score=10_000)
    env.reset(seed=3)
    original_hand = tuple(env.hand or ())

    result = env.step(DISCARD_ACTION_OFFSET + 0b111)

    assert result.info["is_discard"] is True
    assert env.score == 0
    assert env.hands_remaining == env.hands
    assert env.discards_remaining == env.discards - 1
    assert tuple(env.hand or ())[:5] == original_hand[3:]


def test_episode_terminates_on_clear() -> None:
    env = FastBalatroEnv(required_score=1)
    env.reset(seed=4)

    result = env.step(1)

    assert result.terminated
    assert result.reward > 1


def test_invalid_action_is_rejected() -> None:
    env = FastBalatroEnv()
    env.reset(seed=5)

    with pytest.raises(ValueError):
        env.step(0)
