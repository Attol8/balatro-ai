"""Strict public-only expert trajectories for behavior-coverage learning.

Authority traces contain private-capable frames, raw identifiers, commands, and
game seeds.  This module admits only typed policy-visible observations/actions,
safe capture identity, and recomputable public outcomes into a separate schema.
It deliberately carries no rollout targets, intent labels, or route labels.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
import re
import tempfile
from collections import Counter
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from enum import Enum
from pathlib import Path
from typing import Any

from balatro_ai_v2.actions import (
    DiscardCards,
    PlayCards,
    PublicAction,
    action_to_data,
    canonical_action_from_data,
    iter_legal_actions,
)
from balatro_ai_v2.backend import BackendCapabilities, BackendMetadata, RunSpec
from balatro_ai_v2.balatrobot.adapter import action_to_rpc, to_public_observation
from balatro_ai_v2.balatrobot.tracing import (
    CANONICAL_SCHEMA_VERSION,
    TRACE_SCHEMA_VERSION,
    TraceManifest,
    read_verified_trace,
)
from balatro_ai_v2.canonical import BalatroBotCanonicalizer
from balatro_ai_v2.policy import PublicHistoryStep
from balatro_ai_v2.policy_wire import POLICY_ACTION_CONTRACT
from balatro_ai_v2.public_codec import (
    public_observation_from_data,
    public_observation_to_data,
)
from balatro_ai_v2.public_state import Phase, PublicObservation
from balatro_ai_v2.strategy_context import (
    PublicStrategyContext,
    derive_public_strategy_context,
)

EXPERT_TRAJECTORY_SCHEMA_VERSION = 1
EXPERT_MODEL_MAX_ACTIONS = 512
EXPERT_MAX_EXACT_ACTIONS = 100_000
EXPERT_MAX_TRACE_CANDIDATES = 2_000_000
_OPAQUE_RUN_GROUP = re.compile(r"origin-[0-9a-f]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_REVISION = re.compile(r"[0-9a-f]{40}")
_BALATROBOT_BACKEND = "BalatroBot/LÖVE"
_REQUIRED_MOD_PREFIXES = ("balatrobot@", "Steamodded@", "Lovely@")
_ROW_ENVELOPE = {
    "schema_version",
    "run_id",
    "seq",
    "event",
    "previous_hash",
    "row_hash",
}
_TRANSITION_FIELDS = _ROW_ENVELOPE | {
    "before_canonical_digest",
    "action",
    "rpc_method",
    "rpc_params",
    "status",
    "rpc_observations",
    "error",
    "after",
    "public_after",
}
_RUN_END_FIELDS = _ROW_ENVELOPE | {
    "complete",
    "won",
    "antes_cleared",
    "ante",
    "round_no",
    "accepted_decisions",
    "rejected_decisions",
    "terminal_reason",
    "final_public_digest",
    "terminal_blind",
    "action_counts",
    "semantic_action_counts",
    "cards_played",
    "cards_discarded",
    "best_hand_score",
}


class ExpertTerminalEndpoint(str, Enum):
    GAME_OVER = "game_over"
    ANTE_CAP = "ante_cap"


@dataclass(frozen=True, slots=True)
class ExpertCaptureProtocol:
    repository_revision: str
    source_digest: str
    policy_identity_digest: str
    controller_config_digest: str
    model_digest: str | None
    backend_name: str
    backend_version: str
    adapter_version: str
    game_version: str
    runtime_version: str
    profile_mode: str
    deck: str
    stake: str
    mods: tuple[str, ...]
    max_decisions: int
    max_antes_cleared: int
    max_settle_polls: int
    wall_clock_limit_seconds: float | None
    launch_fast: bool
    launch_headless: bool
    sealed_seed_manifest_digest: str | None
    trace_schema_version: int = TRACE_SCHEMA_VERSION
    canonical_schema_version: int = CANONICAL_SCHEMA_VERSION
    action_contract: str = POLICY_ACTION_CONTRACT

    def __post_init__(self) -> None:
        if _GIT_REVISION.fullmatch(self.repository_revision) is None:
            raise ValueError("expert capture repository revision must be a Git SHA")
        if _SHA256.fullmatch(self.source_digest) is None:
            raise ValueError("expert capture source digest must be SHA-256")
        digest_fields = (
            self.policy_identity_digest,
            self.controller_config_digest,
        )
        if any(_SHA256.fullmatch(value) is None for value in digest_fields):
            raise ValueError("expert controller identity must use SHA-256")
        if (
            self.model_digest is not None
            and _SHA256.fullmatch(self.model_digest) is None
        ):
            raise ValueError("expert model digest must be null or SHA-256")
        if (
            self.sealed_seed_manifest_digest is not None
            and _SHA256.fullmatch(self.sealed_seed_manifest_digest) is None
        ):
            raise ValueError("expert sealed cohort digest must be null or SHA-256")
        string_fields = (
            self.backend_name,
            self.backend_version,
            self.adapter_version,
            self.game_version,
            self.runtime_version,
            self.deck,
            self.stake,
        )
        if any(not isinstance(value, str) or not value for value in string_fields):
            raise ValueError("expert capture identity strings must be nonempty")
        if self.profile_mode not in {"all_unlocked", "career"}:
            raise ValueError("expert capture profile mode is unsupported")
        if self.backend_name != _BALATROBOT_BACKEND:
            raise ValueError("expert capture backend is not BalatroBot authority")
        if (
            not isinstance(self.mods, tuple)
            or len(self.mods) != len(_REQUIRED_MOD_PREFIXES)
            or any(
                not isinstance(mod, str) or not mod.startswith(prefix)
                for mod, prefix in zip(self.mods, _REQUIRED_MOD_PREFIXES, strict=True)
            )
        ):
            raise ValueError(
                "expert capture mod identities are not the authority stack"
            )
        for name in ("max_decisions", "max_antes_cleared", "max_settle_polls"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"expert capture {name} must be positive")
        if self.wall_clock_limit_seconds is not None and (
            isinstance(self.wall_clock_limit_seconds, bool)
            or not isinstance(self.wall_clock_limit_seconds, int | float)
            or not math.isfinite(float(self.wall_clock_limit_seconds))
            or self.wall_clock_limit_seconds <= 0
        ):
            raise ValueError("expert wall-clock limit must be null or positive")
        if not isinstance(self.launch_fast, bool) or not isinstance(
            self.launch_headless, bool
        ):
            raise TypeError("expert launch flags must be boolean")
        if self.launch_fast:
            raise ValueError("expert capture cannot use the fast authority launcher")
        if (
            isinstance(self.trace_schema_version, bool)
            or not isinstance(self.trace_schema_version, int)
            or isinstance(self.canonical_schema_version, bool)
            or not isinstance(self.canonical_schema_version, int)
        ):
            raise TypeError("expert capture schema versions must be integers")
        if self.trace_schema_version != TRACE_SCHEMA_VERSION:
            raise ValueError("expert capture trace schema is unsupported")
        if self.canonical_schema_version != CANONICAL_SCHEMA_VERSION:
            raise ValueError("expert capture canonical schema is unsupported")
        if self.action_contract != POLICY_ACTION_CONTRACT:
            raise ValueError("expert capture action contract is unsupported")

    @property
    def protocol_digest(self) -> str:
        payload = _canonical_json(_capture_to_data(self, include_digest=False))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ExpertTransition:
    before: PublicObservation
    action: PublicAction
    after: PublicObservation
    candidates: tuple[PublicAction, ...]
    demonstrated_index: int

    def __post_init__(self) -> None:
        exact = exact_expert_candidates(self.before)
        if not exact:
            raise ValueError("expert transition has no public legal actions")
        if self.candidates != exact:
            raise ValueError(
                "expert candidates differ from the exact public action set"
            )
        if len(set(self.candidates)) != len(self.candidates):
            raise ValueError("expert candidate action set contains duplicates")
        if (
            isinstance(self.demonstrated_index, bool)
            or not isinstance(self.demonstrated_index, int)
            or not 0 <= self.demonstrated_index < len(self.candidates)
        ):
            raise ValueError("expert demonstrated index is out of range")
        if self.candidates[self.demonstrated_index] != self.action:
            raise ValueError("expert demonstrated index does not select the action")
        if sum(candidate == self.action for candidate in self.candidates) != 1:
            raise ValueError("expert action must occur exactly once in candidates")


@dataclass(frozen=True, slots=True)
class ExpertTrajectory:
    run_group: str
    capture: ExpertCaptureProtocol
    transitions: tuple[ExpertTransition, ...]
    terminal_endpoint: ExpertTerminalEndpoint
    won: bool
    terminal_ante: int
    antes_cleared: int
    best_hand_score: int
    long_horizon_censored: bool

    def __post_init__(self) -> None:
        if _OPAQUE_RUN_GROUP.fullmatch(self.run_group) is None:
            raise ValueError("expert run group must be opaque")
        if not self.transitions:
            raise ValueError("expert trajectory must contain at least one transition")
        if not isinstance(self.capture, ExpertCaptureProtocol):
            raise TypeError("expert trajectory capture protocol is invalid")
        if not isinstance(self.terminal_endpoint, ExpertTerminalEndpoint):
            raise TypeError("expert terminal endpoint is unsupported")
        if not isinstance(self.won, bool) or not isinstance(
            self.long_horizon_censored, bool
        ):
            raise TypeError("expert outcome flags must be boolean")
        for name in ("terminal_ante", "antes_cleared", "best_hand_score"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"expert {name} must be a non-negative integer")
        for previous, current in zip(
            self.transitions, self.transitions[1:], strict=False
        ):
            if previous.after != current.before:
                raise ValueError("expert trajectory observations are not contiguous")
        decks = {
            observation.deck
            for transition in self.transitions
            for observation in (transition.before, transition.after)
        }
        stakes = {
            observation.stake
            for transition in self.transitions
            for observation in (transition.before, transition.after)
        }
        if len(decks) != 1 or len(stakes) != 1:
            raise ValueError("expert trajectory deck or stake changes mid-run")
        if decks != {self.capture.deck} or stakes != {self.capture.stake}:
            raise ValueError("expert trajectory deck or stake disagrees with capture")

        final = self.transitions[-1].after
        if self.won != final.won:
            raise ValueError("expert won outcome disagrees with final public state")
        if (
            self.terminal_ante != final.ante
            or self.antes_cleared != final.antes_cleared
        ):
            raise ValueError("expert terminal metrics disagree with final public state")
        if self.best_hand_score != _best_hand_score(self.transitions):
            raise ValueError("expert best-hand score is not publicly reproducible")
        if self.terminal_endpoint == ExpertTerminalEndpoint.GAME_OVER:
            if not final.terminal or final.phase != Phase.GAME_OVER:
                raise ValueError("expert game-over endpoint is not terminal")
            if self.long_horizon_censored:
                raise ValueError("expert game-over outcome cannot be censored")
        elif self.terminal_endpoint == ExpertTerminalEndpoint.ANTE_CAP:
            if final.terminal or not self.long_horizon_censored:
                raise ValueError(
                    "expert ante-cap outcome must be nonterminal and censored"
                )


@dataclass(frozen=True, slots=True)
class ExpertBehaviorExample:
    run_group: str
    decision_index: int
    observation: PublicObservation
    history: tuple[PublicHistoryStep, ...]
    candidates: tuple[PublicAction, ...]
    demonstrated_index: int

    @property
    def tensor_supported(self) -> bool:
        return len(self.candidates) <= EXPERT_MODEL_MAX_ACTIONS

    @property
    def action_intents(self) -> tuple[None, ...]:
        return (None,) * len(self.candidates)

    @property
    def action_routes(self) -> tuple[None, ...]:
        return (None,) * len(self.candidates)

    @property
    def context(self) -> PublicStrategyContext:
        return derive_public_strategy_context(self.observation, self.history)


def trajectory_from_authority_trace(
    path: Path,
    *,
    run_group: str,
) -> ExpertTrajectory:
    """Import one verified authority trace through the public-only whitelist."""

    rows = read_verified_trace(path)
    _validate_source_row_fields(rows)
    manifests = [row for row in rows if row.get("event") == "manifest"]
    starts = [row for row in rows if row.get("event") == "run_start"]
    transitions = [row for row in rows if row.get("event") == "transition"]
    ends = [row for row in rows if row.get("event") == "run_end"]
    if len(manifests) != 1 or len(starts) != 1 or len(ends) != 1:
        raise ValueError("expert source trace has invalid run boundaries")
    if starts[0] is not rows[1] or ends[0] is not rows[-1]:
        raise ValueError("expert source trace boundaries are not ordered")
    if any(
        row.get("event") not in {"manifest", "run_start", "transition", "run_end"}
        for row in rows
    ):
        raise ValueError("expert source trace contains a failure event")

    manifest = manifests[0].get("manifest")
    if not isinstance(manifest, dict):
        raise TypeError("expert source manifest is missing")
    if set(manifest) != {field.name for field in dataclass_fields(TraceManifest)}:
        raise ValueError("expert source manifest has invalid fields")
    if manifest.get("run_id") != rows[0].get("run_id"):
        raise ValueError("expert source manifest run ID is inconsistent")
    capture = _capture_from_manifest(manifest)
    max_antes_cleared = capture.max_antes_cleared
    canonicalizer = BalatroBotCanonicalizer()
    current, current_canonical_digest = _verified_authority_public(
        starts[0].get("authority"),
        starts[0].get("public"),
        canonicalizer,
        max_settle_polls=capture.max_settle_polls,
    )
    admitted: list[ExpertTransition] = []
    action_counts: Counter[str] = Counter()
    cards_played = 0
    cards_discarded = 0
    candidate_total = 0
    for row in transitions:
        if current.terminal or current.antes_cleared >= max_antes_cleared:
            raise ValueError("expert source contains an action after its endpoint")
        if row.get("status") != "accepted":
            raise ValueError("expert source trace contains a non-accepted action")
        if row.get("error") is not None:
            raise ValueError("expert accepted transition contains an error")
        if row.get("before_canonical_digest") != current_canonical_digest:
            raise ValueError("expert source transition is not canonically contiguous")
        action = canonical_action_from_data(row.get("action"))
        expected_method, expected_params = action_to_rpc(action, current)
        if row.get("rpc_method") != expected_method or not _strictly_equal(
            row.get("rpc_params"), expected_params
        ):
            raise ValueError("expert source RPC does not match its public action")
        after, current_canonical_digest = _verified_authority_public(
            row.get("after"),
            row.get("public_after"),
            canonicalizer,
            max_settle_polls=capture.max_settle_polls,
        )
        candidates = exact_expert_candidates(current)
        candidate_total += len(candidates)
        if candidate_total > EXPERT_MAX_TRACE_CANDIDATES:
            raise ValueError("expert source exceeds the candidate resource limit")
        matching = [
            index for index, candidate in enumerate(candidates) if candidate == action
        ]
        if len(matching) != 1:
            raise ValueError("expert action is not unique in the public candidate set")
        admitted.append(
            ExpertTransition(
                before=current,
                action=action,
                after=after,
                candidates=candidates,
                demonstrated_index=matching[0],
            )
        )
        action_type = str(action_to_data(action)["type"])
        action_counts[action_type] += 1
        if isinstance(action, PlayCards):
            cards_played += len(action.cards)
        elif isinstance(action, DiscardCards):
            cards_discarded += len(action.cards)
        current = after

    end = ends[0]
    if end.get("complete") is not True:
        raise ValueError("incomplete source runs cannot produce expert trajectories")
    rejected_decisions = _nonnegative_integer(
        end.get("rejected_decisions"), "rejected_decisions"
    )
    if rejected_decisions != 0:
        raise ValueError("expert source run contains rejected decisions")
    accepted_decisions = _nonnegative_integer(
        end.get("accepted_decisions"), "accepted_decisions"
    )
    if accepted_decisions != len(admitted):
        raise ValueError("expert source decision count is inconsistent")
    if accepted_decisions > capture.max_decisions:
        raise ValueError("expert source exceeds its declared decision limit")
    if end.get("final_public_digest") != current.digest():
        raise ValueError("expert source final public digest is inconsistent")
    source_action_counts = _string_integer_counts(
        end.get("action_counts"), "action_counts"
    )
    _string_integer_counts(end.get("semantic_action_counts"), "semantic_action_counts")
    if not _strictly_equal(source_action_counts, dict(sorted(action_counts.items()))):
        raise ValueError("expert source action counts are inconsistent")
    source_cards_played = _nonnegative_integer(end.get("cards_played"), "cards_played")
    source_cards_discarded = _nonnegative_integer(
        end.get("cards_discarded"), "cards_discarded"
    )
    if source_cards_played != cards_played or source_cards_discarded != cards_discarded:
        raise ValueError("expert source card counts are inconsistent")
    if _nonnegative_integer(end.get("round_no"), "round_no") != current.round_no:
        raise ValueError("expert source terminal round is inconsistent")
    endpoint_raw = end.get("terminal_reason")
    try:
        endpoint = ExpertTerminalEndpoint(endpoint_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("expert source terminal reason is inadmissible") from exc
    won = _boolean(end.get("won"), "won")
    terminal_ante = _nonnegative_integer(end.get("ante"), "ante")
    antes_cleared = _nonnegative_integer(end.get("antes_cleared"), "antes_cleared")
    best_hand_score = _nonnegative_integer(
        end.get("best_hand_score"), "best_hand_score"
    )
    trajectory = ExpertTrajectory(
        run_group=run_group,
        capture=capture,
        transitions=tuple(admitted),
        terminal_endpoint=endpoint,
        won=won,
        terminal_ante=terminal_ante,
        antes_cleared=antes_cleared,
        best_hand_score=best_hand_score,
        long_horizon_censored=endpoint == ExpertTerminalEndpoint.ANTE_CAP,
    )
    if (
        endpoint == ExpertTerminalEndpoint.ANTE_CAP
        and current.antes_cleared != max_antes_cleared
    ):
        raise ValueError("expert source did not reach its declared ante cap")
    return trajectory


def expert_trajectory_to_data(trajectory: ExpertTrajectory) -> dict[str, object]:
    return {
        "schema_version": EXPERT_TRAJECTORY_SCHEMA_VERSION,
        "run_group": trajectory.run_group,
        "capture": _capture_to_data(trajectory.capture, include_digest=True),
        "transitions": [
            {
                "before": public_observation_to_data(transition.before),
                "action": action_to_data(transition.action),
                "after": public_observation_to_data(transition.after),
                "candidates": [
                    action_to_data(candidate) for candidate in transition.candidates
                ],
                "demonstrated_index": transition.demonstrated_index,
            }
            for transition in trajectory.transitions
        ],
        "outcome": {
            "terminal_endpoint": trajectory.terminal_endpoint.value,
            "won": trajectory.won,
            "terminal_ante": trajectory.terminal_ante,
            "antes_cleared": trajectory.antes_cleared,
            "best_hand_score": trajectory.best_hand_score,
            "long_horizon_censored": trajectory.long_horizon_censored,
        },
    }


def expert_trajectory_from_data(data: object) -> ExpertTrajectory:
    required = {"schema_version", "run_group", "capture", "transitions", "outcome"}
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("expert trajectory has invalid fields")
    if data["schema_version"] != EXPERT_TRAJECTORY_SCHEMA_VERSION:
        raise ValueError("expert trajectory schema is unsupported")
    raw_transitions = data["transitions"]
    if not isinstance(raw_transitions, list):
        raise TypeError("expert transitions must be an array")
    transitions: list[ExpertTransition] = []
    for raw in raw_transitions:
        fields = {"before", "action", "after", "candidates", "demonstrated_index"}
        if not isinstance(raw, dict) or set(raw) != fields:
            raise ValueError("expert transition has invalid fields")
        raw_candidates = raw["candidates"]
        if not isinstance(raw_candidates, list):
            raise TypeError("expert candidates must be an array")
        transitions.append(
            ExpertTransition(
                before=public_observation_from_data(raw["before"]),
                action=canonical_action_from_data(raw["action"]),
                after=public_observation_from_data(raw["after"]),
                candidates=tuple(
                    canonical_action_from_data(candidate)
                    for candidate in raw_candidates
                ),
                demonstrated_index=_nonnegative_integer(
                    raw["demonstrated_index"], "demonstrated_index"
                ),
            )
        )
    outcome = data["outcome"]
    outcome_fields = {
        "terminal_endpoint",
        "won",
        "terminal_ante",
        "antes_cleared",
        "best_hand_score",
        "long_horizon_censored",
    }
    if not isinstance(outcome, dict) or set(outcome) != outcome_fields:
        raise ValueError("expert trajectory outcome has invalid fields")
    try:
        endpoint = ExpertTerminalEndpoint(outcome["terminal_endpoint"])
    except (TypeError, ValueError) as exc:
        raise ValueError("expert trajectory endpoint is unsupported") from exc
    return ExpertTrajectory(
        run_group=_string(data["run_group"], "run_group"),
        capture=_capture_from_data(data["capture"]),
        transitions=tuple(transitions),
        terminal_endpoint=endpoint,
        won=_boolean(outcome["won"], "won"),
        terminal_ante=_nonnegative_integer(outcome["terminal_ante"], "terminal_ante"),
        antes_cleared=_nonnegative_integer(outcome["antes_cleared"], "antes_cleared"),
        best_hand_score=_nonnegative_integer(
            outcome["best_hand_score"], "best_hand_score"
        ),
        long_horizon_censored=_boolean(
            outcome["long_horizon_censored"], "long_horizon_censored"
        ),
    )


def expert_trajectories_bytes(trajectories: tuple[ExpertTrajectory, ...]) -> bytes:
    _validate_corpus(trajectories)
    return b"".join(
        (_canonical_json(expert_trajectory_to_data(trajectory)) + "\n").encode("utf-8")
        for trajectory in trajectories
    )


def expert_trajectories_digest(trajectories: tuple[ExpertTrajectory, ...]) -> str:
    return hashlib.sha256(expert_trajectories_bytes(trajectories)).hexdigest()


def write_expert_trajectories(
    path: Path,
    trajectories: tuple[ExpertTrajectory, ...],
) -> str:
    payload = expert_trajectories_bytes(trajectories)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest()


def read_expert_trajectories(path: Path) -> tuple[ExpertTrajectory, ...]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        trajectories = tuple(
            expert_trajectory_from_data(
                json.loads(line, object_pairs_hook=_reject_duplicate_json_keys)
            )
            for line in text.splitlines()
            if line.strip()
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("expert trajectory dataset is invalid JSONL") from exc
    _validate_corpus(trajectories)
    if raw != expert_trajectories_bytes(trajectories):
        raise ValueError("expert trajectory dataset is not canonical JSONL")
    return trajectories


def materialize_behavior_examples(
    trajectories: tuple[ExpertTrajectory, ...],
) -> tuple[ExpertBehaviorExample, ...]:
    _validate_corpus(trajectories)
    examples: list[ExpertBehaviorExample] = []
    for trajectory in trajectories:
        history: list[PublicHistoryStep] = []
        for decision_index, transition in enumerate(trajectory.transitions):
            examples.append(
                ExpertBehaviorExample(
                    run_group=trajectory.run_group,
                    decision_index=decision_index,
                    observation=transition.before,
                    history=tuple(history),
                    candidates=transition.candidates,
                    demonstrated_index=transition.demonstrated_index,
                )
            )
            history.append(
                PublicHistoryStep(
                    before=transition.before,
                    action=transition.action,
                    after=transition.after,
                )
            )
    return tuple(examples)


def split_expert_trajectories(
    trajectories: tuple[ExpertTrajectory, ...],
    *,
    split_nonce: str,
    train_fraction: float = 0.8,
    calibration_fraction: float = 0.1,
) -> dict[str, tuple[ExpertTrajectory, ...]]:
    _validate_corpus(trajectories)
    if not isinstance(split_nonce, str) or not split_nonce:
        raise ValueError("expert split nonce must be nonempty")
    if (
        isinstance(train_fraction, bool)
        or isinstance(calibration_fraction, bool)
        or not all(
            isinstance(value, int | float) and math.isfinite(float(value))
            for value in (train_fraction, calibration_fraction)
        )
        or not 0 <= train_fraction <= 1
        or not 0 <= calibration_fraction <= 1
        or train_fraction + calibration_fraction > 1
    ):
        raise ValueError("expert split fractions are invalid")
    ordered = sorted(
        trajectories,
        key=lambda trajectory: hashlib.sha256(
            f"{split_nonce}\0{trajectory.run_group}".encode()
        ).digest(),
    )
    train_end = int(len(ordered) * train_fraction)
    calibration_end = train_end + int(len(ordered) * calibration_fraction)
    return {
        "train": tuple(ordered[:train_end]),
        "calibration": tuple(ordered[train_end:calibration_end]),
        "holdout": tuple(ordered[calibration_end:]),
    }


def _capture_from_manifest(manifest: dict[str, Any]) -> ExpertCaptureProtocol:
    if manifest.get("repository_dirty") is not False:
        raise ValueError("expert capture repository must be clean")
    if manifest.get("trace_schema_version") != TRACE_SCHEMA_VERSION:
        raise ValueError("expert capture requires the current authority trace schema")
    action_contract = _string(manifest.get("action_contract"), "action_contract")
    if action_contract != POLICY_ACTION_CONTRACT:
        raise ValueError("expert capture action contract is unsupported")
    _sha256_string(manifest.get("config_digest"), "source config digest")
    policy_name = _string(manifest.get("policy_name"), "policy_name")
    inference_budget = _string(manifest.get("inference_budget"), "inference_budget")
    model_digest = _optional_sha256(manifest.get("model_digest"), "model digest")
    max_decisions = _positive_integer(manifest.get("max_decisions"), "max_decisions")
    max_antes_cleared = _positive_integer(
        manifest.get("max_antes_cleared"), "max_antes_cleared"
    )
    max_settle_polls = _positive_integer(
        manifest.get("max_settle_polls"), "max_settle_polls"
    )
    launch_fast = _boolean(manifest.get("launch_fast"), "launch_fast")
    launch_headless = _boolean(manifest.get("launch_headless"), "launch_headless")
    profile_mode = _string(manifest.get("profile_mode"), "profile_mode")
    wall_clock_limit = manifest.get("wall_clock_limit_seconds")
    if wall_clock_limit is not None and (
        isinstance(wall_clock_limit, bool)
        or not isinstance(wall_clock_limit, int | float)
    ):
        raise TypeError("expert wall-clock limit must be null or numeric")
    sealed_digest = _optional_sha256(
        manifest.get("sealed_seed_manifest_digest"), "sealed cohort digest"
    )
    backend = manifest.get("backend")
    backend_fields = {field.name for field in dataclass_fields(BackendMetadata)}
    if not isinstance(backend, dict) or set(backend) != backend_fields:
        raise TypeError("expert capture backend metadata is missing")
    capabilities = backend.get("capabilities")
    capability_fields = {field.name for field in dataclass_fields(BackendCapabilities)}
    expected_capabilities = {
        "authoritative": True,
        "complete_private_state": False,
        "snapshot": False,
        "restore": False,
        "batch_rollout": False,
    }
    if not isinstance(capabilities, dict) or set(capabilities) != capability_fields:
        raise TypeError("expert capture backend capabilities are malformed")
    if not _strictly_equal(capabilities, expected_capabilities):
        raise ValueError("expert capture backend is not authoritative")
    run = manifest.get("run")
    run_fields = {field.name for field in dataclass_fields(RunSpec)}
    if not isinstance(run, dict) or set(run) != run_fields:
        raise TypeError("expert capture run specification is malformed")
    _string(run.get("seed"), "source run seed")
    mods = manifest.get("mods")
    if not isinstance(mods, list):
        raise TypeError("expert capture mods must be an array")
    controller_config_digest = hashlib.sha256(
        _canonical_json(
            {
                "policy_name": policy_name,
                "model_digest": model_digest,
                "inference_budget": inference_budget,
                "max_decisions": max_decisions,
                "max_antes_cleared": max_antes_cleared,
                "max_settle_polls": max_settle_polls,
                "wall_clock_limit_seconds": wall_clock_limit,
                "launch_fast": launch_fast,
                "launch_headless": launch_headless,
                "profile_mode": profile_mode,
                "action_contract": action_contract,
            }
        ).encode()
    ).hexdigest()
    return ExpertCaptureProtocol(
        repository_revision=_string(manifest.get("repository_revision"), "revision"),
        source_digest=_string(manifest.get("source_digest"), "source_digest"),
        policy_identity_digest=hashlib.sha256(policy_name.encode()).hexdigest(),
        controller_config_digest=controller_config_digest,
        model_digest=model_digest,
        backend_name=_string(backend.get("backend_name"), "backend_name"),
        backend_version=_string(backend.get("backend_version"), "backend_version"),
        adapter_version=_string(backend.get("adapter_version"), "adapter_version"),
        game_version=_string(backend.get("game_version"), "game_version"),
        runtime_version=_string(backend.get("runtime_version"), "runtime_version"),
        profile_mode=profile_mode,
        deck=_string(run.get("deck"), "deck"),
        stake=_string(run.get("stake"), "stake"),
        mods=tuple(_string(mod, "mod") for mod in mods),
        max_decisions=max_decisions,
        max_antes_cleared=max_antes_cleared,
        max_settle_polls=max_settle_polls,
        wall_clock_limit_seconds=(
            None if wall_clock_limit is None else float(wall_clock_limit)
        ),
        launch_fast=launch_fast,
        launch_headless=launch_headless,
        sealed_seed_manifest_digest=sealed_digest,
        trace_schema_version=_nonnegative_integer(
            manifest.get("trace_schema_version"), "trace_schema_version"
        ),
        canonical_schema_version=_nonnegative_integer(
            manifest.get("canonical_schema_version"), "canonical_schema_version"
        ),
        action_contract=action_contract,
    )


def _validate_source_row_fields(rows: tuple[dict[str, Any], ...]) -> None:
    for row in rows:
        event = row.get("event")
        actual = set(row)
        if event == "manifest":
            expected = _ROW_ENVELOPE | {"manifest"}
        elif event == "run_start":
            expected = _ROW_ENVELOPE | {"authority", "public"}
        elif event == "transition":
            if actual != _TRANSITION_FIELDS and actual != _TRANSITION_FIELDS | {
                "capacity"
            }:
                raise ValueError("expert source transition has invalid fields")
            continue
        elif event == "run_end":
            expected = _RUN_END_FIELDS
        else:
            raise ValueError("expert source trace contains an unsupported event")
        if actual != expected:
            raise ValueError(f"expert source {event} row has invalid fields")


def _verified_authority_public(
    authority_data: object,
    public_data: object,
    canonicalizer: BalatroBotCanonicalizer,
    *,
    max_settle_polls: int,
) -> tuple[PublicObservation, str]:
    fields = {
        "raw",
        "canonical",
        "raw_digest",
        "canonical_digest",
        "settled",
        "poll_count",
    }
    if not isinstance(authority_data, dict) or set(authority_data) != fields:
        raise ValueError("expert source authority observation has invalid fields")
    if authority_data["settled"] is not True:
        raise ValueError("expert source authority observation is unsettled")
    poll_count = _nonnegative_integer(authority_data["poll_count"], "poll_count")
    if poll_count > max_settle_polls:
        raise ValueError("expert source exceeds its declared settle-poll limit")
    raw = authority_data["raw"]
    if not isinstance(raw, dict):
        raise TypeError("expert source raw authority state is invalid")
    verified = canonicalizer.canonicalize(raw)
    if (
        not _strictly_equal(authority_data["canonical"], verified.canonical)
        or authority_data["raw_digest"] != verified.raw_digest
        or authority_data["canonical_digest"] != verified.canonical_digest
    ):
        raise ValueError("expert source authority projection is inconsistent")
    derived_public = to_public_observation(raw)
    stored_public = public_observation_from_data(public_data)
    if derived_public != stored_public:
        raise ValueError("expert source stored public state disagrees with authority")
    return derived_public, verified.canonical_digest


def _capture_to_data(
    capture: ExpertCaptureProtocol,
    *,
    include_digest: bool,
) -> dict[str, object]:
    data: dict[str, object] = {
        "repository_revision": capture.repository_revision,
        "source_digest": capture.source_digest,
        "policy_identity_digest": capture.policy_identity_digest,
        "controller_config_digest": capture.controller_config_digest,
        "model_digest": capture.model_digest,
        "backend_name": capture.backend_name,
        "backend_version": capture.backend_version,
        "adapter_version": capture.adapter_version,
        "game_version": capture.game_version,
        "runtime_version": capture.runtime_version,
        "profile_mode": capture.profile_mode,
        "deck": capture.deck,
        "stake": capture.stake,
        "mods": list(capture.mods),
        "max_decisions": capture.max_decisions,
        "max_antes_cleared": capture.max_antes_cleared,
        "max_settle_polls": capture.max_settle_polls,
        "wall_clock_limit_seconds": capture.wall_clock_limit_seconds,
        "launch_fast": capture.launch_fast,
        "launch_headless": capture.launch_headless,
        "sealed_seed_manifest_digest": capture.sealed_seed_manifest_digest,
        "trace_schema_version": capture.trace_schema_version,
        "canonical_schema_version": capture.canonical_schema_version,
        "action_contract": capture.action_contract,
    }
    if include_digest:
        data["protocol_digest"] = capture.protocol_digest
    return data


def _capture_from_data(data: object) -> ExpertCaptureProtocol:
    fields = {
        "repository_revision",
        "source_digest",
        "policy_identity_digest",
        "controller_config_digest",
        "model_digest",
        "backend_name",
        "backend_version",
        "adapter_version",
        "game_version",
        "runtime_version",
        "profile_mode",
        "deck",
        "stake",
        "mods",
        "max_decisions",
        "max_antes_cleared",
        "max_settle_polls",
        "wall_clock_limit_seconds",
        "launch_fast",
        "launch_headless",
        "sealed_seed_manifest_digest",
        "trace_schema_version",
        "canonical_schema_version",
        "action_contract",
        "protocol_digest",
    }
    if not isinstance(data, dict) or set(data) != fields:
        raise ValueError("expert capture protocol has invalid fields")
    mods = data["mods"]
    if not isinstance(mods, list):
        raise TypeError("expert capture mods must be an array")
    capture = ExpertCaptureProtocol(
        repository_revision=_string(data["repository_revision"], "revision"),
        source_digest=_string(data["source_digest"], "source_digest"),
        policy_identity_digest=_sha256_string(
            data["policy_identity_digest"], "policy identity digest"
        ),
        controller_config_digest=_sha256_string(
            data["controller_config_digest"], "controller config digest"
        ),
        model_digest=_optional_sha256(data["model_digest"], "model digest"),
        backend_name=_string(data["backend_name"], "backend_name"),
        backend_version=_string(data["backend_version"], "backend_version"),
        adapter_version=_string(data["adapter_version"], "adapter_version"),
        game_version=_string(data["game_version"], "game_version"),
        runtime_version=_string(data["runtime_version"], "runtime_version"),
        profile_mode=_string(data["profile_mode"], "profile_mode"),
        deck=_string(data["deck"], "deck"),
        stake=_string(data["stake"], "stake"),
        mods=tuple(_string(mod, "mod") for mod in mods),
        max_decisions=_positive_integer(data["max_decisions"], "max_decisions"),
        max_antes_cleared=_positive_integer(
            data["max_antes_cleared"], "max_antes_cleared"
        ),
        max_settle_polls=_positive_integer(
            data["max_settle_polls"], "max_settle_polls"
        ),
        wall_clock_limit_seconds=_optional_positive_number(
            data["wall_clock_limit_seconds"], "wall_clock_limit_seconds"
        ),
        launch_fast=_boolean(data["launch_fast"], "launch_fast"),
        launch_headless=_boolean(data["launch_headless"], "launch_headless"),
        sealed_seed_manifest_digest=_optional_sha256(
            data["sealed_seed_manifest_digest"], "sealed cohort digest"
        ),
        trace_schema_version=_nonnegative_integer(
            data["trace_schema_version"], "trace_schema_version"
        ),
        canonical_schema_version=_nonnegative_integer(
            data["canonical_schema_version"], "canonical_schema_version"
        ),
        action_contract=_string(data["action_contract"], "action_contract"),
    )
    if data["protocol_digest"] != capture.protocol_digest:
        raise ValueError("expert capture protocol digest mismatch")
    return capture


def _validate_corpus(trajectories: tuple[ExpertTrajectory, ...]) -> None:
    if not trajectories:
        raise ValueError("expert trajectory dataset is empty")
    groups = [trajectory.run_group for trajectory in trajectories]
    if len(set(groups)) != len(groups):
        raise ValueError("expert trajectory dataset repeats a run group")
    protocols = {trajectory.capture.protocol_digest for trajectory in trajectories}
    if len(protocols) != 1:
        raise ValueError("expert trajectory dataset mixes capture protocols")


def _best_hand_score(transitions: tuple[ExpertTransition, ...]) -> int:
    best = 0
    for transition in transitions:
        if isinstance(transition.action, PlayCards):
            best = max(
                best,
                max(0, transition.after.round.chips - transition.before.round.chips),
            )
    return best


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _strictly_equal(left: object, right: object) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        return set(left) == set(right) and all(
            _strictly_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list | tuple) and isinstance(right, list | tuple):
        return len(left) == len(right) and all(
            _strictly_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return bool(left == right)


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"expert {name} must be a nonempty string")
    return value


def _sha256_string(value: object, name: str) -> str:
    result = _string(value, name)
    if _SHA256.fullmatch(result) is None:
        raise ValueError(f"expert {name} must be SHA-256")
    return result


def _optional_sha256(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _sha256_string(value, name)


def _optional_positive_number(value: object, name: str) -> float | None:
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise ValueError(f"expert {name} must be null or positive")
    return float(value)


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"expert {name} must be boolean")
    return value


def _nonnegative_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"expert {name} must be a non-negative integer")
    return value


def _positive_integer(value: object, name: str) -> int:
    result = _nonnegative_integer(value, name)
    if result < 1:
        raise ValueError(f"expert {name} must be positive")
    return result


def exact_expert_candidates(
    observation: PublicObservation,
) -> tuple[PublicAction, ...]:
    """Enumerate an exact action set within the admission resource ceiling."""

    candidates = tuple(
        itertools.islice(iter_legal_actions(observation), EXPERT_MAX_EXACT_ACTIONS + 1)
    )
    if len(candidates) > EXPERT_MAX_EXACT_ACTIONS:
        raise ValueError("expert decision exceeds the exact-action resource limit")
    return candidates


def _string_integer_counts(value: object, name: str) -> dict[str, int]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str)
        or not key
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count < 0
        for key, count in value.items()
    ):
        raise TypeError(f"expert {name} must contain string/integer counts")
    return value


__all__ = [
    "EXPERT_MAX_EXACT_ACTIONS",
    "EXPERT_MAX_TRACE_CANDIDATES",
    "EXPERT_MODEL_MAX_ACTIONS",
    "EXPERT_TRAJECTORY_SCHEMA_VERSION",
    "ExpertBehaviorExample",
    "ExpertCaptureProtocol",
    "ExpertTerminalEndpoint",
    "ExpertTrajectory",
    "ExpertTransition",
    "expert_trajectories_bytes",
    "expert_trajectories_digest",
    "exact_expert_candidates",
    "expert_trajectory_from_data",
    "expert_trajectory_to_data",
    "materialize_behavior_examples",
    "read_expert_trajectories",
    "split_expert_trajectories",
    "trajectory_from_authority_trace",
    "write_expert_trajectories",
]
