import json
from dataclasses import replace
import pytest
from balatro_ai_v2.solver.adapter import to_public_observation
from balatro_ai_v2.solver.public_state import Phase
from balatro_ai_v2.solver.teacher_packet import make_packet, validate_proposal
from solver_state_factory import state


def packet():
    return make_packet(to_public_observation(state('SHOP', money=20)))


def proposal(p):
    return dict(case_id=p['case_id'], choice_id=p['choices'][0]['id'],
                alternative_id=p['choices'][1]['id'], build_goal='Build repeatable Mult.', reason='Test this purchase.')


def test_public_packet_is_bounded_and_excludes_run_metadata():
    p = packet()
    assert len(json.dumps(p).encode()) < 12000
    assert not {'seed', 'history', 'outcome', 'baseline', 'won'} & p['public_state'].keys()
    assert all(c['action']['type'] not in {'reorder_hand', 'reorder_jokers'} for c in p['choices'])
    assert p == packet()


def test_rejects_raw_and_nonshop_input_and_oversized_packet():
    o = to_public_observation(state('SHOP'))
    for bad in ({'seed': 'private'}, replace(o, phase=Phase.BLIND_SELECT)):
        with pytest.raises(ValueError): make_packet(bad)
    with pytest.raises(ValueError): make_packet(o, max_bytes=1)


def test_legal_teacher_proposal_is_not_a_verified_label():
    p = packet()
    assert validate_proposal(p, proposal(p))['label_status'] == 'unverified_teacher_proposal'


@pytest.mark.parametrize('change', [dict(case_id='wrong'), dict(choice_id='invented'),
                                   dict(reason='x' * 241), dict(reason=''), dict(extra='field')])
def test_rejects_stale_invented_or_unbounded_proposals(change):
    p = packet()
    with pytest.raises(ValueError): validate_proposal(p, {**proposal(p), **change})
