"""Strategic run-value evaluator for the planner.

Replaces static purchase-value tables: a state is worth what the simulator
says it can score against the requirement curve it is about to face.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import log2
from random import Random

from balatro_ai_v2.fast.blinds import BLIND_RULES
from balatro_ai_v2.fast.full_game import (
    UNMODELED_BOSS_EFFECTS,
    FastFullGameEnv,
    _build_balance_value,
    _joker_portfolio_value,
    _legal_masks,
)
from balatro_ai_v2.fast.run import BlindKind, RunPhase, _ante_base_chips


@dataclass(frozen=True, slots=True)
class RunValueWeights:
    progress: float = 10_000.0
    survival_margin: float = 5_000.0
    money: float = 18.0
    interest_band: float = 6.0
    scaling_rate: float = 900.0
    hand_levels: float = 40.0
    build_commitment: float = 1.0
    portfolio: float = 3.0
    blind_progress: float = 300.0
    churn_penalty: float = 5.0
    unmodeled_boss_penalty: float = 300.0
    win_bonus: float = 1_000_000.0
    loss_penalty: float = 25_000.0
    hand_budget_factor: float = 0.45
    margin_decay: float = 0.6
    margin_floor: float = -6.0
    margin_ceiling: float = 2.0
    consumable_value: float = 1.0


DEFAULT_WEIGHTS = RunValueWeights()

# Held-consumable values for effects the int-card sim cannot apply itself
# (enhancements, seals): the LIVE policy spends these in-blind, so holding
# them is real value the simulator would otherwise price at zero.
_CONSUMABLE_HOLD_VALUES: dict[str, float] = {
    "c_heirophant": 60.0,
    "c_empress": 60.0,
    "c_magician": 30.0,
    "c_justice": 45.0,
    "c_chariot": 50.0,
    "c_devil": 45.0,
    "c_lovers": 40.0,
    "c_tower": 25.0,
    "c_talisman": 30.0,
    "c_deja_vu": 35.0,
    "c_trance": 30.0,
    "c_medium": 25.0,
}


def _consumable_portfolio_value(env: FastFullGameEnv) -> float:
    return sum(_CONSUMABLE_HOLD_VALUES.get(key, 0.0) for key in env.consumables)

# Estimated per-round growth strength of self-scaling jokers, in abstract
# margin units. The rollout horizon realizes near-term growth; this term
# credits growth beyond the horizon.
_SCALING_RATES: dict[str, float] = {
    "j_constellation": 3.0,
    "j_hologram": 2.0,
    "j_campfire": 2.0,
    "j_madness": 2.5,
    "j_lucky_cat": 2.0,
    "j_canio": 2.0,
    "j_glass": 1.5,
    "j_vampire": 1.5,
    "j_obelisk": 1.5,
    "j_steel_joker": 1.0,
    "j_green_joker": 1.0,
    "j_ride_the_bus": 1.0,
    "j_square": 1.0,
    "j_runner": 1.0,
    "j_trousers": 1.0,
    "j_wee": 1.2,
    "j_castle": 1.0,
    "j_flash": 0.5,
    "j_red_card": 0.5,
    "j_ceremonial": 0.5,
    "j_supernova": 0.5,
    "j_rocket": 0.8,
    "j_spare_trousers": 1.0,
    # Decaying jokers: the hand-score projection sees their current value as
    # permanent, so the negative rate prices the decay (Seltzer dies in 10
    # hands, Ice Cream/Popcorn/Turtle Bean shrink every round).
    "j_selzer": -2.5,
    "j_ice_cream": -1.0,
    "j_popcorn": -0.8,
    "j_turtle_bean": -1.0,
    "j_ramen": -1.5,
}

_PROJECTION_SAMPLE_HANDS = 2
_PROJECTION_CACHE_MAX = 4096


def scaling_rate(env: FastFullGameEnv) -> float:
    return sum(_SCALING_RATES.get(joker.key, 0.0) for joker in env.jokers)


@lru_cache(maxsize=64)
def _worst_boss_mult(ante: int) -> float:
    if ante >= 8:
        pool = [rule for rule in BLIND_RULES.values() if rule.showdown]
    else:
        pool = [
            rule
            for rule in BLIND_RULES.values()
            if rule.boss and not rule.showdown and (rule.boss_min_ante or 1) <= ante
        ]
    return max(rule.score_mult for rule in pool)


def requirement_curve(env: FastFullGameEnv, horizon: int = 2) -> tuple[int, ...]:
    """Boss-blind requirements for the current and next `horizon` antes."""
    curve = []
    for offset in range(horizon + 1):
        ante = env.run.ante + offset
        if ante > 8:
            break
        if offset == 0 and env.boss_key is not None:
            mult = BLIND_RULES[env.boss_key].score_mult
        else:
            mult = _worst_boss_mult(ante)
        curve.append(int(_ante_base_chips(ante) * mult * env.run.blind_requirement_multiplier))
    return tuple(curve)


class _BoundedCache(dict):
    def trim(self) -> None:
        if len(self) > _PROJECTION_CACHE_MAX:
            self.clear()


_projection_cache: _BoundedCache = _BoundedCache()


def projected_best_hand_score(env: FastFullGameEnv) -> float:
    """Per-blind score capability estimated from the persistent deck.

    Draws deterministic sample hands from the deck composition, scores every
    legal mask with the current jokers and hand levels, and scales the best
    single-hand score by the per-blind hand budget.
    """
    key = (
        tuple(env.jokers),
        tuple(env.hand_levels),
        tuple(sorted(env.deck_cards)),
        env.run.hands,
        env.run.hand_size,
        env.run.money // 5,
        env.run.joker_slots,
    )
    cached = _projection_cache.get(key)
    if cached is not None:
        return cached

    # Probe on a boss-free clone so a just-cleared (or upcoming) boss's
    # debuffs don't distort the capability estimate; boss difficulty enters
    # through the requirement curve instead.
    probe = env.clone()
    probe.run.blind_kind = BlindKind.SMALL
    deck = sorted(env.deck_cards)
    hand_size = min(env.run.hand_size, 8)
    best_total = 0.0
    # Sample hands depend only on the deck composition so capability
    # comparisons across joker/level changes are noise-free.
    rng = Random(hash((tuple(deck), hand_size)) & 0x7FFFFFFF)
    for _ in range(_PROJECTION_SAMPLE_HANDS):
        if len(deck) >= hand_size:
            hand = tuple(sorted(rng.sample(deck, hand_size)))
        else:
            hand = tuple(deck)
        if not hand:
            break
        sample_best = max(
            (
                probe.score_hand_mask(
                    hand,
                    mask,
                    hands_left=max(env.run.hands - 1, 0),
                    discards_left=env.run.discards,
                ).total
                for mask in _legal_masks(len(hand))
            ),
            default=0,
        )
        best_total += sample_best
    best = best_total / max(_PROJECTION_SAMPLE_HANDS, 1)
    hands = max(env.run.hands, 1)
    projected = best * (1.0 + DEFAULT_WEIGHTS.hand_budget_factor * (hands - 1))
    _projection_cache[key] = projected
    _projection_cache.trim()
    return projected


def survival_margin(env: FastFullGameEnv, weights: RunValueWeights = DEFAULT_WEIGHTS) -> float:
    projected = projected_best_hand_score(env)
    margin = 0.0
    for offset, requirement in enumerate(requirement_curve(env)):
        ratio = projected / max(requirement, 1)
        raw = log2(ratio) if ratio > 0 else weights.margin_floor
        clamped = max(weights.margin_floor, min(weights.margin_ceiling, raw))
        margin += (weights.margin_decay**offset) * clamped
    return margin


def run_value(
    env: FastFullGameEnv,
    *,
    steps_taken: int = 0,
    weights: RunValueWeights = DEFAULT_WEIGHTS,
) -> float:
    value = env.rounds_cleared * weights.progress
    if env.won:
        return value + weights.win_bonus + env.run.money * weights.money
    if env.run.phase == RunPhase.GAME_OVER:
        return value - weights.loss_penalty - steps_taken * weights.churn_penalty

    value += weights.survival_margin * survival_margin(env, weights)

    money = env.run.money
    value += money * weights.money
    value += (min(max(money, 0), env.run.interest_cap) // 5) * 5 * weights.interest_band

    value += weights.scaling_rate * scaling_rate(env)
    value += weights.hand_levels * sum(max(level - 1, 0) for level in env.hand_levels)
    value += weights.build_commitment * _build_balance_value(env)
    value += weights.portfolio * _joker_portfolio_value(env)
    value += weights.consumable_value * _consumable_portfolio_value(env)

    score_progress = env.run.score / max(env.run.required_score, 1)
    value += min(score_progress, 1.5) * weights.blind_progress
    value += int(env.run.blind_kind) * 250.0

    if (
        env.boss_key in UNMODELED_BOSS_EFFECTS
        and env.run.blind_kind != BlindKind.BOSS
    ):
        value -= weights.unmodeled_boss_penalty
    value -= steps_taken * weights.churn_penalty
    return value
