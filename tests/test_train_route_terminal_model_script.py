from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import torch

from balatro_ai_v2.route_learning import RouteDatasetSplit
from balatro_ai_v2.route_learning_protocol import (
    MODEL_CONFIG,
    OPTIMIZER_CONFIG,
    ROUTE_LEARNING_COLLECTION_MODE,
)
from balatro_ai_v2.route_model import RouteResidualCalibration, load_route_model
from balatro_ai_v2.route_teacher_protocol import ROUTE_TEACHER_BATCHES
from balatro_ai_v2.strategy_model import (
    RelationalStrategyPolicyValue,
    StrategyModelConfig,
)


def _module():
    path = Path(__file__).parents[1] / "scripts/train_route_terminal_model.py"
    spec = importlib.util.spec_from_file_location("route_trainer", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(tmp_path: Path):
    bundle = tmp_path / "bundle"
    return SimpleNamespace(
        input_jsonl=tmp_path / "merged/teacher.jsonl",
        collection_report=tmp_path / "merged/report.json",
        collection_preregistration_json=tmp_path / "collection.json",
        learner_preregistration_json=tmp_path / "learner.json",
        output_model=bundle / "model.pt",
        report_json=bundle / "report.json",
        repository_root=tmp_path,
        epochs=OPTIMIZER_CONFIG["epochs"],
        training_seed=OPTIMIZER_CONFIG["training_seed"],
        learning_rate=OPTIMIZER_CONFIG["learning_rate"],
        weight_decay=OPTIMIZER_CONFIG["weight_decay"],
        max_gradient_norm=OPTIMIZER_CONFIG["max_gradient_norm"],
        device="cpu",
        hidden_size=MODEL_CONFIG["hidden_size"],
        attention_heads=MODEL_CONFIG["attention_heads"],
        attention_layers=MODEL_CONFIG["attention_layers"],
        feedforward_size=MODEL_CONFIG["feedforward_size"],
        max_entities=MODEL_CONFIG["max_entities"],
        max_actions=MODEL_CONFIG["max_actions"],
    )


def _source(module):
    return module._Source("a" * 40, "b" * 64)


def _groups(start: int, count: int) -> tuple[str, ...]:
    return tuple(f"origin-{value:032x}" for value in range(start, start + count))


def _split() -> RouteDatasetSplit:
    return RouteDatasetSplit(
        train=(),
        calibration=(),
        holdout=(),
        train_groups=_groups(0, 12),
        calibration_groups=_groups(12, 4),
        holdout_groups=_groups(16, 4),
    )


def _inputs(module):
    return module._Inputs(
        records=(),
        merged_report={},
        dataset_digest="1" * 64,
        merged_report_digest="2" * 64,
        collection_preregistration={},
        collection_preregistration_digest="3" * 64,
        learner_preregistration={},
        learner_preregistration_digest="4" * 64,
        teacher_config_digest="5" * 64,
    )


def _model() -> RelationalStrategyPolicyValue:
    return RelationalStrategyPolicyValue(StrategyModelConfig(**MODEL_CONFIG))


def _patch_main_inputs(module, monkeypatch, args, *, admission_passed: bool):
    source = _source(module)
    captures = []

    def capture(_root):
        captures.append("source")
        return source

    monkeypatch.setattr(
        module, "build_parser", lambda: SimpleNamespace(parse_args=lambda: args)
    )
    monkeypatch.setattr(module, "_capture_source", capture)
    monkeypatch.setattr(module, "_load_inputs", lambda *_: _inputs(module))
    monkeypatch.setattr(module, "reconstruct_route_split", lambda *_: _split())
    monkeypatch.setattr(
        module,
        "route_split_admission_report",
        lambda *_: {"splits": {}, "passed": admission_passed},
    )
    return captures


def test_happy_path_publishes_verified_shadow_only_bundle(
    tmp_path, monkeypatch, capsys
):
    module = _module()
    args = _args(tmp_path)
    captures = _patch_main_inputs(module, monkeypatch, args, admission_passed=True)
    calls = []
    calibration = RouteResidualCalibration(calibrated=True)

    def train(split):
        calls.append(("train", split))
        return _model(), [{"epoch": 1, "loss": 0.25, "gradient_norm": 0.5}]

    evidence = {"kind": "test-evidence"}

    def calibrate(model, split):
        calls.append(("calibrate", split.calibration))
        return calibration, evidence

    def evaluate(model, split, fitted, *, calibration_evidence):
        calls.append(("evaluate", split.holdout, calibration_evidence))
        assert fitted == calibration
        return {"gate": {"passed": True}, "holdout_heads": {}}

    monkeypatch.setattr(module, "_train", train)
    monkeypatch.setattr(module, "fit_route_residual_calibration", calibrate)
    monkeypatch.setattr(module, "evaluate_route_holdout", evaluate)
    module.main()

    assert [call[0] for call in calls] == ["train", "calibrate", "evaluate"]
    assert captures == ["source", "source"]
    assert args.output_model.is_file() and args.report_json.is_file()
    artifact = load_route_model(args.output_model)
    assert artifact.calibration == calibration
    assert artifact.provenance["training_status"] == "trained"
    assert artifact.provenance["influence_mode"] == "shadow_only"
    report = json.loads(args.report_json.read_bytes())
    assert report["status"] == "passed"
    assert (
        report["artifact"]["sha256"]
        == hashlib.sha256(args.output_model.read_bytes()).hexdigest()
    )
    assert report["promotion_eligible"] is False
    assert report["action_authority"] is False
    assert report["rollout_authority"] is False
    assert report["certificate_created"] is False
    assert report["training"]["losses"][0]["loss"] == 0.25
    assert report["evaluation"]["gate"]["passed"] is True
    printed = json.loads(capsys.readouterr().out)
    assert printed["status"] == "passed"


def test_failed_admission_publishes_rejection_without_constructing_model(
    tmp_path, monkeypatch
):
    module = _module()
    args = _args(tmp_path)
    _patch_main_inputs(module, monkeypatch, args, admission_passed=False)
    monkeypatch.setattr(
        module, "_train", lambda *_: pytest.fail("training must not start")
    )
    monkeypatch.setattr(
        module,
        "RelationalStrategyPolicyValue",
        lambda *_: pytest.fail("model must not be constructed"),
    )
    module.main()
    report = json.loads(args.report_json.read_bytes())
    assert report["status"] == "rejected"
    assert report["rejection_reason"] == "split_admission_failed"
    assert report["training"]["started"] is False
    assert not args.output_model.exists()


def test_failed_holdout_gate_publishes_report_only(tmp_path, monkeypatch):
    module = _module()
    args = _args(tmp_path)
    _patch_main_inputs(module, monkeypatch, args, admission_passed=True)
    calibration = RouteResidualCalibration(calibrated=True)
    monkeypatch.setattr(module, "_train", lambda *_: (_model(), [{"loss": 1.0}]))
    monkeypatch.setattr(
        module,
        "fit_route_residual_calibration",
        lambda *_: (calibration, {"kind": "test-evidence"}),
    )
    monkeypatch.setattr(
        module,
        "evaluate_route_holdout",
        lambda *_args, **_kwargs: {
            "gate": {"scalar_residual_mae_beats_zero": False, "passed": False}
        },
    )
    module.main()
    report = json.loads(args.report_json.read_bytes())
    assert report["status"] == "rejected"
    assert report["rejection_reason"] == "holdout_gate_failed"
    assert report["training"]["started"] is True
    assert report["gate"]["passed"] is False
    assert report["artifact"]["status"] == "absent"
    assert not args.output_model.exists()


def test_source_snapshot_precedes_any_input_read(tmp_path, monkeypatch):
    module = _module()
    args = _args(tmp_path)
    calls = []
    monkeypatch.setattr(
        module, "build_parser", lambda: SimpleNamespace(parse_args=lambda: args)
    )
    monkeypatch.setattr(
        module,
        "_capture_source",
        lambda *_: calls.append("source") or _source(module),
    )

    def load(*_args):
        calls.append("inputs")
        raise SystemExit("stop")

    monkeypatch.setattr(module, "_load_inputs", load)
    with pytest.raises(SystemExit, match="stop"):
        module.main()
    assert calls == ["source", "inputs"]


def test_no_overwrite_and_output_bundle_layout_are_fail_closed(tmp_path):
    module = _module()
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    with pytest.raises(SystemExit, match="overwrite"):
        module._validate_output_paths(bundle / "model.pt", bundle / "report.json")
    with pytest.raises(SystemExit, match="share one bundle"):
        module._validate_output_paths(
            tmp_path / "one/model.pt", tmp_path / "two/report.json"
        )
    with pytest.raises(SystemExit, match="distinct"):
        module._validate_output_paths(tmp_path / "new/output", tmp_path / "new/output")


def test_source_race_discards_staged_bundle(tmp_path, monkeypatch):
    module = _module()
    expected = _source(module)
    changed = module._Source(expected.revision, "c" * 64)
    monkeypatch.setattr(module, "_capture_source", lambda *_: changed)
    final = tmp_path / "bundle"
    with pytest.raises(SystemExit, match="source changed"):
        module._publish_directory_bundle(
            final, {"report.json": b"{}\n"}, tmp_path, expected
        )
    assert not final.exists()
    assert not tuple(tmp_path.glob(".bundle.*.tmp"))


def test_collection_preregistration_digest_and_frozen_contract(tmp_path):
    module = _module()
    repository = Path(__file__).parents[1]
    raw = (
        repository / "experiments/route-terminal-v1-preregistration.json"
    ).read_bytes()
    path = tmp_path / "experiments/route-terminal-v1-preregistration.json"
    path.parent.mkdir()
    path.write_bytes(raw)
    spec, digest = module._load_collection_preregistration(path, tmp_path)
    assert spec["protocol_id"] == "route-terminal-development-v1"
    assert digest == hashlib.sha256(raw).hexdigest()

    tampered = json.loads(raw)
    tampered["training_authorized"] = True
    path.write_text(json.dumps(tampered))
    with pytest.raises(SystemExit, match="changed the frozen protocol"):
        module._load_collection_preregistration(path, tmp_path)


def _merged_fixture():
    teacher_config = "c" * 64
    groups = _groups(50, 5)
    records = tuple(
        SimpleNamespace(run_group=group, teacher_config_digest=teacher_config)
        for group in groups
    )
    components = []
    for batch, group in zip(ROUTE_TEACHER_BATCHES, groups, strict=True):
        components.append(
            {
                "batch_id": batch["batch_id"],
                "report_sha256": "d" * 64,
                "dataset_sha256": "e" * 64,
                "opaque_group_sha256": hashlib.sha256(group.encode()).hexdigest(),
                "opaque_groups": [group],
            }
        )
    collection = {
        "implementation_revision": "1" * 40,
        "expected_source_digest": "2" * 64,
        "candidate_runtime": {"revision": "runtime"},
        "backend": {"backend_name": "Jackdaw"},
        "strategy_tuning": {"replacement_margin": 20},
    }
    learner = {
        "merger_implementation_revision": "3" * 40,
        "merger_expected_source_digest": "4" * 64,
    }
    dataset_digest = "5" * 64
    report = {
        "strategy_teacher_dataset": {
            "status": "written",
            "mode": ROUTE_LEARNING_COLLECTION_MODE,
            "schema_version": 11,
            "sha256": dataset_digest,
            "records": len(records),
            "groups": len(groups),
            "teacher_config_digest": teacher_config,
            "contains_game_seeds": False,
            "complete_runs_only": True,
            "collection_only": True,
            "training_authorized": False,
            "coverage": {ROUTE_LEARNING_COLLECTION_MODE: {"sentinel": True}},
        },
        "route_terminal_teacher_preregistration": {
            "protocol_id": "route-terminal-development-v1",
            "sha256": "6" * 64,
            "immutable_batches": True,
            "collection_only": True,
            "training_authorized": False,
            "batch_ids": [batch["batch_id"] for batch in ROUTE_TEACHER_BATCHES],
        },
        "manifest": {
            "kind": "route_terminal_teacher_merge_v1",
            "repository_dirty": False,
            "component_count": 5,
            "repository_revision": "8" * 40,
            "source_digest": collection["expected_source_digest"],
            "backend": collection["backend"],
            "merger_source": {
                "repository_dirty": False,
                "repository_revision": "7" * 40,
                "source_digest": learner["merger_expected_source_digest"],
            },
        },
        "summary": {
            "runs": 100,
            "complete": True,
            "merged_component_reports": 5,
        },
        "collection_summary": {
            "rejected_or_censored": 0,
            "training_authorized": False,
        },
        "merged_components": components,
        "candidate_runtime": collection["candidate_runtime"],
        "strategy_tuning": collection["strategy_tuning"],
    }
    return records, report, learner, collection, dataset_digest, teacher_config


def _patch_coverage(module, monkeypatch):
    monkeypatch.setattr(
        module,
        "route_terminal_teacher_coverage",
        lambda _records: {"sentinel": True},
    )
    monkeypatch.setattr(
        module, "route_teacher_coverage_gate_failures", lambda *_args, **_kwargs: ()
    )


def test_merged_bundle_validates_all_frozen_bindings(monkeypatch, tmp_path):
    module = _module()
    _patch_coverage(module, monkeypatch)
    revisions = []
    monkeypatch.setattr(
        module,
        "_validate_frozen_revision",
        lambda *args: revisions.append(args[1:]),
    )
    records, report, learner, collection, digest, teacher_config = _merged_fixture()
    assert (
        module._validate_merged_bundle(
            records, report, digest, learner, collection, "6" * 64, tmp_path
        )
        == teacher_config
    )
    assert revisions == [
        (
            collection["implementation_revision"],
            report["manifest"]["repository_revision"],
            "experiments/route-terminal-v1-preregistration.json",
            "collection",
        ),
        (
            learner["merger_implementation_revision"],
            report["manifest"]["merger_source"]["repository_revision"],
            "experiments/route-terminal-learning-v1-preregistration.json",
            "merger",
        ),
    ]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda report: report["strategy_teacher_dataset"].update({"sha256": "0" * 64}),
        lambda report: report["strategy_teacher_dataset"].update(
            {"mode": "dense_paired_utility"}
        ),
        lambda report: report["manifest"]["merger_source"].update(
            {"source_digest": "0" * 64}
        ),
        lambda report: report["merged_components"][0].update(
            {"opaque_group_sha256": "0" * 64}
        ),
        lambda report: report["merged_components"].reverse(),
    ],
)
def test_merged_bundle_rejects_digest_schema_source_and_component_tamper(
    mutation, monkeypatch, tmp_path
):
    module = _module()
    _patch_coverage(module, monkeypatch)
    monkeypatch.setattr(module, "_validate_frozen_revision", lambda *_: None)
    records, report, learner, collection, digest, _ = _merged_fixture()
    mutation(report)
    with pytest.raises(SystemExit):
        module._validate_merged_bundle(
            records, report, digest, learner, collection, "6" * 64, tmp_path
        )


def test_merged_bundle_recomputes_and_rechecks_frozen_coverage(monkeypatch, tmp_path):
    module = _module()
    records, report, learner, collection, digest, _ = _merged_fixture()
    monkeypatch.setattr(module, "_validate_frozen_revision", lambda *_: None)
    monkeypatch.setattr(
        module, "route_terminal_teacher_coverage", lambda _records: {"different": 1}
    )
    with pytest.raises(SystemExit, match="coverage disagrees"):
        module._validate_merged_bundle(
            records, report, digest, learner, collection, "6" * 64, tmp_path
        )


def test_merged_bundle_reruns_full_frozen_coverage_gate(monkeypatch, tmp_path):
    module = _module()
    records, report, learner, collection, digest, _ = _merged_fixture()
    monkeypatch.setattr(module, "_validate_frozen_revision", lambda *_: None)
    monkeypatch.setattr(
        module,
        "route_terminal_teacher_coverage",
        lambda _records: {"sentinel": True},
    )
    observed = []

    def gate(coverage, contract, *, source_runs):
        observed.append((coverage, contract, source_runs))
        return ("minimum_matched_pairs",)

    monkeypatch.setattr(module, "route_teacher_coverage_gate_failures", gate)
    with pytest.raises(SystemExit, match="fail frozen coverage"):
        module._validate_merged_bundle(
            records, report, digest, learner, collection, "6" * 64, tmp_path
        )
    assert observed[0][2] == 100


def test_trainer_source_binding_rejects_digest_tamper_and_requires_prereg_only_diff(
    monkeypatch, tmp_path
):
    module = _module()
    source = _source(module)
    learner = {
        "expected_source_digest": "0" * 64,
        "implementation_revision": "1" * 40,
    }
    with pytest.raises(SystemExit, match="source digest disagrees"):
        module._validate_source_bindings(tmp_path, source, learner)
    learner["expected_source_digest"] = source.digest
    observed = []
    monkeypatch.setattr(
        module, "_validate_frozen_revision", lambda *args: observed.append(args[1:])
    )
    module._validate_source_bindings(tmp_path, source, learner)
    assert observed == [
        (
            learner["implementation_revision"],
            source.revision,
            "experiments/route-terminal-learning-v1-preregistration.json",
            "trainer",
        )
    ]


def test_frozen_revision_requires_ancestry_and_exact_prereg_only_diff(
    monkeypatch, tmp_path
):
    module = _module()
    outputs = iter(
        [SimpleNamespace(stdout=""), SimpleNamespace(stdout="allowed.json\n")]
    )
    monkeypatch.setattr(
        module.subprocess, "run", lambda *_args, **_kwargs: next(outputs)
    )
    module._validate_frozen_revision(
        tmp_path, "1" * 40, "2" * 40, "allowed.json", "collection"
    )

    outputs = iter(
        [SimpleNamespace(stdout=""), SimpleNamespace(stdout="allowed.json\ncode.py\n")]
    )
    monkeypatch.setattr(
        module.subprocess, "run", lambda *_args, **_kwargs: next(outputs)
    )
    with pytest.raises(SystemExit, match="changed implementation source"):
        module._validate_frozen_revision(
            tmp_path, "1" * 40, "2" * 40, "allowed.json", "collection"
        )

    def no_ancestor(*_args, **_kwargs):
        raise module.subprocess.CalledProcessError(1, "git")

    monkeypatch.setattr(module.subprocess, "run", no_ancestor)
    with pytest.raises(SystemExit, match="cannot verify.*ancestry"):
        module._validate_frozen_revision(
            tmp_path, "1" * 40, "2" * 40, "allowed.json", "collection"
        )


def test_provenance_is_exactly_shadow_only_and_digest_bound():
    module = _module()
    provenance = module._route_provenance(_inputs(module), _split(), _source(module))
    assert set(provenance) == {
        "training_status",
        "influence_mode",
        "dataset_sha256",
        "collection_report_sha256",
        "collection_preregistration_sha256",
        "learner_preregistration_sha256",
        "teacher_config_digest",
        "split",
        "objective",
        "trainer_source_revision",
        "trainer_source_digest",
    }
    assert provenance["training_status"] == "trained"
    assert provenance["influence_mode"] == "shadow_only"


def test_cli_configuration_is_exact_and_json_rejects_nan(tmp_path):
    module = _module()
    args = _args(tmp_path)
    args.epochs -= 1
    with pytest.raises(SystemExit, match="configuration is frozen"):
        module._validate_args(args)
    with pytest.raises(ValueError):
        module._encode_report({"loss": float("nan")})


def test_nonfinite_training_loss_fails_before_optimizer_step(monkeypatch):
    module = _module()

    def nonfinite(model, _records):
        parameter = next(model.parameters())
        loss = parameter.sum() * torch.tensor(float("nan"))
        return loss, {"loss": float("nan")}

    monkeypatch.setattr(module, "route_training_loss", nonfinite)
    with pytest.raises(RuntimeError, match="loss became non-finite"):
        module._train(SimpleNamespace(train=()))
