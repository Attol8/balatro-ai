"""Bridge the typed, public strategic solver to the live experiment runner."""

from __future__ import annotations

from dataclasses import dataclass

from balatro_ai_v2.live.observation import public_observation
from balatro_ai_v2.live.policy import Decision
from balatro_ai_v2.solver.actions import DiscardCards, PlayCards, action_from_data, action_to_data, iter_legal_actions
from balatro_ai_v2.solver.adapter import action_to_rpc, to_public_observation
from balatro_ai_v2.solver.baselines import PublicStrategicPolicy, _with_history_derived_joker_runtime
from balatro_ai_v2.solver.policy import PublicHistoryStep
from balatro_ai_v2.solver.public_codec import public_observation_from_data, public_observation_to_data
from balatro_ai_v2.solver.public_scoring import score_play


def project_strategic_observation(raw: dict) -> dict:
    """Backend-only projection; raw input never reaches a decision method.

    The typed adapter constructs unordered Remaining-view counts, combining
    face-down hand cards with the draw pile so subtraction cannot reveal them.
    This matches the information in the public View Deck screen.
    """
    result = public_observation(raw)
    result["public_solver"] = public_observation_to_data(to_public_observation(raw))
    return result


@dataclass(frozen=True)
class SolverAction:
    method: str
    params: dict
    public_action: dict

    def to_balatrobot_rpc(self) -> tuple[str, dict]:
        return self.method, self.params


class StrategicPolicy:
    def __init__(self) -> None:
        self.policy = PublicStrategicPolicy()
        self.history: list[PublicHistoryStep] = []

    def choose(self, state: dict) -> Decision:
        # Decode only whitelisted typed fields, never the surrounding API data.
        observation = public_observation_from_data(state["public_solver"])
        action, reason, diagnostics = self.select(observation)
        method, params = action_to_rpc(action, observation)
        estimate = None
        limitations = ("Public scorer estimates random effects; unsupported interactions may differ from the game.",)
        if isinstance(action, PlayCards):
            try:
                score_observation = _with_history_derived_joker_runtime(observation, tuple(self.history))
                estimate, _ = score_play(score_observation, action.cards)
                estimate = float(estimate)
            except ValueError:
                limitations += ("Scoring unavailable for this obscured or unsupported state.",)
        return Decision(
            SolverAction(method, params, action_to_data(action)),
            reason, estimate, limitations, diagnostics,
        )

    def select(self, observation):
        action = self.policy.choose_action(
            observation, lambda: iter_legal_actions(observation), tuple(self.history),
        )
        return action, f"Public strategic policy selected {type(action).__name__}.", {}

    def record_transition(self, before: dict, action: dict, after: dict) -> None:
        self.history.append(PublicHistoryStep(
            before=public_observation_from_data(before["public_solver"]),
            action=action_from_data(action["public_action"]),
            after=public_observation_from_data(after["public_solver"]),
        ))


class SearchPolicy(StrategicPolicy):
    """Numerical shop comparisons and sampled public draw lookahead."""

    def __init__(self, tactical_samples: int = 8, shop_samples: int = 6) -> None:
        super().__init__()
        from balatro_ai_v2.solver.shop_search import ShopSearch
        self.shop_search = ShopSearch(samples=shop_samples)
        self.tactical_samples = tactical_samples

    def select(self, observation):
        from balatro_ai_v2.solver.public_state import Phase
        from balatro_ai_v2.solver.tactical_search import choose_tactical
        action, reason, diagnostics = super().select(observation)
        observation = _with_history_derived_joker_runtime(observation, tuple(self.history))
        if observation.phase == Phase.SHOP:
            choice = self.shop_search.choose(observation, action, tuple(self.history))
            if choice is not None:
                return choice.action, choice.reason, choice.diagnostics
        elif isinstance(action, (PlayCards, DiscardCards)):
            tactical = choose_tactical(observation, action, samples=self.tactical_samples)
            return tactical.action, tactical.reason, {
                "sampled_next_play_score": tactical.expected_score,
                "baseline_score": tactical.baseline_score, "samples": tactical.samples,
            }
        return action, reason, diagnostics
