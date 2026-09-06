from dataclasses import replace

import pytest

from balatro_ai_v2.solver.actions import (
    BuyPack, BuyShopCard, BuyVoucher, LeaveShop, PackOfferSlot, ReorderJokers,
    SellJoker, ShopSlot, VoucherSlot, is_legal,
)
from balatro_ai_v2.solver.public_state import Phase, PublicItem, PublicJokerRuntime
from balatro_ai_v2.solver.shop_search import ShopSearch
from test_shop_search import item, shop


def blueprint_shop(*, full=False):
    return shop(money=50, offers=(item('j_blueprint', 10),),
                jokers=(item('j_cavendish'),
                        item('j_juggler')) if full else
                       (item('j_cavendish'),),
                limit=2 if full else 5)


def test_placement_valuation_and_purchase_reorder_are_opt_in():
    obs = blueprint_shop()
    control = ShopSearch(samples=1, max_rerolls=0)
    assert control.choose(obs, LeaveShop()) is None
    planner = ShopSearch(samples=1, max_rerolls=0, evaluate_blueprint_placement=True)
    choice = planner.choose(obs, LeaveShop())
    assert isinstance(choice.action, BuyShopCard)
    assert choice.diagnostics['candidate_capacity'] > choice.diagnostics['current_capacity']
    owned_blueprint = replace(obs.shop[0], buy_cost=99, sell_cost=7, runtime=PublicJokerRuntime(current_mult=0))
    after = replace(obs, jokers=obs.jokers + (owned_blueprint,), shop=(), money=40)
    swap = planner.choose(after, LeaveShop())
    assert isinstance(swap.action, ReorderJokers) and is_legal(after, swap.action)
    settled = replace(after, jokers=tuple(after.jokers[i.value] for i in swap.action.order))
    assert planner.choose(settled, LeaveShop()) is None
    assert planner._blueprint_order is None


@pytest.mark.parametrize('baseline', [BuyPack(PackOfferSlot(0)), BuyVoucher(VoucherSlot(0)), BuyShopCard(ShopSlot(1))])
@pytest.mark.parametrize('broad', [False, True])
def test_blueprint_candidate_precedes_discretionary_purchase_only_when_enabled(baseline, broad):
    obs = blueprint_shop()
    planet = PublicItem('c_mercury', 'Mercury', 'PLANET', buy_cost=3)
    obs = replace(obs, shop=obs.shop + (planet,))
    assert ShopSearch(samples=1).choose(obs, baseline) is None
    choice = ShopSearch(samples=1, evaluate_blueprint_placement=True, prioritize_all_jokers=broad).choose(obs, baseline)
    assert choice.action == BuyShopCard(ShopSlot(0))
    empty = replace(obs, shop=(planet, planet))
    assert ShopSearch(samples=1, evaluate_blueprint_placement=True).choose(empty, baseline) is None


@pytest.mark.parametrize('baseline', [BuyPack(PackOfferSlot(0)), BuyVoucher(VoucherSlot(0)), BuyShopCard(ShopSlot(1))])
def test_narrow_priority_keeps_ordinary_upgrades_from_preempting_purchases(baseline):
    planet = PublicItem('c_mercury', 'Mercury', 'PLANET', buy_cost=3)
    obs = shop(money=50, offers=(item('j_joker', 2), planet), jokers=())
    broad = ShopSearch(samples=1, evaluate_blueprint_placement=True)
    narrow = ShopSearch(samples=1, evaluate_blueprint_placement=True, prioritize_all_jokers=False)
    assert broad.choose(obs, baseline).action == BuyShopCard(ShopSlot(0))
    assert narrow.choose(obs, baseline) is None
    assert narrow.choose(obs, LeaveShop()).action == BuyShopCard(ShopSlot(0))


def test_sale_buy_reorder_sequence_checks_inventory_and_legality():
    obs = blueprint_shop(full=True)
    planner = ShopSearch(samples=1, max_rerolls=0, evaluate_blueprint_placement=True)
    sale = planner.choose(obs, LeaveShop())
    assert isinstance(sale.action, SellJoker) and sale.action.joker.value == 1
    assert is_legal(obs, sale.action)
    after_sale = replace(obs, jokers=obs.jokers[:1], money=52)
    purchase = planner.choose(after_sale, LeaveShop())
    assert purchase.action == BuyShopCard(ShopSlot(0)) and is_legal(after_sale, purchase.action)
    after_buy = replace(after_sale, jokers=after_sale.jokers + (obs.shop[0],), money=42, shop=())
    swap = planner.choose(after_buy, LeaveShop())
    assert isinstance(swap.action, ReorderJokers) and is_legal(after_buy, swap.action)


@pytest.mark.parametrize('stage', ['sale', 'buy'])
@pytest.mark.parametrize('change', ['inventory', 'phase', 'round'])
def test_pending_plan_cancels_without_guessing(stage, change):
    obs = blueprint_shop(full=stage == 'sale')
    planner = ShopSearch(samples=1, max_rerolls=0, evaluate_blueprint_placement=True)
    planner.choose(obs, LeaveShop())
    after = replace(obs, jokers=obs.jokers[:1]) if stage == 'sale' else replace(obs, jokers=obs.jokers + (obs.shop[0],))
    if change == 'inventory':
        after = replace(after, jokers=(item('j_joker'),) + after.jokers[1:])
    elif change == 'phase':
        after = replace(after, phase=Phase.BLIND_SELECT)
    else:
        after = replace(after, round_no=obs.round_no + 1)
    assert planner.choose(after, LeaveShop()) is None
    assert planner._blueprint_purchase is None and planner._blueprint_order is None


def test_duplicate_blueprints_move_only_new_appended_occurrence_with_bounded_swaps():
    obs = blueprint_shop()
    blueprint = obs.shop[0]
    # Exercise execution independently: two equal fingerprints, distinct positions.
    obs = replace(obs, jokers=(blueprint, obs.jokers[0], item('j_joker')))
    planner = ShopSearch(samples=1, max_rerolls=0, evaluate_blueprint_placement=True)
    planner._arm_blueprint_order(obs, blueprint, 1)
    after = replace(obs, jokers=obs.jokers + (blueprint,), shop=())
    for expected_order in ((0, 1, 3, 2), (0, 2, 1, 3)):
        choice = planner.choose(after, LeaveShop())
        assert tuple(i.value for i in choice.action.order) == expected_order
        assert is_legal(after, choice.action)
        after = replace(after, jokers=tuple(after.jokers[i] for i in expected_order))
    assert planner.choose(after, LeaveShop()) is None
    assert planner._blueprint_order is None


def test_opt_in_requires_boolean():
    with pytest.raises(ValueError):
        ShopSearch(evaluate_blueprint_placement=1)
