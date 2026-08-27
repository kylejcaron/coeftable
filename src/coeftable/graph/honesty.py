"""Statistics for honest metric-tree reporting.

Pure functions over level series. Nothing here knows about cards, graphs, or
HTML: a decomposition's credibility is arithmetic, and keeping it separate is
what makes it testable.
"""

from __future__ import annotations

import math
import statistics
import sys
from collections.abc import Sequence

from coeftable.errors import SpecError

RESIDUAL_WARN = 0.005
RESIDUAL_FAIL = 0.20
TRADEOFF_R = -0.5

# Below this magnitude a positive double is subnormal and has lost most of
# its precision; a quotient landing here is not trustworthy even though it
# is a finite, positive float (see `_log_ratio`).
_MIN_NORMAL_RATIO = sys.float_info.min


def _levels(series: Sequence[float], *, name: str) -> tuple[float, ...]:
    """Snapshot a level series, rejecting values that make log ratios undefined."""
    values = tuple(float(value) for value in series)
    if len(values) < 3:
        raise SpecError(f"{name} must have at least 3 observations")
    for value in values:
        if not math.isfinite(value) or value <= 0.0:
            raise SpecError(f"{name} values must be finite and positive")
    return values


def _log_ratio(numerator: float, denominator: float) -> float:
    """Log of numerator/denominator, preferring the direct quotient.

    Subtracting two independently rounded logarithms introduces float noise
    on the order of 1e-16 even when the true ratio is exactly constant
    across a series - enough to make a perfectly steady series look like it
    has real variance. The direct quotient avoids that in the common case;
    fall back to subtracting logs when the quotient itself would overflow to
    infinity, underflow to zero, or land in subnormal range. The
    extreme-magnitude case (e.g. 1e-300 over 1e300) needs the overflow/
    underflow fallback to stay finite; a subnormal quotient (e.g. the
    smallest subnormal divided by 1.5, which rounds right back to itself)
    needs the same fallback because it has too few significant bits left to
    trust - dividing the logs instead stays accurate.
    """
    ratio = numerator / denominator
    if ratio >= _MIN_NORMAL_RATIO and math.isfinite(ratio):
        return math.log(ratio)
    return math.log(numerator) - math.log(denominator)


def weekly_log_changes(series: Sequence[float]) -> tuple[float, ...]:
    """Successive log ratios, the scale on which multiplicative noise is additive."""
    values = _levels(series, name="series")
    return tuple(_log_ratio(values[index + 1], values[index]) for index in range(len(values) - 1))


def level_noise(series: Sequence[float]) -> float:
    """Per-level noise: a change's deviation spans two levels, hence the sqrt(2)."""
    return statistics.stdev(weekly_log_changes(series)) / math.sqrt(2.0)


def _overflow_error(magnitude: float, *, purpose: str) -> SpecError:
    """Build the shared "too many orders of magnitude" error."""
    return SpecError(
        f"a log magnitude of {magnitude!r} spans too many orders of magnitude "
        f"to express as {purpose}"
    )


def _guarded_exp(exponent: float, *, purpose: str) -> float:
    """exp(), refusing to silently overflow into infinity.

    Validation only rejects non-finite levels, so `exponent` reaching here is
    always finite - but exp() of a large-magnitude log change or noise band
    can overflow float range before it becomes a percentage or a ribbon
    factor. Before log ratios were made overflow-safe, that overflow became
    an infinite quotient and callers silently returned infinite bounds; an
    infinite answer isn't useful for a report, so refuse explicitly instead.
    """
    try:
        return math.exp(exponent)
    except OverflowError as exc:
        raise _overflow_error(exponent, purpose=purpose) from exc


def _percent(log_change: float) -> float:
    """Convert a log change to a percentage, refusing an infinite answer.

    `_guarded_exp` only catches the exponential itself overflowing; the
    subsequent scale-by-100 can still push an already-huge-but-finite
    exponential past float range (e.g. exp() near 1e307), which would
    otherwise return infinity silently instead of raising.
    """
    purpose = "a percentage change"
    percent = 100.0 * (_guarded_exp(log_change, purpose=purpose) - 1.0)
    if not math.isfinite(percent):
        raise _overflow_error(log_change, purpose=purpose)
    return percent


def endpoint_interval(series: Sequence[float]) -> tuple[float, float, float]:
    """Percent change first-to-last with its +/-2 sigma band, as percentages.

    The band is 2*stdev(changes), not 2*level_noise: the endpoint comparison
    carries the noise of both endpoints.
    """
    values = _levels(series, name="series")
    changes = weekly_log_changes(values)
    band = 2.0 * statistics.stdev(changes)
    total = _log_ratio(values[-1], values[0])
    return (
        _percent(total),
        _percent(total - band),
        _percent(total + band),
    )


def ribbon_bounds(
    series: Sequence[float],
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Multiplicative +/-2 sigma bounds around each observed level."""
    values = _levels(series, name="series")
    sigma = level_noise(values)
    factor = _guarded_exp(2.0 * sigma, purpose="a +/-2 sigma ribbon")
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


# A relative-only tolerance fails for changes whose true magnitude is itself
# tiny (e.g. a geometric ratio a hair above 1): the allowed spread shrinks
# along with the changes, while the float noise from independently rounded
# divisions and logarithms stays a fixed ~1e-16 regardless of scale. The
# absolute floor catches that noise; it's far below any change size a real
# report would ever treat as meaningful.
_CONSTANT_CHANGE_ABS_TOL = 1e-12
_CONSTANT_CHANGE_REL_TOL = 1e-9


def _is_effectively_constant(values: Sequence[float]) -> bool:
    """Report whether a change series has no real variation, only rounding noise.

    An exact `len(set(values)) == 1` check is wrong here: even with the
    overflow-safe quotient in `_log_ratio`, floating-point division and
    logarithms are not perfectly associative, so a genuinely constant-ratio
    series can still produce a handful of changes that differ by ~1e-16.
    Comparing the spread of the changes to a tolerance combining a relative
    term - so noise is judged against the changes' own magnitude when that
    magnitude is large - with an absolute floor - so noise is still caught
    when the changes themselves are already tiny - treats float-epsilon-scale
    noise as "no variation" at every scale, while any variation of a real
    size still counts.
    """
    spread = max(values) - min(values)
    scale = max(abs(value) for value in values)
    return spread <= _CONSTANT_CHANGE_ABS_TOL + _CONSTANT_CHANGE_REL_TOL * scale


def tradeoff_pairs(
    named: Sequence[tuple[str, Sequence[float]]],
) -> tuple[tuple[str, str, float], ...]:
    """Sibling pairs whose week-to-week changes move strongly against each other.

    Correlating changes rather than levels is deliberate: two rising series are
    trivially correlated in level while their movements may be unrelated. A
    perfectly steady sibling has (up to float noise) zero variance in its
    changes; statistics.correlation is undefined for it, so it is skipped
    rather than treated as an error - every other pair is still evaluated
    normally.
    """
    all_changes = [(name, weekly_log_changes(series)) for name, series in named]
    changes = [
        (name, series_changes)
        for name, series_changes in all_changes
        if not _is_effectively_constant(series_changes)
    ]
    found: list[tuple[str, str, float]] = []
    for index, (left_name, left) in enumerate(changes):
        for right_name, right in changes[index + 1 :]:
            correlation = statistics.correlation(left, right)
            if correlation < TRADEOFF_R:
                found.append((left_name, right_name, correlation))
    return tuple(found)
