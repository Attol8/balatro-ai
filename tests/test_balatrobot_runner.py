from __future__ import annotations

from collections import deque
from copy import deepcopy
from pathlib import Path

import pytest

from balatro_ai_v2.actions import SelectBlind
from balatro_ai_v2.backend import RunSpec
from balatro_ai_v2.balatrobot.backend import BalatroBotBackend, UnsettledStateError
from balatro_ai_v2.balatrobot.client import BalatroBotRpcError, BalatroBotTransportError
from balatro_ai_v2.balatrobot.runner import AuthorityRunner, NoBuySmokePolicy
from state_factory import state


class FakeClient:
    def __init__(self, initial, polls=(), action_result=None, action_error=None) -> None:
        self.initial = deepcopy(initial)
        self.polls = deque(deepcopy(tuple(polls)))
        self.action_result = deepcopy(action_result)
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
            return deepcopy(self.action_result if self.action_result is not None else self.initial)
        return self.polls.popleft()

    def call_action(self, method, params):
        self.calls.append((method, params))
        if self.action_error is not None:
            raise self.action_error
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
    assert "PRIVATE-SEED" not in result.final_observation.canonical_json()  # type: ignore[union-attr]


def test_decision_limit_is_never_complete() -> None:
    initial = state()
    selecting = state("SELECTING_HAND")
    client = FakeClient(initial, polls=[initial, selecting], action_result=selecting)
    backend = BalatroBotBackend(client, settle_poll_delay=0)  # type: ignore[arg-type]

    result = AuthorityRunner(backend, NoBuySmokePolicy(), max_decisions=1).run(RunSpec("RED", "WHITE", "1"))

    assert not result.complete
    assert result.terminal_reason == "decision_limit"
