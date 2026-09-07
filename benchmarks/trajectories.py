"""Loaders for the two recorded trajectory schemas, reduced to one record type.

``evidence/first-win/trajectory.jsonl.gz`` (schema_version 1) emits
``episode -> rpc_attempt -> started -> {decision, transition}* -> result``.  The
decision carries ``observation`` and ``predicted_score``; the matching transition
carries ``observed_score``.

Any evidence directory holding a ``segments.json`` (``astra-low-2K9H9HN``,
``astra-low-TAF7DNTX``, ``astra-low-D0000000``) uses the runner's segment shape:
``rpc_attempt / coach_request / coach_response / transition``, plus ``continued``,
``coach_timeout``, ``coach_rejected`` and ``rpc_timeout`` in the current runner; a
transition recovered after a game-reply timeout carries ``recovered``.  Unknown event
types are counted and skipped, so a newer runner never breaks the loader.  Only the transition
is a decision; ``before``/``after`` are full state snapshots and the hand score has
to be recovered as the round-chip delta.  ``transition.source`` is one of
``coach``, ``automatic``, ``forced`` or ``coach_followup``.  A predicted score exists
only when the chosen play appears in that request's advisory
``analysis.play_candidates`` shortlist, so it is recorded as an estimate with a
coverage count rather than as a per-play guarantee.  Chip requirements reach the
billions in endless antes and are kept as exact integers throughout.
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
SOURCE_FORCED = "forced"
SOURCE_COACH_FOLLOWUP = "coach_followup"

ASTRA_LOW_SUPERVISED = "astra-low-2K9H9HN"
ASTRA_LOW_HEADLESS = "astra-low-TAF7DNTX"
ASTRA_LOW_PANEL_SEED = "astra-low-D0000000"


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
    phase: str = ""

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
class CoachCallHealth:
    """Transport-level events the current runner records around coach calls."""

    responses: int = 0
    responses_with_hedge_data: int = 0
    hedged: int = 0
    hedges_won: int = 0
    timeouts: int = 0
    rejected_responses: int = 0
    rpc_timeouts: int = 0
    recovered_transitions: int = 0

    @property
    def recorded(self) -> bool:
        """Older trajectories carry no transport timings at all."""

        return self.responses_with_hedge_data > 0 or self.timeouts > 0


@dataclass(frozen=True)
class Trajectory:
    """A whole recorded game (segments already concatenated)."""

    run_id: str
    seed: str
    decisions: tuple[DecisionRecord, ...]
    coach_calls: CoachCallHealth = CoachCallHealth()

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


def run_segments(run_dir: Path) -> list[dict]:
    """Segments belonging to the completed game, in ``segments.json`` order."""

    listed = json.loads((run_dir / "segments.json").read_text())
    return [entry for entry in listed if entry.get("part_of_completed_game")]


def astra_low_segments(evidence_root: Path | None = None) -> list[dict]:
    """Segments of the supervised astra-low run (seed 2K9H9HN)."""

    return run_segments((evidence_root or EVIDENCE_ROOT) / ASTRA_LOW_SUPERVISED)


def _call_health(events: Counter, hedged: int, won: int, with_data: int, recovered: int):
    return CoachCallHealth(
        responses=events["coach_response"],
        responses_with_hedge_data=with_data,
        hedged=hedged,
        hedges_won=won,
        timeouts=events["coach_timeout"],
        rejected_responses=events["coach_rejected"],
        rpc_timeouts=events["rpc_timeout"],
        recovered_transitions=recovered,
    )


def load_segmented_run(run_dir: Path, run_id: str | None = None) -> Trajectory:
    """Concatenate every ``part_of_completed_game`` segment of one run directory."""

    seed = json.loads((run_dir / "manifest.json").read_text())["seed"]
    records: list[DecisionRecord] = []
    events: Counter = Counter()
    hedged = won = with_hedge_data = recovered = 0
    index = 0
    for entry in run_segments(run_dir):
        segment = entry["segment"]
        path = run_dir / "segments" / segment / "trajectory.jsonl.gz"
        pending_request: dict | None = None
        for event in _read_jsonl_gz(path):
            kind = event.get("event", "unknown")
            events[kind] += 1
            if kind == "coach_request":
                pending_request = event
                continue
            if kind == "coach_response":
                timings = event.get("transport_timings") or {}
                if "hedged" in timings:
                    with_hedge_data += 1
                    hedged += bool(timings["hedged"])
                    won += int(timings.get("winner") or 0) > 0
                continue
            if kind != "transition":
                continue
            recovered += bool(event.get("recovered"))
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
                    phase=str(before.get("phase", "")),
                )
            )
            index += 1
            pending_request = None
    return Trajectory(
        run_id=run_id or run_dir.name,
        seed=seed,
        decisions=tuple(records),
        coach_calls=_call_health(events, hedged, won, with_hedge_data, recovered),
    )


def load_astra_low(evidence_root: Path | None = None) -> Trajectory:
    """The supervised astra-low run, seed 2K9H9HN."""

    return load_segmented_run((evidence_root or EVIDENCE_ROOT) / ASTRA_LOW_SUPERVISED)


def load_astra_low_headless(evidence_root: Path | None = None) -> Trajectory:
    """The headless astra-low run, seed TAF7DNTX."""

    return load_segmented_run((evidence_root or EVIDENCE_ROOT) / ASTRA_LOW_HEADLESS)


def load_astra_low_panel_seed(evidence_root: Path | None = None) -> Trajectory:
    """The visible astra-low run on the baseline panel seed D0000000."""

    return load_segmented_run((evidence_root or EVIDENCE_ROOT) / ASTRA_LOW_PANEL_SEED)


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
