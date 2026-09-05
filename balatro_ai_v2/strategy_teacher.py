"""Public-only determinized-search teacher records for expert iteration.

The evaluator parent may inspect sampled candidate outcomes, but the persisted
dataset contains only typed public observations/actions, public strategy
intents, scalar outcome targets, and opaque originating-run groups.  A record
cannot be constructed until its originating run completed.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from balatro_ai_v2.actions import (
    PublicAction,
    action_to_data,
    canonical_action_from_data,
    is_legal,
)
from balatro_ai_v2.public_codec import (
    public_observation_from_data,
    public_observation_to_data,
)
from balatro_ai_v2.public_state import PublicObservation
from balatro_ai_v2.strategy_context import PublicStrategyContext
from balatro_ai_v2.strategy_engine import RunGoal, derive_engine_state
from balatro_ai_v2.strategy_options import StrategyIntent


STRATEGY_TEACHER_SCHEMA_VERSION = 7
_RUN_GROUP = re.compile(r"origin-[0-9a-f]{32}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class StrategyTargetEndpoint(str, Enum):
    """Why a sample stopped and which long-horizon targets are exact."""

    HORIZON = "horizon"
    VICTORY = "victory"
    DEATH = "death"
    CENSORED = "censored"


@dataclass(frozen=True, slots=True)
class StrategyRolloutTarget:
    """One sampled public outcome, stripped of the sampled state itself."""

    current_blind_clear: float
    next_boss_clear: float
    ante8_win: float | None
    endless_ante: float | None
    log_score: float | None
    endpoint: StrategyTargetEndpoint = StrategyTargetEndpoint.HORIZON
    search_utility: float = 0.0

    def __post_init__(self) -> None:
        for name in ("current_blind_clear", "next_boss_clear"):
            value = getattr(self, name)
            if not math.isfinite(value) or value not in {0.0, 1.0}:
                raise ValueError(f"{name} must be a binary finite target")
        if self.ante8_win is not None and (
            not math.isfinite(self.ante8_win) or self.ante8_win not in {0.0, 1.0}
        ):
            raise ValueError("ante8_win must be null or a binary finite target")
        for name in ("endless_ante", "log_score"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{name} must be null or a finite non-negative target")
        if not math.isfinite(self.search_utility) or self.search_utility < 0:
            raise ValueError("search utility must be finite and non-negative")
        if not isinstance(self.endpoint, StrategyTargetEndpoint):
            raise ValueError("strategy target endpoint is unsupported")
        if self.endpoint == StrategyTargetEndpoint.CENSORED and any(
            value is not None
            for value in (self.ante8_win, self.endless_ante, self.log_score)
        ):
            raise ValueError("censored samples cannot carry exact long targets")


@dataclass(frozen=True, slots=True)
class StrategyTeacherCandidate:
    action: PublicAction
    intent: StrategyIntent | None
    samples: tuple[StrategyRolloutTarget, ...]

    def __post_init__(self) -> None:
        if not self.samples:
            raise ValueError("teacher candidate needs at least one complete sample")


@dataclass(frozen=True, slots=True)
class StrategyTeacherDraft:
    """In-memory decision waiting for its complete-run outcome."""

    observation: PublicObservation
    candidates: tuple[StrategyTeacherCandidate, ...]
    selected_index: int
    baseline_index: int
    goal: RunGoal
    teacher_config_digest: str
    context: PublicStrategyContext = PublicStrategyContext()
    candidate_space_size: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.context, PublicStrategyContext):
            raise ValueError("strategy teacher context has the wrong type")
        if self.candidate_space_size < 0 or (
            self.candidate_space_size
            and self.candidate_space_size < len(self.candidates)
        ):
            raise ValueError("teacher candidate space size is invalid")
        _validate_decision(
            self.observation,
            self.candidates,
            self.selected_index,
            self.baseline_index,
            self.goal,
        )
        _validate_digest(self.teacher_config_digest)

    def finalize(
        self,
        *,
        run_group: str,
        decision_index: int,
        run_complete: bool,
        run_won: bool,
        terminal_ante: int,
        best_hand_score: int,
    ) -> StrategyTeacherRecord:
        if not run_complete:
            raise ValueError(
                "incomplete originating runs cannot produce teacher records"
            )
        if decision_index < 0 or terminal_ante < 0 or best_hand_score < 0:
            raise ValueError("teacher run outcomes must be non-negative")
        return StrategyTeacherRecord(
            run_group=run_group,
            decision_index=decision_index,
            observation=self.observation,
            candidates=self.candidates,
            selected_index=self.selected_index,
            baseline_index=self.baseline_index,
            goal=self.goal,
            teacher_config_digest=self.teacher_config_digest,
            context=self.context,
            candidate_space_size=self.candidate_space_size or len(self.candidates),
            run_won=run_won,
            terminal_ante=terminal_ante,
            run_log_score=math.log10(max(1, best_hand_score)),
        )


@dataclass(frozen=True, slots=True)
class StrategyTeacherRecord:
    run_group: str
    decision_index: int
    observation: PublicObservation
    candidates: tuple[StrategyTeacherCandidate, ...]
    selected_index: int
    baseline_index: int
    goal: RunGoal
    teacher_config_digest: str
    run_won: bool
    terminal_ante: int
    run_log_score: float
    context: PublicStrategyContext = PublicStrategyContext()
    candidate_space_size: int = 0

    def __post_init__(self) -> None:
        if _RUN_GROUP.fullmatch(self.run_group) is None:
            raise ValueError("run_group must be an opaque origin identifier")
        if not isinstance(self.context, PublicStrategyContext):
            raise ValueError("strategy teacher context has the wrong type")
        if self.candidate_space_size < len(self.candidates):
            raise ValueError("teacher candidate space size is invalid")
        if self.decision_index < 0 or self.terminal_ante < 0:
            raise ValueError("teacher indexes and terminal ante must be non-negative")
        if not math.isfinite(self.run_log_score) or self.run_log_score < 0:
            raise ValueError("run log score must be finite and non-negative")
        _validate_decision(
            self.observation,
            self.candidates,
            self.selected_index,
            self.baseline_index,
            self.goal,
        )
        _validate_digest(self.teacher_config_digest)


def teacher_record_to_data(record: StrategyTeacherRecord) -> dict[str, object]:
    return {
        "schema_version": STRATEGY_TEACHER_SCHEMA_VERSION,
        "run_group": record.run_group,
        "decision_index": record.decision_index,
        "observation": public_observation_to_data(record.observation),
        "context": {
            "version": record.context.version,
            "current_shop_actions": record.context.current_shop_actions,
            "current_shop_has_joker_sale": record.context.current_shop_has_joker_sale,
            "prior_shop_has_joker_sale": record.context.prior_shop_has_joker_sale,
            "loyalty_remaining": record.context.loyalty_remaining,
            "best_hand_log_score": record.context.best_hand_log_score,
            "incoming_intent": (
                record.context.incoming_intent.value
                if record.context.incoming_intent is not None
                else None
            ),
        },
        "candidate_space_size": record.candidate_space_size,
        "candidates": [
            {
                "action": action_to_data(candidate.action),
                "intent": candidate.intent.value
                if candidate.intent is not None
                else None,
                "samples": [
                    {
                        "current_blind_clear": sample.current_blind_clear,
                        "next_boss_clear": sample.next_boss_clear,
                        "ante8_win": sample.ante8_win,
                        "endless_ante": sample.endless_ante,
                        "log_score": sample.log_score,
                        "search_utility": sample.search_utility,
                        "endpoint": sample.endpoint.value,
                    }
                    for sample in candidate.samples
                ],
            }
            for candidate in record.candidates
        ],
        "selected_index": record.selected_index,
        "baseline_index": record.baseline_index,
        "goal": record.goal.value,
        "teacher_config_digest": record.teacher_config_digest,
        "run_outcome": {
            "won": record.run_won,
            "terminal_ante": record.terminal_ante,
            "log_score": record.run_log_score,
        },
    }


def teacher_record_from_data(data: object) -> StrategyTeacherRecord:
    required = {
        "schema_version",
        "run_group",
        "decision_index",
        "observation",
        "context",
        "candidate_space_size",
        "candidates",
        "selected_index",
        "baseline_index",
        "goal",
        "teacher_config_digest",
        "run_outcome",
    }
    if not isinstance(data, dict) or set(data) != required:
        raise ValueError("strategy teacher record has invalid fields")
    if data["schema_version"] != STRATEGY_TEACHER_SCHEMA_VERSION:
        raise ValueError("strategy teacher schema version is unsupported")
    raw_candidates = data["candidates"]
    if not isinstance(raw_candidates, list):
        raise ValueError("strategy teacher candidates must be an array")
    candidates: list[StrategyTeacherCandidate] = []
    for raw_candidate in raw_candidates:
        if not isinstance(raw_candidate, dict) or set(raw_candidate) != {
            "action",
            "intent",
            "samples",
        }:
            raise ValueError("strategy teacher candidate has invalid fields")
        raw_intent = raw_candidate["intent"]
        if raw_intent is not None and not isinstance(raw_intent, str):
            raise ValueError("strategy teacher intent must be a string or null")
        try:
            intent = StrategyIntent(raw_intent) if raw_intent is not None else None
        except ValueError as exc:
            raise ValueError("strategy teacher intent is unsupported") from exc
        raw_samples = raw_candidate["samples"]
        if not isinstance(raw_samples, list):
            raise ValueError("strategy teacher samples must be an array")
        samples: list[StrategyRolloutTarget] = []
        for raw_sample in raw_samples:
            if not isinstance(raw_sample, dict) or set(raw_sample) != {
                "current_blind_clear",
                "next_boss_clear",
                "ante8_win",
                "endless_ante",
                "log_score",
                "search_utility",
                "endpoint",
            }:
                raise ValueError("strategy rollout target has invalid fields")
            try:
                samples.append(
                    StrategyRolloutTarget(
                        current_blind_clear=float(raw_sample["current_blind_clear"]),
                        next_boss_clear=float(raw_sample["next_boss_clear"]),
                        ante8_win=_optional_float(raw_sample["ante8_win"]),
                        endless_ante=_optional_float(raw_sample["endless_ante"]),
                        log_score=_optional_float(raw_sample["log_score"]),
                        search_utility=float(raw_sample["search_utility"]),
                        endpoint=StrategyTargetEndpoint(raw_sample["endpoint"]),
                    )
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("strategy rollout target is invalid") from exc
        candidates.append(
            StrategyTeacherCandidate(
                action=canonical_action_from_data(raw_candidate["action"]),
                intent=intent,
                samples=tuple(samples),
            )
        )
    outcome = data["run_outcome"]
    if not isinstance(outcome, dict) or set(outcome) != {
        "won",
        "terminal_ante",
        "log_score",
    }:
        raise ValueError("strategy teacher run outcome has invalid fields")
    if not isinstance(outcome["won"], bool):
        raise ValueError("strategy teacher won target must be boolean")
    raw_context = data["context"]
    if not isinstance(raw_context, dict) or set(raw_context) != {
        "version",
        "current_shop_actions",
        "current_shop_has_joker_sale",
        "prior_shop_has_joker_sale",
        "loyalty_remaining",
        "best_hand_log_score",
        "incoming_intent",
    }:
        raise ValueError("strategy teacher context has invalid fields")
    raw_incoming_intent = raw_context["incoming_intent"]
    if raw_incoming_intent is not None and not isinstance(raw_incoming_intent, str):
        raise ValueError("incoming strategy intent must be a string or null")
    for name in ("current_shop_has_joker_sale", "prior_shop_has_joker_sale"):
        if not isinstance(raw_context[name], bool):
            raise ValueError("strategy teacher context flags must be boolean")
    try:
        goal = RunGoal(data["goal"])
        context = PublicStrategyContext(
            version=int(raw_context["version"]),
            current_shop_actions=int(raw_context["current_shop_actions"]),
            current_shop_has_joker_sale=raw_context["current_shop_has_joker_sale"],
            prior_shop_has_joker_sale=raw_context["prior_shop_has_joker_sale"],
            loyalty_remaining=(
                int(raw_context["loyalty_remaining"])
                if raw_context["loyalty_remaining"] is not None
                else None
            ),
            best_hand_log_score=float(raw_context["best_hand_log_score"]),
            incoming_intent=(
                StrategyIntent(raw_incoming_intent)
                if raw_incoming_intent is not None
                else None
            ),
        )
        return StrategyTeacherRecord(
            run_group=str(data["run_group"]),
            decision_index=int(data["decision_index"]),
            observation=public_observation_from_data(data["observation"]),
            candidates=tuple(candidates),
            selected_index=int(data["selected_index"]),
            baseline_index=int(data["baseline_index"]),
            goal=goal,
            teacher_config_digest=str(data["teacher_config_digest"]),
            run_won=outcome["won"],
            terminal_ante=int(outcome["terminal_ante"]),
            run_log_score=float(outcome["log_score"]),
            context=context,
            candidate_space_size=int(data["candidate_space_size"]),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("strategy teacher record is invalid") from exc


def write_teacher_records(
    path: Path, records: tuple[StrategyTeacherRecord, ...]
) -> str:
    if not records:
        raise ValueError("strategy teacher dataset is empty")
    if len({record.teacher_config_digest for record in records}) != 1:
        raise ValueError("strategy teacher dataset mixes teacher configurations")
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = handle.name
            for record in records:
                encoded = (
                    json.dumps(
                        teacher_record_to_data(record),
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                handle.write(encoded)
                digest.update(encoded.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return digest.hexdigest()


def teacher_records_digest(records: tuple[StrategyTeacherRecord, ...]) -> str:
    """Hash the exact JSONL bytes without publishing a dataset."""

    if not records:
        raise ValueError("strategy teacher dataset is empty")
    if len({record.teacher_config_digest for record in records}) != 1:
        raise ValueError("strategy teacher dataset mixes teacher configurations")
    digest = hashlib.sha256()
    for record in records:
        encoded = (
            json.dumps(
                teacher_record_to_data(record),
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        digest.update(encoded.encode("utf-8"))
    return digest.hexdigest()


def read_teacher_records(path: Path) -> tuple[StrategyTeacherRecord, ...]:
    return teacher_records_from_bytes(path.read_bytes())


def teacher_records_from_bytes(raw: bytes) -> tuple[StrategyTeacherRecord, ...]:
    """Parse one captured JSONL byte string without a second filesystem read."""

    try:
        text = raw.decode("utf-8")
        records = tuple(
            teacher_record_from_data(json.loads(line))
            for line in text.splitlines()
            if line.strip()
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("strategy teacher dataset is invalid JSONL") from exc
    if not records:
        raise ValueError("strategy teacher dataset is empty")
    identities = {(record.run_group, record.decision_index) for record in records}
    if len(identities) != len(records):
        raise ValueError("strategy teacher dataset repeats a run decision")
    group_outcomes: dict[str, tuple[bool, int, float]] = {}
    for record in records:
        outcome = (record.run_won, record.terminal_ante, record.run_log_score)
        previous = group_outcomes.setdefault(record.run_group, outcome)
        if previous != outcome:
            raise ValueError("strategy teacher origin has inconsistent run outcome")
    return records


def _validate_decision(
    observation: PublicObservation,
    candidates: tuple[StrategyTeacherCandidate, ...],
    selected_index: int,
    baseline_index: int,
    goal: RunGoal,
) -> None:
    if not candidates:
        raise ValueError("strategy teacher decision needs candidates")
    if not 0 <= selected_index < len(candidates) or not 0 <= baseline_index < len(
        candidates
    ):
        raise ValueError("strategy teacher candidate index is out of range")
    if derive_engine_state(observation).goal != goal:
        raise ValueError("strategy teacher goal disagrees with public state")
    sample_counts = {len(candidate.samples) for candidate in candidates}
    if len(sample_counts) != 1:
        raise ValueError("strategy teacher candidates must use paired sample counts")
    identities = {(candidate.action, candidate.intent) for candidate in candidates}
    if len(identities) != len(candidates):
        raise ValueError(
            "strategy teacher candidate action/intent pairs must be unique"
        )
    if any(not is_legal(observation, candidate.action) for candidate in candidates):
        raise ValueError("strategy teacher candidate action is not publicly legal")


def _validate_digest(value: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError("teacher configuration digest must be SHA-256")


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("optional strategy target must be numeric or null")
    return float(value)


__all__ = [
    "STRATEGY_TEACHER_SCHEMA_VERSION",
    "StrategyRolloutTarget",
    "StrategyTargetEndpoint",
    "StrategyTeacherCandidate",
    "StrategyTeacherDraft",
    "StrategyTeacherRecord",
    "PublicStrategyContext",
    "read_teacher_records",
    "teacher_record_from_data",
    "teacher_record_to_data",
    "teacher_records_digest",
    "write_teacher_records",
]
