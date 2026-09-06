"""Seed-free public candidate transcripts and fail-closed live replay."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from balatro_ai_v2.actions import (
    PublicAction,
    action_to_data,
    canonical_action_from_data,
    iter_legal_actions,
)
from balatro_ai_v2.backend import BackendMetadata
from balatro_ai_v2.balatrobot.tracing import source_snapshot
from balatro_ai_v2.policy import ActionSource, PublicHistoryStep
from balatro_ai_v2.policy_wire import POLICY_ACTION_CONTRACT
from balatro_ai_v2.public_codec import public_observation_from_data
from balatro_ai_v2.public_state import PublicObservation


CANDIDATE_TRACE_SCHEMA_VERSION = 1
CANDIDATE_TRACE_FORMAT = "public_candidate_action_transcript_v1"
MAX_CANDIDATE_TRACE_BYTES = 128 * 1024 * 1024
MAX_CANDIDATE_TRACE_DECISIONS = 2_048

_ROW_ENVELOPE = {
    "schema_version",
    "run_id",
    "seq",
    "event",
    "previous_hash",
    "row_hash",
}
_RUN_END_PAYLOAD = {
    "complete",
    "won",
    "antes_cleared",
    "ante",
    "round_no",
    "accepted_decisions",
    "rejected_decisions",
    "terminal_reason",
    "final_public_digest",
    "action_counts",
    "cards_played",
    "cards_discarded",
    "best_hand_score",
}


class CandidateTraceReplayError(ValueError):
    """The candidate transcript or its live public replay is not exact."""


@dataclass(frozen=True, slots=True)
class CandidateTraceManifest:
    format: str
    run_id: str
    created_at: str
    repository_revision: str
    repository_dirty: bool
    source_digest: str
    config_digest: str
    policy_name: str
    model_digest: str | None
    inference_budget: str
    backend_name: str
    backend_version: str
    adapter_version: str
    game_version: str | None
    runtime_version: str | None
    candidate_only: bool
    deck: str
    stake: str
    max_decisions: int
    max_antes_cleared: int
    action_contract: str = POLICY_ACTION_CONTRACT
    schema_version: int = CANDIDATE_TRACE_SCHEMA_VERSION


@dataclass(frozen=True, slots=True)
class CandidateTraceStep:
    before: PublicObservation
    action: PublicAction
    after: PublicObservation


def build_candidate_trace_manifest(
    *,
    repository_root: Path,
    policy_name: str,
    backend: BackendMetadata,
    deck: str,
    stake: str,
    max_decisions: int,
    max_antes_cleared: int,
    inference_budget: str,
    model_digest: str | None,
) -> CandidateTraceManifest:
    """Build provenance without admitting a seed, command, or private state."""

    revision, dirty, source_digest = source_snapshot(repository_root)
    config = {
        "format": CANDIDATE_TRACE_FORMAT,
        "policy_name": policy_name,
        "model_digest": model_digest,
        "inference_budget": inference_budget,
        "backend_name": backend.backend_name,
        "backend_version": backend.backend_version,
        "adapter_version": backend.adapter_version,
        "game_version": backend.game_version,
        "runtime_version": backend.runtime_version,
        "candidate_only": True,
        "deck": deck,
        "stake": stake,
        "max_decisions": max_decisions,
        "max_antes_cleared": max_antes_cleared,
        "action_contract": POLICY_ACTION_CONTRACT,
        "schema_version": CANDIDATE_TRACE_SCHEMA_VERSION,
    }
    return CandidateTraceManifest(
        format=CANDIDATE_TRACE_FORMAT,
        run_id=uuid4().hex,
        created_at=datetime.now(timezone.utc).isoformat(),
        repository_revision=revision,
        repository_dirty=dirty,
        source_digest=source_digest,
        config_digest=_sha256(_canonical_json(config).encode("utf-8")),
        policy_name=policy_name,
        model_digest=model_digest,
        inference_budget=inference_budget,
        backend_name=backend.backend_name,
        backend_version=backend.backend_version,
        adapter_version=backend.adapter_version,
        game_version=backend.game_version,
        runtime_version=backend.runtime_version,
        candidate_only=True,
        deck=deck,
        stake=stake,
        max_decisions=max_decisions,
        max_antes_cleared=max_antes_cleared,
    )


class CandidateTraceWriter:
    """AuthorityRunner-compatible writer that persists public fields only."""

    def __init__(self, path: Path, manifest: CandidateTraceManifest) -> None:
        self.path = path
        self.manifest = manifest
        self._sequence = 0
        self._previous_hash: str | None = None
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8"):
            pass
        self._write("manifest", manifest=asdict(manifest))

    def record(self, event: str, **payload: object) -> None:
        if event == "run_start":
            safe = {"public": payload.get("public")}
        elif event == "transition":
            safe = {
                "action": payload.get("action"),
                "status": payload.get("status"),
                "error": (
                    None if payload.get("error") is None else "candidate_error"
                ),
                "public_after": payload.get("public_after"),
            }
        elif event == "run_end":
            safe = {name: payload.get(name) for name in _RUN_END_PAYLOAD}
        elif event in {"policy_error", "authority_error"}:
            safe = {"error": event}
        else:
            raise CandidateTraceReplayError(f"unsupported candidate event {event!r}")
        self._write(event, **safe)

    def _write(self, event: str, **payload: object) -> None:
        row: dict[str, object] = {
            "schema_version": CANDIDATE_TRACE_SCHEMA_VERSION,
            "run_id": self.manifest.run_id,
            "seq": self._sequence,
            "event": event,
            "previous_hash": self._previous_hash,
            **payload,
        }
        row_hash = _row_hash(row)
        row["row_hash"] = row_hash
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical_json(row) + "\n")
        self._previous_hash = row_hash
        self._sequence += 1


@dataclass(slots=True)
class CandidateTraceReplayPolicy:
    """Replay actions only while the live public trajectory matches exactly."""

    source_digest: str
    source_policy_name: str
    deck: str
    stake: str
    max_decisions: int
    max_antes_cleared: int
    steps: tuple[CandidateTraceStep, ...]
    final_observation: PublicObservation
    terminal_reason: str
    _index: int = 0

    @classmethod
    def from_path(cls, path: Path) -> CandidateTraceReplayPolicy:
        try:
            with path.open("rb") as handle:
                raw = handle.read(MAX_CANDIDATE_TRACE_BYTES + 1)
        except OSError as exc:
            raise CandidateTraceReplayError(
                f"cannot read candidate trace: {exc}"
            ) from exc
        return cls.from_bytes(raw)

    @classmethod
    def from_bytes(cls, raw: bytes) -> CandidateTraceReplayPolicy:
        if len(raw) > MAX_CANDIDATE_TRACE_BYTES:
            raise CandidateTraceReplayError("candidate trace exceeds the byte limit")
        try:
            rows = _read_verified_rows(raw)
            parsed = _parse_candidate_trace(rows)
        except (TypeError, ValueError) as exc:
            raise CandidateTraceReplayError(str(exc)) from exc
        return cls(source_digest=_sha256(raw), **parsed)

    @property
    def consumed_actions(self) -> int:
        return self._index

    def choose_action(
        self,
        observation: PublicObservation,
        legal_actions: ActionSource,
        history: tuple[PublicHistoryStep, ...],
    ) -> PublicAction:
        if self._index >= len(self.steps):
            raise CandidateTraceReplayError("candidate trace has no remaining action")
        if len(history) != self._index:
            raise CandidateTraceReplayError("live public history length diverged")
        if self._index and history[-1] != PublicHistoryStep(
            before=self.steps[self._index - 1].before,
            action=self.steps[self._index - 1].action,
            after=self.steps[self._index - 1].after,
        ):
            raise CandidateTraceReplayError("live public history diverged")
        step = self.steps[self._index]
        if observation != step.before:
            raise CandidateTraceReplayError(
                f"live public observation diverged at decision {self._index}"
            )
        legal = tuple(legal_actions())
        matches = tuple(action for action in legal if action == step.action)
        if len(matches) != 1:
            raise CandidateTraceReplayError(
                f"recorded action is not uniquely legal at decision {self._index}"
            )
        self._index += 1
        return matches[0]

    def assert_complete(self, final_observation: PublicObservation | None) -> None:
        if self._index != len(self.steps):
            raise CandidateTraceReplayError(
                f"live run consumed {self._index} of {len(self.steps)} actions"
            )
        if final_observation != self.final_observation:
            raise CandidateTraceReplayError("live final public observation diverged")


def _parse_candidate_trace(rows: tuple[dict[str, Any], ...]) -> dict[str, object]:
    _validate_row_fields(rows)
    manifest = rows[0].get("manifest")
    manifest_fields = set(CandidateTraceManifest.__dataclass_fields__)
    if not isinstance(manifest, dict) or set(manifest) != manifest_fields:
        raise CandidateTraceReplayError("candidate trace manifest has invalid fields")
    if (
        manifest.get("format") != CANDIDATE_TRACE_FORMAT
        or manifest.get("schema_version") != CANDIDATE_TRACE_SCHEMA_VERSION
    ):
        raise CandidateTraceReplayError("candidate trace schema is not current")
    if manifest.get("action_contract") != POLICY_ACTION_CONTRACT:
        raise CandidateTraceReplayError("candidate trace action contract is not current")
    if manifest.get("run_id") != rows[0].get("run_id"):
        raise CandidateTraceReplayError("candidate trace run ID is inconsistent")
    if manifest.get("repository_dirty") is not False:
        raise CandidateTraceReplayError("candidate trace source repository is dirty")
    for name, length in (
        ("repository_revision", 40),
        ("source_digest", 64),
        ("config_digest", 64),
    ):
        if not _is_hex_digest(manifest.get(name), length):
            raise CandidateTraceReplayError(
                f"candidate trace {name} is not a pinned digest"
            )
    model_digest = manifest.get("model_digest")
    if model_digest is not None and not _is_hex_digest(model_digest, 64):
        raise CandidateTraceReplayError("candidate trace model digest is invalid")
    if manifest.get("config_digest") != _sha256(
        _canonical_json(_manifest_config(manifest)).encode("utf-8")
    ):
        raise CandidateTraceReplayError("candidate trace config digest is inconsistent")
    if manifest.get("candidate_only") is not True:
        raise CandidateTraceReplayError("candidate trace is not candidate-only")
    if manifest.get("backend_name") != "Jackdaw":
        raise CandidateTraceReplayError("replay source is not pinned Jackdaw")
    policy_name = manifest.get("policy_name")
    if not isinstance(policy_name, str) or not policy_name.startswith(
        "DeterminizedSearchPolicy["
    ):
        raise CandidateTraceReplayError("replay source is not determinized search")
    deck = _nonempty_string(manifest.get("deck"), "deck")
    stake = _nonempty_string(manifest.get("stake"), "stake")
    max_decisions = _positive_integer(manifest.get("max_decisions"), "max_decisions")
    max_antes = _positive_integer(
        manifest.get("max_antes_cleared"), "max_antes_cleared"
    )
    if max_decisions > MAX_CANDIDATE_TRACE_DECISIONS:
        raise CandidateTraceReplayError(
            "candidate trace decision budget exceeds the replay limit"
        )

    starts = [row for row in rows if row.get("event") == "run_start"]
    transitions = [row for row in rows if row.get("event") == "transition"]
    ends = [row for row in rows if row.get("event") == "run_end"]
    if (
        len(starts) != 1
        or len(ends) != 1
        or starts[0] is not rows[1]
        or ends[0] is not rows[-1]
    ):
        raise CandidateTraceReplayError("candidate trace boundaries are invalid")
    if len(transitions) > max_decisions:
        raise CandidateTraceReplayError("candidate trace exceeds its decision budget")
    current = public_observation_from_data(starts[0].get("public"))
    if current.deck != deck or current.stake != stake:
        raise CandidateTraceReplayError("candidate trace public run identity disagrees")
    steps: list[CandidateTraceStep] = []
    action_counts: Counter[str] = Counter()
    for row in transitions:
        if current.terminal or current.antes_cleared >= max_antes:
            raise CandidateTraceReplayError("candidate trace acts after its endpoint")
        if row.get("status") != "accepted" or row.get("error") is not None:
            raise CandidateTraceReplayError("candidate trace contains a failed action")
        action = canonical_action_from_data(row.get("action"))
        if sum(candidate == action for candidate in iter_legal_actions(current)) != 1:
            raise CandidateTraceReplayError("candidate source action is not uniquely legal")
        after = public_observation_from_data(row.get("public_after"))
        steps.append(CandidateTraceStep(current, action, after))
        action_counts[str(action_to_data(action)["type"])] += 1
        current = after

    end = ends[0]
    if end.get("complete") is not True:
        raise CandidateTraceReplayError("candidate trace source run is incomplete")
    if _nonnegative_integer(end.get("rejected_decisions"), "rejected_decisions") != 0:
        raise CandidateTraceReplayError("candidate trace source rejected an action")
    if _nonnegative_integer(end.get("accepted_decisions"), "accepted_decisions") != len(steps):
        raise CandidateTraceReplayError("candidate trace decision count is inconsistent")
    if end.get("final_public_digest") != current.digest():
        raise CandidateTraceReplayError("candidate trace final digest is inconsistent")
    if end.get("won") is not current.won:
        raise CandidateTraceReplayError("candidate trace win state is inconsistent")
    if _nonnegative_integer(end.get("antes_cleared"), "antes_cleared") != current.antes_cleared:
        raise CandidateTraceReplayError("candidate trace ante count is inconsistent")
    if _string_integer_counts(end.get("action_counts")) != dict(
        sorted(action_counts.items())
    ):
        raise CandidateTraceReplayError("candidate trace action counts are inconsistent")
    terminal_reason = end.get("terminal_reason")
    if terminal_reason == "game_over":
        if not current.terminal:
            raise CandidateTraceReplayError("candidate game-over endpoint is not terminal")
    elif terminal_reason == "ante_cap":
        if current.antes_cleared < max_antes:
            raise CandidateTraceReplayError("candidate trace did not reach its ante cap")
    else:
        raise CandidateTraceReplayError("candidate trace endpoint is inadmissible")
    return {
        "source_policy_name": policy_name,
        "deck": deck,
        "stake": stake,
        "max_decisions": max_decisions,
        "max_antes_cleared": max_antes,
        "steps": tuple(steps),
        "final_observation": current,
        "terminal_reason": terminal_reason,
    }


def _read_verified_rows(raw: bytes) -> tuple[dict[str, Any], ...]:
    try:
        lines = raw.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise CandidateTraceReplayError("candidate trace is not UTF-8") from exc
    rows: list[dict[str, Any]] = []
    previous_hash: str | None = None
    run_id: str | None = None
    for line_number, line in enumerate(lines, 1):
        try:
            row = json.loads(line, object_pairs_hook=_reject_duplicate_keys)
        except (json.JSONDecodeError, ValueError) as exc:
            raise CandidateTraceReplayError(
                f"invalid candidate JSON on line {line_number}: {exc}"
            ) from exc
        if not isinstance(row, dict):
            raise CandidateTraceReplayError("candidate trace row is not an object")
        if type(row.get("schema_version")) is not int or row.get(
            "schema_version"
        ) != CANDIDATE_TRACE_SCHEMA_VERSION:
            raise CandidateTraceReplayError("candidate trace row schema is not current")
        row_id = row.get("run_id")
        if not isinstance(row_id, str) or not row_id:
            raise CandidateTraceReplayError("candidate trace row has no run ID")
        if run_id is None:
            run_id = row_id
        elif row_id != run_id:
            raise CandidateTraceReplayError("candidate trace run ID changed")
        if type(row.get("seq")) is not int or row["seq"] != len(rows):
            raise CandidateTraceReplayError("candidate trace sequence is invalid")
        if row.get("previous_hash") != previous_hash:
            raise CandidateTraceReplayError("candidate trace hash chain is broken")
        claimed = row.pop("row_hash", None)
        actual = _row_hash(row)
        row["row_hash"] = claimed
        if not isinstance(claimed, str) or claimed != actual:
            raise CandidateTraceReplayError("candidate trace row hash is invalid")
        previous_hash = actual
        rows.append(row)
        if len(rows) > MAX_CANDIDATE_TRACE_DECISIONS + 3:
            raise CandidateTraceReplayError("candidate trace has too many rows")
    if not rows or rows[0].get("event") != "manifest":
        raise CandidateTraceReplayError("candidate trace has no manifest")
    return tuple(rows)


def _validate_row_fields(rows: tuple[dict[str, Any], ...]) -> None:
    for row in rows:
        event = row.get("event")
        if event == "manifest":
            expected = _ROW_ENVELOPE | {"manifest"}
        elif event == "run_start":
            expected = _ROW_ENVELOPE | {"public"}
        elif event == "transition":
            expected = _ROW_ENVELOPE | {"action", "status", "error", "public_after"}
        elif event == "run_end":
            expected = _ROW_ENVELOPE | _RUN_END_PAYLOAD
        else:
            raise CandidateTraceReplayError("candidate trace contains a failure event")
        if set(row) != expected:
            raise CandidateTraceReplayError(
                f"candidate trace {event} row has invalid fields"
            )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _manifest_config(manifest: dict[str, object]) -> dict[str, object]:
    return {
        name: manifest.get(name)
        for name in (
            "format",
            "policy_name",
            "model_digest",
            "inference_budget",
            "backend_name",
            "backend_version",
            "adapter_version",
            "game_version",
            "runtime_version",
            "candidate_only",
            "deck",
            "stake",
            "max_decisions",
            "max_antes_cleared",
            "action_contract",
            "schema_version",
        )
    }


def _string_integer_counts(value: object) -> dict[str, int]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and type(count) is int and count >= 0
        for key, count in value.items()
    ):
        raise CandidateTraceReplayError("candidate trace action counts are invalid")
    return dict(value)


def _positive_integer(value: object, name: str) -> int:
    parsed = _nonnegative_integer(value, name)
    if parsed < 1:
        raise CandidateTraceReplayError(f"{name} must be positive")
    return parsed


def _nonnegative_integer(value: object, name: str) -> int:
    if type(value) is not int or value < 0:
        raise CandidateTraceReplayError(f"{name} must be a non-negative integer")
    return value


def _nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise CandidateTraceReplayError(f"{name} must be a non-empty string")
    return value


def _is_hex_digest(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _row_hash(row: dict[str, object]) -> str:
    return _sha256(_canonical_json(row).encode("utf-8"))


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


__all__ = [
    "CANDIDATE_TRACE_FORMAT",
    "CANDIDATE_TRACE_SCHEMA_VERSION",
    "CandidateTraceManifest",
    "CandidateTraceReplayError",
    "CandidateTraceReplayPolicy",
    "CandidateTraceStep",
    "CandidateTraceWriter",
    "MAX_CANDIDATE_TRACE_BYTES",
    "build_candidate_trace_manifest",
]
