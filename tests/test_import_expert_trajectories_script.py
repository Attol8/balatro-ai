from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from expert_trace_factory import write_current_expert_trace

from balatro_ai_v2.expert_trajectory import read_expert_trajectories
from balatro_ai_v2.policy_wire import POLICY_ACTION_CONTRACT

_ROOT = Path(__file__).resolve().parents[1]
_ORGANIC_TRACE = (
    _ROOT
    / "runs/evidence/planet-buy-use-organic-v1-seeds2411-2430-attempt1"
    / "red-white-seed2411.jsonl"
)
_CURRENT_ORGANIC_TRACE = (
    _ROOT
    / "runs/evidence/expert-admission-organic-v3-source"
    / "red-white-seed2507.jsonl"
)


def _load_script():
    path = _ROOT / "scripts/import_expert_trajectories.py"
    spec = importlib.util.spec_from_file_location("import_expert_trajectories", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest(path: Path, digest: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "cohort_nonce": "expert-authority-development-v1",
        "action_contract": POLICY_ACTION_CONTRACT,
        "traces": [{"path": str(path), "sha256": digest}],
    }


def test_imports_exact_cohort_to_opaque_public_bundle(tmp_path: Path) -> None:
    script = _load_script()
    source = write_current_expert_trace(tmp_path / "source.jsonl")
    trace_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = tmp_path / "cohort.json"
    manifest.write_text(json.dumps(_manifest(source, trace_digest)))
    key = tmp_path / "origin.key"
    key.write_bytes(b"0123456789abcdef0123456789abcdef")
    dataset = tmp_path / "bundle/expert.jsonl"
    report = tmp_path / "bundle/report.json"

    result = script.import_expert_cohort(manifest, key, dataset, report)

    trajectories = read_expert_trajectories(dataset)
    report_data = json.loads(report.read_text())
    assert result["runs"] == 1
    assert result["decisions"] == 3
    assert result["tensor_unsupported_decisions"] == 0
    assert (
        report_data["dataset_sha256"]
        == hashlib.sha256(dataset.read_bytes()).hexdigest()
    )
    assert report_data["capture_protocol_digest"] == (
        trajectories[0].capture.protocol_digest
    )
    assert trajectories[0].run_group.startswith("origin-")
    assert trace_digest not in dataset.read_text()
    assert "PRIVATE-SOURCE-SEED" not in dataset.read_text()
    assert "private-command" not in dataset.read_text()

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        script.import_expert_cohort(manifest, key, dataset, report)


def test_imports_current_real_balatro_pack_sale_to_choice_trace(
    tmp_path: Path,
) -> None:
    script = _load_script()
    digest = hashlib.sha256(_CURRENT_ORGANIC_TRACE.read_bytes()).hexdigest()
    manifest = tmp_path / "cohort.json"
    manifest.write_text(json.dumps(_manifest(_CURRENT_ORGANIC_TRACE, digest)))
    key = tmp_path / "origin.key"
    key.write_bytes(b"real-organic-fixture-origin-key!!")
    dataset = tmp_path / "bundle/expert.jsonl"

    result = script.import_expert_cohort(
        manifest,
        key,
        dataset,
        tmp_path / "bundle/report.json",
    )

    trajectory = read_expert_trajectories(dataset)[0]
    action_names = [
        transition.action.__class__.__name__
        for transition in trajectory.transitions
    ]
    assert result == {
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "runs": 1,
        "decisions": 68,
        "tensor_unsupported_decisions": 0,
    }
    assert sum(
        current.startswith("Sell") and following == "ChoosePackCard"
        for current, following in zip(action_names, action_names[1:])
    ) == 5
    assert all(
        transition.before.round.most_played_hand is not None
        and transition.after.round.most_played_hand is not None
        for transition in trajectory.transitions
    )
    assert "2507" not in dataset.read_text()


def test_manifest_rejects_duplicate_keys_and_digest_mismatch(tmp_path: Path) -> None:
    script = _load_script()
    with pytest.raises(ValueError, match="duplicate JSON key"):
        script._load_manifest(
            b'{"schema_version":1,"schema_version":1,"cohort_nonce":"x",'
            b'"action_contract":"x","traces":[]}'
        )

    source = write_current_expert_trace(tmp_path / "source.jsonl")
    manifest = tmp_path / "cohort.json"
    manifest.write_text(json.dumps(_manifest(source, "0" * 64)))
    key = tmp_path / "origin.key"
    key.write_bytes(b"0123456789abcdef0123456789abcdef")
    with pytest.raises(ValueError, match="digest mismatch"):
        script.import_expert_cohort(
            manifest,
            key,
            tmp_path / "bundle/expert.jsonl",
            tmp_path / "bundle/report.json",
        )


def test_bundle_publish_rolls_back_first_file_when_second_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _load_script()
    dataset = tmp_path / "bundle/expert.jsonl"
    report = tmp_path / "bundle/report.json"

    def fail_publish(_source: Path, _target: Path) -> None:
        raise OSError("synthetic bundle publication failure")

    monkeypatch.setattr(script, "_rename_directory_noreplace", fail_publish)
    with pytest.raises(OSError, match="synthetic"):
        script._publish_bundle(dataset, b"dataset", report, b"report")

    assert not dataset.exists()
    assert not report.exists()


def test_semantic_duplicate_trace_with_different_whitespace_is_rejected(
    tmp_path: Path,
) -> None:
    script = _load_script()
    first = write_current_expert_trace(tmp_path / "first.jsonl")
    second = tmp_path / "second.jsonl"
    second.write_text(
        "\n".join(
            json.dumps(json.loads(line)) for line in first.read_text().splitlines()
        )
        + "\n"
    )
    assert first.read_bytes() != second.read_bytes()
    manifest_data = {
        "schema_version": 1,
        "cohort_nonce": "duplicate-attack",
        "action_contract": POLICY_ACTION_CONTRACT,
        "traces": [
            {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in (first, second)
        ],
    }
    manifest = tmp_path / "cohort.json"
    manifest.write_text(json.dumps(manifest_data))
    key = tmp_path / "origin.key"
    key.write_bytes(b"0123456789abcdef0123456789abcdef")

    with pytest.raises(ValueError, match="semantic source trace"):
        script.import_expert_cohort(
            manifest,
            key,
            tmp_path / "bundle/expert.jsonl",
            tmp_path / "bundle/report.json",
        )
    assert not (tmp_path / "bundle").exists()


def test_mixed_execution_protocols_publish_nothing(tmp_path: Path) -> None:
    script = _load_script()
    first = write_current_expert_trace(tmp_path / "first.jsonl", run_id="first")
    second = write_current_expert_trace(
        tmp_path / "second.jsonl",
        run_id="second",
        max_decisions=4,
    )
    manifest_data = {
        "schema_version": 1,
        "cohort_nonce": "mixed-protocol-attack",
        "action_contract": POLICY_ACTION_CONTRACT,
        "traces": [
            {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in (first, second)
        ],
    }
    manifest = tmp_path / "cohort.json"
    manifest.write_text(json.dumps(manifest_data))
    key = tmp_path / "origin.key"
    key.write_bytes(b"0123456789abcdef0123456789abcdef")

    with pytest.raises(ValueError, match="mixes capture protocols"):
        script.import_expert_cohort(
            manifest,
            key,
            tmp_path / "bundle/expert.jsonl",
            tmp_path / "bundle/report.json",
        )
    assert not (tmp_path / "bundle").exists()


def test_wide_candidate_row_is_preserved_and_reported_unsupported(
    tmp_path: Path,
) -> None:
    script = _load_script()
    source = write_current_expert_trace(tmp_path / "wide.jsonl", wide_hand=True)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = tmp_path / "cohort.json"
    manifest.write_text(json.dumps(_manifest(source, digest)))
    key = tmp_path / "origin.key"
    key.write_bytes(b"0123456789abcdef0123456789abcdef")
    dataset = tmp_path / "bundle/expert.jsonl"
    report = tmp_path / "bundle/report.json"

    result = script.import_expert_cohort(manifest, key, dataset, report)

    report_data = json.loads(report.read_text())
    stored = json.loads(dataset.read_text())
    assert result["tensor_unsupported_decisions"] == 1
    assert report_data["maximum_candidate_actions"] > 512
    assert (
        len(stored["transitions"][0]["candidates"])
        == (report_data["maximum_candidate_actions"])
    )


def test_resource_overflow_publishes_nothing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = _load_script()
    source = write_current_expert_trace(tmp_path / "source.jsonl")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = tmp_path / "cohort.json"
    manifest.write_text(json.dumps(_manifest(source, digest)))
    key = tmp_path / "origin.key"
    key.write_bytes(b"0123456789abcdef0123456789abcdef")
    monkeypatch.setattr(script, "_MAX_TRACE_BYTES", 1)

    with pytest.raises(ValueError, match="resource limit"):
        script.import_expert_cohort(
            manifest,
            key,
            tmp_path / "bundle/expert.jsonl",
            tmp_path / "bundle/report.json",
        )
    assert not (tmp_path / "bundle").exists()


def test_bounded_reader_rejects_before_reading_the_whole_file(
    tmp_path: Path,
) -> None:
    script = _load_script()
    oversized = tmp_path / "oversized.bin"
    with oversized.open("wb") as handle:
        handle.seek(1_000_000)
        handle.write(b"x")

    with pytest.raises(ValueError, match="resource limit"):
        script._read_bounded(oversized, 64, "test input")


def test_bundle_publish_never_replaces_existing_empty_directory(
    tmp_path: Path,
) -> None:
    script = _load_script()
    dataset = tmp_path / "bundle/expert.jsonl"
    report = tmp_path / "bundle/report.json"
    dataset.parent.mkdir()

    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        script._publish_bundle(dataset, b"dataset", report, b"report")

    assert list(dataset.parent.iterdir()) == []
