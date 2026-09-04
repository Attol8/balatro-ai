from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from balatro_ai_v2.actions import LeaveShop
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.strategy_engine import RunGoal
from balatro_ai_v2.strategy_teacher import (
    StrategyRolloutTarget,
    StrategyTeacherCandidate,
    StrategyTeacherDraft,
)
from balatro_ai_v2.strategy_tuning import StrategyTuning
from state_factory import state


def _load_script():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "evaluate_determinized_search.py"
    )
    spec = importlib.util.spec_from_file_location(
        "evaluate_determinized_search_script", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_search_evaluator_exposes_opt_in_strategy_protocol() -> None:
    args = (
        _load_script()
        .build_parser()
        .parse_args(
            [
                "--strategy-options",
                "--include-reorders",
                "--seed-provenance",
                "evaluator_secret",
                "--strategy-shadow-model",
                "model.pt",
                "--record-shadow-decisions",
            ]
        )
    )

    assert args.strategy_options
    assert args.include_reorders
    assert args.seed_provenance == "evaluator_secret"
    assert args.strategy_shadow_model == Path("model.pt")
    assert args.record_shadow_decisions


def test_search_evaluator_keeps_strategy_mode_disabled_by_default() -> None:
    args = _load_script().build_parser().parse_args([])

    assert not args.strategy_options
    assert not args.include_reorders
    assert args.seed_provenance == "development"
    assert args.seed_start == 901


def test_search_evaluator_exposes_terminal_action_protocol() -> None:
    args = (
        _load_script()
        .build_parser()
        .parse_args(
            [
                "--success-terminal-actions",
                "--success-terminal-max-samples",
                "10",
                "--success-terminal-family-alpha",
                "0.025",
                "--success-terminal-max-roots",
                "48",
            ]
        )
    )

    assert args.success_terminal_actions
    assert args.success_terminal_max_samples == 10
    assert args.success_terminal_family_alpha == 0.025
    assert args.success_terminal_max_roots == 48


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        (
            ["--success-teacher", "--teacher-jsonl", "teacher.jsonl"],
            "mutually exclusive",
        ),
        (["--teacher-jsonl", "teacher.jsonl"], "cannot emit teacher JSONL"),
        (["--strategy-shadow-model", "model.pt"], "cannot load a shadow model"),
        (
            [
                "--seed-start",
                "701",
                "--seeds",
                "200",
                "--seed-provenance",
                "gate",
            ],
            "development-only",
        ),
    ],
)
def test_terminal_action_cli_rejects_unsafe_combinations_before_backend_work(
    monkeypatch: pytest.MonkeyPatch,
    extra: list[str],
    message: str,
) -> None:
    module = _load_script()
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["evaluate_determinized_search.py", "--success-terminal-actions", *extra],
    )
    monkeypatch.setattr(
        module,
        "verify_jackdaw_runtime",
        lambda: pytest.fail("backend verification must not run"),
    )

    with pytest.raises(SystemExit, match=message):
        module.main()


def test_search_evaluator_exposes_public_teacher_output() -> None:
    args = (
        _load_script()
        .build_parser()
        .parse_args(["--strategy-options", "--teacher-jsonl", "teacher.jsonl"])
    )

    assert args.teacher_jsonl == Path("teacher.jsonl")


def test_complete_run_drafts_receive_opaque_groups_and_terminal_labels() -> None:
    module = _load_script()
    observation = to_public_observation(state("SHOP"))
    draft = StrategyTeacherDraft(
        observation=observation,
        candidates=(
            StrategyTeacherCandidate(
                LeaveShop(),
                None,
                (StrategyRolloutTarget(1, 0, 0, 2, 3),),
            ),
        ),
        selected_index=0,
        baseline_index=0,
        goal=RunGoal.VICTORY,
        teacher_config_digest="2" * 64,
    )
    rows = [
        {
            "complete": True,
            "won": False,
            "antes_cleared": 3,
            "best_hand_score": 10_000,
            "search": {"rejected_rollouts": 0},
            "_teacher_drafts": (draft,),
        }
    ]

    records, status = module._finalize_teacher_records(rows, enabled=True)

    assert status == "written"
    assert records[0].run_group == "run-000000"
    assert records[0].terminal_ante == 3
    assert "_teacher_drafts" not in rows[0]


def test_incomplete_panel_discards_every_teacher_draft() -> None:
    module = _load_script()
    rows = [{"complete": False, "_teacher_drafts": ()}]

    records, status = module._finalize_teacher_records(rows, enabled=True)

    assert not records
    assert status == "discarded_incomplete_panel"
    assert "_teacher_drafts" not in rows[0]


def test_rejected_rollout_discards_the_entire_teacher_panel() -> None:
    module = _load_script()
    rows = [
        {
            "complete": True,
            "search": {"rejected_rollouts": 1},
            "_teacher_drafts": (),
        },
        {
            "complete": True,
            "search": {"rejected_rollouts": 0},
            "_teacher_drafts": (),
        },
    ]

    records, status = module._finalize_teacher_records(rows, enabled=True)

    assert not records
    assert status == "discarded_rejected_panel"
    assert all("_teacher_drafts" not in row for row in rows)


def test_shadow_diagnostics_derive_action_agreement_from_current_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()

    class FakeDecision:
        unavailable_reason = None
        preferred_action = LeaveShop()
        control_action = LeaveShop()
        preferred_intent = None
        control_intent = None
        recommendation_clears_margin = True
        calibrated_heads = ("policy", "next_boss")

        @staticmethod
        def as_dict() -> dict[str, object]:
            return {"recorded": True}

    class FakeShadow:
        decisions = [FakeDecision()]

    monkeypatch.setattr(module, "ShadowStrategyPolicy", FakeShadow)

    diagnostic = module._shadow_run_diagnostics(FakeShadow(), record_decisions=True)

    assert diagnostic == {
        "enabled": True,
        "decisions": 1,
        "unavailable": 0,
        "agreements": 1,
        "margin_signals": 1,
        "calibrated_head_decisions": {"policy": 1, "next_boss": 1},
        "records": [{"recorded": True}],
    }


def test_success_teacher_coverage_requires_distinct_winning_groups() -> None:
    module = _load_script()
    observation = to_public_observation(state("SHOP"))
    draft = StrategyTeacherDraft(
        observation=observation,
        candidates=(
            StrategyTeacherCandidate(
                LeaveShop(),
                None,
                (StrategyRolloutTarget(1, 0, None, None, None),),
            ),
        ),
        selected_index=0,
        baseline_index=0,
        goal=RunGoal.VICTORY,
        teacher_config_digest="2" * 64,
    )
    records = tuple(
        draft.finalize(
            run_group=f"run-{index:06d}",
            decision_index=0,
            run_complete=True,
            run_won=index < 5,
            terminal_ante=9 if index < 5 else 4,
            best_hand_score=100,
        )
        for index in range(10)
    )
    results = [{"won": index < 5} for index in range(10)]

    coverage = module._teacher_coverage(records, results)

    assert coverage["winning_source_groups"] == 5
    assert coverage["losing_source_groups"] == 5
    assert not coverage["training_coverage_passed"]


def test_search_evaluator_rejects_panel_before_backend_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "evaluate_determinized_search.py",
            "--seed-start",
            "701",
            "--seeds",
            "20",
            "--seed-provenance",
            "gate",
        ],
    )
    monkeypatch.setattr(
        module,
        "verify_jackdaw_runtime",
        lambda: pytest.fail("backend verification must not run"),
    )

    with pytest.raises(SystemExit, match="gate panel must be exactly seeds 701-900"):
        module.main()


def test_reserved_terminal_seeds_require_preregistration_before_backend_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_script()
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "evaluate_determinized_search.py",
            "--seed-start",
            "1055",
            "--seeds",
            "20",
            "--report-json",
            str(tmp_path / "report.json"),
        ],
    )
    monkeypatch.setattr(
        module,
        "verify_jackdaw_runtime",
        lambda: pytest.fail("backend verification must not run"),
    )

    with pytest.raises(SystemExit, match="require --terminal-preregistration-json"):
        module.main()


def test_terminal_preregistration_binds_exact_budget_and_output() -> None:
    module = _load_script()
    root = Path(__file__).resolve().parents[1]
    preregistration = root / "experiments/terminal-actions-v6-preregistration.json"
    args = module.build_parser().parse_args(
        [
            "--seed-start",
            "1055",
            "--seeds",
            "20",
            "--samples",
            "6",
            "--horizon-antes",
            "1",
            "--max-steps",
            "200",
            "--override-z",
            "1",
            "--max-decisions",
            "1200",
            "--ante-cap",
            "12",
            "--workers",
            "9",
            "--terminal-preregistration-json",
            str(preregistration),
            "--report-json",
            str(
                root
                / "runs/experiments/terminal-actions-v6/"
                "seeds1055-1074.baseline.json"
            ),
        ]
    )

    bound = module._validate_terminal_preregistration(  # noqa: SLF001
        args, StrategyTuning(), repository_root=root
    )

    assert bound is not None
    assert bound["mode"] == "baseline"
    args.samples = 7
    with pytest.raises(SystemExit, match="search budget mismatch"):
        module._validate_terminal_preregistration(  # noqa: SLF001
            args, StrategyTuning(), repository_root=root
        )


def test_success_teacher_profile_links_slowest_anchor_and_reconciles() -> None:
    module = _load_script()
    results = [
        {
            "seed": 207,
            "search": {
                "success_teacher_steps": 30,
                "success_teacher_seconds": 3.0,
            },
            "success_teacher_decisions": [
                {
                    "phase": "SHOP",
                    "ante": 4,
                    "roots": 2,
                    "sample_evaluations": 4,
                    "steps": 10,
                    "max_root_cumulative_steps": 5,
                    "seconds": 1.0,
                    "endpoint_counts": {"death": 4},
                    "fallback_reason": None,
                },
                {
                    "phase": "PACK",
                    "ante": 5,
                    "roots": 3,
                    "sample_evaluations": 6,
                    "steps": 20,
                    "max_root_cumulative_steps": 8,
                    "seconds": 2.0,
                    "endpoint_counts": {"victory": 6},
                    "fallback_reason": "insufficient_terminal_dominance",
                },
            ],
        }
    ]

    profile = module._success_teacher_profile(results, mode="actions")  # noqa: SLF001

    assert profile["slowest"]["seed"] == 207
    assert profile["slowest"]["decision_index"] == 1
    assert profile["sample_evaluations"]["max"] == 6
    assert profile["counter_reconciliation"]["steps_match"]
    assert profile["counter_reconciliation"]["seconds_match"]


def test_report_publication_is_atomic_and_exclusive(tmp_path: Path) -> None:
    module = _load_script()
    path = tmp_path / "report.json"

    module._publish_json_exclusive(path, '{"complete":true}\n')  # noqa: SLF001

    assert path.read_text(encoding="utf-8") == '{"complete":true}\n'
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        module._publish_json_exclusive(path, '{"complete":false}\n')  # noqa: SLF001
    assert path.read_text(encoding="utf-8") == '{"complete":true}\n'
    assert list(tmp_path.iterdir()) == [path]
