"""BalatroBot as the observed-state authority."""

from __future__ import annotations

import json
import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from balatro_ai_v2.actions import (
    BuyShopCard,
    BuyVoucher,
    ChoosePackCard,
    PublicAction,
    RerollShop,
    SkipPack,
)
from balatro_ai_v2.backend import (
    AuthorityObservation,
    BackendCapabilities,
    BackendMetadata,
    RunSpec,
    StepResult,
)
from balatro_ai_v2.balatrobot.adapter import action_to_rpc, to_public_observation
from balatro_ai_v2.balatrobot.client import (
    BalatroBotClient,
    BalatroBotRpcError,
    BalatroBotTransportError,
)
from balatro_ai_v2.canonical import BalatroBotCanonicalizer


_PACK_PHASES = {
    "SMODS_BOOSTER_OPENED",
    "PLANET_PACK",
    "TAROT_PACK",
    "SPECTRAL_PACK",
    "STANDARD_PACK",
    "BUFFOON_PACK",
}
_PACK_PHASES_WITH_VISIBLE_HAND = {"TAROT_PACK", "SPECTRAL_PACK"}
_STABLE_PHASES = {"BLIND_SELECT", "ROUND_EVAL", "GAME_OVER"}


class UnsettledStateError(RuntimeError):
    """The real game never reached a stable decision boundary."""


@dataclass(slots=True)
class BalatroBotBackend:
    client: BalatroBotClient
    max_settle_polls: int = 40
    settle_poll_delay: float = 0.02
    sleep: Callable[[float], None] = time.sleep
    backend_version: str = "unknown"
    game_version: str | None = None
    runtime_version: str | None = None
    canonicalizer: BalatroBotCanonicalizer = field(default_factory=BalatroBotCanonicalizer)
    metadata: BackendMetadata = field(init=False)
    _current: AuthorityObservation | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.max_settle_polls < 1:
            raise ValueError("max_settle_polls must be positive")
        self.metadata = BackendMetadata(
            backend_name="BalatroBot/LÖVE",
            backend_version=self.backend_version,
            adapter_version="1",
            game_version=self.game_version,
            runtime_version=self.runtime_version,
            capabilities=BackendCapabilities(
                authoritative=True,
                complete_private_state=False,
                snapshot=False,
                restore=False,
                batch_rollout=False,
            ),
        )

    def reset(self, spec: RunSpec) -> AuthorityObservation:
        self.canonicalizer.reset()
        self.client.menu()
        initial = self.client.start(deck=spec.deck, stake=spec.stake, seed=spec.seed)
        self._current = self._settle(initial)
        return self._current

    def observe(self) -> AuthorityObservation:
        allow_empty_shop = self._current is not None and _canonical_shop_empty(
            self._current.observed.canonical
        )
        self._current = self._settle(
            self.client.gamestate(),
            allow_empty_shop=allow_empty_shop,
        )
        return self._current

    def save_file_snapshot(self, path: Path) -> None:
        """Privileged evaluation hook; snapshot data never crosses the policy boundary."""

        if self._current is None:
            raise RuntimeError("reset must be called before saving a snapshot")
        result = self.client.save(path=str(path))
        if result.get("success") is not True:
            raise RuntimeError("BalatroBot did not confirm snapshot save")

    def load_file_snapshot(self, path: Path) -> AuthorityObservation:
        """Restore a private file snapshot and establish a new canonical branch root."""

        result = self.client.load(path=str(path))
        if result.get("success") is not True:
            raise RuntimeError("BalatroBot did not confirm snapshot restore")
        self.canonicalizer.reset()
        self._current = self._settle(self.client.gamestate())
        return self._current

    def create_memory_checkpoint(self) -> tuple[str, int]:
        if self._current is None:
            raise RuntimeError("reset must be called before creating a checkpoint")
        result = self.client.checkpoint(op="create")
        snapshot_id = result.get("snapshot_id")
        size = result.get("bytes")
        if not isinstance(snapshot_id, str) or not snapshot_id or not isinstance(size, int):
            raise RuntimeError("BalatroBot returned an invalid checkpoint reference")
        return snapshot_id, size

    def load_memory_checkpoint(self, snapshot_id: str) -> AuthorityObservation:
        result = self.client.checkpoint(op="restore", snapshot_id=snapshot_id)
        if result.get("success") is not True:
            raise RuntimeError("BalatroBot did not confirm checkpoint restore")
        self.canonicalizer.reset()
        self._current = self._settle(self.client.gamestate())
        return self._current

    def delete_memory_checkpoint(self, snapshot_id: str) -> None:
        result = self.client.checkpoint(op="delete", snapshot_id=snapshot_id)
        if result.get("success") is not True:
            raise RuntimeError("BalatroBot did not confirm checkpoint deletion")

    def step(self, action: PublicAction) -> StepResult:
        if self._current is None:
            raise RuntimeError("reset must be called before step")
        before = self._current
        raw_before = json.loads(before.observed.raw_json)
        public_before = to_public_observation(raw_before)
        method, params = action_to_rpc(action, public_before)
        try:
            rpc_state = self.client.call_action(method, params)
        except BalatroBotRpcError as exc:
            return StepResult(
                status="rejected",
                action=action,
                before=before,
                rpc_method=method,
                rpc_params=params,
                rpc_observations=(),
                after=None,
                error=str(exc),
            )
        except BalatroBotTransportError as exc:
            return StepResult(
                status="transport_error",
                action=action,
                before=before,
                rpc_method=method,
                rpc_params=params,
                rpc_observations=(),
                after=None,
                error=str(exc),
            )

        after = self._settle(
            rpc_state,
            allow_empty_shop=_action_can_empty_shop(before, action),
        )
        self._current = after
        return StepResult(
            status="accepted",
            action=action,
            before=before,
            rpc_method=method,
            rpc_params=params,
            rpc_observations=after.polls,
            after=after,
        )

    def close(self) -> None:
        return None

    def _settle(
        self,
        initial: dict[str, Any],
        *,
        allow_empty_shop: bool = False,
    ) -> AuthorityObservation:
        captured: list[str] = []
        previous_ready_digest: str | None = None
        state = initial
        for poll_index in range(self.max_settle_polls + 1):
            raw_json = json.dumps(
                state,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            captured.append(raw_json)
            if _is_ready(state, allow_empty_shop=allow_empty_shop):
                ready_digest = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
                if ready_digest == previous_ready_digest:
                    # Validate the information firewall at the boundary, before
                    # any policy can see the state.
                    to_public_observation(state)
                    observed = self.canonicalizer.canonicalize(state)
                    return AuthorityObservation(observed=observed, settled=True, polls=tuple(captured))
                previous_ready_digest = ready_digest
            else:
                previous_ready_digest = None

            if poll_index == self.max_settle_polls:
                break
            if self.settle_poll_delay > 0:
                self.sleep(self.settle_poll_delay)
            state = self.client.gamestate()
        raise UnsettledStateError(
            f"state did not settle after {self.max_settle_polls} polls; last phase={state.get('state')!r}"
        )


def _is_ready(state: dict[str, Any], *, allow_empty_shop: bool = False) -> bool:
    phase = state.get("state")
    if phase in _STABLE_PHASES:
        return True
    if phase == "SELECTING_HAND":
        return _area_ready(state, "hand", require_cards=True)
    if phase == "SHOP":
        areas = ("shop", "packs", "vouchers")
        areas_ready = all(
            area in state and _area_ready(state, area, require_cards=False) for area in areas
        )
        return areas_ready and (
            allow_empty_shop or any(_area_ready(state, area, require_cards=True) for area in areas)
        )
    if phase in _PACK_PHASES:
        if not _area_ready(state, "pack", require_cards=True):
            return False
        return phase not in _PACK_PHASES_WITH_VISIBLE_HAND or _area_ready(state, "hand", require_cards=True)
    return False


def _area_ready(state: dict[str, Any], name: str, *, require_cards: bool) -> bool:
    area = state.get(name)
    if not isinstance(area, dict) or not isinstance(area.get("cards"), list):
        return False
    cards = area["cards"]
    return area.get("count") == len(cards) and (bool(cards) or not require_cards)


def _action_can_empty_shop(before: AuthorityObservation, action: PublicAction) -> bool:
    canonical = before.observed.canonical
    if _canonical_shop_empty(canonical):
        return not isinstance(action, RerollShop)
    counts = {name: _canonical_area_count(canonical, name) for name in ("shop", "packs", "vouchers")}
    if any(count is None for count in counts.values()):
        return False
    if isinstance(action, BuyShopCard):
        return counts == {"shop": 1, "packs": 0, "vouchers": 0}
    if isinstance(action, BuyVoucher):
        return counts == {"shop": 0, "packs": 0, "vouchers": 1}
    if isinstance(action, (ChoosePackCard, SkipPack)):
        return counts == {"shop": 0, "packs": 0, "vouchers": 0}
    return False


def _canonical_shop_empty(canonical: dict[str, Any]) -> bool:
    return all(_canonical_area_count(canonical, name) == 0 for name in ("shop", "packs", "vouchers"))


def _canonical_area_count(canonical: dict[str, Any], name: str) -> int | None:
    area = canonical.get(name)
    count = area.get("count") if isinstance(area, dict) else None
    return count if isinstance(count, int) and count >= 0 else None
