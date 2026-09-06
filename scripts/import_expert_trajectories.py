#!/usr/bin/env python3
"""Import a preregistered authority cohort into public-only expert JSONL."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from balatro_ai_v2.actions import action_to_data
from balatro_ai_v2.balatrobot.tracing import read_verified_trace_bytes
from balatro_ai_v2.expert_trajectory import (
    EXPERT_MAX_EXACT_ACTIONS,
    EXPERT_MAX_TRACE_CANDIDATES,
    EXPERT_MODEL_MAX_ACTIONS,
    EXPERT_TRAJECTORY_SCHEMA_VERSION,
    ExpertBehaviorExample,
    ExpertTrajectory,
    expert_trajectories_bytes,
    materialize_behavior_examples,
    trajectory_from_authority_trace,
)
from balatro_ai_v2.policy_wire import POLICY_ACTION_CONTRACT
from balatro_ai_v2.strategy_model import PublicStrategyTensorizer

EXPERT_COHORT_MANIFEST_SCHEMA_VERSION = 1
EXPERT_IMPORT_REPORT_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAX_COHORT_TRACES = 2_048
_MAX_COHORT_MANIFEST_BYTES = 1 * 1024 * 1024
_MAX_ORIGIN_KEY_BYTES = 4 * 1024
_MAX_TRACE_BYTES = 32 * 1024 * 1024
_MAX_COHORT_SOURCE_BYTES = 512 * 1024 * 1024
_MAX_COHORT_DECISIONS = 100_000
_MAX_COHORT_CANDIDATES = EXPERT_MAX_TRACE_CANDIDATES
_MAX_DATASET_BYTES = 256 * 1024 * 1024


def main() -> None:
    args = build_parser().parse_args()
    result = import_expert_cohort(
        args.cohort_manifest,
        args.origin_key_file,
        args.output_jsonl,
        args.output_report,
    )
    print(json.dumps(result, sort_keys=True))


def import_expert_cohort(
    cohort_manifest_path: Path,
    origin_key_path: Path,
    output_jsonl: Path,
    output_report: Path,
) -> dict[str, object]:
    if output_jsonl == output_report:
        raise ValueError("expert dataset and report paths must differ")
    output_directory = output_jsonl.parent.resolve()
    if output_report.parent.resolve() != output_directory:
        raise ValueError("expert outputs must share one bundle directory")
    if output_directory.exists():
        raise FileExistsError("refusing to overwrite expert output bundle")

    manifest_bytes = _read_bounded(
        cohort_manifest_path,
        _MAX_COHORT_MANIFEST_BYTES,
        "expert cohort manifest",
    )
    manifest = _load_manifest(manifest_bytes)
    origin_key = _read_bounded(
        origin_key_path,
        _MAX_ORIGIN_KEY_BYTES,
        "expert origin key",
    )
    if len(origin_key) < 32:
        raise ValueError("expert origin key must contain at least 32 bytes")

    entries = manifest["traces"]
    assert isinstance(entries, list)
    trajectories: list[ExpertTrajectory] = []
    trace_digests: set[str] = set()
    normalized_trace_digests: set[str] = set()
    source_run_ids: set[str] = set()
    terminal_row_hashes: set[str] = set()
    resolved_paths: set[Path] = set()
    source_bytes_total = 0
    decision_total = 0
    candidate_total = 0
    with tempfile.TemporaryDirectory(prefix="expert-import-") as temporary_dir:
        temporary_root = Path(temporary_dir)
        for index, entry in enumerate(entries):
            assert isinstance(entry, dict)
            expected_digest = str(entry["sha256"])
            source_path = Path(str(entry["path"]))
            if not source_path.is_absolute():
                source_path = cohort_manifest_path.parent / source_path
            source_path = source_path.resolve()
            if source_path in resolved_paths or expected_digest in trace_digests:
                raise ValueError("expert cohort repeats a source trace")
            resolved_paths.add(source_path)
            trace_digests.add(expected_digest)
            source_bytes = _read_bounded(
                source_path,
                _MAX_TRACE_BYTES,
                "expert source trace",
            )
            source_bytes_total += len(source_bytes)
            if source_bytes_total > _MAX_COHORT_SOURCE_BYTES:
                raise ValueError("expert cohort exceeds the source-byte resource limit")
            actual_digest = hashlib.sha256(source_bytes).hexdigest()
            if actual_digest != expected_digest:
                raise ValueError("expert source trace digest mismatch")
            verified_rows = read_verified_trace_bytes(source_bytes)
            source_run_id = str(verified_rows[0]["run_id"])
            terminal_row_hash = str(verified_rows[-1]["row_hash"])
            normalized_digest = _normalized_trace_digest(verified_rows)
            if (
                source_run_id in source_run_ids
                or terminal_row_hash in terminal_row_hashes
                or normalized_digest in normalized_trace_digests
            ):
                raise ValueError("expert cohort repeats a semantic source trace")
            source_run_ids.add(source_run_id)
            terminal_row_hashes.add(terminal_row_hash)
            normalized_trace_digests.add(normalized_digest)

            # Parse the exact bytes that were hashed, even if the source path is
            # concurrently replaced after the single trusted read.
            snapshot_path = temporary_root / f"trace-{index}.jsonl"
            snapshot_path.write_bytes(source_bytes)
            run_group = (
                "origin-"
                + hmac.new(
                    origin_key,
                    bytes.fromhex(normalized_digest),
                    hashlib.sha256,
                ).hexdigest()[:32]
            )
            trajectory = trajectory_from_authority_trace(
                snapshot_path, run_group=run_group
            )
            trajectories.append(trajectory)
            decision_total += len(trajectory.transitions)
            candidate_total += sum(
                len(transition.candidates) for transition in trajectory.transitions
            )
            if decision_total > _MAX_COHORT_DECISIONS:
                raise ValueError("expert cohort exceeds the decision resource limit")
            if candidate_total > _MAX_COHORT_CANDIDATES:
                raise ValueError("expert cohort exceeds the candidate resource limit")

    admitted = tuple(trajectories)
    protocols = {trajectory.capture.protocol_digest for trajectory in admitted}
    if len(protocols) != 1:
        raise ValueError("expert cohort mixes capture protocols")
    dataset_chunks: list[bytes] = []
    dataset_size = 0
    for trajectory in admitted:
        chunk = expert_trajectories_bytes((trajectory,))
        dataset_size += len(chunk)
        if dataset_size > _MAX_DATASET_BYTES:
            raise ValueError("expert dataset exceeds the output resource limit")
        dataset_chunks.append(chunk)
    dataset_bytes = b"".join(dataset_chunks)
    dataset_digest = hashlib.sha256(dataset_bytes).hexdigest()
    examples = materialize_behavior_examples(admitted)
    unsupported = tuple(example for example in examples if not example.tensor_supported)
    _verify_tensorization(
        tuple(example for example in examples if example.tensor_supported)
    )
    action_counts = Counter(
        str(action_to_data(transition.action)["type"])
        for trajectory in admitted
        for transition in trajectory.transitions
    )
    phase_counts = Counter(
        transition.before.phase.value
        for trajectory in admitted
        for transition in trajectory.transitions
    )
    report: dict[str, object] = {
        "schema_version": EXPERT_IMPORT_REPORT_SCHEMA_VERSION,
        "trajectory_schema_version": EXPERT_TRAJECTORY_SCHEMA_VERSION,
        "action_contract": POLICY_ACTION_CONTRACT,
        "cohort_nonce": manifest["cohort_nonce"],
        "cohort_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "capture_protocol_digest": next(iter(protocols)),
        "dataset_sha256": dataset_digest,
        "runs": len(admitted),
        "decisions": len(examples),
        "wins": sum(trajectory.won for trajectory in admitted),
        "censored_runs": sum(
            trajectory.long_horizon_censored for trajectory in admitted
        ),
        "tensor_action_limit": EXPERT_MODEL_MAX_ACTIONS,
        "tensor_supported_decisions": len(examples) - len(unsupported),
        "tensor_unsupported_decisions": len(unsupported),
        "maximum_candidate_actions": max(
            len(example.candidates) for example in examples
        ),
        "resource_limits": {
            "maximum_traces": _MAX_COHORT_TRACES,
            "maximum_manifest_bytes": _MAX_COHORT_MANIFEST_BYTES,
            "maximum_origin_key_bytes": _MAX_ORIGIN_KEY_BYTES,
            "maximum_trace_bytes": _MAX_TRACE_BYTES,
            "maximum_cohort_source_bytes": _MAX_COHORT_SOURCE_BYTES,
            "maximum_cohort_decisions": _MAX_COHORT_DECISIONS,
            "maximum_cohort_candidates": _MAX_COHORT_CANDIDATES,
            "maximum_exact_actions_per_decision": EXPERT_MAX_EXACT_ACTIONS,
            "maximum_dataset_bytes": _MAX_DATASET_BYTES,
        },
        "action_counts": dict(sorted(action_counts.items())),
        "phase_counts": dict(sorted(phase_counts.items())),
    }
    report_bytes = (
        json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    _publish_bundle(output_jsonl, dataset_bytes, output_report, report_bytes)
    return {
        "dataset_sha256": dataset_digest,
        "runs": len(admitted),
        "decisions": len(examples),
        "tensor_unsupported_decisions": len(unsupported),
    }


def _load_manifest(raw: bytes) -> dict[str, object]:
    try:
        manifest = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("expert cohort manifest is invalid JSON") from exc
    fields = {"schema_version", "cohort_nonce", "action_contract", "traces"}
    if not isinstance(manifest, dict) or set(manifest) != fields:
        raise ValueError("expert cohort manifest has invalid fields")
    if manifest["schema_version"] != EXPERT_COHORT_MANIFEST_SCHEMA_VERSION:
        raise ValueError("expert cohort manifest schema is unsupported")
    if manifest["action_contract"] != POLICY_ACTION_CONTRACT:
        raise ValueError("expert cohort action contract is unsupported")
    nonce = manifest["cohort_nonce"]
    if not isinstance(nonce, str) or not nonce or len(nonce) > 160:
        raise ValueError("expert cohort nonce is invalid")
    entries = manifest["traces"]
    if not isinstance(entries, list) or not entries:
        raise ValueError("expert cohort must name at least one trace")
    if len(entries) > _MAX_COHORT_TRACES:
        raise ValueError("expert cohort exceeds the trace resource limit")
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise ValueError("expert cohort trace entry has invalid fields")
        if not isinstance(entry["path"], str) or not entry["path"]:
            raise ValueError("expert cohort trace path is invalid")
        if (
            not isinstance(entry["sha256"], str)
            or _SHA256.fullmatch(entry["sha256"]) is None
        ):
            raise ValueError("expert cohort trace digest is invalid")
    return manifest


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _read_bounded(path: Path, limit: int, label: str) -> bytes:
    with path.open("rb") as handle:
        payload = handle.read(limit + 1)
    if len(payload) > limit:
        raise ValueError(f"{label} exceeds the resource limit")
    return payload


def _publish_bundle(
    dataset_path: Path,
    dataset_bytes: bytes,
    report_path: Path,
    report_bytes: bytes,
) -> None:
    final_directory = dataset_path.parent.resolve()
    if report_path.parent.resolve() != final_directory:
        raise ValueError("expert outputs must share one bundle directory")
    if final_directory.exists():
        raise FileExistsError("refusing to overwrite expert output bundle")
    final_directory.parent.mkdir(parents=True, exist_ok=True)
    staged = Path(
        tempfile.mkdtemp(
            prefix=f".{final_directory.name}.",
            suffix=".tmp",
            dir=final_directory.parent,
        )
    )
    staged_dataset = staged / dataset_path.name
    staged_report = staged / report_path.name
    try:
        for target, payload in (
            (staged_dataset, dataset_bytes),
            (staged_report, report_bytes),
        ):
            with target.open("xb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        staged_descriptor = os.open(staged, os.O_RDONLY)
        try:
            os.fsync(staged_descriptor)
        finally:
            os.close(staged_descriptor)
        _rename_directory_noreplace(staged, final_directory)
        parent_descriptor = os.open(final_directory.parent, os.O_RDONLY)
        try:
            try:
                os.fsync(parent_descriptor)
            except OSError:
                # The complete bundle is already atomically visible. A parent
                # fsync failure may weaken crash durability but must not report
                # a failed import with a published bundle left behind.
                pass
        finally:
            os.close(parent_descriptor)
    except BaseException:
        staged_dataset.unlink(missing_ok=True)
        staged_report.unlink(missing_ok=True)
        try:
            staged.rmdir()
        except OSError:
            pass
        raise


def _rename_directory_noreplace(source: Path, target: Path) -> None:
    """Atomically publish a directory without replacing an existing target."""

    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(library, "renamex_np"):
        result = library.renamex_np(
            os.fsencode(source), os.fsencode(target), ctypes.c_uint(0x00000004)
        )
    elif sys.platform.startswith("linux") and hasattr(library, "renameat2"):
        result = library.renameat2(
            ctypes.c_int(-100),
            os.fsencode(source),
            ctypes.c_int(-100),
            os.fsencode(target),
            ctypes.c_uint(1),
        )
    else:
        if target.exists():
            raise FileExistsError("refusing to overwrite expert output bundle")
        os.rename(source, target)
        return
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in {errno.EEXIST, errno.ENOTEMPTY}:
        raise FileExistsError("refusing to overwrite expert output bundle")
    raise OSError(error, os.strerror(error), str(target))


def _normalized_trace_digest(rows: tuple[dict[str, object], ...]) -> str:
    payload = b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for row in rows
    )
    return hashlib.sha256(payload).hexdigest()


def _verify_tensorization(examples: tuple[ExpertBehaviorExample, ...]) -> None:
    tensorizer = PublicStrategyTensorizer()
    for example in examples:
        batch = tensorizer.tensorize(
            (example.observation,),
            (example.candidates,),
            (example.action_intents,),
            contexts=(example.context,),
            action_routes=(example.action_routes,),
        )
        batch.validate()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import verified authority traces into public expert JSONL"
    )
    parser.add_argument("--cohort-manifest", type=Path, required=True)
    parser.add_argument("--origin-key-file", type=Path, required=True)
    parser.add_argument("--output-jsonl", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    return parser


if __name__ == "__main__":
    main()
