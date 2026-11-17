"""Prepare equal-mass quantiles and reference-safe binned display positions."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import pairwise
from numbers import Real

from coeftable.errors import SpecError


@dataclass(frozen=True)
class DotValues:
    """Validated, ordered representatives with their original denominator."""

    quantiles: tuple[float, ...]
    dot_count: int | None


@dataclass(frozen=True)
class DotPosition:
    """One original representative and its binned display coordinate."""

    value: float
    x: float
    level: int


@dataclass(frozen=True)
class DotLayout:
    """Visible positions and counts excluded by the viewport."""

    dots: tuple[DotPosition, ...]
    dot_count: int | None
    below: int
    above: int
    levels: int


def prepare_dots(
    *,
    samples: Sequence[float] | None = None,
    quantiles: Sequence[float] | None = None,
    dot_count: int | None = None,
    context: str = "Dotplot",
) -> DotValues:
    """Select inverse empirical midpoint quantiles, or validate supplied ones.

    Empty input is absent data. Nonempty input must contain only finite real
    scalars: dropping invalid draws would silently change probability weights.
    """
    if (samples is None) == (quantiles is None):
        raise SpecError(f"{context}: supply exactly one of samples or quantiles")
    if dot_count is not None and (
        isinstance(dot_count, bool) or not isinstance(dot_count, int) or dot_count < 2
    ):
        raise SpecError(f"{context}: dot_count must be an integer >= 2")
    raw = samples if samples is not None else quantiles
    # Arrow-to-pandas list cells are arrays, not collections.abc.Sequence.
    to_list = getattr(raw, "tolist", None)
    if callable(to_list):
        raw = to_list()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise SpecError(f"{context}: distribution must be a sequence of finite numbers")
    values = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
            raise SpecError(f"{context}: distribution contains a nonfinite or nonnumeric value")
        values.append(float(value))
    if samples is not None:
        count = 20 if dot_count is None else dot_count
        if not values:
            return DotValues((), count)
        values.sort()
        size = len(values)
        return DotValues(
            tuple(values[((2 * i + 1) * size - 1) // (2 * count)] for i in range(count)), count
        )
    if not values:
        return DotValues((), dot_count)
    if len(values) < 2 or (dot_count is not None and len(values) != dot_count):
        raise SpecError(f"{context}: quantiles must contain dot_count (at least 2) values")
    if any(a > b for a, b in pairwise(values)):
        raise SpecError(f"{context}: quantiles must be nondecreasing")
    return DotValues(tuple(values), len(values))


def layout_dots(
    values: DotValues,
    *,
    domain: tuple[float, float],
    project: Callable[[float], float],
    dot_size: float,
    ref: float = 0.0,
) -> DotLayout:
    """Bin visible values on a shared grid, without crossing the reference."""
    low, high = domain
    below = above = 0
    rightmost: list[float] = []
    positions: list[DotPosition] = []
    pitch = dot_size + 1
    bin_pitch = 2 * pitch
    left, right = project(low), project(high)
    anchor = project(min(high, max(low, ref)))
    for value in values.quantiles:
        if value < low:
            below += 1
            continue
        if value > high:
            above += 1
            continue
        actual = project(value)
        if value == ref:
            x = actual
        else:
            index = math.floor((actual - anchor) / bin_pitch)
            if low <= ref <= high:
                index = min(-1, index) if value < ref else max(0, index)
            start = max(left, anchor + index * bin_pitch)
            end = min(right, anchor + (index + 1) * bin_pitch)
            x = (start + end) / 2
        level = next((i for i, end in enumerate(rightmost) if x - end >= pitch), len(rightmost))
        if level == len(rightmost):
            rightmost.append(x)
        else:
            rightmost[level] = x
        positions.append(DotPosition(value, x, level))
    return DotLayout(tuple(positions), values.dot_count, below, above, len(rightmost))
