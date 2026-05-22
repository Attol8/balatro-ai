from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.fast.consumables import DETERMINISTIC_CONSUMABLES
from balatro_ai_v2.fast.jokers import IMPLEMENTED_JOKERS
from balatro_ai_v2.fast.run_rules import EXACT_DECKS, EXACT_TAGS, EXACT_VOUCHERS
from balatro_ai_v2.rules import load_rule_catalog

IMPLEMENTED_ENHANCEMENTS = {
    "m_bonus",
    "m_mult",
    "m_wild",
    "m_glass",
    "m_steel",
    "m_gold",
    "m_stone",
}
IMPLEMENTED_EDITIONS = {
    "e_foil",
    "e_holo",
    "e_polychrome",
}


def main() -> None:
    catalog = load_rule_catalog()
    rows = [
        ("jokers", len(IMPLEMENTED_JOKERS), len(catalog.jokers)),
        ("consumables", len(DETERMINISTIC_CONSUMABLES), len(catalog.consumables)),
        ("vouchers", len(EXACT_VOUCHERS), len(catalog.vouchers)),
        ("enhancements", len(IMPLEMENTED_ENHANCEMENTS), len(catalog.enhancements)),
        ("editions", len(IMPLEMENTED_EDITIONS), len(catalog.editions)),
        ("boosters", 0, len(catalog.boosters)),
        ("decks", len(EXACT_DECKS), len(catalog.decks)),
        ("blinds", 2, len(catalog.blinds)),
        ("tags", len(EXACT_TAGS), len(catalog.tags)),
        ("stakes", 1, len(catalog.stakes)),
    ]
    implemented = sum(row[1] for row in rows)
    total = sum(row[2] for row in rows)
    for name, done, count in rows:
        pct = done / count * 100 if count else 100
        print(f"{name}: {done}/{count} ({pct:.1f}%)")
    print(f"total_rule_objects: {implemented}/{total} ({implemented / total * 100:.1f}%)")


if __name__ == "__main__":
    main()
