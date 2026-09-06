from dataclasses import replace
from types import SimpleNamespace

import pytest

from balatro_ai_v2.solver.actions import (
    LeaveShop, ReorderHand, ReorderJokers, action_to_data, iter_legal_actions,
)
from balatro_ai_v2.solver.adapter import to_public_observation
from balatro_ai_v2.solver.blind_rollout import compare_ante
from balatro_ai_v2.solver.policy import PublicHistoryStep
from balatro_ai_v2.solver.public_state import Phase
from solver_state_factory import state


def observation():
    return to_public_observation(state("SHOP", money=20))


class Candidate:
    def __init__(self, obs, mode="clear"):
        self.current_public = obs
        self.mode = mode
        self.closed = False
        self.steps = 0

    def step(self, action):
        self.steps += 1
        if self.mode == "raise":
            raise ValueError("engine")
        if self.mode == "reject":
            return SimpleNamespace(status="rejected", after=None)
        if self.mode == "missing":
            self.current_public = None
        elif self.mode == "lost":
            self.current_public = replace(self.current_public, phase=Phase.GAME_OVER)
        elif self.mode == "clear" and self.steps == 2:
            self.current_public = replace(self.current_public, phase=Phase.ROUND_EVAL,
                                         antes_cleared=self.current_public.antes_cleared + 1)
        return SimpleNamespace(status="accepted", after=True)

    def close(self):
        self.closed = True
        if self.mode == "close":
            raise ValueError("closing")


class Continue:
    def __init__(self):
        self.calls = []

    def choose_action(self, obs, legal, history):
        self.calls.append((obs, tuple(legal()), history))
        return LeaveShop()


def test_all_legal_nonreorder_roots_fresh_particles_and_actual_history():
    obs = observation()
    prefix = (PublicHistoryStep(obs, LeaveShop(), obs),)
    inputs, candidates, policies = [], [], []
    def root(*args):
        inputs.append(args)
        candidate = Candidate(args[0])
        candidates.append(candidate)
        return candidate
    def continuation():
        policy = Continue()
        policies.append(policy)
        return policy
    result = compare_ante(obs, prefix, root_factory=root, continuation_factory=continuation, samples=2)
    expected = tuple(a for a in iter_legal_actions(obs)
                     if not isinstance(a, (ReorderHand, ReorderJokers)))
    assert result.actions == tuple(action_to_data(a) for a in expected)
    assert result.clear_rates == (1.0,) * len(expected)
    assert [x[3] for x in inputs] == [0, 1] * len(expected)
    assert all(x[:3] == (obs, prefix, "public-ante-v1") for x in inputs)
    assert len({id(p) for p in policies}) == len(inputs)
    for index, policy in enumerate(policies):
        history = policy.calls[0][2]
        assert history[:1] == prefix
        assert history[1].before == obs
        assert history[1].action == expected[index // 2]
        assert history[1].after == policy.calls[0][0]
    assert all(c.closed for c in candidates)


@pytest.mark.parametrize("mode,status", [("lost", "lost"), ("reject", "rejected"),
    ("raise", "rejected"), ("missing", "rejected"), ("close", "rejected"), ("wait", "censored")])
def test_explicit_outcomes_and_incomplete_rates(mode, status):
    candidates = []
    def root(obs, *_):
        c = Candidate(obs, mode)
        candidates.append(c)
        return c
    result = compare_ante(observation(), (), root_factory=root,
                          continuation_factory=Continue, samples=1, max_steps=2)
    assert all(o.status == status for row in result.outcomes for o in row)
    assert (result.clear_rates is not None) == (status == "lost")
    assert all(c.closed for c in candidates)


def test_next_blind_clear_is_not_ante_clear_and_no_progress_is_not_loss():
    class RoundClear(Candidate):
        def step(self, action):
            self.current_public = replace(self.current_public, phase=Phase.ROUND_EVAL)
            return SimpleNamespace(status="accepted", after=True)
    class NoProgress:
        def choose_action(self, *args):
            raise RuntimeError("NoPublicProgressAction")
    result = compare_ante(observation(), (), root_factory=lambda o, *_: RoundClear(o),
                          continuation_factory=NoProgress, samples=1)
    assert result.clear_rates is None
    assert all(o.status == "rejected" and "NoPublicProgressAction" in o.reason
               for row in result.outcomes for o in row)


@pytest.mark.parametrize("kwargs", [{"samples": True}, {"samples": 65}, {"samples": 0},
    {"max_steps": False}, {"max_steps": 513}, {"max_steps": 0}, {"max_steps": 1.5}])
def test_strict_budget_bounds(kwargs):
    with pytest.raises(ValueError):
        compare_ante(observation(), (), root_factory=None, continuation_factory=None, **kwargs)


def test_nonshop_never_constructs():
    obs = replace(observation(), phase=Phase.BLIND_SELECT)
    result = compare_ante(obs, (), root_factory=None, continuation_factory=None)
    assert result.unavailable_reason == "outside ante shop slice"


def test_illegal_policy_action_rejected_and_target_tracks_current_blind():
    class Active(Candidate):
        def step(self, action):
            self.current_public = replace(self.current_public, blinds=tuple(
                replace(b, status="CURRENT" if b.kind == "BOSS" else "DEFEATED", score=1234)
                for b in self.current_public.blinds))
            return SimpleNamespace(status="accepted", after=True)
    class Illegal:
        def choose_action(self, *args):
            return ReorderHand(())
    result = compare_ante(observation(), (), root_factory=lambda o, *_: Active(o),
                          continuation_factory=Illegal, samples=1)
    assert all(o.status == "rejected" and o.target == 1234
               for row in result.outcomes for o in row)


def test_two_ante_rollout_continues_after_first_ante():
    class TwoAnteCandidate(Candidate):
        def step(self, action):
            self.steps += 1
            if self.steps % 2 == 0:
                self.current_public = replace(
                    self.current_public,
                    antes_cleared=self.current_public.antes_cleared + 1,
                )
            return SimpleNamespace(status="accepted", after=True)

    result = compare_ante(observation(), (), root_factory=lambda o, *_: TwoAnteCandidate(o),
                          continuation_factory=Continue, samples=1, antes=2)
    assert all(o.status == "cleared" and o.steps == 4
               for row in result.outcomes for o in row)


def test_two_ante_rollout_caps_at_ante_eight():
    obs = replace(observation(), antes_cleared=7)

    class OneAnteCandidate(Candidate):
        def step(self, action):
            self.steps += 1
            self.current_public = replace(
                self.current_public,
                antes_cleared=self.current_public.antes_cleared + 1,
            )
            return SimpleNamespace(status="accepted", after=True)

    result = compare_ante(obs, (), root_factory=lambda o, *_: OneAnteCandidate(o),
                          continuation_factory=Continue, samples=1, antes=2)
    assert all(o.status == "cleared" and o.steps == 1
               for row in result.outcomes for o in row)


@pytest.mark.parametrize("antes", [True, False, 0, 3, 1.5])
def test_antes_bounds_are_strict(antes):
    with pytest.raises(ValueError):
        compare_ante(observation(), (), root_factory=None, continuation_factory=None,
                     antes=antes)
