from __future__ import annotations

import importlib.util
import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import balatro_ai_v2.determinized_search as search_module
from balatro_ai_v2.actions import LeaveShop, RerollShop, iter_legal_actions
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.determinized_search import (
    DeterminizedSearchPolicy,
    RolloutOutcome,
    SearchCounters,
    SearchDecision,
    SuccessTeacherBudget,
)
from balatro_ai_v2.strategy_engine import GoalUtility, RunGoal, RunRoute
from balatro_ai_v2.strategy_options import StrategyCandidateRoot, StrategyIntent
from balatro_ai_v2.strategy_teacher import (
    StrategyRolloutTarget,
    StrategyTargetEndpoint,
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
    assert not args.profile_search_timing
    assert args.seed_provenance == "development"
    assert args.seed_start == 901


def test_search_evaluator_exposes_non_authoritative_candidate_trace_directory() -> None:
    args = (
        _load_script()
        .build_parser()
        .parse_args(["--trace-dir", "runs/experiments/candidate-traces"])
    )

    assert args.trace_dir == Path("runs/experiments/candidate-traces")


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
        ordinary_index=0,
        behavior_index=0,
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


def _route_teacher_row(module) -> dict[str, object]:
    observation = to_public_observation(state("SHOP", money=10))
    samples = (
        StrategyRolloutTarget(1, 1, 0, 4, 2, search_utility=1),
        StrategyRolloutTarget(1, 1, 0, 5, 3, search_utility=2),
    )
    draft = StrategyTeacherDraft(
        observation=observation,
        candidates=(
            StrategyTeacherCandidate(RerollShop(), None, samples),
            StrategyTeacherCandidate(
                RerollShop(),
                StrategyIntent.HELD_RETRIGGER_ENGINE,
                samples,
                route=RunRoute.HELD_RETRIGGER,
            ),
        ),
        selected_index=1,
        baseline_index=0,
        ordinary_index=0,
        behavior_index=1,
        goal=RunGoal.VICTORY,
        teacher_config_digest="2" * 64,
        candidate_space_size=2,
    )
    ordinary = module._teacher_candidate_identity(draft.candidates[0])
    specialist = module._teacher_candidate_identity(draft.candidates[1])
    return {
        "seed": 42,
        "complete": True,
        "won": False,
        "antes_cleared": 4,
        "best_hand_score": 100,
        "search": {
            "rejected_rollouts": 0,
            "unavailable": 0,
            "success_anchors_attempted": 1,
            "success_anchors_completed": 1,
            "success_anchor_fallbacks": 0,
            "success_anchor_unavailable": 0,
            "success_anchor_unsupported": 0,
            "success_teacher_rejected_rollouts": 0,
            "success_teacher_censored_rollouts": 0,
            "strategy_specialist_unavailable": 0,
        },
        "search_failure_reasons": {},
        "success_teacher_decisions": [
            {
                "phase": observation.phase.value,
                "ante": observation.ante,
                "goal": RunGoal.VICTORY.value,
                "roots": 2,
                "initial_samples": 2,
                "max_samples_used": 2,
                "sample_evaluations": 4,
                "ordinary_index": 0,
                "behavior_index": 1,
                "teacher_selected_index": 1,
                "executed_index": 1,
                "ordinary": ordinary,
                "behavior": specialist,
                "teacher_selected": specialist,
                "executed": specialist,
                "fallback_reason": None,
                "affects_actions": False,
                "unavailable": False,
                "unsupported": False,
                "identity_override": False,
                "rejected_rollouts": 0,
                "censored_rollouts": 0,
            }
        ],
        "_teacher_drafts": (draft,),
    }


def test_route_teacher_finalizer_authenticates_action_inert_report() -> None:
    module = _load_script()
    rows = [_route_teacher_row(module)]

    records, status = module._finalize_teacher_records(
        rows,
        enabled=True,
        origin_key=b"k" * 32,
        mode="route_terminal_paired_utility",
    )

    assert status == "written"
    assert len(records) == 1
    assert records[0].ordinary_index == records[0].baseline_index == 0
    assert records[0].behavior_index == records[0].selected_index == 1
    expected_group = hmac.new(b"k" * 32, b"42", hashlib.sha256).hexdigest()[:32]
    assert records[0].run_group == f"origin-{expected_group}"
    assert "_teacher_drafts" not in rows[0]


def test_route_teacher_finalizer_accepts_collector_emitted_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()

    class Sample:
        def close(self) -> None:
            pass

    class Frozen:
        def clone(self):
            return SimpleNamespace(close=lambda: None)

    monkeypatch.setattr(search_module, "sample_candidate", lambda *args: Sample())
    monkeypatch.setattr(search_module, "freeze_backend", lambda sample: Frozen())
    monkeypatch.setattr(
        search_module, "_teacher_config_digest", lambda policy: "1" * 64
    )

    def rollout(self, clone, observation, history, root, **kwargs):
        del self, clone, observation, history, root
        won = kwargs.get("route") == RunRoute.HELD_RETRIGGER
        return RolloutOutcome(
            value=float(won),
            steps=1,
            rejected=False,
            goal_utility=GoalUtility(float(won), 1, 1),
            endpoint=(
                StrategyTargetEndpoint.VICTORY
                if won
                else StrategyTargetEndpoint.DEATH
            ),
        )

    monkeypatch.setattr(DeterminizedSearchPolicy, "_rollout", rollout)
    observation = to_public_observation(state("SHOP", money=10))
    roots = (
        StrategyCandidateRoot(LeaveShop(), None),
        StrategyCandidateRoot(RerollShop(), None),
        StrategyCandidateRoot(
            RerollShop(),
            StrategyIntent.HELD_RETRIGGER_ENGINE,
            route=RunRoute.HELD_RETRIGGER,
        ),
    )
    policy = DeterminizedSearchPolicy(
        backend=None,  # type: ignore[arg-type]
        continuation=None,  # type: ignore[arg-type]
        success_teacher=SuccessTeacherBudget(samples=2),
    )
    assert (
        policy._collect_success_teacher(  # noqa: SLF001
            observation,
            (),
            roots,
            behavior_index=2,
            ordinary_index=0,
            intent_aware=True,
            engine_goal=RunGoal.VICTORY,
        )
        == 2
    )
    assert policy.teacher_drafts[0].candidate_space_size == len(roots)
    row = {
        "seed": 43,
        "complete": True,
        "won": False,
        "antes_cleared": 4,
        "best_hand_score": 100,
        "search": policy.counters.as_dict(),
        "search_failure_reasons": {},
        "success_teacher_decisions": [
            decision.as_dict() for decision in policy.success_decisions
        ],
        "_teacher_drafts": tuple(policy.teacher_drafts),
    }

    records, status = module._finalize_teacher_records(
        [row],
        enabled=True,
        origin_key=b"k" * 32,
        mode="route_terminal_paired_utility",
    )

    assert status == "written"
    assert len(records) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ordinary", {"action": {"type": "leave_shop"}, "intent": None, "route": None}),
        ("executed_index", 0),
        ("affects_actions", True),
        ("identity_override", True),
    ],
)
def test_route_teacher_finalizer_rejects_tampered_report(
    field: str,
    value: object,
) -> None:
    module = _load_script()
    rows = [_route_teacher_row(module)]
    decisions = rows[0]["success_teacher_decisions"]
    assert isinstance(decisions, list) and isinstance(decisions[0], dict)
    decisions[0][field] = value

    records, status = module._finalize_teacher_records(
        rows,
        enabled=True,
        origin_key=b"k" * 32,
        mode="route_terminal_paired_utility",
    )

    assert not records
    assert status == "discarded_invalid_route_teacher_panel"
    assert "_teacher_drafts" not in rows[0]


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


def test_search_timing_summary_merges_only_opt_in_rows() -> None:
    module = _load_script()
    profile = {
        "schema_version": 1,
        "clock": "perf_counter_ns",
        "buckets": {
            "success_teacher.clone": {
                "count": 2,
                "seconds": 0.2,
                "max_seconds": 0.12,
            }
        },
        "allocation": {
            "metric": "net_allocated_blocks",
            "terminal_anchors": 1,
            "net_blocks": 7,
            "max_positive_anchor_net_blocks": 7,
        },
        "gc": {
            "collections_by_generation": {"0": 3},
            "seconds": 0.03,
            "max_seconds": 0.02,
        },
    }

    summary = module._search_timing_summary(  # noqa: SLF001
        [
            {"search_timing": profile},
            {"search_timing": profile},
            {"search": {}},
        ]
    )

    assert summary["profiled_runs"] == 2
    assert summary["buckets"]["success_teacher.clone"] == {
        "count": 4,
        "seconds": 0.4,
        "max_seconds": 0.12,
    }
    assert summary["allocation"]["terminal_anchors"] == 2
    assert summary["allocation"]["net_blocks"] == 14
    assert summary["allocation"]["max_positive_anchor_net_blocks"] == 7
    assert summary["gc"] == {
        "collections_by_generation": {"0": 6},
        "seconds": 0.06,
        "max_seconds": 0.02,
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
            ),
        ),
        selected_index=0,
        baseline_index=0,
        ordinary_index=0,
        behavior_index=0,
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
    assert coverage["dense_paired_utility"]["route_roots"] == {"none": 10}
    assert coverage["dense_paired_utility"]["route_diverse_rows"] == 0


def test_route_terminal_coverage_matches_seed2309_style_paired_residuals() -> None:
    module = _load_script()
    observation = to_public_observation(state("SHOP", money=10))
    ordinary_leave = (
        StrategyRolloutTarget(
            0,
            0,
            None,
            None,
            None,
            endpoint=StrategyTargetEndpoint.CENSORED,
            search_utility=1,
        ),
        StrategyRolloutTarget(0, 0, 1, None, 1, search_utility=1),
    )
    specialist_leave = (
        StrategyRolloutTarget(1, 1, 0, None, None, search_utility=2),
        StrategyRolloutTarget(0, 0, 1, None, 2, search_utility=2),
    )
    ordinary_reroll = (
        StrategyRolloutTarget(0, 1, 0, None, None, search_utility=3),
        StrategyRolloutTarget(0, 1, 0, None, None, search_utility=3),
    )
    specialist_reroll = (
        StrategyRolloutTarget(0, 1, 0, None, None, search_utility=2),
        StrategyRolloutTarget(0, 1, 0, None, None, search_utility=2),
    )
    record = StrategyTeacherDraft(
        observation=observation,
        candidates=(
            StrategyTeacherCandidate(LeaveShop(), None, ordinary_leave),
            StrategyTeacherCandidate(
                LeaveShop(),
                StrategyIntent.PLAYED_RETRIGGER_ENGINE,
                specialist_leave,
                route=RunRoute.PLAYED_RETRIGGER,
            ),
            StrategyTeacherCandidate(RerollShop(), None, ordinary_reroll),
            StrategyTeacherCandidate(
                RerollShop(),
                StrategyIntent.HELD_RETRIGGER_ENGINE,
                specialist_reroll,
                route=RunRoute.HELD_RETRIGGER,
            ),
        ),
        selected_index=0,
        baseline_index=0,
        ordinary_index=0,
        behavior_index=0,
        goal=RunGoal.VICTORY,
        teacher_config_digest="4" * 64,
        candidate_space_size=5,
    ).finalize(
        run_group="origin-00000000000000000000000000000001",
        decision_index=0,
        run_complete=True,
        run_won=False,
        terminal_ante=4,
        best_hand_score=100,
    )

    route = module._teacher_coverage((record,), [{"won": False}])[
        "route_terminal_paired_utility"
    ]

    assert route["records"] == 1
    assert route["groups"] == 1
    assert route["phase_rows"] == {"SHOP": 1}
    assert route["goal_rows"] == {"victory": 1}
    assert route["roots_by_non_victory_route"] == {
        "held_retrigger": 1,
        "played_retrigger": 1,
    }
    assert route["route_diverse_rows"] == 1
    assert route["route_diverse_groups"] == 1
    assert route["matched_pairs"] == 2
    assert route["pair_metrics"]["search_utility"] == {
        "sensitive_pairs": 2,
        "positive_pairs": 1,
        "negative_pairs": 1,
        "zero_pairs": 0,
        "null_mismatch_pairs": 0,
    }
    assert route["pair_metrics"]["current_blind_clear"] == {
        "sensitive_pairs": 1,
        "positive_pairs": 1,
        "negative_pairs": 0,
        "zero_pairs": 1,
        "null_mismatch_pairs": 0,
    }
    assert route["pair_metrics"]["next_boss_clear"] == {
        "sensitive_pairs": 1,
        "positive_pairs": 1,
        "negative_pairs": 0,
        "zero_pairs": 1,
        "null_mismatch_pairs": 0,
    }
    assert route["pair_metrics"]["ante8_win"] == {
        "sensitive_pairs": 1,
        "positive_pairs": 0,
        "negative_pairs": 0,
        "zero_pairs": 2,
        "null_mismatch_pairs": 1,
    }
    assert route["pair_metrics"]["endless_ante"] == {
        "sensitive_pairs": 0,
        "positive_pairs": 0,
        "negative_pairs": 0,
        "zero_pairs": 2,
        "null_mismatch_pairs": 0,
    }
    assert route["pair_metrics"]["log_score"] == {
        "sensitive_pairs": 1,
        "positive_pairs": 1,
        "negative_pairs": 0,
        "zero_pairs": 1,
        "null_mismatch_pairs": 0,
    }
    assert route["stored_root_max"] == 4
    assert route["candidate_space_max"] == 5
    assert route["subset_rows"] == 1
    assert route["censored_rows"] == 1
    assert route["censored_samples"] == 1
    assert route["sample_count_roots"] == {"2": 4}
    assert route["sample_count_min"] == 2
    assert route["sample_count_max"] == 2
    assert route["sample_count_mismatch_rows"] == 0
    assert route["matched_pair_sample_count_min"] == 2
    assert route["matched_pair_sample_count_max"] == 2


def test_route_terminal_coverage_all_null_routes_have_zero_support() -> None:
    module = _load_script()
    observation = to_public_observation(state("SHOP"))
    record = StrategyTeacherDraft(
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
        ordinary_index=0,
        behavior_index=0,
        goal=RunGoal.VICTORY,
        teacher_config_digest="5" * 64,
    ).finalize(
        run_group="origin-00000000000000000000000000000002",
        decision_index=0,
        run_complete=True,
        run_won=False,
        terminal_ante=3,
        best_hand_score=100,
    )

    route = module._teacher_coverage((record,), [{"won": False}])[
        "route_terminal_paired_utility"
    ]

    assert route["roots_by_non_victory_route"] == {}
    assert route["route_diverse_rows"] == 0
    assert route["route_diverse_groups"] == 0
    assert route["matched_pairs"] == 0
    assert all(
        counts
        == {
            "sensitive_pairs": 0,
            "positive_pairs": 0,
            "negative_pairs": 0,
            "zero_pairs": 0,
            "null_mismatch_pairs": 0,
        }
        for counts in route["pair_metrics"].values()
    )


def test_teacher_dataset_mode_classifies_only_route_success_collection() -> None:
    module = _load_script()
    parser = module.build_parser()

    route = parser.parse_args(["--strategy-options", "--success-teacher"])
    dense = parser.parse_args(["--dense-teacher"])
    strategy_only = parser.parse_args(["--strategy-options"])
    success_only = parser.parse_args(["--success-teacher"])
    terminal = parser.parse_args(
        ["--strategy-options", "--success-terminal-actions"]
    )

    assert module._teacher_dataset_mode(route) == "route_terminal_paired_utility"
    assert module._teacher_dataset_mode(dense) == "dense_paired_utility"
    assert module._teacher_dataset_mode(strategy_only) == "legacy"
    assert module._teacher_dataset_mode(success_only) == "legacy"
    assert module._teacher_dataset_mode(terminal) == "legacy"


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
            "2602",
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


@pytest.mark.parametrize("seed_start", [2602, 2901])
def test_v14_reserved_seed_boundaries_require_preregistration(
    tmp_path: Path,
    seed_start: int,
) -> None:
    module = _load_script()
    args = module.build_parser().parse_args(
        ["--seed-start", str(seed_start), "--seeds", "1"]
    )

    with pytest.raises(SystemExit, match="seeds 2602-2901 require"):
        module._validate_contextual_preregistration(
            args, StrategyTuning(), repository_root=tmp_path
        )


@pytest.mark.parametrize("seed_start", [1075, 1975, 2274])
def test_retired_contextual_seeds_cannot_be_reused(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    seed_start: int,
) -> None:
    module = _load_script()
    monkeypatch.setattr(
        module.sys,
        "argv",
        [
            "evaluate_determinized_search.py",
            "--seed-start",
            str(seed_start),
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

    with pytest.raises(SystemExit, match="v9-v13 seeds 1075-2274 are retired"):
        module.main()


@pytest.mark.parametrize("seed_start", [2275, 2601, 2902])
def test_unreserved_development_seed_boundaries_remain_available(
    tmp_path: Path,
    seed_start: int,
) -> None:
    module = _load_script()
    args = module.build_parser().parse_args(
        ["--seed-start", str(seed_start), "--seeds", "1"]
    )

    assert (
        module._validate_contextual_preregistration(
            args, StrategyTuning(), repository_root=tmp_path
        )
        is None
    )


def test_contextual_preregistration_binds_batch_budget_and_outputs(tmp_path) -> None:
    module = _load_script()
    root = tmp_path
    teacher = root / module._CONTEXTUAL_BATCHES[0]["teacher_jsonl"]
    report = root / module._CONTEXTUAL_BATCHES[0]["report_json"]
    origin_key = root / "runs/secrets/contextual-continuation-v14-origin.key"
    origin_key.parent.mkdir(parents=True)
    origin_key.write_bytes(b"k" * 32)
    preregistration = tmp_path / "prereg.json"
    spec = {
        "protocol_id": "contextual-continuation-development-v6",
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
            "nonce": "contextual-continuation-v14-frozen",
            "continuation": "strategic",
            "policy_seed": "baseline-v1",
            "strategy_options": False,
            "include_reorders": False,
            "dense_teacher": True,
        },
        "training": module._CONTEXTUAL_TRAINING,
        "origin_mapping": {
            "algorithm": "hmac-sha256-truncated-128",
            "key_path": "runs/secrets/contextual-continuation-v14-origin.key",
            "key_sha256": hashlib.sha256(b"k" * 32).hexdigest(),
        },
        "batches": list(module._CONTEXTUAL_BATCHES),
        "first_100_kill_gate": module._CONTEXTUAL_FIRST_100_GATE,
    }
    preregistration.write_text(json.dumps(spec), encoding="utf-8")
    args = module.build_parser().parse_args(
        [
            "--seed-start",
            "2602",
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
            "contextual-continuation-v14-frozen",
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
                ordinary_index=0,
                behavior_index=1,
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


def test_contextual_validator_uses_canonical_boundary_selection() -> None:
    module = _load_script()
    boundary_delta = 0.051200000000000134
    record = SimpleNamespace(
        baseline_index=0,
        candidates=(
            SimpleNamespace(
                samples=tuple(SimpleNamespace(search_utility=0.0) for _ in range(6))
            ),
            SimpleNamespace(
                samples=(
                    SimpleNamespace(search_utility=boundary_delta),
                    *(SimpleNamespace(search_utility=0.0) for _ in range(5)),
                )
            ),
        ),
    )

    assert module._contextual_selected_index(record) == 0


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
        ordinary_index=0,
        behavior_index=0,
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


def _route_preregistration_args(tmp_path: Path, module):
    preregistration = tmp_path / module.ROUTE_TEACHER_PREREGISTRATION
    preregistration.parent.mkdir(parents=True)
    origin_key = b"r" * 32
    origin_path = tmp_path / module.ROUTE_TEACHER_ORIGIN_KEY
    origin_path.parent.mkdir(parents=True)
    origin_path.write_bytes(origin_key)
    batch = module.ROUTE_TEACHER_BATCHES[0]
    teacher_path = tmp_path / batch["teacher_jsonl"]
    report_path = tmp_path / batch["report_json"]
    spec = {
        "protocol_id": module.ROUTE_TEACHER_PROTOCOL_ID,
        "status": "reserved",
        "immutable_batches": True,
        "collection_only": True,
        "training_authorized": False,
        "schema_version": 12,
        "implementation_revision": "a" * 40,
        "expected_source_digest": "b" * 64,
        "seed_provenance": "development",
        "deck": "RED",
        "stake": "WHITE",
        "candidate_runtime": {"revision": "candidate"},
        "backend": {"backend_name": "Jackdaw"},
        "strategy_tuning": json.loads(StrategyTuning().canonical_json()),
        "search": module.ROUTE_TEACHER_SEARCH,
        "terminal_teacher": module.ROUTE_TEACHER_TERMINAL,
        "origin_mapping": {
            "algorithm": "hmac-sha256-truncated-128",
            "key_path": module.ROUTE_TEACHER_ORIGIN_KEY,
            "key_sha256": hashlib.sha256(origin_key).hexdigest(),
        },
        "batches": list(module.ROUTE_TEACHER_BATCHES),
        "pilot_gate": module.ROUTE_TEACHER_PILOT_GATE,
        "coverage_gate": module.ROUTE_TEACHER_COVERAGE_GATE,
    }
    preregistration.write_text(json.dumps(spec), encoding="utf-8")
    search = module.ROUTE_TEACHER_SEARCH
    terminal = module.ROUTE_TEACHER_TERMINAL
    args = module.build_parser().parse_args(
        [
            "--seed-start",
            str(batch["seed_start"]),
            "--seeds",
            str(batch["seeds"]),
            "--deck",
            "RED",
            "--stake",
            "WHITE",
            "--seed-provenance",
            "development",
            "--samples",
            str(search["samples"]),
            "--horizon-antes",
            str(search["horizon_antes"]),
            "--max-steps",
            str(search["max_steps"]),
            "--override-z",
            str(search["override_z"]),
            "--max-decisions",
            str(search["max_decisions"]),
            "--ante-cap",
            str(search["ante_cap"]),
            "--workers",
            str(search["workers"]),
            "--nonce",
            str(search["nonce"]),
            "--continuation",
            str(search["continuation"]),
            "--policy-seed",
            str(search["policy_seed"]),
            "--strategy-options",
            "--success-teacher",
            "--success-teacher-samples",
            str(terminal["samples"]),
            "--success-teacher-start-ante",
            str(terminal["prewin_start_ante"]),
            "--success-teacher-endless-antes",
            str(terminal["endless_horizon_antes"]),
            "--success-teacher-max-steps",
            str(terminal["max_steps"]),
            "--teacher-jsonl",
            str(teacher_path),
            "--report-json",
            str(report_path),
            "--origin-key-file",
            str(origin_path),
            "--route-terminal-preregistration-json",
            str(preregistration),
        ]
    )
    return args, spec


def test_route_preregistration_binds_exact_action_inert_batch(tmp_path) -> None:
    module = _load_script()
    args, spec = _route_preregistration_args(tmp_path, module)

    binding = module._validate_route_terminal_preregistration(
        args, StrategyTuning(), repository_root=tmp_path
    )

    assert binding["protocol_id"] == module.ROUTE_TEACHER_PROTOCOL_ID
    assert binding["batch_id"] == "batch-01"
    assert binding["schema_version"] == 12
    assert binding["collection_only"] is True
    assert binding["training_authorized"] is False
    assert binding["expected_source_digest"] == spec["expected_source_digest"]


def test_route_preregistration_rejects_action_influence(tmp_path) -> None:
    module = _load_script()
    args, _ = _route_preregistration_args(tmp_path, module)
    args.success_terminal_actions = True

    with pytest.raises(SystemExit, match="isolated collection"):
        module._validate_route_terminal_preregistration(
            args, StrategyTuning(), repository_root=tmp_path
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("seed_provenance", "evaluator_secret"),
        ("deck", "BLUE"),
        ("stake", "GOLD"),
    ],
)
def test_route_preregistration_binds_actual_panel_identity(
    tmp_path: Path, field: str, value: str
) -> None:
    module = _load_script()
    args, _ = _route_preregistration_args(tmp_path, module)
    setattr(args, field, value)

    with pytest.raises(SystemExit, match="frozen protocol"):
        module._validate_route_terminal_preregistration(
            args, StrategyTuning(), repository_root=tmp_path
        )


def test_reserved_route_seeds_require_preregistration() -> None:
    module = _load_script()
    args = module.build_parser().parse_args(
        ["--seed-start", "2311", "--seeds", "1"]
    )

    with pytest.raises(SystemExit, match="require --route-terminal"):
        module._validate_route_terminal_preregistration(
            args, StrategyTuning(), repository_root=Path.cwd()
        )


def test_reserved_route_seeds_fail_before_backend_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script()
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["evaluate_determinized_search.py", "--seed-start", "2311", "--seeds", "20"],
    )
    monkeypatch.setattr(
        module,
        "verify_jackdaw_runtime",
        lambda: pytest.fail("backend verification must not run"),
    )

    with pytest.raises(SystemExit, match="require --route-terminal"):
        module.main()


def test_later_route_batch_requires_pilot_gate(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()
    args, _ = _route_preregistration_args(tmp_path, module)
    batch = module.ROUTE_TEACHER_BATCHES[1]
    args.seed_start = batch["seed_start"]
    args.seeds = batch["seeds"]
    args.teacher_jsonl = tmp_path / batch["teacher_jsonl"]
    args.report_json = tmp_path / batch["report_json"]
    called = []
    monkeypatch.setattr(
        module,
        "_validate_route_terminal_pilot",
        lambda *args, **kwargs: called.append((args, kwargs)),
    )

    binding = module._validate_route_terminal_preregistration(
        args, StrategyTuning(), repository_root=tmp_path
    )

    assert binding["batch_id"] == "batch-02"
    assert len(called) == 1


def test_route_pilot_reauthenticates_dataset_report_and_support_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()
    batch = module.ROUTE_TEACHER_BATCHES[0]
    origin_key = b"r" * 32
    rows = []
    for seed in range(
        int(batch["seed_start"]), int(batch["seed_start"]) + int(batch["seeds"])
    ):
        row = _route_teacher_row(module)
        row.update(
            seed=seed,
            terminal_reason="game_over",
            terminal_error=None,
            rejected_decisions=0,
        )
        rows.append(row)
    records, status = module._finalize_teacher_records(
        rows,
        enabled=True,
        origin_key=origin_key,
        mode="route_terminal_paired_utility",
    )
    assert status == "written"
    teacher_path = tmp_path / batch["teacher_jsonl"]
    report_path = tmp_path / batch["report_json"]
    teacher_digest = write_teacher_records(teacher_path, records)
    preregistration_digest = "d" * 64
    candidate_runtime = {"revision": "candidate"}
    backend = {"backend_name": "Jackdaw"}
    spec = {
        "implementation_revision": "a" * 40,
        "expected_source_digest": "b" * 64,
        "candidate_runtime": candidate_runtime,
        "backend": backend,
        "origin_mapping": {
            "key_sha256": hashlib.sha256(origin_key).hexdigest(),
        },
    }
    binding = {
        "protocol_id": module.ROUTE_TEACHER_PROTOCOL_ID,
        "sha256": preregistration_digest,
        "batch_id": batch["batch_id"],
        "seed_start": batch["seed_start"],
        "seeds": batch["seeds"],
        "immutable_batches": True,
        "collection_only": True,
        "training_authorized": False,
        "schema_version": 12,
        "implementation_revision": spec["implementation_revision"],
        "expected_source_digest": spec["expected_source_digest"],
        "candidate_runtime": candidate_runtime,
        "backend": backend,
        "origin_key_sha256": spec["origin_mapping"]["key_sha256"],
    }
    coverage = module._teacher_coverage(records, rows)
    report = {
        "candidate_runtime": candidate_runtime,
        "manifest": {
            "repository_dirty": False,
            "source_digest": spec["expected_source_digest"],
            "backend": backend,
        },
        "search_protocol": {
            "version": module.SEARCH_VERSION,
            "budget": {
                key: module.ROUTE_TEACHER_SEARCH[key]
                for key in ("samples", "horizon_antes", "max_steps", "override_z")
            },
            "nonce": module.ROUTE_TEACHER_SEARCH["nonce"],
            "continuation": "PublicStrategicPolicy",
            "policy_seed": module.ROUTE_TEACHER_SEARCH["policy_seed"],
            "strategy_options": True,
            "include_reorders": False,
            "success_teacher": {
                "mode": "collect",
                "affects_actions": False,
                "samples": module.ROUTE_TEACHER_TERMINAL["samples"],
                "prewin_start_ante": module.ROUTE_TEACHER_TERMINAL[
                    "prewin_start_ante"
                ],
                "endless_horizon_antes": module.ROUTE_TEACHER_TERMINAL[
                    "endless_horizon_antes"
                ],
                "max_steps": module.ROUTE_TEACHER_TERMINAL["max_steps"],
                "anchor_schedule": module.ROUTE_TEACHER_TERMINAL[
                    "anchor_schedule"
                ],
            },
        },
        "route_terminal_teacher_preregistration": binding,
        "strategy_teacher_dataset": {
            "status": "written",
            "mode": "route_terminal_paired_utility",
            "schema_version": 12,
            "sha256": teacher_digest,
            "records": len(records),
            "groups": len({record.run_group for record in records}),
            "complete_runs_only": True,
            "contains_game_seeds": False,
            "teacher_config_digest": records[0].teacher_config_digest,
            "coverage": coverage,
        },
        "results": rows,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(
        module,
        "ROUTE_TEACHER_PILOT_GATE",
        {
            "source_runs": 20,
            "minimum_record_groups": 20,
            "minimum_records": 20,
            "required_route_phases": ["SHOP"],
            "minimum_route_diverse_groups": 20,
            "minimum_route_diverse_rows": 20,
            "minimum_matched_pairs": 20,
            "minimum_search_utility_sensitive_pairs": 0,
            "sample_count": 2,
            "maximum_stored_roots": 2,
            "maximum_subset_rows": 0,
            "rejected_or_censored": 0,
        },
    )

    module._validate_route_terminal_pilot(
        spec,
        preregistration_digest=preregistration_digest,
        origin_key=origin_key,
        repository_root=tmp_path,
    )
    report["strategy_teacher_dataset"]["coverage"] = None
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(SystemExit, match="violates its frozen protocol"):
        module._validate_route_terminal_pilot(
            spec,
            preregistration_digest=preregistration_digest,
            origin_key=origin_key,
            repository_root=tmp_path,
        )


def test_route_freeze_allows_only_preregistration_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()
    binding = {
        "implementation_revision": "a" * 40,
        "expected_source_digest": "b" * 64,
        "candidate_runtime": {"revision": "runtime"},
        "backend": {"backend_name": "Jackdaw"},
    }

    def run(command, **kwargs):
        del kwargs
        output = (
            module.ROUTE_TEACHER_PREREGISTRATION + "\n"
            if "--name-only" in command
            else ""
        )
        return SimpleNamespace(stdout=output)

    monkeypatch.setattr(module.subprocess, "run", run)
    module._verify_route_terminal_freeze(
        binding,
        repository_revision="c" * 40,
        source_digest="b" * 64,
        repository_dirty=False,
        candidate_runtime={"revision": "runtime"},
        backend={"backend_name": "Jackdaw"},
        repository_root=tmp_path,
    )
    with pytest.raises(SystemExit, match="clean source"):
        module._verify_route_terminal_freeze(
            binding,
            repository_revision="c" * 40,
            source_digest="b" * 64,
            repository_dirty=True,
            candidate_runtime={"revision": "runtime"},
            backend={"backend_name": "Jackdaw"},
            repository_root=tmp_path,
        )


def test_route_bundle_uses_route_specific_atomic_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script()
    row = _route_teacher_row(module)
    records, status = module._finalize_teacher_records(
        [row],
        enabled=True,
        origin_key=b"k" * 32,
        mode="route_terminal_paired_utility",
    )
    assert status == "written"
    runtime = {"revision": "runtime"}
    monkeypatch.setattr(module, "source_snapshot", lambda _root: ("r", False, "s"))
    monkeypatch.setattr(module, "verify_jackdaw_runtime", lambda: runtime)
    teacher = tmp_path / "route-batch/teacher.jsonl"
    report = tmp_path / "route-batch/report.json"

    module._publish_route_terminal_bundle(
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
    assert report.is_file()
    with pytest.raises(SystemExit, match="refusing to overwrite"):
        module._publish_route_terminal_bundle(
            teacher,
            report,
            records,
            expected_teacher_digest=module.teacher_records_digest(records),
            encoded_report='{"complete":true}\n',
            expected_manifest=SimpleNamespace(
                repository_revision="r", source_digest="s"
            ),
            expected_runtime=runtime,
            repository_root=tmp_path,
        )
