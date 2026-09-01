"""Learner-free, public-information search for the shop before a boss.

This is deliberately a narrow promotion slice.  It compares leaving the shop
with one directly buyable Joker, then rolls the visible boss using shared
public deck particles.  No live seed, engine clone, or future shop enters the
policy.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from fractions import Fraction

from balatro_ai_v2.actions import (
    BuyShopCard,
    LeaveShop,
    PublicAction,
    ShopSlot,
    action_to_data,
    is_legal,
    iter_legal_actions,
)
from balatro_ai_v2.baselines import (
    PublicStrategicPolicy,
    _best_available_play,
    _coverage_discard,
    _joker_value,
    _play_score,
)
from balatro_ai_v2.policy import ActionSource, PublicHistoryStep, PublicPolicy
from balatro_ai_v2.public_state import (
    HandStat,
    Phase,
    PublicBlind,
    PublicItem,
    PublicObservation,
    VisiblePlayingCard,
)


_SUPPORTED_BOSSES = frozenset({"the wall", "violet vessel", "the needle", "the water"})
_SUPPORTED_JOKERS = frozenset(
    {
        "j_bull",
        "j_crafty",
        "j_droll",
        "j_greedy_joker",
        "j_gluttenous_joker",
        "j_joker",
        "j_lusty_joker",
        "j_mystic_summit",
        "j_scary_face",
        "j_wily",
    }
)
_RANK_SORT = {
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
    "7": 7,
    "8": 8,
    "9": 9,
    "T": 10,
    "J": 11,
    "Q": 12,
    "K": 13,
    "A": 14,
}
_SUIT_SORT = {"D": 1, "C": 2, "H": 3, "S": 4}


@dataclass(frozen=True, slots=True)
class ParticleResult:
    action: PublicAction
    wins: int
    particles: int
    mean_score: Fraction


@dataclass(frozen=True, slots=True)
class PreBossSearchDecision:
    root_digest: str
    public_history_digest: str
    blind_name: str
    results: tuple[ParticleResult, ...]
    baseline: PublicAction
    selected: PublicAction


@dataclass(slots=True)
class PublicPreBossSearchPolicy:
    """One-intervention Red/Gold search wrapped around the frozen heuristic."""

    search_nonce: str = "red-gold-preboss-v1"
    particles: int = 16
    minimum_particle_gain: int = 2
    max_joker_candidates: int = 3
    baseline: PublicPolicy = field(default_factory=PublicStrategicPolicy)
    last_decision: PreBossSearchDecision | None = field(default=None, init=False)
    decisions: list[PreBossSearchDecision] = field(default_factory=list, init=False)
    _searched_shop: tuple[int, int] | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.particles <= 0:
            raise ValueError("particles must be positive")
        if self.minimum_particle_gain <= 0:
            raise ValueError("minimum particle gain must be positive")
        if self.max_joker_candidates <= 0:
            raise ValueError("max joker candidates must be positive")

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        self.last_decision = None
        if not history and observation.phase == Phase.BLIND_SELECT:
            self._searched_shop = None
            self.decisions.clear()

        baseline_action = self.baseline.choose_action(observation, legal_actions, history)
        blind = _eligible_next_blind(observation)
        shop_key = (observation.ante, observation.round_no)
        if (
            blind is None
            or not _supports_shop_rollout(observation)
            or self._searched_shop == shop_key
            or not _represented_baseline_action(observation, baseline_action)
        ):
            return baseline_action

        candidates = _candidate_buys(observation, self.max_joker_candidates)
        if not candidates:
            return baseline_action

        history_digest = _public_history_digest(history)
        tapes = tuple(
            _public_deck_particle(
                observation,
                history_digest=history_digest,
                nonce=self.search_nonce,
                particle=index,
            )
            for index in range(self.particles)
        )
        actions: tuple[PublicAction, ...] = (LeaveShop(), *candidates)
        if baseline_action not in actions:
            return baseline_action
        results = tuple(
            _evaluate_action(observation, blind, action, tapes) for action in actions
        )
        baseline_result = next(result for result in results if result.action == baseline_action)
        best = max(
            results,
            key=lambda result: (
                result.wins,
                result.mean_score,
                -_action_slot(result.action),
            ),
        )
        selected = (
            best.action
            if best.action != baseline_action
            and best.wins >= baseline_result.wins + self.minimum_particle_gain
            else baseline_action
        )
        self._searched_shop = shop_key
        decision = PreBossSearchDecision(
            root_digest=observation.digest(),
            public_history_digest=history_digest,
            blind_name=blind.name,
            results=results,
            baseline=baseline_action,
            selected=selected,
        )
        self.last_decision = decision
        self.decisions.append(decision)
        return selected


def _eligible_next_blind(observation: PublicObservation) -> PublicBlind | None:
    if (
        observation.phase != Phase.SHOP
        or observation.deck.upper() != "RED"
        or observation.stake.upper() != "GOLD"
    ):
        return None
    next_kind = {1: "BIG", 2: "BOSS"}.get(observation.round_no % 3)
    if next_kind is None:
        return None
    blind = next(
        (
            value
            for value in observation.blinds
            if value.kind == next_kind and value.status in {"UPCOMING", "SELECT"}
        ),
        None,
    )
    if blind is None or blind.score <= 0:
        return None
    if blind.kind == "BOSS" and blind.name.lower() not in _SUPPORTED_BOSSES:
        return None
    return blind


def _represented_baseline_action(
    observation: PublicObservation,
    action: PublicAction,
) -> bool:
    if isinstance(action, LeaveShop):
        return True
    return (
        isinstance(action, BuyShopCard)
        and action.card.value < len(observation.shop)
        and observation.shop[action.card.value].key in _SUPPORTED_JOKERS
    )


def _candidate_buys(
    observation: PublicObservation,
    maximum: int,
) -> tuple[BuyShopCard, ...]:
    candidates: list[tuple[int, int, int, BuyShopCard]] = []
    for index, item in enumerate(observation.shop):
        action = BuyShopCard(ShopSlot(index))
        if (
            item.kind.upper() != "JOKER"
            or item.key not in _SUPPORTED_JOKERS
            or item.edition not in {None, "FOIL"}
            or item.rental
            or item.debuffed
            or item.perishable_rounds == 0
            or not is_legal(observation, action)
        ):
            continue
        candidates.append(
            (
                _joker_value(item),
                -(item.buy_cost or 0),
                -index,
                action,
            )
        )
    candidates.sort(reverse=True)
    return tuple(entry[3] for entry in candidates[:maximum])


def _public_deck_particle(
    observation: PublicObservation,
    *,
    history_digest: str,
    nonce: str,
    particle: int,
) -> tuple[VisiblePlayingCard, ...]:
    deck = [
        entry.card
        for entry in observation.remaining_deck
        for _ in range(entry.count)
    ]
    payload = "\0".join(
        (
            nonce,
            observation.digest(),
            history_digest,
            str(particle),
        )
    )
    seed = int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:16], "big")
    random.Random(seed).shuffle(deck)
    return tuple(deck)


def _evaluate_action(
    observation: PublicObservation,
    boss: PublicBlind,
    action: PublicAction,
    tapes: tuple[tuple[VisiblePlayingCard, ...], ...],
) -> ParticleResult:
    joker: PublicItem | None = None
    if isinstance(action, BuyShopCard):
        joker = observation.shop[action.card.value]
    scores = tuple(_simulate_boss(observation, boss, joker, tape) for tape in tapes)
    return ParticleResult(
        action=action,
        wins=sum(score >= boss.score for score in scores),
        particles=len(scores),
        mean_score=sum(scores, Fraction(0)) / len(scores),
    )


def _simulate_boss(
    observation: PublicObservation,
    boss: PublicBlind,
    bought_joker: PublicItem | None,
    tape: tuple[VisiblePlayingCard, ...],
) -> Fraction:
    deck = list(tape)
    hand_size = max(1, observation.hand_limit)
    hand = deck[:hand_size]
    hand.sort(key=_hand_sort_key, reverse=True)
    del deck[:hand_size]
    jokers = observation.jokers + ((bought_joker,) if bought_joker is not None else ())
    money = observation.money - ((bought_joker.buy_cost or 0) if bought_joker else 0)
    previous_total_hands = observation.round.hands_left + observation.round.hands_played
    hands = max(1, previous_total_hands)
    if boss.name.lower() == "the needle":
        hands = 1
    previous_total_discards = observation.round.discards_left + observation.round.discards_used
    discards = 0 if boss.name.lower() == "the water" else previous_total_discards
    stats = tuple(replace(stat, played_this_round=0) for stat in observation.hand_stats)
    total = Fraction(0)

    hands_left = hands
    hands_played = 0
    discards_left = discards
    discards_used = 0
    for _ in range(hands + discards):
        if not hand or hands_left <= 0:
            break
        tactical = replace(
            observation,
            phase=Phase.SELECTING_HAND,
            money=money,
            round=replace(
                observation.round,
                chips=int(total),
                hands_left=hands_left,
                discards_left=discards_left,
                hands_played=hands_played,
                discards_used=discards_used,
            ),
            hand=tuple(hand),
            required_hand_slots=(),
            draw_count=len(deck),
            hand_stats=stats,
            jokers=jokers,
            shop=(),
            vouchers=(),
            packs=(),
        )
        legal = list(iter_legal_actions(tactical))
        play, hand_name = _best_available_play(tactical, legal)
        discard = _coverage_discard(tactical, play, hand_name)
        selected = discard if discard is not None and discard in legal else play
        if discard is not None and selected == discard:
            discards_left -= 1
            discards_used += 1
        else:
            score, _ = _play_score(
                tactical,
                play.cards,
                {stat.name: stat for stat in stats},
            )
            total += math.floor(score)
            stats = _increment_hand_stat(stats, hand_name)
            hands_left -= 1
            hands_played += 1
        for slot in sorted((card.value for card in selected.cards), reverse=True):
            del hand[slot]
        draw = min(hand_size - len(hand), len(deck))
        hand.extend(deck[:draw])
        del deck[:draw]
        hand.sort(key=_hand_sort_key, reverse=True)
        if total >= boss.score:
            break
    return total


def _increment_hand_stat(stats: tuple[HandStat, ...], hand_name: str) -> tuple[HandStat, ...]:
    changed = False
    values: list[HandStat] = []
    for stat in stats:
        if stat.name == hand_name:
            values.append(
                replace(
                    stat,
                    played=stat.played + 1,
                    played_this_round=stat.played_this_round + 1,
                )
            )
            changed = True
        else:
            values.append(stat)
    if not changed:
        raise ValueError(f"missing public hand stat for {hand_name!r}")
    return tuple(values)


def _supports_shop_rollout(observation: PublicObservation) -> bool:
    cards = tuple(entry.card for entry in observation.remaining_deck)
    return (
        not observation.consumables
        and all(joker.key in _SUPPORTED_JOKERS for joker in observation.jokers)
        and all(joker.edition in {None, "FOIL"} and not joker.debuffed for joker in observation.jokers)
        and not any("observatory" in voucher.lower() for voucher in observation.used_vouchers)
        and all(card.enhancement is None for card in cards)
        and all(card.edition is None for card in cards)
        and all(card.seal is None for card in cards)
        and all(not card.debuffed for card in cards)
        and all(card.permanent_bonus == 0 for card in cards)
    )


def _hand_sort_key(card: VisiblePlayingCard) -> tuple[int, int]:
    return (_RANK_SORT[card.rank], _SUIT_SORT[card.suit])


def _public_history_digest(history: tuple[PublicHistoryStep, ...]) -> str:
    rows: Iterator[dict[str, object]] = (
        {
            "before": step.before.digest(),
            "action": action_to_data(step.action),
            "after": step.after.digest(),
        }
        for step in history[-64:]
    )
    payload = json.dumps(tuple(rows), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _action_slot(action: PublicAction) -> int:
    return action.card.value if isinstance(action, BuyShopCard) else -1


def preboss_search_legal_actions(observation: PublicObservation) -> ActionSource:
    """Convenience source used by tests and direct public runners."""

    return lambda: iter_legal_actions(observation)
