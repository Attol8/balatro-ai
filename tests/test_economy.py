from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from balatro_ai.economy import blind_reward, interest, money_sources, shop_visit, skip_value
from balatro_ai.game.actions import BuyMode, BuyShopCard, LeaveShop, RerollShop, ShopSlot
from balatro_ai.game.codec import public_observation_from_data
from balatro_ai.game.history import HistoryStep
from balatro_ai.game.state import Phase, PublicItem

FIXTURES = Path(__file__).parent / "fixtures" / "pace"


def _shop():
    data = json.loads((FIXTURES / "jbg00002_wheel_shop.json").read_text())["observation"]
    return public_observation_from_data(data)


def test_the_small_blind_pays_nothing_from_red_stake_up() -> None:
    observation = _shop()
    small = replace(observation.blinds[0], kind="SMALL")
    assert blind_reward(replace(observation, stake="GOLD"), small) == 0
    assert blind_reward(replace(observation, stake="WHITE"), small) == 3
    assert blind_reward(observation, replace(small, kind="BIG")) == 4


def test_interest_says_how_much_can_be_spent_without_losing_any() -> None:
    observation = _shop()
    assert interest(replace(observation, money=23))["spend_keeping_interest"] == 3
    assert interest(replace(observation, money=31))["spend_keeping_interest"] == 6
    assert interest(replace(observation, money=4))["at_cashout"] == 0


def test_money_tarots_report_their_payout_now() -> None:
    observation = replace(
        _shop(),
        money=14,
        consumables=(PublicItem("c_hermit", "The Hermit", "TAROT"),),
        shop=(PublicItem("c_temperance", "Temperance", "TAROT", buy_cost=3),),
    )
    rows = {row["key"]: row["pays_now"] for row in money_sources(observation)}
    sell = sum(joker.sell_cost or 0 for joker in observation.jokers)
    assert rows == {"c_hermit": 14, "c_temperance": min(sell, 50)}


def test_skip_value_prices_a_polychrome_tag_against_a_rewardless_small_blind() -> None:
    """JBG00001 played an Ante 3 Small Blind at $1 for a $0 reward instead of the tag."""

    observation = _shop()
    blinds = (
        replace(
            observation.blinds[0],
            kind="SMALL",
            name="Small Blind",
            status="SELECT",
            tag_name="Polychrome Tag",
            tag_effect="Next base edition shop Joker is free and becomes Polychrome",
        ),
    )
    value = skip_value(replace(observation, phase=Phase.BLIND_SELECT, blinds=blinds, stake="GOLD"))
    assert value["reward_if_played"] == 0 and value["tag"] == "Polychrome Tag"
    economy = replace(blinds[0], tag_name="Economy Tag")
    assert skip_value(replace(observation, blinds=(economy,), money=17))["tag_money"] == 17


def test_shop_visit_counts_rerolls_and_spend_since_the_shop_opened() -> None:
    shop = _shop()
    step = lambda before, action, after: HistoryStep(before, action, after)  # noqa: E731
    rerolled = replace(shop, money=shop.money - 5)
    bought = replace(rerolled, money=rerolled.money - 9)
    history = (
        step(replace(shop, phase=Phase.ROUND_EVAL), LeaveShop(), shop),
        step(shop, RerollShop(), rerolled),
        step(rerolled, BuyShopCard(ShopSlot(0), BuyMode.STORE), bought),
    )
    assert shop_visit(history) == {"rerolls": 1, "spent": 14}
