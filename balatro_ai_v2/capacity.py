"""Fail-closed engine-capacity estimates from typed public information."""

from __future__ import annotations

import hashlib
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from fractions import Fraction

from balatro_ai_v2.actions import PlayCards, iter_legal_actions
from balatro_ai_v2.belief import PublicDrawBelief, canonical_remaining_deck
from balatro_ai_v2.joker_catalog import get_joker_profile
from balatro_ai_v2.boss_rules import BossConstraint, BossRule, boss_rule
from balatro_ai_v2.joker_rules import (
    ONE_PLAY_CAPACITY_EXACT_JOKERS,
    ONE_PLAY_CAPACITY_RUNTIME_FIELD,
    exact_joker_multiplicity,
)
from balatro_ai_v2.public_scoring import score_play
from balatro_ai_v2.public_state import (
    DeckCardCount,
    HiddenHandCard,
    HiddenJokerSlot,
    Phase,
    PublicObservation,
    VisiblePlayingCard,
)


CAPACITY_MODEL_VERSION = 5
CAPACITY_SAMPLE_METHOD = "public-digest-monte-carlo-without-replacement-v1"
_SAMPLED_PHASES = frozenset({Phase.BLIND_SELECT, Phase.ROUND_EVAL, Phase.SHOP, Phase.PACK})
_UNSUPPORTED_CAPACITY_BOSS_CONSTRAINTS = frozenset(
    {
        BossConstraint.FORCED_SLOT,
        BossConstraint.JOKER_DEBUFF,
        BossConstraint.JOKER_ORDER,
        BossConstraint.SELL_TO_DISABLE,
        BossConstraint.FACE_DOWN,
        BossConstraint.PLAYED_CARD_DEBUFF,
    }
)
_SCORING_NEUTRAL_VOUCHERS = frozenset(
    {
        "v_antimatter",
        "v_blank",
        "v_clearance_sale",
        "v_crystal_ball",
        "v_directors_cut",
        "v_glow_up",
        "v_grabber",
        "v_hieroglyph",
        "v_hone",
        "v_illusion",
        "v_liquidation",
        "v_magic_trick",
        "v_money_tree",
        "v_nacho_tong",
        "v_omen_globe",
        "v_overstock_norm",
        "v_overstock_plus",
        "v_paint_brush",
        "v_palette",
        "v_petroglyph",
        "v_planet_merchant",
        "v_planet_tycoon",
        "v_recyclomancy",
        "v_reroll_glut",
        "v_reroll_surplus",
        "v_retcon",
        "v_seed_money",
        "v_tarot_merchant",
        "v_tarot_tycoon",
        "v_telescope",
        "v_wasteful",
    }
)


@dataclass(frozen=True, slots=True)
class CapacityHand:
    cards: tuple[VisiblePlayingCard, ...]
    probability: Fraction
    best_play: tuple[int, ...]
    hand_name: str
    score: Fraction


@dataclass(frozen=True, slots=True)
class CapacityHandBreakdown:
    hand_name: str
    samples: int
    probability: Fraction
    mean_best_score: Fraction
    maximum_best_score: Fraction


@dataclass(frozen=True, slots=True)
class CapacityEstimate:
    available: bool
    unavailable_reason: str | None
    mean_best_score: Fraction | None
    best_hand: CapacityHand | None
    breakdown: tuple[CapacityHandBreakdown, ...]
    samples: int
    sample_method: str
    public_root_digest: str
    model_version: int = CAPACITY_MODEL_VERSION


@dataclass(frozen=True, slots=True)
class CapacityProjection:
    available: bool
    unavailable_reason: str | None
    current: CapacityEstimate
    rounds: int
    projected_mean_best_score: Fraction | None
    growth_rate: float | None


@dataclass(frozen=True, slots=True)
class CapacityMargin:
    available: bool
    unavailable_reason: str | None
    capacity: CapacityEstimate
    boss_requirement: int | None
    log_margin: float | None


def estimate_capacity(
    observation: PublicObservation,
    belief: PublicDrawBelief,
    samples: int,
) -> CapacityEstimate:
    """Estimate expected best one-play score without privileged draw order.

    At a visible hand, the one public hand is scored directly. At strategic
    phases, future hands are sampled without replacement from the exchangeable
    public deck multiset. The player chooses a legal play after that future
    hand becomes visible, so each sample is maximized independently.
    """

    root_digest = _capacity_root_digest(observation)
    reason = _unsupported_reason(observation, belief, samples)
    if reason is not None:
        return _unavailable(root_digest, reason)

    if observation.phase == Phase.SELECTING_HAND:
        weighted_hands = ((tuple(observation.hand), Fraction(1)),)
        sample_method = "visible-hand-v1"
    else:
        weighted_hands, sample_method = _sample_hands(observation, belief, samples)

    scored: list[CapacityHand] = []
    for hand, probability in weighted_hands:
        synthetic = _with_hand(observation, belief, hand)
        plays = tuple(
            action
            for action in iter_legal_actions(synthetic)
            if isinstance(action, PlayCards) and _play_meets_boss(synthetic, action)
        )
        if not plays:
            return _unavailable(root_digest, "no legal public play")
        candidates = []
        stats = {stat.name: stat for stat in synthetic.hand_stats}
        for action in plays:
            score, hand_name = score_play(synthetic, action.cards, stats)
            candidates.append(
                (
                    Fraction(score),
                    tuple(-slot.value for slot in action.cards),
                    tuple(slot.value for slot in action.cards),
                    hand_name,
                )
            )
        score, _, slots, hand_name = max(candidates, key=lambda row: row[:2])
        scored.append(CapacityHand(hand, probability, slots, hand_name, score))

    count = len(scored)
    mean = sum((entry.probability * entry.score for entry in scored), Fraction(0))
    best = max(
        scored,
        key=lambda entry: (
            entry.score,
            entry.hand_name,
            tuple((card.rank, card.suit) for card in entry.cards),
            tuple(-slot for slot in entry.best_play),
        ),
    )
    grouped: dict[str, list[tuple[Fraction, Fraction]]] = defaultdict(list)
    for entry in scored:
        grouped[entry.hand_name].append((entry.probability, entry.score))
    breakdown = tuple(
        CapacityHandBreakdown(
            hand_name=name,
            samples=len(scores),
            probability=sum((weight for weight, _ in scores), Fraction(0)),
            mean_best_score=(
                sum((weight * score for weight, score in scores), Fraction(0))
                / sum((weight for weight, _ in scores), Fraction(0))
            ),
            maximum_best_score=max(score for _, score in scores),
        )
        for name, scores in sorted(grouped.items())
    )
    return CapacityEstimate(
        available=True,
        unavailable_reason=None,
        mean_best_score=mean,
        best_hand=best,
        breakdown=breakdown,
        samples=count,
        sample_method=sample_method,
        public_root_digest=root_digest,
    )


def project_capacity(
    observation: PublicObservation,
    belief: PublicDrawBelief,
    samples: int,
    rounds: int,
    *,
    current: CapacityEstimate | None = None,
) -> CapacityProjection:
    """Project only builds whose relevant scoring state is known to stay flat."""

    current = current or estimate_capacity(observation, belief, samples)
    if isinstance(rounds, bool) or not isinstance(rounds, int) or rounds < 0:
        return CapacityProjection(False, "rounds must be a non-negative integer", current, 0, None, None)
    if not current.available:
        return CapacityProjection(False, current.unavailable_reason, current, rounds, None, None)
    for joker in observation.jokers:
        if isinstance(joker, HiddenJokerSlot):
            return CapacityProjection(
                False,
                "face-down Jokers are unsupported",
                current,
                rounds,
                None,
                None,
            )
        try:
            scaling = get_joker_profile(joker.key).primary_role == "scaling"
        except KeyError:
            scaling = True
        if scaling:
            return CapacityProjection(
                False,
                f"uncatalogued capacity projection for {joker.key}",
                current,
                rounds,
                None,
                None,
            )
    return CapacityProjection(True, None, current, rounds, current.mean_best_score, 0.0)


def log_margin(
    observation: PublicObservation,
    estimate: CapacityEstimate,
) -> CapacityMargin:
    """Compare one-play capacity with the visible upcoming boss requirement."""

    bosses = tuple(
        blind
        for blind in observation.blinds
        if blind.kind == "BOSS" and blind.status in {"SELECT", "UPCOMING", "CURRENT"}
    )
    if not estimate.available:
        return CapacityMargin(False, estimate.unavailable_reason, estimate, None, None)
    if len(bosses) != 1 or bosses[0].score <= 0:
        return CapacityMargin(False, "one positive visible boss requirement is required", estimate, None, None)
    score = estimate.mean_best_score
    if score is None or score <= 0:
        return CapacityMargin(True, None, estimate, bosses[0].score, -math.inf)
    return CapacityMargin(
        True,
        None,
        estimate,
        bosses[0].score,
        math.log(float(score)) - math.log(bosses[0].score),
    )


def _unsupported_reason(
    observation: PublicObservation,
    belief: PublicDrawBelief,
    samples: int,
) -> str | None:
    if isinstance(samples, bool) or not isinstance(samples, int) or samples <= 0:
        return "samples must be a positive integer"
    if observation.phase not in _SAMPLED_PHASES | {Phase.SELECTING_HAND}:
        return f"unsupported capacity phase {observation.phase.value}"
    if observation.phase == Phase.SELECTING_HAND and any(
        isinstance(card, HiddenHandCard) for card in observation.hand
    ):
        return "hidden hand cards are unsupported"
    if any(isinstance(joker, HiddenJokerSlot) for joker in observation.jokers):
        return "face-down Jokers are unsupported"
    if observation.phase == Phase.SELECTING_HAND:
        current = next(
            (blind for blind in observation.blinds if blind.status == "CURRENT"),
            None,
        )
        if (
            current is not None
            and current.kind == "BOSS"
            and not current.disabled
            and boss_rule(current.name) is None
        ):
            return f"unknown current boss blind {current.name!r}"
    if canonical_remaining_deck(belief.remaining_deck) != canonical_remaining_deck(
        observation.remaining_deck
    ) or belief.draw_count != observation.draw_count:
        return "belief does not match the public observation"
    if observation.phase in _SAMPLED_PHASES and (
        _future_hand_size(observation) <= 0
        or _future_hand_size(observation) > belief.draw_count
    ):
        return "future public hand size is unavailable"
    if not exact_joker_multiplicity(observation.jokers):
        return "unsupported duplicate Joker mechanics"
    for joker in observation.jokers:
        if joker.key not in ONE_PLAY_CAPACITY_EXACT_JOKERS:
            return f"unsupported Joker {joker.key}"
        if (
            joker.edition
            not in {None, "FOIL", "HOLO", "HOLOGRAPHIC", "POLYCHROME", "NEGATIVE"}
            or joker.eternal
            or joker.perishable_rounds is not None
            or joker.rental
            or joker.debuffed
            or not _supported_runtime(joker)
        ):
            return f"unsupported Joker state for {joker.key}"
    cards = tuple(
        card
        for card in observation.hand
        if isinstance(card, VisiblePlayingCard)
    ) + tuple(entry.card for entry in belief.remaining_deck)
    for card in cards:
        if (
            card.enhancement is not None
            or card.edition is not None
            or card.seal is not None
            or card.debuffed
            or card.permanent_bonus != 0
        ):
            return "unsupported playing-card mechanic"
    for voucher in observation.used_vouchers:
        if voucher == "v_observatory":
            return "unsupported Observatory scoring"
        if voucher not in _SCORING_NEUTRAL_VOUCHERS:
            return f"unsupported voucher {voucher}"
    if observation.phase in _SAMPLED_PHASES:
        boss, boss_reason = _future_boss_rule(observation)
        if boss_reason is not None:
            return boss_reason
        assert boss is not None
        unsupported = boss.constraints & _UNSUPPORTED_CAPACITY_BOSS_CONSTRAINTS
        if unsupported:
            names = ", ".join(sorted(constraint.value for constraint in unsupported))
            return f"unsupported next-boss mechanics for {boss.name}: {names}"
    return None


def _supported_runtime(joker: object) -> bool:
    runtime = getattr(joker, "runtime", None)
    expected = ONE_PLAY_CAPACITY_RUNTIME_FIELD.get(getattr(joker, "key", ""))
    if runtime is None:
        return expected is None
    if expected is None or getattr(runtime, expected) is None:
        return False
    fields = (
        "current_mult",
        "current_chips",
        "current_x_mult",
        "current_dollars",
        "remaining_hands",
        "loyalty_remaining",
        "driver_tally",
        "target_hand",
        "target_rank",
        "target_suit",
        "castle_suit",
        "invisible_rounds",
        "mail_rank",
        "current_hand_size_bonus",
        "remaining_discards",
    )
    return all(field == expected or getattr(runtime, field) is None for field in fields)


def _sample_hands(
    observation: PublicObservation,
    belief: PublicDrawBelief,
    samples: int,
) -> tuple[
    tuple[tuple[tuple[VisiblePlayingCard, ...], Fraction], ...],
    str,
]:
    draws = _future_hand_size(observation)
    if math.comb(belief.draw_count, draws) <= samples:
        outcomes = belief.exact_outcomes(draws, max_outcomes=samples)
        return (
            tuple((outcome.drawn_cards, outcome.probability) for outcome in outcomes),
            "exact-public-hypergeometric-v1",
        )
    population = tuple(
        entry.card for entry in canonical_remaining_deck(belief.remaining_deck) for _ in range(entry.count)
    )
    seed_material = f"capacity-v{CAPACITY_MODEL_VERSION}\0{_capacity_root_digest(observation)}\0{samples}"
    seed = int.from_bytes(hashlib.sha256(seed_material.encode("utf-8")).digest()[:16], "big")
    rng = random.Random(seed)
    return (
        tuple(
            (tuple(rng.sample(population, draws)), Fraction(1, samples))
            for _ in range(samples)
        ),
        CAPACITY_SAMPLE_METHOD,
    )


def _with_hand(
    observation: PublicObservation,
    belief: PublicDrawBelief,
    hand: tuple[VisiblePlayingCard, ...],
) -> PublicObservation:
    if observation.phase == Phase.SELECTING_HAND:
        return observation
    remaining = Counter(entry.card for entry in canonical_remaining_deck(belief.remaining_deck) for _ in range(entry.count))
    remaining.subtract(hand)
    deck = tuple(
        DeckCardCount(card, count)
        for card, count in sorted(
            ((card, count) for card, count in remaining.items() if count > 0),
            key=lambda pair: (pair[0].rank, pair[0].suit),
        )
    )
    boss, boss_reason = _future_boss_rule(observation)
    if boss_reason is not None or boss is None:
        raise AssertionError("capacity capability gate admitted an unsupported boss")
    hand = tuple(_apply_boss_debuff(card, boss) for card in hand)
    blinds = tuple(
        replace(blind, status="CURRENT" if blind.kind == "BOSS" else "DEFEATED")
        for blind in observation.blinds
    )
    return replace(
        observation,
        phase=Phase.SELECTING_HAND,
        hand=hand,
        selection_limit=min(5, len(hand)),
        required_hand_slots=(),
        remaining_deck=deck,
        draw_count=sum(entry.count for entry in deck),
        shop=(),
        vouchers=(),
        packs=(),
        opened_pack=(),
        pack_kind=None,
        pack_choices_remaining=0,
        blinds=blinds,
        hand_stats=tuple(replace(stat, played_this_round=0) for stat in observation.hand_stats),
        round=replace(
            observation.round,
            chips=0,
            hands_left=_future_hands(observation, boss),
            discards_left=_future_discards(observation, boss),
            hands_played=0,
            discards_used=0,
        ),
    )


def _future_boss_rule(
    observation: PublicObservation,
) -> tuple[BossRule | None, str | None]:
    bosses = tuple(
        blind
        for blind in observation.blinds
        if blind.kind == "BOSS" and blind.status in {"SELECT", "UPCOMING", "CURRENT"}
    )
    if len(bosses) != 1:
        return None, "one visible next boss is required"
    rule = boss_rule(bosses[0].name)
    if rule is None:
        return None, f"unknown next boss blind {bosses[0].name!r}"
    return rule, None


def _future_hand_size(observation: PublicObservation) -> int:
    rule, _ = _future_boss_rule(observation)
    delta = rule.hand_size_delta if rule is not None else 0
    return observation.hand_limit + delta


def _future_hands(observation: PublicObservation, rule: BossRule) -> int:
    if rule.hands_forced is not None:
        return rule.hands_forced
    return max(
        1,
        4
        + sum(
            voucher in {"v_grabber", "v_nacho_tong"}
            for voucher in observation.used_vouchers
        )
        - sum(voucher == "v_hieroglyph" for voucher in observation.used_vouchers),
    )


def _future_discards(observation: PublicObservation, rule: BossRule) -> int:
    if rule.discards_forced is not None:
        return rule.discards_forced
    return max(
        0,
        3
        + int(observation.deck == "RED")
        + sum(
            voucher in {"v_wasteful", "v_recyclomancy"}
            for voucher in observation.used_vouchers
        )
        - sum(voucher == "v_petroglyph" for voucher in observation.used_vouchers)
        + sum(
            joker.key == "j_drunkard"
            for joker in observation.jokers
            if not isinstance(joker, HiddenJokerSlot)
        ),
    )


def _apply_boss_debuff(card: VisiblePlayingCard, rule: BossRule) -> VisiblePlayingCard:
    face = card.rank in {"J", "Q", "K"}
    debuffed = (
        card.debuffed
        or card.rank in rule.rank_debuff
        or card.suit in rule.suit_debuff
        or (rule.face_debuff and face)
    )
    return replace(card, debuffed=debuffed)


def _play_meets_boss(observation: PublicObservation, action: PlayCards) -> bool:
    current = next(
        (blind for blind in observation.blinds if blind.status == "CURRENT"),
        None,
    )
    if current is None or current.kind != "BOSS" or current.disabled:
        return True
    rule = boss_rule(current.name)
    return rule is not None and (
        rule.min_selected_cards is None or len(action.cards) >= rule.min_selected_cards
    )


def _unavailable(root_digest: str, reason: str) -> CapacityEstimate:
    return CapacityEstimate(
        available=False,
        unavailable_reason=reason,
        mean_best_score=None,
        best_hand=None,
        breakdown=(),
        samples=0,
        sample_method=CAPACITY_SAMPLE_METHOD,
        public_root_digest=root_digest,
    )


def _capacity_root_digest(observation: PublicObservation) -> str:
    normalized = replace(
        observation,
        remaining_deck=canonical_remaining_deck(observation.remaining_deck),
    )
    return hashlib.sha256(normalized.canonical_json().encode("utf-8")).hexdigest()
