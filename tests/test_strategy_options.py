from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest

import balatro_ai_v2.strategy_options as strategy_options_module
from balatro_ai_v2.actions import (
    BuyPack,
    BuyShopCard,
    ReorderJokers,
    UseConsumable,
    iter_legal_actions,
)
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.public_state import PublicItem
from balatro_ai_v2.strategy_engine import derive_engine_state
from balatro_ai_v2.strategy_options import (
    PersistentIntent,
    StrategyIntent,
    build_strategy_candidates,
    iter_strategy_options,
    options_for_intent,
)
from state_factory import item_card, state


def _with_consumable(key: str):
    raw = state("SELECTING_HAND")
    raw["consumables"]["cards"] = [item_card(key, card_id=80, kind="TAROT")]
    raw["consumables"]["count"] = 1
    return to_public_observation(raw)


def _joker(key: str) -> PublicItem:
    return PublicItem(key=key, label=key, kind="JOKER", buy_cost=1, sell_cost=1)


def test_every_emitted_option_starts_with_a_currently_legal_action() -> None:
    for phase in ("BLIND_SELECT", "SELECTING_HAND", "ROUND_EVAL", "SHOP", "BUFFOON_PACK"):
        observation = to_public_observation(state(phase))
        legal = set(iter_legal_actions(observation))
        options = iter_strategy_options(observation)

        assert options
        assert all(option.first_action in legal for option in options)
        assert all(option.is_legal(observation) for option in options)


def test_death_targets_are_deck_sculpting_options() -> None:
    observation = _with_consumable("c_death")

    options = options_for_intent(observation, StrategyIntent.DECK_SCULPT)

    death = [option for option in options if isinstance(option.first_action, UseConsumable)]
    assert death
    assert all(len(option.first_action.targets) == 2 for option in death)


def test_hermit_is_an_economy_option() -> None:
    observation = _with_consumable("c_hermit")

    options = options_for_intent(observation, StrategyIntent.ECONOMY)

    assert any(isinstance(option.first_action, UseConsumable) for option in options)


def test_copy_reorders_are_exposed_as_retrigger_engine_options() -> None:
    observation = replace(
        to_public_observation(state("SHOP")),
        jokers=(_joker("j_blueprint"), _joker("j_mime"), _joker("j_joker")),
    )

    held = options_for_intent(observation, StrategyIntent.HELD_RETRIGGER_ENGINE)

    assert any(isinstance(option.first_action, ReorderJokers) for option in held)


def test_blue_seal_generation_option_holds_instead_of_playing_the_seal() -> None:
    raw = state("SELECTING_HAND")
    raw["hand"]["cards"][0]["modifier"] = ["BLUE"]
    observation = to_public_observation(raw)

    generation = options_for_intent(observation, StrategyIntent.CONSUMABLE_GENERATION)
    plays = [option.first_action for option in generation if hasattr(option.first_action, "cards")]

    assert plays
    assert all(0 not in {slot.value for slot in action.cards} for action in plays)


def test_luchador_purchase_is_a_boss_preparation_option() -> None:
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        shop=(_joker("j_luchador"),),
    )

    options = options_for_intent(observation, StrategyIntent.BOSS_PREPARATION)

    assert any(isinstance(option.first_action, BuyShopCard) for option in options)


def test_unknown_shop_mechanic_gets_no_speculative_strategy() -> None:
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        shop=(PublicItem("j_future_mod", "Future", "JOKER", buy_cost=1),),
    )

    options = iter_strategy_options(observation)

    assert not any(
        isinstance(option.first_action, BuyShopCard) for option in options
    )


def test_nonexistent_buffoon_lookalike_gets_no_pack_strategy() -> None:
    observation = replace(
        to_public_observation(state("SHOP", money=10)),
        packs=(PublicItem("p_buffoon_jumbo_2", "Future pack", "BOOSTER", buy_cost=1),),
    )

    options = iter_strategy_options(observation)

    assert not any(isinstance(option.first_action, BuyPack) for option in options)


def test_persistent_intent_survives_revalidation_and_resets_on_goal_change() -> None:
    observation = _with_consumable("c_hermit")
    engine = derive_engine_state(observation)
    option = options_for_intent(observation, StrategyIntent.ECONOMY)[0]
    intent = PersistentIntent.start(option, engine)

    continued = intent.advance(option, engine)
    won_observation = replace(observation, ante=9, antes_cleared=8, won=True)
    won_engine = derive_engine_state(won_observation)
    endless_option = replace(option, intent=StrategyIntent.ENDLESS_GROWTH)
    reset = continued.advance(endless_option, won_engine)

    assert continued.decisions == 2
    assert continued.started_ante == observation.ante
    assert reset.decisions == 1
    assert reset.goal == won_engine.goal


def test_endless_growth_intent_is_not_exposed_before_public_win() -> None:
    before = to_public_observation(state("SELECTING_HAND"))
    after = replace(before, ante=9, antes_cleared=8, won=True)

    assert not options_for_intent(before, StrategyIntent.ENDLESS_GROWTH)
    assert options_for_intent(after, StrategyIntent.ENDLESS_GROWTH)


def test_expert_vignettes_cover_every_declared_strategy_intent() -> None:
    hermit = _with_consumable("c_hermit")
    death = _with_consumable("c_death")
    red_seal_raw = state("SELECTING_HAND")
    red_seal_raw["hand"]["cards"][0]["modifier"] = ["RED"]
    red_seal = to_public_observation(red_seal_raw)
    held_raw = state("SELECTING_HAND")
    held_raw["hand"]["cards"][0]["modifier"] = ["BLUE"]
    held = replace(
        to_public_observation(held_raw),
        jokers=(_joker("j_baron"),),
    )
    boss_prep = replace(
        to_public_observation(state("SHOP", money=10)),
        shop=(_joker("j_luchador"),),
    )
    endless = replace(red_seal, ante=9, antes_cleared=8, won=True)

    seen = {
        option.intent
        for observation in (hermit, death, red_seal, held, boss_prep, endless)
        for option in iter_strategy_options(observation)
    }

    assert seen == set(StrategyIntent)


def test_hidden_private_twins_have_identical_strategy_options() -> None:
    left = state("SHOP", seed="PRIVATE-A")
    right = deepcopy(left)
    right["seed"] = "PRIVATE-B"
    right["cards"]["cards"].reverse()
    for card in right["cards"]["cards"]:
        card["id"] += 100_000

    assert iter_strategy_options(to_public_observation(left)) == iter_strategy_options(
        to_public_observation(right)
    )


def test_candidate_contract_preserves_active_intent_and_reorder_scope() -> None:
    observation = replace(
        to_public_observation(state("SHOP")),
        jokers=(_joker("j_blueprint"), _joker("j_mime"), _joker("j_joker")),
    )
    legal = tuple(iter_legal_actions(observation))
    option = next(
        option
        for option in iter_strategy_options(observation)
        if option.intent == StrategyIntent.HELD_RETRIGGER_ENGINE
        and isinstance(option.first_action, ReorderJokers)
    )
    active = PersistentIntent.start(option, derive_engine_state(observation))

    without = build_strategy_candidates(
        observation,
        legal,
        option.first_action,
        active_intent=active,
        include_reorders=False,
    )
    with_reorders = build_strategy_candidates(
        observation,
        legal,
        option.first_action,
        active_intent=active,
        include_reorders=True,
    )

    assert without[0].identity == (option.first_action, active.intent)
    assert not any(isinstance(root.action, ReorderJokers) for root in without[1:])
    assert any(isinstance(root.action, ReorderJokers) for root in with_reorders)
    assert len({root.identity for root in with_reorders}) == len(with_reorders)


def test_candidate_contract_reuses_the_captured_legal_action_tuple(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observation = to_public_observation(state("SHOP", money=10))
    legal = tuple(iter_legal_actions(observation))
    expected = iter_strategy_options(observation)
    monkeypatch.setattr(
        strategy_options_module,
        "iter_legal_actions",
        lambda observation: pytest.fail("legal actions were enumerated twice"),
    )

    actual = iter_strategy_options(observation, legal_actions=legal)

    assert actual == expected
