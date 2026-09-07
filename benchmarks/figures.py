"""Deterministic SVG figures for the recorded evidence.

Matplotlib only, Agg backend, no timestamps in the output: the same evidence
always produces byte-comparable SVGs.  Colours come from a validated
colourblind-safe palette (blue/orange, all-pairs CVD deltaE 24.7), with marker shape
carrying identity as well as hue so the figures survive greyscale printing.  Each
figure paints its own light surface, so it stays legible on a dark page.
"""

from __future__ import annotations

import random
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from . import EVIDENCE_ROOT, SETTING  # noqa: E402
from .baselines import BaselinePanel, load_panels  # noqa: E402
from .tables import CoachedRow, built_in_coached_rows  # noqa: E402
from .trajectories import (  # noqa: E402
    Trajectory,
    load_astra_low,
    load_astra_low_headless,
    load_astra_low_panel_seed,
)

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SERIES_BASELINE = "#2a78d6"
SERIES_COACHED = "#eb6834"

WIN_ANTE = 8
LABEL_BOX = {"boxstyle": "round,pad=0.2", "facecolor": SURFACE, "edgecolor": "none"}
WIN_ANTE_REACHED = WIN_ANTE + 1
ENDLESS_FOOTNOTES = (
    "Each Astra-low game continued in endless mode after clearing Ante 8.",
    "A hollow star marks a coached game played on a seed from the heuristic panel.",
)


def _coached_annotation(row: CoachedRow) -> str:
    """``n=1`` for a plain coached game, flagged when it ran on past the win."""

    label = f"n={row.games}"
    if row.ante8_clears and max(row.antes_reached) > WIN_ANTE_REACHED:
        return f"{label}, endless after win"
    return label


def _configure() -> None:
    plt.rcParams["svg.hashsalt"] = "balatro-ai"
    plt.rcParams["svg.fonttype"] = "none"
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.size"] = 9


def _save(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, format="svg", facecolor=SURFACE, metadata={"Date": None})
    plt.close(fig)
    return path


def _style_axes(axes: plt.Axes) -> None:
    axes.set_facecolor(SURFACE)
    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axes.spines[side].set_color(AXIS)
        axes.spines[side].set_linewidth(1.0)
    axes.tick_params(colors=INK_MUTED, labelsize=8, length=3)
    for label in axes.get_xticklabels() + axes.get_yticklabels():
        label.set_color(INK_SECONDARY)


def ante_reached_by_policy(
    panels: list[BaselinePanel],
    coached: list[CoachedRow],
    path: Path,
) -> Path:
    """Headline figure: one row per policy, a dot for every completed game."""

    _configure()
    jitter = random.Random(0)
    repeated_coached = {
        label for label, count in Counter(row.label for row in coached).items() if count > 1
    }
    rows: list[tuple[str, list[int], bool, str, bool]] = [
        (
            f"{row.label}, seed {row.seed_label}" if row.label in repeated_coached else row.label,
            list(row.antes_reached),
            True,
            _coached_annotation(row),
            row.panel_seed,
        )
        for row in coached
    ]
    rows += [
        (
            f"{panel.policy} ({panel.run_dir})"
            if panel.policy.startswith("strategic")
            else panel.policy,
            [game.ante_reached for game in panel.games if game.completed],
            False,
            "",
            False,
        )
        for panel in panels
    ]
    height = 2.2 + 0.36 * len(rows)
    fig, axes = plt.subplots(figsize=(8.0, height), dpi=100)
    _style_axes(axes)
    axes.xaxis.grid(True, color=GRID, linewidth=0.8)
    axes.set_axisbelow(True)

    positions = list(range(len(rows) - 1, -1, -1))
    for position, (label, antes, is_coached, annotation, panel_seed) in zip(positions, rows):
        if not antes:
            continue
        colour = SERIES_COACHED if is_coached else SERIES_BASELINE
        offsets = [position + jitter.uniform(-0.22, 0.22) for _ in antes]
        spread = [ante + jitter.uniform(-0.12, 0.12) for ante in antes]
        if is_coached:
            axes.plot(
                antes,
                [position] * len(antes),
                linestyle="none",
                marker="*",
                markersize=15,
                markerfacecolor=SURFACE if panel_seed else colour,
                markeredgecolor=colour if panel_seed else SURFACE,
                markeredgewidth=1.6 if panel_seed else 1.2,
                color=colour,
                zorder=4,
            )
            # A star at the far right of the scale has no room for a label
            # beside it, so that one is labelled to its left instead.
            crowded = max(antes) > WIN_ANTE_REACHED
            axes.annotate(
                annotation,
                (max(antes), position),
                textcoords="offset points",
                xytext=(-14, -3) if crowded else (14, -3),
                ha="right" if crowded else "left",
                color=INK_SECONDARY,
                fontsize=8,
            )
        else:
            axes.plot(
                spread,
                offsets,
                linestyle="none",
                marker="o",
                markersize=6,
                color=colour,
                alpha=0.75,
                markeredgecolor=SURFACE,
                markeredgewidth=0.8,
                zorder=3,
            )
            median = (
                sorted(antes)[len(antes) // 2]
                if len(antes) % 2
                else (sorted(antes)[len(antes) // 2 - 1] + sorted(antes)[len(antes) // 2]) / 2
            )
            axes.plot(
                [median, median],
                [position - 0.36, position + 0.36],
                color=SURFACE,
                linewidth=5.0,
                solid_capstyle="butt",
                zorder=5,
            )
            axes.plot(
                [median, median],
                [position - 0.36, position + 0.36],
                color=INK,
                linewidth=2.0,
                solid_capstyle="butt",
                zorder=6,
            )
        del label

    axes.axvline(WIN_ANTE, color=INK_MUTED, linewidth=1.4, linestyle=(0, (4, 3)), zorder=2)
    axes.annotate(
        "Ante 8 = win",
        (WIN_ANTE, len(rows) - 0.35),
        textcoords="offset points",
        xytext=(5, 0),
        color=INK_SECONDARY,
        fontsize=8,
    )
    axes.set_yticks(positions)
    axes.set_yticklabels([label for label, _, _, _, _ in rows])
    axes.set_ylim(-0.8, len(rows) - 0.1)
    axes.set_xlabel("Ante reached", color=INK_SECONDARY)
    axes.set_xticks(range(1, max(max(antes) for _, antes, _, _, _ in rows if antes) + 1))

    total_baseline = sum(len(antes) for _, antes, coach, _note, _seed in rows if not coach)
    total_coached = sum(len(antes) for _, antes, coach, _note, _seed in rows if coach)
    on_panel_seed = sum(len(antes) for _, antes, coach, _note, seed in rows if coach and seed)
    fig.text(
        0.012,
        1 - 0.34 / height,
        "How far each policy got in real Balatro",
        ha="left",
        va="top",
        color=INK,
        fontsize=13,
        fontweight="bold",
    )
    fig.text(
        0.012,
        1 - 0.62 / height,
        f"{SETTING}",
        ha="left",
        va="top",
        color=INK_SECONDARY,
        fontsize=9,
    )
    fig.text(
        0.012,
        1 - 0.82 / height,
        f"{total_baseline} completed heuristic games on seeds D0000000-D0000019; "
        f"{total_coached} coached game{'' if total_coached == 1 else 's'}, "
        f"{on_panel_seed} of them on a panel seed",
        ha="left",
        va="top",
        color=INK_SECONDARY,
        fontsize=9,
    )
    handles = [
        plt.Line2D(
            [],
            [],
            linestyle="none",
            marker="o",
            markersize=6,
            color=SERIES_BASELINE,
            label="Heuristic baseline game",
        ),
        plt.Line2D(
            [],
            [],
            linestyle="none",
            marker="*",
            markersize=13,
            color=SERIES_COACHED,
            label="Coached game (n=1, not a win rate)",
        ),
        plt.Line2D(
            [],
            [],
            linestyle="none",
            marker="*",
            markersize=13,
            markerfacecolor=SURFACE,
            markeredgecolor=SERIES_COACHED,
            markeredgewidth=1.6,
            color=SERIES_COACHED,
            label="Coached game on a panel seed",
        ),
        plt.Line2D([], [], color=INK, linewidth=2.0, label="Median ante"),
    ]
    legend = axes.legend(
        handles=handles,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.10 - 4.0 / (height * 100)),
        ncol=2,
        frameon=False,
        fontsize=8,
        handletextpad=0.6,
        columnspacing=2.0,
    )
    for text in legend.get_texts():
        text.set_color(INK_SECONDARY)
    for offset, footnote in enumerate(reversed(ENDLESS_FOOTNOTES)):
        fig.text(
            0.012,
            (0.10 + 0.16 * offset) / height,
            footnote,
            ha="left",
            va="bottom",
            color=INK_MUTED,
            fontsize=8,
        )
    fig.tight_layout(rect=(0, 0.95 / height, 1, 1 - 1.0 / height))
    return _save(fig, path)


def score_vs_requirement(runs: list[tuple[Trajectory, str]], path: Path) -> Path:
    """Chip requirement versus the best hand actually scored, per blind, per run."""

    _configure()
    fig, axes_column = plt.subplots(
        len(runs), 1, figsize=(8.0, 3.4 * len(runs) + 0.9), dpi=100, squeeze=False
    )
    for axes, (trajectory, title) in zip(axes_column[:, 0], runs):
        _style_axes(axes)
        axes.set_yscale("log")
        axes.yaxis.grid(True, color=GRID, linewidth=0.8)
        axes.set_axisbelow(True)
        blinds = trajectory.blind_series()
        xs = list(range(len(blinds)))
        axes.step(
            xs,
            [blind.requirement for blind in blinds],
            where="mid",
            color=INK_MUTED,
            linewidth=2.0,
            label="Blind requirement (chips)",
            zorder=3,
        )
        axes.plot(
            xs,
            [blind.best_hand_score for blind in blinds],
            linestyle="none",
            marker="o",
            markersize=6,
            color=SERIES_BASELINE,
            markeredgecolor=SURFACE,
            markeredgewidth=0.8,
            label="Best single hand in the blind",
            zorder=4,
        )
        ticks, labels = [], []
        seen: set[int] = set()
        for index, blind in enumerate(blinds):
            if blind.ante not in seen:
                seen.add(blind.ante)
                ticks.append(index)
                labels.append(f"A{blind.ante}")
        axes.set_xticks(ticks)
        axes.set_xticklabels(labels)
        final = blinds[-1]
        for index, blind in enumerate(blinds):
            if blind.ante == WIN_ANTE and blind.blind == "BOSS":
                axes.annotate(
                    "Ante 8 boss",
                    (index, blind.requirement),
                    textcoords="offset points",
                    xytext=(-12, 20),
                    ha="right",
                    color=INK_SECONDARY,
                    fontsize=8,
                    bbox=LABEL_BOX,
                    arrowprops=dict(arrowstyle="-", color=AXIS, linewidth=0.8),
                )
        axes.plot(
            [len(blinds) - 1],
            [final.best_hand_score],
            linestyle="none",
            marker="X",
            markersize=10,
            color=SERIES_COACHED,
            markeredgecolor=SURFACE,
            markeredgewidth=1.0,
            zorder=5,
            label=f"Ante {final.ante} loss (endless)",
        )
        axes.annotate(
            f"best hand {final.best_hand_score:,.0f}",
            (len(blinds) - 1, final.best_hand_score),
            textcoords="offset points",
            xytext=(-10, 20),
            ha="right",
            color=INK_SECONDARY,
            fontsize=8,
            bbox=LABEL_BOX,
            arrowprops=dict(arrowstyle="-", color=AXIS, linewidth=0.8),
        )
        axes.set_title(title, loc="left", color=INK, fontsize=10, fontweight="bold", pad=8)
        axes.set_ylabel("Chips (log)", color=INK_SECONDARY)
        legend = axes.legend(loc="upper left", frameon=False, fontsize=8)
        for text in legend.get_texts():
            text.set_color(INK_SECONDARY)
    axes_column[-1, 0].set_xlabel("Blinds played, labelled by ante", color=INK_SECONDARY)
    fig.suptitle(
        "Score delivered against the blind it had to beat",
        x=0.012,
        y=0.99,
        ha="left",
        color=INK,
        fontsize=13,
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.955))
    return _save(fig, path)


def render_all(out_dir: Path, evidence_root: Path | None = None) -> list[Path]:
    """Write all three figures into ``out_dir/figures``."""

    root = evidence_root or EVIDENCE_ROOT
    figures_dir = out_dir / "figures"
    panels = load_panels(root)
    coached = built_in_coached_rows(root)
    runs = [
        (
            load_astra_low_headless(root),
            "Astra low, seed TAF7DNTX - headless, cleared Ante 8, lost in endless Ante 13",
        ),
        (
            load_astra_low_panel_seed(root),
            "Astra low, seed D0000000 - panel seed, cleared Ante 8, lost in endless Ante 10",
        ),
        (
            load_astra_low(root),
            "Astra low, seed 2K9H9HN - cleared Ante 8, lost in endless Ante 11",
        ),
    ]
    return [
        ante_reached_by_policy(panels, coached, figures_dir / "ante-reached-by-policy.svg"),
        score_vs_requirement(runs, figures_dir / "score-vs-requirement.svg"),
    ]


__all__ = [
    "ante_reached_by_policy",
    "render_all",
    "score_vs_requirement",
]
