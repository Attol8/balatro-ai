"""In-blind play/discard beam search shared by fast eval and live play.

Port of the SearchRunAgent tactical branch with boss-aware in-beam state:
The Mouth's first-hand lock and The Eye's no-repeat rule are tracked along
each beam path instead of only against the env's current round state.
"""

from __future__ import annotations

from balatro_ai_v2.fast.blinds import BlindHandPolicy, BlindRule
from balatro_ai_v2.fast.env import DISCARD_ACTION_OFFSET
from balatro_ai_v2.fast.full_game import (
    FastFullGameEnv,
    _jokers_after_discard,
    _jokers_after_play,
    _legal_masks,
    _ranked_discard_masks,
    _replace_selected_from_front,
    _score_mask_with_jokers,
    _selected_cards,
)
from balatro_ai_v2.fast.hand import FastScore
from balatro_ai_v2.fast.jokers import Joker


def plan_blind_tactics(
    env: FastFullGameEnv,
    *,
    beam_width: int = 4,
    action_beam: int = 3,
    wide_retry: bool = True,
) -> int:
    action = _beam_search(env, beam_width=beam_width, action_beam=action_beam)
    if (
        wide_retry
        and action is not None
        and not _clears_blind(env, action)
        and env.hands_remaining >= 2
        and env.discards_remaining > 0
    ):
        wide = _beam_search(env, beam_width=max(beam_width, 8), action_beam=max(action_beam, 6))
        if wide is not None and _clears_blind(env, wide):
            return wide
    if action is None:
        return env.greedy_play_action()
    return action


def _clears_blind(env: FastFullGameEnv, action: int) -> bool:
    if action >= DISCARD_ACTION_OFFSET:
        return False
    score = env.score_hand_mask(tuple(env.run.hand), action)
    return env.run.score + score.total >= env.run.required_score


def _beam_search(env: FastFullGameEnv, *, beam_width: int, action_beam: int) -> int | None:
    rule = env._boss_rule()
    states: list[
        tuple[
            int | None,
            tuple[int, ...],
            tuple[int, ...],
            int,
            int,
            int,
            tuple[Joker, ...],
            int | None,
            frozenset[int],
        ]
    ] = [
        (
            None,
            tuple(env.run.hand),
            tuple(env.run.deck[env.run.deck_pos :]),
            env.run.score,
            env.hands_remaining,
            env.discards_remaining,
            tuple(env.jokers),
            env.first_hand_kind_this_round,
            frozenset(env.played_hand_kinds_this_round),
        )
    ]
    best_action: int | None = None
    best_score = env.run.score
    max_depth = max(env.hands_remaining + env.discards_remaining, 1)

    for _ in range(max_depth):
        next_states: list[
            tuple[int, tuple[int, ...], tuple[int, ...], int, int, int, tuple[Joker, ...], int | None, frozenset[int]]
        ] = []
        for first_action, hand, deck, score, hands, discards, jokers, first_kind, prev_kinds in states:
            if score >= env.run.required_score:
                if first_action is not None:
                    return first_action
                continue
            if hands <= 0 or not hand:
                continue

            for mask, scored in _ranked_beam_plays(
                env, rule, hand, jokers, hands, discards, len(deck), action_beam, first_kind, prev_kinds
            ):
                selected = _selected_cards(hand, mask)
                next_hand, next_deck = _replace_selected_from_front(hand, deck, mask)
                next_score = score + scored.total
                next_jokers = _jokers_after_play(jokers, scored, selected)
                next_first = first_kind if first_kind is not None else (scored.kind if scored.total > 0 else None)
                next_prev = prev_kinds | {scored.kind} if scored.total > 0 else prev_kinds
                candidate_first = first_action if first_action is not None else mask
                if next_score > best_score:
                    best_score = next_score
                    best_action = candidate_first
                if next_score >= env.run.required_score:
                    return candidate_first
                next_states.append(
                    (candidate_first, next_hand, next_deck, next_score, hands - 1, discards, next_jokers, next_first, next_prev)
                )

            if discards > 0:
                for mask in _ranked_discard_masks(env, hand, deck, jokers, hands, discards, action_beam):
                    action = DISCARD_ACTION_OFFSET + mask
                    next_hand, next_deck = _replace_selected_from_front(hand, deck, mask)
                    next_jokers = _jokers_after_discard(jokers, mask.bit_count())
                    candidate_first = first_action if first_action is not None else action
                    next_states.append(
                        (candidate_first, next_hand, next_deck, score, hands, discards - 1, next_jokers, first_kind, prev_kinds)
                    )

        if not next_states:
            break
        next_states.sort(
            key=lambda item: (item[3] >= env.run.required_score, item[3], item[4], item[5]),
            reverse=True,
        )
        states = next_states[:beam_width]

    return best_action


def _ranked_beam_plays(
    env: FastFullGameEnv,
    rule: BlindRule | None,
    hand: tuple[int, ...],
    jokers: tuple[Joker, ...],
    hands_left: int,
    discards_left: int,
    deck_count: int,
    action_beam: int,
    first_kind: int | None,
    prev_kinds: frozenset[int],
) -> tuple[tuple[int, FastScore], ...]:
    scored: list[tuple[int, FastScore]] = []
    for mask in _legal_masks(len(hand)):
        result = _score_mask_with_jokers(
            env,
            hand,
            mask,
            jokers=jokers,
            hands_left=max(hands_left - 1, 0),
            discards_left=discards_left,
            deck_count=deck_count,
        )
        if rule is not None and _beam_blocked(rule, result.kind, mask.bit_count(), first_kind, prev_kinds):
            result = FastScore(kind=result.kind, chips=0, mult=0.0, total=0, scoring_mask=result.scoring_mask)
        scored.append((mask, result))
    scored.sort(key=lambda item: item[1].total, reverse=True)
    return tuple(scored[:action_beam])


def _beam_blocked(
    rule: BlindRule,
    kind: int,
    selected_count: int,
    first_kind: int | None,
    prev_kinds: frozenset[int],
) -> bool:
    policy = rule.hand_policy
    if policy == BlindHandPolicy.MIN_FIVE_CARDS:
        return selected_count < 5
    if policy == BlindHandPolicy.REPEAT_HAND_FORBIDDEN:
        return kind in prev_kinds
    if policy == BlindHandPolicy.ONLY_FIRST_HAND_TYPE:
        return first_kind is not None and kind != first_kind
    return False
