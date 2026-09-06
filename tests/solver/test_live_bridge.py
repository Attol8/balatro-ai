from copy import deepcopy
from types import SimpleNamespace

from balatro_ai_v2.live.observation import public_observation
from balatro_ai_v2.live.runner import RunConfig, make_policy, replay, run_episode
from balatro_ai_v2.live.strategic import StrategicPolicy, project_strategic_observation
from solver_state_factory import state


def test_public_bridge_preserves_empty_typed_arrays_on_replay():
    projected = project_strategic_observation(state("BLIND_SELECT"))
    assert projected["public_solver"]["hand"] == []
    assert public_observation(projected)["public_solver"]["hand"] == []


def test_private_order_and_seed_do_not_change_typed_policy_action():
    raw = state("SELECTING_HAND")
    twin = deepcopy(raw)
    twin["seed"] = "OTHER"
    twin["cards"]["cards"].reverse()
    for card in twin["cards"]["cards"]:
        card["id"] += 123456
    left = project_strategic_observation(raw)
    right = project_strategic_observation(twin)
    assert left["public_solver"] == right["public_solver"]
    assert StrategicPolicy().choose(left).action == StrategicPolicy().choose(right).action


def test_live_trace_replays_strategic_history(tmp_path):
    initial = state("SELECTING_HAND", seed="TEST")
    final = state("GAME_OVER", seed="TEST")

    class Client:
        def rpc(self, method, params=None):
            return deepcopy(initial if method == "start" else final)

    path = tmp_path / "strategic.jsonl"
    result = run_episode(Client(), StrategicPolicy(), "TEST", path, RunConfig(stable_reads=1, policy="strategic"))
    assert result["status"] == "lost"
    replayed = replay(path)
    assert replayed["matching"] == replayed["decisions"] == 1
    assert replayed["complete_trace"]


def test_strategic_final_boss_loss_does_not_violate_typed_win_invariant(tmp_path):
    initial = state("SELECTING_HAND", seed="TEST")
    initial["ante_num"] = 8
    final = state("GAME_OVER", seed="TEST")
    final.update(ante_num=8, won=True)

    class Client:
        def rpc(self, method, params=None):
            return deepcopy(initial if method == "start" else final)

    result = run_episode(Client(), StrategicPolicy(), "TEST", tmp_path / "run.jsonl", RunConfig(stable_reads=1, policy="strategic"))
    assert result["status"] == "lost" and result["won"] is False


def test_planet_variant_is_explicit_and_control_remains_disabled():
    assert make_policy('search').shop_search.evaluate_planets is False
    assert make_policy('search-planets').shop_search.evaluate_planets is True
    assert RunConfig(policy='search-planets').policy == 'search-planets'


def test_green_variant_is_isolated_from_planet_and_control():
    assert make_policy('search').model_green_joker is False
    assert make_policy('search-planets').model_green_joker is False
    assert make_policy('search-green').model_green_joker is True
    assert make_policy('search-green').shop_search.evaluate_planets is False
    assert RunConfig(policy='search-green').policy == 'search-green'


def test_boss_variant_is_isolated_from_other_changes():
    assert make_policy('search').shop_search.project_next_boss is False
    candidate = make_policy('search-boss')
    assert candidate.shop_search.project_next_boss is True
    assert candidate.shop_search.evaluate_planets is False
    assert candidate.model_green_joker is False
    assert RunConfig(policy='search-boss').policy == 'search-boss'


def test_order_variant_has_a_bounded_reassessment_budget():
    from balatro_ai_v2.solver.actions import HandSlot, PlayCards, ReorderHand
    policy = make_policy('search-order')
    assert policy.optimize_order and not make_policy('search').optimize_order
    swap = SimpleNamespace(action=ReorderHand((HandSlot(1), HandSlot(0))))
    policy.history = [swap] * 7
    assert policy._reorder_budget_available()
    policy.history.append(swap)
    assert not policy._reorder_budget_available()
    policy.history.append(SimpleNamespace(action=PlayCards((HandSlot(0),))))
    assert policy._reorder_budget_available()


def test_order_budget_also_blocks_inherited_reorders(monkeypatch):
    from balatro_ai_v2.solver.actions import HandSlot, PlayCards, ReorderHand
    from balatro_ai_v2.solver.adapter import to_public_observation
    from balatro_ai_v2.solver.tactical_search import TacticalChoice
    import balatro_ai_v2.solver.tactical_search as tactical
    policy = make_policy('search-order')
    swap = ReorderHand((HandSlot(1), HandSlot(0)))
    policy.history = [SimpleNamespace(action=swap)] * 8
    monkeypatch.setattr(StrategicPolicy, 'select', lambda *args: (swap, 'inherited', {}))
    monkeypatch.setattr('balatro_ai_v2.live.strategic._with_history_derived_joker_runtime', lambda o, h: o)
    monkeypatch.setattr(tactical, 'choose_tactical', lambda o, a, **kw: TacticalChoice(a, 0, 0, 0, 'bounded'))
    action, _, _ = policy.select(to_public_observation(state('SELECTING_HAND')))
    assert isinstance(action, PlayCards)


def test_planet_variant_projects_typed_state_and_replays(tmp_path):
    initial = state('SELECTING_HAND', seed='TEST')
    final = state('GAME_OVER', seed='TEST')

    class Client:
        def rpc(self, method, params=None):
            return deepcopy(initial if method == 'start' else final)

    path = tmp_path / 'planets.jsonl'
    result = run_episode(Client(), make_policy('search-planets'), 'TEST', path,
                         RunConfig(stable_reads=1, policy='search-planets'))
    assert result['status'] == 'lost'
    replayed = replay(path)
    assert replayed['matching'] == replayed['decisions'] == 1
    assert replayed['complete_trace']
