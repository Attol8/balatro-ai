from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
from pathlib import Path

import pytest

from balatro_ai_v2.actions import (
    LeaveShop,
    ReorderConsumables,
    ReorderHand,
    ReorderJokers,
    iter_legal_actions,
)
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.strategy_engine import RunGoal
from balatro_ai_v2.strategy_teacher import (
    StrategyRolloutTarget,
    StrategyTeacherCandidate,
    StrategyTeacherDraft,
    read_teacher_records,
    write_teacher_records,
)
from state_factory import state


_REORDERS = (ReorderHand, ReorderJokers, ReorderConsumables)


def _load_script():
    path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "merge_strategy_teacher_datasets.py"
    )
    spec = importlib.util.spec_from_file_location("merge_strategy_teacher", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _record(seed: int, key: bytes):
    observation = to_public_observation(state("SHOP", money=10))
    actions = tuple(
        action
        for action in iter_legal_actions(observation)
        if not isinstance(action, _REORDERS)
    )
    baseline_index = actions.index(LeaveShop())
    selected_index = next(
        index for index in range(len(actions)) if index != baseline_index
    )
    candidates = tuple(
        StrategyTeacherCandidate(
            action,
            None,
            tuple(
                StrategyRolloutTarget(
                    1,
                    1,
                    0,
                    4,
                    2,
                    search_utility=2 if index == selected_index else 1,
                )
                for _ in range(6)
            ),
        )
        for index, action in enumerate(actions)
    )
    group = (
        "origin-" + hmac.new(key, str(seed).encode(), hashlib.sha256).hexdigest()[:32]
    )
    return StrategyTeacherDraft(
        observation=observation,
        candidates=candidates,
        selected_index=selected_index,
        baseline_index=baseline_index,
        goal=RunGoal.VICTORY,
        teacher_config_digest="3" * 64,
        candidate_space_size=len(candidates),
    ).finalize(
        run_group=group,
        decision_index=0,
        run_complete=True,
        run_won=False,
        terminal_ante=3,
        best_hand_score=100,
    )


def _preregistration(tmp_path: Path, script, monkeypatch):
    coverage_gate = {
        **script._EXPECTED_COVERAGE_GATE,
        "minimum_records": 300,
        "required_phases": ["SHOP"],
        "minimum_winning_source_groups": 0,
        "minimum_observed_victory_groups": 0,
        "minimum_postwin_rows": 0,
        "minimum_postwin_groups": 0,
    }
    first_gate = {
        **script._EXPECTED_FIRST_100_GATE,
        "minimum_observed_victory_groups": 0,
    }
    monkeypatch.setattr(script, "_EXPECTED_COVERAGE_GATE", coverage_gate)
    monkeypatch.setattr(script, "_EXPECTED_FIRST_100_GATE", first_gate)
    monkeypatch.setattr(script, "_validate_source_freeze", lambda *_args: None)
    monkeypatch.setattr(script, "_verify_merger_checkout", lambda *_args: None)
    key = b"0123456789abcdef0123456789abcdef"
    key_path = tmp_path / "runs/secrets/contextual-continuation-v11-origin.key"
    key_path.parent.mkdir(parents=True)
    key_path.write_bytes(key)
    batches = [
        {
            "batch_id": f"batch-{index:02d}",
            "seed_start": seed_start,
            "seeds": 50,
            "teacher_jsonl": (
                "runs/experiments/contextual-continuation-v11/"
                f"batch-{index:02d}/teacher.jsonl"
            ),
            "report_json": (
                "runs/experiments/contextual-continuation-v11/"
                f"batch-{index:02d}/report.json"
            ),
        }
        for index, seed_start in enumerate(range(1675, 1975, 50), start=1)
    ]
    candidate_runtime = {"revision": "runtime", "data_hashes": {}}
    backend = {"backend_name": "Jackdaw", "adapter_version": "3"}
    strategy_tuning = {"replacement_margin": 20}
    spec = {
        "protocol_id": script._PROTOCOL_ID,
        "status": "reserved",
        "immutable_batches": True,
        "implementation_revision": "b" * 40,
        "expected_source_digest": "a" * 64,
        "seed_provenance": "development",
        "deck": "RED",
        "stake": "WHITE",
        "candidate_runtime": candidate_runtime,
        "backend": backend,
        "strategy_tuning": strategy_tuning,
        "search": script._EXPECTED_SEARCH,
        "origin_mapping": {
            "algorithm": "hmac-sha256-truncated-128",
            "key_path": "runs/secrets/contextual-continuation-v11-origin.key",
            "key_sha256": hashlib.sha256(key).hexdigest(),
        },
        "batches": batches,
        "training": script._EXPECTED_TRAINING,
        "coverage_gate": coverage_gate,
        "first_100_kill_gate": first_gate,
    }
    path = tmp_path / "experiments/contextual-continuation-v11-preregistration.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path, key_path, key, spec, hashlib.sha256(path.read_bytes()).hexdigest()


def _component(
    tmp_path: Path,
    *,
    index: int,
    seed_start: int,
    key: bytes,
    preregistration_digest: str,
    spec: dict[str, object],
):
    root = tmp_path / "runs/experiments/contextual-continuation-v11"
    root = root / f"batch-{index:02d}"
    root.mkdir(parents=True, exist_ok=True)
    dataset = root / "teacher.jsonl"
    report = root / "report.json"
    records = tuple(_record(seed, key) for seed in range(seed_start, seed_start + 50))
    digest = write_teacher_records(dataset, records)
    payload = {
        "candidate_only": True,
        "candidate_runtime": spec["candidate_runtime"],
        "manifest": {
            "source_digest": spec["expected_source_digest"],
            "backend": spec["backend"],
            "repository_revision": "c" * 40,
            "repository_dirty": False,
            "max_antes_cleared": 12,
            "max_decisions": 1200,
            "run": {"deck": "RED", "stake": "WHITE", "seed": "opaque"},
            "command": ["collector"],
        },
        "search_protocol": {
            "version": "determinized-search-v11",
            "continuation": "strategic",
            "policy_seed": "baseline-v1",
            "budget": {
                "samples": 6,
                "horizon_antes": 1,
                "max_steps": 200,
                "override_z": 1.0,
            },
            "nonce": "contextual-continuation-v11-frozen",
            "phases": ["BLIND_SELECT", "PACK", "SHOP"],
            "strategy_options": False,
            "include_reorders": False,
        },
        "strategy_tuning": spec["strategy_tuning"],
        "benchmark_protocol": {
            "seed_provenance": "development",
            "filtered_seeds": False,
            "restart_selection": False,
            "mods": False,
            "panel_registry": {
                "verification": "registry_verified",
                "count": 50,
            },
        },
        "contextual_teacher_preregistration": {
            "protocol_id": "contextual-continuation-development-v3",
            "sha256": preregistration_digest,
            "immutable_batches": True,
            "batch_id": f"batch-{index:02d}",
            "seed_start": seed_start,
            "seeds": 50,
        },
        "strategy_teacher_dataset": {
            "mode": "dense_paired_utility",
            "status": "written",
            "sha256": digest,
            "records": 50,
            "groups": 50,
            "complete_runs_only": True,
            "contains_game_seeds": False,
            "teacher_config_digest": "3" * 64,
            "coverage": {},
        },
        "results": [
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
        ],
        "summary": {"runs": 50},
    }
    report.write_text(json.dumps(payload), encoding="utf-8")
    return dataset, report


def _fixtures(tmp_path, script, monkeypatch):
    prereg_path, key_path, key, spec, digest = _preregistration(
        tmp_path, script, monkeypatch
    )
    paths = [
        _component(
            tmp_path,
            index=index,
            seed_start=seed_start,
            key=key,
            preregistration_digest=digest,
            spec=spec,
        )
        for index, seed_start in enumerate(range(1675, 1975, 50), start=1)
    ]
    return prereg_path, key_path, key, spec, digest, paths


def test_merge_cli_preserves_all_disjoint_groups_and_component_hashes(
    tmp_path, monkeypatch
) -> None:
    script = _load_script()
    prereg, key_path, _, _, _, components = _fixtures(tmp_path, script, monkeypatch)
    output = tmp_path / "merged/teacher.jsonl"
    report = tmp_path / "merged/report.json"
    monkeypatch.setattr(
        script.sys,
        "argv",
        [
            "merge_strategy_teacher_datasets.py",
            *(value for pair in components for value in ("--input", *map(str, pair))),
            "--output-jsonl",
            str(output),
            "--output-report",
            str(report),
            "--preregistration-json",
            str(prereg),
            "--origin-key-file",
            str(key_path),
            "--repository-root",
            str(tmp_path),
        ],
    )

    script.main()

    merged = json.loads(report.read_text(encoding="utf-8"))
    assert len(read_teacher_records(output)) == 300
    assert merged["strategy_teacher_dataset"]["groups"] == 300
    assert (
        merged["strategy_teacher_dataset"]["coverage"]["dense_paired_utility"][
            "action_sensitive_rows"
        ]
        == 300
    )
    assert len(merged["merged_components"]) == 6
    assert (
        merged["contextual_teacher_preregistration"]["protocol_id"]
        == "contextual-continuation-development-v3"
    )
    assert "results" not in merged
    assert "1675" not in json.dumps(merged)


def test_merge_rejects_revision_or_seed_overlap(tmp_path, monkeypatch) -> None:
    script = _load_script()
    prereg, key_path, _, spec, digest, paths = _fixtures(tmp_path, script, monkeypatch)
    loaded_spec, loaded_digest, key = script._load_preregistration(
        prereg, key_path, repository_root=tmp_path
    )
    duplicate = json.loads(paths[1][1].read_text(encoding="utf-8"))
    duplicate["results"] = json.loads(paths[0][1].read_text(encoding="utf-8"))[
        "results"
    ]
    duplicate["contextual_teacher_preregistration"].update(
        {"batch_id": "batch-01", "seed_start": 1675}
    )
    paths[1][1].write_text(json.dumps(duplicate), encoding="utf-8")
    components = tuple(script._load_component(*component) for component in paths)
    kwargs = {
        "preregistration": loaded_spec,
        "preregistration_digest": loaded_digest,
        "origin_key": key,
        "repository_root": tmp_path,
    }
    with pytest.raises(SystemExit, match="wrong batch panel|overlap"):
        script._validate_components(components, **kwargs)

    paths[1][0].unlink()
    paths[1][1].unlink()
    paths[1] = _component(
        tmp_path,
        index=2,
        seed_start=1725,
        key=key,
        preregistration_digest=digest,
        spec=spec,
    )
    changed = json.loads(paths[1][1].read_text(encoding="utf-8"))
    changed["manifest"]["repository_revision"] = "d" * 40
    paths[1][1].write_text(json.dumps(changed), encoding="utf-8")
    components = tuple(script._load_component(*component) for component in paths)
    with pytest.raises(SystemExit, match="protocol mismatch"):
        script._validate_components(components, **kwargs)


def test_merge_rejects_tampered_origin_and_run_outcome(tmp_path, monkeypatch) -> None:
    script = _load_script()
    prereg, key_path, _, _, _, paths = _fixtures(tmp_path, script, monkeypatch)
    spec, digest, key = script._load_preregistration(
        prereg, key_path, repository_root=tmp_path
    )
    kwargs = {
        "preregistration": spec,
        "preregistration_digest": digest,
        "origin_key": key,
        "repository_root": tmp_path,
    }
    components = tuple(script._load_component(*component) for component in paths)
    object.__setattr__(components[0][3][0], "run_group", "origin-" + "f" * 32)
    with pytest.raises(SystemExit, match="origin mapping"):
        script._validate_components(components, **kwargs)

    components = tuple(script._load_component(*component) for component in paths)
    object.__setattr__(components[0][3][0], "terminal_ante", 4)
    with pytest.raises(SystemExit, match="outcome disagrees"):
        script._validate_components(components, **kwargs)


def test_merge_rejects_missing_binding_and_internal_duplicate_seed(
    tmp_path, monkeypatch
) -> None:
    script = _load_script()
    _, _, _, _, _, paths = _fixtures(tmp_path, script, monkeypatch)
    components = tuple(script._load_component(*component) for component in paths)
    components[0][2].pop("contextual_teacher_preregistration")
    with pytest.raises(SystemExit, match="lacks contextual preregistration"):
        script._validate_components(
            components,
            preregistration={},
            preregistration_digest="d" * 64,
            origin_key=b"0" * 32,
            repository_root=tmp_path,
        )

    changed = json.loads(paths[0][1].read_text(encoding="utf-8"))
    changed["results"][-1]["seed"] = changed["results"][0]["seed"]
    paths[0][1].write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(SystemExit, match="not merge-eligible"):
        script._load_component(*paths[0])
