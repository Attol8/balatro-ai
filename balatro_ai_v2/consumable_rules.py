"""Source-audited public legality for vanilla consumables.

The policy must not inspect Jackdaw cards or Balatro ability tables.  These
rules are the small, versioned public projection of Balatro 1.0.1o's visible
consumable contract.  Unknown keys fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from itertools import combinations
from typing import Iterator

from balatro_ai_v2.public_state import (
    HiddenHandCard,
    PublicItem,
    PublicObservation,
    VisiblePlayingCard,
)


class ConsumableRequirement(str, Enum):
    ALWAYS = "always"
    CONSUMABLE_SLOT = "consumable_slot"
    JOKER_SLOT = "joker_slot"
    ELIGIBLE_JOKER = "eligible_joker"
    HAND_CARDS = "hand_cards"
    ANKH = "ankh"
    FOOL = "fool"


class TargetFilter(str, Enum):
    ANY = "any"
    NO_EDITION = "no_edition"


@dataclass(frozen=True, slots=True)
class PublicConsumableRule:
    minimum_targets: int = 0
    maximum_targets: int = 0
    target_filter: TargetFilter = TargetFilter.ANY
    requirement: ConsumableRequirement = ConsumableRequirement.ALWAYS

    def __post_init__(self) -> None:
        if not 0 <= self.minimum_targets <= self.maximum_targets <= 5:
            raise ValueError("consumable target bounds are invalid")


_TARGET_RULES: dict[str, PublicConsumableRule] = {
    "c_magician": PublicConsumableRule(1, 2),
    "c_empress": PublicConsumableRule(1, 2),
    "c_heirophant": PublicConsumableRule(1, 2),
    "c_lovers": PublicConsumableRule(1, 1),
    "c_chariot": PublicConsumableRule(1, 1),
    "c_justice": PublicConsumableRule(1, 1),
    "c_strength": PublicConsumableRule(1, 2),
    "c_hanged_man": PublicConsumableRule(1, 2),
    "c_death": PublicConsumableRule(2, 2),
    "c_devil": PublicConsumableRule(1, 1),
    "c_tower": PublicConsumableRule(1, 1),
    "c_star": PublicConsumableRule(1, 3),
    "c_moon": PublicConsumableRule(1, 3),
    "c_sun": PublicConsumableRule(1, 3),
    "c_world": PublicConsumableRule(1, 3),
    "c_talisman": PublicConsumableRule(1, 1),
    "c_aura": PublicConsumableRule(1, 1, TargetFilter.NO_EDITION),
    "c_deja_vu": PublicConsumableRule(1, 1),
    "c_trance": PublicConsumableRule(1, 1),
    "c_medium": PublicConsumableRule(1, 1),
    "c_cryptid": PublicConsumableRule(1, 1),
}

_PLANETS = frozenset(
    {
        "c_mercury",
        "c_venus",
        "c_earth",
        "c_mars",
        "c_jupiter",
        "c_saturn",
        "c_uranus",
        "c_neptune",
        "c_pluto",
        "c_planet_x",
        "c_ceres",
        "c_eris",
    }
)

_NO_TARGET_RULES: dict[str, ConsumableRequirement] = {
    "c_hermit": ConsumableRequirement.ALWAYS,
    "c_temperance": ConsumableRequirement.ALWAYS,
    "c_black_hole": ConsumableRequirement.ALWAYS,
    "c_high_priestess": ConsumableRequirement.CONSUMABLE_SLOT,
    "c_emperor": ConsumableRequirement.CONSUMABLE_SLOT,
    "c_fool": ConsumableRequirement.FOOL,
    "c_judgement": ConsumableRequirement.JOKER_SLOT,
    "c_soul": ConsumableRequirement.JOKER_SLOT,
    "c_wraith": ConsumableRequirement.JOKER_SLOT,
    "c_wheel_of_fortune": ConsumableRequirement.ELIGIBLE_JOKER,
    "c_ectoplasm": ConsumableRequirement.ELIGIBLE_JOKER,
    "c_hex": ConsumableRequirement.ELIGIBLE_JOKER,
    "c_familiar": ConsumableRequirement.HAND_CARDS,
    "c_grim": ConsumableRequirement.HAND_CARDS,
    "c_incantation": ConsumableRequirement.HAND_CARDS,
    "c_immolate": ConsumableRequirement.HAND_CARDS,
    "c_sigil": ConsumableRequirement.HAND_CARDS,
    "c_ouija": ConsumableRequirement.HAND_CARDS,
    "c_ankh": ConsumableRequirement.ANKH,
}


def public_consumable_rule(item: PublicItem) -> PublicConsumableRule | None:
    """Return the audited vanilla rule for ``item``, else fail closed."""

    if item.key in _PLANETS:
        return PublicConsumableRule()
    targeted = _TARGET_RULES.get(item.key)
    if targeted is not None:
        return targeted
    requirement = _NO_TARGET_RULES.get(item.key)
    if requirement is None:
        return None
    return PublicConsumableRule(requirement=requirement)


def iter_public_targets(
    observation: PublicObservation,
    item: PublicItem,
    *,
    from_pack: bool,
) -> Iterator[tuple[int, ...]]:
    """Yield every public target selection legal for this consumable."""

    rule = public_consumable_rule(item)
    if rule is None:
        return
    if rule.maximum_targets == 0:
        if public_consumable_is_usable(observation, item, (), from_pack=from_pack):
            yield ()
        return
    valid = tuple(
        index
        for index, card in enumerate(observation.hand)
        if _target_matches(card, rule.target_filter)
    )
    for size in range(rule.maximum_targets, rule.minimum_targets - 1, -1):
        for targets in combinations(valid, size):
            if public_consumable_is_usable(
                observation,
                item,
                targets,
                from_pack=from_pack,
            ):
                yield targets


def public_consumable_is_usable(
    observation: PublicObservation,
    item: PublicItem,
    targets: tuple[int, ...],
    *,
    from_pack: bool,
) -> bool:
    """Mirror vanilla's public ``can_use_consumeable`` gates.

    This function deliberately handles only the pinned vanilla card set.  A
    modded or newly introduced key returns ``False`` until its rule is audited.
    """

    rule = public_consumable_rule(item)
    if rule is None or len(targets) != len(set(targets)):
        return False
    if not rule.minimum_targets <= len(targets) <= rule.maximum_targets:
        return False
    if any(target < 0 or target >= len(observation.hand) for target in targets):
        return False
    if any(
        not _target_matches(observation.hand[target], rule.target_filter)
        for target in targets
    ):
        return False

    requirement = rule.requirement
    if requirement == ConsumableRequirement.ALWAYS:
        return True
    if requirement in {ConsumableRequirement.CONSUMABLE_SLOT, ConsumableRequirement.FOOL}:
        occupied = len(observation.consumables) - (0 if from_pack else 1)
        if occupied >= observation.consumable_limit:
            return False
        if requirement == ConsumableRequirement.FOOL:
            return observation.last_tarot_planet not in {None, "c_fool"}
        return True
    if requirement == ConsumableRequirement.JOKER_SLOT:
        return len(observation.jokers) < observation.joker_limit
    if requirement == ConsumableRequirement.ELIGIBLE_JOKER:
        return any(joker.edition is None for joker in observation.jokers)
    if requirement == ConsumableRequirement.HAND_CARDS:
        return len(observation.hand) > 1
    if requirement == ConsumableRequirement.ANKH:
        return (
            bool(observation.jokers)
            and observation.joker_limit > 1
            and len(observation.jokers) < observation.joker_limit
        )
    return False


def _target_matches(
    card: VisiblePlayingCard | HiddenHandCard,
    target_filter: TargetFilter,
) -> bool:
    if target_filter == TargetFilter.ANY:
        return True
    if target_filter == TargetFilter.NO_EDITION:
        if isinstance(card, HiddenHandCard):
            return False
        return card.edition is None
    return False
