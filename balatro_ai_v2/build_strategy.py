"""Deterministic build commitment from the public observation only."""

from __future__ import annotations

from dataclasses import dataclass

from balatro_ai_v2.joker_catalog import JOKER_CATALOG
from balatro_ai_v2.public_state import PublicObservation


_STANDARD_HAND_ORDER = (
    "High Card",
    "Pair",
    "Two Pair",
    "Three of a Kind",
    "Straight",
    "Flush",
    "Full House",
    "Four of a Kind",
    "Straight Flush",
    "Five of a Kind",
    "Flush House",
    "Flush Five",
)
_TIE_ORDER = (
    "Pair",
    "Two Pair",
    "Flush",
    "Straight",
    *(
        hand
        for hand in _STANDARD_HAND_ORDER
        if hand not in {"Pair", "Two Pair", "Flush", "Straight"}
    ),
)
_TIE_RANK = {hand: index for index, hand in enumerate(_TIE_ORDER)}

_HAND_TAGS = {
    "High Card": "high_card",
    "Pair": "pair",
    "Two Pair": "two_pair",
    "Three of a Kind": "three_of_a_kind",
    "Straight": "straight",
    "Flush": "flush",
    "Full House": "full_house",
    "Four of a Kind": "four_of_a_kind",
    "Straight Flush": "straight_flush",
}
_TAG_HANDS = {tag: hand for hand, tag in _HAND_TAGS.items()}

_PAIR_FAMILY = frozenset(
    {
        "Pair",
        "Two Pair",
        "Three of a Kind",
        "Full House",
        "Four of a Kind",
        "Five of a Kind",
    }
)
_FLUSH_FAMILY = frozenset({"Flush", "Straight Flush", "Flush House", "Flush Five"})
_STRAIGHT_FAMILY = frozenset({"Straight", "Straight Flush"})

_PLANET_HANDS = {
    "c_pluto": "High Card",
    "c_mercury": "Pair",
    "c_uranus": "Two Pair",
    "c_venus": "Three of a Kind",
    "c_saturn": "Straight",
    "c_jupiter": "Flush",
    "c_earth": "Full House",
    "c_mars": "Four of a Kind",
    "c_neptune": "Straight Flush",
    "c_planet_x": "Five of a Kind",
    "c_ceres": "Flush House",
    "c_eris": "Flush Five",
}


@dataclass(frozen=True, slots=True)
class BuildPlan:
    primary_hand: str
    secondary_hand: str | None
    confidence_numerator: int
    confidence_denominator: int
    favored_tags: frozenset[str]


def infer_build_plan(observation: PublicObservation) -> BuildPlan:
    """Infer a stable hand lane from public Jokers, deck, and hand statistics."""

    votes = {hand: 0 for hand in _STANDARD_HAND_ORDER}
    votes.update({"Pair": 2, "Two Pair": 2, "Flush": 2, "Straight": 1})

    for joker in observation.jokers:
        profile = JOKER_CATALOG.get(joker.key)
        if profile is None:
            continue
        for tag in profile.archetypes:
            hand = _TAG_HANDS.get(tag)
            if hand is not None:
                votes[hand] += 2

    deck = observation.deck.upper()
    if deck == "CHECKERED":
        votes["Flush"] += 3
    elif deck == "ABANDONED":
        votes["Flush"] += 2
        votes["Straight"] += 1

    known_stats = [stat for stat in observation.hand_stats if stat.name in votes]
    if known_stats:
        top_played = min(
            known_stats,
            key=lambda stat: (-stat.played, _TIE_RANK[stat.name]),
        )
        if top_played.played >= 3:
            votes[top_played.name] += 3
        for stat in known_stats:
            votes[stat.name] += min(3, max(0, stat.level - 1))

    ranked = sorted(votes, key=lambda hand: (-votes[hand], _TIE_RANK[hand]))
    primary = ranked[0]
    secondary = ranked[1] if len(ranked) > 1 else None
    denominator = sum(votes.values())
    return BuildPlan(
        primary_hand=primary,
        secondary_hand=secondary,
        confidence_numerator=votes[primary],
        confidence_denominator=denominator,
        favored_tags=_favored_tags(primary),
    )
def planet_hand(key: str) -> str | None:
    """Return the exact vanilla hand upgraded by a semantic Planet key."""

    return _PLANET_HANDS.get(key)


def planet_fit(key: str, plan: BuildPlan) -> int:
    """Return a closed ordinal fit score for a Planet and committed build."""

    hand = planet_hand(key)
    if hand is None:
        return 0
    if hand == plan.primary_hand:
        return 100
    if hand in _related_hands(plan.primary_hand):
        return 60
    return 10


def _related_hands(hand: str) -> frozenset[str]:
    related = {hand}
    if hand in _PAIR_FAMILY:
        related.update(_PAIR_FAMILY)
    if hand in _FLUSH_FAMILY:
        related.update(_FLUSH_FAMILY)
    if hand in _STRAIGHT_FAMILY:
        related.update(_STRAIGHT_FAMILY)
    return frozenset(related)


def _favored_tags(hand: str) -> frozenset[str]:
    related = _related_hands(hand)
    return frozenset(
        _HAND_TAGS[related_hand]
        for related_hand in related
        if related_hand in _HAND_TAGS
    )


__all__ = ["BuildPlan", "infer_build_plan", "planet_fit", "planet_hand"]
