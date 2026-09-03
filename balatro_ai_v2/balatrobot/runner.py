"""Policy runner that never exposes privileged authority state."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass

from balatro_ai_v2.actions import (
    BuyPack,
    BuyShopCard,
    BuyVoucher,
    CashOut,
    ChoosePackCard,
    DiscardCards,
    HandSlot,
    LeaveShop,
    PlayCards,
    PublicAction,
    SelectBlind,
    SellConsumable,
    SellJoker,
    SkipPack,
    UseConsumable,
    action_to_data,
    is_legal,
    iter_legal_actions,
)
from balatro_ai_v2.backend import AuthorityObservation, GameBackend, RunSpec
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.balatrobot.backend import UnsettledStateError
from balatro_ai_v2.balatrobot.tracing import AuthorityTraceWriter
from balatro_ai_v2.policy import ActionSource, PublicHistoryStep, PublicPolicy
from balatro_ai_v2.public_state import (
    Phase,
    PublicBlind,
    PublicItem,
    PublicObservation,
    VisiblePlayingCard,
)


@dataclass(frozen=True, slots=True)
class RunResult:
    complete: bool
    won: bool
    antes_cleared: int
    ante: int
    round_no: int
    decisions: int
    rejected_decisions: int
    terminal_reason: str
    final_observation: PublicObservation | None
    terminal_blind: PublicBlind | None
    action_counts: tuple[tuple[str, int], ...]
    semantic_action_counts: tuple[tuple[str, int], ...]
    cards_played: int
    cards_discarded: int


@dataclass(slots=True)
class AuthorityRunner:
    backend: GameBackend
    policy: PublicPolicy
    max_decisions: int = 800
    max_antes_cleared: int = 20
    trace: AuthorityTraceWriter | None = None

    def __post_init__(self) -> None:
        if self.max_decisions < 1 or self.max_antes_cleared < 1:
            raise ValueError("runner decision and ante caps must be positive")

    def run(self, spec: RunSpec) -> RunResult:
        history: list[PublicHistoryStep] = []
        action_counts: Counter[str] = Counter()
        semantic_action_counts: Counter[str] = Counter()
        cards_played = 0
        cards_discarded = 0
        rejected = 0
        final: PublicObservation | None = None
        terminal_blind: PublicBlind | None = None
        terminal_reason = "policy_error"
        try:
            authority = self.backend.reset(spec)
            public = _public(authority)
            final = public
            terminal_blind = _current_blind(public)
            self._record("run_start", authority=_authority_data(authority), public=json.loads(public.canonical_json()))
            for _ in range(self.max_decisions):
                terminal_blind = _current_blind(public) or terminal_blind
                if public.terminal:
                    terminal_reason = "game_over"
                    break
                if public.antes_cleared >= self.max_antes_cleared:
                    terminal_reason = "ante_cap"
                    break
                try:
                    action = self.policy.choose_action(
                        public,
                        lambda: iter_legal_actions(public),
                        tuple(history),
                    )
                except Exception as exc:  # the trace must close even for model failures
                    terminal_reason = "policy_error"
                    self._record("policy_error", error=f"{type(exc).__name__}: {exc}")
                    break
                if not is_legal(public, action):
                    terminal_reason = "policy_error"
                    self._record("policy_error", error=f"policy emitted illegal action {action!r}")
                    break

                result = self.backend.step(action)
                semantic_action = _semantic_action_label(public, action)
                transition: dict[str, object] = {
                    "before_canonical_digest": authority.observed.canonical_digest,
                    "action": action_to_data(action),
                    "rpc_method": result.rpc_method,
                    "rpc_params": result.rpc_params,
                    "status": result.status,
                    "rpc_observations": [json.loads(value) for value in result.rpc_observations],
                    "error": result.error,
                }
                if result.status == "rejected":
                    rejected += 1
                    terminal_reason = "rejected_action"
                    self._record("transition", **transition)
                    break
                if result.status == "transport_error" or result.after is None:
                    terminal_reason = "transport_error"
                    self._record("transition", **transition)
                    break

                after_public = _public(result.after)
                transition.update(
                    after=_authority_data(result.after),
                    public_after=json.loads(after_public.canonical_json()),
                )
                self._record("transition", **transition)
                action_kind = str(action_to_data(action)["type"])
                action_counts[action_kind] += 1
                if semantic_action is not None:
                    semantic_action_counts[semantic_action] += 1
                if isinstance(action, PlayCards):
                    cards_played += len(action.cards)
                elif isinstance(action, DiscardCards):
                    cards_discarded += len(action.cards)
                history.append(PublicHistoryStep(before=public, action=action, after=after_public))
                authority = result.after
                public = after_public
                final = public
                terminal_blind = _current_blind(public) or terminal_blind
                if public.terminal:
                    terminal_reason = "game_over"
                    break
                if public.antes_cleared >= self.max_antes_cleared:
                    terminal_reason = "ante_cap"
                    break
            else:
                terminal_reason = "decision_limit"
        except UnsettledStateError as exc:
            terminal_reason = "unsettled"
            self._record("authority_error", error=str(exc))

        complete = terminal_reason in {"game_over", "ante_cap"} and final is not None
        result = RunResult(
            complete=complete,
            won=bool(final.won) if complete else False,
            antes_cleared=(
                min(final.antes_cleared, self.max_antes_cleared)
                if complete
                else 0
            ),
            ante=final.ante if final is not None else 0,
            round_no=final.round_no if final is not None else 0,
            decisions=len(history),
            rejected_decisions=rejected,
            terminal_reason=terminal_reason,
            final_observation=final,
            terminal_blind=terminal_blind,
            action_counts=tuple(sorted(action_counts.items())),
            semantic_action_counts=tuple(sorted(semantic_action_counts.items())),
            cards_played=cards_played,
            cards_discarded=cards_discarded,
        )
        self._record(
            "run_end",
            complete=result.complete,
            won=result.won,
            antes_cleared=result.antes_cleared,
            ante=result.ante,
            round_no=result.round_no,
            accepted_decisions=result.decisions,
            rejected_decisions=result.rejected_decisions,
            terminal_reason=result.terminal_reason,
            final_public_digest=final.digest() if final is not None else None,
            terminal_blind=(
                {
                    "kind": result.terminal_blind.kind,
                    "name": result.terminal_blind.name,
                    "effect": result.terminal_blind.effect,
                    "score": result.terminal_blind.score,
                }
                if result.terminal_blind is not None
                else None
            ),
            action_counts=dict(result.action_counts),
            semantic_action_counts=dict(result.semantic_action_counts),
            cards_played=result.cards_played,
            cards_discarded=result.cards_discarded,
        )
        return result

    def _record(self, event: str, **payload: object) -> None:
        if self.trace is not None:
            self.trace.record(event, **payload)


class NoBuySmokePolicy:
    """A public-only integration smoke test, deliberately not a solver."""

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        del legal_actions, history
        if observation.phase == Phase.BLIND_SELECT:
            return SelectBlind()
        if observation.phase == Phase.SELECTING_HAND:
            size = min(5, observation.selection_limit, len(observation.hand))
            return PlayCards(tuple(HandSlot(index) for index in range(size)))
        if observation.phase == Phase.ROUND_EVAL:
            return CashOut()
        if observation.phase == Phase.SHOP:
            return LeaveShop()
        if observation.phase == Phase.PACK:
            return SkipPack()
        raise RuntimeError(f"no smoke action for {observation.phase.value}")


def _public(authority: AuthorityObservation) -> PublicObservation:
    raw = json.loads(authority.observed.raw_json)
    if not isinstance(raw, dict):
        raise AssertionError("authority state root is not an object")
    return to_public_observation(raw)


def _current_blind(observation: PublicObservation) -> PublicBlind | None:
    return next((blind for blind in observation.blinds if blind.status == "CURRENT"), None)


def _semantic_action_label(
    observation: PublicObservation,
    action: PublicAction,
) -> str | None:
    """Describe an accepted item action using only its pre-action public key."""

    item: PublicItem | VisiblePlayingCard
    action_name: str
    if isinstance(action, BuyShopCard):
        item = observation.shop[action.card.value]
        action_name = "buy_shop_card"
    elif isinstance(action, BuyVoucher):
        item = observation.vouchers[action.voucher.value]
        action_name = "buy_voucher"
    elif isinstance(action, BuyPack):
        item = observation.packs[action.pack.value]
        action_name = "buy_pack"
    elif isinstance(action, ChoosePackCard):
        item = observation.opened_pack[action.card.value]
        action_name = "choose_pack_card"
    elif isinstance(action, UseConsumable):
        item = observation.consumables[action.consumable.value]
        action_name = "use_consumable"
    elif isinstance(action, SellJoker):
        item = observation.jokers[action.joker.value]
        action_name = "sell_joker"
    elif isinstance(action, SellConsumable):
        item = observation.consumables[action.consumable.value]
        action_name = "sell_consumable"
    else:
        return None
    key = item.key if isinstance(item, PublicItem) else f"{item.suit}_{item.rank}"
    return f"{action_name}:{key}"


def _authority_data(authority: AuthorityObservation) -> dict[str, object]:
    return {
        "raw": json.loads(authority.observed.raw_json),
        "canonical": json.loads(authority.observed.canonical_json),
        "raw_digest": authority.observed.raw_digest,
        "canonical_digest": authority.observed.canonical_digest,
        "settled": authority.settled,
        "poll_count": len(authority.polls) - 1,
    }
