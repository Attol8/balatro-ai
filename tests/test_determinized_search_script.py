from __future__ import annotations

import importlib.util
import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from balatro_ai_v2.actions import LeaveShop, iter_legal_actions
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.determinized_search import SearchCounters, SearchDecision
from balatro_ai_v2.strategy_engine import RunGoal, RunRoute
from balatro_ai_v2.strategy_teacher import (
    StrategyRolloutTarget,
    StrategyTeacherCandidate,
    StrategyTeacherDraft,
    write_teacher_records,
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
    assert records[0].run_group.startswith("origin-")
    assert len(records[0].run_group) == len("origin-") + 32
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
        preferred_route = None
        control_route = None
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

    FakeDecision.preferred_route = "held_retrigger"
    FakeDecision.control_route = "victory"

    route_disagreement = module._shadow_run_diagnostics(
        FakeShadow(), record_decisions=False
    )

    assert route_disagreement["agreements"] == 0


def test_search_summary_aggregates_route_identity_diagnostics() -> None:
    module = _load_script()
    counters = SearchCounters(
        strategic_decisions=2,
        searched=2,
        changed=0,
        strategy_identity_changes=1,
        strategy_specialist_challenges=7,
        strategy_specialist_roots_generated=9,
        strategy_specialist_overrides=1,
        strategy_specialist_unavailable=1,
        strategy_route_abandonments=1,
        strategy_victory_escapes=1,
        success_route_only_overrides=1,
    )
    counters.strategy_route_selections.update(
        {"held_retrigger": 1, "victory": 1}
    )
    counters.strategy_route_transitions.update(
        {"held_retrigger->held_retrigger": 1, "held_retrigger->victory": 1}
    )

    summary = module._search_summary(
        [{"search": {**counters.as_dict(), "run_seconds": 1.0}}]
    )

    assert summary["strategy_identity_changes"] == 1
    assert summary["strategy_identity_changed_fraction"] == 0.5
    assert summary["success_route_only_overrides"] == 1
    assert summary["strategy_specialist_challenges"] == 7
    assert summary["strategy_specialist_roots_generated"] == 9
    assert summary["strategy_specialist_overrides"] == 1
    assert summary["strategy_specialist_unavailable"] == 1
    assert summary["strategy_specialist_unavailable_fraction"] == 0.5
    assert summary["strategy_route_abandonments"] == 1
    assert summary["strategy_victory_escapes"] == 1
    assert summary["strategy_route_selections"] == {
        "held_retrigger": 1,
        "victory": 1,
    }
    assert summary["strategy_route_transitions"] == {
        "held_retrigger->held_retrigger": 1,
        "held_retrigger->victory": 1,
    }


def test_search_decision_profile_reports_overlay_shape_and_failures() -> None:
    module = _load_script()
    decision = SearchDecision(
        phase="SHOP",
        ante=2,
        roots=5,
        samples=2,
        steps=20,
        seconds=0.5,
        rejected_rollouts=0,
        values=(),
        baseline='{"type":"leave_shop"}',
        selected='{"type":"reroll_shop"}',
        ordinary_selected='{"type":"leave_shop"}',
        ordinary_roots=3,
        specialist_roots=2,
        specialist_roots_generated=4,
        specialist_override=True,
        specialist_unavailable_reason="synthetic_specialist_gap",
    )

    profile = module._search_decision_profile([decision])
    failures = module._search_failure_reasons([decision])

    assert profile["specialist_overrides"] == 1
    assert profile["specialist_unavailable"] == 1
    assert profile["ordinary_roots"]["max"] == 3
    assert profile["specialist_roots"]["max"] == 2
    assert profile["specialist_roots_generated"]["max"] == 4
    assert failures == {
        "specialist_unavailable|synthetic_specialist_gap": 1,
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
                route=RunRoute.VICTORY,
            ),
        ),
        selected_index=0,
        baseline_index=0,
        goal=RunGoal.VICTORY,
        teacher_config_digest="2" * 64,
    )
    records = tuple(
        draft.finalize(
            run_group=f"origin-{index:032x}",
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
    assert coverage["dense_paired_utility"]["route_roots"] == {"victory": 10}
    assert coverage["dense_paired_utility"]["route_diverse_rows"] == 0


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


def test_stale_continuation_artifacts_fail_before_backend_work(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_script()
    model = tmp_path / "model.pt"
    certificate = tmp_path / "certificate.json"
    training_report = tmp_path / "training.json"
    for path in (model, certificate, training_report):
        path.write_bytes(b"stale")
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "evaluate_determinized_search.py",
            "--strategy-continuation-model",
            str(model),
            "--strategy-continuation-certificate",
            str(certificate),
            "--strategy-continuation-training-report",
            str(training_report),
        ],
    )
    monkeypatch.setattr(
        module.CertifiedUtilityContinuationPolicy,
        "from_artifacts",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("stale model schema")),
    )
    monkeypatch.setattr(
        module,
        "verify_jackdaw_runtime",
        lambda: pytest.fail("backend verification must not run"),
    )

    with pytest.raises(
        SystemExit, match="invalid rollout continuation artifact: stale model schema"
    ):
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
                root / "runs/experiments/terminal-actions-v6/"
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


def test_reserved_contextual_seeds_require_preregistration_before_backend_work(
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
            "1975",
            "--seeds",
            "50",
            "--dense-teacher",
            "--teacher-jsonl",
            str(tmp_path / "teacher.jsonl"),
            "--report-json",
            str(tmp_path / "report.json"),
        ],
    )
    monkeypatch.setattr(
        module,
        "verify_jackdaw_runtime",
        lambda: pytest.fail("backend verification must not run"),
    )

    with pytest.raises(SystemExit, match="require --contextual-preregistration-json"):
        module.main()


def test_retired_contextual_v9_seeds_cannot_be_reused(
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
            "1075",
            "--seeds",
            "50",
            "--dense-teacher",
            "--teacher-jsonl",
            str(tmp_path / "teacher.jsonl"),
            "--report-json",
            str(tmp_path / "report.json"),
        ],
    )
    monkeypatch.setattr(
        module,
        "verify_jackdaw_runtime",
        lambda: pytest.fail("backend verification must not run"),
    )

    with pytest.raises(SystemExit, match="v9/v10 seeds 1075-1674 are retired"):
        module.main()


def test_contextual_preregistration_binds_batch_budget_and_outputs(tmp_path) -> None:
    module = _load_script()
    root = tmp_path
    teacher = root / module._CONTEXTUAL_BATCHES[0]["teacher_jsonl"]
    report = root / module._CONTEXTUAL_BATCHES[0]["report_json"]
    origin_key = root / "runs/secrets/contextual-continuation-v12-origin.key"
    origin_key.parent.mkdir(parents=True)
    origin_key.write_bytes(b"k" * 32)
    preregistration = tmp_path / "prereg.json"
    spec = {
        "protocol_id": "contextual-continuation-development-v4",
        "status": "reserved",
        "immutable_batches": True,
        "seed_provenance": "development",
        "deck": "RED",
        "stake": "WHITE",
        "strategy_tuning": json.loads(StrategyTuning().canonical_json()),
        "search": {
            "samples": 6,
            "horizon_antes": 1,
            "max_steps": 200,
            "override_z": 1.0,
            "max_decisions": 1200,
            "ante_cap": 12,
            "workers": 6,
            "nonce": "contextual-continuation-v12-frozen",
            "continuation": "strategic",
            "policy_seed": "baseline-v1",
            "strategy_options": False,
            "include_reorders": False,
            "dense_teacher": True,
        },
        "origin_mapping": {
            "algorithm": "hmac-sha256-truncated-128",
            "key_path": "runs/secrets/contextual-continuation-v12-origin.key",
            "key_sha256": hashlib.sha256(b"k" * 32).hexdigest(),
        },
        "batches": list(module._CONTEXTUAL_BATCHES),
        "first_100_kill_gate": module._CONTEXTUAL_FIRST_100_GATE,
    }
    preregistration.write_text(json.dumps(spec), encoding="utf-8")
    args = module.build_parser().parse_args(
        [
            "--seed-start",
            "1975",
            "--seeds",
            "50",
            "--samples",
            "6",
            "--horizon-antes",
            "1",
            "--max-steps",
            "200",
            "--max-decisions",
            "1200",
            "--ante-cap",
            "12",
            "--workers",
            "6",
            "--nonce",
            "contextual-continuation-v12-frozen",
            "--dense-teacher",
            "--teacher-jsonl",
            str(teacher),
            "--report-json",
            str(report),
            "--contextual-preregistration-json",
            str(preregistration),
            "--origin-key-file",
            str(origin_key),
        ]
    )

    binding = module._validate_contextual_preregistration(
        args, StrategyTuning(), repository_root=root
    )

    assert binding is not None
    assert binding["batch_id"] == "batch-01"
    args.samples = 5
    with pytest.raises(SystemExit, match="search budget mismatch"):
        module._validate_contextual_preregistration(
            args, StrategyTuning(), repository_root=root
        )


def test_contextual_first_100_gate_requires_two_clean_passing_reports(tmp_path) -> None:
    module = _load_script()
    preregistration_digest = "d" * 64
    origin_key = b"k" * 32
    batches = list(module._CONTEXTUAL_BATCHES)
    spec = {
        "batches": batches,
        "first_100_kill_gate": {
            "minimum_action_sensitive_fraction": 0.4,
            "minimum_observed_victory_groups": 10,
            "rejected_or_censored": 0,
        },
    }
    for expected in batches[:2]:
        seed_start = int(expected["seed_start"])
        observation = to_public_observation(state("BLIND_SELECT"))
        actions = tuple(iter_legal_actions(observation))
        records = tuple(
            StrategyTeacherDraft(
                observation=observation,
                candidates=tuple(
                    StrategyTeacherCandidate(
                        action,
                        None,
                        tuple(
                            StrategyRolloutTarget(
                                1,
                                1,
                                1 if seed < seed_start + 5 and index == 1 else 0,
                                4,
                                2,
                                search_utility=2 if index == 1 else 1,
                            )
                            for _ in range(6)
                        ),
                    )
                    for index, action in enumerate(actions)
                ),
                selected_index=1,
                baseline_index=0,
                goal=RunGoal.VICTORY,
                teacher_config_digest="3" * 64,
                candidate_space_size=len(actions),
            ).finalize(
                run_group="origin-"
                + hmac.new(origin_key, str(seed).encode(), hashlib.sha256).hexdigest()[
                    :32
                ],
                decision_index=0,
                run_complete=True,
                run_won=False,
                terminal_ante=3,
                best_hand_score=100,
            )
            for seed in range(seed_start, seed_start + 50)
        )
        rows = [
            {
                "seed": seed,
                "complete": True,
                "won": False,
                "antes_cleared": 3,
                "rejected_decisions": 0,
                "terminal_reason": "game_over",
                "terminal_error": None,
                "best_hand_score": 100,
                "search_failure_reasons": {},
                "search": {
                    "rejected_rollouts": 0,
                    "unavailable": 0,
                    "searched": 1,
                },
            }
            for seed in range(seed_start, seed_start + 50)
        ]
        teacher_path = tmp_path / expected["teacher_jsonl"]
        teacher_path.parent.mkdir(parents=True, exist_ok=True)
        teacher_digest = write_teacher_records(teacher_path, records)
        path = tmp_path / expected["report_json"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "contextual_teacher_preregistration": {
                        "sha256": preregistration_digest,
                        "batch_id": expected["batch_id"],
                    },
                    "strategy_teacher_dataset": {
                        "status": "written",
                        "sha256": teacher_digest,
                        "groups": 50,
                        "records": 50,
                        "teacher_config_digest": "3" * 64,
                        "coverage": module._teacher_coverage(records, rows),
                    },
                    "results": rows,
                }
            ),
            encoding="utf-8",
        )

    module._validate_contextual_first_100(
        spec,
        preregistration_sha256=preregistration_digest,
        origin_key=origin_key,
        repository_root=tmp_path,
    )

    failed = tmp_path / batches[1]["report_json"]
    report = json.loads(failed.read_text(encoding="utf-8"))
    report["results"][0]["search"]["rejected_rollouts"] = 1
    failed.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(SystemExit, match="integrity checks"):
        module._validate_contextual_first_100(
            spec,
            preregistration_sha256=preregistration_digest,
            origin_key=origin_key,
            repository_root=tmp_path,
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
                    "route_counts": {"held_retrigger": 2},
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
                    "route_counts": {"victory": 3},
                    "fallback_reason": "insufficient_terminal_dominance",
                },
            ],
        }
    ]

    profile = module._success_teacher_profile(results, mode="actions")  # noqa: SLF001

    assert profile["slowest"]["seed"] == 207
    assert profile["slowest"]["decision_index"] == 1
    assert profile["sample_evaluations"]["max"] == 6
    assert profile["route_counts"] == {"held_retrigger": 2, "victory": 3}
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


def test_contextual_bundle_publishes_teacher_and_report_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()
    observation = to_public_observation(state("SHOP"))
    record = StrategyTeacherDraft(
        observation=observation,
        candidates=(
            StrategyTeacherCandidate(
                LeaveShop(),
                None,
                (StrategyRolloutTarget(1, 1, 0, 3, 2),),
            ),
        ),
        selected_index=0,
        baseline_index=0,
        goal=RunGoal.VICTORY,
        teacher_config_digest="2" * 64,
    ).finalize(
        run_group="origin-" + "1" * 32,
        decision_index=0,
        run_complete=True,
        run_won=False,
        terminal_ante=3,
        best_hand_score=100,
    )
    records = (record,)
    runtime = {"revision": "runtime"}
    monkeypatch.setattr(module, "source_snapshot", lambda _root: ("r", False, "s"))
    monkeypatch.setattr(module, "verify_jackdaw_runtime", lambda: runtime)
    teacher = tmp_path / "batch-01/teacher.jsonl"
    report = tmp_path / "batch-01/report.json"

    module._publish_contextual_bundle(
        teacher,
        report,
        records,
        expected_teacher_digest=module.teacher_records_digest(records),
        encoded_report='{"complete":true}\n',
        expected_manifest=SimpleNamespace(repository_revision="r", source_digest="s"),
        expected_runtime=runtime,
        repository_root=tmp_path,
    )

    assert teacher.is_file()
    assert report.read_text(encoding="utf-8") == '{"complete":true}\n'
    assert {path.name for path in tmp_path.iterdir()} == {"batch-01"}
