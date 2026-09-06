"""Focused objective/budget tests, independent of live game transport."""
from dataclasses import replace

import pytest

from balatro_ai_v2.solver.actions import LeaveShop, RerollShop, BuyPack, PackOfferSlot, SkipPack, BuyShopCard
from balatro_ai_v2.solver.adapter import to_public_observation
from balatro_ai_v2.solver.policy import PublicHistoryStep
from balatro_ai_v2.solver.public_state import DeckCardCount, PublicBlind, PublicItem, VisiblePlayingCard, Phase
from balatro_ai_v2.solver.shop_search import ShopSearch
from solver_state_factory import state


def observation(jokers=(), offers=()):
    obs = to_public_observation(state('SHOP', money=100))
    deck = tuple(DeckCardCount(VisiblePlayingCard(r, 'S'), 1) for r in ('A', 'K', '2'))
    return replace(obs, ante=6, round_no=10, full_deck=deck, deck_size=3,
                   remaining_deck=deck, draw_count=3, hand_limit=3, jokers=jokers, shop=offers,
                   round=replace(obs.round, reroll_cost=0),
                   blinds=(PublicBlind('SMALL', 'DEFEATED', 'Small Blind', '', 100, False),
                           PublicBlind('BIG', 'UPCOMING', 'Big Blind', '', 300, False),
                           PublicBlind('BOSS', 'UPCOMING', 'Violet Vessel', '', 300000, False)))


def planner(**kwargs):
    return ShopSearch(samples=1, project_next_boss=True, boss_readiness=True, **kwargs)


def history_to(obs, *, visit=0, prior_visit=0, earlier_ante=0, excursion=False):
    """Connected public steps for testing bookkeeping, not engine replay."""
    history = []
    current = replace(obs, ante=1, round_no=0, antes_cleared=0)
    def transition(action, after):
        nonlocal current
        history.append(PublicHistoryStep(current, action, after))
        current = after
    for i in range(earlier_ante):
        transition(RerollShop(), current)
    transition(LeaveShop(), replace(obs, round_no=9))
    for i in range(prior_visit):
        transition(RerollShop(), current)
    transition(LeaveShop(), obs)
    for i in range(visit):
        transition(RerollShop(), current)
    if excursion:
        pack = replace(current, phase=Phase.PACK, shop=(), vouchers=(), packs=(),
                       opened_pack=(PublicItem('c_pluto', 'Pluto', 'PLANET'),),
                       pack_kind='CELESTIAL', pack_choices_remaining=1)
        transition(BuyPack(PackOfferSlot(0)), pack)
        transition(SkipPack(), obs)
    return tuple(history)


def test_visible_violet_target_is_not_multiplied_and_immediate_readiness_is_separate(monkeypatch):
    obs = observation()
    monkeypatch.setattr(ShopSearch, '_capacity_components', staticmethod(lambda *args: (200, 200, 200)))
    choice = planner().choose(obs, LeaveShop())
    assert choice.diagnostics['public_boss_target'] == 300000
    assert choice.diagnostics['immediate_pace_ratio'] == 2
    assert choice.diagnostics['boss_pace_ratio'] == pytest.approx(.002)
    assert choice.diagnostics['reserve'] == 2


def test_water_projects_zero_discards_for_banner_and_summit():
    obs = observation(jokers=(PublicItem('j_banner', 'Banner', 'JOKER'),))
    water = PublicBlind('BOSS', 'CURRENT', 'The Water', '', 10000, False)
    p = planner()
    hands = p._hands(obs)
    with_banner = p._capacity_components(obs, hands, water)
    without = p._capacity_components(replace(obs, jokers=()), hands, water)
    with_summit = p._capacity_components(replace(obs, jokers=(PublicItem('j_mystic_summit', 'Summit', 'JOKER'),)), hands, water)
    assert with_banner == without
    assert with_summit[0] > without[0]


def test_boss_oriented_upgrade_cannot_reduce_immediate_safe_capacity(monkeypatch):
    offer = PublicItem('j_joker', 'Joker', 'JOKER', buy_cost=1, sell_cost=1)
    obs = observation(offers=(offer,))
    def capacity(candidate, hands, blind=None):
        boss = blind is not None and blind.name == 'Violet Vessel'
        value = (100000 if boss else 90) if candidate.jokers else (100 if boss else 200)
        return (value,) * 3
    monkeypatch.setattr(ShopSearch, '_capacity_components', staticmethod(capacity))
    choice = planner(max_rerolls=0).choose(obs, LeaveShop())
    assert not isinstance(choice.action, BuyShopCard)
    assert choice.action == LeaveShop()


@pytest.mark.parametrize('baseline', [LeaveShop(), RerollShop()])
def test_four_actual_visit_rerolls_cap_even_free_and_after_pack(baseline):
    obs = observation()
    p = planner()
    assert isinstance(p.choose(obs, baseline, history_to(obs, visit=3)).action, RerollShop)
    choice = p.choose(obs, baseline, history_to(obs, visit=4, excursion=True))
    assert choice.action == LeaveShop()
    assert choice.diagnostics['reroll_limit'] == 4


def test_six_actual_current_ante_rerolls_cap_across_visits():
    obs = observation()
    p = planner()
    assert isinstance(p.choose(obs, LeaveShop(), history_to(obs, visit=2, prior_visit=3)).action, RerollShop)
    choice = p.choose(obs, RerollShop(), history_to(obs, visit=2, prior_visit=4))
    assert choice.action == LeaveShop()
    assert choice.diagnostics['ante_rerolls'] == 6


def test_previous_ante_rerolls_do_not_spend_current_ante_budget():
    obs = observation()
    choice = planner().choose(obs, LeaveShop(), history_to(obs, earlier_ante=20))
    assert isinstance(choice.action, RerollShop)
    assert choice.diagnostics['ante_rerolls'] == 0


def test_incomplete_history_does_not_expand_visit_budget():
    obs = observation()
    history = history_to(obs, visit=2)
    for incomplete in ((), history[1:]):
        choice = planner().choose(obs, RerollShop(), incomplete)
        assert choice.diagnostics['preparation_history_complete'] is False
        assert choice.diagnostics['reroll_limit'] == 2


def test_disabled_flag_matches_default_control():
    obs = observation()
    history = history_to(obs, visit=3)
    default = ShopSearch(samples=1, project_next_boss=True)
    explicit = ShopSearch(samples=1, project_next_boss=True, boss_readiness=False)
    assert default.choose(obs, LeaveShop(), history) == explicit.choose(obs, LeaveShop(), history)


def test_baseline_reroll_cannot_bypass_preparation_cash_floor():
    obs = observation()
    obs = replace(obs, money=12, round=replace(obs.round, reroll_cost=5))
    choice = planner().choose(obs, RerollShop(), history_to(obs))
    assert choice.action == LeaveShop()  # 12 - 5 < reserve2 + purchase buffer6.
    funded = replace(obs, money=13)
    assert isinstance(planner().choose(funded, RerollShop(), history_to(funded)).action, RerollShop)


def test_readiness_requires_projection_and_boolean():
    with pytest.raises(ValueError):
        ShopSearch(boss_readiness=True)
    with pytest.raises(ValueError):
        ShopSearch(project_next_boss=True, boss_readiness=1)


@pytest.mark.parametrize('cost,money', [(0, 11), (5, 20)])
def test_unmodeled_boss_does_not_add_cash_guard_to_baseline_reroll(monkeypatch, cost, money):
    obs = observation()
    obs = replace(obs, ante=3, money=money, round=replace(obs.round, reroll_cost=cost),
                  blinds=tuple(replace(b, name='The Arm') if b.kind == 'BOSS' else b for b in obs.blinds))
    monkeypatch.setattr(ShopSearch, '_capacity_components', staticmethod(lambda *args: (10000,) * 3))
    assert planner().choose(obs, RerollShop(), history_to(obs)).action == RerollShop()


def test_free_preparation_reroll_needs_no_cash_buffer_but_still_counts():
    obs = replace(observation(), money=1)
    p = planner()
    assert p.choose(obs, LeaveShop(), history_to(obs)).action == RerollShop()
    assert p.choose(obs, RerollShop(), history_to(obs, visit=4)).action == LeaveShop()
