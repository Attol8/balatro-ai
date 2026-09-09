"""Bounded joker ordering advice, including neutral adjacent bridge steps."""

from __future__ import annotations

from collections import deque
from dataclasses import replace
from fractions import Fraction

from balatro_ai.game.actions import JokerSlot, PlayCards, ReorderJokers, action_to_data, is_legal
from balatro_ai.game.scoring import _prepare_score_context, _score_play_prepared
from balatro_ai.game.state import PublicItem, PublicObservation


def joker_reorder_advice(
    observation: PublicObservation,
    plays: list[tuple[PlayCards, int | Fraction, str]],
    approximation: str,
) -> list[dict[str, object]]:
    """Return the first step of a shortest admissible path to a better score.

    Callers must include the current globally highest scoring legal play. Neutral
    steps strictly reduce the lexicographic public joker representation. Together
    with the nondecreasing best-play score this prevents cycles, even when callers
    reselect candidate plays after every observation. This deliberately misses
    paths requiring a score loss or a canonical-increasing neutral step.
    """
    items = observation.jokers
    if not plays or not 2 <= len(items) <= 6 or not all(
        isinstance(item, PublicItem) for item in items
    ):
        return []
    plays = plays[:3]
    baseline = max(row[1] for row in plays)
    start = tuple(range(len(items)))
    signatures = tuple(repr(item) for item in items)
    queue = deque([(start, (), 0)])
    seen = {start}
    scored: dict[tuple[int, ...], list[tuple[int | Fraction, str]]] = {}

    def scores(order: tuple[int, ...]) -> list[tuple[int | Fraction, str]]:
        if order not in scored:
            after = replace(observation, jokers=tuple(items[index] for index in order))
            context = _prepare_score_context(after)
            scored[order] = [
                _score_play_prepared(after, play.cards, None, context)
                for play, _, _ in plays
            ]
        return scored[order]

    while queue:
        order, first, depth = queue.popleft()
        for index in range(len(items) - 1):
            adjacent = list(order)
            adjacent[index], adjacent[index + 1] = adjacent[index + 1], adjacent[index]
            target = tuple(adjacent)
            if target in seen:
                continue
            first_step = first or target
            action = ReorderJokers(tuple(JokerSlot(value) for value in first_step))
            if not is_legal(observation, action):
                continue
            try:
                target_scores = scores(target)
            except ValueError:
                continue
            best_index = max(range(len(plays)), key=lambda value: target_scores[value][0])
            target_score, family = target_scores[best_index]
            if target_score > baseline:
                play, play_baseline, _ = plays[best_index]
                first_scores = scores(first_step)
                return [{
                    "action": action_to_data(action),
                    "then_play": action_to_data(play),
                    "family": family,
                    "baseline_score": _number(play_baseline),
                    "reordered_score": _number(first_scores[best_index][0]),
                    "target_score": _number(target_score),
                    "search_baseline_score": _number(baseline),
                    "first_step_best_score": _number(max(row[0] for row in first_scores)),
                    "target_joker_order": list(target),
                    "adjacent_steps_to_target": depth + 1,
                    "approximation": approximation,
                    "selected_before": [slot.value for slot in play.cards],
                    "selected_after": [slot.value for slot in play.cards],
                    "note": (
                        "Execute only this adjacent reorder, then observe and reassess. "
                        "then_play identifies the evaluated cards, not a queued action. "
                        "reordered_score is the first-step estimate; target_score requires "
                        "the remaining reorders. Bounded search over at most 720 joker "
                        "orders and three plays; neutral steps only in canonical-decreasing "
                        "order. No global optimality claim."
                    ),
                }]
            if target_score == baseline and tuple(signatures[i] for i in target) < tuple(
                signatures[i] for i in order
            ):
                seen.add(target)
                queue.append((target, first_step, depth + 1))
    return []


def _number(value: int | Fraction) -> int | float:
    return int(value) if value.denominator == 1 else float(value)
