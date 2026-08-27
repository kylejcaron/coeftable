"""Statistics for honest metric-tree reporting.

Pure functions over level series. Nothing here knows about cards, graphs, or
HTML: a decomposition's credibility is arithmetic, and keeping it separate is
what makes it testable.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

from coeftable.errors import SpecError

RESIDUAL_WARN = 0.005
RESIDUAL_FAIL = 0.20
TRADEOFF_R = -0.5


def _levels(series: Sequence[float], *, name: str) -> tuple[float, ...]:
    """Snapshot a level series, rejecting values that make log ratios undefined."""
    values = tuple(float(value) for value in series)
    if len(values) < 3:
        raise SpecError(f"{name} must have at least 3 observations")
    for value in values:
        if not math.isfinite(value) or value <= 0.0:
            raise SpecError(f"{name} values must be finite and positive")
    return values


def weekly_log_changes(series: Sequence[float]) -> tuple[float, ...]:
    """Successive log ratios, the scale on which multiplicative noise is additive."""
    values = _levels(series, name="series")
    return tuple(math.log(values[index + 1] / values[index]) for index in range(len(values) - 1))


def level_noise(series: Sequence[float]) -> float:
    """Per-level noise: a change's deviation spans two levels, hence the sqrt(2)."""
    return statistics.stdev(weekly_log_changes(series)) / math.sqrt(2.0)


def endpoint_interval(series: Sequence[float]) -> tuple[float, float, float]:
    """Percent change first-to-last with its +/-2 sigma band, as percentages.

    The band is 2*stdev(changes), not 2*level_noise: the endpoint comparison
    carries the noise of both endpoints.
    """
    values = _levels(series, name="series")
    changes = weekly_log_changes(values)
    band = 2.0 * statistics.stdev(changes)
    total = math.log(values[-1] / values[0])
    return (
        100.0 * (math.exp(total) - 1.0),
        100.0 * (math.exp(total - band) - 1.0),
        100.0 * (math.exp(total + band) - 1.0),
    )


def ribbon_bounds(
    series: Sequence[float],
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Multiplicative +/-2 sigma bounds around each observed level."""
    values = _levels(series, name="series")
    sigma = level_noise(values)
    factor = math.exp(2.0 * sigma)
    return (
        tuple(value / factor for value in values),
        tuple(value * factor for value in values),
    )


def ribbon_domain(
    series: Sequence[float],
    lower: Sequence[float],
    upper: Sequence[float],
) -> tuple[float, float]:
    """Pad the ribbon extent by a tenth of the series span.

    A flat series has zero span, which would collapse the domain; fall back to
    the level's own magnitude, then to 1.0 for a flat-at-zero series.
    """
    values = tuple(float(value) for value in series)
    span = (max(values) - min(values)) or abs(max(values)) or 1.0
    return (min(lower) - 0.1 * span, max(upper) + 0.1 * span)


def implied_series(children: Sequence[Sequence[float]], op: str) -> tuple[float, ...]:
    """Combine children pointwise under the decomposition's operator."""
    if op not in ("+", "x"):
        raise SpecError("decomposition op must be '+' or 'x'")
    if not children:
        raise SpecError("decomposition must have at least one child")
    lengths = {len(child) for child in children}
    if len(lengths) != 1:
        # zip(strict=True) would raise ValueError here; report our own error type.
        raise SpecError("decomposition children must all have the same length")
    columns = zip(*children, strict=True)
    if op == "+":
        return tuple(math.fsum(column) for column in columns)
    return tuple(math.prod(column) for column in columns)


def identity_gap(parent: Sequence[float], children: Sequence[Sequence[float]], op: str) -> float:
    """Mean relative discrepancy between a parent and its combined children."""
    values = tuple(float(value) for value in parent)
    implied = implied_series(children, op)
    if len(implied) != len(values):
        raise SpecError("decomposition children must match the parent's length")
    for value in values:
        if value == 0.0:
            raise SpecError("decomposition parent values must be non-zero")
    return math.fsum(
        abs(value - other) / abs(value) for value, other in zip(values, implied, strict=True)
    ) / len(values)


def tradeoff_pairs(
    named: Sequence[tuple[str, Sequence[float]]],
) -> tuple[tuple[str, str, float], ...]:
    """Sibling pairs whose week-to-week changes move strongly against each other.

    Correlating changes rather than levels is deliberate: two rising series are
    trivially correlated in level while their movements may be unrelated.
    """
    changes = [(name, weekly_log_changes(series)) for name, series in named]
    for name, series in changes:
        if len(set(series)) == 1:
            # A perfectly steady series has zero variance; statistics.correlation
            # raises StatisticsError on it. Refuse with our own error type.
            raise SpecError(f"{name} has no week-to-week variation to correlate")
    found: list[tuple[str, str, float]] = []
    for index, (left_name, left) in enumerate(changes):
        for right_name, right in changes[index + 1 :]:
            correlation = statistics.correlation(left, right)
            if correlation < TRADEOFF_R:
                found.append((left_name, right_name, correlation))
    return tuple(found)
