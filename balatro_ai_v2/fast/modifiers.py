from __future__ import annotations

from enum import IntEnum


class Enhancement(IntEnum):
    BASE = 0
    BONUS = 1
    MULT = 2
    WILD = 3
    GLASS = 4
    STEEL = 5
    STONE = 6
    GOLD = 7
    LUCKY = 8


class Edition(IntEnum):
    BASE = 0
    FOIL = 1
    HOLOGRAPHIC = 2
    POLYCHROME = 3
    NEGATIVE = 4


class Seal(IntEnum):
    NONE = 0
    GOLD = 1
    RED = 2
    BLUE = 3
    PURPLE = 4


DETERMINISTIC_PLAYED_ENHANCEMENTS = {
    Enhancement.BASE,
    Enhancement.BONUS,
    Enhancement.MULT,
    Enhancement.WILD,
    Enhancement.GLASS,
    Enhancement.STONE,
    Enhancement.GOLD,
}


def enhancement_chip_bonus(enhancement: Enhancement) -> int:
    if enhancement == Enhancement.BONUS:
        return 30
    if enhancement == Enhancement.STONE:
        return 50
    return 0


def enhancement_mult_bonus(enhancement: Enhancement) -> int:
    if enhancement == Enhancement.MULT:
        return 4
    return 0


def enhancement_xmult(enhancement: Enhancement) -> float:
    if enhancement == Enhancement.GLASS:
        return 2.0
    return 1.0


def edition_chip_bonus(edition: Edition) -> int:
    if edition == Edition.FOIL:
        return 50
    return 0


def edition_mult_bonus(edition: Edition) -> int:
    if edition == Edition.HOLOGRAPHIC:
        return 10
    return 0


def edition_xmult(edition: Edition) -> float:
    if edition == Edition.POLYCHROME:
        return 1.5
    return 1.0

