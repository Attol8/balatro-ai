"""Baseline panels: the non-LLM heuristic policies played on the real game.

Provenance: ``evidence/baselines/<run>/manifest.json`` (deck, stake, policy,
profile mode, git revision, seed list) and ``evidence/baselines/<run>/summary.json``
(``requested``, ``attempted``, ``ante_8_wins`` and one entry per game in ``runs``).

A game with ``status == "error"`` counts as attempted but never completed, and is
excluded from every ante statistic.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from pathlib import Path

from . import EVIDENCE_ROOT, FULL_PANEL_SIZE

ERROR_STATUS = "error"


@dataclass(frozen=True)
class BaselineGame:
    """One recorded game inside a baseline panel."""

    seed: str
    status: str
    won: bool
    ante_reached: int
    round_reached: int
    decisions: int
    seconds: float
    peak_hand_score: float

    @property
    def completed(self) -> bool:
        return self.status != ERROR_STATUS


@dataclass(frozen=True)
class BaselinePanel:
    """A whole panel of games played by one heuristic policy."""

    policy: str
    run_dir: str
    requested: int
    attempted: int
    completed: int
    ante8_clears: int
    reached_ante8_or_more: int
    median_ante: float
    mean_ante: float
    seeds_label: str
    partial: bool
    git_revision: str
    profile_mode: str
    deck: str
    stake: str
    reported_ante_8_wins: int
    games: tuple[BaselineGame, ...]

    @property
    def notes(self) -> tuple[str, ...]:
        notes: list[str] = []
        errors = sum(1 for game in self.games if not game.completed)
        if self.attempted < self.requested:
            notes.append(f"partial panel: {self.attempted} of {self.requested} seeds attempted")
        elif self.partial:
            notes.append(
                f"short panel: {self.attempted} seeds, not the {FULL_PANEL_SIZE}-seed panel"
            )
        if errors:
            notes.append(f"{errors} game(s) errored and are excluded from ante statistics")
        if self.profile_mode != "all_unlocked":
            notes.append(f"profile_mode {self.profile_mode!r}, not all_unlocked")
        return tuple(notes)


def _seeds_label(seeds: list[str]) -> str:
    if not seeds:
        return "-"
    if len(seeds) == 1:
        return seeds[0]
    return f"{seeds[0]}-{seeds[-1]}"


def load_panel(run_dir: Path) -> BaselinePanel:
    """Read one ``evidence/baselines/<run>`` directory into a panel."""

    manifest = json.loads((run_dir / "manifest.json").read_text())
    summary = json.loads((run_dir / "summary.json").read_text())
    config = manifest.get("config") or {}
    games = tuple(
        BaselineGame(
            seed=run["seed"],
            status=run["status"],
            won=bool(run["won"]),
            ante_reached=int(run["ante_reached"]),
            round_reached=int(run["round_reached"]),
            decisions=int(run["decisions"]),
            seconds=float(run["seconds"]),
            peak_hand_score=float(run["peak_hand_score"]),
        )
        for run in summary["runs"]
    )
    finished = [game for game in games if game.completed]
    antes = [game.ante_reached for game in finished]
    attempted = int(summary["attempted"])
    requested = int(summary["requested"])
    return BaselinePanel(
        policy=config.get("policy") or manifest["policy"],
        run_dir=run_dir.name,
        requested=requested,
        attempted=attempted,
        completed=len(finished),
        ante8_clears=sum(1 for game in finished if game.won),
        reached_ante8_or_more=sum(1 for game in finished if game.ante_reached >= 8),
        median_ante=float(statistics.median(antes)) if antes else 0.0,
        mean_ante=round(statistics.fmean(antes), 2) if antes else 0.0,
        seeds_label=_seeds_label([game.seed for game in games]),
        partial=attempted < requested or attempted < FULL_PANEL_SIZE,
        git_revision=manifest["git_revision"],
        profile_mode=(manifest.get("server") or {}).get("profile_mode", "unknown"),
        deck=config.get("deck", "unknown"),
        stake=config.get("stake", "unknown"),
        reported_ante_8_wins=int(summary["ante_8_wins"]),
        games=games,
    )


def load_panels(evidence_root: Path | None = None) -> list[BaselinePanel]:
    """Load every baseline panel, sorted by Ante-8 clears then median ante."""

    root = (evidence_root or EVIDENCE_ROOT) / "baselines"
    panels = [load_panel(child) for child in sorted(root.iterdir()) if child.is_dir()]
    return sort_panels(panels)


def sort_panels(panels: list[BaselinePanel]) -> list[BaselinePanel]:
    """Table A order: Ante-8 clears desc, median ante desc, then policy name."""

    return sorted(panels, key=lambda p: (-p.ante8_clears, -p.median_ante, p.policy))
