from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from balatro_ai_v2.actions import LeaveShop, RerollShop
from balatro_ai_v2.balatrobot.adapter import to_public_observation
from balatro_ai_v2.strategy_engine import RunGoal
from balatro_ai_v2.strategy_options import StrategyIntent
from balatro_ai_v2.strategy_teacher import (
    StrategyRolloutTarget,
    StrategyTeacherCandidate,
    StrategyTeacherDraft,
    read_teacher_records,
    write_teacher_records,
)
from state_factory import state


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


def _record(group: int):
    observation = to_public_observation(state("SHOP", money=10))
    return StrategyTeacherDraft(
        observation=observation,
        candidates=(
            StrategyTeacherCandidate(
                LeaveShop(),
                StrategyIntent.STABILIZE,
                tuple(
                    StrategyRolloutTarget(0, 0, 0, 3, 1, search_utility=1)
                    for _ in range(6)
                ),
            ),
            StrategyTeacherCandidate(
                RerollShop(),
                StrategyIntent.ECONOMY,
                tuple(
                    StrategyRolloutTarget(1, 1, 0, 4, 2, search_utility=2)
                    for _ in range(6)
                ),
            ),
        ),
        selected_index=1,
        baseline_index=0,
        goal=RunGoal.VICTORY,
        teacher_config_digest="3" * 64,
    ).finalize(
        run_group=f"origin-{group:032x}",
        decision_index=0,
        run_complete=True,
        run_won=False,
        terminal_ante=3,
        best_hand_score=100,
    )


def _component(tmp_path: Path, name: str, seed_start: int, group_start: int):
    dataset = tmp_path / f"{name}.jsonl"
    report = tmp_path / f"{name}.json"
    records = tuple(_record(group_start + offset) for offset in range(50))
    digest = write_teacher_records(dataset, records)
    payload = {
        "candidate_only": True,
        "candidate_runtime": {"revision": "runtime", "data_hashes": {}},
        "manifest": {
            "source_digest": "a" * 64,
            "backend": {"backend_name": "Jackdaw"},
            "repository_revision": "b" * 40,
            "repository_dirty": False,
            "max_antes_cleared": 12,
            "max_decisions": 1200,
            "run": {"deck": "RED", "stake": "WHITE", "seed": "opaque"},
            "command": ["collector"],
        },
        "search_protocol": {
            "version": "determinized-search-v9",
            "budget": {
                "samples": 6,
                "horizon_antes": 1,
                "max_steps": 200,
                "override_z": 1.0,
            },
            "nonce": "contextual-continuation-v9-frozen",
            "strategy_options": False,
            "include_reorders": False,
        },
        "strategy_tuning": {"replacement_margin": 20},
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
            "protocol_id": "contextual-continuation-development-v1",
            "sha256": "d" * 64,
            "immutable_batches": True,
            "batch_id": f"batch-{(seed_start - 1075) // 50 + 1:02d}",
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
                "search": {"rejected_rollouts": 0},
            }
            for seed in range(seed_start, seed_start + 50)
        ],
        "summary": {"runs": 50},
    }
    report.write_text(json.dumps(payload), encoding="utf-8")
    return dataset, report


def test_merge_cli_preserves_all_disjoint_groups_and_component_hashes(
    tmp_path, monkeypatch
) -> None:
    script = _load_script()
    components = [
        _component(tmp_path, f"batch-{index}", seed, index * 100)
        for index, seed in enumerate(range(1075, 1375, 50), start=1)
    ]
    output = tmp_path / "merged.jsonl"
    report = tmp_path / "merged.json"
    monkeypatch.setattr(
        script.sys,
        "argv",
        [
            "merge_strategy_teacher_datasets.py",
            *(
                value
                for dataset, component_report in components
                for value in (
                    "--input",
                    str(dataset),
                    str(component_report),
                )
            ),
            "--output-jsonl",
            str(output),
            "--output-report",
            str(report),
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
    assert "results" not in merged
    assert "1075" not in json.dumps(merged)


def test_merge_rejects_revision_or_seed_overlap(tmp_path) -> None:
    script = _load_script()
    paths = [
        _component(tmp_path, f"batch-{index}", seed, index * 100)
        for index, seed in enumerate(range(1075, 1375, 50), start=1)
    ]
    duplicate = json.loads(paths[1][1].read_text(encoding="utf-8"))
    duplicate["results"] = json.loads(paths[0][1].read_text(encoding="utf-8"))[
        "results"
    ]
    duplicate["contextual_teacher_preregistration"].update(
        {"batch_id": "batch-01", "seed_start": 1075}
    )
    paths[1][1].write_text(json.dumps(duplicate), encoding="utf-8")
    components = tuple(script._load_component(*component) for component in paths)

    with pytest.raises(SystemExit, match="overlap"):
        script._validate_components(components)

    paths[1] = _component(tmp_path, "replacement", 1125, 700)
    changed = json.loads(paths[1][1].read_text(encoding="utf-8"))
    changed["manifest"]["repository_revision"] = "c" * 40
    paths[1][1].write_text(json.dumps(changed), encoding="utf-8")
    components = tuple(script._load_component(*component) for component in paths)
    with pytest.raises(SystemExit, match="protocol mismatch"):
        script._validate_components(components)


def test_merge_rejects_missing_binding_and_internal_duplicate_seed(tmp_path) -> None:
    script = _load_script()
    paths = [
        _component(tmp_path, f"batch-{index}", seed, index * 100)
        for index, seed in enumerate(range(1075, 1375, 50), start=1)
    ]
    components = tuple(script._load_component(*component) for component in paths)
    components[0][1].pop("contextual_teacher_preregistration")
    with pytest.raises(SystemExit, match="lacks contextual preregistration"):
        script._validate_components(components)

    changed = json.loads(paths[0][1].read_text(encoding="utf-8"))
    changed["results"][-1]["seed"] = changed["results"][0]["seed"]
    paths[0][1].write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(SystemExit, match="not merge-eligible"):
        script._load_component(*paths[0])
