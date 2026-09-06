"""Bounded public packets and strict, unverified teacher proposals.

No model client or live transport. An orchestrating session supplies the teacher.
"""
from dataclasses import asdict
import json

from .actions import ReorderHand, ReorderJokers, action_to_data, iter_legal_actions
from .public_state import Phase, PublicObservation


def _compact(value):
    if isinstance(value, dict):
        return {k: _compact(v) for k, v in value.items()
                if v is not None and v != '' and v is not False}
    if isinstance(value, (tuple, list)):
        return [_compact(v) for v in value]
    return value


def make_packet(observation: PublicObservation, *, max_bytes=12000):
    if not isinstance(observation, PublicObservation) or observation.phase != Phase.SHOP:
        raise ValueError('teacher packets require typed public SHOP observations')
    actions = sorted((action_to_data(a) for a in iter_legal_actions(observation)
                      if not isinstance(a, (ReorderHand, ReorderJokers))),
                     key=lambda a: json.dumps(a, sort_keys=True))
    raw = asdict(observation)
    state = {k: raw[k] for k in (
        'deck', 'stake', 'ante', 'round_no', 'money', 'hand_limit', 'joker_limit',
        'consumable_limit', 'blinds', 'hand_stats', 'jokers', 'consumables', 'shop',
        'vouchers', 'packs', 'used_vouchers', 'last_tarot_planet')}
    state['reroll_cost'] = observation.round.reroll_cost
    state['deck_cards'] = [
        [e.count, e.card.rank, e.card.suit,
         _compact({k: v for k, v in asdict(e.card).items() if k not in {'rank', 'suit', 'effect_text', 'debuffed'}
                   and not (k == 'permanent_bonus' and v == 0)})]
        for e in observation.full_deck
    ]
    packet = {'schema_version': 1, 'case_id': observation.digest(),
              'public_state': _compact(state),
              'choices': [{'id': f'a{i}', 'action': action} for i, action in enumerate(actions)]}
    if len(json.dumps(packet, separators=(',', ':')).encode()) > max_bytes:
        raise ValueError('teacher packet exceeds byte budget; do not silently truncate rules')
    return packet


def validate_proposal(packet, proposal):
    fields = {'case_id', 'choice_id', 'alternative_id', 'build_goal', 'reason'}
    if not isinstance(proposal, dict) or set(proposal) != fields:
        raise ValueError('teacher proposal fields do not match contract')
    if proposal['case_id'] != packet['case_id']:
        raise ValueError('teacher case ID mismatch')
    choices = {c['id']: c['action'] for c in packet['choices']}
    for field in ('choice_id', 'alternative_id'):
        if not isinstance(proposal[field], str) or proposal[field] not in choices:
            raise ValueError('teacher selected an unavailable action ID')
    if proposal['choice_id'] == proposal['alternative_id']:
        raise ValueError('teacher alternative must differ from its choice')
    for field in ('build_goal', 'reason'):
        if not isinstance(proposal[field], str) or not 1 <= len(proposal[field]) <= 240:
            raise ValueError('teacher explanations must contain 1..240 characters')
    return {**proposal, 'action': choices[proposal['choice_id']],
            'alternative': choices[proposal['alternative_id']],
            'label_status': 'unverified_teacher_proposal'}
