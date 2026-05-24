from balatro_ai_v2.fast.full_game import FastFullGameEnv, FlushRunAgent, evaluate_agent
from balatro_ai_v2.fast.run import RunPhase


def test_full_game_reset_is_deterministic() -> None:
    env = FastFullGameEnv(deck_key="b_red")

    first = env.reset(seed=42)
    second = env.reset(seed=42)

    assert first == second
    assert env.run.phase == RunPhase.SELECTING_HAND


def test_flush_agent_clears_first_red_deck_seed() -> None:
    env = FastFullGameEnv(deck_key="b_red")
    agent = FlushRunAgent()
    env.reset(seed=1)

    for _ in range(600):
        result = env.step(agent.act(env))
        if result.terminated:
            break

    assert env.won
    assert env.rounds_cleared == 24


def test_flush_agent_beats_ante_8_on_first_deck_multiple_seeds() -> None:
    metrics = evaluate_agent(range(1, 17), deck_key="b_red")

    assert metrics["wins"] == 16
    assert metrics["win_rate"] == 1.0
    assert metrics["avg_rounds_cleared"] == 24
