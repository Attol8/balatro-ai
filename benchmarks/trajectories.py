"""Loaders for the two recorded trajectory schemas, reduced to one record type.

``evidence/first-win/trajectory.jsonl.gz`` (schema_version 1) emits
``episode -> rpc_attempt -> started -> {decision, transition}* -> result``.  The
decision carries ``observation`` and ``predicted_score``; the matching transition
carries ``observed_score``.

``evidence/astra-low-2K9H9HN/segments/NN/trajectory.jsonl.gz`` is the older shape:
``rpc_attempt / coach_request / coach_response / transition``.  Only the transition
is a decision; ``before``/``after`` are full state snapshots and the hand score has
to be recovered as the round-chip delta.  A predicted score exists there only when
the chosen play appears in that request's advisory ``analysis.play_candidates``
shortlist, so it is recorded as an estimate with a coverage count rather than as a
per-play guarantee.
"""

from __future__ import annotations

import gzip
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from . import EVIDENCE_ROOT

PLAY_ACTION = "play_cards"
SOURCE_COACH = "coach"
SOURCE_AUTOMATIC = "automatic"
SOURCE_DELEGATE = "numerical_delegate"


@dataclass(frozen=True)
class DecisionRecord:
    """One agent action, common to both schemas."""

    index: int
    segment: str
    ante: int
    ante_after: int
    blind_kind: str | None
    requirement: int | None
    round_chips_after: int
    action: str
    source: str
    money: int
    observed_score: float | None = None
    predicted_score: float | None = None
    predicted_is_estimate: bool = False

    @property
    def is_play(self) -> bool:
        return self.action == PLAY_ACTION


@dataclass(frozen=True)
class BlindRecord:
    """One blind the run actually played hands into."""

    ante: int
    blind: str
    requirement: int
    hands_played: int
    best_hand_score: float
    total_chips_scored: float

    @property
    def cleared(self) -> bool:
        return self.total_chips_scored >= self.requirement


@dataclass(frozen=True)
class Trajectory:
    """A whole recorded game (segments already concatenated)."""

    run_id: str
    seed: str
    decisions: tuple[DecisionRecord, ...]

    @property
    def plays(self) -> tuple[DecisionRecord, ...]:
        return tuple(record for record in self.decisions if record.is_play)

    def source_counts(self) -> dict[str, int]:
        counts = Counter(record.source for record in self.decisions)
        return {key: counts[key] for key in sorted(counts)}

    def decisions_per_ante(self) -> dict[int, int]:
        counts = Counter(record.ante for record in self.decisions)
        return {ante: counts[ante] for ante in sorted(counts)}

    def ante_series(self) -> tuple[int, ...]:
        return tuple(record.ante for record in self.decisions)

    def blind_series(self) -> tuple[BlindRecord, ...]:
        """Consecutive plays grouped into the blind they were played into."""

        blinds: list[BlindRecord] = []
        key: tuple[int, str | None, int | None] | None = None
        scores: list[float] = []
        for record in self.plays:
            record_key = (record.ante, record.blind_kind, record.requirement)
            if record_key != key:
                if key is not None:
                    blinds.append(_finish_blind(key, scores))
                key, scores = record_key, []
            scores.append(record.observed_score or 0.0)
        if key is not None:
            blinds.append(_finish_blind(key, scores))
        return tuple(blinds)


def _finish_blind(key: tuple[int, str | None, int | None], scores: list[float]) -> BlindRecord:
    ante, blind, requirement = key
    return BlindRecord(
        ante=ante,
        blind=blind or "UNKNOWN",
        requirement=int(requirement or 0),
        hands_played=len(scores),
        best_hand_score=max(scores) if scores else 0.0,
        total_chips_scored=sum(scores),
    )


def _read_jsonl_gz(path: Path) -> Iterator[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _first_win_source(diagnostics: dict) -> str:
    if "coach_request_id" in diagnostics:
        return SOURCE_COACH
    if diagnostics.get("coach_delegated") is True:
        return SOURCE_DELEGATE
    if "coach_automatic" in diagnostics:
        return SOURCE_AUTOMATIC
    return "unknown"


def _current_blind_v1(observation: dict) -> tuple[str | None, int | None]:
    for blind in observation.get("blinds", {}).values():
        if blind.get("status") == "CURRENT":
            return blind.get("type"), blind.get("score")
    return None, None


def load_first_win(evidence_root: Path | None = None) -> Trajectory:
    """Load ``evidence/first-win`` (the Astra-high win on seed D0001000)."""

    root = (evidence_root or EVIDENCE_ROOT) / "first-win"
    decisions: dict[int, dict] = {}
    transitions: dict[int, dict] = {}
    seed = ""
    for event in _read_jsonl_gz(root / "trajectory.jsonl.gz"):
        kind = event.get("event")
        if kind == "episode":
            seed = event.get("seed", "")
        elif kind == "decision":
            decisions[event["index"]] = event
        elif kind == "transition":
            transitions[event["index"]] = event
    records = []
    for index in sorted(decisions):
        decision = decisions[index]
        transition = transitions[index]
        observation = decision["observation"]
        action = decision["action"].get("public_action", {}).get("type", "unknown")
        kind, requirement = _current_blind_v1(observation)
        is_play = action == PLAY_ACTION
        records.append(
            DecisionRecord(
                index=index,
                segment="first-win",
                ante=int(observation["ante_num"]),
                ante_after=int(transition["observation"]["ante_num"]),
                blind_kind=kind,
                requirement=requirement,
                round_chips_after=int(transition["observation"]["round"]["chips"]),
                action=action,
                source=_first_win_source(decision.get("diagnostics") or {}),
                money=int(observation["money"]),
                observed_score=transition.get("observed_score") if is_play else None,
                predicted_score=decision.get("predicted_score") if is_play else None,
            )
        )
    return Trajectory(run_id="astra-high-D0001000", seed=seed, decisions=tuple(records))


def _current_blind_v0(snapshot: dict) -> tuple[str | None, int | None]:
    for blind in snapshot.get("blinds", []):
        if blind.get("status") == "CURRENT":
            return blind.get("kind"), blind.get("score")
    return None, None


def _shortlist_estimate(request: dict | None, action: dict) -> float | None:
    if not request:
        return None
    for candidate in (request.get("analysis") or {}).get("play_candidates", []):
        if candidate.get("action") == action:
            return float(candidate["estimated_score"])
    return None


def astra_low_segments(evidence_root: Path | None = None) -> list[dict]:
    """Segments belonging to the completed game, in ``segments.json`` order."""

    root = (evidence_root or EVIDENCE_ROOT) / "astra-low-2K9H9HN"
    listed = json.loads((root / "segments.json").read_text())
    return [entry for entry in listed if entry.get("part_of_completed_game")]


def load_astra_low(evidence_root: Path | None = None) -> Trajectory:
    """Concatenate the astra-low segments into one trajectory."""

    root = (evidence_root or EVIDENCE_ROOT) / "astra-low-2K9H9HN"
    seed = json.loads((root / "manifest.json").read_text())["seed"]
    records: list[DecisionRecord] = []
    index = 0
    for entry in astra_low_segments(evidence_root):
        segment = entry["segment"]
        path = root / "segments" / segment / "trajectory.jsonl.gz"
        pending_request: dict | None = None
        for event in _read_jsonl_gz(path):
            kind = event.get("event")
            if kind == "coach_request":
                pending_request = event
                continue
            if kind != "transition":
                continue
            before, after = event["before"], event["after"]
            action = event.get("action") or {}
            action_type = action.get("type", "unknown")
            blind_kind, requirement = _current_blind_v0(before)
            is_play = action_type == PLAY_ACTION
            observed = None
            estimate = None
            if is_play:
                observed = float(after["round"]["chips"] - before["round"]["chips"])
                estimate = _shortlist_estimate(pending_request, action)
            records.append(
                DecisionRecord(
                    index=index,
                    segment=segment,
                    ante=int(before["ante"]),
                    ante_after=int(after["ante"]),
                    blind_kind=blind_kind,
                    requirement=requirement,
                    round_chips_after=int(after["round"]["chips"]),
                    action=action_type,
                    source=event.get("source", "unknown"),
                    money=int(before["money"]),
                    observed_score=observed,
                    predicted_score=estimate,
                    predicted_is_estimate=estimate is not None,
                )
            )
            index += 1
            pending_request = None
    return Trajectory(run_id="astra-low-2K9H9HN", seed=seed, decisions=tuple(records))


def segment_ante_bounds(trajectory: Trajectory) -> list[tuple[str, int, int]]:
    """``(segment, ante at segment start, ante at segment end)`` in recorded order."""

    bounds: list[tuple[str, int, int]] = []
    for record in trajectory.decisions:
        if bounds and bounds[-1][0] == record.segment:
            segment, start, _ = bounds[-1]
            bounds[-1] = (segment, start, record.ante_after)
        else:
            bounds.append((record.segment, record.ante, record.ante_after))
    return bounds
