"""Shadow-only, paired next-blind experiments rooted in public information.

This does not choose real-game actions. Candidate outcomes are model evidence,
not authority results. No real backend, seed, raw frame or save is accepted.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from .actions import (
    BuyMode, BuyShopCard, DiscardCards, LeaveShop, PlayCards, PublicAction,
    ReorderConsumables, ReorderHand, ReorderJokers, SelectBlind, action_to_data, is_legal,
    iter_legal_actions,
)
from .policy import PublicHistoryStep, PublicPolicy
from .public_state import Phase, PublicItem, PublicObservation


class Candidate(Protocol):
    current_public: PublicObservation | None

    def step(self, action: PublicAction): ...
    def close(self) -> None: ...


RootFactory = Callable[
    [PublicObservation, tuple[PublicHistoryStep, ...], str, int], Candidate
]


@dataclass(frozen=True)
class BlindOutcome:
    status: str  # cleared, lost, rejected, censored
    steps: int
    chips: int
    target: int
    reason: str | None = None


@dataclass(frozen=True)
class BlindComparison:
    observation_digest: str
    actions: tuple[dict, ...]
    # Rows are actions, columns are the same public-derived particles.
    outcomes: tuple[tuple[BlindOutcome, ...], ...]
    unavailable_reason: str | None = None

    @property
    def complete(self) -> bool:
        return bool(self.outcomes) and all(
            o.status in {"cleared", "lost"} for row in self.outcomes for o in row
        )

    @property
    def clear_rates(self) -> tuple[float, ...] | None:
        # Never silently drop failed/censored particles from a denominator.
        if not self.complete:
            return None
        return tuple(sum(o.status == "cleared" for o in row) / len(row)
                     for row in self.outcomes)


def shop_roots(observation: PublicObservation) -> tuple[PublicAction, ...]:
    """Visible single purchases only; no generated packs, rerolls or sale plans."""
    if observation.phase != Phase.SHOP:
        return ()
    roots: list[PublicAction] = []
    for action in iter_legal_actions(observation):
        if isinstance(action, LeaveShop):
            roots.append(action)
        elif isinstance(action, BuyShopCard):
            offer = observation.shop[action.card.value]
            if isinstance(offer, PublicItem) and (
                (offer.kind == "JOKER" and action.mode == BuyMode.STORE)
                or (offer.kind == "PLANET" and action.mode == BuyMode.USE)
            ):
                roots.append(action)
    return tuple(roots)


def compare_next_blind(
    observation: PublicObservation,
    history: tuple[PublicHistoryStep, ...],
    *,
    root_factory: RootFactory,
    continuation_factory: Callable[[], PublicPolicy],
    samples: int = 8,
    max_steps: int = 64,
    nonce: str = "public-next-blind-v1",
) -> BlindComparison:
    """Buy the root item (or leave), then leave and play exactly one blind.

    Each branch gets a fresh continuation and a fresh root from the identical
    particle inputs. The constructor is responsible for public reconstruction
    and history validation. Nothing here calls private-clone determinization.
    """
    if (type(samples) is not int or not 1 <= samples <= 64
            or type(max_steps) is not int or not 1 <= max_steps <= 128):
        raise ValueError("shadow rollout budgets must be bounded positive integers")
    upcoming = sorted(
        (b for b in observation.blinds if b.status in {"SELECT", "UPCOMING"}),
        key=lambda b: {"SMALL": 0, "BIG": 1, "BOSS": 2}.get(b.kind, 3),
    )
    roots = shop_roots(observation)
    if not roots or not upcoming or upcoming[0].kind not in {"SMALL", "BIG"}:
        return BlindComparison(observation.digest(), (), (), "outside ordinary shop slice")
    blind = upcoming[0]
    rows = []
    for root in roots:
        row = []
        for index in range(samples):
            candidate = None
            try:
                candidate = root_factory(observation, history, nonce, index)
                continuation = continuation_factory()
                result = _run_blind(candidate, observation, history, root,
                                    continuation, blind.kind, blind.score, max_steps)
            except Exception as exc:
                result = BlindOutcome("rejected", 0, 0, blind.score,
                                      f"root_exception:{type(exc).__name__}:{exc}")
            finally:
                if candidate is not None:
                    try:
                        candidate.close()
                    except Exception as exc:
                        result = BlindOutcome("rejected", result.steps, result.chips,
                                              blind.score, f"close_exception:{type(exc).__name__}:{exc}")
            row.append(result)
        rows.append(tuple(row))
    return BlindComparison(observation.digest(), tuple(action_to_data(a) for a in roots),
                           tuple(rows))


def compare_ante(
    observation: PublicObservation,
    history: tuple[PublicHistoryStep, ...],
    *,
    root_factory: RootFactory,
    continuation_factory: Callable[[], PublicPolicy],
    samples: int = 8,
    max_steps: int = 200,
    antes: int = 1,
    nonce: str = "public-ante-v1",
    roots: tuple[PublicAction, ...] | None = None,
) -> BlindComparison:
    """Compare non-reorder shop roots through one or two antes, capped at eight.

    Every branch is freshly reconstructed from the same public particle inputs.
    Continuations control every subsequent phase; failures never become losses.
    """
    if (type(samples) is not int or not 1 <= samples <= 64
            or type(max_steps) is not int or not 1 <= max_steps <= 512
            or type(antes) is not int or not 1 <= antes <= 2):
        raise ValueError("ante rollout budgets must be bounded positive integers")
    if observation.phase != Phase.SHOP:
        return BlindComparison(observation.digest(), (), (), "outside ante shop slice")
    if roots is None:
        roots = tuple(a for a in iter_legal_actions(observation)
                      if not isinstance(a, (ReorderHand, ReorderJokers)))
    else:
        if type(roots) is not tuple or not roots:
            raise ValueError("ante rollout roots must be a nonempty tuple")
        canonical_roots: list[dict[str, object]] = []
        for root in roots:
            if isinstance(root, (ReorderConsumables, ReorderHand, ReorderJokers)):
                raise ValueError("ante rollout roots must not reorder")
            try:
                canonical = action_to_data(root)
            except Exception as exc:
                raise ValueError("ante rollout roots must be legal public actions") from exc
            if any(canonical == existing for existing in canonical_roots):
                raise ValueError("ante rollout roots must not contain duplicates")
            if not is_legal(observation, root):
                raise ValueError("ante rollout roots must be legal for the observation")
            canonical_roots.append(canonical)
    rows = []
    for root in roots:
        row = []
        for index in range(samples):
            candidate = None
            result = BlindOutcome("rejected", 0, observation.round.chips,
                                  _current_target(observation, 0), "uninitialized")
            try:
                candidate = root_factory(observation, history, nonce, index)
                continuation = continuation_factory()
                if candidate.current_public is None:
                    result = BlindOutcome("rejected", 0, result.chips, result.target,
                                          "missing_root_public")
                else:
                    result = _run_ante(candidate, observation, history, root,
                                       continuation, max_steps, antes)
            except Exception as exc:
                result = BlindOutcome("rejected", result.steps, result.chips, result.target,
                                      f"root_exception:{type(exc).__name__}:{exc}")
            finally:
                if candidate is not None:
                    try:
                        candidate.close()
                    except Exception as exc:
                        result = BlindOutcome("rejected", result.steps, result.chips,
                                              result.target, f"close_exception:{type(exc).__name__}:{exc}")
            row.append(result)
        rows.append(tuple(row))
    return BlindComparison(observation.digest(), tuple(action_to_data(a) for a in roots),
                           tuple(rows))


def _current_target(observation, previous):
    return next((b.score for b in observation.blinds if b.status == "CURRENT"), previous)


def _run_ante(candidate, observation, history, root, continuation, max_steps, antes):
    current = observation
    trajectory = list(history)
    action = root
    target = _current_target(current, 0)
    target_ante = min(8, observation.antes_cleared + antes)
    steps = 0
    try:
        for step in range(1, max_steps + 1):
            if not is_legal(current, action):
                return BlindOutcome("rejected", steps, current.round.chips, target,
                                    "illegal_continuation")
            steps = step
            result = candidate.step(action)
            after = candidate.current_public
            if result.status != "accepted" or result.after is None or after is None:
                return BlindOutcome("rejected", steps, current.round.chips, target,
                                    f"step_{result.status}:missing_public_or_rejected")
            trajectory.append(PublicHistoryStep(current, action, after))
            current = after
            target = _current_target(current, target)
            if current.antes_cleared >= target_ante:
                return BlindOutcome("cleared", steps, current.round.chips, target)
            if current.terminal:
                return BlindOutcome("lost", steps, current.round.chips, target)
            if steps < max_steps:
                action = continuation.choose_action(
                    current, lambda: iter_legal_actions(current), tuple(trajectory))
        return BlindOutcome("censored", steps, current.round.chips, target, "max_steps")
    except Exception as exc:
        return BlindOutcome("rejected", steps, current.round.chips, target,
                            f"rollout_exception:{type(exc).__name__}:{exc}")


def _run_blind(candidate, observation, history, root, continuation,
               blind_kind, target, max_steps):
    current = observation
    trajectory = list(history)
    action = root
    started = False
    for step in range(1, max_steps + 1):
        if not is_legal(current, action):
            return BlindOutcome("rejected", step - 1, current.round.chips, target,
                                "illegal_continuation")
        try:
            result = candidate.step(action)
        except Exception as exc:
            return BlindOutcome("rejected", step, current.round.chips, target,
                                f"step_exception:{type(exc).__name__}:{exc}")
        after = candidate.current_public
        if result.status != "accepted" or result.after is None or after is None:
            return BlindOutcome("rejected", step, current.round.chips, target,
                                f"step_{result.status}")
        trajectory.append(PublicHistoryStep(current, action, after))
        if isinstance(action, SelectBlind):
            active = [b for b in after.blinds if b.status == "CURRENT"]
            if (len(active) != 1 or active[0].kind != blind_kind
                    or active[0].score != target):
                return BlindOutcome("rejected", step, after.round.chips, target,
                                    "unexpected_next_blind")
            started = True
        current = after
        if started and current.terminal:
            return BlindOutcome("lost", step, current.round.chips, target)
        if started and current.phase == Phase.ROUND_EVAL:
            # Includes a legitimate Mr. Bones rescue; never trust raw won alone.
            return BlindOutcome("cleared", step, current.round.chips, target)
        if current.phase == Phase.SHOP and not started:
            action = LeaveShop()
        elif current.phase == Phase.BLIND_SELECT and not started:
            action = SelectBlind()
        elif current.phase == Phase.SELECTING_HAND and started:
            try:
                action = continuation.choose_action(
                    current, lambda: iter_legal_actions(current), tuple(trajectory))
            except Exception as exc:
                return BlindOutcome("rejected", step, current.round.chips, target,
                                    f"policy_exception:{type(exc).__name__}:{exc}")
            if not isinstance(action, (PlayCards, DiscardCards, ReorderHand, ReorderJokers)):
                return BlindOutcome("rejected", step, current.round.chips, target,
                                    "unsupported_continuation_action")
        else:
            return BlindOutcome("rejected", step, current.round.chips, target,
                                "outside_blind_slice")
    return BlindOutcome("censored", max_steps, current.round.chips, target, "max_steps")
