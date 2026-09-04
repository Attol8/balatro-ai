from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


def _load_script():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "compare_terminal_action_reports.py"
    )
    spec = importlib.util.spec_from_file_location(
        "compare_terminal_action_reports_script", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _success_protocol(mode: str) -> dict[str, object]:
    value: dict[str, object] = {
        "enabled": mode == "actions",
        "mode": mode,
        "affects_actions": mode == "actions",
        "emits_teacher_rows": False,
        "samples": 2,
        "prewin_start_ante": 4,
        "endless_horizon_antes": 2,
        "max_steps": 600,
        "anchor_schedule": (
            "first_shop_each_ante;first_pack_each_ante_from_ante4;"
            "boss_select_ante5_plus;postwin_first_shop_and_pack_each_ante"
        ),
        "endpoint_semantics": (
            "victory_or_death_exact;endless_fixed_horizon;"
            "censored_never_exact;no_public_progress_inadmissible_for_actions"
        ),
        "terminal_action_budget": {
            "max_samples": 12,
            "max_roots": 64,
            "family_alpha": 0.05,
        }
        if mode == "actions"
        else None,
        "terminal_action_selector": (
            "root_adjusted_one_sided_sign;zero_adverse_discordances;"
            "victory=exact_win;endless=alive,ante,log_score;"
            "ties_inert;root_overflow=fail_closed_without_truncation;"
            "fallback=exact_behavior_identity"
            if mode == "actions"
            else None
        ),
        "sample_nonce_stream": "search-v1:success-terminal-v1",
        "root_builder": "determinized-search-v6",
        "counter_semantics": (
            "attempted=all_scheduled_anchors;completed=no_fallback;"
            "fallback=action_mode_exact_behavior_fallback;"
            "unavailable=subset_of_fallback_without_valid_evaluation"
        ),
    }
    value["protocol_digest"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return value


def _report(
    *, actions: bool, preregistration: dict[str, object], preregistration_digest: str
) -> dict[str, object]:
    results = []
    for seed in range(1055, 1075):
        won = actions and seed == 1055
        override = actions and seed == 1055
        behavior = {"action": {"type": "leave_shop"}, "intent": None}
        executed = (
            {"action": {"type": "reroll_shop"}, "intent": "economy"}
            if override
            else behavior
        )
        decision = {
            "roots": 2,
            "initial_samples": 2,
            "max_samples_used": 5 if override else 2,
            "sample_evaluations": 10 if override else 4,
            "rejected_rollouts": 0,
            "censored_rollouts": 0,
            "behavior_index": 0,
            "teacher_selected_index": 1 if override else 0,
            "executed_index": 1 if override else 0,
            "behavior": behavior,
            "teacher_selected": executed,
            "executed": executed,
            "fallback_reason": None if override else "insufficient_terminal_dominance",
            "affects_actions": True,
            "unavailable": False,
            "unsupported": False,
            "identity_override": override,
            "positive_discordances": 5 if override else 0,
            "adverse_discordances": 0,
            "required_positive_discordances": 5,
        }
        results.append(
            {
                "seed": seed,
                "complete": True,
                "won": won,
                "antes_cleared": 8 if won else 3,
                "survived_to_ante_6": won,
                "ante": 9 if won else 4,
                "best_hand_score": 100 if won else 10,
                "terminal_reason": "game_over",
                "search": {
                    "rejected_rollouts": 0,
                    "unavailable": 0,
                    "success_teacher_rejected_rollouts": 0,
                    "success_teacher_censored_rollouts": 0,
                    "success_anchors_attempted": 1 if actions else 0,
                    "success_anchors_completed": 1 if override else 0,
                    "success_anchor_fallbacks": (
                        int(actions and not override)
                    ),
                    "success_anchor_unavailable": 0,
                    "success_anchor_unsupported": 0,
                    "success_action_overrides": 1
                    if actions and seed == 1055
                    else 0,
                    "success_intent_only_overrides": 0,
                },
                "success_teacher_decisions": [decision] if actions else [],
            }
        )
    return {
        "candidate_only": True,
        "candidate_runtime": preregistration["candidate_runtime"],
        "manifest": {
            "repository_revision": "frozen",
            "repository_dirty": False,
            "source_digest": preregistration["expected_source_digest"],
            "backend": preregistration["backend"],
            "canonical_schema_version": 6,
            "trace_schema_version": 1,
            "max_decisions": 1200,
            "max_antes_cleared": 12,
            "max_settle_polls": 0,
            "wall_clock_limit_seconds": None,
            "profile_mode": "all_unlocked",
            "launch_fast": False,
            "launch_headless": False,
            "inference_budget": "actions" if actions else "baseline",
            "run": {"deck": "RED", "stake": "WHITE", "seed": "1055:20"},
        },
        "search_protocol": {
            "version": "determinized-search-v6",
            "continuation": "PublicStrategicPolicy",
            "policy_seed": "baseline-v1",
            "budget": {
                "samples": 6,
                "horizon_antes": 1,
                "max_steps": 200,
                "override_z": 1.0,
            },
            "nonce": "search-v1",
            "phases": ["BLIND_SELECT", "PACK", "SHOP"],
            "value": (
                "rounds_cleared_plus_failed_blind_fraction;alive_at_horizon=+1"
            ),
            "selection": (
                "paired_delta_vs_continuation;"
                "override_when_mean_minus_z_se_positive"
            ),
            "strategy_options": False,
            "include_reorders": False,
            "objective": "legacy_scalar_progress",
            "success_teacher": _success_protocol("actions" if actions else "disabled"),
        },
        "strategy_tuning": {
            "replacement_margin": 20,
            "reserve_ante_1": 3,
            "reserve_ante_2": 6,
            "reserve_ante_3": 12,
            "sell_threshold": 65,
        },
        "terminal_action_preregistration": {
            "protocol_id": "terminal-actions-development-v1",
            "sha256": (
                preregistration_digest
            ),
            "mode": "candidate" if actions else "baseline",
            "single_use": True,
            "declared_report": (
                "runs/experiments/terminal-actions-v6/"
                f"seeds1055-1074.{'candidate' if actions else 'baseline'}.json"
            ),
            "implementation_revision": preregistration["implementation_revision"],
            "expected_source_digest": preregistration["expected_source_digest"],
            "candidate_runtime": preregistration["candidate_runtime"],
            "backend": preregistration["backend"],
        },
        "benchmark_protocol": {
            "category": "fair_public_agent",
            "seed_provenance": "development",
            "restart_selection": False,
            "filtered_seeds": False,
            "mods": False,
        },
        "results": results,
    }


def _write_pair(tmp_path: Path) -> tuple[Path, Path, Path]:
    baseline = tmp_path / "baseline.json"
    candidate = tmp_path / "candidate.json"
    preregistration_path = tmp_path / "preregistration.json"
    source = (
        Path(__file__).resolve().parents[1]
        / "experiments/terminal-actions-v6-preregistration.json"
    )
    preregistration = json.loads(source.read_text(encoding="utf-8"))
    preregistration["implementation_revision"] = "a" * 40
    preregistration["expected_source_digest"] = "b" * 64
    encoded = json.dumps(preregistration, sort_keys=True)
    preregistration_path.write_text(encoded, encoding="utf-8")
    digest = hashlib.sha256(encoded.encode()).hexdigest()
    baseline.write_text(
        json.dumps(
            _report(
                actions=False,
                preregistration=preregistration,
                preregistration_digest=digest,
            )
        ),
        encoding="utf-8",
    )
    candidate.write_text(
        json.dumps(
            _report(
                actions=True,
                preregistration=preregistration,
                preregistration_digest=digest,
            )
        ),
        encoding="utf-8",
    )
    return baseline, candidate, preregistration_path


def test_strict_terminal_comparison_accepts_only_capability_evidence(
    tmp_path: Path,
) -> None:
    module = _load_script()
    baseline, candidate, preregistration = _write_pair(tmp_path)

    result = module.compare_terminal_action_reports(
        baseline, candidate, preregistration
    )

    assert result["capability_gate_passed"]
    assert result["capability_only"]
    assert not result["authorizes_promotion"]
    assert result["intervention_coverage"]["identity_overrides"] == 1


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["manifest"].update(source_digest="changed"), "source"),
        (
            lambda value: value["search_protocol"]["budget"].update(samples=7),
            "base search field",
        ),
        (
            lambda value: value["results"][0].update(complete=False),
            "incomplete run",
        ),
        (
            lambda value: value["search_protocol"]["success_teacher"].update(
                protocol_digest="0" * 64
            ),
            "digest mismatch",
        ),
        (
            lambda value: [
                row["search"].update(
                    success_action_overrides=0,
                    success_intent_only_overrides=0,
                )
                for row in value["results"]
            ],
            "counter disagrees",
        ),
        (
            lambda value: value["strategy_tuning"].update(replacement_margin=21),
            "strategy tuning",
        ),
        (
            lambda value: value["terminal_action_preregistration"].update(
                sha256="0" * 64
            ),
            "preregistration",
        ),
        (
            lambda value: value["results"][0]["success_teacher_decisions"][0].update(
                sample_evaluations=4
            ),
            "impossible selector evidence",
        ),
        (
            lambda value: (
                value["search_protocol"]["success_teacher"].update(samples=3),
                value["search_protocol"]["success_teacher"].update(
                    protocol_digest=hashlib.sha256(
                        json.dumps(
                            {
                                key: item
                                for key, item in value["search_protocol"][
                                    "success_teacher"
                                ].items()
                                if key != "protocol_digest"
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                    ).hexdigest()
                ),
            ),
            "preregistered constants",
        ),
    ],
)
def test_strict_terminal_comparison_rejects_protocol_drift(
    tmp_path: Path,
    mutation,
    message: str,
) -> None:
    module = _load_script()
    baseline, candidate, preregistration = _write_pair(tmp_path)
    value = json.loads(candidate.read_text(encoding="utf-8"))
    mutation(value)
    candidate.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(module.ReportError, match=message):
        module.compare_terminal_action_reports(baseline, candidate, preregistration)


def test_strict_terminal_comparison_rejects_baseline_search_failure(
    tmp_path: Path,
) -> None:
    module = _load_script()
    baseline, candidate, preregistration = _write_pair(tmp_path)
    value = json.loads(baseline.read_text(encoding="utf-8"))
    value["results"][0]["search"]["rejected_rollouts"] = 1
    baseline.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(module.ReportError, match="baseline contains failed search"):
        module.compare_terminal_action_reports(baseline, candidate, preregistration)
