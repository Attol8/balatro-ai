from __future__ import annotations

from collections import Counter
import importlib.util
from pathlib import Path

from balatro_ai_v2.balatrobot.adapter import to_public_observation
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
        {"complete": True, "won": False, "survived_to_ante_6": True, "ante": 6, "round": 17, "decisions": 10},
        {"complete": True, "won": True, "survived_to_ante_6": True, "ante": 9, "round": 24, "decisions": 20},
        {"complete": True, "won": False, "survived_to_ante_6": False, "ante": 4, "round": 12, "decisions": 8},
    ]

    summary = module.summarize_results(
        results, elapsed=1.0, terminal_reasons=Counter({"won": 1, "lost": 2})
    )

    assert summary["survived_to_ante_6"] == 2
    assert summary["survival_to_ante_6_rate"] == 2 / 3


def test_candidate_baseline_cli_has_only_public_control_policies() -> None:
    parser = _load_script().build_parser()

    args = parser.parse_args(["--policy", "greedy"])

    assert args.policy == "greedy"
    assert args.policy_timeout == 5.0
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
        "schema_version": 1,
        "phase": "GAME_OVER",
        "won": False,
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
