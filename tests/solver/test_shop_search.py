from dataclasses import replace

from balatro_ai_v2.solver.actions import BuyMode, BuyPack, BuyVoucher, PackOfferSlot, VoucherSlot, BuyShopCard, LeaveShop, RerollShop, SellJoker, ShopSlot, UseConsumable, ConsumableSlot, is_legal
from balatro_ai_v2.solver.adapter import to_public_observation
from balatro_ai_v2.solver.policy import PublicHistoryStep
from balatro_ai_v2.solver.public_state import DeckCardCount, HandStat, Phase, PublicItem, VisiblePlayingCard
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


def test_pending_upgrade_precedes_spending_on_packs_or_vouchers():
    for alternative in (BuyPack(PackOfferSlot(0)), BuyVoucher(VoucherSlot(0))):
        planner = ShopSearch(samples=1)
        obs = shop(money=20, offers=(item('j_cavendish', 8),), jokers=(item('j_juggler'),), limit=1)
        assert isinstance(planner.choose(obs, LeaveShop()).action, SellJoker)
        after_sale = replace(obs, jokers=(), money=22)
        choice = planner.choose(after_sale, alternative)
        assert choice.action == BuyShopCard(ShopSlot(0))
        assert is_legal(after_sale, choice.action)


def test_pending_upgrade_still_requires_exact_affordable_offer():
    planner = ShopSearch(samples=1)
    obs = shop(money=20, offers=(item('j_cavendish', 8),), jokers=(item('j_juggler'),), limit=1)
    assert isinstance(planner.choose(obs, LeaveShop()).action, SellJoker)
    after_sale = replace(obs, jokers=(), money=1)
    assert planner.choose(after_sale, BuyPack(PackOfferSlot(0))) is None


def test_late_weak_build_buys_stuntman_instead_of_hoarding_25():
    obs = shop(money=26, offers=(item('j_stuntman', 7),))
    obs = replace(obs, ante=7, blinds=tuple(replace(b, score=70000) for b in obs.blinds))
    choice = ShopSearch(samples=1).choose(obs, LeaveShop())
    assert choice.action == BuyShopCard(ShopSlot(0))
    assert choice.diagnostics['reserve'] == 2


def test_blue_joker_uses_full_deck_minus_synthetic_hand():
    obs = shop(jokers=(item('j_blue_joker'),))
    obs = replace(obs, hand_limit=1, remaining_deck=(), draw_count=0)
    ace = next(entry.card for entry in obs.full_deck if entry.card.rank == 'A')
    first, _, _ = ShopSearch._capacity_components(obs, ((ace,),))
    # High Card 5 + Ace 11 + two undrawn cards * Blue Joker 2.
    assert first == 20
    assert obs.draw_count == 0


def test_stuntman_purchase_reduces_candidate_hand_size(monkeypatch):
    planner = ShopSearch(samples=1)
    original = planner._capacity_components
    inspected = []
    def capture(obs, hands):
        inspected.append((tuple(j.key for j in obs.jokers), obs.hand_limit))
        return original(obs, hands)
    monkeypatch.setattr(planner, '_capacity_components', capture)
    obs = shop(offers=(item('j_stuntman', 7),))
    planner.choose(obs, LeaveShop())
    assert ((), 3) in inspected
    assert (('j_stuntman',), 1) in inspected


def test_selling_juggler_removes_its_hand_size_bonus(monkeypatch):
    planner = ShopSearch(samples=1)
    original = planner._capacity_components
    inspected = []
    def capture(obs, hands):
        inspected.append((tuple(j.key for j in obs.jokers), obs.hand_limit))
        return original(obs, hands)
    monkeypatch.setattr(planner, '_capacity_components', capture)
    obs = shop(offers=(item('j_cavendish'),), jokers=(item('j_juggler'),), limit=1)
    planner.choose(obs, LeaveShop())
    assert (('j_cavendish',), 2) in inspected


def test_shared_sample_stream_is_independent_of_loadout_hand_size():
    obs = shop()
    deck = tuple(DeckCardCount(VisiblePlayingCard(rank=r, suit='S'), 1)
                 for r in ('A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2'))
    obs = replace(obs, full_deck=deck, remaining_deck=deck, draw_count=13, deck_size=13, hand_limit=8)
    planner = ShopSearch(samples=2)
    assert planner._hands(obs) == planner._hands(replace(obs, hand_limit=9))
    assert all(len(stream) == 12 for stream in planner._hands(obs))


def test_unknown_turtle_bean_hand_size_is_not_projected():
    obs = shop(offers=(item('j_turtle_bean', 1),))
    assert ShopSearch(samples=1, max_rerolls=0).choose(obs, LeaveShop()) is None


def planet(key='c_pluto', cost=3):
    return PublicItem(key=key, label=key, kind='PLANET', buy_cost=cost, sell_cost=1)


def test_planet_ablation_is_off_by_default():
    obs = shop(offers=(planet(),))
    assert ShopSearch(samples=1, max_rerolls=0).choose(obs, LeaveShop()) is None
    choice = ShopSearch(samples=1, max_rerolls=0, evaluate_planets=True).choose(obs, LeaveShop())
    assert choice.action == BuyShopCard(ShopSlot(0), BuyMode.USE)
    assert choice.diagnostics['candidate_first_hand'] == 52
    assert choice.diagnostics['desired_planet'] == 'c_pluto'


def test_irrelevant_planet_does_not_improve_sampled_hands():
    obs = shop(offers=(planet('c_mercury'),))
    obs = replace(obs, hand_stats=obs.hand_stats + (HandStat('Pair', 1, 10, 2, 0, 0),))
    choice = ShopSearch(samples=1, max_rerolls=0, evaluate_planets=True).choose(obs, LeaveShop())
    assert isinstance(choice.action, LeaveShop)
    assert choice.diagnostics['best_planet_utility'] < 0


def test_planet_capacity_accounts_for_bull_cash_spending():
    obs = shop(money=20, offers=(planet(),), jokers=(item('j_bull'),))
    choice = ShopSearch(samples=1, max_rerolls=0, evaluate_planets=True).choose(obs, LeaveShop())
    # Planet: (High Card 15 + Ace 11 + Bull 2*$17) * 2.
    assert choice.diagnostics['candidate_first_hand'] == 120


def test_planet_ablation_preserves_reserve_and_use_legality():
    planner = ShopSearch(samples=1, max_rerolls=0, evaluate_planets=True)
    obs = shop(money=2, offers=(planet(),))
    assert isinstance(planner.choose(obs, LeaveShop()).action, LeaveShop)
    obs = replace(obs, money=4)
    assert 'protected cash reserve' in planner.choose(obs, LeaveShop()).diagnostics['planet_screen']
    obs = replace(obs, money=5, consumable_limit=0)
    choice = planner.choose(obs, LeaveShop())
    assert choice.action == BuyShopCard(ShopSlot(0), BuyMode.USE)
    assert is_legal(obs, choice.action)


def test_planet_ablation_skips_observatory():
    obs = replace(shop(offers=(planet(),)), used_vouchers=('v_observatory',))
    choice = ShopSearch(samples=1, max_rerolls=0, evaluate_planets=True).choose(obs, LeaveShop())
    assert isinstance(choice.action, LeaveShop)
    assert 'Observatory' in choice.diagnostics['planet_screen']


def test_planet_and_joker_compete_on_same_capacity_utility():
    obs = shop(offers=(planet(), item('j_joker', 3)))
    choice = ShopSearch(samples=1, max_rerolls=0, evaluate_planets=True).choose(obs, LeaveShop())
    assert choice.action == BuyShopCard(ShopSlot(1))
