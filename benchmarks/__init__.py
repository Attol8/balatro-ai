"""Offline benchmark builder for the recorded Balatro evidence.

Every number this package reports is read from a file under ``evidence/``:

* ``evidence/baselines/<run>/{manifest.json,summary.json}`` -- twelve panels of
  non-LLM heuristic policies played on the real game (Red Deck / White Stake).
* ``evidence/first-win/`` -- the Astra-high coached win on seed ``D0001000``
  (``result.json``, ``scoring-audit.json``, ``trajectory.jsonl.gz``).
* ``evidence/astra-low-2K9H9HN/`` -- the supervised Astra-low run, stored as
  ordered segments listed in ``segments.json``.

Nothing here talks to the game; the builder is pure file reading plus rendering.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_ROOT = REPO_ROOT / "evidence"
DEFAULT_OUTPUT = REPO_ROOT / "benchmarks" / "results"

SETTING = "Red Deck / White Stake / all unlocked"
FULL_PANEL_SIZE = 20

__all__ = [
    "DEFAULT_OUTPUT",
    "EVIDENCE_ROOT",
    "FULL_PANEL_SIZE",
    "REPO_ROOT",
    "SETTING",
]
