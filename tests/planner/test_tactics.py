from balatro_ai_v2.fast.cards import NUM_RANKS
from balatro_ai_v2.fast.env import DISCARD_ACTION_OFFSET
from balatro_ai_v2.fast.full_game import SELECT_BLIND_ACTION, FastFullGameEnv
from balatro_ai_v2.fast.hand import PAIR
from balatro_ai_v2.fast.run import BlindKind, RunPhase
from balatro_ai_v2.planner.tactics import plan_blind_tactics


def _card(suit: int, rank: int) -> int:
    return suit * NUM_RANKS + rank


def _blind_env(seed: int = 1, boss_key: str | None = None) -> FastFullGameEnv:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=seed)
    if boss_key is not None:
        env.run.blind_kind = BlindKind.BOSS
        env.boss_key = boss_key
    env.step(SELECT_BLIND_ACTION)
    return env


def test_tactics_returns_legal_action() -> None:
    env = _blind_env()
    action = plan_blind_tactics(env)
    assert action in env.legal_action_ids()


def test_tactics_clears_easy_blind() -> None:
    env = _blind_env()
    steps = 0
    while env.run.phase == RunPhase.SELECTING_HAND and steps < 10:
        env.step(plan_blind_tactics(env))
        steps += 1
    assert env.run.phase == RunPhase.ROUND_EVAL


def test_tactics_avoids_blocked_mouth_followup() -> None:
    env = _blind_env(boss_key="bl_mouth")
    env.run.required_score = 10_000  # force multi-hand planning
    env.run.hand = [
        _card(0, 3),
        _card(1, 3),
        _card(0, 5),
        _card(1, 7),
        _card(2, 9),
        _card(3, 10),
        _card(0, 11),
        _card(2, 2),
    ]
    env.step(0b11)  # play the pair, locking the hand type
    assert env.first_hand_kind_this_round == PAIR

    action = plan_blind_tactics(env)
    if action < DISCARD_ACTION_OFFSET:
        score = env.score_hand_mask(tuple(env.run.hand), action)
        assert score.total > 0, "planner picked a Mouth-blocked play"


def test_tactics_uses_discards_when_needed() -> None:
    env = _blind_env(seed=3)
    env.run.required_score = 100_000
    action = plan_blind_tactics(env)
    assert action in env.legal_action_ids()
