from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_authority_snapshots.py"
    spec = importlib.util.spec_from_file_location("benchmark_authority_snapshots_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snapshot_benchmark_requires_provenance_and_keeps_blob_ephemeral() -> None:
    script = _load_script()
    parser = script.build_parser()

    args = parser.parse_args(
        [
            "--balatrobot-version",
            "bb",
            "--game-version",
            "game",
            "--runtime-version",
            "runtime",
            "--mod",
            "balatrobot@digest",
        ]
    )

    assert args.depth == 8
    assert args.repeats == 5
    assert args.protocol == "file"
    assert not hasattr(args, "snapshot_path")
