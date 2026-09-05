"""Stable public diagnostics for strategy decisions and benchmark reports."""

from __future__ import annotations

from collections import Counter
from fractions import Fraction
from typing import Mapping, Sequence

from balatro_ai_v2.public_state import PublicObservation
from balatro_ai_v2.strategy_engine import derive_engine_state
from balatro_ai_v2.strategy_options import PersistentIntent, iter_strategy_options


STRATEGY_DIAGNOSTIC_SCHEMA_VERSION = 3


def strategy_snapshot(
    observation: PublicObservation,
    active_intent: PersistentIntent | None = None,
) -> dict[str, object]:
    """Project engine, goal, intent, boss, deck, and option facts to JSON data."""

    engine = derive_engine_state(observation)
    options = iter_strategy_options(observation, engine)
    option_counts = Counter(option.intent.value for option in options)
    return {
        "schema_version": STRATEGY_DIAGNOSTIC_SCHEMA_VERSION,
        "goal": engine.goal.value,
        "active_intent": active_intent.intent.value if active_intent is not None else None,
        "active_intent_decisions": active_intent.decisions if active_intent is not None else 0,
        "option_count": len(options),
        "option_counts_by_intent": dict(sorted(option_counts.items())),
        "scoring": {
            "role_counts": dict(engine.scoring.role_counts),
            "archetype_tags": sorted(engine.scoring.archetype_tags),
            "scoring_slots": list(engine.scoring.scoring_slots),
            "order_sensitive_slots": list(engine.scoring.order_sensitive_slots),
            "copy_relations": [
                {
                    "source_slot": relation.source_slot,
                    "target_slot": relation.target_slot,
                    "kind": relation.kind.value,
                    "publicly_enabled": relation.publicly_enabled,
                }
                for relation in engine.scoring.copy_relations
            ],
            "unknown_joker_slots": list(engine.scoring.unknown_joker_slots),
        },
        "available_deck": {
            "card_count": engine.available_deck.card_count,
            "distinct_cards": engine.available_deck.distinct_cards,
            "declared_deck_size": engine.available_deck.declared_deck_size,
            "rank_concentration": _fraction(engine.available_deck.rank_concentration),
            "suit_concentration": _fraction(engine.available_deck.suit_concentration),
            "duplicate_concentration": _fraction(engine.available_deck.duplicate_concentration),
            "enhancement_counts": dict(engine.available_deck.enhancement_counts),
            "seal_counts": dict(engine.available_deck.seal_counts),
            "edition_counts": dict(engine.available_deck.edition_counts),
        },
        "economy": {
            "cash": engine.economy.cash,
            "interest_units": engine.economy.interest_units,
            "interest_cap": engine.economy.interest_cap,
            "credit_floor": engine.economy.credit_floor,
            "rental_liability_per_round": engine.economy.rental_liability_per_round,
            "sell_value": engine.economy.sell_value,
            "economy_jokers": engine.economy.economy_jokers,
            "free_rerolls": engine.economy.free_rerolls,
            "unknown_used_vouchers": list(engine.economy.unknown_used_vouchers),
        },
        "consumables": {
            "keys": list(engine.consumables.keys),
            "kinds": dict(engine.consumables.kinds),
            "free_slots": engine.consumables.free_slots,
            "duplicators": list(engine.consumables.duplicators),
            "unknown_keys": list(engine.consumables.unknown_keys),
        },
        "hand_development": {
            "primary_hand": engine.hand_development.primary_hand,
            "secondary_hand": engine.hand_development.secondary_hand,
            "confidence": _fraction(engine.hand_development.confidence),
            "levels": dict(engine.hand_development.levels),
            "played": dict(engine.hand_development.played),
        },
        "boss": {
            "name": engine.boss.name,
            "known": engine.boss.known,
            "disabled": engine.boss.disabled,
            "constraints": sorted(constraint.value for constraint in engine.boss.constraints),
            "conflicts": sorted(engine.boss.conflicts),
            "score_multiplier": engine.boss.score_multiplier,
        },
    }


def summarize_strategy_results(results: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Aggregate failures by visible boss/build without conflating Endless deaths."""

    prewin_boss_failures: Counter[str] = Counter()
    prewin_build_failures: Counter[str] = Counter()
    boss_conflicts: Counter[str] = Counter()
    final_goals: Counter[str] = Counter()
    final_deck_sizes: list[int] = []
    for result in results:
        snapshot = result.get("strategy")
        if not isinstance(snapshot, Mapping):
            continue
        goal = snapshot.get("goal")
        if isinstance(goal, str):
            final_goals[goal] += 1
        deck = snapshot.get("available_deck")
        if isinstance(deck, Mapping) and isinstance(deck.get("declared_deck_size"), int):
            final_deck_sizes.append(int(deck["declared_deck_size"]))
        boss = snapshot.get("boss")
        if isinstance(boss, Mapping):
            for conflict in boss.get("conflicts", ()):
                if isinstance(conflict, str):
                    boss_conflicts[conflict] += 1
        if bool(result.get("won")):
            continue
        terminal = result.get("terminal")
        terminal_blind = terminal.get("terminal_blind") if isinstance(terminal, Mapping) else None
        if (
            isinstance(terminal_blind, Mapping)
            and terminal_blind.get("kind") == "BOSS"
            and isinstance(terminal_blind.get("name"), str)
        ):
            prewin_boss_failures[str(terminal_blind["name"])] += 1
        hand = snapshot.get("hand_development")
        if isinstance(hand, Mapping) and isinstance(hand.get("primary_hand"), str):
            prewin_build_failures[str(hand["primary_hand"])] += 1
    return {
        "schema_version": STRATEGY_DIAGNOSTIC_SCHEMA_VERSION,
        "snapshots": sum(isinstance(result.get("strategy"), Mapping) for result in results),
        "final_goals": dict(sorted(final_goals.items())),
        "prewin_failures_by_terminal_boss": dict(sorted(prewin_boss_failures.items())),
        "prewin_failures_by_primary_hand": dict(sorted(prewin_build_failures.items())),
        "final_boss_conflicts": dict(sorted(boss_conflicts.items())),
        "final_deck_size_min": min(final_deck_sizes) if final_deck_sizes else None,
        "final_deck_size_max": max(final_deck_sizes) if final_deck_sizes else None,
    }


def _fraction(value: Fraction) -> list[int]:
    return [value.numerator, value.denominator]


__all__ = [
    "STRATEGY_DIAGNOSTIC_SCHEMA_VERSION",
    "strategy_snapshot",
    "summarize_strategy_results",
]
