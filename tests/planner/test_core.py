from balatro_ai_v2.fast.full_game import (
    CASH_OUT_ACTION,
    NEXT_ROUND_ACTION,
    SELECT_BLIND_ACTION,
    FastFullGameEnv,
)
from balatro_ai_v2.fast.run import BlindKind, RunPhase
from balatro_ai_v2.planner import PlannerAgent, PlannerConfig, PlannerCore


def _env(seed: int = 1) -> FastFullGameEnv:
    env = FastFullGameEnv(deck_key="b_red")
    env.reset(seed=seed)
    return env


def _fast_core() -> PlannerCore:
    return PlannerCore(
        config=PlannerConfig(
            shop_candidates=3,
            rollout_horizon_blinds=1,
            max_rollout_steps=10,
        )
    )


def test_planner_never_skips_boss() -> None:
    env = _env()
    env.run.blind_kind = BlindKind.BOSS
    core = _fast_core()
    assert core.decide(env) == SELECT_BLIND_ACTION


def test_planner_cashes_out_round_eval() -> None:
    env = _env()
    env.run.phase = RunPhase.ROUND_EVAL
    core = _fast_core()
    assert core.decide(env) == CASH_OUT_ACTION


def test_planner_shop_decision_is_legal_and_deterministic() -> None:
    env = _env()
    env.run.phase = RunPhase.ROUND_EVAL
    env.step(CASH_OUT_ACTION)
    core = _fast_core()

    action = core.decide(env)
    assert action in env.legal_action_ids()

    repeat_env = _env()
    repeat_env.run.phase = RunPhase.ROUND_EVAL
    repeat_env.step(CASH_OUT_ACTION)
    assert PlannerCore(config=core.config).decide(repeat_env) == action


def test_planner_decision_does_not_mutate_env() -> None:
    env = _env()
    env.run.phase = RunPhase.ROUND_EVAL
    env.step(CASH_OUT_ACTION)
    before = (
        env.observation(),
        env.run.money,
        tuple(env.jokers),
        tuple(env.run.shop.item_keys),
        env.seed,
    )
    _fast_core().decide(env)
    after = (
        env.observation(),
        env.run.money,
        tuple(env.jokers),
        tuple(env.run.shop.item_keys),
        env.seed,
    )
    assert before == after


def test_planner_plays_through_first_blind() -> None:
    env = _env()
    agent = PlannerAgent(core=_fast_core())

    steps = 0
    while env.run.phase != RunPhase.SHOP and steps < 20:
        result = env.step(agent.act(env))
        assert not result.terminated
        steps += 1
    assert env.run.phase == RunPhase.SHOP
    assert env.rounds_cleared == 1


def test_planner_leaves_empty_shop() -> None:
    env = _env()
    env.run.phase = RunPhase.SHOP
    env.run.shop.item_keys = []
    env.available_voucher = None
    env.run.money = 0
    core = _fast_core()
    assert core.decide(env) == NEXT_ROUND_ACTION
