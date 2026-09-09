"""Bounded action examples must cover mechanisms before target variants."""
from dataclasses import replace

from balatro_ai.analysis import _strategic_actions
from balatro_ai.game.actions import (
    DiscardCards,
    PlayCards,
    canonical_action_from_data,
    is_legal,
    iter_legal_actions,
)
from balatro_ai.game.adapter import to_public_observation
from balatro_ai.game.state import PublicItem, VisiblePlayingCard
from tests.game.state_factory import state


def test_targeted_tarot_does_not_hide_other_consumable_or_target_sizes():
    obs = replace(
        to_public_observation(state('SELECTING_HAND')),
        hand=tuple(VisiblePlayingCard(rank, 'H') for rank in ('2','3','4','5','6','7','8','9')),
        jokers=(),
        consumables=(PublicItem('c_star','The Star','TAROT'), PublicItem('c_hermit','The Hermit','TAROT')),
    )
    shown, omitted = _strategic_actions(obs)
    assert len(shown) == 24 and omitted > 0
    assert all(is_legal(obs, canonical_action_from_data(row)) for row in shown)
    assert len(shown) + omitted == sum(not isinstance(a, (PlayCards, DiscardCards)) for a in iter_legal_actions(obs))
    uses = [r for r in shown if r['type'] == 'use_consumable']
    assert {r['consumable'] for r in uses} == {0,1}
    assert {len(r['targets']) for r in uses if r['consumable'] == 0} == {1,2,3}
    assert {'reorder_hand','reorder_consumables','sell_consumable'} <= {r['type'] for r in shown}
    assert len({str(r) for r in shown}) == len(shown)
    assert _strategic_actions(obs) == (shown, omitted)


def test_small_action_set_retains_every_choice():
    obs = replace(to_public_observation(state('SHOP')), jokers=(), consumables=(), shop=(), vouchers=(), packs=())
    shown, omitted = _strategic_actions(obs)
    assert omitted == 0
    assert {r['type'] for r in shown} == {'leave_shop'}  # $4 cannot pay the $5 reroll.
