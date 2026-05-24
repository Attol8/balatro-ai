from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BoosterKind(StrEnum):
    ARCANA = "Arcana"
    CELESTIAL = "Celestial"
    SPECTRAL = "Spectral"
    STANDARD = "Standard"
    BUFFOON = "Buffoon"


@dataclass(frozen=True, slots=True)
class BoosterSpec:
    key: str
    name: str
    order: int
    kind: BoosterKind
    cost: int
    size: int
    choices: int
    weight: float


def _booster_family(
    family: str,
    display_name: str,
    kind: BoosterKind,
    *,
    start_order: int,
    normal_count: int,
    normal_size: int,
    normal_weight: float,
    jumbo_count: int,
    jumbo_size: int,
    jumbo_weight: float,
    mega_count: int,
    mega_size: int,
    mega_weight: float,
) -> dict[str, BoosterSpec]:
    specs: dict[str, BoosterSpec] = {}
    order = start_order
    for index in range(1, normal_count + 1):
        specs[f"p_{family}_normal_{index}"] = BoosterSpec(
            f"p_{family}_normal_{index}", f"{display_name} Pack", order, kind, 4, normal_size, 1, normal_weight
        )
        order += 1
    for index in range(1, jumbo_count + 1):
        specs[f"p_{family}_jumbo_{index}"] = BoosterSpec(
            f"p_{family}_jumbo_{index}", f"Jumbo {display_name} Pack", order, kind, 6, jumbo_size, 1, jumbo_weight
        )
        order += 1
    for index in range(1, mega_count + 1):
        specs[f"p_{family}_mega_{index}"] = BoosterSpec(
            f"p_{family}_mega_{index}", f"Mega {display_name} Pack", order, kind, 8, mega_size, 2, mega_weight
        )
        order += 1
    return specs


BOOSTER_SPECS: dict[str, BoosterSpec] = {
    **_booster_family(
        "arcana",
        "Arcana",
        BoosterKind.ARCANA,
        start_order=1,
        normal_count=4,
        normal_size=3,
        normal_weight=1,
        jumbo_count=2,
        jumbo_size=5,
        jumbo_weight=1,
        mega_count=2,
        mega_size=5,
        mega_weight=0.25,
    ),
    **_booster_family(
        "celestial",
        "Celestial",
        BoosterKind.CELESTIAL,
        start_order=9,
        normal_count=4,
        normal_size=3,
        normal_weight=1,
        jumbo_count=2,
        jumbo_size=5,
        jumbo_weight=1,
        mega_count=2,
        mega_size=5,
        mega_weight=0.25,
    ),
    **_booster_family(
        "spectral",
        "Spectral",
        BoosterKind.SPECTRAL,
        start_order=29,
        normal_count=2,
        normal_size=2,
        normal_weight=0.3,
        jumbo_count=1,
        jumbo_size=4,
        jumbo_weight=0.3,
        mega_count=1,
        mega_size=4,
        mega_weight=0.07,
    ),
    **_booster_family(
        "standard",
        "Standard",
        BoosterKind.STANDARD,
        start_order=17,
        normal_count=4,
        normal_size=3,
        normal_weight=1,
        jumbo_count=2,
        jumbo_size=5,
        jumbo_weight=1,
        mega_count=2,
        mega_size=5,
        mega_weight=0.25,
    ),
    **_booster_family(
        "buffoon",
        "Buffoon",
        BoosterKind.BUFFOON,
        start_order=25,
        normal_count=2,
        normal_size=2,
        normal_weight=0.6,
        jumbo_count=1,
        jumbo_size=4,
        jumbo_weight=0.6,
        mega_count=1,
        mega_size=4,
        mega_weight=0.15,
    ),
}

IMPLEMENTED_BOOSTERS = frozenset(BOOSTER_SPECS)


def booster_spec(key: str) -> BoosterSpec:
    try:
        return BOOSTER_SPECS[key]
    except KeyError as exc:
        raise NotImplementedError(f"booster is not implemented: {key}") from exc
