#!/usr/bin/env python3
"""Evaluate determinized-rollout search in pinned Jackdaw.

Emits the same report schema as ``evaluate_candidate_baselines.py`` so that
``compare_candidate_reports.py`` works unchanged.  Seeds are sharded across
``--workers`` processes, one Jackdaw and one search policy per worker.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os
import secrets
import subprocess
import sys
import tempfile
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from balatro_ai_v2.backend import RunSpec
from balatro_ai_v2.actions import (
    ReorderConsumables,
    ReorderHand,
    ReorderJokers,
    action_to_data,
    iter_legal_actions,
)
from balatro_ai_v2.balatrobot.runner import AuthorityRunner
from balatro_ai_v2.balatrobot.tracing import build_manifest, source_snapshot
from balatro_ai_v2.baselines import build_public_baseline
from balatro_ai_v2.candidate_trace_replay import (
    CandidateTraceWriter,
    build_candidate_trace_manifest,
)
from balatro_ai_v2.determinized_search import (
    SEARCH_VERSION,
    STRATEGY_SPECIALIST_MAX_ROOTS,
    DeterminizedSearchPolicy,
    RolloutBudget,
    SearchDecision,
    SearchTimingCollector,
    SuccessTeacherBudget,
    SuccessTerminalActionBudget,
    select_paired_root,
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
from balatro_ai_v2.policy_wire import POLICY_ACTION_CONTRACT
from balatro_ai_v2.strategy_diagnostics import (
    strategy_snapshot,
    summarize_strategy_results,
)
from balatro_ai_v2.strategy_engine import RunRoute
from balatro_ai_v2.strategy_learning import (
    PAIRED_UTILITY_ONLY_LOSS_WEIGHTS,
    PAIRED_UTILITY_ONLY_OBJECTIVE,
)
from balatro_ai_v2.strategy_continuation import CertifiedUtilityContinuationPolicy
from balatro_ai_v2.strategy_model import (
    PublicStrategyTensorizer,
    StrategyModelError,
    load_strategy_model,
)
from balatro_ai_v2.route_teacher import (
    RouteTeacherValidationError,
    route_teacher_coverage_gate_failures,
    route_terminal_teacher_coverage,
    validate_route_teacher_component,
)
from balatro_ai_v2.route_teacher_protocol import (
    ROUTE_TEACHER_BATCHES,
    ROUTE_TEACHER_BATCH_SIZE,
    ROUTE_TEACHER_BATCH_STARTS,
    ROUTE_TEACHER_COVERAGE_GATE,
    ROUTE_TEACHER_ORIGIN_KEY,
    ROUTE_TEACHER_PILOT_GATE,
    ROUTE_TEACHER_PREREGISTRATION,
    ROUTE_TEACHER_PROTOCOL_ID,
    ROUTE_TEACHER_SEARCH,
    ROUTE_TEACHER_TERMINAL,
)
from balatro_ai_v2.strategy_shadow import ShadowStrategyPolicy
from balatro_ai_v2.strategy_teacher import (
    STRATEGY_TEACHER_SCHEMA_VERSION,
    StrategyTargetEndpoint,
    StrategyTeacherCandidate,
    StrategyTeacherDraft,
    StrategyTeacherRecord,
    teacher_records_digest,
    teacher_records_from_bytes,
    write_teacher_records,
)
from balatro_ai_v2.strategy_tuning import StrategyTuning
from evaluate_candidate_baselines import summarize_results, terminal_projection


_WORKER: dict[str, object] = {}
_CONTEXTUAL_BATCHES = tuple(
    {
        "batch_id": f"batch-{index + 1:02d}",
        "seed_start": seed_start,
        "seeds": 50,
        "teacher_jsonl": (
            "runs/experiments/contextual-continuation-v14/"
            f"batch-{index + 1:02d}/teacher.jsonl"
        ),
        "report_json": (
            "runs/experiments/contextual-continuation-v14/"
            f"batch-{index + 1:02d}/report.json"
        ),
    }
    for index, seed_start in enumerate(range(2602, 2902, 50))
)
_CONTEXTUAL_SEARCH = {
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
}
_CONTEXTUAL_TRAINING = {
    "objective": PAIRED_UTILITY_ONLY_OBJECTIVE,
    "loss_weights": asdict(PAIRED_UTILITY_ONLY_LOSS_WEIGHTS),
    "split_nonce": "strategy-split-v3-predeclared",
    "train_groups": 182,
    "calibration_groups": 59,
    "holdout_groups": 59,
    "epochs": 30,
    "training_seed": 20260904,
    "hidden_size": 64,
    "attention_heads": 4,
    "attention_layers": 2,
    "feedforward_size": 128,
    "max_entities": 256,
    "max_actions": 512,
    "learning_rate": 0.0003,
    "weight_decay": 0.0001,
    "max_gradient_norm": 1.0,
    "chunk_size": 16,
    "device": "cpu",
}
_CONTEXTUAL_FIRST_100_GATE = {
    "minimum_action_sensitive_fraction": 0.4,
    "minimum_observed_victory_groups": 10,
    "rejected_or_censored": 0,
}
_CONTEXTUAL_REORDERS = (ReorderHand, ReorderJokers, ReorderConsumables)


def _init_worker(args_dict: dict[str, object]) -> None:
    tuning = StrategyTuning.from_json(str(args_dict["tuning_json"]))
    continuation, _ = build_public_baseline(
        str(args_dict["continuation"]), str(args_dict["policy_seed"]), tuning
    )
    backend = JackdawBackend()
    rollout_continuation = None
    continuation_model = str(args_dict["strategy_continuation_model"])
    continuation_certificate = str(args_dict["strategy_continuation_certificate"])
    continuation_training_report = str(
        args_dict["strategy_continuation_training_report"]
    )
    if continuation_model:
        fallback, _ = build_public_baseline(
            str(args_dict["continuation"]), str(args_dict["policy_seed"]), tuning
        )
        rollout_continuation = CertifiedUtilityContinuationPolicy.from_artifacts(
            control=fallback,
            model_path=Path(continuation_model),
            certificate_path=Path(continuation_certificate),
            training_report_path=Path(continuation_training_report),
        )
    policy = DeterminizedSearchPolicy(
        backend=backend,
        continuation=continuation,
        rollout_continuation=rollout_continuation,
        nonce=str(args_dict["nonce"]),
        budget=RolloutBudget(
            samples=int(args_dict["samples"]),
            horizon_antes=int(args_dict["horizon_antes"]),
            max_steps=int(args_dict["max_steps"]),
            override_z=float(args_dict["override_z"]),
        ),
        enable_strategy_options=bool(args_dict["strategy_options"]),
        collect_dense_teacher=bool(args_dict["dense_teacher"]),
        include_reorders=bool(args_dict["include_reorders"]),
        success_teacher=(
            SuccessTeacherBudget(
                samples=int(args_dict["success_teacher_samples"]),
                prewin_start_ante=int(args_dict["success_teacher_start_ante"]),
                endless_horizon_antes=int(args_dict["success_teacher_endless_antes"]),
                max_steps=int(args_dict["success_teacher_max_steps"]),
            )
            if bool(args_dict["success_teacher"])
            or bool(args_dict["success_terminal_actions"])
            else None
        ),
        success_terminal_actions=(
            SuccessTerminalActionBudget(
                max_samples=int(args_dict["success_terminal_max_samples"]),
                max_roots=int(args_dict["success_terminal_max_roots"]),
                family_alpha=float(args_dict["success_terminal_family_alpha"]),
            )
            if bool(args_dict["success_terminal_actions"])
            else None
        ),
        timing=(
            SearchTimingCollector()
            if bool(args_dict["profile_search_timing"])
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
    spec = RunSpec(str(args_dict["deck"]), str(args_dict["stake"]), str(seed_number))
    trace = None
    trace_dir = str(args_dict["trace_dir"])
    if trace_dir:
        trace_index = seed_number - int(args_dict["seed_start"])
        trace = CandidateTraceWriter(
            Path(trace_dir) / f"run-{trace_index:04d}.jsonl",
            build_candidate_trace_manifest(
                repository_root=Path(str(args_dict["repository_root"])),
                policy_name=str(args_dict["policy_name"]),
                backend=backend.metadata,
                deck=spec.deck,
                stake=spec.stake,
                max_decisions=int(args_dict["max_decisions"]),
                max_antes_cleared=int(args_dict["ante_cap"]),
                inference_budget=str(args_dict["inference_budget"]),
                model_digest=(
                    str(args_dict["model_digest"])
                    if args_dict["model_digest"] is not None
                    else None
                ),
            ),
        )
    started = time.perf_counter()
    result = AuthorityRunner(
        backend,
        runner_policy,  # type: ignore[arg-type]
        max_decisions=int(args_dict["max_decisions"]),
        max_antes_cleared=int(args_dict["ante_cap"]),
        trace=trace,
    ).run(spec)
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
            strategy_snapshot(
                result.final_observation, policy.active_intent, policy.active_route
            )
            if result.final_observation is not None
            else None
        ),
        "policy_diagnostics": {},
        "search": {
            **policy.counters.as_dict(),
            "run_seconds": time.perf_counter() - started,
        },
        "search_decision_profile": _search_decision_profile(policy.decisions),
        "search_failure_reasons": _search_failure_reasons(policy.decisions),
        "search_decisions": [decision.as_dict() for decision in policy.decisions]
        if bool(args_dict["record_decisions"])
        else [],
        "success_teacher_decisions": [
            decision.as_dict() for decision in policy.success_decisions
        ],
        "strategy_shadow": _shadow_run_diagnostics(
            shadow,
            record_decisions=bool(args_dict["record_shadow_decisions"]),
        ),
        "capacity_decisions": [],
    }
    if bool(args_dict["collect_teacher"]):
        row["_teacher_drafts"] = tuple(policy.teacher_drafts)
    if policy.timing is not None:
        row["search_timing"] = policy.timing.as_dict()
    return row


def _validate_terminal_preregistration(
    args: argparse.Namespace,
    tuning: StrategyTuning,
    *,
    repository_root: Path,
) -> dict[str, object] | None:
    reserved = range(1055, 1075)
    requested = range(args.seed_start, args.seed_start + args.seeds)
    overlaps_reserved = (
        requested.start < reserved.stop and reserved.start < requested.stop
    )
    path = args.terminal_preregistration_json
    if path is None:
        if overlaps_reserved:
            raise SystemExit("seeds 1055-1074 require --terminal-preregistration-json")
        return None
    try:
        raw = path.read_bytes()
        spec = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid terminal preregistration: {exc}") from exc
    if not isinstance(spec, dict):
        raise SystemExit("terminal preregistration root must be an object")
    if (
        spec.get("protocol_id") != "terminal-actions-development-v1"
        or spec.get("status") != "reserved"
        or spec.get("single_use") is not True
    ):
        raise SystemExit("terminal preregistration is not the reserved protocol")
    expected_top = {
        "seed_start": args.seed_start,
        "seeds": args.seeds,
        "seed_provenance": args.seed_provenance,
        "deck": args.deck,
        "stake": args.stake,
    }
    for key, actual in expected_top.items():
        if spec.get(key) != actual:
            raise SystemExit(f"terminal preregistration mismatch: {key}")
    base = spec.get("base_search")
    terminal = spec.get("terminal_actions")
    if not isinstance(base, dict) or not isinstance(terminal, dict):
        raise SystemExit("terminal preregistration omitted search budgets")
    expected_base = {
        "samples": args.samples,
        "horizon_antes": args.horizon_antes,
        "max_steps": args.max_steps,
        "override_z": args.override_z,
        "max_decisions": args.max_decisions,
        "ante_cap": args.ante_cap,
        "workers": args.workers,
        "nonce": args.nonce,
        "continuation": args.continuation,
        "policy_seed": args.policy_seed,
        "strategy_options": args.strategy_options,
        "include_reorders": args.include_reorders,
    }
    expected_terminal = {
        "success_teacher_samples": args.success_teacher_samples,
        "success_teacher_start_ante": args.success_teacher_start_ante,
        "success_teacher_endless_antes": args.success_teacher_endless_antes,
        "success_teacher_max_steps": args.success_teacher_max_steps,
        "success_terminal_max_samples": args.success_terminal_max_samples,
        "success_terminal_max_roots": args.success_terminal_max_roots,
        "success_terminal_family_alpha": args.success_terminal_family_alpha,
    }
    if base != expected_base or terminal != expected_terminal:
        raise SystemExit("terminal preregistration search budget mismatch")
    if spec.get("strategy_tuning") != json.loads(tuning.canonical_json()):
        raise SystemExit("terminal preregistration strategy tuning mismatch")
    if args.success_teacher or args.strategy_shadow_model is not None:
        raise SystemExit("terminal preregistration forbids teacher and shadow modes")
    mode = "candidate" if args.success_terminal_actions else "baseline"
    report_field = f"{mode}_report"
    declared_report = spec.get(report_field)
    if not isinstance(declared_report, str) or args.report_json is None:
        raise SystemExit("terminal preregistration requires its declared report path")
    if args.report_json.resolve() != (repository_root / declared_report).resolve():
        raise SystemExit(f"terminal preregistration mismatch: {report_field}")
    return {
        "protocol_id": spec["protocol_id"],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "mode": mode,
        "single_use": True,
        "declared_report": declared_report,
        "implementation_revision": spec.get("implementation_revision"),
        "expected_source_digest": spec.get("expected_source_digest"),
        "candidate_runtime": spec.get("candidate_runtime"),
        "backend": spec.get("backend"),
    }


def _validate_route_terminal_preregistration(
    args: argparse.Namespace,
    tuning: StrategyTuning,
    *,
    repository_root: Path,
) -> dict[str, object] | None:
    reserved = range(
        ROUTE_TEACHER_BATCH_STARTS[0],
        ROUTE_TEACHER_BATCH_STARTS[-1] + ROUTE_TEACHER_BATCH_SIZE,
    )
    requested = range(args.seed_start, args.seed_start + args.seeds)
    overlaps_reserved = (
        requested.start < reserved.stop and reserved.start < requested.stop
    )
    path = args.route_terminal_preregistration_json
    if path is None:
        if overlaps_reserved:
            raise SystemExit(
                "route-terminal seeds 2311-2410 require "
                "--route-terminal-preregistration-json"
            )
        return None
    expected_path = (repository_root / ROUTE_TEACHER_PREREGISTRATION).resolve()
    if path.resolve() != expected_path:
        raise SystemExit("route-terminal preregistration path is not frozen")
    try:
        raw = path.read_bytes()
        spec = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid route-terminal preregistration: {exc}") from exc
    if not isinstance(spec, dict):
        raise SystemExit("route-terminal preregistration root must be an object")
    if (
        spec.get("protocol_id") != ROUTE_TEACHER_PROTOCOL_ID
        or spec.get("status") != "reserved"
        or spec.get("immutable_batches") is not True
        or spec.get("collection_only") is not True
        or spec.get("training_authorized") is not False
        or spec.get("schema_version") != STRATEGY_TEACHER_SCHEMA_VERSION
        or spec.get("seed_provenance") != "development"
        or spec.get("deck") != "RED"
        or spec.get("stake") != "WHITE"
        or spec.get("search") != ROUTE_TEACHER_SEARCH
        or spec.get("terminal_teacher") != ROUTE_TEACHER_TERMINAL
        or spec.get("pilot_gate") != ROUTE_TEACHER_PILOT_GATE
        or spec.get("coverage_gate") != ROUTE_TEACHER_COVERAGE_GATE
        or spec.get("batches") != list(ROUTE_TEACHER_BATCHES)
        or spec.get("strategy_tuning") != json.loads(tuning.canonical_json())
        or args.seed_provenance != spec.get("seed_provenance")
        or args.deck != spec.get("deck")
        or args.stake != spec.get("stake")
    ):
        raise SystemExit("route-terminal preregistration changed the frozen protocol")
    expected_search = {
        "samples": args.samples,
        "horizon_antes": args.horizon_antes,
        "max_steps": args.max_steps,
        "override_z": args.override_z,
        "max_decisions": args.max_decisions,
        "ante_cap": args.ante_cap,
        "workers": args.workers,
        "nonce": args.nonce,
        "continuation": args.continuation,
        "policy_seed": args.policy_seed,
        "strategy_options": args.strategy_options,
        "include_reorders": args.include_reorders,
        "dense_teacher": args.dense_teacher,
    }
    expected_terminal = {
        "samples": args.success_teacher_samples,
        "prewin_start_ante": args.success_teacher_start_ante,
        "endless_horizon_antes": args.success_teacher_endless_antes,
        "max_steps": args.success_teacher_max_steps,
        "affects_actions": args.success_terminal_actions,
        "anchor_schedule": ROUTE_TEACHER_TERMINAL["anchor_schedule"],
    }
    if (
        expected_search != ROUTE_TEACHER_SEARCH
        or expected_terminal != ROUTE_TEACHER_TERMINAL
        or not args.success_teacher
        or args.success_terminal_actions
        or args.dense_teacher
        or not args.strategy_options
        or args.include_reorders
        or args.strategy_shadow_model is not None
        or args.strategy_continuation_model is not None
        or args.record_shadow_decisions
        or args.teacher_jsonl is None
        or args.report_json is None
    ):
        raise SystemExit("route-terminal preregistration requires isolated collection")
    origin = spec.get("origin_mapping")
    if (
        not isinstance(origin, dict)
        or origin.get("algorithm") != "hmac-sha256-truncated-128"
        or origin.get("key_path") != ROUTE_TEACHER_ORIGIN_KEY
        or not isinstance(origin.get("key_sha256"), str)
        or len(origin["key_sha256"]) != 64
        or args.origin_key_file is None
        or args.origin_key_file.resolve()
        != (repository_root / ROUTE_TEACHER_ORIGIN_KEY).resolve()
    ):
        raise SystemExit("route-terminal preregistration origin mapping mismatch")
    try:
        origin_key = args.origin_key_file.read_bytes()
    except OSError as exc:
        raise SystemExit("route-terminal origin key is unreadable") from exc
    if (
        len(origin_key) != 32
        or hashlib.sha256(origin_key).hexdigest() != origin["key_sha256"]
        or not isinstance(spec.get("candidate_runtime"), dict)
        or not isinstance(spec.get("backend"), dict)
    ):
        raise SystemExit("route-terminal preregistration provenance is invalid")
    matches = [
        batch
        for batch in ROUTE_TEACHER_BATCHES
        if batch["seed_start"] == args.seed_start and batch["seeds"] == args.seeds
    ]
    if len(matches) != 1:
        raise SystemExit("route-terminal preregistration has no unique requested batch")
    batch = matches[0]
    for key, actual in (
        ("teacher_jsonl", args.teacher_jsonl),
        ("report_json", args.report_json),
    ):
        if actual.resolve() != (repository_root / str(batch[key])).resolve():
            raise SystemExit(f"route-terminal preregistration mismatch: {key}")
    digest = hashlib.sha256(raw).hexdigest()
    if batch["batch_id"] != ROUTE_TEACHER_BATCHES[0]["batch_id"]:
        _validate_route_terminal_pilot(
            spec,
            preregistration_digest=digest,
            origin_key=origin_key,
            repository_root=repository_root,
        )
    return {
        "protocol_id": spec["protocol_id"],
        "sha256": digest,
        "batch_id": batch["batch_id"],
        "seed_start": args.seed_start,
        "seeds": args.seeds,
        "immutable_batches": True,
        "collection_only": True,
        "training_authorized": False,
        "schema_version": STRATEGY_TEACHER_SCHEMA_VERSION,
        "implementation_revision": spec.get("implementation_revision"),
        "expected_source_digest": spec.get("expected_source_digest"),
        "candidate_runtime": spec.get("candidate_runtime"),
        "backend": spec.get("backend"),
        "origin_key_sha256": origin["key_sha256"],
    }


def _validate_route_terminal_pilot(
    spec: dict[str, object],
    *,
    preregistration_digest: str,
    origin_key: bytes,
    repository_root: Path,
) -> None:
    batch = ROUTE_TEACHER_BATCHES[0]
    try:
        teacher_path = repository_root / str(batch["teacher_jsonl"])
        report_path = repository_root / str(batch["report_json"])
        teacher_bytes = teacher_path.read_bytes()
        report = json.loads(report_path.read_bytes())
        records = teacher_records_from_bytes(teacher_bytes)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit("route-terminal pilot artifacts are incomplete") from exc
    if not isinstance(report, dict):
        raise SystemExit("route-terminal pilot report is invalid")
    teacher = report.get("strategy_teacher_dataset")
    binding = report.get("route_terminal_teacher_preregistration")
    manifest = report.get("manifest")
    search = report.get("search_protocol")
    success = search.get("success_teacher") if isinstance(search, dict) else None
    coverage = route_terminal_teacher_coverage(records)
    reported_coverage = (
        teacher.get("coverage") if isinstance(teacher, dict) else None
    )
    expected_binding = {
        "protocol_id": ROUTE_TEACHER_PROTOCOL_ID,
        "sha256": preregistration_digest,
        "batch_id": batch["batch_id"],
        "seed_start": batch["seed_start"],
        "seeds": batch["seeds"],
        "immutable_batches": True,
        "collection_only": True,
        "training_authorized": False,
        "schema_version": STRATEGY_TEACHER_SCHEMA_VERSION,
        "implementation_revision": spec.get("implementation_revision"),
        "expected_source_digest": spec.get("expected_source_digest"),
        "candidate_runtime": spec.get("candidate_runtime"),
        "backend": spec.get("backend"),
        "origin_key_sha256": spec["origin_mapping"]["key_sha256"],
    }
    if (
        binding != expected_binding
        or not isinstance(teacher, dict)
        or teacher.get("status") != "written"
        or teacher.get("mode") != "route_terminal_paired_utility"
        or teacher.get("schema_version") != STRATEGY_TEACHER_SCHEMA_VERSION
        or teacher.get("sha256") != hashlib.sha256(teacher_bytes).hexdigest()
        or teacher.get("records") != len(records)
        or teacher.get("groups") != len({record.run_group for record in records})
        or teacher.get("complete_runs_only") is not True
        or teacher.get("contains_game_seeds") is not False
        or {record.teacher_config_digest for record in records}
        != {teacher.get("teacher_config_digest")}
        or not isinstance(reported_coverage, dict)
        or reported_coverage.get("route_terminal_paired_utility") != coverage
        or not isinstance(manifest, dict)
        or manifest.get("repository_dirty") is not False
        or manifest.get("source_digest") != spec.get("expected_source_digest")
        or manifest.get("backend") != spec.get("backend")
        or report.get("candidate_runtime") != spec.get("candidate_runtime")
        or not isinstance(search, dict)
        or search.get("version") != SEARCH_VERSION
        or search.get("budget")
        != {
            key: ROUTE_TEACHER_SEARCH[key]
            for key in ("samples", "horizon_antes", "max_steps", "override_z")
        }
        or search.get("nonce") != ROUTE_TEACHER_SEARCH["nonce"]
        or search.get("continuation") != "PublicStrategicPolicy"
        or search.get("policy_seed") != ROUTE_TEACHER_SEARCH["policy_seed"]
        or search.get("strategy_options") is not True
        or search.get("include_reorders") is not False
        or not isinstance(success, dict)
        or success.get("mode") != "collect"
        or success.get("affects_actions") is not False
        or success.get("samples") != ROUTE_TEACHER_TERMINAL["samples"]
        or success.get("prewin_start_ante")
        != ROUTE_TEACHER_TERMINAL["prewin_start_ante"]
        or success.get("endless_horizon_antes")
        != ROUTE_TEACHER_TERMINAL["endless_horizon_antes"]
        or success.get("max_steps") != ROUTE_TEACHER_TERMINAL["max_steps"]
        or success.get("anchor_schedule")
        != ROUTE_TEACHER_TERMINAL["anchor_schedule"]
    ):
        raise SystemExit("route-terminal pilot violates its frozen protocol")
    try:
        validate_route_teacher_component(
            records,
            report.get("results"),
            origin_key=origin_key,
            expected_seed_start=int(batch["seed_start"]),
            expected_seed_count=int(batch["seeds"]),
            sample_count=int(ROUTE_TEACHER_TERMINAL["samples"]),
        )
    except RouteTeacherValidationError as exc:
        raise SystemExit(f"route-terminal pilot is invalid: {exc}") from exc
    failures = route_teacher_coverage_gate_failures(
        coverage,
        ROUTE_TEACHER_PILOT_GATE,
        source_runs=int(batch["seeds"]),
    )
    if failures:
        raise SystemExit(
            "route-terminal pilot support gate failed: " + ",".join(failures)
        )


def _verify_terminal_freeze(
    binding: dict[str, object] | None,
    *,
    repository_revision: str,
    source_digest: str,
    repository_dirty: bool,
    candidate_runtime: dict[str, object],
    backend: dict[str, object],
    repository_root: Path,
) -> None:
    if binding is None:
        return
    implementation_revision = binding.get("implementation_revision")
    expected_source_digest = binding.get("expected_source_digest")
    if (
        not isinstance(implementation_revision, str)
        or len(implementation_revision) != 40
        or not isinstance(expected_source_digest, str)
        or len(expected_source_digest) != 64
    ):
        raise SystemExit("terminal preregistration source freeze is incomplete")
    if repository_dirty or source_digest != expected_source_digest:
        raise SystemExit("terminal run does not match preregistered clean source")
    if candidate_runtime != binding.get("candidate_runtime"):
        raise SystemExit("terminal run changed preregistered candidate runtime")
    if backend != binding.get("backend"):
        raise SystemExit("terminal run changed preregistered backend")
    if repository_revision == implementation_revision:
        raise SystemExit(
            "terminal preregistration was not committed after implementation"
        )
    try:
        subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                implementation_revision,
                repository_revision,
            ],
            cwd=repository_root,
            check=True,
            capture_output=True,
        )
        changed = subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                implementation_revision,
                repository_revision,
            ],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("cannot verify terminal implementation ancestry") from exc
    if set(changed) != {"experiments/terminal-actions-v6-preregistration.json"}:
        raise SystemExit(
            "terminal preregistration commit changed implementation source"
        )


def _verify_route_terminal_freeze(
    binding: dict[str, object] | None,
    *,
    repository_revision: str,
    source_digest: str,
    repository_dirty: bool,
    candidate_runtime: dict[str, object],
    backend: dict[str, object],
    repository_root: Path,
) -> None:
    if binding is None:
        return
    implementation_revision = binding.get("implementation_revision")
    expected_source_digest = binding.get("expected_source_digest")
    if (
        not isinstance(implementation_revision, str)
        or len(implementation_revision) != 40
        or not isinstance(expected_source_digest, str)
        or len(expected_source_digest) != 64
    ):
        raise SystemExit("route-terminal preregistration source freeze is incomplete")
    if repository_dirty or source_digest != expected_source_digest:
        raise SystemExit("route-terminal run does not match preregistered clean source")
    if candidate_runtime != binding.get("candidate_runtime"):
        raise SystemExit("route-terminal run changed preregistered candidate runtime")
    if backend != binding.get("backend"):
        raise SystemExit("route-terminal run changed preregistered backend")
    if repository_revision == implementation_revision:
        raise SystemExit(
            "route-terminal preregistration was not committed after implementation"
        )
    try:
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", implementation_revision, repository_revision],
            cwd=repository_root,
            check=True,
            capture_output=True,
        )
        changed = subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                implementation_revision,
                repository_revision,
            ],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("cannot verify route-terminal implementation ancestry") from exc
    if set(changed) != {ROUTE_TEACHER_PREREGISTRATION}:
        raise SystemExit(
            "route-terminal preregistration commit changed implementation source"
        )


def _validate_contextual_preregistration(
    args: argparse.Namespace,
    tuning: StrategyTuning,
    *,
    repository_root: Path,
) -> dict[str, object] | None:
    retired = range(1075, 2275)
    reserved = range(2602, 2902)
    requested = range(args.seed_start, args.seed_start + args.seeds)
    if requested.start < retired.stop and retired.start < requested.stop:
        raise SystemExit("contextual v9-v13 seeds 1075-2274 are retired")
    overlaps_reserved = (
        requested.start < reserved.stop and reserved.start < requested.stop
    )
    path = args.contextual_preregistration_json
    if path is None:
        if overlaps_reserved:
            raise SystemExit(
                "seeds 2602-2901 require --contextual-preregistration-json"
            )
        return None
    try:
        raw = path.read_bytes()
        spec = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid contextual preregistration: {exc}") from exc
    if not isinstance(spec, dict):
        raise SystemExit("contextual preregistration root must be an object")
    if (
        spec.get("protocol_id") != "contextual-continuation-development-v6"
        or spec.get("status") != "reserved"
        or spec.get("immutable_batches") is not True
    ):
        raise SystemExit("contextual preregistration is not the reserved protocol")
    if (
        spec.get("seed_provenance") != args.seed_provenance
        or spec.get("deck") != args.deck
        or spec.get("stake") != args.stake
        or spec.get("strategy_tuning") != json.loads(tuning.canonical_json())
    ):
        raise SystemExit("contextual preregistration top-level mismatch")
    expected_search = {
        "samples": args.samples,
        "horizon_antes": args.horizon_antes,
        "max_steps": args.max_steps,
        "override_z": args.override_z,
        "max_decisions": args.max_decisions,
        "ante_cap": args.ante_cap,
        "workers": args.workers,
        "nonce": args.nonce,
        "continuation": args.continuation,
        "policy_seed": args.policy_seed,
        "strategy_options": args.strategy_options,
        "include_reorders": args.include_reorders,
        "dense_teacher": args.dense_teacher,
    }
    if (
        spec.get("search") != _CONTEXTUAL_SEARCH
        or expected_search != _CONTEXTUAL_SEARCH
        or spec.get("training") != _CONTEXTUAL_TRAINING
        or spec.get("first_100_kill_gate") != _CONTEXTUAL_FIRST_100_GATE
    ):
        raise SystemExit("contextual preregistration search budget mismatch")
    origin = spec.get("origin_mapping")
    if (
        not isinstance(origin, dict)
        or origin.get("algorithm") != "hmac-sha256-truncated-128"
        or origin.get("key_path")
        != "runs/secrets/contextual-continuation-v14-origin.key"
        or not isinstance(origin.get("key_sha256"), str)
        or len(origin["key_sha256"]) != 64
        or args.origin_key_file is None
        or args.origin_key_file.resolve()
        != (repository_root / origin["key_path"]).resolve()
    ):
        raise SystemExit("contextual preregistration origin mapping mismatch")
    try:
        origin_key = args.origin_key_file.read_bytes()
    except OSError as exc:
        raise SystemExit("contextual origin key is unreadable") from exc
    if (
        len(origin_key) != 32
        or hashlib.sha256(origin_key).hexdigest() != origin["key_sha256"]
    ):
        raise SystemExit("contextual origin key disagrees with its commitment")
    if (
        not args.dense_teacher
        or args.success_teacher
        or args.success_terminal_actions
        or args.strategy_shadow_model is not None
        or args.strategy_continuation_model is not None
        or args.teacher_jsonl is None
        or args.report_json is None
    ):
        raise SystemExit(
            "contextual preregistration requires isolated dense collection"
        )
    batches = spec.get("batches")
    if batches != list(_CONTEXTUAL_BATCHES):
        raise SystemExit("contextual preregistration changed the frozen batches")
    matches = [
        batch
        for batch in batches
        if isinstance(batch, dict)
        and batch.get("seed_start") == args.seed_start
        and batch.get("seeds") == args.seeds
    ]
    if len(matches) != 1:
        raise SystemExit("contextual preregistration has no unique requested batch")
    batch = matches[0]
    for key, actual in (
        ("teacher_jsonl", args.teacher_jsonl),
        ("report_json", args.report_json),
    ):
        declared = batch.get(key)
        if (
            not isinstance(declared, str)
            or actual.resolve() != (repository_root / declared).resolve()
        ):
            raise SystemExit(f"contextual preregistration mismatch: {key}")
    if int(batch["seed_start"]) >= int(_CONTEXTUAL_BATCHES[2]["seed_start"]):
        _validate_contextual_first_100(
            spec,
            preregistration_sha256=hashlib.sha256(raw).hexdigest(),
            origin_key=origin_key,
            repository_root=repository_root,
        )
    return {
        "protocol_id": spec["protocol_id"],
        "sha256": hashlib.sha256(raw).hexdigest(),
        "batch_id": batch.get("batch_id"),
        "seed_start": args.seed_start,
        "seeds": args.seeds,
        "immutable_batches": True,
        "implementation_revision": spec.get("implementation_revision"),
        "expected_source_digest": spec.get("expected_source_digest"),
        "candidate_runtime": spec.get("candidate_runtime"),
        "backend": spec.get("backend"),
        "training": spec.get("training"),
        "origin_key_sha256": origin["key_sha256"],
    }


def _validate_contextual_first_100(
    spec: dict[str, object],
    *,
    preregistration_sha256: str,
    origin_key: bytes,
    repository_root: Path,
) -> None:
    """Enforce the precommitted kill gate before batch three can start."""

    gate = spec.get("first_100_kill_gate")
    batches = spec.get("batches")
    if not isinstance(gate, dict) or not isinstance(batches, list) or len(batches) != 6:
        raise SystemExit("contextual first-100 gate is missing")
    all_records: list[StrategyTeacherRecord] = []
    all_rows: list[dict[str, object]] = []
    for expected in batches[:2]:
        if (
            not isinstance(expected, dict)
            or not isinstance(expected.get("report_json"), str)
            or not isinstance(expected.get("teacher_jsonl"), str)
        ):
            raise SystemExit("contextual first-100 artifact path is invalid")
        try:
            report = json.loads(
                (repository_root / expected["report_json"]).read_text(encoding="utf-8")
            )
            teacher_bytes = (repository_root / expected["teacher_jsonl"]).read_bytes()
            records = teacher_records_from_bytes(teacher_bytes)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise SystemExit("contextual first-100 artifacts are incomplete") from exc
        if not isinstance(report, dict):
            raise SystemExit("contextual first-100 report is invalid")
        binding = report.get("contextual_teacher_preregistration")
        teacher = report.get("strategy_teacher_dataset")
        rows = report.get("results")
        if (
            not isinstance(binding, dict)
            or binding.get("sha256") != preregistration_sha256
            or binding.get("batch_id") != expected.get("batch_id")
            or not isinstance(teacher, dict)
            or teacher.get("status") != "written"
            or teacher.get("sha256") != hashlib.sha256(teacher_bytes).hexdigest()
            or teacher.get("groups") != 50
            or teacher.get("records") != len(records)
            or {record.teacher_config_digest for record in records}
            != {teacher.get("teacher_config_digest")}
            or not isinstance(rows, list)
            or len(rows) != 50
            or any(
                not isinstance(row, dict)
                or row.get("complete") is not True
                or row.get("terminal_reason") not in {"game_over", "ante_cap"}
                or row.get("terminal_error") is not None
                or row.get("rejected_decisions") != 0
                or not isinstance(row.get("search"), dict)
                or row["search"].get("rejected_rollouts") != 0
                or row["search"].get("unavailable") != 0
                or row.get("search_failure_reasons") != {}
                for row in rows
            )
        ):
            raise SystemExit("contextual first-100 gate failed integrity checks")
        typed_rows = [row for row in rows if isinstance(row, dict)]
        _validate_first_100_component_records(
            records,
            typed_rows,
            expected_seed_start=int(expected["seed_start"]),
            origin_key=origin_key,
        )
        actual_coverage = _teacher_coverage(records, typed_rows)
        if teacher.get("coverage") != actual_coverage:
            raise SystemExit("contextual first-100 report coverage is unauthenticated")
        all_records.extend(records)
        all_rows.extend(typed_rows)
    dense = _teacher_coverage(tuple(all_records), all_rows)["dense_paired_utility"]
    assert isinstance(dense, dict)
    if (
        float(dense["action_sensitive_fraction"])
        < float(gate["minimum_action_sensitive_fraction"])
        or int(dense["observed_victory_origin_groups"])
        < int(gate["minimum_observed_victory_groups"])
        or gate.get("rejected_or_censored") != 0
    ):
        raise SystemExit("contextual first-100 kill gate failed")


def _validate_first_100_component_records(
    records: tuple[StrategyTeacherRecord, ...],
    rows: list[dict[str, object]],
    *,
    expected_seed_start: int,
    origin_key: bytes,
) -> None:
    expected_seeds = set(range(expected_seed_start, expected_seed_start + 50))
    if {row.get("seed") for row in rows} != expected_seeds:
        raise SystemExit("contextual first-100 seed panel is invalid")
    expected_groups = {
        "origin-"
        + hmac.new(
            origin_key, str(int(row["seed"])).encode(), hashlib.sha256
        ).hexdigest()[:32]: row
        for row in rows
    }
    by_group: dict[str, list[StrategyTeacherRecord]] = {}
    for record in records:
        by_group.setdefault(record.run_group, []).append(record)
    if set(by_group) != set(expected_groups):
        raise SystemExit("contextual first-100 origin mapping is invalid")
    for group, group_records in by_group.items():
        row = expected_groups[group]
        search = row["search"]
        assert isinstance(search, dict)
        ordered = sorted(group_records, key=lambda record: record.decision_index)
        if (
            [record.decision_index for record in ordered] != list(range(len(ordered)))
            or not isinstance(search.get("searched"), int)
            or isinstance(search.get("searched"), bool)
            or len(ordered) != int(search["searched"])
            or not isinstance(row.get("won"), bool)
            or not isinstance(row.get("antes_cleared"), int)
            or isinstance(row.get("antes_cleared"), bool)
            or not isinstance(row.get("best_hand_score"), int)
            or isinstance(row.get("best_hand_score"), bool)
        ):
            raise SystemExit("contextual first-100 decision sequence is incomplete")
        expected_log_score = math.log10(max(1, int(row["best_hand_score"])))
        for record in ordered:
            legal_roots = tuple(
                action
                for action in iter_legal_actions(record.observation)
                if not isinstance(action, _CONTEXTUAL_REORDERS)
            )
            if (
                record.run_won is not row["won"]
                or record.terminal_ante != row["antes_cleared"]
                or not math.isclose(
                    record.run_log_score,
                    expected_log_score,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                or tuple(candidate.action for candidate in record.candidates)
                != legal_roots
                or record.candidate_space_size != len(legal_roots)
                or any(candidate.intent is not None for candidate in record.candidates)
                or any(len(candidate.samples) != 6 for candidate in record.candidates)
                or any(
                    sample.endpoint == StrategyTargetEndpoint.CENSORED
                    for candidate in record.candidates
                    for sample in candidate.samples
                )
                or record.selected_index != _contextual_selected_index(record)
            ):
                raise SystemExit("contextual first-100 teacher record is invalid")


def _contextual_selected_index(record: StrategyTeacherRecord) -> int:
    return select_paired_root(
        tuple(
            tuple(sample.search_utility for sample in candidate.samples)
            for candidate in record.candidates
        ),
        record.baseline_index,
        float(_CONTEXTUAL_SEARCH["override_z"]),
    )


def _verify_contextual_freeze(
    binding: dict[str, object] | None,
    *,
    repository_revision: str,
    source_digest: str,
    repository_dirty: bool,
    candidate_runtime: dict[str, object],
    backend: dict[str, object],
    repository_root: Path,
) -> None:
    if binding is None:
        return
    implementation_revision = binding.get("implementation_revision")
    expected_source_digest = binding.get("expected_source_digest")
    if (
        not isinstance(implementation_revision, str)
        or len(implementation_revision) != 40
        or not isinstance(expected_source_digest, str)
        or len(expected_source_digest) != 64
    ):
        raise SystemExit("contextual preregistration source freeze is incomplete")
    if repository_dirty or source_digest != expected_source_digest:
        raise SystemExit("contextual run does not match preregistered clean source")
    if candidate_runtime != binding.get("candidate_runtime"):
        raise SystemExit("contextual run changed preregistered candidate runtime")
    if backend != binding.get("backend"):
        raise SystemExit("contextual run changed preregistered backend")
    if repository_revision == implementation_revision:
        raise SystemExit(
            "contextual preregistration was not committed after implementation"
        )
    try:
        subprocess.run(
            [
                "git",
                "merge-base",
                "--is-ancestor",
                implementation_revision,
                repository_revision,
            ],
            cwd=repository_root,
            check=True,
            capture_output=True,
        )
        changed = subprocess.run(
            [
                "git",
                "diff",
                "--name-only",
                implementation_revision,
                repository_revision,
            ],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("cannot verify contextual implementation ancestry") from exc
    if set(changed) != {"experiments/contextual-continuation-v14-preregistration.json"}:
        raise SystemExit(
            "contextual preregistration commit changed implementation source"
        )


def main() -> None:
    args = build_parser().parse_args()
    teacher_mode = _teacher_dataset_mode(args)
    try:
        panel_validation = validate_seed_panel(
            args.seed_start, args.seeds, args.seed_provenance
        )
    except PanelValidationError as exc:
        raise SystemExit(f"invalid seed panel: {exc}") from exc
    if (
        min(
            args.max_decisions,
            args.ante_cap,
            args.workers,
            args.success_teacher_samples,
            args.success_teacher_start_ante,
            args.success_teacher_endless_antes,
            args.success_teacher_max_steps,
            args.success_terminal_max_samples,
            args.success_terminal_max_roots,
        )
        < 1
    ):
        raise SystemExit("decision, worker, and teacher budgets must be positive")
    if args.include_reorders and not (
        args.strategy_options or args.success_teacher or args.success_terminal_actions
    ):
        raise SystemExit("--include-reorders requires a strategy root consumer")
    if args.success_teacher and args.success_terminal_actions:
        raise SystemExit(
            "--success-teacher and --success-terminal-actions are mutually exclusive"
        )
    if args.teacher_jsonl is not None and not (
        args.dense_teacher
        or args.strategy_options
        or args.success_teacher
        or args.success_terminal_actions
    ):
        raise SystemExit("--teacher-jsonl requires a teacher collection mode")
    if args.dense_teacher and (
        args.strategy_options or args.success_teacher or args.success_terminal_actions
    ):
        raise SystemExit("--dense-teacher is an exclusive ordinary-root collector")
    if args.dense_teacher and args.teacher_jsonl is None:
        raise SystemExit("--dense-teacher requires --teacher-jsonl")
    if args.success_teacher and args.teacher_jsonl is None:
        raise SystemExit("--success-teacher requires --teacher-jsonl")
    if args.success_terminal_actions:
        if args.teacher_jsonl is not None:
            raise SystemExit("terminal action mode cannot emit teacher JSONL")
        if args.strategy_shadow_model is not None:
            raise SystemExit("terminal action mode cannot load a shadow model")
        if args.strategy_continuation_model is not None:
            raise SystemExit("terminal action mode cannot load a continuation model")
        if args.seed_provenance != "development":
            raise SystemExit("terminal action mode is development-only")
        if not 0.0 < args.success_terminal_family_alpha < 1.0:
            raise SystemExit("terminal action family alpha must be in (0, 1)")
        if args.success_teacher_samples > args.success_terminal_max_samples:
            raise SystemExit("initial terminal samples exceed the action sample cap")
    if args.teacher_jsonl is not None and args.report_json is None:
        raise SystemExit("--teacher-jsonl requires --report-json for provenance")
    if args.teacher_jsonl is not None and args.strategy_shadow_model is not None:
        raise SystemExit("teacher collection cannot be combined with model shadowing")
    continuation_paths = (
        args.strategy_continuation_model,
        args.strategy_continuation_certificate,
        args.strategy_continuation_training_report,
    )
    if len({path is None for path in continuation_paths}) != 1:
        raise SystemExit(
            "continuation model, certificate, and training report must be supplied together"
        )
    if continuation_paths[0] is not None:
        if args.seed_provenance != "development":
            raise SystemExit("learned rollout continuation is development-only")
        if (
            args.teacher_jsonl is not None
            or args.strategy_shadow_model is not None
            or args.strategy_options
            or args.success_teacher
            or args.success_terminal_actions
        ):
            raise SystemExit(
                "continuation evaluation requires ordinary search without teachers"
            )
    if (
        args.teacher_jsonl is not None
        and args.report_json is not None
        and args.teacher_jsonl.resolve() == args.report_json.resolve()
    ):
        raise SystemExit("teacher and evaluation reports need distinct output paths")
    for output_path in (args.report_json, args.teacher_jsonl):
        if output_path is not None and output_path.exists():
            raise SystemExit(f"refusing to overwrite existing output: {output_path}")
    if args.trace_dir is not None:
        if args.trace_dir.exists() and not args.trace_dir.is_dir():
            raise SystemExit(f"candidate trace path is not a directory: {args.trace_dir}")
        for index in range(args.seeds):
            target = args.trace_dir / f"run-{index:04d}.jsonl"
            if target.exists():
                raise SystemExit(f"refusing to overwrite existing output: {target}")
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
    try:
        continuation_digest = (
            hashlib.sha256(args.strategy_continuation_model.read_bytes()).hexdigest()
            if args.strategy_continuation_model is not None
            else None
        )
        certificate_digest = (
            hashlib.sha256(
                args.strategy_continuation_certificate.read_bytes()
            ).hexdigest()
            if args.strategy_continuation_certificate is not None
            else None
        )
        continuation_training_report_digest = (
            hashlib.sha256(
                args.strategy_continuation_training_report.read_bytes()
            ).hexdigest()
            if args.strategy_continuation_training_report is not None
            else None
        )
    except OSError as exc:
        raise SystemExit(f"invalid rollout continuation artifact: {exc}") from exc
    root = Path(__file__).resolve().parents[1]
    try:
        tuning = StrategyTuning.from_json(args.tuning_json)
    except ValueError as exc:
        raise SystemExit(f"invalid --tuning-json: {exc}") from exc
    if args.strategy_continuation_model is not None:
        fallback, _ = build_public_baseline(
            args.continuation, args.policy_seed, tuning
        )
        try:
            CertifiedUtilityContinuationPolicy.from_artifacts(
                control=fallback,
                model_path=args.strategy_continuation_model,
                certificate_path=args.strategy_continuation_certificate,
                training_report_path=args.strategy_continuation_training_report,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise SystemExit(f"invalid rollout continuation artifact: {exc}") from exc
    terminal_preregistration = _validate_terminal_preregistration(
        args, tuning, repository_root=root
    )
    contextual_preregistration = _validate_contextual_preregistration(
        args, tuning, repository_root=root
    )
    route_terminal_preregistration = _validate_route_terminal_preregistration(
        args, tuning, repository_root=root
    )
    if contextual_preregistration is not None and route_terminal_preregistration is not None:
        raise SystemExit("teacher collection preregistrations are mutually exclusive")
    origin_key = (
        args.origin_key_file.read_bytes()
        if contextual_preregistration is not None
        or route_terminal_preregistration is not None
        else None
    )
    _, continuation_name = build_public_baseline(
        args.continuation, args.policy_seed, tuning
    )
    budget = RolloutBudget(
        samples=args.samples,
        horizon_antes=args.horizon_antes,
        max_steps=args.max_steps,
        override_z=args.override_z,
    )
    success_budget = (
        SuccessTeacherBudget(
            samples=args.success_teacher_samples,
            prewin_start_ante=args.success_teacher_start_ante,
            endless_horizon_antes=args.success_teacher_endless_antes,
            max_steps=args.success_teacher_max_steps,
        )
        if args.success_teacher or args.success_terminal_actions
        else None
    )
    success_teacher_mode = (
        success_budget.canonical() if success_budget is not None else "disabled"
    )
    success_action_mode = (
        SuccessTerminalActionBudget(
            max_samples=args.success_terminal_max_samples,
            max_roots=args.success_terminal_max_roots,
            family_alpha=args.success_terminal_family_alpha,
        ).canonical()
        if args.success_terminal_actions
        else "disabled"
    )
    strategy_mode = (
        f"strategy_options={args.strategy_options};"
        f"dense_teacher={args.dense_teacher};"
        f"include_reorders={args.include_reorders};"
        f"success_teacher={success_teacher_mode};"
        f"success_terminal_actions={success_action_mode}"
    )
    shadow_mode = f"strategy_shadow={shadow_digest or 'disabled'}"
    continuation_mode = (
        f"strategy_continuation={continuation_digest or 'disabled'};"
        f"certificate={certificate_digest or 'disabled'}"
    )
    policy_name = (
        f"DeterminizedSearchPolicy[{SEARCH_VERSION};{continuation_name};"
        f"{budget.canonical()};{strategy_mode};{shadow_mode};"
        f"{continuation_mode}]:parent-v1"
    )
    inference_budget = (
        f"policy_action_contract={POLICY_ACTION_CONTRACT};"
        f"determinized_rollouts;{budget.canonical()};{strategy_mode};{shadow_mode};"
        f"workers={args.workers};ante_cap={args.ante_cap}"
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
        "dense_teacher": args.dense_teacher,
        "include_reorders": args.include_reorders,
        "strategy_shadow_model": (
            str(args.strategy_shadow_model.resolve())
            if args.strategy_shadow_model
            else ""
        ),
        "strategy_continuation_model": (
            str(args.strategy_continuation_model.resolve())
            if args.strategy_continuation_model
            else ""
        ),
        "strategy_continuation_certificate": (
            str(args.strategy_continuation_certificate.resolve())
            if args.strategy_continuation_certificate
            else ""
        ),
        "strategy_continuation_training_report": (
            str(args.strategy_continuation_training_report.resolve())
            if args.strategy_continuation_training_report
            else ""
        ),
        "record_shadow_decisions": args.record_shadow_decisions,
        "collect_teacher": args.teacher_jsonl is not None,
        "success_teacher": args.success_teacher,
        "success_terminal_actions": args.success_terminal_actions,
        "success_teacher_samples": args.success_teacher_samples,
        "success_teacher_start_ante": args.success_teacher_start_ante,
        "success_teacher_endless_antes": args.success_teacher_endless_antes,
        "success_teacher_max_steps": args.success_teacher_max_steps,
        "success_terminal_max_samples": args.success_terminal_max_samples,
        "success_terminal_max_roots": args.success_terminal_max_roots,
        "success_terminal_family_alpha": args.success_terminal_family_alpha,
        "profile_search_timing": args.profile_search_timing,
        "seed_start": args.seed_start,
        "trace_dir": str(args.trace_dir.resolve()) if args.trace_dir else "",
        "repository_root": str(root),
        "policy_name": policy_name,
        "inference_budget": inference_budget,
        "model_digest": shadow_digest,
    }
    seeds = list(range(args.seed_start, args.seed_start + args.seeds))
    if args.trace_dir is not None:
        args.trace_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    try:
        candidate_runtime = verify_jackdaw_runtime()
        metadata_backend = JackdawBackend()
        preflight_manifest = build_manifest(
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
            inference_budget=inference_budget,
        )
        _verify_terminal_freeze(
            terminal_preregistration,
            repository_revision=preflight_manifest.repository_revision,
            source_digest=preflight_manifest.source_digest,
            repository_dirty=preflight_manifest.repository_dirty,
            candidate_runtime=candidate_runtime,
            backend=asdict(metadata_backend.metadata),
            repository_root=root,
        )
        _verify_contextual_freeze(
            contextual_preregistration,
            repository_revision=preflight_manifest.repository_revision,
            source_digest=preflight_manifest.source_digest,
            repository_dirty=preflight_manifest.repository_dirty,
            candidate_runtime=candidate_runtime,
            backend=asdict(metadata_backend.metadata),
            repository_root=root,
        )
        _verify_route_terminal_freeze(
            route_terminal_preregistration,
            repository_revision=preflight_manifest.repository_revision,
            source_digest=preflight_manifest.source_digest,
            repository_dirty=preflight_manifest.repository_dirty,
            candidate_runtime=candidate_runtime,
            backend=asdict(metadata_backend.metadata),
            repository_root=root,
        )
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
            origin_key=origin_key,
            mode=teacher_mode,
        )
        teacher_digest = (
            teacher_records_digest(teacher_records) if teacher_records else None
        )
        teacher_coverage = _teacher_coverage(teacher_records, results)
        elapsed = time.perf_counter() - started
        terminal_reasons = Counter(str(row["terminal_reason"]) for row in results)
        summary = summarize_results(
            results, elapsed=elapsed, terminal_reasons=terminal_reasons
        )
        summary["search"] = _search_summary(results)
        if args.profile_search_timing:
            summary["search_timing"] = _search_timing_summary(results)
        summary["success_teacher_profile"] = _success_teacher_profile(
            results,
            mode=(
                "actions"
                if args.success_terminal_actions
                else "collect"
                if args.success_teacher
                else "disabled"
            ),
        )
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
            inference_budget=inference_budget,
        )
        _verify_terminal_freeze(
            terminal_preregistration,
            repository_revision=manifest.repository_revision,
            source_digest=manifest.source_digest,
            repository_dirty=manifest.repository_dirty,
            candidate_runtime=candidate_runtime,
            backend=asdict(metadata_backend.metadata),
            repository_root=root,
        )
        _verify_contextual_freeze(
            contextual_preregistration,
            repository_revision=manifest.repository_revision,
            source_digest=manifest.source_digest,
            repository_dirty=manifest.repository_dirty,
            candidate_runtime=candidate_runtime,
            backend=asdict(metadata_backend.metadata),
            repository_root=root,
        )
        _verify_route_terminal_freeze(
            route_terminal_preregistration,
            repository_revision=manifest.repository_revision,
            source_digest=manifest.source_digest,
            repository_dirty=manifest.repository_dirty,
            candidate_runtime=candidate_runtime,
            backend=asdict(metadata_backend.metadata),
            repository_root=root,
        )
        success_protocol = {
            "enabled": args.success_teacher or args.success_terminal_actions,
            "mode": (
                "actions"
                if args.success_terminal_actions
                else "collect"
                if args.success_teacher
                else "disabled"
            ),
            "affects_actions": args.success_terminal_actions,
            "emits_teacher_rows": args.success_teacher,
            "samples": args.success_teacher_samples,
            "prewin_start_ante": args.success_teacher_start_ante,
            "endless_horizon_antes": args.success_teacher_endless_antes,
            "max_steps": args.success_teacher_max_steps,
            "anchor_schedule": (
                "first_shop_each_ante;first_pack_each_ante_from_ante4;"
                "boss_select_ante5_plus;postwin_first_shop_and_pack_each_ante"
            ),
            "endpoint_semantics": (
                "victory_or_death_exact;endless_fixed_horizon;"
                "censored_never_exact;no_public_progress_inadmissible_for_actions"
            ),
            "terminal_action_budget": (
                json.loads(
                    json.dumps(
                        asdict(
                            SuccessTerminalActionBudget(
                                max_samples=args.success_terminal_max_samples,
                                max_roots=args.success_terminal_max_roots,
                                family_alpha=args.success_terminal_family_alpha,
                            )
                        )
                    )
                )
                if args.success_terminal_actions
                else None
            ),
            "terminal_action_selector": (
                "root_adjusted_one_sided_sign;zero_adverse_discordances;"
                "victory=exact_win;endless=alive,ante,log_score;"
                "ties_inert;root_overflow=fail_closed_without_truncation;"
                "fallback=exact_behavior_identity"
                if args.success_terminal_actions
                else None
            ),
            "sample_nonce_stream": f"{args.nonce}:success-terminal-v1",
            "root_builder": SEARCH_VERSION,
            "counter_semantics": (
                "attempted=all_scheduled_anchors;completed=no_fallback;"
                "fallback=action_mode_exact_behavior_fallback;"
                "unavailable=subset_of_fallback_without_valid_evaluation"
            ),
        }
        success_protocol["protocol_digest"] = hashlib.sha256(
            json.dumps(
                success_protocol,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        payload = {
            "candidate_only": True,
            "candidate_runtime": candidate_runtime,
            "manifest": asdict(manifest),
            "search_protocol": {
                "version": SEARCH_VERSION,
                "continuation": continuation_name,
                "policy_seed": args.policy_seed,
                "budget": json.loads(json.dumps(asdict(budget))),
                "nonce": args.nonce,
                "phases": ["BLIND_SELECT", "PACK", "SHOP"],
                "value": "rounds_cleared_plus_failed_blind_fraction;alive_at_horizon=+1",
                "selection": (
                    "ordinary_all_legal_nonreorder_scalar_then_nonvictory_"
                    "specialist_overlay;"
                    "paired_delta_vs_ordinary_winner;"
                    "override_when_mean_minus_z_se_positive;"
                    "victory_is_unconditioned;specialist_root_cap="
                    f"{STRATEGY_SPECIALIST_MAX_ROOTS}"
                    if args.strategy_options
                    else "paired_delta_vs_continuation;override_when_mean_minus_z_se_positive"
                ),
                "strategy_options": args.strategy_options,
                "include_reorders": args.include_reorders,
                "objective": (
                    "scalar_progress_online;goal_utility_teacher_and_diagnostics_only"
                    if args.strategy_options
                    else "legacy_scalar_progress"
                ),
                "success_teacher": success_protocol,
            },
            "strategy_tuning": json.loads(tuning.canonical_json()),
            "terminal_action_preregistration": terminal_preregistration,
            "contextual_teacher_preregistration": contextual_preregistration,
            "route_terminal_teacher_preregistration": (
                route_terminal_preregistration
            ),
            "strategy_model_shadow": {
                "enabled": shadow_digest is not None,
                "artifact_digest": shadow_digest,
                "affects_actions": False,
                "record_decisions": args.record_shadow_decisions,
                **shadow_artifact_status,
            },
            "strategy_model_continuation": {
                "enabled": continuation_digest is not None,
                "artifact_digest": continuation_digest,
                "certificate_digest": certificate_digest,
                "training_report_digest": continuation_training_report_digest,
                "affects_actions": continuation_digest is not None,
                "scope": "rollout_only",
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
                "mode": teacher_mode,
                "schema_version": STRATEGY_TEACHER_SCHEMA_VERSION,
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
        if args.profile_search_timing:
            search_protocol_payload = payload["search_protocol"]
            assert isinstance(search_protocol_payload, dict)
            search_protocol_payload["timing_profile"] = {
                "schema_version": 1,
                "clock": "perf_counter_ns",
                "behavioral_influence": False,
                "gc_forced": False,
                "allocation_metric": "net_allocated_blocks",
            }
        encoded = json.dumps(payload, sort_keys=True)
        print(json.dumps({"summary": summary}, sort_keys=True))
        publication_manifest = build_manifest(
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
                f"policy_action_contract={POLICY_ACTION_CONTRACT};"
                f"determinized_rollouts;{budget.canonical()};{strategy_mode};{shadow_mode};"
                f"workers={args.workers};ante_cap={args.ante_cap}"
            ),
        )
        if (
            publication_manifest.repository_revision != manifest.repository_revision
            or publication_manifest.repository_dirty != manifest.repository_dirty
            or publication_manifest.source_digest != manifest.source_digest
        ):
            raise SystemExit("repository source changed before atomic publication")
        publication_runtime = verify_jackdaw_runtime()
        _verify_terminal_freeze(
            terminal_preregistration,
            repository_revision=publication_manifest.repository_revision,
            source_digest=publication_manifest.source_digest,
            repository_dirty=publication_manifest.repository_dirty,
            candidate_runtime=publication_runtime,
            backend=asdict(metadata_backend.metadata),
            repository_root=root,
        )
        _verify_contextual_freeze(
            contextual_preregistration,
            repository_revision=publication_manifest.repository_revision,
            source_digest=publication_manifest.source_digest,
            repository_dirty=publication_manifest.repository_dirty,
            candidate_runtime=publication_runtime,
            backend=asdict(metadata_backend.metadata),
            repository_root=root,
        )
        _verify_route_terminal_freeze(
            route_terminal_preregistration,
            repository_revision=publication_manifest.repository_revision,
            source_digest=publication_manifest.source_digest,
            repository_dirty=publication_manifest.repository_dirty,
            candidate_runtime=publication_runtime,
            backend=asdict(metadata_backend.metadata),
            repository_root=root,
        )
        if route_terminal_preregistration is not None:
            if args.teacher_jsonl is None or args.report_json is None:
                raise RuntimeError("route-terminal artifact paths disappeared")
            _publish_route_terminal_bundle(
                args.teacher_jsonl,
                args.report_json,
                teacher_records,
                expected_teacher_digest=teacher_digest,
                encoded_report=encoded + "\n",
                expected_manifest=manifest,
                expected_runtime=route_terminal_preregistration["candidate_runtime"],
                repository_root=root,
            )
        elif contextual_preregistration is not None:
            if args.teacher_jsonl is None or args.report_json is None:
                raise RuntimeError("contextual artifact paths disappeared")
            _publish_contextual_bundle(
                args.teacher_jsonl,
                args.report_json,
                teacher_records,
                expected_teacher_digest=teacher_digest,
                encoded_report=encoded + "\n",
                expected_manifest=manifest,
                expected_runtime=contextual_preregistration["candidate_runtime"],
                repository_root=root,
            )
        else:
            teacher_published = False
            try:
                if args.teacher_jsonl is not None and teacher_records:
                    actual_digest = write_teacher_records(
                        args.teacher_jsonl, teacher_records
                    )
                    teacher_published = True
                    if actual_digest != teacher_digest:
                        raise RuntimeError(
                            "published teacher digest changed after preflight"
                        )
                if args.report_json is not None:
                    args.report_json.parent.mkdir(parents=True, exist_ok=True)
                    _publish_json_exclusive(args.report_json, encoded + "\n")
            except BaseException:
                if teacher_published and args.teacher_jsonl is not None:
                    args.teacher_jsonl.unlink(missing_ok=True)
                raise
        if sum(bool(row["complete"]) for row in results) != len(results):
            raise SystemExit(2)
    except JackdawUnavailable as exc:
        raise SystemExit(f"Jackdaw candidate unavailable: {exc}") from exc


def _publish_json_exclusive(path: Path, encoded: str) -> None:
    """Atomically publish a complete report without replacing any prior evidence."""

    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except FileExistsError as exc:
        raise SystemExit(f"refusing to overwrite existing output: {path}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _publish_contextual_bundle(
    teacher_path: Path,
    report_path: Path,
    records: tuple[StrategyTeacherRecord, ...],
    *,
    expected_teacher_digest: str | None,
    encoded_report: str,
    expected_manifest: object,
    expected_runtime: object,
    repository_root: Path,
) -> None:
    """Publish a contextual batch with one crash-atomic directory rename."""

    _publish_teacher_bundle(
        teacher_path,
        report_path,
        records,
        expected_teacher_digest=expected_teacher_digest,
        encoded_report=encoded_report,
        expected_manifest=expected_manifest,
        expected_runtime=expected_runtime,
        repository_root=repository_root,
        protocol_label="contextual",
    )


def _publish_teacher_bundle(
    teacher_path: Path,
    report_path: Path,
    records: tuple[StrategyTeacherRecord, ...],
    *,
    expected_teacher_digest: str | None,
    encoded_report: str,
    expected_manifest: object,
    expected_runtime: object,
    repository_root: Path,
    protocol_label: str,
) -> None:
    """Publish one teacher/report pair through a crash-atomic directory rename."""

    final_directory = teacher_path.parent.resolve()
    if report_path.parent.resolve() != final_directory:
        raise SystemExit(f"{protocol_label} outputs must share one batch directory")
    if final_directory.exists():
        raise SystemExit(f"refusing to overwrite existing batch: {final_directory}")
    final_directory.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(
        tempfile.mkdtemp(
            prefix=f".{final_directory.name}.",
            suffix=".tmp",
            dir=final_directory.parent,
        )
    )
    staged_teacher = staged / teacher_path.name
    staged_report = staged / report_path.name
    try:
        if records:
            actual_digest = write_teacher_records(staged_teacher, records)
            if actual_digest != expected_teacher_digest:
                raise RuntimeError("published teacher digest changed after preflight")
        elif expected_teacher_digest is not None:
            raise RuntimeError("empty teacher records have a nonempty digest")
        _publish_json_exclusive(staged_report, encoded_report)
        revision, dirty, source_digest = source_snapshot(repository_root)
        if (
            dirty
            or revision != getattr(expected_manifest, "repository_revision", None)
            or source_digest != getattr(expected_manifest, "source_digest", None)
            or verify_jackdaw_runtime() != expected_runtime
        ):
            raise SystemExit(
                f"{protocol_label} source changed before bundle publication"
            )
        os.rename(staged, final_directory)
    except BaseException:
        staged_teacher.unlink(missing_ok=True)
        staged_report.unlink(missing_ok=True)
        try:
            staged.rmdir()
        except OSError:
            pass
        raise


def _publish_route_terminal_bundle(
    teacher_path: Path,
    report_path: Path,
    records: tuple[StrategyTeacherRecord, ...],
    *,
    expected_teacher_digest: str | None,
    encoded_report: str,
    expected_manifest: object,
    expected_runtime: object,
    repository_root: Path,
) -> None:
    """Publish a preregistered route batch with the same atomic boundary."""

    _publish_teacher_bundle(
        teacher_path,
        report_path,
        records,
        expected_teacher_digest=expected_teacher_digest,
        encoded_report=encoded_report,
        expected_manifest=expected_manifest,
        expected_runtime=expected_runtime,
        repository_root=repository_root,
        protocol_label="route-terminal",
    )


def _distribution(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p50": 0.0, "p90": 0.0, "p99": 0.0, "max": 0.0}
    ordered = sorted(values)

    def percentile(fraction: float) -> float:
        return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]

    return {
        "p50": percentile(0.50),
        "p90": percentile(0.90),
        "p99": percentile(0.99),
        "max": ordered[-1],
    }


def _search_decision_profile(decisions: list[SearchDecision]) -> dict[str, object]:
    if not decisions:
        return {
            "decisions": 0,
            "specialist_overrides": 0,
            "specialist_unavailable": 0,
            "seconds": _distribution([]),
            "roots": _distribution([]),
            "ordinary_roots": _distribution([]),
            "specialist_roots": _distribution([]),
            "specialist_roots_generated": _distribution([]),
            "steps": _distribution([]),
            "slowest": None,
        }
    slowest = max(decisions, key=lambda decision: decision.seconds)
    return {
        "decisions": len(decisions),
        "specialist_overrides": sum(
            decision.specialist_override for decision in decisions
        ),
        "specialist_unavailable": sum(
            decision.specialist_unavailable_reason is not None
            for decision in decisions
        ),
        "seconds": _distribution([decision.seconds for decision in decisions]),
        "roots": _distribution([float(decision.roots) for decision in decisions]),
        "ordinary_roots": _distribution(
            [float(decision.ordinary_roots) for decision in decisions]
        ),
        "specialist_roots": _distribution(
            [float(decision.specialist_roots) for decision in decisions]
        ),
        "specialist_roots_generated": _distribution(
            [float(decision.specialist_roots_generated) for decision in decisions]
        ),
        "steps": _distribution([float(decision.steps) for decision in decisions]),
        "slowest": {
            "phase": slowest.phase,
            "ante": slowest.ante,
            "roots": slowest.roots,
            "steps": slowest.steps,
            "seconds": slowest.seconds,
        },
    }


def _search_failure_reasons(decisions: list[SearchDecision]) -> dict[str, int]:
    reasons: Counter[str] = Counter()
    for decision in decisions:
        if decision.unavailable_reason is not None:
            reasons[f"unavailable|{decision.unavailable_reason}"] += 1
        if decision.specialist_unavailable_reason is not None:
            reasons[
                f"specialist_unavailable|{decision.specialist_unavailable_reason}"
            ] += 1
        reasons.update(dict(decision.rejection_reasons))
    return dict(sorted(reasons.items()))


def _success_teacher_profile(
    results: list[dict[str, object]], *, mode: str
) -> dict[str, object]:
    records: list[tuple[int, int, dict[str, object]]] = []
    for row in results:
        raw_decisions = row.get("success_teacher_decisions", [])
        if isinstance(raw_decisions, list):
            records.extend(
                (int(row["seed"]), index, decision)
                for index, decision in enumerate(raw_decisions)
                if isinstance(decision, dict)
            )
    decisions = [record[2] for record in records]
    endpoints: Counter[str] = Counter()
    routes: Counter[str] = Counter()
    fallback_reasons: Counter[str] = Counter()
    for decision in decisions:
        raw_endpoints = decision.get("endpoint_counts")
        if isinstance(raw_endpoints, dict):
            endpoints.update(
                {
                    str(key): int(value)
                    for key, value in raw_endpoints.items()
                    if isinstance(value, int | float)
                }
            )
        raw_routes = decision.get("route_counts")
        if isinstance(raw_routes, dict):
            routes.update(
                {
                    str(key): int(value)
                    for key, value in raw_routes.items()
                    if isinstance(value, int | float)
                }
            )
        reason = decision.get("fallback_reason")
        if isinstance(reason, str):
            fallback_reasons[reason] += 1
    slowest = (
        max(records, key=lambda record: float(record[2].get("seconds", 0.0)))
        if records
        else None
    )
    total_steps = sum(int(decision.get("steps", 0)) for decision in decisions)
    total_seconds = sum(float(decision.get("seconds", 0.0)) for decision in decisions)
    counter_steps = sum(
        int(search.get("success_teacher_steps", 0))
        for row in results
        if isinstance((search := row.get("search")), dict)
    )
    counter_seconds = sum(
        float(search.get("success_teacher_seconds", 0.0))
        for row in results
        if isinstance((search := row.get("search")), dict)
    )
    return {
        "mode": mode,
        "decisions": len(decisions),
        "roots": _distribution(
            [float(decision.get("roots", 0)) for decision in decisions]
        ),
        "steps": _distribution(
            [float(decision.get("steps", 0)) for decision in decisions]
        ),
        "seconds": _distribution(
            [float(decision.get("seconds", 0.0)) for decision in decisions]
        ),
        "sample_evaluations": _distribution(
            [float(decision.get("sample_evaluations", 0)) for decision in decisions]
        ),
        "max_root_cumulative_steps": _distribution(
            [
                float(decision.get("max_root_cumulative_steps", 0))
                for decision in decisions
            ]
        ),
        "steps_per_second": _distribution(
            [
                float(decision.get("steps", 0)) / seconds
                for decision in decisions
                if (seconds := float(decision.get("seconds", 0.0))) > 0.0
            ]
        ),
        "endpoint_counts": dict(endpoints),
        "route_counts": dict(sorted(routes.items())),
        "fallback_reasons": dict(fallback_reasons),
        "slowest": (
            {
                "seed": slowest[0],
                "decision_index": slowest[1],
                "phase": slowest[2].get("phase"),
                "ante": slowest[2].get("ante"),
                "roots": slowest[2].get("roots"),
                "sample_evaluations": slowest[2].get("sample_evaluations"),
                "steps": slowest[2].get("steps"),
                "seconds": slowest[2].get("seconds"),
                "fallback_reason": slowest[2].get("fallback_reason"),
            }
            if slowest is not None
            else None
        ),
        "counter_reconciliation": {
            "decision_steps": total_steps,
            "counter_steps": counter_steps,
            "steps_match": total_steps == counter_steps,
            "decision_seconds": total_seconds,
            "counter_seconds": counter_seconds,
            "seconds_match": math.isclose(
                total_seconds, counter_seconds, rel_tol=1e-12, abs_tol=1e-9
            ),
        },
    }


def _search_timing_summary(results: list[dict[str, object]]) -> dict[str, object]:
    buckets: dict[str, dict[str, int | float]] = {}
    allocation = {
        "terminal_anchors": 0,
        "net_blocks": 0,
        "max_positive_anchor_net_blocks": 0,
    }
    gc_collections: Counter[str] = Counter()
    gc_seconds = 0.0
    gc_max_seconds = 0.0
    profiled_runs = 0
    for row in results:
        timing = row.get("search_timing")
        if not isinstance(timing, dict):
            continue
        profiled_runs += 1
        raw_buckets = timing.get("buckets")
        if isinstance(raw_buckets, dict):
            for name, raw_bucket in raw_buckets.items():
                if not isinstance(name, str) or not isinstance(raw_bucket, dict):
                    continue
                bucket = buckets.setdefault(
                    name,
                    {"count": 0, "seconds": 0.0, "max_seconds": 0.0},
                )
                bucket["count"] = int(bucket["count"]) + int(
                    raw_bucket.get("count", 0)
                )
                bucket["seconds"] = float(bucket["seconds"]) + float(
                    raw_bucket.get("seconds", 0.0)
                )
                bucket["max_seconds"] = max(
                    float(bucket["max_seconds"]),
                    float(raw_bucket.get("max_seconds", 0.0)),
                )
        raw_allocation = timing.get("allocation")
        if isinstance(raw_allocation, dict):
            allocation["terminal_anchors"] += int(
                raw_allocation.get("terminal_anchors", 0)
            )
            allocation["net_blocks"] += int(raw_allocation.get("net_blocks", 0))
            allocation["max_positive_anchor_net_blocks"] = max(
                allocation["max_positive_anchor_net_blocks"],
                int(raw_allocation.get("max_positive_anchor_net_blocks", 0)),
            )
        raw_gc = timing.get("gc")
        if isinstance(raw_gc, dict):
            raw_collections = raw_gc.get("collections_by_generation")
            if isinstance(raw_collections, dict):
                gc_collections.update(
                    {
                        str(generation): int(count)
                        for generation, count in raw_collections.items()
                    }
                )
            gc_seconds += float(raw_gc.get("seconds", 0.0))
            gc_max_seconds = max(
                gc_max_seconds,
                float(raw_gc.get("max_seconds", 0.0)),
            )
    return {
        "schema_version": 1,
        "clock": "perf_counter_ns",
        "profiled_runs": profiled_runs,
        "buckets": dict(sorted(buckets.items())),
        "allocation": {"metric": "net_allocated_blocks", **allocation},
        "gc": {
            "collections_by_generation": dict(sorted(gc_collections.items())),
            "seconds": gc_seconds,
            "max_seconds": gc_max_seconds,
        },
    }


def _search_summary(results: list[dict[str, object]]) -> dict[str, object]:
    totals: Counter[str] = Counter()
    route_selections: Counter[str] = Counter()
    route_transitions: Counter[str] = Counter()
    for row in results:
        search = row["search"]
        assert isinstance(search, dict)
        for key in (
            "strategic_decisions",
            "searched",
            "changed",
            "strategy_identity_changes",
            "strategy_specialist_challenges",
            "strategy_specialist_roots_generated",
            "strategy_specialist_overrides",
            "strategy_specialist_unavailable",
            "strategy_route_abandonments",
            "strategy_victory_escapes",
            "unavailable",
            "rollout_steps",
            "rejected_rollouts",
            "seconds",
            "run_seconds",
            "success_teacher_steps",
            "success_teacher_rejected_rollouts",
            "success_teacher_seconds",
            "success_anchors_attempted",
            "success_anchors_completed",
            "success_anchor_fallbacks",
            "success_anchor_unavailable",
            "success_anchor_unsupported",
            "success_teacher_censored_rollouts",
            "success_action_overrides",
            "success_intent_only_overrides",
            "success_route_only_overrides",
        ):
            totals[key] += float(search[key])
        for name, count in dict(search["strategy_route_selections"]).items():
            route_selections[str(name)] += int(count)
        for name, count in dict(search["strategy_route_transitions"]).items():
            route_transitions[str(name)] += int(count)
    runs = max(1, len(results))
    return {
        **{key: totals[key] for key in totals},
        "strategy_route_selections": dict(sorted(route_selections.items())),
        "strategy_route_transitions": dict(sorted(route_transitions.items())),
        "mean_run_seconds": totals["run_seconds"] / runs,
        "steps_per_second": (totals["rollout_steps"] / totals["seconds"])
        if totals["seconds"] > 0
        else 0.0,
        "changed_fraction": (totals["changed"] / totals["searched"])
        if totals["searched"] > 0
        else 0.0,
        "strategy_identity_changed_fraction": (
            totals["strategy_identity_changes"] / totals["searched"]
        )
        if totals["searched"] > 0
        else 0.0,
        "unavailable_fraction": (
            totals["unavailable"] / totals["strategic_decisions"]
            if totals["strategic_decisions"] > 0
            else 0.0
        ),
        "strategy_specialist_unavailable_fraction": (
            totals["strategy_specialist_unavailable"]
            / totals["strategic_decisions"]
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
        and decision.preferred_route == decision.control_route
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
    origin_key: bytes | None = None,
    mode: str = "legacy",
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
        or type(row["search"].get("rejected_rollouts")) is not int
        or row["search"].get("rejected_rollouts") != 0
        for row in results
    ):
        for row in results:
            row.pop("_teacher_drafts", None)
        return (), "discarded_rejected_panel"
    if any(
        type(row["search"].get("unavailable", 0)) is not int
        or row["search"].get("unavailable", 0) != 0
        for row in results
    ):
        for row in results:
            row.pop("_teacher_drafts", None)
        return (), "discarded_unavailable_panel"
    if mode not in {
        "legacy",
        "dense_paired_utility",
        "route_terminal_paired_utility",
    }:
        raise ValueError("teacher dataset mode is unsupported")
    for row in results:
        drafts = row.get("_teacher_drafts", ())
        if mode == "route_terminal_paired_utility" and not _valid_route_teacher_row(
            row, drafts
        ):
            for result in results:
                result.pop("_teacher_drafts", None)
            return (), "discarded_invalid_route_teacher_panel"
        if origin_key is not None and mode == "dense_paired_utility" and (
            not isinstance(drafts, tuple)
            or not all(isinstance(draft, StrategyTeacherDraft) for draft in drafts)
            or type(row["search"].get("searched")) is not int
            or row["search"].get("searched") != len(drafts)
            or any(
                draft.candidate_space_size != len(draft.candidates)
                or any(
                    candidate.intent is not None
                    or len(candidate.samples) != 6
                    or any(
                        sample.endpoint == StrategyTargetEndpoint.CENSORED
                        for sample in candidate.samples
                    )
                    for candidate in draft.candidates
                )
                for draft in drafts
            )
        ):
            for result in results:
                result.pop("_teacher_drafts", None)
            return (), "discarded_invalid_teacher_panel"
        if origin_key is not None and mode == "legacy":
            for result in results:
                result.pop("_teacher_drafts", None)
            return (), "discarded_invalid_teacher_panel"
    records: list[StrategyTeacherRecord] = []
    run_groups = [
        (
            "origin-"
            + hmac.new(
                origin_key,
                str(int(row["seed"])).encode(),
                hashlib.sha256,
            ).hexdigest()[:32]
            if origin_key is not None
            else f"origin-{secrets.token_hex(16)}"
        )
        for row in results
    ]
    if len(set(run_groups)) != len(run_groups):
        raise RuntimeError("opaque teacher origin identifier collision")
    for run_group, row in zip(run_groups, results, strict=True):
        drafts = row.pop("_teacher_drafts", ())
        if not isinstance(drafts, tuple) or not all(
            isinstance(draft, StrategyTeacherDraft) for draft in drafts
        ):
            raise RuntimeError("worker returned invalid strategy teacher drafts")
        for decision_index, draft in enumerate(drafts):
            records.append(
                draft.finalize(
                    run_group=run_group,
                    decision_index=decision_index,
                    run_complete=True,
                    run_won=bool(row["won"]),
                    terminal_ante=int(row["antes_cleared"]),
                    best_hand_score=int(row["best_hand_score"]),
                )
            )
    if not records:
        return (), "discarded_no_eligible_decisions"
    secrets.SystemRandom().shuffle(records)
    return tuple(records), "written"


def _valid_route_teacher_row(row: dict[str, object], drafts: object) -> bool:
    """Authenticate one action-inert v16 route-terminal source run."""

    search = row.get("search")
    decisions = row.get("success_teacher_decisions")
    zero_counters = (
        "success_anchor_fallbacks",
        "success_anchor_unavailable",
        "success_anchor_unsupported",
        "success_teacher_rejected_rollouts",
        "success_teacher_censored_rollouts",
        "strategy_specialist_unavailable",
    )
    if (
        not isinstance(search, dict)
        or not isinstance(drafts, tuple)
        or not all(isinstance(draft, StrategyTeacherDraft) for draft in drafts)
        or not isinstance(decisions, list)
        or len(decisions) != len(drafts)
        or type(search.get("success_anchors_attempted")) is not int
        or search.get("success_anchors_attempted") != len(drafts)
        or type(search.get("success_anchors_completed")) is not int
        or search.get("success_anchors_completed") != len(drafts)
        or any(
            type(search.get(name)) is not int or search.get(name) != 0
            for name in zero_counters
        )
        or row.get("search_failure_reasons") != {}
    ):
        return False
    for draft, decision in zip(drafts, decisions, strict=True):
        if not isinstance(decision, dict):
            return False
        sample_count = len(draft.candidates[0].samples)
        identities = tuple(
            (candidate.action, candidate.intent, candidate.route)
            for candidate in draft.candidates
        )
        ordinary_by_action = Counter(
            candidate.action
            for candidate in draft.candidates
            if candidate.intent is None and candidate.route is None
        )
        expected_counts = {
            "ante": draft.observation.ante,
            "roots": len(draft.candidates),
            "initial_samples": sample_count,
            "max_samples_used": sample_count,
            "sample_evaluations": len(draft.candidates) * sample_count,
            "ordinary_index": draft.ordinary_index,
            "behavior_index": draft.behavior_index,
            "teacher_selected_index": draft.selected_index,
            "executed_index": draft.behavior_index,
            "rejected_rollouts": 0,
            "censored_rollouts": 0,
        }
        if (
            draft.candidate_space_size != len(draft.candidates)
            or draft.baseline_index != draft.ordinary_index
            or draft.candidates[draft.ordinary_index].intent is not None
            or draft.candidates[draft.ordinary_index].route is not None
            or len(set(identities)) != len(identities)
            or any(
                candidate.route == RunRoute.VICTORY
                or len(candidate.samples) != sample_count
                or (
                    candidate.route is None
                    and candidate.intent is not None
                )
                or (
                    candidate.route is not None
                    and ordinary_by_action[candidate.action] != 1
                )
                or any(
                    sample.endpoint == StrategyTargetEndpoint.CENSORED
                    for sample in candidate.samples
                )
                for candidate in draft.candidates
            )
            or decision.get("phase") != draft.observation.phase.value
            or decision.get("goal") != draft.goal.value
            or any(
                type(decision.get(name)) is not int
                or decision.get(name) != expected
                for name, expected in expected_counts.items()
            )
            or decision.get("affects_actions") is not False
            or decision.get("identity_override") is not False
            or decision.get("fallback_reason") is not None
            or decision.get("unavailable") is not False
            or decision.get("unsupported") is not False
        ):
            return False
        for name, index in (
            ("ordinary", draft.ordinary_index),
            ("behavior", draft.behavior_index),
            ("teacher_selected", draft.selected_index),
            ("executed", draft.behavior_index),
        ):
            if decision.get(name) != _teacher_candidate_identity(
                draft.candidates[index]
            ):
                return False
    return True


def _teacher_candidate_identity(
    candidate: StrategyTeacherCandidate,
) -> dict[str, object]:
    return {
        "action": action_to_data(candidate.action),
        "intent": candidate.intent.value if candidate.intent is not None else None,
        "route": candidate.route.value if candidate.route is not None else None,
    }


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
    dense_sensitive_rows = 0
    phase_rows: Counter[str] = Counter()
    action_roots: Counter[str] = Counter()
    route_roots: Counter[str] = Counter()
    route_diverse_rows = 0
    observed_victory_groups: set[str] = set()
    for record in records:
        phase_rows[record.observation.phase.value] += 1
        baseline = record.candidates[record.baseline_index].samples
        sensitive = False
        row_routes: set[str] = set()
        for candidate in record.candidates:
            action_roots[type(candidate.action).__name__] += 1
            route = candidate.route.value if candidate.route is not None else "none"
            route_roots[route] += 1
            row_routes.add(route)
            if any(sample.ante8_win == 1.0 for sample in candidate.samples):
                observed_victory_groups.add(record.run_group)
            delta = sum(
                sample.search_utility - base.search_utility
                for sample, base in zip(candidate.samples, baseline, strict=True)
            ) / len(candidate.samples)
            sensitive |= abs(delta) > 1e-12
        dense_sensitive_rows += int(sensitive)
        route_diverse_rows += int(len(row_routes) > 1)
    return {
        "winning_source_groups": winning_groups,
        "losing_source_groups": losing_groups,
        "resolved_endless_rows": len(endless_rows),
        "resolved_endless_groups": endless_groups,
        "late_action_sensitive_ante8_rows": sensitive_late_rows,
        "training_coverage_passed": passed,
        "dense_paired_utility": {
            "records": len(records),
            "action_sensitive_rows": dense_sensitive_rows,
            "action_sensitive_fraction": (
                dense_sensitive_rows / len(records) if records else 0.0
            ),
            "phase_rows": dict(sorted(phase_rows.items())),
            "action_roots": dict(sorted(action_roots.items())),
            "route_roots": dict(sorted(route_roots.items())),
            "route_diverse_rows": route_diverse_rows,
            "stored_root_max": max(
                (len(record.candidates) for record in records), default=0
            ),
            "candidate_space_max": max(
                (record.candidate_space_size for record in records), default=0
            ),
            "subset_rows": sum(
                record.candidate_space_size > len(record.candidates)
                for record in records
            ),
            "subset_contract": "complete_roots;max512;overflow=fail_closed",
            "observed_victory_origin_groups": len(observed_victory_groups),
            "postwin_rows": len(endless_rows),
            "postwin_origin_groups": endless_groups,
        },
        "route_terminal_paired_utility": route_terminal_teacher_coverage(records),
    }


def _teacher_dataset_mode(args: argparse.Namespace) -> str:
    if args.dense_teacher:
        return "dense_paired_utility"
    if (
        args.strategy_options
        and args.success_teacher
        and not args.success_terminal_actions
    ):
        return "route_terminal_paired_utility"
    return "legacy"


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
    parser.add_argument(
        "--trace-dir",
        type=Path,
        help=(
            "Write one seed-free public candidate transcript per run; "
            "these traces are action transcripts and never authority evidence."
        ),
    )
    parser.add_argument("--profile-search-timing", action="store_true")
    parser.add_argument("--strategy-shadow-model", type=Path)
    parser.add_argument("--strategy-continuation-model", type=Path)
    parser.add_argument("--strategy-continuation-certificate", type=Path)
    parser.add_argument("--strategy-continuation-training-report", type=Path)
    parser.add_argument("--record-shadow-decisions", action="store_true")
    parser.add_argument("--teacher-jsonl", type=Path)
    parser.add_argument("--dense-teacher", action="store_true")
    parser.add_argument("--success-teacher", action="store_true")
    parser.add_argument("--success-terminal-actions", action="store_true")
    parser.add_argument("--success-teacher-samples", type=int, default=2)
    parser.add_argument("--success-teacher-start-ante", type=int, default=4)
    parser.add_argument("--success-teacher-endless-antes", type=int, default=2)
    parser.add_argument("--success-teacher-max-steps", type=int, default=600)
    parser.add_argument("--success-terminal-max-samples", type=int, default=12)
    parser.add_argument("--success-terminal-max-roots", type=int, default=64)
    parser.add_argument("--success-terminal-family-alpha", type=float, default=0.05)
    parser.add_argument("--terminal-preregistration-json", type=Path)
    parser.add_argument("--contextual-preregistration-json", type=Path)
    parser.add_argument("--route-terminal-preregistration-json", type=Path)
    parser.add_argument("--origin-key-file", type=Path)
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
