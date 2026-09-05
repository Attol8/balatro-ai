from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction

import pytest

from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.boss_rules import BossConstraint
from balatro_ai_v2.public_state import PublicItem
from balatro_ai_v2.strategy_engine import (
    CopyKind,
    GoalUtility,
    RunGoal,
    derive_engine_state,
)
from state_factory import state


def _joker(key: str, **changes: object) -> PublicItem:
    return PublicItem(key=key, label=key, kind="JOKER", **changes)


def test_goal_switches_only_after_public_win() -> None:
    before = derive_engine_state(to_public_observation(state("BLIND_SELECT")))
    endless = derive_engine_state(to_public_observation(state("BLIND_SELECT", won=True)))

    assert before.goal == RunGoal.VICTORY
    assert endless.goal == RunGoal.ENDLESS


def test_victory_utility_cannot_trade_a_win_for_score() -> None:
    winning = GoalUtility(1.0, 1.0, 8.0, log_score=1.0)
    spectacular_loss = GoalUtility(0.0, 1.0, 7.99, endless_ante=100.0, log_score=1e300)

    assert winning.ordering_key(RunGoal.VICTORY) > spectacular_loss.ordering_key(
        RunGoal.VICTORY
    )
    assert spectacular_loss.ordering_key(RunGoal.ENDLESS) > winning.ordering_key(
        RunGoal.ENDLESS
    )


def test_endless_utility_prefers_a_live_line_to_score_at_the_same_ante() -> None:
    alive = GoalUtility(1.0, 0.2, 9.2, endless_ante=9, log_score=1, alive_probability=1)
    dead = GoalUtility(1.0, 0.9, 9.9, endless_ante=9, log_score=300, alive_probability=0)

    assert alive.ordering_key(RunGoal.ENDLESS) > dead.ordering_key(RunGoal.ENDLESS)


def test_copy_relations_follow_public_joker_order_exactly() -> None:
    observation = replace(
        to_public_observation(state("SHOP")),
        jokers=(
            _joker("j_blueprint"),
            _joker("j_mime"),
            _joker("j_brainstorm"),
        ),
    )

    engine = derive_engine_state(observation)

    assert tuple(
        (
            relation.source_slot,
            relation.target_slot,
            relation.kind,
            relation.publicly_enabled,
        )
        for relation in engine.scoring.copy_relations
    ) == (
        (0, 1, CopyKind.BLUEPRINT_RIGHT, True),
        (2, 0, CopyKind.BRAINSTORM_LEFTMOST, True),
    )


def test_leftmost_brainstorm_self_relation_is_visible_but_not_enabled() -> None:
    observation = replace(
        to_public_observation(state("SHOP")),
        jokers=(_joker("j_brainstorm"), _joker("j_joker")),
    )

    relation = derive_engine_state(observation).scoring.copy_relations[0]

    assert relation.source_slot == relation.target_slot == 0
    assert not relation.publicly_enabled

def test_available_deck_profile_and_public_liabilities_are_compositional() -> None:
    observation = replace(
        to_public_observation(state("SHOP", money=27)),
        jokers=(
            _joker("j_credit_card", rental=True, sell_cost=2),
            _joker("j_chaos", sell_cost=3),
        ),
        used_vouchers=("v_money_tree",),
    )

    engine = derive_engine_state(observation)

    assert engine.available_deck.card_count == 3
    assert engine.available_deck.rank_concentration == Fraction(1, 3)
    assert engine.available_deck.suit_concentration == Fraction(1, 3)
    assert engine.economy.interest_cap == 20
    assert engine.economy.interest_units == 5
    assert engine.economy.credit_floor == -20
    assert engine.economy.rental_liability_per_round == 3
    assert engine.economy.free_rerolls == 1


def test_boss_vulnerability_uses_audited_rule_and_visible_engine_tags() -> None:
    observation = replace(
        to_public_observation(state("SHOP")),
        jokers=(_joker("j_lusty_joker"),),
    )

    boss = derive_engine_state(observation).boss

    assert boss.name == "The Head"
    assert boss.known
    assert BossConstraint.SUIT_DEBUFF in boss.constraints
    assert "debuffs_hearts" in boss.conflicts


def test_disabled_current_boss_has_no_strategy_constraints() -> None:
    raw = state("SELECTING_HAND")
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["boss"].update(
        name="The Head", status="CURRENT", disabled=True
    )

    boss = derive_engine_state(to_public_observation(raw)).boss

    assert boss.name == "The Head"
    assert boss.known
    assert boss.disabled
    assert not boss.constraints
    assert not boss.conflicts


def test_unknown_boss_and_joker_mechanics_fail_closed() -> None:
    observation = to_public_observation(state("SHOP"))
    observation = replace(
        observation,
        jokers=(_joker("j_future_mod"),),
        blinds=tuple(
            replace(blind, name="Future Boss") if blind.kind == "BOSS" else blind
            for blind in observation.blinds
        ),
    )

    engine = derive_engine_state(observation)

    assert engine.scoring.unknown_joker_slots == (0,)
    assert not engine.boss.known
    assert not engine.boss.constraints
    assert not engine.boss.conflicts


def test_hidden_private_twins_have_identical_engine_state() -> None:
    left = state("SHOP", seed="PRIVATE-A")
    right = deepcopy(left)
    right["seed"] = "PRIVATE-B"
    right["cards"]["cards"].reverse()
    for card in right["cards"]["cards"]:
        card["id"] += 100_000

    assert derive_engine_state(to_public_observation(left)) == derive_engine_state(
        to_public_observation(right)
    )


def test_engine_state_is_immutable() -> None:
    engine = derive_engine_state(to_public_observation(state("SHOP")))

    with pytest.raises(FrozenInstanceError):
        engine.goal = RunGoal.ENDLESS  # type: ignore[misc]
