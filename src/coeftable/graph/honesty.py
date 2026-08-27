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
# is a finite, positive float (see `log_ratio`).
_MIN_NORMAL_RATIO = sys.float_info.min


def _levels(series: Sequence[float], *, name: str) -> tuple[float, ...]:
    """Snapshot a level series, rejecting values that make log ratios undefined."""
    try:
        values = tuple(float(value) for value in series)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpecError(f"{name} values must be finite numbers") from exc
    if len(values) < 3:
        raise SpecError(f"{name} must have at least 3 observations")
    for value in values:
        if not math.isfinite(value) or value <= 0.0:
            raise SpecError(f"{name} values must be finite and positive")
    return values


def log_ratio(numerator: float, denominator: float) -> float:
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
    trust - subtracting the logs instead stays accurate. Any input that
    can't yield a finite ratio at all - division by zero, an integer pair
    too large for a machine float, a value outside log()'s domain, a NaN -
    raises SpecError instead of a raw arithmetic exception or a silent NaN.
    """
    try:
        ratio = numerator / denominator
    except (TypeError, ZeroDivisionError, OverflowError) as exc:
        raise SpecError("log ratio requires two finite, positive numbers") from exc
    if ratio >= _MIN_NORMAL_RATIO and math.isfinite(ratio):
        return math.log(ratio)
    try:
        result = math.log(numerator) - math.log(denominator)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpecError("log ratio requires two finite, positive numbers") from exc
    if not math.isfinite(result):
        raise SpecError("log ratio requires two finite, positive numbers")
    return result


def weekly_log_changes(series: Sequence[float]) -> tuple[float, ...]:
    """Successive log ratios, the scale on which multiplicative noise is additive."""
    values = _levels(series, name="series")
    return tuple(log_ratio(values[index + 1], values[index]) for index in range(len(values) - 1))


def level_noise(series: Sequence[float]) -> float:
    """Per-level noise: a change's deviation spans two levels, hence the sqrt(2)."""
    return statistics.stdev(weekly_log_changes(series)) / math.sqrt(2.0)


def _overflow_error(magnitude: float, *, purpose: str) -> SpecError:
    """Build the shared "too many orders of magnitude" error."""
    return SpecError(
        f"a magnitude of {magnitude!r} spans too many orders of magnitude to express as {purpose}"
    )


def _require_finite(values: Sequence[float], *, magnitude: float, purpose: str) -> None:
    """Raise the shared overflow error unless every completed value is finite.

    Every guard in this module up to this point protects an intermediate
    step (an exponential, a factor), but a later scale, multiply, or sum can
    still push an already-huge-but-finite intermediate past float range.
    This checks the value actually about to be returned, not just the step
    that most often overflows. `magnitude` is the input driving the
    computation, since the overflowed result itself isn't useful to report.
    """
    if not all(math.isfinite(value) for value in values):
        raise _overflow_error(magnitude, purpose=purpose)


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
    _require_finite((percent,), magnitude=log_change, purpose=purpose)
    return percent


def endpoint_interval(series: Sequence[float]) -> tuple[float, float, float]:
    """Percent change first-to-last with its +/-2 sigma band, as percentages.

    The band is 2*stdev(changes), not 2*level_noise: the endpoint comparison
    carries the noise of both endpoints.
    """
    values = _levels(series, name="series")
    changes = weekly_log_changes(values)
    band = 2.0 * statistics.stdev(changes)
    total = log_ratio(values[-1], values[0])
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
    purpose = "a +/-2 sigma ribbon"
    factor = _guarded_exp(2.0 * sigma, purpose=purpose)
    lower = tuple(value / factor for value in values)
    upper = tuple(value * factor for value in values)
    _require_finite((*lower, *upper), magnitude=2.0 * sigma, purpose=purpose)
    return (lower, upper)


def ribbon_domain(
    series: Sequence[float],
    lower: Sequence[float],
    upper: Sequence[float],
) -> tuple[float, float]:
    """Pad the ribbon extent by a tenth of the series span.

    A flat series has zero span, which would collapse the domain; fall back to
    the level's own magnitude, then to 1.0 for a flat-at-zero series. Even
    that fallback pad can underflow to zero against a subnormal-magnitude
    flat series (or round away entirely against a near-max one), so an
    endpoint the padding fails to move is nudged apart with
    `math.nextafter` instead - the returned domain is never degenerate.
    """
    try:
        values = tuple(float(value) for value in series)
        lower_values = tuple(float(value) for value in lower)
        upper_values = tuple(float(value) for value in upper)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpecError("ribbon domain values must be finite numbers") from exc
    if not (values and lower_values and upper_values):
        raise SpecError("ribbon domain requires at least one observation")
    for value in (*values, *lower_values, *upper_values):
        if not math.isfinite(value):
            raise SpecError("ribbon domain values must be finite")
    span = (max(values) - min(values)) or abs(max(values)) or 1.0
    raw_lo = min(lower_values)
    raw_hi = max(upper_values)
    pad = 0.1 * span
    lo = raw_lo - pad
    hi = raw_hi + pad
    if lo == raw_lo:
        lo = math.nextafter(raw_lo, -math.inf)
    if hi == raw_hi:
        hi = math.nextafter(raw_hi, math.inf)
    _require_finite((lo, hi), magnitude=span, purpose="a ribbon domain")
    return (lo, hi)


def _combine_column(column: tuple[float, ...], op: str) -> float:
    """Sum or multiply one pointwise column, refusing an out-of-range result.

    `math.fsum` itself raises `OverflowError` when a finite-input sum can't
    fit in float range; `math.prod` instead returns infinity silently. Both
    are folded into the module's own overflow error so neither leaks past
    this module or returns a non-finite series silently.
    """
    purpose = "an implied series"
    magnitude = max(abs(value) for value in column)
    try:
        combined = math.fsum(column) if op == "+" else math.prod(column)
    except OverflowError as exc:
        raise _overflow_error(magnitude, purpose=purpose) from exc
    _require_finite((combined,), magnitude=magnitude, purpose=purpose)
    return combined


def implied_series(children: Sequence[Sequence[float]], op: str) -> tuple[float, ...]:
    """Combine children pointwise under the decomposition's operator.

    Children are normalized to float before combining: leaving an integer
    column unconverted lets it stay arbitrary-precision through the
    multiply/sum, so a later `math.isfinite` on an out-of-float-range int
    result raises `OverflowError` instead of this function returning
    cleanly or raising `SpecError` like every other overflow here does.
    """
    if op not in ("+", "x"):
        raise SpecError("decomposition op must be '+' or 'x'")
    if not children:
        raise SpecError("decomposition must have at least one child")
    lengths = {len(child) for child in children}
    if len(lengths) != 1:
        # zip(strict=True) would raise ValueError here; report our own error type.
        raise SpecError("decomposition children must all have the same length")
    try:
        normalized = [tuple(float(value) for value in child) for child in children]
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpecError("decomposition children values must be finite numbers") from exc
    for child in normalized:
        if not all(math.isfinite(value) for value in child):
            raise SpecError("decomposition children values must be finite numbers")
    columns = zip(*normalized, strict=True)
    return tuple(_combine_column(tuple(column), op) for column in columns)


def identity_gap(parent: Sequence[float], children: Sequence[Sequence[float]], op: str) -> float:
    """Mean relative discrepancy between a parent and its combined children."""
    try:
        values = tuple(float(value) for value in parent)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpecError("decomposition parent values must be finite numbers") from exc
    if not values:
        raise SpecError("decomposition parent must have at least one value")
    implied = implied_series(children, op)
    if len(implied) != len(values):
        raise SpecError("decomposition children must match the parent's length")
    for value in values:
        if not math.isfinite(value) or value == 0.0:
            raise SpecError("decomposition parent values must be finite and non-zero")
    purpose = "a decomposition's identity gap"
    magnitude = max(abs(value) for value in values)
    try:
        gap = math.fsum(
            abs(value - other) / abs(value) for value, other in zip(values, implied, strict=True)
        ) / len(values)
    except OverflowError as exc:
        raise _overflow_error(magnitude, purpose=purpose) from exc
    _require_finite((gap,), magnitude=magnitude, purpose=purpose)
    return gap


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
    overflow-safe quotient in `log_ratio`, floating-point division and
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
    lengths = {len(series_changes) for _, series_changes in all_changes}
    if len(lengths) > 1:
        raise SpecError("sibling series must all have the same length")
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
