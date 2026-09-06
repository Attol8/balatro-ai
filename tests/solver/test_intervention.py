from dataclasses import replace
import pytest
from balatro_ai_v2.live.intervention import InterventionPolicy
from balatro_ai_v2.live.strategic import SearchPolicy
from balatro_ai_v2.solver.actions import LeaveShop, SelectBlind
from balatro_ai_v2.solver.adapter import to_public_observation
from solver_state_factory import state


def test_intervention_is_exact_public_state_and_one_shot(monkeypatch):
    obs = to_public_observation(state('SHOP', money=20))
    monkeypatch.setattr(SearchPolicy, 'select', lambda self, o: ('fallback', '', {}))
    policy = InterventionPolicy(obs, LeaveShop())
    assert policy.select(replace(obs, money=21))[0] == 'fallback'
    assert not policy.applied
    assert policy.select(obs)[0] == LeaveShop()
    assert policy.applied
    assert policy.select(obs)[0] == 'fallback'


def test_intervention_rejects_illegal_target_action():
    obs = to_public_observation(state('SHOP'))
    with pytest.raises(ValueError):
        InterventionPolicy(obs, SelectBlind())
