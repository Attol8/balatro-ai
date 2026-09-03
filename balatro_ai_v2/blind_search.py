"""Exact, fail-closed public belief search within the current blind."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import combinations

from balatro_ai_v2.actions import (
    DiscardCards,
    HandSlot,
    PlayCards,
    PublicAction,
    is_legal,
    iter_legal_actions,
)
from balatro_ai_v2.baselines import PublicStrategicPolicy
from balatro_ai_v2.belief import (
    DrawOutcomeLimitExceeded,
    PublicDrawBelief,
    PublicDrawOutcome,
    canonical_remaining_deck,
    canonical_visible_card,
    visible_card_semantic_key,
)
from balatro_ai_v2.joker_rules import (
    TACTICAL_EXACT_JOKERS,
    exact_joker_multiplicity,
    faceless_discard_reward,
)
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.public_scoring import score_play
from balatro_ai_v2.public_state import (
    DeckCardCount,
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
class Outcome:
    clear_probability: Fraction
    expected_capped_chips: Fraction
    complete: bool = True


@dataclass(frozen=True, slots=True)
class ExactActionValue:
    action: PlayCards | DiscardCards
    outcome: Outcome


@dataclass(frozen=True, slots=True)
class BlindSearchDecision:
    root_digest: str
    baseline: PlayCards | DiscardCards
    selected: PlayCards | DiscardCards
    values: tuple[ExactActionValue, ...]
    proposal_complete: bool
    play_discard_action_complete: bool
    incomplete_reason: str | None
    states_evaluated: int
    chance_outcomes_evaluated: int
    transitions_evaluated: int
    score_evaluations: int
    cache_hits: int
    raw_actions: int
    semantic_actions: int
    max_discard_cards: int


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


@dataclass(frozen=True, slots=True)
class _ExactState:
    hand: tuple[VisiblePlayingCard, ...]
    remaining_deck: tuple[DeckCardCount, ...]
    chips: int
    money: int
    hands_left: int
    discards_left: int
    hands_played: int
    discards_used: int
    hand_stats: tuple[HandStat, ...]


@dataclass(frozen=True, slots=True)
class _WeightedExactState:
    probability: Fraction
    state: _ExactState


class _ExactIncomplete(RuntimeError):
    pass


@dataclass(slots=True)
class _ExactContext:
    root: PublicObservation
    target: int
    max_states: int
    max_transitions: int
    max_chance_outcomes: int
    max_chance_outcomes_per_transition: int
    max_score_evaluations: int
    max_actions_per_state: int
    max_discard_cards: int
    state_cache: dict[_ExactState, Outcome]
    score_cache: dict[tuple[_ExactState, tuple[object, ...]], tuple[int, str]]
    draw_cache: dict[
        tuple[tuple[DeckCardCount, ...], int],
        tuple[PublicDrawOutcome, ...],
    ]
    states_evaluated: int = 0
    chance_outcomes_evaluated: int = 0
    transitions_evaluated: int = 0
    score_evaluations: int = 0
    cache_hits: int = 0
    raw_actions: int = 0
    semantic_actions: int = 0


@dataclass(slots=True)
class PublicBlindBeliefSearch:
    """Compare a declared play/discard proposal exactly or preserve the baseline."""

    max_decisions: int = 2
    max_states: int = 10_000
    max_transitions: int = 100_000
    max_chance_outcomes: int = 50_000
    max_chance_outcomes_per_transition: int = 2_048
    max_score_evaluations: int = 100_000
    max_actions_per_state: int = 1_000
    max_discard_cards: int = 1
    last_decision: BlindSearchDecision | None = None

    def __post_init__(self) -> None:
        values = (
            self.max_decisions,
            self.max_states,
            self.max_transitions,
            self.max_chance_outcomes,
            self.max_chance_outcomes_per_transition,
            self.max_score_evaluations,
            self.max_actions_per_state,
            self.max_discard_cards,
        )
        if min(values) <= 0:
            raise ValueError("exact blind search bounds must be positive")
        if self.max_decisions > 2:
            raise ValueError("certified exact blind horizon cannot exceed two decisions")
        if self.max_discard_cards > 5:
            raise ValueError("max_discard_cards cannot exceed five")

    def choose_action(
        self,
        observation: PublicObservation,
        baseline: PublicAction,
        history: tuple[PublicHistoryStep, ...],
    ) -> PlayCards | DiscardCards:
        del history
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

        root_digest = observation.digest()
        initial = _initial_exact_state(observation)
        context = _new_exact_context(observation, current.score, self)
        try:
            if initial.hands_left + initial.discards_left > self.max_decisions:
                raise _ExactIncomplete("decision horizon exceeds exact bound")
            _enter_state(context)
            selected, values, _ = _evaluate_decision(context, initial, baseline)
        except (DrawOutcomeLimitExceeded, _ExactIncomplete, ValueError) as error:
            self.last_decision = _decision_record(
                root_digest,
                baseline,
                baseline,
                (),
                context,
                proposal_complete=False,
                incomplete_reason=str(error),
            )
            return baseline

        self.last_decision = _decision_record(
            root_digest,
            baseline,
            selected,
            values,
            context,
            proposal_complete=True,
            incomplete_reason=None,
        )
        return selected


def exact_blind_inference_budget() -> str:
    """Stable manifest label for the deployed default exact proposal."""

    search = PublicBlindBeliefSearch()
    return (
        "exact_blind_proposal=all_plays+one_card_discards+baseline;"
        f"exact_max_decisions={search.max_decisions};"
        f"exact_max_states={search.max_states};"
        f"exact_max_transitions={search.max_transitions};"
        f"exact_max_chance_outcomes={search.max_chance_outcomes};"
        "exact_max_chance_outcomes_per_transition="
        f"{search.max_chance_outcomes_per_transition};"
        f"exact_max_score_evaluations={search.max_score_evaluations};"
        f"exact_max_actions_per_state={search.max_actions_per_state}"
    )


def _initial_exact_state(observation: PublicObservation) -> _ExactState:
    return _ExactState(
        hand=tuple(
            canonical_visible_card(card)
            for card in observation.hand
            if isinstance(card, VisiblePlayingCard)
        ),
        remaining_deck=canonical_remaining_deck(observation.remaining_deck),
        chips=observation.round.chips,
        money=observation.money,
        hands_left=observation.round.hands_left,
        discards_left=observation.round.discards_left,
        hands_played=observation.round.hands_played,
        discards_used=observation.round.discards_used,
        hand_stats=observation.hand_stats,
    )


def _new_exact_context(
    observation: PublicObservation,
    target: int,
    search: PublicBlindBeliefSearch,
) -> _ExactContext:
    return _ExactContext(
        root=observation,
        target=target,
        max_states=search.max_states,
        max_transitions=search.max_transitions,
        max_chance_outcomes=search.max_chance_outcomes,
        max_chance_outcomes_per_transition=search.max_chance_outcomes_per_transition,
        max_score_evaluations=search.max_score_evaluations,
        max_actions_per_state=search.max_actions_per_state,
        max_discard_cards=search.max_discard_cards,
        state_cache={},
        score_cache={},
        draw_cache={},
    )


def _decision_record(
    root_digest: str,
    baseline: PlayCards | DiscardCards,
    selected: PlayCards | DiscardCards,
    values: tuple[ExactActionValue, ...],
    context: _ExactContext,
    *,
    proposal_complete: bool,
    incomplete_reason: str | None,
) -> BlindSearchDecision:
    return BlindSearchDecision(
        root_digest=root_digest,
        baseline=baseline,
        selected=selected,
        values=values,
        proposal_complete=proposal_complete,
        play_discard_action_complete=context.max_discard_cards == 5,
        incomplete_reason=incomplete_reason,
        states_evaluated=context.states_evaluated,
        chance_outcomes_evaluated=context.chance_outcomes_evaluated,
        transitions_evaluated=context.transitions_evaluated,
        score_evaluations=context.score_evaluations,
        cache_hits=context.cache_hits,
        raw_actions=context.raw_actions,
        semantic_actions=context.semantic_actions,
        max_discard_cards=context.max_discard_cards,
    )


def _enter_state(context: _ExactContext) -> None:
    if context.states_evaluated >= context.max_states:
        raise _ExactIncomplete("exact state budget exhausted")
    context.states_evaluated += 1


def _solve_state(context: _ExactContext, state: _ExactState) -> Outcome:
    terminal = _terminal_outcome(state, context.target)
    if terminal is not None:
        return terminal
    cached = context.state_cache.get(state)
    if cached is not None:
        context.cache_hits += 1
        return cached
    _enter_state(context)
    observation = _observation_for_exact_state(context.root, state)
    baseline = PublicStrategicPolicy().choose_action(
        observation,
        lambda: iter_legal_actions(observation),
        (),
    )
    if not isinstance(baseline, (PlayCards, DiscardCards)):
        raise _ExactIncomplete("future tactical baseline is outside exact action space")
    _, _, outcome = _evaluate_decision(context, state, baseline)
    context.state_cache[state] = outcome
    return outcome


def _evaluate_decision(
    context: _ExactContext,
    state: _ExactState,
    baseline: PlayCards | DiscardCards,
) -> tuple[PlayCards | DiscardCards, tuple[ExactActionValue, ...], Outcome]:
    observation = _observation_for_exact_state(context.root, state)
    if not is_legal(observation, baseline):
        raise _ExactIncomplete("baseline action is not legal in exact state")
    proposed_raw_actions = _proposal_raw_action_count(
        observation,
        baseline,
        max_discard_cards=context.max_discard_cards,
    )
    if proposed_raw_actions > context.max_actions_per_state:
        raise _ExactIncomplete("raw proposal action budget exhausted")
    actions, raw_count = _semantic_actions(
        observation,
        baseline,
        max_discard_cards=context.max_discard_cards,
    )
    if raw_count != proposed_raw_actions:
        raise _ExactIncomplete("proposal action preflight mismatch")
    context.raw_actions += raw_count
    context.semantic_actions += len(actions)
    if len(actions) > context.max_actions_per_state:
        raise _ExactIncomplete("semantic action budget exhausted")
    baseline_key = _semantic_action_key(state.hand, baseline)
    if baseline_key not in {_semantic_action_key(state.hand, action) for action in actions}:
        raise _ExactIncomplete("baseline semantic action is absent")

    values: list[ExactActionValue] = []
    baseline_outcome: Outcome | None = None
    for action in actions:
        outcome = _evaluate_action(context, state, action)
        reported = baseline if _semantic_action_key(state.hand, action) == baseline_key else action
        values.append(ExactActionValue(reported, outcome))
        if reported == baseline:
            baseline_outcome = outcome
    if baseline_outcome is None:
        raise _ExactIncomplete("exact evaluation omitted the baseline")

    better_probability = max(value.outcome.clear_probability for value in values)
    if better_probability <= baseline_outcome.clear_probability:
        selected = baseline
        selected_outcome = baseline_outcome
    else:
        best_expected = max(
            value.outcome.expected_capped_chips
            for value in values
            if value.outcome.clear_probability == better_probability
        )
        best = min(
            (
                value
                for value in values
                if value.outcome.clear_probability == better_probability
                and value.outcome.expected_capped_chips == best_expected
            ),
            key=lambda value: _action_sort_key(value.action),
        )
        selected = best.action
        selected_outcome = best.outcome
    return selected, tuple(values), selected_outcome


def _semantic_actions(
    observation: PublicObservation,
    baseline: PlayCards | DiscardCards,
    *,
    max_discard_cards: int,
) -> tuple[tuple[PlayCards | DiscardCards, ...], int]:
    hand = tuple(card for card in observation.hand if isinstance(card, VisiblePlayingCard))
    slots = tuple(HandSlot(index) for index in range(len(hand)))
    maximum = min(5, observation.selection_limit, len(slots))
    representatives: dict[tuple[object, ...], PlayCards | DiscardCards] = {}
    raw_count = 0
    for size in range(1, maximum + 1):
        for selected in combinations(slots, size):
            for action in (PlayCards(selected), DiscardCards(selected)):
                if not is_legal(observation, action):
                    continue
                if (
                    isinstance(action, DiscardCards)
                    and len(action.cards) > max_discard_cards
                    and action != baseline
                ):
                    continue
                raw_count += 1
                key = _semantic_action_key(hand, action)
                current = representatives.get(key)
                if current is None or _action_sort_key(action) < _action_sort_key(current):
                    representatives[key] = action
    return tuple(sorted(representatives.values(), key=_action_sort_key)), raw_count


def _proposal_raw_action_count(
    observation: PublicObservation,
    baseline: PlayCards | DiscardCards,
    *,
    max_discard_cards: int,
) -> int:
    maximum = min(5, observation.selection_limit, len(observation.hand))
    plays = sum(math.comb(len(observation.hand), size) for size in range(1, maximum + 1))
    if observation.round.discards_left <= 0:
        return plays
    discard_maximum = min(maximum, max_discard_cards)
    discards = sum(
        math.comb(len(observation.hand), size)
        for size in range(1, discard_maximum + 1)
    )
    if isinstance(baseline, DiscardCards) and len(baseline.cards) > max_discard_cards:
        discards += 1
    return plays + discards


def _semantic_action_key(
    hand: tuple[VisiblePlayingCard, ...],
    action: PlayCards | DiscardCards,
) -> tuple[object, ...]:
    selected_indexes = {slot.value for slot in action.cards}
    selected = tuple(
        sorted(
            (visible_card_semantic_key(hand[index]) for index in selected_indexes),
        )
    )
    retained = tuple(
        sorted(
            visible_card_semantic_key(card)
            for index, card in enumerate(hand)
            if index not in selected_indexes
        )
    )
    return ("play" if isinstance(action, PlayCards) else "discard", selected, retained)


def _evaluate_action(
    context: _ExactContext,
    state: _ExactState,
    action: PlayCards | DiscardCards,
) -> Outcome:
    successors = _exact_successors(context, state, action)
    clear_probability = Fraction(0)
    expected_capped_chips = Fraction(0)
    for successor in successors:
        terminal = _terminal_outcome(successor.state, context.target)
        child_outcome = terminal or _solve_state(context, successor.state)
        clear_probability += successor.probability * child_outcome.clear_probability
        expected_capped_chips += successor.probability * child_outcome.expected_capped_chips
    return Outcome(clear_probability, expected_capped_chips)


def _exact_successors(
    context: _ExactContext,
    state: _ExactState,
    action: PlayCards | DiscardCards,
) -> tuple[_WeightedExactState, ...]:
    if context.transitions_evaluated >= context.max_transitions:
        raise _ExactIncomplete("exact transition budget exhausted")
    context.transitions_evaluated += 1
    after = _apply_without_refill(context, state, action)
    terminal = _terminal_outcome(after, context.target)
    if terminal is not None:
        return (_WeightedExactState(Fraction(1), after),)

    draw_count = min(
        max(0, context.root.hand_limit - len(after.hand)),
        sum(entry.count for entry in after.remaining_deck),
    )
    if draw_count == 0:
        return (_WeightedExactState(Fraction(1), after),)
    remaining_budget = context.max_chance_outcomes - context.chance_outcomes_evaluated
    if remaining_budget <= 0:
        raise _ExactIncomplete("exact chance-outcome budget exhausted")
    draw_key = (after.remaining_deck, draw_count)
    cached_outcomes = context.draw_cache.get(draw_key)
    if cached_outcomes is None:
        belief = PublicDrawBelief(
            after.remaining_deck,
            sum(entry.count for entry in after.remaining_deck),
        )
        outcomes = belief.exact_outcomes(
            draw_count,
            max_outcomes=min(context.max_chance_outcomes_per_transition, remaining_budget),
        )
        context.draw_cache[draw_key] = outcomes
    else:
        outcomes = cached_outcomes
        context.cache_hits += 1
        if len(outcomes) > remaining_budget:
            raise _ExactIncomplete("exact chance-outcome budget exhausted")
    context.chance_outcomes_evaluated += len(outcomes)

    successors: list[_WeightedExactState] = []
    for draw in outcomes:
        child_hand = tuple(
            sorted((*after.hand, *draw.drawn_cards), key=_hand_sort_key, reverse=True)
        )
        child = replace(
            after,
            hand=child_hand,
            remaining_deck=draw.remaining_deck,
        )
        successors.append(_WeightedExactState(draw.probability, child))
    if sum((successor.probability for successor in successors), Fraction(0)) != 1:
        raise _ExactIncomplete("exact successor probabilities do not sum to one")
    return tuple(successors)


def _apply_without_refill(
    context: _ExactContext,
    state: _ExactState,
    action: PlayCards | DiscardCards,
) -> _ExactState:
    selected = tuple(slot.value for slot in action.cards)
    chips = state.chips
    money = state.money
    hands_left = state.hands_left
    discards_left = state.discards_left
    hands_played = state.hands_played
    discards_used = state.discards_used
    stats = state.hand_stats
    if isinstance(action, PlayCards):
        score_key = (state, _semantic_action_key(state.hand, action))
        scored = context.score_cache.get(score_key)
        if scored is None:
            if context.score_evaluations >= context.max_score_evaluations:
                raise _ExactIncomplete("exact score budget exhausted")
            observation = _observation_for_exact_state(context.root, state)
            score, hand_name = score_play(
                observation,
                action.cards,
                {stat.name: stat for stat in stats},
            )
            scored = (math.floor(score), hand_name)
            context.score_cache[score_key] = scored
            context.score_evaluations += 1
        else:
            context.cache_hits += 1
        score, hand_name = scored
        chips += score
        hands_left -= 1
        hands_played += 1
        stats = _increment_hand_stat(stats, hand_name)
    else:
        discarded = tuple(state.hand[index] for index in selected)
        money += faceless_discard_reward(context.root.jokers, discarded)
        discards_left -= 1
        discards_used += 1

    selected_set = set(selected)
    hand = tuple(
        sorted(
            (card for index, card in enumerate(state.hand) if index not in selected_set),
            key=_hand_sort_key,
            reverse=True,
        )
    )
    return _ExactState(
        hand=hand,
        remaining_deck=state.remaining_deck,
        chips=chips,
        money=money,
        hands_left=hands_left,
        discards_left=discards_left,
        hands_played=hands_played,
        discards_used=discards_used,
        hand_stats=stats,
    )


def _terminal_outcome(state: _ExactState, target: int) -> Outcome | None:
    if state.chips >= target:
        return Outcome(Fraction(1), Fraction(target))
    if state.hands_left <= 0 or (
        not state.hand and not any(entry.count for entry in state.remaining_deck)
    ):
        return Outcome(Fraction(0), Fraction(min(state.chips, target)))
    return None


def _observation_for_exact_state(
    root: PublicObservation,
    state: _ExactState,
) -> PublicObservation:
    return replace(
        root,
        hand=state.hand,
        money=state.money,
        required_hand_slots=(),
        remaining_deck=state.remaining_deck,
        draw_count=sum(entry.count for entry in state.remaining_deck),
        round=replace(
            root.round,
            chips=state.chips,
            hands_left=state.hands_left,
            discards_left=state.discards_left,
            hands_played=state.hands_played,
            discards_used=state.discards_used,
        ),
        hand_stats=state.hand_stats,
    )


def _action_sort_key(action: PlayCards | DiscardCards) -> tuple[int, tuple[int, ...]]:
    return (
        0 if isinstance(action, PlayCards) else 1,
        tuple(slot.value for slot in action.cards),
    )


def _supports_rollout(observation: PublicObservation) -> bool:
    cards = (
        *(card for card in observation.hand if isinstance(card, VisiblePlayingCard)),
        *(entry.card for entry in observation.remaining_deck),
    )
    try:
        PublicDrawBelief.from_observation(observation)
    except ValueError:
        return False
    return (
        all(joker.key in TACTICAL_EXACT_JOKERS for joker in observation.jokers)
        and exact_joker_multiplicity(observation.jokers)
        and all(joker.edition in {None, "FOIL"} and not joker.debuffed for joker in observation.jokers)
        and not any("observatory" in voucher.lower() for voucher in observation.used_vouchers)
        and all(card.rank in _RANK_SORT and card.suit in _SUIT_SORT for card in cards)
        and all(card.enhancement is None for card in cards)
        and all(card.edition is None for card in cards)
        and all(card.seal is None for card in cards)
        and all(not card.debuffed for card in cards)
        and all(card.permanent_bonus == 0 for card in cards)
    )


def _hand_sort_key(card: VisiblePlayingCard) -> tuple[int, int]:
    # The certified two-decision envelope enumerates every represented card
    # multiset at the final decision, so this is a canonical label rather than
    # an assumption about a player's UI sort preference.
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
        score, hand_name = score_play(
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
