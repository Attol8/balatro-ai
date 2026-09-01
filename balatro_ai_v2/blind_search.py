"""Finite-horizon public belief search within the current blind."""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import combinations

from balatro_ai_v2.actions import (
    DiscardCards,
    HandSlot,
    PlayCards,
    PublicAction,
    action_to_data,
    is_legal,
)
from balatro_ai_v2.baselines import _coverage_discard, _play_score
from balatro_ai_v2.joker_rules import (
    TACTICAL_EXACT_JOKERS,
    exact_joker_multiplicity,
    faceless_discard_reward,
)
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.preboss_search import ParticleResult
from balatro_ai_v2.public_state import (
    HandStat,
    HiddenHandCard,
    Phase,
    PublicObservation,
    VisiblePlayingCard,
)


_SUPPORTED_CURRENT_BLINDS = frozenset({"small blind", "big blind"})
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
class BlindSearchDecision:
    root_digest: str
    results: tuple[ParticleResult, ...]
    baseline: PlayCards | DiscardCards
    selected: PlayCards | DiscardCards
    transitions_evaluated: int
    score_evaluations: int


@dataclass(frozen=True, slots=True)
class _RolloutState:
    hand: tuple[VisiblePlayingCard, ...]
    deck_index: int
    chips: Fraction
    money: int
    hands_left: int
    discards_left: int
    hands_played: int
    discards_used: int
    hand_stats: tuple[HandStat, ...]


@dataclass(slots=True)
class PublicBlindBeliefSearch:
    """Compare roots on shared particles under one executable continuation."""

    search_nonce: str = "red-gold-blind-v1"
    particles: int = 8
    minimum_particle_gain: int = 2
    root_play_width: int = 3
    root_discard_width: int = 3
    max_play_candidates_per_state: int = 1000
    last_decision: BlindSearchDecision | None = None

    def __post_init__(self) -> None:
        values = (
            self.particles,
            self.minimum_particle_gain,
            self.root_play_width,
            self.root_discard_width,
            self.max_play_candidates_per_state,
        )
        if min(values) <= 0:
            raise ValueError("blind search bounds must be positive")

    def choose_action(
        self,
        observation: PublicObservation,
        baseline: PublicAction,
        history: tuple[PublicHistoryStep, ...],
    ) -> PlayCards | DiscardCards:
        self.last_decision = None
        if not isinstance(baseline, (PlayCards, DiscardCards)):
            raise ValueError("blind search requires a tactical baseline action")
        if (
            observation.phase != Phase.SELECTING_HAND
            or observation.deck.upper() != "RED"
            or observation.stake.upper() != "GOLD"
            or any(isinstance(card, HiddenHandCard) for card in observation.hand)
            or observation.required_hand_slots
            or not _supports_rollout(observation)
            or _play_candidate_count(observation) > self.max_play_candidates_per_state
        ):
            return baseline
        current = next(
            (blind for blind in observation.blinds if blind.status == "CURRENT"),
            None,
        )
        if (
            current is None
            or current.name.lower() not in _SUPPORTED_CURRENT_BLINDS
            or current.score <= observation.round.chips
        ):
            return baseline

        candidates, root_score_evaluations = _rank_actions(
            observation,
            play_width=self.root_play_width,
            discard_width=self.root_discard_width,
        )
        if baseline not in candidates:
            candidates = (baseline, *candidates)
        candidates = tuple(dict.fromkeys(candidates))
        root_digest = observation.digest()
        tapes = _public_tapes(
            observation,
            history,
            self.search_nonce,
            self.particles,
            root_digest,
        )
        results: list[ParticleResult] = []
        transitions = 0
        score_evaluations = root_score_evaluations
        for action in candidates:
            wins = 0
            total_chips = Fraction(0)
            for tape in tapes:
                won, chips, evaluated, scored = self._rollout(
                    observation,
                    action,
                    tape,
                    current.score,
                )
                wins += int(won)
                total_chips += chips
                transitions += evaluated
                score_evaluations += scored
            results.append(
                ParticleResult(
                    action=action,
                    wins=wins,
                    particles=len(tapes),
                    mean_score=total_chips / len(tapes),
                )
            )
        baseline_result = next(result for result in results if result.action == baseline)
        best = max(
            results,
            key=lambda result: (
                result.wins,
                result.mean_score,
                _action_tie_break(result.action),
            ),
        )
        selected = (
            best.action
            if best.action != baseline
            and best.wins >= baseline_result.wins + self.minimum_particle_gain
            else baseline
        )
        if not isinstance(selected, (PlayCards, DiscardCards)):
            raise AssertionError("blind search selected a non-tactical action")
        self.last_decision = BlindSearchDecision(
            root_digest=root_digest,
            results=tuple(results),
            baseline=baseline,
            selected=selected,
            transitions_evaluated=transitions,
            score_evaluations=score_evaluations,
        )
        return selected

    def _rollout(
        self,
        observation: PublicObservation,
        root_action: PlayCards | DiscardCards,
        tape: tuple[VisiblePlayingCard, ...],
        target: int,
    ) -> tuple[bool, Fraction, int, int]:
        initial = _RolloutState(
            hand=tuple(card for card in observation.hand if isinstance(card, VisiblePlayingCard)),
            deck_index=0,
            chips=Fraction(observation.round.chips),
            money=observation.money,
            hands_left=observation.round.hands_left,
            discards_left=observation.round.discards_left,
            hands_played=observation.round.hands_played,
            discards_used=observation.round.discards_used,
            hand_stats=observation.hand_stats,
        )
        first = _transition(observation, initial, root_action, tape)
        evaluated = 1
        if first.chips >= target:
            return True, first.chips, evaluated, 0
        state = first
        score_evaluations = 0
        maximum_depth = first.hands_left + first.discards_left
        for _ in range(maximum_depth):
            if state.chips >= target:
                return True, state.chips, evaluated, score_evaluations
            if state.hands_left <= 0 or not state.hand:
                break
            hypothetical = _observation_for_state(observation, state, len(tape))
            action, scored = _continuation_action(hypothetical)
            score_evaluations += scored
            state = _transition(observation, state, action, tape)
            evaluated += 1
            if state.chips >= target:
                return True, state.chips, evaluated, score_evaluations
        return False, state.chips, evaluated, score_evaluations


def _rank_actions(
    observation: PublicObservation,
    *,
    play_width: int,
    discard_width: int,
) -> tuple[tuple[PlayCards | DiscardCards, ...], int]:
    stats = {stat.name: stat for stat in observation.hand_stats}
    plays: list[tuple[Fraction, int, tuple[int, ...], PlayCards]] = []
    slots = tuple(HandSlot(index) for index in range(len(observation.hand)))
    maximum = min(5, observation.selection_limit, len(slots))
    selections = tuple(
        selected
        for size in range(maximum, 0, -1)
        for selected in combinations(slots, size)
    )
    for selected in selections:
        score, _ = _play_score(observation, selected, stats)
        plays.append(
            (
                Fraction(score),
                -len(selected),
                tuple(-slot.value for slot in selected),
                PlayCards(selected),
            )
        )
    ranked_plays = [entry[3] for entry in sorted(plays, reverse=True)[:play_width]]
    best_slots = {slot.value for slot in ranked_plays[0].cards}
    discards: list[tuple[int, int, int, tuple[int, ...], DiscardCards]] = []
    if observation.round.discards_left > 0:
        for selected in selections:
            outside = sum(slot.value not in best_slots for slot in selected)
            overlap = len(selected) - outside
            discards.append(
                (
                    outside,
                    -overlap,
                    len(selected),
                    tuple(-slot.value for slot in selected),
                    DiscardCards(selected),
                )
            )
    ranked_discards = [entry[4] for entry in sorted(discards, reverse=True)[:discard_width]]
    return tuple((*ranked_plays, *ranked_discards)), len(selections)


def _continuation_action(
    observation: PublicObservation,
) -> tuple[PlayCards | DiscardCards, int]:
    ranked, scored = _rank_actions(observation, play_width=1, discard_width=0)
    play = ranked[0]
    if not isinstance(play, PlayCards):
        raise AssertionError("continuation ranking omitted a play")
    _, hand_name = _play_score(
        observation,
        play.cards,
        {stat.name: stat for stat in observation.hand_stats},
    )
    discard = _coverage_discard(observation, play, hand_name)
    if discard is not None and is_legal(observation, discard):
        return discard, scored + 1
    return play, scored + 1


def _play_candidate_count(observation: PublicObservation) -> int:
    maximum = min(5, observation.selection_limit, len(observation.hand))
    return sum(math.comb(len(observation.hand), size) for size in range(1, maximum + 1))


def _supports_rollout(observation: PublicObservation) -> bool:
    cards = (
        *(card for card in observation.hand if isinstance(card, VisiblePlayingCard)),
        *(entry.card for entry in observation.remaining_deck),
    )
    return (
        all(joker.key in TACTICAL_EXACT_JOKERS for joker in observation.jokers)
        and exact_joker_multiplicity(observation.jokers)
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


def _transition(
    root: PublicObservation,
    state: _RolloutState,
    action: PlayCards | DiscardCards,
    tape: tuple[VisiblePlayingCard, ...],
) -> _RolloutState:
    selected = tuple(slot.value for slot in action.cards)
    chips = state.chips
    money = state.money
    hands_left = state.hands_left
    discards_left = state.discards_left
    hands_played = state.hands_played
    discards_used = state.discards_used
    stats = state.hand_stats
    if isinstance(action, PlayCards):
        observation = _observation_for_state(root, state, len(tape))
        score, hand_name = _play_score(
            observation,
            action.cards,
            {stat.name: stat for stat in stats},
        )
        chips += math.floor(score)
        hands_left -= 1
        hands_played += 1
        stats = _increment_hand_stat(stats, hand_name)
    else:
        discarded = tuple(state.hand[index] for index in selected)
        money += faceless_discard_reward(root.jokers, discarded)
        discards_left -= 1
        discards_used += 1

    selected_set = set(selected)
    hand = [card for index, card in enumerate(state.hand) if index not in selected_set]
    draw_count = min(
        max(0, root.hand_limit - len(hand)),
        len(tape) - state.deck_index,
    )
    end = state.deck_index + draw_count
    hand.extend(tape[state.deck_index:end])
    hand.sort(key=_hand_sort_key, reverse=True)
    return _RolloutState(
        hand=tuple(hand),
        deck_index=end,
        chips=Fraction(chips),
        money=money,
        hands_left=hands_left,
        discards_left=discards_left,
        hands_played=hands_played,
        discards_used=discards_used,
        hand_stats=stats,
    )


def _observation_for_state(
    root: PublicObservation,
    state: _RolloutState,
    tape_size: int,
) -> PublicObservation:
    return replace(
        root,
        hand=state.hand,
        money=state.money,
        required_hand_slots=(),
        draw_count=max(0, tape_size - state.deck_index),
        round=replace(
            root.round,
            chips=int(state.chips),
            hands_left=state.hands_left,
            discards_left=state.discards_left,
            hands_played=state.hands_played,
            discards_used=state.discards_used,
        ),
        hand_stats=state.hand_stats,
    )


def _increment_hand_stat(stats: tuple[HandStat, ...], hand_name: str) -> tuple[HandStat, ...]:
    values: list[HandStat] = []
    found = False
    for stat in stats:
        if stat.name == hand_name:
            values.append(
                replace(
                    stat,
                    played=stat.played + 1,
                    played_this_round=stat.played_this_round + 1,
                )
            )
            found = True
        else:
            values.append(stat)
    if not found:
        raise ValueError(f"missing public hand stat for {hand_name!r}")
    return tuple(values)


def _public_tapes(
    observation: PublicObservation,
    history: tuple[PublicHistoryStep, ...],
    nonce: str,
    particles: int,
    root_digest: str,
) -> tuple[tuple[VisiblePlayingCard, ...], ...]:
    deck = [
        entry.card
        for entry in observation.remaining_deck
        for _ in range(entry.count)
    ]
    history_rows = tuple(
        (step.before.digest(), action_to_data(step.action), step.after.digest())
        for step in history[-64:]
    )
    history_digest = hashlib.sha256(
        json.dumps(history_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    tapes: list[tuple[VisiblePlayingCard, ...]] = []
    for particle in range(particles):
        payload = f"{nonce}\0{root_digest}\0{history_digest}\0{particle}"
        seed = int.from_bytes(hashlib.sha256(payload.encode("utf-8")).digest()[:16], "big")
        shuffled = list(deck)
        random.Random(seed).shuffle(shuffled)
        tapes.append(tuple(shuffled))
    return tuple(tapes)


def _action_tie_break(action: PublicAction) -> tuple[int, ...]:
    if isinstance(action, PlayCards):
        return (1, *(-slot.value for slot in action.cards))
    if isinstance(action, DiscardCards):
        return (0, *(-slot.value for slot in action.cards))
    return (-1,)
