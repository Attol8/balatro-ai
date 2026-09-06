"""Small, revisable strategic intent and conservative acquisition values."""

from __future__ import annotations

from dataclasses import dataclass

from balatro_ai_v2.solver.build_strategy import infer_build_plan, planet_hand
from balatro_ai_v2.solver.joker_catalog import JOKER_CATALOG
from balatro_ai_v2.solver.public_state import PublicItem, PublicObservation
from balatro_ai_v2.solver.strategy_engine import RouteStage, RunRoute, derive_engine_state


@dataclass(frozen=True, slots=True)
class BuildIntent:
    primary_hand: str
    family: str
    growth_keys: tuple[str, ...]
    economy_slots: int
    scoring_slots: int


def _active(observation: PublicObservation) -> tuple[PublicItem, ...]:
    return tuple(
        joker for joker in observation.jokers
        if isinstance(joker, PublicItem) and joker.kind == "JOKER" and not joker.debuffed
    )


def derive_intent(observation: PublicObservation) -> BuildIntent:
    """Derive a deterministic intent from fields visible to the policy."""
    plan = infer_build_plan(observation)
    jokers = _active(observation)
    profiles = tuple(JOKER_CATALOG[j.key] for j in jokers if j.key in JOKER_CATALOG)
    engine = derive_engine_state(observation)

    # Advanced routes are commitments only when the public route has a real
    # anchor/enabler; an offer alone must not make us force a rare combination.
    route_family = {
        RunRoute.HELD_RETRIGGER: "held_card",
        RunRoute.PLAYED_RETRIGGER: "played_card",
        RunRoute.CONSUMABLE_DUPLICATION: "consumable",
    }
    family = "hand"
    for route in (RunRoute.HELD_RETRIGGER, RunRoute.PLAYED_RETRIGGER,
                  RunRoute.CONSUMABLE_DUPLICATION):
        state = engine.route(route)
        if state.stage in {RouteStage.ASSEMBLING, RouteStage.ONLINE} and state.payload_count > 0:
            family = route_family[route]
            break
    if family == "hand" and any(
        key in {"j_green_joker", "j_supernova", "j_ride_the_bus", "j_square", "j_trousers"}
        for key in (p.key for p in profiles)
    ):
        family = "small_hand" if plan.primary_hand in {"High Card", "Pair", "Two Pair"} else "hand"
    if family == "hand" and any(h.name == plan.primary_hand and h.level >= 3
                                for h in observation.hand_stats):
        family = "planet"

    growth = tuple(sorted(
        p.key for p in profiles if p.primary_role == "scaling"
    ))
    economy = sum(p.primary_role == "economy" for p in profiles)
    scoring = sum(p.score_effect for p in profiles)
    return BuildIntent(plan.primary_hand, family, growth, economy, scoring)


_ROLE_BASE = {
    "x_mult": 72.0, "retrigger": 62.0, "scaling": 60.0,
    "flat_mult": 48.0, "chips": 46.0, "economy": 34.0, "utility": 18.0,
}


def joker_value(item: PublicItem, observation: PublicObservation, intent: BuildIntent) -> float:
    """Return an ordinal (not probabilistic) value for a visible Joker offer."""
    if not isinstance(item, PublicItem) or item.kind != "JOKER" or item.debuffed:
        return 0.0
    profile = JOKER_CATALOG.get(item.key)
    if profile is None:
        return 0.0
    active = _active(observation)
    existing = [JOKER_CATALOG[j.key] for j in active if j.key in JOKER_CATALOG]
    if "copy" in profile.route_tags and not any(
        p.score_effect or p.primary_role == "retrigger" for p in existing
    ):
        return 0.0
    value = _ROLE_BASE[profile.primary_role]
    tags = profile.archetypes
    hand_tag = {
        "High Card": "high_card", "Pair": "pair", "Two Pair": "two_pair",
        "Three of a Kind": "three_of_a_kind", "Straight": "straight",
        "Flush": "flush", "Full House": "full_house", "Four of a Kind": "four_of_a_kind",
        "Straight Flush": "straight_flush",
    }.get(intent.primary_hand)
    if hand_tag in tags:
        value += 28
    if intent.family == "small_hand" and "small_hand" in tags:
        value += 22
    if intent.family == "held_card" and tags.intersection({"held_cards", "kings"}):
        value += 24
    if intent.family == "played_card" and profile.route_tags.intersection({"played_anchor", "played_enabler"}):
        value += 24
    if intent.family == "consumable" and tags.intersection({"consumables", "planets", "tarot"}):
        value += 20
    role_count = sum(p.primary_role == profile.primary_role for p in existing)
    value -= min(24.0, role_count * 10.0)
    # Growth and runway matter most before the engine is online; economy has
    # sharply less marginal value once there is a late, healthy scoring core.
    weak = intent.scoring_slots < 2
    if profile.primary_role == "scaling":
        value += 18 if observation.ante <= 3 and weak else 4
    if profile.primary_role == "economy":
        value += 18 if observation.ante <= 3 and weak else (-12 if observation.ante >= 6 and not weak else 3)
    if profile.route_tags.intersection({"copy"}):
        value += 28
    if profile.primary_role == "retrigger":
        value += 18 if any(p.route_tags.intersection({"played_anchor", "held_anchor"}) for p in existing) else -8
    return max(0.0, round(value, 3))


def planet_value(key: str, intent: BuildIntent) -> float:
    """Ordinal priority for a Planet, based on exact or related hand fit."""
    hand = planet_hand(key)
    if hand is None:
        return 0.0
    if hand == intent.primary_hand:
        return 100.0
    related = {
        "Pair": {"Two Pair", "Three of a Kind", "Full House", "Four of a Kind", "Five of a Kind"},
        "Two Pair": {"Pair", "Three of a Kind", "Full House", "Four of a Kind", "Five of a Kind"},
        "Flush": {"Straight Flush", "Flush House", "Flush Five"},
        "Straight": {"Straight Flush"},
    }
    return 60.0 if hand in related.get(intent.primary_hand, set()) else 10.0


__all__ = ["BuildIntent", "derive_intent", "joker_value", "planet_value"]
