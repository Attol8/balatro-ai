from __future__ import annotations

import pytest

from balatro_ai_v2.evaluation_protocol import (
    MAX_SEED,
    PanelValidationError,
    validate_seed_panel,
)


def test_registered_tuning_and_gate_panels_are_exact() -> None:
    tuning = validate_seed_panel(1, 200, "tuning")
    gate = validate_seed_panel(701, 200, "gate")

    assert (tuning.start, tuning.end, tuning.verification) == (
        1,
        200,
        "registry_verified",
    )
    assert (gate.start, gate.end, gate.verification) == (
        701,
        900,
        "registry_verified",
    )


@pytest.mark.parametrize(
    ("start", "count", "provenance"),
    [
        (1, 199, "tuning"),
        (2, 200, "tuning"),
        (701, 199, "gate"),
        (702, 200, "gate"),
        (701, 200, "tuning"),
        (1, 200, "gate"),
        (1, 200, "development"),
        (700, 2, "development"),
        (900, 2, "development"),
    ],
)
def test_partial_mislabeled_and_overlapping_panels_fail_closed(
    start: int, count: int, provenance: str
) -> None:
    with pytest.raises(PanelValidationError):
        validate_seed_panel(start, count, provenance)


@pytest.mark.parametrize("provenance", ("development", "tuning", "gate"))
def test_former_501_panel_is_quarantined(provenance: str) -> None:
    with pytest.raises(PanelValidationError):
        validate_seed_panel(501, 200, provenance)


@pytest.mark.parametrize(
    ("start", "count"),
    [(True, 1), (1, True), (0, 1), (1, 0), (-1, 1), (1, -1), (MAX_SEED, 2)],
)
def test_invalid_types_bounds_and_overflow_are_rejected(start: int, count: int) -> None:
    with pytest.raises(PanelValidationError):
        validate_seed_panel(start, count, "development")


def test_evaluator_secret_is_explicitly_external_and_unverifiable() -> None:
    panel = validate_seed_panel(1, 200, "evaluator_secret")

    assert panel.verification == "external_unverifiable"
