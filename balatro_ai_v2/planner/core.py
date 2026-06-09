"""PlannerCore: online rollout-expectimax planning over FastFullGameEnv.

One decision procedure for both fast-sim evaluation and live play:
- in-blind tactics: deterministic beam search (deck order is known),
- shop/pack/blind decisions: top-K candidates by static run_value delta,
  each rolled forward with a cheap policy and scored by run_value.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from balatro_ai_v2.fast.full_game import (
    CASH_OUT_ACTION,
    NEXT_ROUND_ACTION,
    SELECT_BLIND_ACTION,
    SKIP_BLIND_ACTION,
    FastFullGameEnv,
    SearchRunAgent,
)
from balatro_ai_v2.fast.run import BlindKind, RunPhase
from balatro_ai_v2.planner.evaluation import DEFAULT_WEIGHTS, RunValueWeights, run_value
from balatro_ai_v2.planner.tactics import plan_blind_tactics


@dataclass(frozen=True, slots=True)
class PlannerConfig:
    shop_candidates: int = 6
    rollout_horizon_blinds: int = 4
    max_rollout_steps: int = 40
    determinizations: int = 1
    tactical_beam: int = 4
    tactical_action_beam: int = 3
    rollout_tactical_beam: int = 1
    rollout_tactical_action_beam: int = 1
    max_shop_actions_per_visit: int = 12
    evaluate_blind_skip: bool = True


@dataclass(slots=True)
class PlannerCore:
    config: PlannerConfig = field(default_factory=PlannerConfig)
    weights: RunValueWeights = field(default_factory=lambda: DEFAULT_WEIGHTS)
    # Cheap heuristics used INSIDE rollouts only; strategic choices at the
    # top level are made by run_value, not by these tables.
    _rollout_heuristics: SearchRunAgent = field(default_factory=SearchRunAgent)

    def decide(self, env: FastFullGameEnv) -> int:
        phase = env.run.phase
        if phase == RunPhase.BLIND_SELECT:
            return self._decide_blind(env)
        if phase == RunPhase.ROUND_EVAL:
            return CASH_OUT_ACTION
        if phase == RunPhase.SHOP:
            return self._decide_with_rollouts(env)
        if phase == RunPhase.PACK:
            return self._decide_with_rollouts(env)
        if phase == RunPhase.SELECTING_HAND:
            return plan_blind_tactics(
                env,
                beam_width=self.config.tactical_beam,
                action_beam=self.config.tactical_action_beam,
            )
        raise ValueError(f"cannot decide in phase {phase}")

    # -- blind select ------------------------------------------------------

    def _decide_blind(self, env: FastFullGameEnv) -> int:
        if env.run.blind_kind == BlindKind.BOSS or not self.config.evaluate_blind_skip:
            return SELECT_BLIND_ACTION
        legal = set(env.legal_action_ids())
        if SKIP_BLIND_ACTION not in legal:
            return SELECT_BLIND_ACTION
        select_score = self._rollout_value(env, SELECT_BLIND_ACTION)
        skip_score = self._rollout_value(env, SKIP_BLIND_ACTION)
        return SKIP_BLIND_ACTION if skip_score > select_score else SELECT_BLIND_ACTION

    # -- shop / pack -------------------------------------------------------

    def _decide_with_rollouts(self, env: FastFullGameEnv) -> int:
        legal = list(env.legal_action_ids())
        if not legal:
            raise ValueError("no legal actions")
        if len(legal) == 1:
            return legal[0]
        ranked = self._static_ranked_candidates(env, legal)
        candidates = [action for _, action in ranked[: self.config.shop_candidates]]
        if NEXT_ROUND_ACTION in legal and NEXT_ROUND_ACTION not in candidates:
            candidates.append(NEXT_ROUND_ACTION)

        best_action = candidates[0]
        best_score = float("-inf")
        for action in candidates:
            score = self._rollout_value(env, action)
            if score > best_score:
                best_score = score
                best_action = action
        return best_action

    def _static_ranked_candidates(
        self, env: FastFullGameEnv, legal: list[int]
    ) -> list[tuple[float, int]]:
        ranked: list[tuple[float, int]] = []
        for action in legal:
            probe = env.clone()
            try:
                probe.step(action)
            except ValueError:
                continue
            value = run_value(probe, weights=self.weights)
            ranked.append((value, action))
        ranked.sort(key=lambda item: (item[0], -item[1]), reverse=True)
        return ranked

    # -- rollouts ----------------------------------------------------------

    def _rollout_value(self, env: FastFullGameEnv, first_action: int) -> float:
        samples = max(self.config.determinizations, 1)
        total = 0.0
        for sample in range(samples):
            total += self._single_rollout(env, first_action, sample)
        return total / samples

    def _single_rollout(self, env: FastFullGameEnv, first_action: int, sample: int) -> float:
        clone = env.clone()
        if sample:
            # Determinize hidden future RNG streams; visible state is exact.
            clone.seed = (clone.seed * 1_000_003 + sample * 7_919_993) % (2**31 - 1)
        try:
            result = clone.step(first_action)
        except ValueError:
            return float("-inf")
        target_rounds = env.rounds_cleared + self.config.rollout_horizon_blinds
        steps = 1
        shop_actions_this_visit = 0
        while (
            not result.terminated
            and steps < self.config.max_rollout_steps
            and clone.rounds_cleared < target_rounds
        ):
            try:
                action = self._rollout_policy_action(clone, shop_actions_this_visit)
                result = clone.step(action)
            except ValueError:
                break
            if clone.run.phase in (RunPhase.SHOP, RunPhase.PACK):
                shop_actions_this_visit += 1
            else:
                shop_actions_this_visit = 0
            steps += 1
        return run_value(clone, steps_taken=steps, weights=self.weights)

    def _rollout_policy_action(self, env: FastFullGameEnv, shop_actions_this_visit: int) -> int:
        phase = env.run.phase
        if phase == RunPhase.BLIND_SELECT:
            return SELECT_BLIND_ACTION
        if phase == RunPhase.ROUND_EVAL:
            return CASH_OUT_ACTION
        if phase == RunPhase.SHOP:
            if shop_actions_this_visit >= self.config.max_shop_actions_per_visit:
                return NEXT_ROUND_ACTION
            return self._rollout_heuristics._heuristic_shop_action(env)
        if phase == RunPhase.PACK:
            return self._rollout_heuristics._pack_action(env)
        if phase == RunPhase.SELECTING_HAND:
            if self.config.rollout_tactical_beam <= 1:
                return env.greedy_play_action()
            return plan_blind_tactics(
                env,
                beam_width=self.config.rollout_tactical_beam,
                action_beam=self.config.rollout_tactical_action_beam,
                wide_retry=False,
            )
        raise ValueError(f"cannot act in phase {phase}")


@dataclass(slots=True)
class PlannerAgent:
    """SearchRunAgent-compatible wrapper for the eval harness."""

    core: PlannerCore = field(default_factory=PlannerCore)

    def act(self, env: FastFullGameEnv) -> int:
        return self.core.decide(env)
