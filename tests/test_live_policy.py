import pytest

from balatro_ai_v2.actions import ActionKind
from balatro_ai_v2.live.policy import BaselinePolicy


def card(key, **extra):
    return {'key': key, **extra}


def hand_state(keys):
    return {'state': 'SELECTING_HAND', 'hand': {'cards': [card(k) for k in keys]},
            'round': {'hands_left': 4, 'discards_left': 0, 'chips': 0},
            'blinds': {'small': {'status': 'CURRENT', 'score': 300}}, 'hands': {}}


def test_levels_change_selected_hand():
    state = hand_state(['S_A', 'H_A', 'D_2', 'C_3', 'H_4'])
    normal = BaselinePolicy().choose(state)
    assert len(normal.action.indices) == 2
    state['hands']['High Card'] = {'level': 20}
    leveled = BaselinePolicy().choose(state)
    assert len(leveled.action.indices) == 1
    assert leveled.predicted_score > normal.predicted_score


def test_forced_card_and_psychic():
    state = hand_state(['S_A', 'H_A', 'D_2', 'C_3', 'H_4', 'S_5'])
    state['hand']['cards'][2]['state'] = {'forced_selection': True}
    assert 2 in BaselinePolicy().choose(state).action.indices
    state['blinds']['small']['name'] = 'The Psychic'
    assert len(BaselinePolicy().choose(state).action.indices) == 5


def test_eye_avoids_previously_played_pair():
    state = hand_state(['S_A', 'H_A', 'D_2'])
    state['blinds']['small']['name'] = 'The Eye'
    state['hands']['Pair'] = {'played_this_round': 1}
    assert len(BaselinePolicy().choose(state).action.indices) == 1


def test_hidden_card_remains_legal_without_identity():
    state = hand_state(['S_A', 'H_A'])
    state['hand']['cards'][0] = {'state': {'hidden': True, 'forced_selection': True}}
    decision = BaselinePolicy().choose(state)
    assert 0 in decision.action.indices
    assert decision.limitations


def test_discards_are_bounded_and_disabled_when_exhausted():
    state = hand_state(['S_A', 'H_A', 'D_2', 'C_3', 'H_4', 'S_6', 'D_8', 'C_T', 'D_J'])
    state['blinds']['small']['score'] = 10000
    state['round']['discards_left'] = 2
    decision = BaselinePolicy().choose(state)
    assert decision.action.kind == ActionKind.DISCARD
    assert 1 <= len(decision.action.indices) <= 5
    state['round']['discards_left'] = 0
    assert BaselinePolicy().choose(state).action.kind == ActionKind.PLAY


@pytest.mark.parametrize(('phase', 'kind'), [('BLIND_SELECT', ActionKind.SELECT_BLIND), ('ROUND_EVAL', ActionKind.CASH_OUT), ('SHOP', ActionKind.NEXT_ROUND)])
def test_phase_progression(phase, kind):
    assert BaselinePolicy().choose({'state': phase}).action.kind == kind


def test_shop_affordability_and_eternal_protection():
    state = {'state': 'SHOP', 'money': 4, 'shop': {'cards': [card('j_cavendish', cost={'buy': 5})]}}
    assert BaselinePolicy().choose(state).action.kind == ActionKind.NEXT_ROUND
    state['money'] = 20
    state['jokers'] = {'limit': 1, 'cards': [card('j_joker', modifier={'eternal': True}, cost={'sell': 2})]}
    assert BaselinePolicy().choose(state).action.kind == ActionKind.NEXT_ROUND
    state['jokers']['cards'][0]['modifier']['eternal'] = False
    assert BaselinePolicy().choose(state).action.kind == ActionKind.SELL_JOKER
    state['jokers']['cards'] = []
    assert BaselinePolicy().choose(state).action.kind == ActionKind.BUY_CARD


def test_planet_is_used_and_unsupported_pack_is_skipped():
    state = {'state': 'SHOP', 'consumables': {'cards': [card('c_pluto')]}}
    assert BaselinePolicy().choose(state).action.kind == ActionKind.USE_CONSUMABLE
    state = {'state': 'SMODS_BOOSTER_OPENED', 'pack': {'cards': [card('c_ankh')]}}
    assert BaselinePolicy().choose(state).action.kind == ActionKind.PACK_SKIP
    state['pack']['cards'].append(card('c_pluto'))
    decision = BaselinePolicy().choose(state)
    assert decision.action.kind == ActionKind.PACK_SELECT
    assert decision.action.index == 1


def test_pack_targets_use_visible_card_indices():
    state = hand_state(['S_A', 'H_2'])
    state.update(state='TAROT_PACK', pack={'cards': [card('c_empress')]})
    decision = BaselinePolicy().choose(state)
    assert decision.action.to_balatrobot_rpc() == ('pack', {'card': 0, 'targets': [0, 1]})


def test_targeted_consumable_waits_for_hand_phase():
    state = hand_state(['S_A'])
    state['state'] = 'SHOP'
    state['consumables'] = {'cards': [card('c_empress')]}
    assert BaselinePolicy().choose(state).action.kind == ActionKind.NEXT_ROUND
    state['state'] = 'SELECTING_HAND'
    assert BaselinePolicy().choose(state).action.kind == ActionKind.USE_CONSUMABLE


def test_targeted_consumable_includes_low_rank_forced_card():
    state = hand_state(['S_A', 'H_2'])
    state['hand']['cards'][1]['state'] = {'forced_selection': True}
    state['consumables'] = {'cards': [card('c_chariot')]}
    decision = BaselinePolicy().choose(state)
    assert decision.action.kind == ActionKind.USE_CONSUMABLE
    assert decision.action.indices == (1,)


@pytest.mark.parametrize('forced_card', [
    {'state': {'hidden': True, 'forced_selection': True}},
    card('H_2', state={'forced_selection': True}, modifier={'enhancement': 'GLASS'}),
])
def test_targeted_consumable_declines_ineligible_forced_card(forced_card):
    state = hand_state(['S_A', 'H_2'])
    state['hand']['cards'][1] = forced_card
    state['consumables'] = {'cards': [card('c_chariot')]}
    decision = BaselinePolicy().choose(state)
    assert decision.action.kind == ActionKind.PLAY
    assert 1 in decision.action.indices


def test_replacement_does_not_sell_negative_joker_to_free_slot():
    state = {'state': 'SHOP', 'money': 30,
             'jokers': {'limit': 1, 'cards': [card('j_credit_card', modifier={'edition': 'NEGATIVE'}, cost={'sell': 2})]},
             'shop': {'cards': [card('j_blueprint', cost={'buy': 10})]}}
    assert BaselinePolicy().choose(state).action.kind == ActionKind.NEXT_ROUND


def test_red_seal_repeats_base_chips_and_joker_order_is_preserved():
    policy = BaselinePolicy()
    state = hand_state(['S_2'])
    base = policy.choose(state).predicted_score
    state['hand']['cards'][0]['modifier'] = {'seal': 'RED'}
    assert policy.choose(state).predicted_score == base + 2
    state['hand']['cards'][0]['modifier'] = {}
    state['jokers'] = {'cards': [card('j_cavendish'), card('j_joker')]}
    first = policy.choose(state).predicted_score
    state['jokers']['cards'].reverse()
    assert policy.choose(state).predicted_score > first


def test_terminal_state_does_not_emit_mutation():
    with pytest.raises(ValueError, match='non-playable'):
        BaselinePolicy().choose({'state': 'GAME_OVER'})
