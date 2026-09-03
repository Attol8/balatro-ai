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


_DETERMINISM_MANIFEST_FIELDS = (
    "repository_revision",
    "repository_dirty",
    "source_digest",
    "policy_name",
    "model_digest",
    "inference_budget",
    "backend",
    "run",
    "sealed_seed_manifest_digest",
    "max_decisions",
    "max_settle_polls",
    "wall_clock_limit_seconds",
    "launch_fast",
    "launch_headless",
    "profile_mode",
    "mods",
    "canonical_schema_version",
)


def compare_authority_traces(first_path: Path, second_path: Path) -> DifferentialReport:
    """Require two fresh authority runs to produce the same canonical trajectory."""

    first_rows = read_verified_trace(first_path)
    second_rows = read_verified_trace(second_path)
    first_manifest = _nested(first_rows[0], "manifest")
    second_manifest = _nested(second_rows[0], "manifest")
    if not isinstance(first_manifest, dict) or not isinstance(second_manifest, dict):
        return _failure(0, "/manifest", "manifest object", second_manifest, "invalid manifest")

    first_config = {key: first_manifest.get(key) for key in _DETERMINISM_MANIFEST_FIELDS}
    second_config = {key: second_manifest.get(key) for key in _DETERMINISM_MANIFEST_FIELDS}
    mismatch = _compare_values(
        first_config,
        second_config,
        transition=0,
        path_prefix="/manifest",
        message="authority trace configurations differ",
    )
    if mismatch is not None:
        return DifferentialReport(False, 0, mismatch)

    first_bounds = _complete_trace_bounds(first_rows)
    second_bounds = _complete_trace_bounds(second_rows)
    if isinstance(first_bounds, DifferentialReport):
        return first_bounds
    if isinstance(second_bounds, DifferentialReport):
        return second_bounds
    first_start, first_end = first_bounds
    second_start, second_end = second_bounds

    mismatch = _compare_values(
        _nested(first_start, "authority", "canonical"),
        _nested(second_start, "authority", "canonical"),
        transition=0,
        message="authority initial states differ",
    )
    if mismatch is not None:
        return DifferentialReport(False, 0, mismatch)

    first_transitions = [row for row in first_rows if row.get("event") == "transition"]
    second_transitions = [row for row in second_rows if row.get("event") == "transition"]
    checked = 0
    for index, (first, second) in enumerate(
        zip(first_transitions, second_transitions, strict=False), 1
    ):
        for row in (first, second):
            if row.get("status") != "accepted":
                return _failure(
                    index,
                    "/status",
                    "accepted",
                    row.get("status"),
                    "determinism traces must contain only accepted actions",
                    checked,
                )
        mismatch = _compare_values(
            first.get("action"),
            second.get("action"),
            transition=index,
            path_prefix="/action",
            message="deterministic policy actions differ",
        )
        if mismatch is not None:
            return DifferentialReport(False, checked, mismatch)
        mismatch = _compare_values(
            _nested(first, "after", "canonical"),
            _nested(second, "after", "canonical"),
            transition=index,
            message="authority canonical states differ",
        )
        if mismatch is not None:
            return DifferentialReport(False, checked, mismatch)
        checked += 1

    if len(first_transitions) != len(second_transitions):
        return _failure(
            checked + 1,
            "/transition_count",
            len(first_transitions),
            len(second_transitions),
            "authority transition counts differ",
            checked,
        )
    mismatch = _compare_values(
        {key: first_end.get(key) for key in ("complete", "won", "ante", "terminal_reason")},
        {key: second_end.get(key) for key in ("complete", "won", "ante", "terminal_reason")},
        transition=checked,
        path_prefix="/run_end",
        message="authority terminal outcomes differ",
    )
    if mismatch is not None:
        return DifferentialReport(False, checked, mismatch)
    return DifferentialReport(True, checked)


def replay_authority_trace(path: Path, candidate: GameBackend) -> DifferentialReport:
    rows = read_verified_trace(path)
    manifest_row = rows[0].get("manifest")
    if not isinstance(manifest_row, dict):
        return _failure(0, "", "manifest object", manifest_row, "invalid manifest")
    trace_profile_mode = manifest_row.get("profile_mode")
    candidate_profile_mode = getattr(candidate, "profile_mode", None)
    if candidate_profile_mode is not None and trace_profile_mode != candidate_profile_mode:
        return _failure(
            0,
            "/manifest/profile_mode",
            candidate_profile_mode,
            trace_profile_mode,
            "candidate and authority profile modes differ",
        )
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
    configure_replay = getattr(candidate, "configure_replay", None)
    if callable(configure_replay):
        configure_replay(expected_start)
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

    run_end = ends[0]
    terminal_reason = run_end.get("terminal_reason")
    final_canonical = current.observed.canonical
    final_phase = final_canonical.get("state")
    final_antes_cleared = _canonical_antes_cleared(final_canonical)
    if terminal_reason == "game_over":
        if final_phase != "GAME_OVER":
            return _failure(
                checked,
                "/state",
                "GAME_OVER",
                final_phase,
                "game-over trace did not reach GAME_OVER",
                checked,
            )
    elif terminal_reason == "ante_cap":
        cap = manifest_row.get("max_antes_cleared")
        if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
            return _failure(
                checked,
                "/manifest/max_antes_cleared",
                "positive integer",
                cap,
                "invalid ante cap",
                checked,
            )
        if final_antes_cleared != cap:
            return _failure(
                checked,
                "/antes_cleared",
                cap,
                final_antes_cleared,
                "ante-cap trace did not reach its declared cap",
                checked,
            )
    else:
        return _failure(
            checked,
            "/run_end/terminal_reason",
            "game_over or ante_cap",
            terminal_reason,
            "complete trace has an invalid terminal reason",
            checked,
        )
    recorded_antes = run_end.get("antes_cleared")
    if recorded_antes is not None and recorded_antes != final_antes_cleared:
        return _failure(
            checked,
            "/run_end/antes_cleared",
            final_antes_cleared,
            recorded_antes,
            "recorded and canonical ante metrics differ",
            checked,
        )
    return DifferentialReport(True, checked)


def _canonical_antes_cleared(canonical: dict[str, Any]) -> int:
    ante = canonical.get("ante_num")
    vouchers = canonical.get("used_vouchers")
    if isinstance(ante, bool) or not isinstance(ante, int) or ante < 1:
        return -1
    if isinstance(vouchers, dict) and all(isinstance(value, str) for value in vouchers):
        voucher_keys = vouchers.keys()
    elif isinstance(vouchers, list) and all(isinstance(value, str) for value in vouchers):
        voucher_keys = vouchers
    else:
        return -1
    reductions = sum(
        voucher in {"v_hieroglyph", "v_petroglyph"} for voucher in voucher_keys
    )
    return max(0, ante - 1 + reductions)


def _compare(authority: object, candidate: object, *, transition: int) -> DifferentialMismatch | None:
    return _compare_values(
        authority,
        candidate,
        transition=transition,
        message="canonical observed state differs",
    )


def _compare_values(
    authority: object,
    candidate: object,
    *,
    transition: int,
    message: str,
    path_prefix: str = "",
) -> DifferentialMismatch | None:
    difference = _first_difference(authority, candidate, path="")
    if difference is None:
        return None
    path, expected, actual = difference
    return DifferentialMismatch(
        transition=transition,
        path=f"{path_prefix}{path}" or "/",
        authority=expected,
        candidate=actual,
        message=message,
    )


def _complete_trace_bounds(
    rows: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], dict[str, Any]] | DifferentialReport:
    starts = [row for row in rows if row.get("event") == "run_start"]
    ends = [row for row in rows if row.get("event") == "run_end"]
    if len(starts) != 1 or len(ends) != 1:
        return _failure(0, "/", "one run_start and one run_end", (len(starts), len(ends)), "truncated trace")
    if ends[0] is not rows[-1]:
        return _failure(0, "/", "run_end as final row", rows[-1].get("event"), "invalid terminal trace")
    if not bool(ends[0].get("complete")):
        return _failure(0, "/run_end/complete", True, ends[0].get("complete"), "authority trace is incomplete")
    return starts[0], ends[0]


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
