"""Public, compositional strategy state for long-horizon Balatro decisions.

This module is intentionally a pure projection of :class:`PublicObservation`.
It names the relationships an expert reasons about without importing a game
engine, save payload, seed, or future random state.  Unknown Jokers and bosses
remain visible as unknowns; their mechanics are never inferred from tooltip
text.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction

from balatro_ai_v2.boss_rules import BossConstraint, boss_rule
from balatro_ai_v2.build_strategy import infer_build_plan
from balatro_ai_v2.consumable_rules import public_consumable_rule
from balatro_ai_v2.joker_catalog import JOKER_CATALOG, JokerRole
from balatro_ai_v2.public_state import PublicObservation


class RunGoal(str, Enum):
    """The objective changes only after authoritative public win state."""

    VICTORY = "victory"
    ENDLESS = "endless"


class CopyKind(str, Enum):
    BLUEPRINT_RIGHT = "blueprint_right"
    BRAINSTORM_LEFTMOST = "brainstorm_leftmost"


@dataclass(frozen=True, slots=True)
class CopyRelation:
    source_slot: int
    target_slot: int
    kind: CopyKind
    publicly_enabled: bool


@dataclass(frozen=True, slots=True)
class ScoringEngine:
    role_counts: tuple[tuple[JokerRole, int], ...]
    archetype_tags: frozenset[str]
    scoring_slots: tuple[int, ...]
    order_sensitive_slots: tuple[int, ...]
    copy_relations: tuple[CopyRelation, ...]
    unknown_joker_slots: tuple[int, ...]

    def count_role(self, role: JokerRole) -> int:
        return next((count for candidate, count in self.role_counts if candidate == role), 0)


@dataclass(frozen=True, slots=True)
class AvailableDeckProfile:
    """Composition of cards currently exposed as available to draw.

    During a blind this is not the whole deck: played, discarded, and held
    cards are represented elsewhere in the observation.  Keeping the name
    explicit prevents a policy from treating this as hidden snapshot fidelity.
    """

    card_count: int
    distinct_cards: int
    rank_counts: tuple[tuple[str, int], ...]
    suit_counts: tuple[tuple[str, int], ...]
    enhancement_counts: tuple[tuple[str, int], ...]
    seal_counts: tuple[tuple[str, int], ...]
    edition_counts: tuple[tuple[str, int], ...]
    rank_concentration: Fraction
    suit_concentration: Fraction
    duplicate_concentration: Fraction
    declared_deck_size: int


@dataclass(frozen=True, slots=True)
class EconomyProfile:
    cash: int
    interest_cap: int
    interest_units: int
    credit_floor: int
    rental_liability_per_round: int
    sell_value: int
    economy_jokers: int
    free_rerolls: int
    unknown_used_vouchers: tuple[str, ...]


KNOWN_VOUCHERS = frozenset(
    {
        "v_antimatter", "v_blank", "v_clearance_sale", "v_crystal_ball",
        "v_directors_cut", "v_glow_up", "v_grabber", "v_hieroglyph", "v_hone",
        "v_illusion", "v_liquidation", "v_magic_trick", "v_money_tree", "v_nacho_tong",
        "v_observatory", "v_omen_globe", "v_overstock_norm", "v_overstock_plus",
        "v_paint_brush", "v_palette", "v_petroglyph", "v_planet_merchant",
        "v_planet_tycoon", "v_recyclomancy", "v_reroll_glut", "v_reroll_surplus",
        "v_retcon", "v_seed_money", "v_tarot_merchant", "v_tarot_tycoon", "v_telescope",
        "v_wasteful",
    }
)


@dataclass(frozen=True, slots=True)
class ConsumableProfile:
    keys: tuple[str, ...]
    kinds: tuple[tuple[str, int], ...]
    free_slots: int
    has_planet: bool
    has_tarot: bool
    has_spectral: bool
    duplicators: tuple[str, ...]
    unknown_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HandDevelopment:
    primary_hand: str
    secondary_hand: str | None
    confidence: Fraction
    levels: tuple[tuple[str, int], ...]
    played: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class BossVulnerability:
    name: str | None
    known: bool
    constraints: frozenset[BossConstraint]
    conflicts: frozenset[str]
    score_multiplier: int | None


@dataclass(frozen=True, slots=True)
class PublicEngineState:
    goal: RunGoal
    ante: int
    antes_cleared: int
    won: bool
    scoring: ScoringEngine
    available_deck: AvailableDeckProfile
    economy: EconomyProfile
    consumables: ConsumableProfile
    hand_development: HandDevelopment
    boss: BossVulnerability


@dataclass(frozen=True, slots=True)
class GoalUtility:
    """A goal-conditioned value with lexicographic, rather than blended, order."""

    win_probability: float
    current_blind_clear_probability: float
    survival_progress: float
    endless_ante: float = 0.0
    log_score: float = 0.0
    economy_reserve: float = 0.0
    alive_probability: float = 1.0

    def __post_init__(self) -> None:
        probabilities = (
            self.win_probability,
            self.current_blind_clear_probability,
            self.alive_probability,
        )
        if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in probabilities):
            raise ValueError("probabilities must be finite values in [0, 1]")
        other = (self.survival_progress, self.endless_ante, self.log_score, self.economy_reserve)
        if any(not math.isfinite(value) for value in other):
            raise ValueError("utility components must be finite")

    def ordering_key(self, goal: RunGoal) -> tuple[float, ...]:
        """Return the exact objective order used for candidate comparison.

        Pre-win score is deliberately absent.  Consequently no amount of score
        can make a losing line outrank a line with a higher Ante-8 win chance.
        After the public ``won`` flag, Endless ante and log-score lead.
        """

        if goal == RunGoal.VICTORY:
            return (
                self.win_probability,
                self.alive_probability,
                self.current_blind_clear_probability,
                self.survival_progress,
                self.economy_reserve,
            )
        return (
            self.endless_ante,
            self.alive_probability,
            self.current_blind_clear_probability,
            self.survival_progress,
            self.log_score,
            self.economy_reserve,
        )


def derive_engine_state(observation: PublicObservation) -> PublicEngineState:
    """Derive the immutable long-horizon state from public fields only."""

    scoring = _scoring_engine(observation)
    hand_development = _hand_development(observation)
    return PublicEngineState(
        goal=RunGoal.ENDLESS if observation.won else RunGoal.VICTORY,
        ante=observation.ante,
        antes_cleared=observation.antes_cleared,
        won=observation.won,
        scoring=scoring,
        available_deck=_available_deck(observation),
        economy=_economy(observation),
        consumables=_consumables(observation),
        hand_development=hand_development,
        boss=_boss_vulnerability(observation, scoring, hand_development),
    )


def _scoring_engine(observation: PublicObservation) -> ScoringEngine:
    counts: dict[JokerRole, int] = {}
    tags: set[str] = set()
    scoring_slots: list[int] = []
    order_sensitive_slots: list[int] = []
    unknown_slots: list[int] = []
    for slot, joker in enumerate(observation.jokers):
        profile = JOKER_CATALOG.get(joker.key)
        if profile is None:
            unknown_slots.append(slot)
            continue
        counts[profile.role] = counts.get(profile.role, 0) + 1
        tags.update(profile.tags)
        if profile.score_effect:
            scoring_slots.append(slot)
        if profile.order_sensitive:
            order_sensitive_slots.append(slot)

    relations: list[CopyRelation] = []
    for source, joker in enumerate(observation.jokers):
        target: int | None = None
        kind: CopyKind | None = None
        if joker.key == "j_blueprint" and source + 1 < len(observation.jokers):
            target = source + 1
            kind = CopyKind.BLUEPRINT_RIGHT
        elif joker.key == "j_brainstorm" and observation.jokers:
            target = 0
            kind = CopyKind.BRAINSTORM_LEFTMOST
        if target is not None and kind is not None:
            relations.append(
                CopyRelation(
                    source_slot=source,
                    target_slot=target,
                    kind=kind,
                    # This is public topology, not a claim that the target is
                    # compatible in every trigger context. Compatibility is
                    # intentionally left to the authoritative simulator.
                    publicly_enabled=(
                        source != target
                        and not joker.debuffed
                        and not observation.jokers[target].debuffed
                    ),
                )
            )

    return ScoringEngine(
        role_counts=tuple(sorted(counts.items())),
        archetype_tags=frozenset(tags),
        scoring_slots=tuple(scoring_slots),
        order_sensitive_slots=tuple(order_sensitive_slots),
        copy_relations=tuple(relations),
        unknown_joker_slots=tuple(unknown_slots),
    )


def _available_deck(observation: PublicObservation) -> AvailableDeckProfile:
    rank_counts: dict[str, int] = {}
    suit_counts: dict[str, int] = {}
    enhancement_counts: dict[str, int] = {}
    seal_counts: dict[str, int] = {}
    edition_counts: dict[str, int] = {}
    total = 0
    maximum_duplicate = 0
    for entry in observation.remaining_deck:
        count = max(0, entry.count)
        total += count
        maximum_duplicate = max(maximum_duplicate, count)
        _increment(rank_counts, entry.card.rank, count)
        _increment(suit_counts, entry.card.suit, count)
        _increment(enhancement_counts, entry.card.enhancement, count)
        _increment(seal_counts, entry.card.seal, count)
        _increment(edition_counts, entry.card.edition, count)
    return AvailableDeckProfile(
        card_count=total,
        distinct_cards=sum(entry.count > 0 for entry in observation.remaining_deck),
        rank_counts=tuple(sorted(rank_counts.items())),
        suit_counts=tuple(sorted(suit_counts.items())),
        enhancement_counts=tuple(sorted(enhancement_counts.items())),
        seal_counts=tuple(sorted(seal_counts.items())),
        edition_counts=tuple(sorted(edition_counts.items())),
        rank_concentration=_maximum_share(rank_counts, total),
        suit_concentration=_maximum_share(suit_counts, total),
        duplicate_concentration=Fraction(maximum_duplicate, total) if total else Fraction(0),
        declared_deck_size=observation.deck_size,
    )


def _economy(observation: PublicObservation) -> EconomyProfile:
    if "v_money_tree" in observation.used_vouchers:
        interest_cap = 20
    elif "v_seed_money" in observation.used_vouchers:
        interest_cap = 10
    else:
        interest_cap = 5
    credit_cards = sum(
        joker.key == "j_credit_card" and not joker.debuffed for joker in observation.jokers
    )
    economy_jokers = sum(
        (profile := JOKER_CATALOG.get(joker.key)) is not None
        and profile.role == "economy"
        and not joker.debuffed
        for joker in observation.jokers
    )
    return EconomyProfile(
        cash=observation.money,
        interest_cap=interest_cap,
        interest_units=min(interest_cap, max(0, observation.money) // 5),
        credit_floor=-20 * credit_cards,
        rental_liability_per_round=3 * sum(joker.rental for joker in observation.jokers),
        sell_value=sum(joker.sell_cost or 0 for joker in observation.jokers)
        + sum(item.sell_cost or 0 for item in observation.consumables),
        economy_jokers=economy_jokers,
        free_rerolls=sum(joker.key == "j_chaos" and not joker.debuffed for joker in observation.jokers),
        unknown_used_vouchers=tuple(
            key for key in observation.used_vouchers if key not in KNOWN_VOUCHERS
        ),
    )


def _consumables(observation: PublicObservation) -> ConsumableProfile:
    kinds: dict[str, int] = {}
    for item in observation.consumables:
        kinds[item.kind.upper()] = kinds.get(item.kind.upper(), 0) + 1
    keys = tuple(item.key for item in observation.consumables)
    return ConsumableProfile(
        keys=keys,
        kinds=tuple(sorted(kinds.items())),
        free_slots=max(0, observation.consumable_limit - len(observation.consumables)),
        has_planet=any(item.kind.upper() == "PLANET" for item in observation.consumables),
        has_tarot=any(item.kind.upper() == "TAROT" for item in observation.consumables),
        has_spectral=any(item.kind.upper() == "SPECTRAL" for item in observation.consumables),
        duplicators=tuple(key for key in keys if key in {"c_fool", "c_cryptid"}),
        unknown_keys=tuple(
            item.key
            for item in observation.consumables
            if public_consumable_rule(item) is None
        ),
    )


def _hand_development(observation: PublicObservation) -> HandDevelopment:
    plan = infer_build_plan(observation)
    return HandDevelopment(
        primary_hand=plan.primary_hand,
        secondary_hand=plan.secondary_hand,
        confidence=Fraction(plan.confidence_numerator, plan.confidence_denominator),
        levels=tuple(sorted((stat.name, stat.level) for stat in observation.hand_stats)),
        played=tuple(sorted((stat.name, stat.played) for stat in observation.hand_stats)),
    )


def _boss_vulnerability(
    observation: PublicObservation,
    scoring: ScoringEngine,
    hand_development: HandDevelopment,
) -> BossVulnerability:
    visible = next(
        (
            blind
            for blind in observation.blinds
            if blind.kind == "BOSS" and blind.status in {"CURRENT", "SELECT", "UPCOMING"}
        ),
        None,
    )
    if visible is None:
        return BossVulnerability(None, False, frozenset(), frozenset(), None)
    rule = boss_rule(visible.name)
    if rule is None:
        return BossVulnerability(visible.name, False, frozenset(), frozenset(), None)

    tags = scoring.archetype_tags
    conflicts: set[str] = set()
    suit_tag = {"S": "spades", "H": "hearts", "D": "diamonds", "C": "clubs"}
    for suit in rule.suit_debuff:
        if suit_tag.get(suit) in tags:
            conflicts.add(f"debuffs_{suit_tag.get(suit, suit)}")
        elif hand_development.primary_hand in {
            "Flush",
            "Straight Flush",
            "Flush House",
            "Flush Five",
        }:
            conflicts.add(f"potentially_debuffs_flush_{suit_tag.get(suit, suit)}")
    if rule.face_debuff and tags.intersection({"face_cards", "jacks", "queens", "kings"}):
        conflicts.add("face_engine_debuffed")
    if rule.repeat_hand_restriction and (
        "repeat_hand" in tags or max((stat.played for stat in observation.hand_stats), default=0) > 1
    ):
        conflicts.add("repeat_hand_blocked")
    public_plays = [stat.played for stat in observation.hand_stats if stat.played > 0]
    if rule.single_hand_family and public_plays and max(public_plays) == sum(public_plays):
        conflicts.add("single_hand_dependency")
    if rule.joker_order and (
        scoring.copy_relations or scoring.order_sensitive_slots
    ):
        conflicts.add("joker_order_disrupted")
    if rule.joker_debuff and observation.jokers:
        conflicts.add("joker_engine_disrupted")
    if rule.high_target:
        conflicts.add("high_score_target")
    if rule.hands_forced == 1:
        conflicts.add("one_hand_only")
    if rule.discards_forced == 0:
        conflicts.add("no_discards")
    if rule.face_down_cards:
        conflicts.add("face_down_cards")
    return BossVulnerability(
        name=visible.name,
        known=True,
        constraints=rule.constraints,
        conflicts=frozenset(conflicts),
        score_multiplier=rule.score_multiplier,
    )


def _increment(counts: dict[str, int], key: str | None, count: int) -> None:
    if key is not None and count:
        counts[key] = counts.get(key, 0) + count


def _maximum_share(counts: dict[str, int], total: int) -> Fraction:
    return Fraction(max(counts.values(), default=0), total) if total else Fraction(0)


__all__ = [
    "AvailableDeckProfile",
    "BossVulnerability",
    "ConsumableProfile",
    "CopyKind",
    "CopyRelation",
    "EconomyProfile",
    "GoalUtility",
    "HandDevelopment",
    "KNOWN_VOUCHERS",
    "PublicEngineState",
    "RunGoal",
    "ScoringEngine",
    "derive_engine_state",
]
