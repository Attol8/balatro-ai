from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from balatro_ai_v2.actions import PlayCards, SelectBlind, iter_legal_actions
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.baselines import PublicStrategicPolicy
from balatro_ai_v2.determinized_search import (
    DeterminizedSearchPolicy,
    SuccessTeacherBudget,
    _public_best_hand_score,
    _select_goal_root,
)
from balatro_ai_v2.public_state import PublicItem
from balatro_ai_v2.policy import NoPublicProgressAction, PublicHistoryStep
from balatro_ai_v2.strategy_engine import GoalUtility, RunGoal
from balatro_ai_v2.strategy_options import PersistentIntent, StrategyIntent
from state_factory import state


def _utility(
    *,
    win: float = 0.0,
    clear: float = 0.0,
    progress: float = 0.0,
    ante: float = 0.0,
    score: float = 0.0,
) -> GoalUtility:
    return GoalUtility(win, clear, progress, ante, score)


def test_victory_selector_never_trades_a_win_for_endless_score() -> None:
    values = (
        (_utility(win=1, clear=1, progress=8, score=2),),
        (_utility(win=0, clear=1, progress=99, ante=99, score=300),),
    )

    assert _select_goal_root(values, 0, RunGoal.VICTORY, 0) == 0


def test_endless_selector_uses_ante_then_log_score() -> None:
    values = (
        (_utility(win=1, ante=10, score=20),),
        (_utility(win=1, ante=10, score=21),),
        (_utility(win=1, ante=11, score=1),),
    )

    assert _select_goal_root(values, 0, RunGoal.ENDLESS, 0) == 2


def test_endless_selector_does_not_trade_liveness_for_score_at_same_ante() -> None:
    alive = _utility(win=1, ante=10, progress=10, score=1)
    dead = GoalUtility(
        1,
        1,
        10.99,
        endless_ante=10,
        log_score=300,
        alive_probability=0,
    )

    assert _select_goal_root(((alive,), (dead,)), 0, RunGoal.ENDLESS, 0) == 0


def test_uncertain_higher_priority_delta_cannot_be_rescued_by_score() -> None:
    baseline = (
        _utility(win=1, progress=8, score=1),
        _utility(win=0, progress=8, score=1),
    )
    noisy = (
        _utility(win=0, progress=100, score=100),
        _utility(win=1, progress=100, score=100),
    )

    assert _select_goal_root((baseline, noisy), 0, RunGoal.VICTORY, 1) == 0


def test_exact_higher_priority_tie_allows_survival_comparison() -> None:
    baseline = (_utility(clear=0.5, progress=1), _utility(clear=0.5, progress=1))
    better = (_utility(clear=0.5, progress=2), _utility(clear=0.5, progress=2))

    assert _select_goal_root((baseline, better), 0, RunGoal.VICTORY, 1) == 1


def test_truncated_or_rejected_root_is_ineligible_to_override() -> None:
    baseline = (_utility(progress=1),)
    apparently_better = (_utility(progress=100),)

    assert (
        _select_goal_root(
            (baseline, apparently_better),
            0,
            RunGoal.VICTORY,
            0,
            admissible=(True, False),
        )
        == 0
    )


def test_strategy_search_fails_closed_before_sampling_unknown_owned_mechanics() -> None:
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        jokers=(PublicItem("j_future_mod", "Future", "JOKER"),),
    )
    continuation = PublicStrategicPolicy()
    baseline = continuation.choose_action(
        observation, lambda: iter_legal_actions(observation), ()
    )
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=continuation,
        enable_strategy_options=True,
    )

    selected = policy.choose_action(
        observation, lambda: iter_legal_actions(observation), ()
    )

    assert selected == baseline
    assert policy.last_decision is not None
    assert policy.last_decision.unavailable_reason == "unknown_owned_joker"


def test_strategy_search_fails_closed_on_unknown_active_voucher() -> None:
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        used_vouchers=("v_future_mod",),
    )
    continuation = PublicStrategicPolicy()
    baseline = continuation.choose_action(
        observation, lambda: iter_legal_actions(observation), ()
    )
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=continuation,
        enable_strategy_options=True,
    )

    assert (
        policy.choose_action(observation, lambda: iter_legal_actions(observation), ())
        == baseline
    )
    assert policy.last_decision is not None
    assert policy.last_decision.unavailable_reason == "unknown_used_voucher"


def test_intent_continuation_without_isolated_fork_fails_closed() -> None:
    class UnsafeIntentContinuation:
        control = PublicStrategicPolicy()

        def choose_action(self, observation, legal_actions, history):
            return self.control.choose_action(observation, legal_actions, history)

        def choose_action_for_intent(self, observation, legal_actions, history, intent):
            return self.control.choose_action(observation, legal_actions, history)

    observation = to_public_observation(state("SHOP", money=10))
    continuation = UnsafeIntentContinuation()
    baseline = continuation.choose_action(
        observation, lambda: iter_legal_actions(observation), ()
    )
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=continuation,
        enable_strategy_options=True,
    )

    assert (
        policy.choose_action(observation, lambda: iter_legal_actions(observation), ())
        == baseline
    )
    assert policy.last_decision is not None
    assert (
        policy.last_decision.unavailable_reason
        == "intent_continuation_missing_rollout_fork"
    )


def test_active_intent_controls_intervening_public_decisions() -> None:
    class IntentContinuation:
        calls: list[StrategyIntent] = []

        def choose_action(self, observation, legal_actions, history):
            return tuple(legal_actions())[0]

        def choose_action_for_intent(self, observation, legal_actions, history, intent):
            self.calls.append(intent)
            return tuple(legal_actions())[-1]

        def fork_for_rollout(self):
            return IntentContinuation()

    observation = to_public_observation(state("SELECTING_HAND"))
    legal = tuple(iter_legal_actions(observation))
    continuation = IntentContinuation()
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=continuation,  # type: ignore[arg-type]
        enable_strategy_options=True,
        active_intent=PersistentIntent(
            intent=StrategyIntent.RELIABLE_HAND,
            goal=RunGoal.VICTORY,
            started_ante=1,
            decisions=1,
            evidence=(),
        ),
    )

    selected = policy.choose_action(observation, lambda: iter(legal), ())

    assert selected == legal[-1]
    assert continuation.calls == [StrategyIntent.RELIABLE_HAND]


def test_public_dead_end_is_a_losing_rollout_not_a_rejected_root() -> None:
    before = to_public_observation(state("BLIND_SELECT"))
    raw_dead_end = state("SELECTING_HAND")
    raw_dead_end["hand"]["cards"] = []
    raw_dead_end["hand"]["count"] = 0
    raw_dead_end["round"].update(hands_left=1, discards_left=0)
    dead_end = to_public_observation(raw_dead_end)

    class DeadEndClone:
        current_public = dead_end

        def step(self, action):
            del action
            return SimpleNamespace(status="accepted", after=SimpleNamespace())

    class DeadEndContinuation:
        def choose_action(self, observation, legal_actions, history):
            del observation, legal_actions, history
            raise NoPublicProgressAction("synthetic public dead end")

    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=DeadEndContinuation(),  # type: ignore[arg-type]
    )

    outcome = policy._rollout(  # noqa: SLF001 - exact rollout contract regression
        DeadEndClone(),  # type: ignore[arg-type]
        before,
        (),
        SelectBlind(),
    )

    assert not outcome.rejected
    assert outcome.rejection_reason is None
    assert outcome.goal_utility is not None
    assert outcome.goal_utility.alive_probability == 0


def test_success_anchor_schedule_is_sparse_per_public_ante() -> None:
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=PublicStrategicPolicy(),
        success_teacher=SuccessTeacherBudget(),
    )
    shop = replace(to_public_observation(state("SHOP")), ante=4, antes_cleared=3)
    pack = replace(
        to_public_observation(state("BUFFOON_PACK")), ante=4, antes_cleared=3
    )

    assert policy._is_success_anchor(shop)  # noqa: SLF001
    assert not policy._is_success_anchor(shop)  # noqa: SLF001
    assert policy._is_success_anchor(pack)  # noqa: SLF001
    assert not policy._is_success_anchor(pack)  # noqa: SLF001


def test_teacher_score_target_includes_typed_public_prefix() -> None:
    before = to_public_observation(state("SELECTING_HAND"))
    after = replace(before, round=replace(before.round, chips=12_345))
    action = next(
        action for action in iter_legal_actions(before) if isinstance(action, PlayCards)
    )
    history = (PublicHistoryStep(before, action, after),)

    assert _public_best_hand_score(history) == 12_345
