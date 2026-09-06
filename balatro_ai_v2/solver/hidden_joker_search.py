"""A narrow public-history permutation belief for Amber Acorn.

Remembered Joker identities are never assigned to an actual hidden position.
Each candidate hand is evaluated against the same complete permutation set.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from itertools import combinations, permutations

from balatro_ai_v2.solver.actions import (
    DiscardCards, HandSlot, PlayCards, PublicAction, ReorderHand, SelectBlind, is_legal,
)
from balatro_ai_v2.solver.policy import PublicHistoryStep
from balatro_ai_v2.solver.public_scoring import _prepare_score_context, _score_play_prepared
from balatro_ai_v2.solver.public_state import HiddenJokerSlot, Phase, PublicItem, PublicObservation, VisiblePlayingCard

_AUDITED = frozenset({'j_green_joker', 'j_card_sharp', 'j_blackboard', 'j_duo', 'j_throwback'})


@dataclass(frozen=True, slots=True)
class HiddenPlayChoice:
    action: PlayCards
    reason: str
    diagnostics: dict[str, float | int | str]


def _amber(observation: PublicObservation) -> bool:
    return (observation.phase == Phase.SELECTING_HAND
            and any(b.status == 'CURRENT' and b.kind == 'BOSS' and b.name == 'Amber Acorn' and not b.disabled for b in observation.blinds)
            and 1 <= len(observation.jokers) <= 5
            and all(isinstance(j, HiddenJokerSlot) for j in observation.jokers))


def _remembered_inventory(observation: PublicObservation, history: tuple[PublicHistoryStep, ...]) -> tuple[PublicItem, ...] | None:
    if not history or history[-1].after != observation:
        return None
    anchor = None
    for index in range(len(history) - 1, -1, -1):
        step = history[index]
        if isinstance(step.action, SelectBlind) and step.before.phase == Phase.BLIND_SELECT and _amber(step.after):
            anchor = index
            break
    if anchor is None:
        return None
    first = history[anchor]
    if not is_legal(first.before, first.action):
        return None
    if len(first.before.jokers) != len(observation.jokers):
        return None
    inventory = first.before.jokers
    for joker in inventory:
        if not isinstance(joker, PublicItem) or joker.key not in _AUDITED or joker.debuffed or joker.perishable_rounds is not None:
            return None
        allowed = {'current_mult'} if joker.key == 'j_green_joker' else {'current_x_mult'} if joker.key == 'j_throwback' else set()
        if joker.runtime is not None and any(value is not None for key, value in asdict(joker.runtime).items() if key not in allowed):
            return None
        if joker.key == 'j_green_joker' and (joker.runtime is None or joker.runtime.current_mult is None):
            return None
        if joker.key == 'j_throwback' and (joker.runtime is None or joker.runtime.current_x_mult is None):
            return None
    previous = first.after
    for step in history[anchor + 1:]:
        if step.before != previous or not _amber(step.before) or not _amber(step.after):
            return None
        if len(step.after.jokers) != len(inventory) or step.before.round_no != step.after.round_no:
            return None
        if not isinstance(step.action, (PlayCards, DiscardCards, ReorderHand)) or not is_legal(step.before, step.action):
            return None
        # Unsupported generated consumables or inventory effects are not
        # silently treated as identity-preserving hidden transitions.
        if step.before.consumables != step.after.consumables:
            return None
        change = 1 if isinstance(step.action, PlayCards) else -1 if isinstance(step.action, DiscardCards) else 0
        inventory = tuple(replace(j, runtime=replace(j.runtime, current_mult=max(0, j.runtime.current_mult + change)))
                          if j.key == 'j_green_joker' else j for j in inventory)
        previous = step.after
    return inventory


def choose_hidden_play(observation: PublicObservation, baseline: PublicAction,
                       history: tuple[PublicHistoryStep, ...]) -> HiddenPlayChoice | None:
    if not _amber(observation) or not isinstance(baseline, (PlayCards, DiscardCards)) or not is_legal(observation, baseline):
        return None
    if len(observation.hand) > 10:
        return None
    if any(not isinstance(card, VisiblePlayingCard) or card.enhancement == 'LUCKY' for card in observation.hand):
        return None
    inventory = _remembered_inventory(observation, history)
    if inventory is None:
        return None
    ordered = sorted(inventory, key=lambda j: json.dumps(asdict(j), sort_keys=True))
    hypotheses = tuple(dict.fromkeys(permutations(ordered)))
    worlds = tuple(replace(observation, jokers=permutation) for permutation in hypotheses)
    contexts = tuple(_prepare_score_context(world) for world in worlds)
    stats = {stat.name: stat for stat in observation.hand_stats}
    target = max(0, next(b.score for b in observation.blinds if b.status == 'CURRENT') - observation.round.chips)
    best = None
    for count in range(1, min(5, observation.selection_limit, len(observation.hand)) + 1):
        for indices in combinations(range(len(observation.hand)), count):
            action = PlayCards(tuple(HandSlot(i) for i in indices))
            if not is_legal(observation, action):
                continue
            try:
                scores = tuple(float(_score_play_prepared(world, action.cards, stats, context)[0])
                               for world, context in zip(worlds, contexts))
            except (ValueError, KeyError, NotImplementedError):
                return None
            minimum = min(scores)
            if isinstance(baseline, DiscardCards) and minimum < target:
                continue
            mean = sum(scores) / len(scores)
            capped = sum(min(target, score) for score in scores) / len(scores)
            clear_fraction = sum(score >= target for score in scores) / len(scores)
            rank = (clear_fraction if observation.round.hands_left == 1 else 0.0,
                    capped, mean, action == baseline, -count, tuple(-i for i in indices))
            if best is None or rank > best[0]:
                best = (rank, action, minimum, mean, clear_fraction)
    if best is None:
        return None
    rank, action, minimum, mean, clear_fraction = best
    return HiddenPlayChoice(action, 'Choose a hand across every remembered-inventory permutation; no hidden positions assumed.',
                            {'permutations': len(hypotheses), 'minimum_score': minimum,
                             'mean_score': mean, 'capped_mean_score': rank[1], 'target': target,
                             'modeled_clear_fraction': clear_fraction,
                             'inventory_model': 'audited static jokers plus public Green Joker play/discard counter'})
