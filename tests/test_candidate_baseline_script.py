from __future__ import annotations

from collections import Counter
import importlib.util
from pathlib import Path

import pytest

from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.strategy_tuning import StrategyTuning
from state_factory import state


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_candidate_baselines.py"
    spec = importlib.util.spec_from_file_location("evaluate_candidate_baselines_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_candidate_baseline_reports_ante_six_survival_metric() -> None:
    module = _load_script()
    results = [
        {"complete": True, "won": False, "antes_cleared": 5, "survived_to_ante_6": True, "ante": 6, "round": 17, "decisions": 10, "best_hand_score": 100},
        {"complete": True, "won": True, "antes_cleared": 8, "survived_to_ante_6": True, "ante": 9, "round": 24, "decisions": 20, "best_hand_score": 1000},
        {"complete": True, "won": False, "antes_cleared": 3, "survived_to_ante_6": False, "ante": 4, "round": 12, "decisions": 8, "best_hand_score": 10},
    ]

    summary = module.summarize_results(
        results, elapsed=1.0, terminal_reasons=Counter({"won": 1, "lost": 2})
    )

    assert summary["survived_to_ante_6"] == 2
    assert summary["win_rate"] == pytest.approx(1 / 3)
    assert summary["survival_to_ante_6_rate"] == 2 / 3
    assert summary["mean_antes_cleared"] == 16 / 3
    assert summary["antes_cleared_deciles"]["p50"] == 5
    assert summary["maximum_ante"] == 9
    assert summary["best_hand_score"] == 1000
    assert summary["max_log10_best_hand_score"] == 3
    assert summary["mean_log10_best_hand_score"] == 2


def test_candidate_baseline_cli_has_only_public_control_policies() -> None:
    parser = _load_script().build_parser()

    args = parser.parse_args(["--policy", "greedy"])

    assert args.policy == "greedy"
    assert args.policy_timeout == 5.0
    assert args.tuning_json == StrategyTuning().canonical_json()
    assert args.seed_provenance == "development"
    assert args.seed_start == 901
    assert not hasattr(args, "model")
    assert not hasattr(args, "search")


def test_candidate_baseline_cli_exposes_public_belief_tactical_control() -> None:
    parser = _load_script().build_parser()

    args = parser.parse_args(["--policy", "tactical"])

    assert args.policy == "tactical"


def test_candidate_baseline_cli_supports_tuning_fitness_output() -> None:
    parser = _load_script().build_parser()

    args = parser.parse_args(["--policy", "strategic", "--fitness-only"])

    assert args.fitness_only is True


def test_candidate_baseline_rejects_panel_before_backend_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "evaluate_candidate_baselines.py",
            "--policy",
            "greedy",
            "--seed-start",
            "1",
            "--seeds",
            "20",
            "--seed-provenance",
            "development",
        ],
    )
    monkeypatch.setattr(
        module,
        "verify_jackdaw_runtime",
        lambda: pytest.fail("backend verification must not run"),
    )

    with pytest.raises(SystemExit, match="overlaps protected tuning"):
        module.main()


def test_terminal_projection_persists_public_loss_context() -> None:
    module = _load_script()
    raw = state("GAME_OVER", money=7)
    raw["ante_num"] = 3
    raw["round_num"] = 8
    raw["round"].update(
        chips=275,
        hands_left=0,
        discards_left=2,
        hands_played=4,
        discards_used=2,
    )
    raw["blinds"]["small"]["status"] = "DEFEATED"
    raw["blinds"]["big"]["status"] = "CURRENT"

    projection = module.terminal_projection(to_public_observation(raw))

    assert projection == {
        "schema_version": 2,
        "phase": "GAME_OVER",
        "won": False,
        "antes_cleared": 2,
        "ante": 3,
        "round": 8,
        "money": 7,
        "chips": 275,
        "target": 450,
        "chip_margin": -175,
        "hands_left": 0,
        "discards_left": 2,
        "hands_played": 4,
        "discards_used": 2,
        "terminal_blind": {
            "kind": "BIG",
            "status": "CURRENT",
            "name": "Big Blind",
            "effect": "",
            "score": 450,
            "tag_name": "",
            "tag_effect": "",
        },
        "visible_boss": {
            "kind": "BOSS",
            "status": "UPCOMING",
            "name": "The Head",
            "effect": "Debuffs hearts",
            "score": 600,
            "tag_name": "",
            "tag_effect": "",
        },
    }
