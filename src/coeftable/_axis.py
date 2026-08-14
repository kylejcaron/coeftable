"""Shared axis coercion helpers."""

from __future__ import annotations

import datetime
import math
from collections.abc import Iterable
from typing import Any

# Deliberately naive: paired with elapsed-time subtraction in _epoch_seconds
# so relative spacing never depends on the host machine's local timezone.
_EPOCH = datetime.datetime(1970, 1, 1)


def _epoch_seconds(value: datetime.date) -> float:
    """Convert a date/datetime to seconds since the Unix epoch.

    A timezone-aware `datetime` is converted to UTC first; a naive
    `datetime` (or a plain `date`, read as midnight) is measured as an
    elapsed-time delta from a naive epoch, never through
    `datetime.timestamp()` -- which reads a naive value against the host's
    *local* timezone and would make relative spacing depend on where the
    code runs.
    """
    if isinstance(value, datetime.datetime):
        if value.tzinfo is not None:
            value = value.astimezone(datetime.UTC).replace(tzinfo=None)
        return (value - _EPOCH).total_seconds()
    return (datetime.datetime(value.year, value.month, value.day) - _EPOCH).total_seconds()


def _detect_temporal(values: Iterable[Any]) -> bool:
    """Return True when the first non-missing value is a date or datetime."""
    for value in values:
        if value is not None:
            return isinstance(value, datetime.date)
    return False


def _coerce_temporal(values: Iterable[Any]) -> list[float | None]:
    """Coerce raw date/datetime values to epoch seconds, `None` for missing.

    A bare `None` is missing directly; pandas' `NaT` is not `None` but is
    still an `isinstance(..., datetime.datetime)` whose epoch delta
    degenerates to NaN rather than raising, so the result is checked for
    NaN too -- mirroring `coerce_numeric`'s own missing-value handling.
    """
    out: list[float | None] = []
    for value in values:
        if value is None:
            out.append(None)
            continue
        seconds = _epoch_seconds(value)
        out.append(None if math.isnan(seconds) else seconds)
    return out
