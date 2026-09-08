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
from .baselines import BaselinePanel, load_panels, panel_seeds
from .trajectories import (
    ASTRA_LOW_HEADLESS,
    ASTRA_LOW_PANEL_SEED,
    ASTRA_LOW_RECORDED,
    ASTRA_LOW_SUPERVISED,
    TERRA_LOW,
    TERRA_LOW_FIRST_ATTEMPT,
    Trajectory,
    load_astra_low,
    load_segmented_run,
    segment_ante_bounds,
)

TABLE_A_TITLE = f"Real-game results, {SETTING}"
TABLE_B_TITLE = "Scoring-engine exactness"
TABLE_C_TITLE = "Decision mix in the Astra-low runs"
TABLE_D_TITLE = "Same seed, D0000000"
PANEL_SEED = "D0000000"
ASTRA_ROUND_PRODUCTION = "astra-round-production-XV2MP8L5"

# Newest game first. The index breaks ties in Table A's ante ordering, so when two
# runs reached the same ante the later, cleaner game is listed first.
COACHED_RUNS: tuple[tuple[str, str], ...] = (
    (
        ASTRA_ROUND_PRODUCTION,
        "single game, seed XV2MP8L5: round-production advice at 9395d7a; "
        "cleared Ante 8, then lost at the ante 12 boss The Arm; "
        "one recovered RPC timeout, no rejected replies or restarts",
    ),
    (
        TERRA_LOW,
        "single game, seed QD3F4XVW: visible game, endless; lost at the ante 2 boss "
        "The Mouth after locking the round to High Card",
    ),
    (
        TERRA_LOW_FIRST_ATTEMPT,
        "first attempt on seed QD3F4XVW: lost at the ante 2 boss The Mouth; a runner "
        "fault, since fixed, selected the boss while a skip tag's Mega Buffoon Pack "
        "was opening, so that pack was never offered",
    ),
    (
        ASTRA_LOW_RECORDED,
        "supervised end to end, one automatic restart, game visible at speed 2, recorded",
    ),
    (
        ASTRA_LOW_PANEL_SEED,
        "visible game, endless; on the baseline panel seed; cleared Ante 8, lost at ante 10",
    ),
    (
        ASTRA_LOW_HEADLESS,
        "single game, seed TAF7DNTX: headless, endless; cleared Ante 8, then lost at ante 13",
    ),
    (ASTRA_LOW_SUPERVISED, ""),
)
# Table C, the score figure and the segment-continuity report cover the Astra-low
# runs; the terra games are rows of Table A and stars in the headline figure only.
DECISION_MIX_RUNS = frozenset(
    {ASTRA_LOW_RECORDED, ASTRA_LOW_PANEL_SEED, ASTRA_LOW_HEADLESS, ASTRA_LOW_SUPERVISED}
)
# Distinguish repeat attempts and changed advice policies from historical runs.
LABEL_SUFFIXES = {
    TERRA_LOW_FIRST_ATTEMPT: ", first attempt",
    ASTRA_ROUND_PRODUCTION: ", round-production advice (9395d7a)",
}
_MODEL_FAMILIES = {"astra": "Astra", "terra": "Terra"}
# Only the newest runs are written out in full in results.md; results.json keeps them all.
RENDERED_MIXES = 2
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
    panel_seed: bool = False
    recency: int = 0

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
        "panel_seed": row.panel_seed,
        "recency": row.recency,
        "seconds": row.seconds,
        "peak_hand_score": row.peak_hand_score,
        "notes": [row.note],
        "sources": list(row.sources),
    }


def _coached_label(manifest: dict) -> str:
    """``Astra low (gpt-6-astra)``: the model family, its effort and the exact model id."""

    model = manifest["requested_model"]
    family = next((name for key, name in _MODEL_FAMILIES.items() if key in model), model)
    return f"{family} {manifest['requested_reasoning_effort']} ({model})"


def _coached_row_from_result(
    run_dir: Path,
    note: str,
    known_panel_seeds: frozenset[str],
    recency: int = 0,
    label_suffix: str = "",
) -> CoachedRow:
    """Build one coached row from a run directory's ``result.json``/``manifest.json``."""

    result = json.loads((run_dir / "result.json").read_text())
    manifest = json.loads((run_dir / "manifest.json").read_text())
    seed = manifest["seed"]
    return CoachedRow(
        label=_coached_label(manifest) + label_suffix,
        model=manifest["requested_model"],
        reasoning_effort=manifest["requested_reasoning_effort"],
        seeds=[seed],
        games=1,
        ante8_clears=1 if result["won"] else 0,
        antes_reached=[int(result["ante_reached"])],
        decisions=int(result["decisions"]),
        coach_requests=int(result["coach_requests"]),
        seconds=float(result["seconds"]),
        peak_hand_score=float(result["peak_hand_score"]),
        note=note,
        sources=[f"evidence/{run_dir.name}"],
        followup_actions=_optional_int(result, "followup_actions"),
        forced_actions=_optional_int(result, "forced_actions"),
        coach_timeouts=_optional_int(result, "coach_timeouts"),
        panel_seed=seed in known_panel_seeds,
        recency=recency,
    )


def _optional_int(result: dict, key: str) -> int | None:
    value = result.get(key)
    return None if value is None else int(value)


def built_in_coached_rows(evidence_root: Path | None = None) -> list[CoachedRow]:
    """The published coached runs, by ante reached (descending), newest first on a tie."""

    root = evidence_root or EVIDENCE_ROOT
    known = panel_seeds(root)
    ante8 = json.loads((root / ASTRA_LOW_SUPERVISED / "ante-8-result.json").read_text())
    supervised_note = (
        "single game, seed 2K9H9HN: cleared Ante 8 "
        f"({ante8['decisions']} decisions, ante {ante8['ante_reached']}), "
        "then continued in endless and lost at ante 11"
    )
    rows = [
        _coached_row_from_result(
            root / directory,
            note or supervised_note,
            known,
            recency=recency,
            label_suffix=LABEL_SUFFIXES.get(directory, ""),
        )
        for recency, (directory, note) in enumerate(COACHED_RUNS)
    ]
    rows.sort(key=lambda row: (-max(row.antes_reached), row.recency))
    return rows


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


def _table_a(
    panels: list[BaselinePanel],
    coached: list[CoachedRow],
    table_d: dict,
    table_c: dict,
) -> dict:
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
            _coached_seeds_footnote(coached),
            _terra_footnote(),
            _panel_seed_footnote(table_d),
            _recorded_run_footnote(table_c),
            "Coached rows are sorted by ante reached (descending); when two runs reached the "
            "same ante the later, cleaner game is listed first.",
            f"The {PANEL_SEED} run was restarted three times at safe moments and once restored "
            "from Balatro's autosave after an operating-system kill; no game state or trajectory "
            f"was edited by hand. See evidence/astra-low-{PANEL_SEED}/README.md.",
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


def _decision_mix(trajectory: Trajectory, result: dict, recency: int = 0) -> dict:
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
        "recency": recency,
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
            "rpc_timeouts": calls.rpc_timeouts,
            "recovered_transitions": calls.recovered_transitions,
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


def _table_c(runs: list[tuple[Trajectory, dict, int]]) -> dict:
    blocks = [_decision_mix(trajectory, result, recency) for trajectory, result, recency in runs]
    rendered = [block["run"] for block in sorted(blocks, key=lambda block: block["recency"])][
        :RENDERED_MIXES
    ]
    return {
        "title": TABLE_C_TITLE,
        "blocks": blocks,
        "rendered_runs": rendered,
        "note": (
            "results.md writes out the two newest runs in full; every run's mix is in "
            "results.json under table_c.blocks."
        ),
    }


def _coached_seeds_footnote(coached: list[CoachedRow]) -> str:
    outside = list(dict.fromkeys(row.seed_label for row in coached if not row.panel_seed))
    on_panel = list(dict.fromkeys(row.seed_label for row in coached if row.panel_seed))
    return (
        f"Each coached row is a single game: {', '.join(outside)} are seeds outside the "
        f"D0000000-D0000019 baseline panel, {', '.join(on_panel)} is that panel's first seed. "
        "They are demonstrations, not win-rate estimates."
    )


def _terra_footnote() -> str:
    return (
        "The two gpt-5.6-terra rows are the same seed as the recorded gpt-6-astra game "
        "QD3F4XVW, played with the same tools, prompts and limits; both lost at the ante 2 "
        "boss. One seed at one effort level is not a model ranking. They are not part of "
        "Table C or the score figure, which cover the Astra-low runs. See "
        f"evidence/{TERRA_LOW}/README.md."
    )


def _recorded_run_footnote(table_c: dict) -> str:
    block = next(block for block in table_c["blocks"] if block["run"] == ASTRA_LOW_RECORDED)
    rejected = block["coach_calls"]["rejected_responses"]
    return (
        "Seed QD3F4XVW was played end to end by the supervisor: one automatic restart after "
        "the mod refused a boss reroll, no operator intervention, and "
        f"{rejected} rejected replies. Hieroglyph and Petroglyph each lowered the ante by one, "
        "so blinds at antes 9 and 10 were played twice."
    )


def _panel_seed_footnote(table_d: dict) -> str:
    best = table_d["best_baseline"]
    coached = next(row for row in table_d["rows"] if row["kind"] == "coached")
    return (
        f"On seed {PANEL_SEED} the best heuristic ({best['player']}) reached ante "
        f"{best['ante_reached']} with a {best['peak_hand_score']:,.0f} peak hand; the coached "
        f"run reached ante {coached['ante_reached']} with {coached['peak_hand_score']:,.0f}."
    )


def _table_d(panels: list[BaselinePanel], coached: list[CoachedRow]) -> dict:
    """Every player that met seed D0000000, best first."""

    rows: list[dict] = []
    for panel in panels:
        for game in panel.games:
            if game.seed != PANEL_SEED:
                continue
            rows.append(
                {
                    "player": panel.policy,
                    "run": panel.run_dir,
                    "kind": "baseline",
                    "status": game.status,
                    "ante_reached": game.ante_reached,
                    "peak_hand_score": game.peak_hand_score,
                }
            )
    for row in coached:
        if PANEL_SEED not in row.seeds:
            continue
        rows.append(
            {
                "player": f"{row.label} + tools",
                "run": row.sources[0] if row.sources else "",
                "kind": "coached",
                "status": "ante 8 cleared, lost in endless",
                "ante_reached": max(row.antes_reached),
                "peak_hand_score": row.peak_hand_score,
            }
        )
    rows.sort(key=lambda row: (-row["ante_reached"], -row["peak_hand_score"], row["run"]))
    best_baseline = max(
        (row for row in rows if row["kind"] == "baseline"),
        key=lambda row: (row["ante_reached"], row["peak_hand_score"]),
    )
    return {
        "title": TABLE_D_TITLE,
        "seed": PANEL_SEED,
        "rows": rows,
        "best_baseline": best_baseline,
        "note": (
            f"Every heuristic panel played {PANEL_SEED} as its first seed, so this is the same "
            "game dealt to every player. One seed is not a rate."
        ),
        "source": "evidence/baselines/*/summary.json",
    }


def build_results(
    evidence_root: Path | None = None,
    extra_runs: list[Path] | None = None,
) -> dict:
    """Assemble every table into one JSON-serialisable dict."""

    root = evidence_root or EVIDENCE_ROOT
    panels = load_panels(root)
    builtin = built_in_coached_rows(root)
    mixed = [row for row in builtin if row.sources[0].rsplit("/", 1)[-1] in DECISION_MIX_RUNS]
    trajectories = [load_segmented_run(root / row.sources[0].rsplit("/", 1)[-1]) for row in mixed]
    low = load_astra_low(root)
    runs = [
        (
            trajectory,
            json.loads((root / trajectory.run_id / "result.json").read_text()),
            row.recency,
        )
        for trajectory, row in zip(trajectories, mixed)
    ]
    coached = builtin + load_extra_runs(list(extra_runs or []))
    table_c = _table_c(runs)
    table_d = _table_d(panels, coached)
    return {
        "setting": SETTING,
        "evidence_root": "evidence",
        "table_a": _table_a(panels, coached, table_d, table_c),
        "table_b": _table_b(low, root),
        "table_c": table_c,
        "table_d": table_d,
        "segment_continuity": [
            {
                "run": trajectory.run_id,
                "segments": [
                    {"segment": segment, "ante_start": start, "ante_end": end}
                    for segment, start, end in segment_ante_bounds(trajectory)
                ],
            }
            for trajectory in trajectories
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
    rendered = set(table_c["rendered_runs"])
    lines.append(table_c["note"])
    lines.append("")
    for block in table_c["blocks"]:
        if block["run"] not in rendered:
            continue
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
                [
                    "Responses",
                    "With hedge data",
                    "Hedged",
                    "Hedges won",
                    "Timeouts",
                    "Rejected",
                    "Game-reply timeouts recovered",
                ],
                [
                    [
                        str(calls["responses"]),
                        str(calls["responses_with_hedge_data"]),
                        str(calls["hedged"]),
                        str(calls["hedges_won"]),
                        str(calls["timeouts"]),
                        str(calls["rejected_responses"]),
                        f"{calls['recovered_transitions']} of {calls['rpc_timeouts']}",
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
    skipped = [block for block in table_c["blocks"] if block["run"] not in rendered]
    if skipped:
        lines.append(
            "Not written out here: "
            + ", ".join(
                f"{block['run']} ({block['total_transitions']} decisions)" for block in skipped
            )
            + " - see `results.json`."
        )
        lines.append("")
    table_d = results["table_d"]
    lines += [f"## Table D - {table_d['title']}", ""]
    lines += _md_table(
        ["Player", "Run", "Ante reached", "Peak hand", "Outcome"],
        [
            [
                f"**{row['player']}**" if row["kind"] == "coached" else row["player"],
                f"`{row['run']}`",
                str(row["ante_reached"]),
                f"{row['peak_hand_score']:,.0f}",
                row["status"],
            ]
            for row in table_d["rows"]
        ],
    )
    lines.append("")
    lines.append(f"- {table_d['note']}")
    lines.append(f"- Source: `{table_d['source']}`")
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
