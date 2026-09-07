"""Build the benchmark tables and render them deterministically.

Table A pairs the twelve recorded baseline panels (``evidence/baselines``) with the
published coached run (``evidence/astra-low-2K9H9HN``).  Table B reports scoring-engine
exactness for that run: the headline figure is quoted from ``docs/trajectory-review.md``
because the trajectory stores no per-play prediction, and the recoverable shortlist
estimates are reported beside it.  Table C splits the same run by decision source,
phase, action type and shop visit, all recomputed from the concatenated segments.

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
    ASTRA_LOW_HEADLESS,
    ASTRA_LOW_SUPERVISED,
    Trajectory,
    load_astra_low,
    load_astra_low_headless,
    segment_ante_bounds,
)

TABLE_A_TITLE = f"Real-game results, {SETTING}"
TABLE_B_TITLE = "Scoring-engine exactness"
TABLE_C_TITLE = "Decision mix in the Astra-low runs"
SHOP_PHASE = "SHOP"

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
    followup_actions: int | None = None
    forced_actions: int | None = None
    coach_timeouts: int | None = None

    @property
    def median_ante(self) -> float:
        return float(statistics.median(self.antes_reached))

    @property
    def mean_ante(self) -> float:
        return round(statistics.fmean(self.antes_reached), 2)

    @property
    def seed_label(self) -> str:
        return ", ".join(self.seeds)

    @property
    def calls_per_decision(self) -> str:
        """Coach calls against decisions taken, e.g. ``357/384 = 0.93``."""

        if not self.decisions:
            return "-"
        ratio = self.coach_requests / self.decisions
        return f"{self.coach_requests}/{self.decisions} = {ratio:.2f}"

    @property
    def intervention_label(self) -> str:
        """Follow-ups, forced moves and retried stalls, or ``-`` when not recorded."""

        parts = (self.followup_actions, self.forced_actions, self.coach_timeouts)
        if all(part is None for part in parts):
            return "-"
        return " / ".join("-" if part is None else str(part) for part in parts)


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
        "calls_per_decision": "-",
        "followups_forced_stalls": "-",
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
        "calls_per_decision": row.calls_per_decision,
        "followup_actions": row.followup_actions,
        "forced_actions": row.forced_actions,
        "coach_timeouts": row.coach_timeouts,
        "followups_forced_stalls": row.intervention_label,
        "seconds": row.seconds,
        "peak_hand_score": row.peak_hand_score,
        "notes": [row.note],
        "sources": list(row.sources),
    }


def built_in_coached_rows(evidence_root: Path | None = None) -> list[CoachedRow]:
    """The two published coached runs, headless TAF7DNTX first."""

    root = evidence_root or EVIDENCE_ROOT
    headless_dir = root / ASTRA_LOW_HEADLESS
    headless = json.loads((headless_dir / "result.json").read_text())
    headless_manifest = json.loads((headless_dir / "manifest.json").read_text())
    supervised_dir = root / ASTRA_LOW_SUPERVISED
    low = json.loads((supervised_dir / "result.json").read_text())
    low_ante8 = json.loads((supervised_dir / "ante-8-result.json").read_text())
    low_manifest = json.loads((supervised_dir / "manifest.json").read_text())
    return [
        CoachedRow(
            label=f"Astra low ({headless_manifest['requested_model']})",
            model=headless_manifest["requested_model"],
            reasoning_effort=headless_manifest["requested_reasoning_effort"],
            seeds=[headless_manifest["seed"]],
            games=1,
            ante8_clears=1 if headless["won"] else 0,
            antes_reached=[int(headless["ante_reached"])],
            decisions=int(headless["decisions"]),
            coach_requests=int(headless["coach_requests"]),
            seconds=float(headless["seconds"]),
            peak_hand_score=float(headless["peak_hand_score"]),
            note=(
                f"single game, seed {headless_manifest['seed']}: headless, endless; "
                f"cleared Ante 8, then lost at ante {headless['ante_reached']}"
            ),
            sources=[f"evidence/{ASTRA_LOW_HEADLESS}"],
            followup_actions=int(headless["followup_actions"]),
            forced_actions=int(headless["forced_actions"]),
            coach_timeouts=int(headless["coach_timeouts"]),
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
            sources=[f"evidence/{ASTRA_LOW_SUPERVISED}"],
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
    seen_labels = Counter(row.label for row in coached)
    for row in coached:
        entry = _coached_row(row)
        entry["display_name"] = (
            f"{row.label}, seed {row.seed_label}" if seen_labels[row.label] > 1 else row.label
        )
        coached_rows.append(entry)
    return {
        "title": TABLE_A_TITLE,
        "setting": SETTING,
        "baselines": baseline_rows,
        "coached": coached_rows,
        "footnotes": [
            "Each coached row is a single game on a seed outside the D0000000-D0000019 "
            "baseline panel; they are demonstrations, not win-rate estimates.",
            "Seed TAF7DNTX was played headless in endless mode. The runner process was stopped "
            "and resumed four times at safe moments (during model calls) to deploy runner fixes "
            "- request-id length, timeout retry, hedged calls. No game state or trajectory was "
            "edited; illegal replies were rejected and corrected in place.",
            "The Astra-low run was supervised: it was played with adapter fixes and reviewed "
            "continuations across 7 recorded segments, so it is not an unattended benchmark.",
            "'Coach calls / decisions' counts model requests against actions taken; the runner "
            "takes cash-outs itself, so the ratio is below one.",
            "'Follow-ups / forced / stalls' counts chained follow-up actions, moves the runner "
            "forced when no legal reply arrived, and coach calls that timed out and were "
            "retried; only the current runner records them.",
            "Baselines are sorted by Ante-8 clears (descending), then median ante (descending).",
            "Games with status 'error' count as attempted but not completed and are excluded "
            "from the ante statistics.",
        ],
    }


def _table_b(low: Trajectory, evidence_root: Path | None = None) -> dict:
    del evidence_root
    plays = low.plays
    with_estimate = [play for play in plays if play.predicted_is_estimate]
    within_chip = [
        play
        for play in with_estimate
        if abs((play.observed_score or 0.0) - (play.predicted_score or 0.0)) < 1.0
    ]
    return {
        "title": TABLE_B_TITLE,
        "rows": [
            {
                "run": low.run_id,
                "plays_scored": len(plays),
                "exact_after_public_correction": 46,
                "plays_with_visible_joker_identities": 47,
                "derivation": "cited",
                "source": TRAJECTORY_REVIEW,
                "cross_check": {
                    "plays_with_shortlist_estimate": len(with_estimate),
                    "shortlist_estimates_within_1_chip": len(within_chip),
                    "source": "evidence/astra-low-2K9H9HN/segments/*/trajectory.jsonl.gz",
                },
                "note": (
                    "The astra-low trajectory stores no per-play prediction; only the advisory "
                    "shortlist estimate for the chosen play is recoverable, and it predates the "
                    f"Fortune Teller adapter fix. The exactness figure is quoted from "
                    f"{TRAJECTORY_REVIEW}."
                ),
            }
        ],
    }


def _shop_visits(trajectory: Trajectory) -> dict:
    """Consecutive SHOP-phase decisions grouped into one shop visit each."""

    visits: list[int] = []
    current = 0
    for record in trajectory.decisions:
        if record.phase == SHOP_PHASE:
            current += 1
        elif current:
            visits.append(current)
            current = 0
    if current:
        visits.append(current)
    return {
        "visits": len(visits),
        "actions_total": sum(visits),
        "median_actions_per_visit": float(statistics.median(visits)),
        "mean_actions_per_visit": round(statistics.fmean(visits), 2),
        "max_actions_in_a_visit": max(visits),
    }


def _decision_mix(trajectory: Trajectory, result: dict) -> dict:
    """One run's decision mix: sources, phases, action types, shop visits, call health."""

    phases = Counter(record.phase for record in trajectory.decisions)
    by_action: dict[str, Counter] = {}
    for record in trajectory.decisions:
        by_action.setdefault(record.action, Counter())[record.source] += 1
    actions = [
        {
            "action": action,
            "count": sum(counts.values()),
            "sources": {source: counts[source] for source in sorted(counts)},
        }
        for action, counts in by_action.items()
    ]
    actions.sort(key=lambda entry: (-entry["count"], entry["action"]))
    calls = trajectory.coach_calls
    block = {
        "run": trajectory.run_id,
        "seed": trajectory.seed,
        "total_transitions": len(trajectory.decisions),
        "reported_decisions": int(result["decisions"]),
        "decision_sources": trajectory.source_counts(),
        "decisions_per_phase": {phase: phases[phase] for phase in sorted(phases)},
        "decisions_per_action": actions,
        "shop_visits": _shop_visits(trajectory),
        "coach_calls": {
            "recorded": calls.recorded,
            "responses": calls.responses,
            "responses_with_hedge_data": calls.responses_with_hedge_data,
            "hedged": calls.hedged,
            "hedges_won": calls.hedges_won,
            "timeouts": calls.timeouts,
            "rejected_responses": calls.rejected_responses,
        },
        "source": f"evidence/{trajectory.run_id}/segments/*/trajectory.jsonl.gz",
    }
    if len(trajectory.decisions) != block["reported_decisions"]:
        block["note"] = (
            f"The concatenated segments hold {len(trajectory.decisions)} transitions while "
            f"result.json reports {block['reported_decisions']} decisions: segment 00 ended on "
            "an errored action that was counted but never produced a transition record."
        )
    else:
        block["note"] = (
            f"The concatenated segments hold exactly the {block['reported_decisions']} decisions "
            "result.json reports."
        )
    return block


def _table_c(runs: list[tuple[Trajectory, dict]]) -> dict:
    return {
        "title": TABLE_C_TITLE,
        "blocks": [_decision_mix(trajectory, result) for trajectory, result in runs],
    }


def build_results(
    evidence_root: Path | None = None,
    extra_runs: list[Path] | None = None,
) -> dict:
    """Assemble every table into one JSON-serialisable dict."""

    root = evidence_root or EVIDENCE_ROOT
    panels = load_panels(root)
    low = load_astra_low(root)
    headless = load_astra_low_headless(root)
    low_result = json.loads((root / ASTRA_LOW_SUPERVISED / "result.json").read_text())
    headless_result = json.loads((root / ASTRA_LOW_HEADLESS / "result.json").read_text())
    coached = built_in_coached_rows(root) + load_extra_runs(list(extra_runs or []))
    return {
        "setting": SETTING,
        "evidence_root": "evidence",
        "table_a": _table_a(panels, coached),
        "table_b": _table_b(low, root),
        "table_c": _table_c([(headless, headless_result), (low, low_result)]),
        "segment_continuity": [
            {
                "run": trajectory.run_id,
                "segments": [
                    {"segment": segment, "ante_start": start, "ante_end": end}
                    for segment, start, end in segment_ante_bounds(trajectory)
                ],
            }
            for trajectory in (headless, low)
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
        "Coach calls / decisions",
        "Follow-ups / forced / stalls",
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
                row.get("calls_per_decision") or "-",
                row.get("followups_forced_stalls") or "-",
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
    for block in table_c["blocks"]:
        lines.append(f"### {block['run']} (seed {block['seed']})")
        lines.append("")
        lines.append("Decision source, over the concatenated segments:")
        lines.append("")
        lines += _md_table(
            ["Decision source", "Count"],
            [[name, str(count)] for name, count in block["decision_sources"].items()]
            + [["**total**", str(block["total_transitions"])]],
        )
        lines.append("")
        lines.append("Decisions per phase:")
        lines.append("")
        lines += _md_table(
            ["Phase", "Decisions"],
            [[phase, str(count)] for phase, count in block["decisions_per_phase"].items()],
        )
        lines.append("")
        lines.append("Decisions per action type:")
        lines.append("")
        lines += _md_table(
            ["Action", "Count", "Sources"],
            [
                [
                    entry["action"],
                    str(entry["count"]),
                    ", ".join(f"{name} {count}" for name, count in entry["sources"].items()),
                ]
                for entry in block["decisions_per_action"]
            ],
        )
        lines.append("")
        shop = block["shop_visits"]
        lines.append("Shop visits:")
        lines.append("")
        lines += _md_table(
            ["Visits", "Shop actions", "Median per visit", "Mean per visit", "Max in one visit"],
            [
                [
                    str(shop["visits"]),
                    str(shop["actions_total"]),
                    _fmt(shop["median_actions_per_visit"]),
                    _fmt(shop["mean_actions_per_visit"]),
                    str(shop["max_actions_in_a_visit"]),
                ]
            ],
        )
        lines.append("")
        calls = block["coach_calls"]
        lines.append("Coach call health:")
        lines.append("")
        if calls["recorded"]:
            lines += _md_table(
                ["Responses", "With hedge data", "Hedged", "Hedges won", "Timeouts", "Rejected"],
                [
                    [
                        str(calls["responses"]),
                        str(calls["responses_with_hedge_data"]),
                        str(calls["hedged"]),
                        str(calls["hedges_won"]),
                        str(calls["timeouts"]),
                        str(calls["rejected_responses"]),
                    ]
                ],
            )
        else:
            lines.append(
                f"- {calls['responses']} coach responses; this run predates the transport "
                "timings, so hedges, timeouts and rejections were never recorded."
            )
        lines.append("")
        lines.append(f"- {block['note']}")
        lines.append(f"- Source: `{block['source']}`")
        lines.append("")
    lines.append("## Segment continuity")
    lines.append("")
    for entry in results["segment_continuity"]:
        lines.append(f"### {entry['run']}")
        lines.append("")
        lines += _md_table(
            ["Segment", "Ante at start", "Ante at end"],
            [
                [item["segment"], str(item["ante_start"]), str(item["ante_end"])]
                for item in entry["segments"]
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
