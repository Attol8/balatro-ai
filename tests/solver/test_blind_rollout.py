from dataclasses import replace
from types import SimpleNamespace

import pytest

from balatro_ai_v2.solver.actions import (
    BuyMode, BuyShopCard, HandSlot, LeaveShop, PlayCards, SelectBlind,
)
from balatro_ai_v2.solver.adapter import to_public_observation
from balatro_ai_v2.solver.blind_rollout import compare_next_blind, shop_roots
from balatro_ai_v2.solver.public_state import Phase, PublicItem
from balatro_ai_v2.solver.public_codec import public_observation_to_data
from balatro_ai_v2.solver.shadow_blind import load_decision
from solver_state_factory import state


def observation():
    obs = to_public_observation(state("SHOP", money=20))
    return replace(obs, shop=(
        PublicItem("j_joker", "Joker", "JOKER", buy_cost=4, sell_cost=2),
        PublicItem("c_pluto", "Pluto", "PLANET", buy_cost=3, sell_cost=1),
        PublicItem("c_hanged_man", "Hanged Man", "TAROT", buy_cost=3, sell_cost=1),
    ))


class PlayFirst:
    def choose_action(self, obs, legal, history):
        return PlayCards((HandSlot(0),))


class FakeCandidate:
    def __init__(self, obs, *, fail=False, never_finish=False):
        self.current_public = obs
        self.closed = False
        self.fail = fail
        self.never_finish = never_finish
        self.actions = []

    def step(self, action):
        self.actions.append(action)
        if self.fail:
            return SimpleNamespace(status="rejected", after=None)
        obs = self.current_public
        if isinstance(action, BuyShopCard):
            after = replace(obs, shop=())
        elif isinstance(action, LeaveShop):
            after = replace(obs, phase=Phase.BLIND_SELECT, blinds=tuple(
                replace(b, status="SELECT" if b.kind == "BIG" else "DEFEATED")
                for b in obs.blinds))
        elif isinstance(action, SelectBlind):
            after = to_public_observation(state("SELECTING_HAND"))
            after = replace(after, blinds=tuple(
                replace(b, status="CURRENT" if b.kind == "BIG" else "DEFEATED")
                for b in after.blinds))
        else:
            after = obs if self.never_finish else replace(obs, phase=Phase.ROUND_EVAL)
        self.current_public = after
        return SimpleNamespace(status="accepted", after=True)

    def close(self):
        self.closed = True


def test_roots_exclude_generated_offers_and_destructive_consumables():
    roots = shop_roots(observation())
    assert LeaveShop() in roots
    buys = [a for a in roots if isinstance(a, BuyShopCard)]
    assert {(a.card.value, a.mode) for a in buys} == {(0, BuyMode.STORE), (1, BuyMode.USE)}


def test_common_public_particles_fresh_continuations_and_stop_before_cashout():
    obs = observation()
    inputs, candidates, policies = [], [], []
    def factory(*args):
        inputs.append(args)
        candidate = FakeCandidate(args[0])
        candidates.append(candidate)
        return candidate
    def continuation():
        policy = PlayFirst()
        policies.append(policy)
        return policy
    result = compare_next_blind(obs, (), root_factory=factory,
                                continuation_factory=continuation, samples=2)
    assert result.complete
    assert result.clear_rates == (1.0,) * 3
    assert [args[3] for args in inputs] == [0, 1] * 3
    assert all(args[:3] == (obs, (), "public-next-blind-v1") for args in inputs)
    assert len({id(p) for p in policies}) == 6
    assert all(c.closed and isinstance(c.actions[-1], PlayCards) for c in candidates)


@pytest.mark.parametrize("mode,status", [("fail", "rejected"), ("never_finish", "censored")])
def test_incomplete_particles_are_not_losses_or_omitted_from_rates(mode, status):
    result = compare_next_blind(observation(), (),
        root_factory=lambda obs, *_: FakeCandidate(obs, **{mode: True}),
        continuation_factory=PlayFirst, samples=1, max_steps=5)
    assert not result.complete
    assert result.clear_rates is None
    assert all(o.status == status for row in result.outcomes for o in row)


def test_boss_shops_fail_closed_without_constructing_root():
    obs = observation()
    obs = replace(obs, blinds=tuple(replace(b, status="UPCOMING" if b.kind == "BOSS" else "DEFEATED")
                                   for b in obs.blinds))
    def forbidden(*args):
        raise AssertionError("root must not be requested")
    result = compare_next_blind(obs, (), root_factory=forbidden, continuation_factory=PlayFirst)
    assert result.unavailable_reason == "outside ordinary shop slice"
    assert result.outcomes == ()


def test_root_failure_is_explicit():
    def unavailable(*args):
        raise ValueError("incomplete public history")
    result = compare_next_blind(observation(), (), root_factory=unavailable,
                                continuation_factory=PlayFirst, samples=1)
    assert result.clear_rates is None
    assert "incomplete public history" in result.outcomes[0][0].reason


@pytest.mark.parametrize("kwargs", [{"samples": True}, {"samples": 65}, {"max_steps": 0}])
def test_bounded_budgets(kwargs):
    with pytest.raises(ValueError):
        compare_next_blind(observation(), (), root_factory=None, continuation_factory=None, **kwargs)


def test_prior_won_flag_does_not_turn_terminal_loss_into_clear():
    class Loser(FakeCandidate):
        def step(self, action):
            result = super().step(action)
            if isinstance(action, PlayCards):
                self.current_public = replace(self.current_public, phase=Phase.GAME_OVER,
                                              won=True, antes_cleared=8, ante=9)
            return result
    result = compare_next_blind(observation(), (), root_factory=lambda obs, *_: Loser(obs),
                                continuation_factory=PlayFirst, samples=1)
    assert result.complete
    assert result.clear_rates == (0.0,) * 3


def test_close_failure_is_not_reported_as_a_completed_sample():
    class BadClose(FakeCandidate):
        def close(self):
            raise RuntimeError("close failed")
    result = compare_next_blind(observation(), (), root_factory=lambda obs, *_: BadClose(obs),
                                continuation_factory=PlayFirst, samples=1)
    assert result.clear_rates is None
    assert result.outcomes[0][0].reason.startswith("close_exception:")


def test_trace_loader_ignores_private_metadata_and_checks_contiguity(tmp_path):
    import json
    obs = observation()
    public = public_observation_to_data(obs)
    event = {"event": "decision", "index": 0,
             "observation": {"public_solver": public, "seed": "NEVER_PASS", "private": [1, 2]},
             "action": {"public_action": {"type": "leave_shop"}}}
    path = tmp_path / "trace.jsonl"
    path.write_text(json.dumps(event) + "\n")
    assert load_decision(path, 0) == (obs, ())
    event["index"] = 1
    path.write_text(json.dumps(event) + "\n")
    with pytest.raises(ValueError, match="noncontiguous"):
        load_decision(path, 1)
