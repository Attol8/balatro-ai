"""Small public-information baselines for coverage and later comparison.

These policies are deliberately not learning agents.  They exist to drive
organic public actions through both kernels and expose the first divergence.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import combinations, islice
from typing import Literal

from balatro_ai_v2.actions import (
    BuyPack,
    BuyShopCard,
    BuyVoucher,
    CashOut,
    ChoosePackCard,
    ConsumableSlot,
    DiscardCards,
    HandSlot,
    LeaveShop,
    PlayCards,
    PublicAction,
    ReorderConsumables,
    ReorderHand,
    ReorderJokers,
    RerollShop,
    SelectBlind,
    SkipBlind,
    SkipPack,
    UseConsumable,
    action_to_data,
    is_legal,
)
from balatro_ai_v2.belief import PublicDrawBelief
from balatro_ai_v2.policy import ActionSource, PublicHistoryStep, PublicPolicy
from balatro_ai_v2.public_state import (
    HandStat,
    HiddenHandCard,
    Phase,
    PublicObservation,
    VisiblePlayingCard,
)


_RANK_CHIPS = {"A": 11, "K": 10, "Q": 10, "J": 10, "T": 10, **{str(value): value for value in range(2, 10)}}
_RANK_ORDER = {"A": 14, "K": 13, "Q": 12, "J": 11, "T": 10, **{str(value): value for value in range(2, 10)}}
_REORDER_TYPES = (ReorderHand, ReorderJokers, ReorderConsumables)
_MAX_TACTICAL_CANDIDATES = 2048
_MAX_PUBLIC_ACTIONS = 256
_MAX_PUBLIC_DRAW_BRANCHES = 512
PUBLIC_BASELINE_NAMES = ("random", "greedy", "tactical")


def build_public_baseline(name: str, policy_seed: str) -> tuple[PublicPolicy, str]:
    if name == "random":
        return DeterministicRandomPolicy(policy_seed), f"DeterministicRandomPolicy:{policy_seed}"
    if name == "greedy":
        return GreedyImmediatePolicy(), "GreedyImmediatePolicy"
    if name == "tactical":
        return PublicBeliefTacticalPolicy(), "PublicBeliefTacticalPolicy"
    raise ValueError(f"unknown public baseline {name!r}")


@dataclass(frozen=True, slots=True)
class DeterministicRandomPolicy:
    """Bounded random legal-action control using public state only."""

    policy_seed: str = "random-v1"

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        actions = _bounded_actions(legal_actions())
        if not actions:
            raise RuntimeError(f"no bounded public action for {observation.phase.value}")
        payload = f"{self.policy_seed}\0{len(history)}\0{observation.digest()}"
        number = int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")
        return actions[number % len(actions)]


@dataclass(frozen=True, slots=True)
class GreedyImmediatePolicy:
    """Immediate visible-score baseline with no strategic shop model."""

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        del history
        if observation.phase == Phase.SELECTING_HAND:
            return _best_play(observation, 0)[0]
        return _passive_control_action(observation, legal_actions)


@dataclass(frozen=True, slots=True)
class PublicBeliefTacticalPolicy:
    """One-ply public expectimax over a bounded visible-score surrogate."""

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        del history
        if observation.phase == Phase.SELECTING_HAND:
            return _belief_tactical_action(observation)
        return _passive_control_action(observation, legal_actions)


@dataclass(frozen=True, slots=True)
class DeterministicCoveragePolicy:
    """Exercise public action families without consulting privileged state."""

    policy_seed: str = "coverage-v1"
    max_shop_actions: int = 3
    pack_strategy: Literal["mixed", "skip", "pick"] = "mixed"
    coverage_mode: Literal["default", "extended"] = "default"

    def __post_init__(self) -> None:
        if self.max_shop_actions < 0:
            raise ValueError("max_shop_actions must be non-negative")
        if self.coverage_mode not in {"default", "extended"}:
            raise ValueError(f"unsupported coverage mode {self.coverage_mode!r}")

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        if observation.phase == Phase.BLIND_SELECT:
            actions = _bounded_actions(legal_actions())
            skips = [action for action in actions if isinstance(action, SkipBlind)]
            if skips and self._number(observation, history, "blind") % 5 == 0:
                return skips[0]
            return next(action for action in actions if isinstance(action, SelectBlind))

        if observation.phase == Phase.SELECTING_HAND:
            planet = self._held_planet(observation)
            if self.coverage_mode == "extended" and planet is not None:
                return planet
            best, hand_name = _best_play(observation, self._number(observation, history, "tactical"))
            discard = _coverage_discard(observation, best, hand_name)
            if discard is not None:
                return discard
            return best

        if observation.phase == Phase.ROUND_EVAL:
            return CashOut()

        if observation.phase == Phase.SHOP:
            actions = _bounded_actions(legal_actions())
            shop_steps = _current_shop_action_count(history)
            if shop_steps >= self.max_shop_actions:
                return next(action for action in actions if isinstance(action, LeaveShop))
            rerolls = [action for action in actions if isinstance(action, RerollShop)]
            if self.coverage_mode == "extended" and rerolls and shop_steps == 0:
                return rerolls[0]
            planet = self._held_planet(observation)
            if self.coverage_mode == "extended" and planet is not None:
                return planet
            pack_purchases = [action for action in actions if isinstance(action, BuyPack)]
            if pack_purchases and self.pack_strategy != "mixed" and shop_steps == 0:
                return self._pick(pack_purchases, observation, history, "pack-buy")
            purchases = [
                action for action in actions if isinstance(action, (BuyShopCard, BuyPack, BuyVoucher))
            ]
            if purchases and (shop_steps == 0 or self._number(observation, history, "buy") % 3):
                return self._pick(purchases, observation, history, "buy-choice")
            if rerolls and shop_steps == 0:
                return rerolls[0]
            return next(action for action in actions if isinstance(action, LeaveShop))

        if observation.phase == Phase.PACK:
            actions = _bounded_actions(legal_actions())
            if self.pack_strategy == "skip":
                return next(action for action in actions if isinstance(action, SkipPack))
            choices = [action for action in actions if isinstance(action, ChoosePackCard)]
            if choices and (
                self.pack_strategy == "pick" or self._number(observation, history, "pack") % 4
            ):
                return self._pick(choices, observation, history, "pack-choice")
            return next(action for action in actions if isinstance(action, SkipPack))

        raise RuntimeError(f"no coverage action for {observation.phase.value}")

    @staticmethod
    def _held_planet(observation: PublicObservation) -> UseConsumable | None:
        for index, item in enumerate(observation.consumables):
            if item.kind.upper() == "PLANET":
                return UseConsumable(ConsumableSlot(index))
        return None

    def _pick(
        self,
        actions: list[PublicAction],
        observation: PublicObservation,
        history: tuple[PublicHistoryStep, ...],
        label: str,
    ) -> PublicAction:
        ordered = sorted(actions, key=lambda action: json.dumps(action_to_data(action), sort_keys=True))
        return ordered[self._number(observation, history, label) % len(ordered)]

    def _number(
        self,
        observation: PublicObservation,
        history: tuple[PublicHistoryStep, ...],
        label: str,
    ) -> int:
        payload = f"{self.policy_seed}\0{label}\0{len(history)}\0{observation.digest()}"
        return int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


def _best_play(observation: PublicObservation, tie_seed: int) -> tuple[PlayCards, str]:
    action, hand_name, _ = _best_play_with_score(observation, tie_seed)
    return action, hand_name


def _best_play_with_score(
    observation: PublicObservation,
    tie_seed: int,
    hand_stats: Mapping[str, HandStat] | None = None,
) -> tuple[PlayCards, str, int | Fraction]:
    slots = tuple(HandSlot(index) for index in range(len(observation.hand)))
    maximum = min(5, observation.selection_limit, len(slots))
    candidate_slots = islice(
        (selected for size in range(maximum, 0, -1) for selected in combinations(slots, size)),
        _MAX_TACTICAL_CANDIDATES,
    )
    stats = hand_stats if hand_stats is not None else {hand.name: hand for hand in observation.hand_stats}
    best: tuple[int | Fraction, int, tuple[HandSlot, ...], str] | None = None
    for selected in candidate_slots:
        cards = tuple(observation.hand[slot.value] for slot in selected)
        hand_name = _classify(cards)
        stat = stats.get(hand_name)
        base_chips = stat.chips if stat is not None else 0
        base_mult = stat.mult if stat is not None else 1
        card_chips = sum(_card_chips(card) for card in cards)
        mult_bonus = sum(4 for card in cards if isinstance(card, VisiblePlayingCard) and card.enhancement == "MULT")
        multiplier: int | Fraction = 1
        for card in cards:
            if isinstance(card, VisiblePlayingCard) and card.enhancement == "GLASS":
                multiplier *= 2
            if isinstance(card, VisiblePlayingCard) and card.edition == "POLYCHROME":
                multiplier *= Fraction(3, 2)
        score = (base_chips + card_chips) * (base_mult + mult_bonus) * multiplier
        tie = (tie_seed ^ sum((slot.value + 1) * 0x9E3779B1 for slot in selected)) & 0xFFFFFFFF
        candidate = (score, tie, selected, hand_name)
        if best is None or (candidate[0], candidate[1]) > (best[0], best[1]):
            best = candidate
    if best is None:
        raise RuntimeError("selecting-hand state has no legal cards")
    score, _, selected, hand_name = best
    return PlayCards(selected), hand_name, score


def _belief_tactical_action(observation: PublicObservation) -> PublicAction:
    hand_stats = {hand.name: hand for hand in observation.hand_stats}
    play, _, current_score = _best_play_with_score(observation, 0, hand_stats)
    if (
        observation.round.discards_left <= 0
        or any(isinstance(card, HiddenHandCard) for card in observation.hand)
        or not observation.hand
    ):
        return play
    try:
        belief = PublicDrawBelief.from_observation(observation)
    except ValueError:
        return play
    if belief.draw_count == 0:
        return play

    candidates = tuple(HandSlot(index) for index in range(len(observation.hand)))
    if len(candidates) * len(belief.remaining_deck) > _MAX_PUBLIC_DRAW_BRANCHES:
        return play

    ranked: list[tuple[Fraction, int, DiscardCards]] = []
    for slot in candidates:
        discard = DiscardCards((slot,))
        if not is_legal(observation, discard):
            continue
        weighted_score = Fraction(0)
        for entry in belief.remaining_deck:
            hand = list(observation.hand)
            hand[slot.value] = entry.card
            hypothetical = replace(observation, hand=tuple(hand))
            _, _, score = _best_play_with_score(hypothetical, 0, hand_stats)
            weighted_score += entry.count * score
        expected_score = weighted_score / belief.draw_count
        ranked.append((expected_score, -slot.value, discard))
    if not ranked:
        return play
    expected_score, _, discard = max(ranked, key=lambda item: (item[0], item[1]))
    return discard if expected_score > current_score else play


def _passive_control_action(
    observation: PublicObservation,
    legal_actions: ActionSource,
) -> PublicAction:
    actions = _bounded_actions(legal_actions())
    expected = {
        Phase.BLIND_SELECT: SelectBlind,
        Phase.ROUND_EVAL: CashOut,
        Phase.SHOP: LeaveShop,
        Phase.PACK: SkipPack,
    }.get(observation.phase)
    if expected is None:
        raise RuntimeError(f"no passive action for {observation.phase.value}")
    return next(action for action in actions if isinstance(action, expected))


def _coverage_discard(
    observation: PublicObservation,
    best: PlayCards,
    hand_name: str,
) -> DiscardCards | None:
    if observation.round.discards_left <= 0 or observation.round.discards_used >= 2:
        return None
    if hand_name not in {"High Card", "Pair", "Two Pair", "Three of a Kind"}:
        return None

    visible = {
        index: card for index, card in enumerate(observation.hand) if isinstance(card, VisiblePlayingCard)
    }
    rank_counts = Counter(card.rank for card in visible.values())
    suit_counts = Counter(card.suit for card in visible.values())
    kept = {index for index, card in visible.items() if rank_counts[card.rank] >= 2}
    if suit_counts:
        suit, count = suit_counts.most_common(1)[0]
        if count >= 3 and count > len(kept):
            kept = {index for index, card in visible.items() if card.suit == suit}

    candidates = [
        index
        for index, card in sorted(visible.items(), key=lambda pair: (_card_chips(pair[1]), pair[0]))
        if index not in kept
    ]
    if not candidates:
        best_slots = {slot.value for slot in best.cards}
        candidates = [index for index in visible if index not in best_slots]
    limit = min(5, observation.selection_limit, len(candidates))
    return DiscardCards(tuple(HandSlot(index) for index in candidates[:limit])) if limit else None


def _classify(cards: tuple[VisiblePlayingCard | HiddenHandCard, ...]) -> str:
    playing = tuple(
        card for card in cards if isinstance(card, VisiblePlayingCard) and card.enhancement != "STONE"
    )
    ranks = [_RANK_ORDER.get(card.rank, 0) for card in playing]
    counts = sorted(Counter(ranks).values(), reverse=True)
    flush = len(playing) == 5 and len({card.suit for card in playing}) == 1
    unique = sorted(set(ranks))
    straight = len(unique) == 5 and (
        unique[-1] - unique[0] == 4 or unique == [2, 3, 4, 5, 14]
    )
    if straight and flush:
        return "Straight Flush"
    if counts[:1] == [4]:
        return "Four of a Kind"
    if counts == [3, 2]:
        return "Full House"
    if flush:
        return "Flush"
    if straight:
        return "Straight"
    if counts[:1] == [3]:
        return "Three of a Kind"
    if counts[:2] == [2, 2]:
        return "Two Pair"
    if counts[:1] == [2]:
        return "Pair"
    return "High Card"


def _card_chips(card: VisiblePlayingCard | HiddenHandCard) -> int:
    if not isinstance(card, VisiblePlayingCard):
        return 0
    if card.enhancement == "STONE":
        return 50
    chips = _RANK_CHIPS.get(card.rank, 0)
    if card.enhancement == "BONUS":
        chips += 30
    if card.edition == "FOIL":
        chips += 50
    return chips


def _bounded_actions(actions: Iterator[PublicAction]) -> list[PublicAction]:
    return [
        action
        for action in islice(actions, _MAX_PUBLIC_ACTIONS)
        if not isinstance(action, _REORDER_TYPES)
    ]


def _current_shop_action_count(history: tuple[PublicHistoryStep, ...]) -> int:
    count = 0
    for step in reversed(history):
        if step.before.phase == Phase.ROUND_EVAL and step.after.phase == Phase.SHOP:
            break
        if step.before.phase == Phase.SHOP:
            count += 1
    return count
