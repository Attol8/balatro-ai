from dataclasses import replace

from balatro_ai_v2.solver.actions import BuyShopCard, LeaveShop, RerollShop, SellJoker, ShopSlot, UseConsumable, ConsumableSlot, is_legal
from balatro_ai_v2.solver.adapter import to_public_observation
from balatro_ai_v2.solver.policy import PublicHistoryStep
from balatro_ai_v2.solver.public_state import DeckCardCount, Phase, PublicItem, VisiblePlayingCard
from balatro_ai_v2.solver.shop_search import ShopSearch
from solver_state_factory import state


def item(key, cost=4, **kwargs):
    return PublicItem(key=key, label=key, kind='JOKER', buy_cost=cost, sell_cost=2, **kwargs)


def shop(money=20, offers=(), jokers=(), limit=5):
    obs = to_public_observation(state('SHOP', money=money))
    deck = tuple(DeckCardCount(VisiblePlayingCard(rank=r, suit='S'), 1) for r in ('A', 'K', '2'))
    return replace(obs, full_deck=deck, deck_size=3, remaining_deck=deck, draw_count=3,
                   hand_limit=3, shop=offers, jokers=jokers, joker_limit=limit)


def test_buys_measurable_scoring_gain_using_next_blind():
    obs = shop(offers=(item('j_joker'),))
    choice = ShopSearch(samples=2).choose(obs, LeaveShop())
    assert isinstance(choice.action, BuyShopCard)
    assert is_legal(obs, choice.action)
    assert choice.diagnostics['candidate_capacity'] > choice.diagnostics['current_capacity']
    assert choice.diagnostics['next_blind_target'] == 450


def test_no_unaffordable_purchase_or_sale():
    obs = shop(money=1, offers=(item('j_cavendish', 20),), jokers=(item('j_joker'),), limit=1)
    assert ShopSearch(samples=1).choose(obs, LeaveShop()) is None


def test_weak_build_relaxes_reserve_but_keeps_minimum():
    planner = ShopSearch(samples=1)
    obs = shop(money=6, offers=(item('j_joker', 4),))
    assert isinstance(planner.choose(obs, LeaveShop()).action, BuyShopCard)
    assert planner.choose(replace(obs, money=5), LeaveShop()) is None


def test_full_slot_upgrade_commits_to_revalidated_purchase():
    planner = ShopSearch(samples=1)
    obs = shop(money=20, offers=(item('j_cavendish', 8),), jokers=(item('j_juggler'),), limit=1)
    sale = planner.choose(obs, LeaveShop())
    assert isinstance(sale.action, SellJoker)
    after_sale = replace(obs, jokers=(), money=22)
    purchase = planner.choose(after_sale, LeaveShop())
    assert purchase.action == BuyShopCard(ShopSlot(0))
    assert is_legal(after_sale, purchase.action)


def test_stale_planned_purchase_is_not_issued():
    planner = ShopSearch(samples=1, max_rerolls=0)
    obs = shop(offers=(item('j_cavendish'),), jokers=(item('j_juggler'),), limit=1)
    assert isinstance(planner.choose(obs, LeaveShop()).action, SellJoker)
    assert planner.choose(replace(obs, shop=(), jokers=()), LeaveShop()) is None


def test_eternal_and_negative_cards_cannot_be_sold_for_slot():
    for old in (item('j_juggler', eternal=True), item('j_juggler', edition='NEGATIVE')):
        obs = shop(offers=(item('j_cavendish'),), jokers=(old,), limit=1)
        choice = ShopSearch(samples=1, max_rerolls=0).choose(obs, LeaveShop())
        assert choice is None


def test_negative_offer_can_be_purchased_with_full_slots():
    obs = shop(offers=(item('j_joker', edition='NEGATIVE'),), jokers=(item('j_juggler'),), limit=1)
    assert isinstance(ShopSearch(samples=1).choose(obs, LeaveShop()).action, BuyShopCard)


def test_reroll_is_bounded_by_history_and_money():
    obs = shop()
    planner = ShopSearch(samples=1, max_rerolls=1)
    assert isinstance(planner.choose(obs, LeaveShop()).action, RerollShop)
    history = (PublicHistoryStep(obs, RerollShop(), obs),)
    assert planner.choose(obs, LeaveShop(), history) is None
    assert isinstance(planner.choose(obs, RerollShop(), history).action, LeaveShop)
    assert planner.choose(replace(obs, money=5), LeaveShop()) is None


def test_private_seed_and_order_never_enter_sampling():
    obs = shop(offers=(item('j_joker'),))
    a = ShopSearch(samples=2).choose(obs, LeaveShop())
    b = ShopSearch(samples=2).choose(replace(obs, remaining_deck=tuple(reversed(obs.remaining_deck))), LeaveShop())
    assert a == b


def test_other_phases_and_consumable_decisions_remain_untouched():
    obs = shop()
    assert ShopSearch().choose(replace(obs, phase=Phase.ROUND_EVAL), LeaveShop()) is None
    assert ShopSearch().choose(obs, UseConsumable(ConsumableSlot(0))) is None


def test_unknown_joker_is_not_bought_for_generic_tier_value():
    obs = shop(offers=(item('j_not_vanilla', 1),))
    assert ShopSearch(samples=1, max_rerolls=0).choose(obs, LeaveShop()) is None


def test_capacity_clears_previous_disabled_boss():
    obs = shop(offers=(item('j_joker'),))
    boss = replace(obs.blinds[-1], status='CURRENT', disabled=True)
    obs = replace(obs, blinds=(boss,))
    assert ShopSearch(samples=1).choose(obs, LeaveShop()) is not None


def test_card_sharp_is_valued_on_repeated_family_not_first_hand():
    obs = shop(offers=(item('j_card_sharp', 6),), jokers=(item('j_joker'),))
    choice = ShopSearch(samples=1).choose(obs, LeaveShop())
    assert isinstance(choice.action, BuyShopCard)
    diagnostic = choice.diagnostics
    assert diagnostic['candidate_first_hand'] == diagnostic['current_first_hand']
    assert diagnostic['candidate_repeat_hand'] == 3 * diagnostic['candidate_first_hand']
    assert diagnostic['candidate_capacity'] > diagnostic['current_capacity']


def test_cheap_green_joker_has_explicit_bounded_growth_projection():
    obs = shop(offers=(item('j_green_joker', 2),), jokers=(item('j_joker'),))
    choice = ShopSearch(samples=1).choose(obs, LeaveShop())
    assert isinstance(choice.action, BuyShopCard)
    diagnostic = choice.diagnostics
    assert diagnostic['candidate_final_hand'] > diagnostic['candidate_repeat_hand'] > diagnostic['candidate_first_hand']
    assert 'Green Joker +1' in diagnostic['continuation_assumption']
    assert obs.shop[0].runtime is None


def test_acrobat_valued_only_in_final_hand_component():
    obs = shop(offers=(item('j_acrobat', 4),), jokers=(item('j_joker'),))
    choice = ShopSearch(samples=1).choose(obs, LeaveShop())
    assert isinstance(choice.action, BuyShopCard)
    diagnostic = choice.diagnostics
    assert diagnostic['candidate_first_hand'] == diagnostic['candidate_repeat_hand']
    assert diagnostic['candidate_final_hand'] == 3 * diagnostic['candidate_first_hand']
