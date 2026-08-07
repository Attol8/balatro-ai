"""No-waiver replay of authority traces against a candidate backend."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from balatro_ai_v2.actions import action_from_data
from balatro_ai_v2.backend import GameBackend, RunSpec
from balatro_ai_v2.balatrobot.tracing import read_verified_trace


@dataclass(frozen=True, slots=True)
class DifferentialMismatch:
    transition: int
    path: str
    authority: object
    candidate: object
    message: str


@dataclass(frozen=True, slots=True)
class DifferentialReport:
    observed_lockstep: bool
    checked_transitions: int
    mismatch: DifferentialMismatch | None = None


def replay_authority_trace(path: Path, candidate: GameBackend) -> DifferentialReport:
    rows = read_verified_trace(path)
    manifest_row = rows[0].get("manifest")
    if not isinstance(manifest_row, dict):
        return _failure(0, "", "manifest object", manifest_row, "invalid manifest")
    run_data = manifest_row.get("run")
    if not isinstance(run_data, dict):
        return _failure(0, "/manifest/run", "run object", run_data, "invalid run specification")
    spec = RunSpec(
        deck=str(run_data.get("deck") or ""),
        stake=str(run_data.get("stake") or ""),
        seed=str(run_data["seed"]) if run_data.get("seed") is not None else None,
    )

    starts = [row for row in rows if row.get("event") == "run_start"]
    ends = [row for row in rows if row.get("event") == "run_end"]
    if len(starts) != 1 or len(ends) != 1:
        return _failure(0, "", "one run_start and one run_end", (len(starts), len(ends)), "truncated trace")
    if ends[0] is not rows[-1]:
        return _failure(0, "", "run_end as final row", rows[-1].get("event"), "invalid terminal trace")
    if not bool(ends[0].get("complete")):
        return _failure(0, "/run_end/complete", True, ends[0].get("complete"), "authority trace is incomplete")

    expected_start = _nested(starts[0], "authority", "canonical")
    initial = candidate.reset(spec)
    mismatch = _compare(expected_start, initial.observed.canonical, transition=0)
    if mismatch is not None:
        return DifferentialReport(False, 0, mismatch)

    checked = 0
    current = initial
    for row in (entry for entry in rows if entry.get("event") == "transition"):
        if row.get("status") != "accepted":
            return _failure(
                checked + 1,
                "/status",
                "accepted",
                row.get("status"),
                "acceptance traces cannot contain rejected or failed actions",
                checked,
            )
        action_data = row.get("action")
        if not isinstance(action_data, dict):
            return _failure(checked + 1, "/action", "action object", action_data, "invalid action", checked)
        result = candidate.step(action_from_data(action_data))
        if result.status != "accepted" or result.after is None:
            return _failure(
                checked + 1,
                "/status",
                "accepted",
                result.status,
                "candidate action acceptance differs",
                checked,
            )
        expected = _nested(row, "after", "canonical")
        mismatch = _compare(expected, result.after.observed.canonical, transition=checked + 1)
        if mismatch is not None:
            return DifferentialReport(False, checked, mismatch)
        current = result.after
        checked += 1

    final_phase = current.observed.canonical.get("state")
    if final_phase != "GAME_OVER":
        return _failure(checked, "/state", "GAME_OVER", final_phase, "candidate did not terminate", checked)
    return DifferentialReport(True, checked)


def _compare(authority: object, candidate: object, *, transition: int) -> DifferentialMismatch | None:
    difference = _first_difference(authority, candidate, path="")
    if difference is None:
        return None
    path, expected, actual = difference
    return DifferentialMismatch(
        transition=transition,
        path=path or "/",
        authority=expected,
        candidate=actual,
        message="canonical observed state differs",
    )


def _first_difference(left: object, right: object, *, path: str) -> tuple[str, object, object] | None:
    if type(left) is not type(right):
        return path, left, right
    if isinstance(left, dict) and isinstance(right, dict):
        for key in sorted(set(left) | set(right)):
            child_path = f"{path}/{_escape_pointer(key)}"
            if key not in left:
                return child_path, "<missing>", right[key]
            if key not in right:
                return child_path, left[key], "<missing>"
            difference = _first_difference(left[key], right[key], path=child_path)
            if difference is not None:
                return difference
        return None
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return f"{path}/length", len(left), len(right)
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            difference = _first_difference(left_item, right_item, path=f"{path}/{index}")
            if difference is not None:
                return difference
        return None
    if left != right:
        return path, left, right
    return None


def _nested(row: dict[str, Any], *keys: str) -> object:
    value: object = row
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"trace is missing /{'/'.join(keys)}")
        value = value[key]
    return value


def _failure(
    transition: int,
    path: str,
    authority: object,
    candidate: object,
    message: str,
    checked: int = 0,
) -> DifferentialReport:
    return DifferentialReport(
        observed_lockstep=False,
        checked_transitions=checked,
        mismatch=DifferentialMismatch(transition, path or "/", authority, candidate, message),
    )


def _escape_pointer(value: object) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")
