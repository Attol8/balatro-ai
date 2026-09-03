"""Composed public belief search for the Red/Gold milestone."""

from __future__ import annotations

from dataclasses import dataclass, field

from balatro_ai_v2.actions import DiscardCards, PlayCards, PublicAction
from balatro_ai_v2.baselines import PublicStrategicPolicy
from balatro_ai_v2.blind_search import PublicBlindBeliefSearch
from balatro_ai_v2.policy import ActionSource, PublicHistoryStep
from balatro_ai_v2.preboss_search import PublicPreBossSearchPolicy
from balatro_ai_v2.public_state import Phase, PublicObservation
from balatro_ai_v2.strategy_tuning import StrategyTuning


@dataclass(slots=True)
class PublicRedGoldSearchPolicy:
    search_nonce: str = "red-gold-search-v1"
    tuning: StrategyTuning = StrategyTuning()
    strategic: PublicPreBossSearchPolicy = field(init=False)
    tactical_baseline: PublicStrategicPolicy = field(init=False)
    tactical: PublicBlindBeliefSearch = field(init=False)

    def __post_init__(self) -> None:
        baseline = PublicStrategicPolicy(tuning=self.tuning)
        self.strategic = PublicPreBossSearchPolicy(
            search_nonce=f"{self.search_nonce}:shop",
            baseline=baseline,
        )
        self.tactical_baseline = PublicStrategicPolicy(tuning=self.tuning)
        self.tactical = PublicBlindBeliefSearch()

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        if observation.phase == Phase.SELECTING_HAND:
            baseline = self.tactical_baseline.choose_action(
                observation,
                legal_actions,
                history,
            )
            if not isinstance(baseline, (PlayCards, DiscardCards)):
                return baseline
            return self.tactical.choose_action(observation, baseline, history)
        return self.strategic.choose_action(observation, legal_actions, history)
