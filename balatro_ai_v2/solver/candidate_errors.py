"""Fail-closed errors for public-only candidate reconstruction."""


class DeterminizationUnavailable(RuntimeError):
    """The public observation cannot safely construct a candidate root."""
