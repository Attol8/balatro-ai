import json
from pathlib import Path

import pytest

from balatro_ai_v2.balatrobot.imitation_policy import fast_legal_full_actions
from balatro_ai_v2.balatrobot.tactical_planner import _active_required_score
from balatro_ai_v2.fast.run import RunPhase
from balatro_ai_v2.planner.core import PlannerConfig, PlannerCore
from balatro_ai_v2.planner.mirror import determinize, mirror_live_state

TRACE = Path(__file__).resolve().parents[2] / "runs" / "red_deck_seed1_visible_fast_type_joker_values.jsonl"


def _trace_states(state_name: str, limit: int = 5) -> list[dict]:
    if not TRACE.exists():
        pytest.skip(f"reference trace not available: {TRACE}")
    states = []
    with TRACE.open() as handle:
        for line in handle:
            record = json.loads(line)
            state = record.get("before") or record.get("state") or {}
            if state.get("state") == state_name:
                states.append(state)
                if len(states) >= limit:
                    break
    if not states:
        pytest.skip(f"no {state_name} states in reference trace")
    return states


def test_mirror_selecting_hand_states() -> None:
    for state in _trace_states("SELECTING_HAND"):
        env = mirror_live_state(state)
        assert env.run.phase == RunPhase.SELECTING_HAND
        assert len(env.run.hand) == len((state.get("hand") or {}).get("cards") or [])
        assert env.run.money == int(state.get("money") or 0)
        assert env.run.required_score == _active_required_score(state)
        round_state = state.get("round") or {}
        assert env.hands_remaining == int(round_state.get("hands_left") or 0)
        assert env.discards_remaining == int(round_state.get("discards_left") or 0)
        # Env legal actions must be a subset of live legal actions.
        live_legal = set(fast_legal_full_actions(state))
        assert set(env.legal_action_ids()) <= live_legal


def test_mirror_shop_states_use_live_offers_and_costs() -> None:
    for state in _trace_states("SHOP"):
        env = mirror_live_state(state)
        assert env.run.phase == RunPhase.SHOP
        live_shop_keys = [
            str(card.get("key") or "") for card in ((state.get("shop") or {}).get("cards") or [])
        ]
        assert env.run.shop.item_keys == live_shop_keys[:4]
        from balatro_ai_v2.fast.jokers import IMPLEMENTED_JOKERS, PROBABILISTIC_SCORE_JOKERS

        for card in ((state.get("shop") or {}).get("cards") or [])[:4]:
            key = str(card.get("key") or "")
            unbuyable = key.startswith("j_") and (
                key not in IMPLEMENTED_JOKERS or key in PROBABILISTIC_SCORE_JOKERS
            )
            expected = 999 if unbuyable else int(((card.get("cost") or {}).get("buy") or 0))
            assert env._item_cost(key) == expected
        live_packs = [
            str(card.get("key") or "") for card in ((state.get("packs") or {}).get("cards") or [])
        ]
        assert list(env._pack_keys()) == live_packs[:2]


def test_mirror_jokers_include_unmodeled_as_inert() -> None:
    states = _trace_states("SHOP", limit=20)
    state = states[-1]
    env = mirror_live_state(state)
    live_joker_keys = [
        str(card.get("key") or "") for card in ((state.get("jokers") or {}).get("cards") or [])
    ]
    assert [joker.key for joker in env.jokers] == live_joker_keys


def test_planner_decides_legal_action_on_mirrored_states() -> None:
    core = PlannerCore(
        config=PlannerConfig(shop_candidates=3, rollout_horizon_blinds=1, max_rollout_steps=8)
    )
    for state_name in ("SELECTING_HAND", "SHOP", "BLIND_SELECT"):
        for state in _trace_states(state_name, limit=2):
            env = mirror_live_state(state)
            action = core.decide(env)
            assert action in fast_legal_full_actions(state), (state_name, action)


def test_determinize_changes_future_rng_not_visible_state() -> None:
    state = _trace_states("SHOP")[0]
    env = mirror_live_state(state)
    sample = determinize(env, 1)
    assert sample.seed != env.seed
    assert sample.run.shop.item_keys == env.run.shop.item_keys
    assert sample.run.money == env.run.money
    base = determinize(env, 0)
    assert base.seed == env.seed
