from dataclasses import replace

from balatro_ai_v2.solver.actions import DiscardCards, HandSlot, PlayCards, SelectBlind, UseConsumable, ConsumableSlot
from balatro_ai_v2.solver.adapter import to_public_observation
from balatro_ai_v2.solver.hidden_joker_search import choose_hidden_play, _remembered_inventory
from balatro_ai_v2.solver.policy import PublicHistoryStep
from balatro_ai_v2.solver.public_state import HiddenJokerSlot, PublicItem, PublicJokerRuntime, VisiblePlayingCard
from solver_state_factory import state


def joker(key, mult=None, xmult=None):
    runtime = PublicJokerRuntime(current_mult=mult, current_x_mult=xmult) if mult is not None or xmult is not None else None
    return PublicItem(key, key, 'JOKER', runtime=runtime)


def fixture(inventory=None, target=1000):
    inventory = inventory or (joker('j_green_joker', mult=5), joker('j_duo'))
    before = to_public_observation(state('BLIND_SELECT'))
    before = replace(before, jokers=inventory)
    current = to_public_observation(state('SELECTING_HAND'))
    boss = replace(current.blinds[-1], name='Amber Acorn', status='CURRENT', score=target)
    current = replace(current, jokers=tuple(HiddenJokerSlot() for _ in inventory), blinds=(boss,),
                      hand=(VisiblePlayingCard('A', 'S'), VisiblePlayingCard('K', 'H')))
    return current, (PublicHistoryStep(before, SelectBlind(), current),)


PLAY = PlayCards((HandSlot(0),))
DISCARD = DiscardCards((HandSlot(0),))


def test_uses_known_inventory_without_mapping_hidden_positions():
    current, history = fixture()
    result = choose_hidden_play(current, PLAY, history)
    assert result is not None
    assert result.diagnostics['permutations'] == 2
    assert result.diagnostics['mean_score'] >= result.diagnostics['minimum_score']
    assert all(isinstance(j, HiddenJokerSlot) for j in current.jokers)


def test_old_visible_order_does_not_change_belief_or_action():
    current, history = fixture()
    reordered = replace(history[0].before, jokers=tuple(reversed(history[0].before.jokers)))
    twin_history = (replace(history[0], before=reordered),)
    assert choose_hidden_play(current, PLAY, history) == choose_hidden_play(current, PLAY, twin_history)


def test_identical_jokers_do_not_duplicate_permutations():
    current, history = fixture((joker('j_green_joker', mult=5),) * 2)
    assert choose_hidden_play(current, PLAY, history).diagnostics['permutations'] == 1


def test_missing_discontinuous_or_wrong_count_history_declines():
    current, history = fixture()
    assert choose_hidden_play(current, PLAY, ()) is None
    assert choose_hidden_play(replace(current, money=current.money+1), PLAY, history) is None
    bad = replace(history[0], before=replace(history[0].before, jokers=history[0].before.jokers[:1]))
    assert choose_hidden_play(current, PLAY, (bad,)) is None


def test_green_growth_applies_floor_after_each_observed_action():
    initial, history = fixture((joker('j_green_joker', mult=0),))
    after_discard = replace(initial, round=replace(initial.round, discards_left=2, discards_used=1))
    after_play = replace(after_discard, round=replace(after_discard.round, hands_left=3, hands_played=1))
    history += (PublicHistoryStep(initial, DISCARD, after_discard), PublicHistoryStep(after_discard, PLAY, after_play))
    assert _remembered_inventory(after_play, history)[0].runtime.current_mult == 1
    assert history[0].before.jokers[0].runtime.current_mult == 0


def test_unknown_runtime_unsupported_inventory_and_actions_decline():
    for inventory in ((joker('j_green_joker'),), (joker('j_throwback'),), (joker('j_bloodstone'),)):
        current, history = fixture(inventory)
        assert choose_hidden_play(current, PLAY, history) is None
    current, history = fixture()
    after = replace(current, money=current.money+1)
    history += (PublicHistoryStep(current, UseConsumable(ConsumableSlot(0)), after),)
    assert choose_hidden_play(after, PLAY, history) is None


def test_lucky_cards_and_large_inventory_decline():
    current, history = fixture()
    lucky = replace(current, hand=(VisiblePlayingCard('A', 'S', enhancement='LUCKY'),))
    assert choose_hidden_play(lucky, PLAY, (replace(history[0], after=lucky),)) is None
    current, history = fixture((joker('j_duo'),) * 6)
    assert choose_hidden_play(current, PLAY, history) is None


def test_perishable_inventory_and_illegal_anchor_decline():
    current, history = fixture((replace(joker('j_duo'), perishable_rounds=1),))
    assert choose_hidden_play(current, PLAY, history) is None
    current, history = fixture()
    before = replace(history[0].before, blinds=tuple(replace(b, status='DEFEATED') for b in history[0].before.blinds))
    assert choose_hidden_play(current, PLAY, (replace(history[0], before=before),)) is None


def test_aggregate_same_actions_not_per_world_oracle(monkeypatch):
    def fake_score(world, selected, stats, context):
        if selected == (HandSlot(0),):
            return (100 if world.jokers[0].key == 'j_green_joker' else 0), 'High Card'
        return (60 if selected == (HandSlot(1),) else 1), 'High Card'
    monkeypatch.setattr('balatro_ai_v2.solver.hidden_joker_search._score_play_prepared', fake_score)
    current, history = fixture(target=100)
    choice = choose_hidden_play(current, PLAY, history)
    assert choice.action.cards == (HandSlot(1),)
    assert choice.diagnostics['mean_score'] == choice.diagnostics['minimum_score'] == 60
    assert choose_hidden_play(current, DISCARD, history) is None
    current, history = fixture(target=60)
    assert choose_hidden_play(current, DISCARD, history).action.cards == (HandSlot(1),)


def test_last_hand_prioritizes_possible_clear_over_guaranteed_near_miss(monkeypatch):
    def fake_score(world, selected, stats, context):
        if selected == (HandSlot(0),):
            return 99, 'High Card'
        if selected == (HandSlot(1),):
            return (100 if world.jokers[0].key == 'j_green_joker' else 0), 'High Card'
        return 1, 'High Card'
    monkeypatch.setattr('balatro_ai_v2.solver.hidden_joker_search._score_play_prepared', fake_score)
    current, history = fixture(target=100)
    assert choose_hidden_play(current, PLAY, history).action == PLAY
    last = replace(current, round=replace(current.round, hands_left=1))
    choice = choose_hidden_play(last, PLAY, (replace(history[0], after=last),))
    assert choice.action.cards == (HandSlot(1),)
    assert choice.diagnostics['modeled_clear_fraction'] == 0.5
    assert choice.diagnostics['capped_mean_score'] == 50
