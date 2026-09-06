"""Backend-neutral authority contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from balatro_ai_v2.solver.actions import PublicAction
from balatro_ai_v2.solver.canonical import CanonicalObservedState


@dataclass(frozen=True, slots=True)
class RunSpec:
    deck: str
    stake: str
    seed: str | None = None


@dataclass(frozen=True, slots=True)
class BackendCapabilities:
    authoritative: bool
    complete_private_state: bool
    snapshot: bool
    restore: bool
    batch_rollout: bool


@dataclass(frozen=True, slots=True)
class BackendMetadata:
    backend_name: str
    backend_version: str
    adapter_version: str
    game_version: str | None
    runtime_version: str | None
    capabilities: BackendCapabilities


@dataclass(frozen=True, slots=True)
class AuthorityObservation:
    observed: CanonicalObservedState
    settled: bool
    polls: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class StepResult:
    status: Literal["accepted", "rejected", "transport_error"]
    action: PublicAction
    before: AuthorityObservation
    rpc_method: str
    rpc_params: dict[str, object]
    rpc_observations: tuple[str, ...]
    after: AuthorityObservation | None
    error: str | None = None


class GameBackend(Protocol):
    metadata: BackendMetadata

    def reset(self, spec: RunSpec) -> AuthorityObservation: ...

    def observe(self) -> AuthorityObservation: ...

    def step(self, action: PublicAction) -> StepResult: ...

    def close(self) -> None: ...
