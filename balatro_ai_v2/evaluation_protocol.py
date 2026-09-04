"""Seed-panel registry for reproducible candidate evaluation.

The registry protects the tuning and final gate panels from accidental reuse or
mislabeling.  Evaluator-secret panels are owned by an external evaluator, so
their provenance can be recorded but cannot be verified by this repository.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal, cast


SeedProvenance = Literal["development", "tuning", "gate", "evaluator_secret"]
SEED_PROVENANCES: tuple[SeedProvenance, ...] = (
    "development",
    "tuning",
    "gate",
    "evaluator_secret",
)
MAX_SEED = (1 << 63) - 1

_TUNING_START = 1
_TUNING_COUNT = 200
_GATE_START = 701
_GATE_COUNT = 200
_PROTECTED = {
    "tuning": (_TUNING_START, _TUNING_START + _TUNING_COUNT - 1),
    "gate": (_GATE_START, _GATE_START + _GATE_COUNT - 1),
}
_QUARANTINED = {"former_gate": (501, 700)}


class PanelValidationError(ValueError):
    """A requested seed panel violates the evaluation registry."""


@dataclass(frozen=True, slots=True)
class SeedPanelValidation:
    """Validated, inclusive seed-panel bounds and their trust status."""

    start: int
    count: int
    end: int
    provenance: SeedProvenance
    verification: Literal["registry_verified", "external_unverifiable"]

    def as_dict(self) -> dict[str, int | str]:
        return asdict(self)


def validate_seed_panel(
    start: int,
    count: int,
    provenance: str,
) -> SeedPanelValidation:
    """Validate a contiguous panel against the central seed registry.

    ``evaluator_secret`` is deliberately accepted without checking its range:
    the external evaluator, not this repository, owns and verifies those seeds.
    """

    if isinstance(start, bool) or not isinstance(start, int) or start <= 0:
        raise PanelValidationError("seed panel start must be a positive integer")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise PanelValidationError("seed panel count must be a positive integer")
    if start > MAX_SEED or count > MAX_SEED - start + 1:
        raise PanelValidationError(f"seed panel exceeds maximum seed {MAX_SEED}")
    if provenance not in SEED_PROVENANCES:
        raise PanelValidationError(f"unknown seed provenance: {provenance!r}")

    end = start + count - 1
    typed_provenance = cast(SeedProvenance, provenance)
    if typed_provenance == "evaluator_secret":
        return SeedPanelValidation(
            start=start,
            count=count,
            end=end,
            provenance="evaluator_secret",
            verification="external_unverifiable",
        )

    if typed_provenance in _PROTECTED:
        required_start, required_end = _PROTECTED[typed_provenance]
        if (start, end) != (required_start, required_end):
            raise PanelValidationError(
                f"{typed_provenance} panel must be exactly seeds "
                f"{required_start}-{required_end}"
            )
    else:
        for label, (quarantined_start, quarantined_end) in _QUARANTINED.items():
            if start <= quarantined_end and end >= quarantined_start:
                raise PanelValidationError(
                    f"development panel overlaps quarantined {label} seeds "
                    f"{quarantined_start}-{quarantined_end}"
                )
        for label, (protected_start, protected_end) in _PROTECTED.items():
            if start <= protected_end and end >= protected_start:
                raise PanelValidationError(
                    f"development panel overlaps protected {label} seeds "
                    f"{protected_start}-{protected_end}"
                )

    return SeedPanelValidation(
        start=start,
        count=count,
        end=end,
        provenance=typed_provenance,
        verification="registry_verified",
    )
