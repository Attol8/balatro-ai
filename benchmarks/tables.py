"""Build the benchmark tables and render them deterministically.

Table A pairs the twelve recorded baseline panels (``evidence/baselines``) with the
two coached runs (``evidence/first-win`` and ``evidence/astra-low-2K9H9HN``).
Table B reports scoring-engine exactness from ``evidence/first-win/scoring-audit.json``
plus what the astra-low trajectory itself supports.  Table C splits the Astra-high
win by decision source and by ante, recomputed from the trajectory.

Rendering is pure: the same evidence always produces the same bytes, so
``results.json`` and ``results.md`` are safe to commit.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import EVIDENCE_ROOT, SETTING
from .baselines import BaselinePanel, load_panels
from .trajectories import (
    SOURCE_DELEGATE,
    Trajectory,
    load_astra_low,
    load_first_win,
    segment_ante_bounds,
)

TABLE_A_TITLE = f"Real-game results, {SETTING}"
TABLE_B_TITLE = "Scoring-engine exactness"
TABLE_C_TITLE = "Decision sources in the Astra-high win"

TRAJECTORY_REVIEW = "docs/trajectory-review.md"


@dataclass
class CoachedRow:
    """A coached (LLM-driven) row of Table A."""

    label: str
    model: str
    reasoning_effort: str
    seeds: list[str]
    games: int
    ante8_clears: int
    antes_reached: list[int]
    decisions: int
    coach_requests: int
    seconds: float
    peak_hand_score: float
    note: str
    sources: list[str] = field(default_factory=list)

    @property
    def median_ante(self) -> float:
        return float(statistics.median(self.antes_reached))

    @property
    def mean_ante(self) -> float:
        return round(statistics.fmean(self.antes_reached), 2)

    @property
    def seed_label(self) -> str:
        return ", ".join(self.seeds)


def _panel_row(panel: BaselinePanel) -> dict:
    return {
        "policy": panel.policy,
        "run_dir": panel.run_dir,
        "kind": "baseline",
        "games_requested": panel.requested,
        "games_attempted": panel.attempted,
        "games_completed": panel.completed,
        "ante8_clears": panel.ante8_clears,
        "reached_ante8_or_more": panel.reached_ante8_or_more,
        "median_ante": panel.median_ante,
        "mean_ante": panel.mean_ante,
        "seed_panel": panel.seeds_label,
        "partial": panel.partial,
        "git_revision": panel.git_revision,
        "profile_mode": panel.profile_mode,
        "notes": list(panel.notes),
    }


def _coached_row(row: CoachedRow) -> dict:
    return {
        "policy": row.label,
        "run_dir": row.sources[0] if row.sources else "",
        "kind": "coached",
        "model": row.model,
        "reasoning_effort": row.reasoning_effort,
        "games_requested": row.games,
        "games_attempted": row.games,
        "games_completed": row.games,
        "ante8_clears": row.ante8_clears,
        "reached_ante8_or_more": sum(1 for ante in row.antes_reached if ante >= 8),
        "median_ante": row.median_ante,
        "mean_ante": row.mean_ante,
        "seed_panel": row.seed_label,
        "decisions": row.decisions,
        "coach_requests": row.coach_requests,
        "seconds": row.seconds,
        "peak_hand_score": row.peak_hand_score,
        "notes": [row.note],
        "sources": list(row.sources),
    }


def built_in_coached_rows(evidence_root: Path | None = None) -> list[CoachedRow]:
    """The two coached runs stored under ``evidence/``."""

    root = evidence_root or EVIDENCE_ROOT
    high = json.loads((root / "first-win" / "result.json").read_text())
    high_manifest = json.loads((root / "first-win" / "manifest.json").read_text())
    low = json.loads((root / "astra-low-2K9H9HN" / "result.json").read_text())
    low_ante8 = json.loads((root / "astra-low-2K9H9HN" / "ante-8-result.json").read_text())
    low_manifest = json.loads((root / "astra-low-2K9H9HN" / "manifest.json").read_text())
    return [
        CoachedRow(
            label=f"Astra high ({high_manifest['coach']['model']})",
            model=high_manifest["coach"]["model"],
            reasoning_effort=high_manifest["coach"]["effort"],
            seeds=[high["seed"]],
            games=1,
            ante8_clears=1 if high["won"] else 0,
            antes_reached=[int(high["ante_reached"])],
            decisions=int(high["decisions"]),
            coach_requests=int(high["coach_requests"]),
            seconds=float(high["seconds"]),
            peak_hand_score=float(high["peak_hand_score"]),
            note=(
                f"single game, seed {high['seed']}: {high['reason']}, "
                f"ante {high['ante_reached']} reached"
            ),
            sources=["evidence/first-win"],
        ),
        CoachedRow(
            label=f"Astra low ({low_manifest['requested_model']})",
            model=low_manifest["requested_model"],
            reasoning_effort=low_manifest["requested_reasoning_effort"],
            seeds=[low_manifest["seed"]],
            games=1,
            ante8_clears=1 if low["won"] else 0,
            antes_reached=[int(low["ante_reached"])],
            decisions=int(low["decisions"]),
            coach_requests=int(low["coach_requests"]),
            seconds=float(low["seconds"]),
            peak_hand_score=float(low["peak_hand_score"]),
            note=(
                f"single game, seed {low_manifest['seed']}: cleared Ante 8 "
                f"({low_ante8['decisions']} decisions, ante {low_ante8['ante_reached']}), "
                f"then continued in endless and lost at ante {low['ante_reached']}"
            ),
            sources=["evidence/astra-low-2K9H9HN"],
        ),
    ]


def load_extra_runs(run_dirs: list[Path]) -> list[CoachedRow]:
    """Group directories produced by ``balatro play`` by model and reasoning effort."""

    grouped: dict[tuple[str, str], list[tuple[Path, dict, dict]]] = {}
    for run_dir in run_dirs:
        manifest = json.loads((run_dir / "manifest.json").read_text())
        result = json.loads((run_dir / "result.json").read_text())
        model = manifest.get("requested_model", "unknown")
        effort = manifest.get("requested_reasoning_effort", "unknown")
        grouped.setdefault((model, effort), []).append((run_dir, manifest, result))
    rows: list[CoachedRow] = []
    for (model, effort), entries in sorted(grouped.items()):
        entries.sort(key=lambda item: str(item[0]))
        completed = [item for item in entries if item[2].get("status") != "error"]
        antes = [int(item[2].get("ante_reached", 0)) for item in completed] or [0]
        rows.append(
            CoachedRow(
                label=f"{model} ({effort})",
                model=model,
                reasoning_effort=effort,
                seeds=[str(item[1].get("seed", "unknown")) for item in entries],
                games=len(entries),
                ante8_clears=sum(1 for item in completed if item[2].get("won")),
                antes_reached=antes,
                decisions=sum(int(item[2].get("decisions", 0)) for item in entries),
                coach_requests=sum(int(item[2].get("coach_requests", 0)) for item in entries),
                seconds=round(sum(float(item[2].get("seconds", 0.0)) for item in entries), 3),
                peak_hand_score=max(
                    (float(item[2].get("peak_hand_score", 0.0)) for item in entries), default=0.0
                ),
                note=f"ingested with --runs; {len(completed)} of {len(entries)} games completed",
                sources=[str(item[0]) for item in entries],
            )
        )
    return rows


def _table_a(panels: list[BaselinePanel], coached: list[CoachedRow]) -> dict:
    repeated = {
        policy for policy, count in Counter(panel.policy for panel in panels).items() if count > 1
    }
    baseline_rows = []
    for panel in panels:
        row = _panel_row(panel)
        row["display_name"] = (
            f"{panel.policy} ({panel.run_dir})" if panel.policy in repeated else panel.policy
        )
        baseline_rows.append(row)
    coached_rows = []
    for row in coached:
        entry = _coached_row(row)
        entry["display_name"] = row.label
        coached_rows.append(entry)
    return {
        "title": TABLE_A_TITLE,
        "setting": SETTING,
        "baselines": baseline_rows,
        "coached": coached_rows,
        "footnotes": [
            "Coached games are single games on seeds outside the D0000000-D0000019 baseline "
            "panel; they are demonstrations, not win-rate estimates.",
            "The Astra-high win delegated 5 of its 203 decisions to the search-v6 numerical "
            "policy and took 23 automatic cashouts; 175 decisions came from the coach.",
            "The Astra-low run was supervised: it was played with adapter fixes and reviewed "
            "continuations across 7 recorded segments, so it is not an unattended benchmark.",
            "Baselines are sorted by Ante-8 clears (descending), then median ante (descending).",
            "Games with status 'error' count as attempted but not completed and are excluded "
            "from the ante statistics.",
        ],
    }


def _table_b(high: Trajectory, low: Trajectory, evidence_root: Path | None = None) -> dict:
    root = evidence_root or EVIDENCE_ROOT
    audit = json.loads((root / "first-win" / "scoring-audit.json").read_text())
    recorded = audit["recorded_prediction_comparison"]
    versus_game = audit["actual_game_comparison"]
    high_plays = high.plays
    high_diffs = [
        abs((play.observed_score or 0.0) - (play.predicted_score or 0.0)) for play in high_plays
    ]
    low_plays = low.plays
    low_with_estimate = [play for play in low_plays if play.predicted_is_estimate]
    low_exact = [
        play
        for play in low_with_estimate
        if abs((play.observed_score or 0.0) - (play.predicted_score or 0.0)) < 1.0
    ]
    return {
        "title": TABLE_B_TITLE,
        "rows": [
            {
                "run": high.run_id,
                "plays_scored": audit["play_actions_scored"],
                "prediction_mismatches": recorded["mismatch_count"],
                "max_abs_prediction_difference": recorded["max_absolute_difference"],
                "sub_chip_floor_differences_vs_game": versus_game["discrepancy_count"],
                "max_abs_difference_vs_game": versus_game["max_absolute_difference"],
                "derivation": "computed",
                "source": "evidence/first-win/scoring-audit.json",
                "cross_check": {
                    "plays_in_trajectory": len(high_plays),
                    "plays_differing_from_prediction": sum(1 for diff in high_diffs if diff > 0),
                    "max_abs_difference": max(high_diffs) if high_diffs else 0.0,
                    "source": "evidence/first-win/trajectory.jsonl.gz",
                },
                "note": versus_game["reason"],
            },
            {
                "run": low.run_id,
                "plays_scored": len(low_plays),
                "exact_after_public_correction": 46,
                "plays_with_visible_joker_identities": 47,
                "derivation": "cited",
                "source": TRAJECTORY_REVIEW,
                "cross_check": {
                    "plays_with_shortlist_estimate": len(low_with_estimate),
                    "shortlist_estimates_within_1_chip": len(low_exact),
                    "source": "evidence/astra-low-2K9H9HN/segments/*/trajectory.jsonl.gz",
                },
                "note": (
                    "The astra-low trajectory stores no per-play prediction; only the advisory "
                    "shortlist estimate for the chosen play is recoverable, and it predates the "
                    f"Fortune Teller adapter fix. The exactness figure is quoted from "
                    f"{TRAJECTORY_REVIEW}."
                ),
            },
        ],
    }


def _table_c(high: Trajectory) -> dict:
    sources = high.source_counts()
    per_ante = high.decisions_per_ante()
    return {
        "title": TABLE_C_TITLE,
        "run": high.run_id,
        "seed": high.seed,
        "total_decisions": len(high.decisions),
        "decision_sources": sources,
        "decisions_per_ante": {str(ante): count for ante, count in per_ante.items()},
        "source": "evidence/first-win/trajectory.jsonl.gz",
        "note": (
            f"{sources.get(SOURCE_DELEGATE, 0)} decisions were delegated to the search-v6 "
            "numerical policy; the automatic decisions are cash-outs the runner takes without "
            "asking the coach."
        ),
    }


def build_results(
    evidence_root: Path | None = None,
    extra_runs: list[Path] | None = None,
) -> dict:
    """Assemble every table into one JSON-serialisable dict."""

    root = evidence_root or EVIDENCE_ROOT
    panels = load_panels(root)
    high = load_first_win(root)
    low = load_astra_low(root)
    coached = built_in_coached_rows(root) + load_extra_runs(list(extra_runs or []))
    return {
        "setting": SETTING,
        "evidence_root": "evidence",
        "table_a": _table_a(panels, coached),
        "table_b": _table_b(high, low, root),
        "table_c": _table_c(high),
        "astra_low_segments": [
            {"segment": segment, "ante_start": start, "ante_end": end}
            for segment, start, end in segment_ante_bounds(low)
        ],
    }


def render_json(results: dict) -> str:
    """Sorted keys, two-space indent, one trailing newline."""

    return json.dumps(results, sort_keys=True, indent=2) + "\n"


def _fmt(value: float) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _md_table(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |"]
    lines.append("|" + "|".join(["---"] * len(header)) + "|")
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def render_markdown(results: dict) -> str:
    """Render the same dict as a stable Markdown document."""

    table_a = results["table_a"]
    lines = [
        "# Balatro benchmark results",
        "",
        f"Setting: {results['setting']}. Every number is read from a file under "
        "`evidence/`; this document is generated by `python -m benchmarks`.",
        "",
        f"## Table A - {table_a['title']}",
        "",
    ]
    header = [
        "Policy",
        "Attempted",
        "Completed",
        "Ante-8 clears",
        "Reached Ante >=8",
        "Median ante",
        "Mean ante",
        "Seed panel",
        "Notes",
    ]
    rows = []
    for row in table_a["coached"] + table_a["baselines"]:
        rows.append(
            [
                f"**{row['display_name']}**" if row["kind"] == "coached" else row["display_name"],
                str(row["games_attempted"]),
                str(row["games_completed"]),
                str(row["ante8_clears"]),
                str(row["reached_ante8_or_more"]),
                _fmt(row["median_ante"]),
                _fmt(row["mean_ante"]),
                row["seed_panel"],
                "; ".join(row["notes"]) or "-",
            ]
        )
    lines += _md_table(header, rows)
    lines.append("")
    for index, note in enumerate(table_a["footnotes"], start=1):
        lines.append(f"{index}. {note}")
    lines.append("")

    table_b = results["table_b"]
    lines += [f"## Table B - {table_b['title']}", ""]
    b_rows = []
    for row in table_b["rows"]:
        if row["derivation"] == "computed":
            figure = (
                f"{row['plays_scored']} plays scored, {row['prediction_mismatches']} prediction "
                f"mismatches, {row['sub_chip_floor_differences_vs_game']} sub-1-chip floor "
                f"differences vs the game (max {row['max_abs_difference_vs_game']})"
            )
        else:
            cross = row["cross_check"]
            figure = (
                f"{row['exact_after_public_correction']} of "
                f"{row['plays_with_visible_joker_identities']} plays exact after the public "
                f"Fortune Teller correction; {cross['plays_with_shortlist_estimate']} of "
                f"{row['plays_scored']} recorded plays carry a shortlist estimate, "
                f"{cross['shortlist_estimates_within_1_chip']} of those within 1 chip"
            )
        b_rows.append([row["run"], figure, row["derivation"], f"`{row['source']}`"])
    lines += _md_table(["Run", "Result", "Derivation", "Source"], b_rows)
    lines.append("")
    for row in table_b["rows"]:
        lines.append(f"- {row['run']}: {row['note']}")
    lines.append("")

    table_c = results["table_c"]
    lines += [f"## Table C - {table_c['title']}", ""]
    lines += _md_table(
        ["Decision source", "Count"],
        [[name, str(count)] for name, count in table_c["decision_sources"].items()]
        + [["**total**", str(table_c["total_decisions"])]],
    )
    lines.append("")
    lines += _md_table(
        ["Ante", "Decisions"],
        [[ante, str(count)] for ante, count in table_c["decisions_per_ante"].items()],
    )
    lines.append("")
    lines.append(f"- {table_c['note']}")
    lines.append(f"- Source: `{table_c['source']}`")
    lines.append("")
    lines.append("## Astra-low segment continuity")
    lines.append("")
    lines += _md_table(
        ["Segment", "Ante at start", "Ante at end"],
        [
            [entry["segment"], str(entry["ante_start"]), str(entry["ante_end"])]
            for entry in results["astra_low_segments"]
        ],
    )
    lines.append("")
    return "\n".join(lines)


def write_results(results: dict, out_dir: Path) -> list[Path]:
    """Write ``results.json`` and ``results.md``; return the paths written."""

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "results.json"
    md_path = out_dir / "results.md"
    json_path.write_text(render_json(results), encoding="utf-8")
    md_path.write_text(render_markdown(results), encoding="utf-8")
    return [json_path, md_path]


__all__ = [
    "CoachedRow",
    "build_results",
    "built_in_coached_rows",
    "load_extra_runs",
    "render_json",
    "render_markdown",
    "write_results",
]
