from __future__ import annotations

from collections import deque
from copy import deepcopy
from pathlib import Path

import pytest

from balatro_ai_v2.actions import (
    BuyMode,
    BuyShopCard,
    ConsumableSlot,
    SelectBlind,
    ShopSlot,
    UseConsumable,
)
from balatro_ai_v2.backend import RunSpec
from balatro_ai_v2.balatrobot.backend import BalatroBotBackend, UnsettledStateError
from balatro_ai_v2.balatrobot.client import BalatroBotRpcError, BalatroBotTransportError
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.balatrobot.runner import (
    AuthorityRunner,
    NoBuySmokePolicy,
    _semantic_action_label,
)
from state_factory import item_card, state


class FakeClient:
    def __init__(
        self,
        initial,
        polls=(),
        action_result=None,
        action_error=None,
        action_results=(),
    ) -> None:
        self.initial = deepcopy(initial)
        self.polls = deque(deepcopy(tuple(polls)))
        self.action_result = deepcopy(action_result)
        self.action_results = deque(deepcopy(tuple(action_results)))
        self.action_error = action_error
        self.calls: list[tuple[str, object]] = []

    def menu(self):
        self.calls.append(("menu", None))
        return {"state": "MENU"}

    def start(self, *, deck, stake, seed):
        self.calls.append(("start", (deck, stake, seed)))
        return deepcopy(self.initial)

    def gamestate(self):
        self.calls.append(("gamestate", None))
        if not self.polls:
            return deepcopy(
                self.action_result if self.action_result is not None else self.initial
            )
        return self.polls.popleft()

    def call_action(self, method, params):
        self.calls.append((method, params))
        if self.action_error is not None:
            raise self.action_error
        if self.action_results:
            return self.action_results.popleft()
        return deepcopy(self.action_result)

    def save(self, *, path):
        self.calls.append(("save", path))
        return {"success": True, "path": path}

    def load(self, *, path):
        self.calls.append(("load", path))
        return {"success": True, "path": path}

    def checkpoint(self, *, op, snapshot_id=None):
        self.calls.append(("checkpoint", (op, snapshot_id)))
        if op == "create":
            return {"snapshot_id": "s1", "bytes": 123}
        return {"success": True, "snapshot_id": snapshot_id}


def test_backend_settles_after_two_identical_semantic_reads() -> None:
    initial = state()
    client = FakeClient(initial, polls=[initial])
    backend = BalatroBotBackend(client, settle_poll_delay=0)  # type: ignore[arg-type]

    observation = backend.reset(RunSpec("RED", "WHITE", "1"))

    assert observation.settled
    assert len(observation.polls) == 2
    assert backend.metadata.capabilities.authoritative
    assert not backend.metadata.capabilities.snapshot
    assert not backend.metadata.capabilities.complete_private_state


def test_backend_never_force_accepts_a_changing_state() -> None:
    initial = state(money=1)
    client = FakeClient(initial, polls=[state(money=2), state(money=3)])
    backend = BalatroBotBackend(client, max_settle_polls=2, settle_poll_delay=0)  # type: ignore[arg-type]

    with pytest.raises(UnsettledStateError):
        backend.reset(RunSpec("RED", "WHITE", "1"))


def test_file_snapshot_restore_replaces_current_branch_root() -> None:
    initial = state(money=4)
    restored = state(money=9)
    client = FakeClient(initial, polls=[initial, restored, restored])
    backend = BalatroBotBackend(client, settle_poll_delay=0)  # type: ignore[arg-type]
    backend.reset(RunSpec("RED", "WHITE", "1"))

    path = Path("/private/tmp/parent.jkr")
    backend.save_file_snapshot(path)
    observation = backend.load_file_snapshot(path)

    assert observation.observed.canonical["money"] == 9
    assert ("save", str(path)) in client.calls
    assert ("load", str(path)) in client.calls


def test_memory_checkpoint_restore_replaces_current_branch_root() -> None:
    initial = state(money=4)
    restored = state(money=9)
    client = FakeClient(initial, polls=[initial, restored, restored])
    backend = BalatroBotBackend(client, settle_poll_delay=0)  # type: ignore[arg-type]
    backend.reset(RunSpec("RED", "WHITE", "1"))

    snapshot_id, size = backend.create_memory_checkpoint()
    observation = backend.load_memory_checkpoint(snapshot_id)
    backend.delete_memory_checkpoint(snapshot_id)

    assert (snapshot_id, size) == ("s1", 123)
    assert observation.observed.canonical["money"] == 9
    assert ("checkpoint", ("restore", "s1")) in client.calls


def test_backend_never_settles_a_shop_missing_public_areas() -> None:
    incomplete = state("SHOP")
    incomplete.pop("packs")
    client = FakeClient(incomplete, polls=[incomplete])
    backend = BalatroBotBackend(client, max_settle_polls=1, settle_poll_delay=0)  # type: ignore[arg-type]

    with pytest.raises(UnsettledStateError):
        backend.reset(RunSpec("RED", "WHITE", "1"))


def test_backend_never_settles_a_fresh_empty_shop() -> None:
    empty = state("SHOP")
    for name in ("shop", "packs", "vouchers"):
        empty[name]["cards"] = []
        empty[name]["count"] = 0
    client = FakeClient(empty, polls=[empty])
    backend = BalatroBotBackend(client, max_settle_polls=1, settle_poll_delay=0)  # type: ignore[arg-type]

    with pytest.raises(UnsettledStateError):
        backend.reset(RunSpec("RED", "WHITE", "1"))


def test_backend_settles_shop_after_last_known_offer_is_bought() -> None:
    initial = state("SHOP", money=10)
    for name in ("packs", "vouchers"):
        initial[name]["cards"] = []
        initial[name]["count"] = 0
    empty = deepcopy(initial)
    empty["shop"]["cards"] = []
    empty["shop"]["count"] = 0
    client = FakeClient(initial, polls=[initial], action_result=empty)
    backend = BalatroBotBackend(client, settle_poll_delay=0)  # type: ignore[arg-type]
    backend.reset(RunSpec("RED", "WHITE", "1"))

    result = backend.step(BuyShopCard(ShopSlot(0)))

    assert result.after is not None
    assert result.after.observed.canonical["state"] == "SHOP"
    assert result.after.observed.canonical["shop"]["count"] == 0
    assert len(result.after.polls) == 2


def test_backend_keeps_settling_an_established_empty_shop() -> None:
    initial = state("SHOP", money=10)
    for name in ("packs", "vouchers"):
        initial[name]["cards"] = []
        initial[name]["count"] = 0
    initial["consumables"]["cards"] = [
        item_card("c_mercury", card_id=30, kind="PLANET")
    ]
    initial["consumables"]["count"] = 1
    empty = deepcopy(initial)
    empty["shop"]["cards"] = []
    empty["shop"]["count"] = 0
    client = FakeClient(initial, polls=[initial], action_result=empty)
    backend = BalatroBotBackend(client, settle_poll_delay=0)  # type: ignore[arg-type]
    backend.reset(RunSpec("RED", "WHITE", "1"))
    backend.step(BuyShopCard(ShopSlot(0)))

    spent = deepcopy(empty)
    spent["consumables"]["cards"] = []
    spent["consumables"]["count"] = 0
    client.action_result = spent
    result = backend.step(UseConsumable(ConsumableSlot(0)))

    assert result.after is not None
    assert result.after.observed.canonical["state"] == "SHOP"
    assert result.after.observed.canonical["shop"]["count"] == 0


def test_backend_waits_for_visible_hand_in_targeted_pack() -> None:
    opening = state("SPECTRAL_PACK")
    ready = deepcopy(opening)
    dealt = state("SELECTING_HAND")
    ready["hand"] = dealt["hand"]
    ready["cards"] = dealt["cards"]
    client = FakeClient(opening, polls=[ready, ready])
    backend = BalatroBotBackend(client, settle_poll_delay=0)  # type: ignore[arg-type]

    observation = backend.reset(RunSpec("RED", "WHITE", "1"))

    assert len(observation.polls) == 3
    assert len(observation.observed.canonical["hand"]["cards"]) == 3


def test_rejected_action_stays_rejected_and_is_not_replaced_by_polling() -> None:
    initial = state()
    client = FakeClient(
        initial,
        polls=[initial],
        action_error=BalatroBotRpcError("bad state"),
    )
    backend = BalatroBotBackend(client, settle_poll_delay=0)  # type: ignore[arg-type]
    backend.reset(RunSpec("RED", "WHITE", "1"))

    result = backend.step(SelectBlind())

    assert result.status == "rejected"
    assert result.after is None
    assert client.calls[-1] == ("select", {})


def test_transport_error_is_distinct_from_game_rejection() -> None:
    initial = state()
    client = FakeClient(
        initial,
        polls=[initial],
        action_error=BalatroBotTransportError("connection lost"),
    )
    backend = BalatroBotBackend(client, settle_poll_delay=0)  # type: ignore[arg-type]
    backend.reset(RunSpec("RED", "WHITE", "1"))

    assert backend.step(SelectBlind()).status == "transport_error"


def test_runner_passes_only_public_observation_and_completes_real_terminal() -> None:
    initial = state()
    terminal = state("GAME_OVER", won=True)
    client = FakeClient(initial, polls=[initial, terminal], action_result=terminal)
    backend = BalatroBotBackend(client, settle_poll_delay=0)  # type: ignore[arg-type]

    result = AuthorityRunner(backend, NoBuySmokePolicy(), max_decisions=2).run(
        RunSpec("RED", "WHITE", "PRIVATE-SEED")
    )

    assert result.complete
    assert result.won
    assert result.decisions == 1
    assert result.action_counts == (("select_blind", 1),)
    assert result.cards_played == 0
    assert result.cards_discarded == 0
    assert result.terminal_blind is not None
    assert result.terminal_blind.name == "Small Blind"
    assert "PRIVATE-SEED" not in result.final_observation.canonical_json()  # type: ignore[union-attr]


def test_runner_summarizes_accepted_card_actions() -> None:
    initial = state("SELECTING_HAND")
    terminal = state("GAME_OVER")
    terminal["round"]["chips"] = 777
    client = FakeClient(initial, polls=[initial, terminal], action_result=terminal)
    backend = BalatroBotBackend(client, settle_poll_delay=0)  # type: ignore[arg-type]

    result = AuthorityRunner(backend, NoBuySmokePolicy(), max_decisions=1).run(
        RunSpec("RED", "WHITE", "1")
    )

    assert result.action_counts == (("play_cards", 1),)
    assert result.best_hand_score == 777
    assert result.cards_played == 3
    assert result.cards_discarded == 0


def test_runner_semantic_action_label_uses_public_item_key() -> None:
    observation = to_public_observation(state("SHOP", money=10))

    assert (
        _semantic_action_label(observation, BuyShopCard(ShopSlot(0)))
        == "buy_shop_card:j_joker"
    )

    raw = state("SHOP", money=10)
    raw["shop"] = {
        "cards": [item_card("c_mercury", card_id=90, kind="PLANET", buy=3)],
        "count": 1,
        "highlighted_limit": 1,
        "limit": 2,
    }
    planet_shop = to_public_observation(raw)
    assert (
        _semantic_action_label(
            planet_shop, BuyShopCard(ShopSlot(0), BuyMode.USE)
        )
        == "buy_and_use_consumable:c_mercury"
    )


def test_runner_recognizes_terminal_on_final_allowed_decision() -> None:
    initial = state()
    terminal = state("GAME_OVER", won=True)
    client = FakeClient(initial, polls=[initial, terminal], action_result=terminal)
    backend = BalatroBotBackend(client, settle_poll_delay=0)  # type: ignore[arg-type]

    result = AuthorityRunner(backend, NoBuySmokePolicy(), max_decisions=1).run(
        RunSpec("RED", "WHITE", "1")
    )

    assert result.complete
    assert result.terminal_reason == "game_over"
    assert result.decisions == 1


def test_runner_surfaces_bounded_policy_error_diagnostics() -> None:
    class FailingPolicy:
        def choose_action(self, observation, legal_actions, history):
            raise RuntimeError("public policy failure")

    initial = state()
    client = FakeClient(initial, polls=[initial])
    backend = BalatroBotBackend(client, settle_poll_delay=0)  # type: ignore[arg-type]

    result = AuthorityRunner(backend, FailingPolicy(), max_decisions=1).run(  # type: ignore[arg-type]
        RunSpec("RED", "WHITE", "1")
    )

    assert not result.complete
    assert result.terminal_reason == "policy_error"
    assert result.terminal_error == "RuntimeError: public policy failure"


def test_runner_continues_from_win_into_endless() -> None:
    won_round_eval = state("ROUND_EVAL", won=True)
    won_round_eval["ante_num"] = 9
    endless_shop = state("SHOP", won=True)
    endless_shop["ante_num"] = 9
    endless_game_over = state("GAME_OVER", won=True)
    endless_game_over["ante_num"] = 9
    client = FakeClient(
        won_round_eval,
        polls=[won_round_eval, endless_shop, endless_game_over],
        action_results=[endless_shop, endless_game_over],
    )
    backend = BalatroBotBackend(client, settle_poll_delay=0)  # type: ignore[arg-type]

    result = AuthorityRunner(backend, NoBuySmokePolicy(), max_decisions=2).run(
        RunSpec("RED", "WHITE", "1")
    )

    assert result.complete
    assert result.won
    assert result.antes_cleared == 8
    assert result.terminal_reason == "game_over"
    assert result.decisions == 2
    assert result.final_observation is not None
    assert result.final_observation.phase.value == "GAME_OVER"
    assert ("cash_out", {}) in client.calls
    assert ("next_round", {}) in client.calls


def test_runner_completes_at_development_ante_cap() -> None:
    capped = state("ROUND_EVAL", won=True)
    capped["ante_num"] = 19
    capped["used_vouchers"] = ["v_hieroglyph", "v_petroglyph"]
    client = FakeClient(capped, polls=[capped])
    backend = BalatroBotBackend(client, settle_poll_delay=0)  # type: ignore[arg-type]

    result = AuthorityRunner(backend, NoBuySmokePolicy(), max_antes_cleared=20).run(
        RunSpec("RED", "WHITE", "1")
    )

    assert result.complete
    assert result.terminal_reason == "ante_cap"
    assert result.antes_cleared == 20
    assert result.decisions == 0


def test_decision_limit_is_never_complete() -> None:
    initial = state()
    selecting = state("SELECTING_HAND")
    client = FakeClient(initial, polls=[initial, selecting], action_result=selecting)
    backend = BalatroBotBackend(client, settle_poll_delay=0)  # type: ignore[arg-type]

    result = AuthorityRunner(backend, NoBuySmokePolicy(), max_decisions=1).run(
        RunSpec("RED", "WHITE", "1")
    )

    assert not result.complete
    assert result.terminal_reason == "decision_limit"
