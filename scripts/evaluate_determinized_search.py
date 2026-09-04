#!/usr/bin/env python3
"""Evaluate determinized-rollout search in pinned Jackdaw.

Emits the same report schema as ``evaluate_candidate_baselines.py`` so that
``compare_candidate_reports.py`` works unchanged.  Seeds are sharded across
``--workers`` processes, one Jackdaw and one search policy per worker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from balatro_ai_v2.backend import RunSpec
from balatro_ai_v2.balatrobot.runner import AuthorityRunner
from balatro_ai_v2.balatrobot.tracing import build_manifest
from balatro_ai_v2.baselines import build_public_baseline
from balatro_ai_v2.determinized_search import (
    SEARCH_VERSION,
    DeterminizedSearchPolicy,
    RolloutBudget,
    SuccessTeacherBudget,
)
from balatro_ai_v2.evaluation_protocol import (
    SEED_PROVENANCES,
    PanelValidationError,
    validate_seed_panel,
)
from balatro_ai_v2.jackdaw import (
    JackdawBackend,
    JackdawUnavailable,
    verify_jackdaw_runtime,
)
from balatro_ai_v2.strategy_diagnostics import (
    strategy_snapshot,
    summarize_strategy_results,
)
from balatro_ai_v2.strategy_model import (
    PublicStrategyTensorizer,
    StrategyModelError,
    load_strategy_model,
)
from balatro_ai_v2.strategy_shadow import ShadowStrategyPolicy
from balatro_ai_v2.strategy_teacher import (
    StrategyTeacherDraft,
    StrategyTeacherRecord,
    write_teacher_records,
)
from balatro_ai_v2.strategy_tuning import StrategyTuning
from evaluate_candidate_baselines import summarize_results, terminal_projection


_WORKER: dict[str, object] = {}


def _init_worker(args_dict: dict[str, object]) -> None:
    tuning = StrategyTuning.from_json(str(args_dict["tuning_json"]))
    continuation, _ = build_public_baseline(
        str(args_dict["continuation"]), str(args_dict["policy_seed"]), tuning
    )
    backend = JackdawBackend()
    policy = DeterminizedSearchPolicy(
        backend=backend,
        continuation=continuation,
        nonce=str(args_dict["nonce"]),
        budget=RolloutBudget(
            samples=int(args_dict["samples"]),
            horizon_antes=int(args_dict["horizon_antes"]),
            max_steps=int(args_dict["max_steps"]),
            override_z=float(args_dict["override_z"]),
        ),
        enable_strategy_options=bool(args_dict["strategy_options"]),
        include_reorders=bool(args_dict["include_reorders"]),
        success_teacher=(
            SuccessTeacherBudget(
                samples=int(args_dict["success_teacher_samples"]),
                prewin_start_ante=int(args_dict["success_teacher_start_ante"]),
                endless_horizon_antes=int(
                    args_dict["success_teacher_endless_antes"]
                ),
                max_steps=int(args_dict["success_teacher_max_steps"]),
            )
            if bool(args_dict["success_teacher"])
            else None
        ),
    )
    shadow: ShadowStrategyPolicy | None = None
    runner_policy = policy
    model_path = str(args_dict["strategy_shadow_model"])
    if model_path:
        model = load_strategy_model(Path(model_path))
        shadow = ShadowStrategyPolicy(
            control=policy,
            model=model,
            tensorizer=PublicStrategyTensorizer(model.config),
        )
        runner_policy = shadow
    _WORKER.update(
        args=args_dict,
        backend=backend,
        policy=policy,
        runner_policy=runner_policy,
        shadow=shadow,
    )


def _run_seed(seed_number: int) -> dict[str, object]:
    args_dict = _WORKER["args"]
    backend = _WORKER["backend"]
    policy = _WORKER["policy"]
    runner_policy = _WORKER["runner_policy"]
    shadow = _WORKER["shadow"]
    assert isinstance(args_dict, dict) and isinstance(backend, JackdawBackend)
    assert isinstance(policy, DeterminizedSearchPolicy)
    policy.reset_run()
    if isinstance(shadow, ShadowStrategyPolicy):
        shadow.reset_run()
    started = time.perf_counter()
    result = AuthorityRunner(
        backend,
        runner_policy,  # type: ignore[arg-type]
        max_decisions=int(args_dict["max_decisions"]),
        max_antes_cleared=int(args_dict["ante_cap"]),
    ).run(RunSpec(str(args_dict["deck"]), str(args_dict["stake"]), str(seed_number)))
    print(
        f"seed {seed_number}: antes_cleared={result.antes_cleared} won={result.won} "
        f"decisions={result.decisions} searched={policy.counters.searched} "
        f"changed={policy.counters.changed} seconds={time.perf_counter() - started:.0f}",
        file=sys.stderr,
        flush=True,
    )
    row = {
        "seed": seed_number,
        "complete": result.complete,
        "won": result.won,
        "antes_cleared": result.antes_cleared,
        "survived_to_ante_6": result.complete and result.ante >= 6,
        "ante": result.ante,
        "round": result.round_no,
        "decisions": result.decisions,
        "rejected_decisions": result.rejected_decisions,
        "terminal_reason": result.terminal_reason,
        "terminal_error": result.terminal_error,
        "terminal": terminal_projection(
            result.final_observation, terminal_blind=result.terminal_blind
        ),
        "final_observation": (
            json.loads(result.final_observation.canonical_json())
            if result.final_observation is not None
            else None
        ),
        "actions": {
            "counts": dict(result.action_counts),
            "semantic_counts": dict(result.semantic_action_counts),
            "cards_played": result.cards_played,
            "cards_discarded": result.cards_discarded,
        },
        "best_hand_score": result.best_hand_score,
        "strategy": (
            strategy_snapshot(result.final_observation, policy.active_intent)
            if result.final_observation is not None
            else None
        ),
        "policy_diagnostics": {},
        "search": {
            **policy.counters.as_dict(),
            "run_seconds": time.perf_counter() - started,
        },
        "search_decisions": [decision.as_dict() for decision in policy.decisions]
        if bool(args_dict["record_decisions"])
        else [],
        "strategy_shadow": _shadow_run_diagnostics(
            shadow,
            record_decisions=bool(args_dict["record_shadow_decisions"]),
        ),
        "capacity_decisions": [],
    }
    if bool(args_dict["collect_teacher"]):
        row["_teacher_drafts"] = tuple(policy.teacher_drafts)
    return row


def main() -> None:
    args = build_parser().parse_args()
    try:
        panel_validation = validate_seed_panel(
            args.seed_start, args.seeds, args.seed_provenance
        )
    except PanelValidationError as exc:
        raise SystemExit(f"invalid seed panel: {exc}") from exc
    if min(
        args.max_decisions,
        args.ante_cap,
        args.workers,
        args.success_teacher_samples,
        args.success_teacher_start_ante,
        args.success_teacher_endless_antes,
        args.success_teacher_max_steps,
    ) < 1:
        raise SystemExit("decision, worker, and teacher budgets must be positive")
    if args.include_reorders and not (args.strategy_options or args.success_teacher):
        raise SystemExit("--include-reorders requires a strategy root consumer")
    if args.teacher_jsonl is not None and not (
        args.strategy_options or args.success_teacher
    ):
        raise SystemExit("--teacher-jsonl requires strategy options or success teacher")
    if args.success_teacher and args.teacher_jsonl is None:
        raise SystemExit("--success-teacher requires --teacher-jsonl")
    if args.teacher_jsonl is not None and args.report_json is None:
        raise SystemExit("--teacher-jsonl requires --report-json for provenance")
    if args.teacher_jsonl is not None and args.strategy_shadow_model is not None:
        raise SystemExit("teacher collection cannot be combined with model shadowing")
    if (
        args.teacher_jsonl is not None
        and args.report_json is not None
        and args.teacher_jsonl.resolve() == args.report_json.resolve()
    ):
        raise SystemExit("teacher and evaluation reports need distinct output paths")
    for output_path in (args.report_json, args.teacher_jsonl):
        if output_path is not None and output_path.exists():
            raise SystemExit(f"refusing to overwrite existing output: {output_path}")
    shadow_digest: str | None = None
    shadow_artifact_status: dict[str, object] = {}
    if args.strategy_shadow_model is not None:
        try:
            shadow_model = load_strategy_model(args.strategy_shadow_model)
            provenance = shadow_model.provenance
            if (
                provenance.get("training_status") != "trained"
                or provenance.get("influence_mode") != "shadow"
            ):
                raise StrategyModelError(
                    "shadow evaluation requires a trained shadow-only artifact"
                )
            calibration = provenance.get("calibration")
            if not isinstance(calibration, dict) or not isinstance(
                calibration.get("gate"), dict
            ):
                raise StrategyModelError("shadow artifact has no validated gate")
            gate = calibration["gate"]
            shadow_artifact_status = {
                "training_status": provenance["training_status"],
                "declared_influence_mode": provenance["influence_mode"],
                "offline_gate_passed": gate["offline_gate_passed"],
                "authorizes_action_influence": gate["authorizes_action_influence"],
            }
            shadow_digest = hashlib.sha256(
                args.strategy_shadow_model.read_bytes()
            ).hexdigest()
        except (OSError, StrategyModelError) as exc:
            raise SystemExit(f"invalid --strategy-shadow-model: {exc}") from exc
    root = Path(__file__).resolve().parents[1]
    try:
        tuning = StrategyTuning.from_json(args.tuning_json)
    except ValueError as exc:
        raise SystemExit(f"invalid --tuning-json: {exc}") from exc
    _, continuation_name = build_public_baseline(
        args.continuation, args.policy_seed, tuning
    )
    budget = RolloutBudget(
        samples=args.samples,
        horizon_antes=args.horizon_antes,
        max_steps=args.max_steps,
        override_z=args.override_z,
    )
    success_teacher_mode = (
        SuccessTeacherBudget(
            samples=args.success_teacher_samples,
            prewin_start_ante=args.success_teacher_start_ante,
            endless_horizon_antes=args.success_teacher_endless_antes,
            max_steps=args.success_teacher_max_steps,
        ).canonical()
        if args.success_teacher
        else "disabled"
    )
    strategy_mode = (
        f"strategy_options={args.strategy_options};"
        f"include_reorders={args.include_reorders};"
        f"success_teacher={success_teacher_mode}"
    )
    shadow_mode = f"strategy_shadow={shadow_digest or 'disabled'}"
    policy_name = (
        f"DeterminizedSearchPolicy[{SEARCH_VERSION};{continuation_name};"
        f"{budget.canonical()};{strategy_mode};{shadow_mode}]:parent-v1"
    )
    worker_args = {
        "tuning_json": tuning.canonical_json(),
        "continuation": args.continuation,
        "policy_seed": args.policy_seed,
        "nonce": args.nonce,
        "samples": args.samples,
        "horizon_antes": args.horizon_antes,
        "max_steps": args.max_steps,
        "override_z": args.override_z,
        "max_decisions": args.max_decisions,
        "ante_cap": args.ante_cap,
        "deck": args.deck,
        "stake": args.stake,
        "record_decisions": args.record_decisions,
        "strategy_options": args.strategy_options,
        "include_reorders": args.include_reorders,
        "strategy_shadow_model": (
            str(args.strategy_shadow_model.resolve())
            if args.strategy_shadow_model
            else ""
        ),
        "record_shadow_decisions": args.record_shadow_decisions,
        "collect_teacher": args.teacher_jsonl is not None,
        "success_teacher": args.success_teacher,
        "success_teacher_samples": args.success_teacher_samples,
        "success_teacher_start_ante": args.success_teacher_start_ante,
        "success_teacher_endless_antes": args.success_teacher_endless_antes,
        "success_teacher_max_steps": args.success_teacher_max_steps,
    }
    seeds = list(range(args.seed_start, args.seed_start + args.seeds))
    started = time.perf_counter()
    try:
        candidate_runtime = verify_jackdaw_runtime()
        metadata_backend = JackdawBackend()
        if args.workers == 1:
            _init_worker(worker_args)
            results = [_run_seed(seed) for seed in seeds]
        else:
            with ProcessPoolExecutor(
                max_workers=args.workers,
                initializer=_init_worker,
                initargs=(worker_args,),
            ) as executor:
                results = list(executor.map(_run_seed, seeds, chunksize=1))
        results.sort(key=lambda row: int(row["seed"]))
        teacher_records, teacher_status = _finalize_teacher_records(
            results,
            enabled=args.teacher_jsonl is not None,
        )
        teacher_digest = (
            write_teacher_records(args.teacher_jsonl, teacher_records)
            if args.teacher_jsonl is not None and teacher_records
            else None
        )
        teacher_coverage = _teacher_coverage(teacher_records, results)
        elapsed = time.perf_counter() - started
        terminal_reasons = Counter(str(row["terminal_reason"]) for row in results)
        summary = summarize_results(
            results, elapsed=elapsed, terminal_reasons=terminal_reasons
        )
        summary["search"] = _search_summary(results)
        summary["strategy"] = summarize_strategy_results(results)
        summary["strategy_shadow"] = _shadow_summary(results)
        manifest = build_manifest(
            repository_root=root,
            command=tuple(sys.argv),
            policy_name=policy_name,
            backend=metadata_backend.metadata,
            run=RunSpec(args.deck, args.stake, f"{args.seed_start}:{args.seeds}"),
            max_decisions=args.max_decisions,
            max_antes_cleared=args.ante_cap,
            max_settle_polls=0,
            launch_fast=False,
            launch_headless=False,
            profile_mode="all_unlocked",
            model_path=args.strategy_shadow_model,
            inference_budget=(
                f"determinized_rollouts;{budget.canonical()};{strategy_mode};{shadow_mode};"
                f"workers={args.workers};ante_cap={args.ante_cap}"
            ),
        )
        payload = {
            "candidate_only": True,
            "candidate_runtime": candidate_runtime,
            "manifest": asdict(manifest),
            "search_protocol": {
                "version": SEARCH_VERSION,
                "continuation": continuation_name,
                "budget": json.loads(json.dumps(asdict(budget))),
                "nonce": args.nonce,
                "phases": ["BLIND_SELECT", "PACK", "SHOP"],
                "value": "rounds_cleared_plus_failed_blind_fraction;alive_at_horizon=+1",
                "selection": (
                    "paired_lexicographic_delta_vs_continuation;"
                    "lower_components_require_exact_higher_ties"
                    if args.strategy_options
                    else "paired_delta_vs_continuation;override_when_mean_minus_z_se_positive"
                ),
                "strategy_options": args.strategy_options,
                "include_reorders": args.include_reorders,
                "objective": (
                    "lexicographic_victory_then_survival;postwin_endless_ante_then_log_score"
                    if args.strategy_options
                    else "legacy_scalar_progress"
                ),
                "success_teacher": {
                    "enabled": args.success_teacher,
                    "affects_actions": False,
                    "samples": args.success_teacher_samples,
                    "prewin_start_ante": args.success_teacher_start_ante,
                    "endless_horizon_antes": args.success_teacher_endless_antes,
                    "max_steps": args.success_teacher_max_steps,
                    "anchor_schedule": (
                        "first_shop_each_ante;first_pack_each_ante_from_ante4;"
                        "boss_select_ante5_plus;postwin_first_shop_and_pack_each_ante"
                    ),
                    "endpoint_semantics": "victory_or_death_exact;endless_fixed_horizon;censored_never_exact",
                },
            },
            "strategy_tuning": json.loads(tuning.canonical_json()),
            "strategy_model_shadow": {
                "enabled": shadow_digest is not None,
                "artifact_digest": shadow_digest,
                "affects_actions": False,
                "record_decisions": args.record_shadow_decisions,
                **shadow_artifact_status,
            },
            "strategy_teacher_dataset": {
                "enabled": args.teacher_jsonl is not None,
                "status": teacher_status,
                "path": str(args.teacher_jsonl.resolve())
                if args.teacher_jsonl
                else None,
                "sha256": teacher_digest,
                "records": len(teacher_records),
                "groups": len({record.run_group for record in teacher_records}),
                "contains_game_seeds": False,
                "complete_runs_only": True,
                "teacher_config_digest": (
                    teacher_records[0].teacher_config_digest
                    if teacher_records
                    else None
                ),
                "coverage": teacher_coverage,
            },
            "benchmark_protocol": {
                "category": "fair_public_agent",
                "seed_provenance": args.seed_provenance,
                "panel_registry": panel_validation.as_dict(),
                "restart_selection": False,
                "filtered_seeds": False,
                "mods": False,
            },
            "results": results,
            "summary": summary,
        }
        encoded = json.dumps(payload, sort_keys=True)
        print(json.dumps({"summary": summary}, sort_keys=True))
        if args.report_json is not None:
            args.report_json.parent.mkdir(parents=True, exist_ok=True)
            with args.report_json.open("x", encoding="utf-8") as handle:
                handle.write(encoded + "\n")
        if sum(bool(row["complete"]) for row in results) != len(results):
            raise SystemExit(2)
    except JackdawUnavailable as exc:
        raise SystemExit(f"Jackdaw candidate unavailable: {exc}") from exc


def _search_summary(results: list[dict[str, object]]) -> dict[str, float]:
    totals: Counter[str] = Counter()
    for row in results:
        search = row["search"]
        assert isinstance(search, dict)
        for key in (
            "strategic_decisions",
            "searched",
            "changed",
            "unavailable",
            "rollout_steps",
            "rejected_rollouts",
            "seconds",
            "run_seconds",
            "success_teacher_steps",
            "success_teacher_rejected_rollouts",
        ):
            totals[key] += float(search[key])
    runs = max(1, len(results))
    return {
        **{key: totals[key] for key in totals},
        "mean_run_seconds": totals["run_seconds"] / runs,
        "steps_per_second": (totals["rollout_steps"] / totals["seconds"])
        if totals["seconds"] > 0
        else 0.0,
        "changed_fraction": (totals["changed"] / totals["searched"])
        if totals["searched"] > 0
        else 0.0,
        "unavailable_fraction": (
            totals["unavailable"] / totals["strategic_decisions"]
            if totals["strategic_decisions"] > 0
            else 0.0
        ),
    }


def _shadow_run_diagnostics(
    shadow: object,
    *,
    record_decisions: bool,
) -> dict[str, object]:
    if not isinstance(shadow, ShadowStrategyPolicy):
        return {"enabled": False, "decisions": 0, "unavailable": 0, "agreements": 0}
    unavailable = sum(
        decision.unavailable_reason is not None for decision in shadow.decisions
    )
    agreements = sum(
        decision.unavailable_reason is None
        and decision.preferred_action == decision.control_action
        and decision.preferred_intent == decision.control_intent
        for decision in shadow.decisions
    )
    margin_signals = sum(
        decision.recommendation_clears_margin for decision in shadow.decisions
    )
    calibrated_head_decisions: Counter[str] = Counter(
        head for decision in shadow.decisions for head in decision.calibrated_heads
    )
    return {
        "enabled": True,
        "decisions": len(shadow.decisions),
        "unavailable": unavailable,
        "agreements": agreements,
        "margin_signals": margin_signals,
        "calibrated_head_decisions": dict(calibrated_head_decisions),
        "records": [decision.as_dict() for decision in shadow.decisions]
        if record_decisions
        else [],
    }


def _finalize_teacher_records(
    results: list[dict[str, object]],
    *,
    enabled: bool,
) -> tuple[tuple[StrategyTeacherRecord, ...], str]:
    """Attach public terminal labels only after every originating run completes."""

    if not enabled:
        for row in results:
            row.pop("_teacher_drafts", None)
        return (), "disabled"
    if any(not bool(row.get("complete")) for row in results):
        for row in results:
            row.pop("_teacher_drafts", None)
        return (), "discarded_incomplete_panel"
    if any(
        not isinstance(row.get("search"), dict)
        or int(row["search"].get("rejected_rollouts", 0)) != 0
        for row in results
    ):
        for row in results:
            row.pop("_teacher_drafts", None)
        return (), "discarded_rejected_panel"
    records: list[StrategyTeacherRecord] = []
    for group_index, row in enumerate(results):
        drafts = row.pop("_teacher_drafts", ())
        if not isinstance(drafts, tuple) or not all(
            isinstance(draft, StrategyTeacherDraft) for draft in drafts
        ):
            raise RuntimeError("worker returned invalid strategy teacher drafts")
        for decision_index, draft in enumerate(drafts):
            records.append(
                draft.finalize(
                    run_group=f"run-{group_index:06d}",
                    decision_index=decision_index,
                    run_complete=True,
                    run_won=bool(row["won"]),
                    terminal_ante=int(row["antes_cleared"]),
                    best_hand_score=int(row["best_hand_score"]),
                )
            )
    if not records:
        return (), "discarded_no_eligible_decisions"
    return tuple(records), "written"


def _shadow_summary(results: list[dict[str, object]]) -> dict[str, object]:
    totals: Counter[str] = Counter()
    calibrated_head_decisions: Counter[str] = Counter()
    enabled = False
    for row in results:
        diagnostic = row.get("strategy_shadow")
        if not isinstance(diagnostic, dict):
            continue
        enabled = enabled or bool(diagnostic.get("enabled"))
        for key in ("decisions", "unavailable", "agreements", "margin_signals"):
            totals[key] += int(diagnostic.get(key, 0))
        heads = diagnostic.get("calibrated_head_decisions", {})
        if isinstance(heads, dict):
            for name, count in heads.items():
                calibrated_head_decisions[str(name)] += int(count)
    decisions = totals["decisions"]
    available = decisions - totals["unavailable"]
    return {
        "enabled": enabled,
        **dict(totals),
        "calibrated_head_decisions": dict(calibrated_head_decisions),
        "available_fraction": available / decisions if decisions else 0.0,
        "agreement_fraction": totals["agreements"] / available if available else 0.0,
    }


def _teacher_coverage(
    records: tuple[StrategyTeacherRecord, ...],
    results: list[dict[str, object]],
) -> dict[str, object]:
    winning_groups = sum(bool(row.get("won")) for row in results)
    losing_groups = len(results) - winning_groups
    endless_rows = tuple(
        record
        for record in records
        if record.goal.value == "endless"
        and any(
            sample.endless_ante is not None
            for candidate in record.candidates
            for sample in candidate.samples
        )
    )
    sensitive_late_rows = 0
    for record in records:
        if record.goal.value != "victory" or record.observation.ante < 4:
            continue
        outcomes = []
        for candidate in record.candidates:
            resolved = [
                sample.ante8_win
                for sample in candidate.samples
                if sample.ante8_win is not None
            ]
            outcomes.append(
                tuple(float(value) for value in resolved) if resolved else None
            )
        if None not in outcomes and len(set(outcomes)) > 1:
            sensitive_late_rows += 1
    endless_groups = len({record.run_group for record in endless_rows})
    passed = (
        winning_groups >= 5
        and losing_groups >= 5
        and len(endless_rows) >= 25
        and endless_groups >= 5
        and sensitive_late_rows >= 20
    )
    return {
        "winning_source_groups": winning_groups,
        "losing_source_groups": losing_groups,
        "resolved_endless_rows": len(endless_rows),
        "resolved_endless_groups": endless_groups,
        "late_action_sensitive_ante8_rows": sensitive_late_rows,
        "training_coverage_passed": passed,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--continuation", default="strategic")
    parser.add_argument("--policy-seed", default="baseline-v1")
    parser.add_argument("--nonce", default="search-v1")
    parser.add_argument("--seed-start", type=int, default=901)
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--deck", default="RED")
    parser.add_argument("--stake", default="WHITE")
    parser.add_argument("--samples", type=int, default=8)
    parser.add_argument("--horizon-antes", type=int, default=2)
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--override-z", type=float, default=1.0)
    parser.add_argument("--max-decisions", type=int, default=800)
    parser.add_argument("--ante-cap", type=int, default=20)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--tuning-json", default=StrategyTuning().canonical_json())
    parser.add_argument("--record-decisions", action="store_true")
    parser.add_argument("--strategy-shadow-model", type=Path)
    parser.add_argument("--record-shadow-decisions", action="store_true")
    parser.add_argument("--teacher-jsonl", type=Path)
    parser.add_argument("--success-teacher", action="store_true")
    parser.add_argument("--success-teacher-samples", type=int, default=2)
    parser.add_argument("--success-teacher-start-ante", type=int, default=4)
    parser.add_argument("--success-teacher-endless-antes", type=int, default=2)
    parser.add_argument("--success-teacher-max-steps", type=int, default=600)
    parser.add_argument("--strategy-options", action="store_true")
    parser.add_argument("--include-reorders", action="store_true")
    parser.add_argument(
        "--seed-provenance",
        choices=SEED_PROVENANCES,
        default="development",
    )
    parser.add_argument("--report-json", type=Path)
    return parser


if __name__ == "__main__":
    main()
