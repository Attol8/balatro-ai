"""Tamper-evident, provenance-rich authority traces."""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from balatro_ai_v2.backend import BackendMetadata, RunSpec


TRACE_SCHEMA_VERSION = 1
CANONICAL_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class TraceManifest:
    run_id: str
    created_at: str
    repository_revision: str
    repository_dirty: bool
    source_digest: str
    command: tuple[str, ...]
    config_digest: str
    policy_name: str
    model_digest: str | None
    inference_budget: str
    backend: BackendMetadata
    run: RunSpec
    sealed_seed_manifest_digest: str | None
    max_decisions: int
    max_settle_polls: int
    wall_clock_limit_seconds: float | None
    launch_fast: bool
    launch_headless: bool
    profile_mode: str
    mods: tuple[str, ...] = ()
    trace_schema_version: int = TRACE_SCHEMA_VERSION
    canonical_schema_version: int = CANONICAL_SCHEMA_VERSION


def build_manifest(
    *,
    repository_root: Path,
    command: tuple[str, ...],
    policy_name: str,
    backend: BackendMetadata,
    run: RunSpec,
    max_decisions: int,
    max_settle_polls: int,
    launch_fast: bool,
    launch_headless: bool,
    profile_mode: str,
    model_path: Path | None = None,
    inference_budget: str = "none",
    sealed_seed_manifest_digest: str | None = None,
    wall_clock_limit_seconds: float | None = None,
    mods: tuple[str, ...] = (),
) -> TraceManifest:
    revision, dirty = _git_state(repository_root)
    config_json = _canonical_json(
        {
            "command": command,
            "policy": policy_name,
            "run": asdict(run),
            "max_decisions": max_decisions,
            "max_settle_polls": max_settle_polls,
            "wall_clock_limit_seconds": wall_clock_limit_seconds,
            "inference_budget": inference_budget,
            "launch_fast": launch_fast,
            "launch_headless": launch_headless,
            "profile_mode": profile_mode,
        }
    )
    return TraceManifest(
        run_id=uuid4().hex,
        created_at=datetime.now(timezone.utc).isoformat(),
        repository_revision=revision,
        repository_dirty=dirty,
        source_digest=_source_digest(repository_root),
        command=command,
        config_digest=_sha256(config_json.encode("utf-8")),
        policy_name=policy_name,
        model_digest=_file_digest(model_path) if model_path is not None else None,
        inference_budget=inference_budget,
        backend=backend,
        run=run,
        sealed_seed_manifest_digest=sealed_seed_manifest_digest,
        max_decisions=max_decisions,
        max_settle_polls=max_settle_polls,
        wall_clock_limit_seconds=wall_clock_limit_seconds,
        launch_fast=launch_fast,
        launch_headless=launch_headless,
        profile_mode=profile_mode,
        mods=mods,
    )


class AuthorityTraceWriter:
    def __init__(self, path: Path, manifest: TraceManifest) -> None:
        self.path = path
        self.manifest = manifest
        self._sequence = 0
        self._previous_hash: str | None = None
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8"):
            pass
        self.record("manifest", manifest=_primitive(manifest))

    def record(self, event: str, **payload: object) -> None:
        row: dict[str, object] = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "run_id": self.manifest.run_id,
            "seq": self._sequence,
            "event": event,
            "previous_hash": self._previous_hash,
            **{key: _primitive(value) for key, value in payload.items()},
        }
        row_hash = _row_hash(row)
        row["row_hash"] = row_hash
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(_canonical_json(row) + "\n")
        self._previous_hash = row_hash
        self._sequence += 1


def read_verified_trace(path: Path) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    previous_hash: str | None = None
    run_id: str | None = None
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on trace line {line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"trace line {line_number} is not an object")
            if row.get("schema_version") != TRACE_SCHEMA_VERSION:
                raise ValueError(f"unsupported schema version at trace line {line_number}")
            row_run_id = row.get("run_id")
            if not isinstance(row_run_id, str) or not row_run_id:
                raise ValueError(f"missing run ID at trace line {line_number}")
            if run_id is None:
                run_id = row_run_id
            elif row_run_id != run_id:
                raise ValueError(f"run ID changed at trace line {line_number}")
            if not isinstance(row.get("event"), str) or not row["event"]:
                raise ValueError(f"missing event name at trace line {line_number}")
            if row.get("seq") != len(rows):
                raise ValueError(f"non-contiguous sequence at trace line {line_number}")
            if row.get("previous_hash") != previous_hash:
                raise ValueError(f"broken hash chain at trace line {line_number}")
            claimed_hash = row.pop("row_hash", None)
            if not isinstance(claimed_hash, str):
                raise ValueError(f"missing row hash at trace line {line_number}")
            actual_hash = _row_hash(row)
            row["row_hash"] = claimed_hash
            if claimed_hash != actual_hash:
                raise ValueError(f"row hash mismatch at trace line {line_number}")
            previous_hash = actual_hash
            rows.append(row)
    if not rows or rows[0].get("event") != "manifest":
        raise ValueError("trace must begin with exactly one manifest")
    if sum(row.get("event") == "manifest" for row in rows) != 1:
        raise ValueError("trace must contain exactly one manifest")
    manifest = rows[0].get("manifest")
    if not isinstance(manifest, dict):
        raise ValueError("trace manifest payload is missing")
    if manifest.get("canonical_schema_version") != CANONICAL_SCHEMA_VERSION:
        raise ValueError("unsupported canonical schema version")
    if manifest.get("profile_mode") not in {"all_unlocked", "career"}:
        raise ValueError("trace manifest has no supported profile mode")
    return tuple(rows)


def _row_hash(row: dict[str, object]) -> str:
    return _sha256(_canonical_json(row).encode("utf-8"))


def _primitive(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return _primitive(asdict(value))
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [_primitive(item) for item in value]
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError(f"trace value is not serializable: {type(value).__name__}")


def _git_state(root: Path) -> tuple[str, bool]:
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return revision, dirty
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True


def _source_digest(root: Path) -> str:
    digest = hashlib.sha256()
    candidates = [root / "pyproject.toml", root / "plan.md"]
    for directory in (root / "balatro_ai_v2", root / "scripts", root / "tests"):
        if directory.exists():
            candidates.extend(directory.rglob("*.py"))
    for path in sorted((path for path in candidates if path.is_file()), key=lambda item: str(item.relative_to(root))):
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _file_digest(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    return _sha256(path.read_bytes())


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
