from __future__ import annotations

from dataclasses import dataclass

from balatro_ai_v2.fast.blinds import IMPLEMENTED_BLINDS
from balatro_ai_v2.fast.boosters import IMPLEMENTED_BOOSTERS
from balatro_ai_v2.fast.consumables import DETERMINISTIC_CONSUMABLES
from balatro_ai_v2.fast.hand import HAND_RULE_JOKERS
from balatro_ai_v2.fast.joker_events import EVENT_JOKERS
from balatro_ai_v2.fast.jokers import IMPLEMENTED_JOKERS
from balatro_ai_v2.fast.joker_money import DOLLAR_BONUS_JOKERS, MONEY_EVENT_JOKERS
from balatro_ai_v2.fast.joker_repetitions import RETRIGGER_JOKERS
from balatro_ai_v2.fast.joker_run_rules import RUN_EFFECT_JOKERS
from balatro_ai_v2.fast.run_rules import EXACT_DECKS, EXACT_TAGS, EXACT_VOUCHERS
from balatro_ai_v2.fast.stakes import IMPLEMENTED_STAKES
from balatro_ai_v2.rules.catalog import RuleCatalog, RuleSource


IMPLEMENTED_ENHANCEMENTS = frozenset(
    {
        "m_bonus",
        "m_mult",
        "m_wild",
        "m_glass",
        "m_steel",
        "m_gold",
        "m_stone",
        "m_lucky",
    }
)

IMPLEMENTED_EDITIONS = frozenset(
    {
        "e_base",
        "e_foil",
        "e_holo",
        "e_polychrome",
        "e_negative",
    }
)

@dataclass(frozen=True, slots=True)
class CoverageRow:
    name: str
    implemented: int
    total: int
    missing: tuple[str, ...]
    missing_sources: tuple[RuleSource, ...]

    @property
    def complete(self) -> bool:
        return self.implemented == self.total

    @property
    def percent(self) -> float:
        return self.implemented / self.total * 100 if self.total else 100.0


@dataclass(frozen=True, slots=True)
class CoverageReport:
    rows: tuple[CoverageRow, ...]

    @property
    def implemented(self) -> int:
        return sum(row.implemented for row in self.rows)

    @property
    def total(self) -> int:
        return sum(row.total for row in self.rows)

    @property
    def complete(self) -> bool:
        return all(row.complete for row in self.rows)

    @property
    def percent(self) -> float:
        return self.implemented / self.total * 100 if self.total else 100.0


def build_coverage_report(catalog: RuleCatalog) -> CoverageReport:
    rows = (
        _row(
            catalog,
            "jokers",
            IMPLEMENTED_JOKERS
            | RUN_EFFECT_JOKERS
            | DOLLAR_BONUS_JOKERS
            | MONEY_EVENT_JOKERS
            | HAND_RULE_JOKERS
            | RETRIGGER_JOKERS
            | EVENT_JOKERS,
            catalog.jokers,
        ),
        _row(catalog, "consumables", DETERMINISTIC_CONSUMABLES, catalog.consumables),
        _row(catalog, "vouchers", EXACT_VOUCHERS, catalog.vouchers),
        _row(catalog, "enhancements", IMPLEMENTED_ENHANCEMENTS, catalog.enhancements),
        _row(catalog, "editions", IMPLEMENTED_EDITIONS, catalog.editions),
        _row(catalog, "boosters", IMPLEMENTED_BOOSTERS, catalog.boosters),
        _row(catalog, "decks", EXACT_DECKS, catalog.decks),
        _row(catalog, "blinds", IMPLEMENTED_BLINDS, catalog.blinds),
        _row(catalog, "tags", EXACT_TAGS, catalog.tags),
        _row(catalog, "stakes", IMPLEMENTED_STAKES, catalog.stakes),
    )
    return CoverageReport(rows=rows)


def _row(
    catalog: RuleCatalog, name: str, implemented: frozenset[str], total_keys: tuple[str, ...]
) -> CoverageRow:
    total = frozenset(total_keys)
    covered = implemented & total
    missing = tuple(sorted(total - implemented))
    return CoverageRow(
        name=name,
        implemented=len(covered),
        total=len(total),
        missing=missing,
        missing_sources=tuple(source for key in missing if (source := catalog.sources.get(key))),
    )
