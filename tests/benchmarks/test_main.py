"""``python -m benchmarks`` writes the committed artefacts and repeats itself."""

from __future__ import annotations

from pathlib import Path

from benchmarks.__main__ import main


def test_cli_writes_stable_results(tmp_path: Path):
    assert main(["--out", str(tmp_path), "--no-figures"]) == 0
    first = {path.name: path.read_bytes() for path in sorted(tmp_path.iterdir())}
    assert set(first) == {"results.json", "results.md"}
    assert main(["--out", str(tmp_path), "--no-figures"]) == 0
    second = {path.name: path.read_bytes() for path in sorted(tmp_path.iterdir())}
    assert first == second


def test_cli_rejects_a_runs_directory_without_a_result(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["--out", str(tmp_path / "out"), "--no-figures", "--runs", str(empty)]) == 2
