"""Inline SVG emitters for forest bars and their shared axis."""

from __future__ import annotations

import math

from coeftable.format import Format, is_missing
from coeftable.theme import Theme

_TICK_STEPS = (1.0, 2.0, 2.5, 5.0, 10.0)


def nice_ticks(low: float, high: float, target: int = 4) -> list[float]:
    """Return round tick positions spanning ``[low, high]``.

    Parameters
    ----------
    low, high
        Domain bounds.
    target
        Approximate number of ticks wanted.

    Returns
    -------
    list of float
        Tick positions, empty when the domain is invalid.
    """
    if not (math.isfinite(low) and math.isfinite(high)) or high < low:
        return []
    if high == low:
        return [low]
    raw = (high - low) / max(target, 1)
    magnitude = 10.0 ** math.floor(math.log10(raw))
    step = next((m * magnitude for m in _TICK_STEPS if raw <= m * magnitude), 10.0 * magnitude)
    start = math.ceil(low / step) * step
    count = math.floor((high - start) / step) + 1
    return [round(start + i * step, 10) for i in range(max(count, 0))]


def _projector(domain: tuple[float, float], width: int, pad: int):
    low, high = domain
    span = high - low
    if span <= 0:
        span = 1.0
    inner = width - 2 * pad

    def project(value: float) -> float:
        return pad + (value - low) / span * inner

    return project


def _svg(width: int, height: int, body: str) -> str:
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" style="display:block;margin:0 auto">'
        f"{body}</svg>"
    )


def forest_bar(
    estimate: float | None,
    lower: float | None,
    upper: float | None,
    *,
    domain: tuple[float, float],
    ref: float,
    color: str,
    theme: Theme,
    width: int = 220,
    height: int = 18,
    bar_height: int = 9,
    pad: int = 3,
) -> str:
    """Render one interval as an inline SVG bar.

    The bar spans the interval, a light tick marks the point estimate, and a
    dashed line marks `ref` when it falls inside `domain`.  A bound outside the
    domain, including an unbounded one, draws to the edge with a triangular cap
    so that clipping is visible rather than silently misleading.

    Parameters
    ----------
    estimate
        Point estimate; the tick is omitted when missing or outside `domain`.
    lower, upper
        Interval bounds.  ``None`` means unbounded on that side.
    domain
        Shared x-domain the bar is drawn against.
    ref
        Reference value for the dashed line.
    color
        Bar colour, resolved from a semantic role by the caller.
    theme
        Supplies axis and surface colours.
    width, height, bar_height, pad
        Geometry in pixels.

    Returns
    -------
    str
        A complete ``<svg>`` element.
    """
    low, high = domain
    project = _projector(domain, width, pad)
    low_value = low if lower is None or is_missing(lower) else lower
    high_value = high if upper is None or is_missing(upper) else upper
    clipped_low = is_missing(lower) or low_value < low
    clipped_high = is_missing(upper) or high_value > high

    x0 = project(max(low_value, low))
    x1 = project(min(high_value, high))
    top = (height - bar_height) / 2
    middle = height / 2
    parts: list[str] = []

    if low <= ref <= high:
        ref_x = project(ref)
        parts.append(
            f'<line x1="{ref_x:.2f}" y1="0" x2="{ref_x:.2f}" y2="{height}" '
            f'stroke="{theme.axis}" stroke-width="1" stroke-dasharray="2,2"/>'
        )

    parts.append(
        f'<rect x="{x0:.2f}" y="{top:.2f}" width="{max(x1 - x0, 0.75):.2f}" '
        f'height="{bar_height}" fill="{color}" fill-opacity="0.75" '
        f'stroke="{color}" stroke-width="0.75"/>'
    )

    if estimate is not None and not is_missing(estimate) and low <= estimate <= high:
        tick_x = project(estimate)
        parts.append(
            f'<line x1="{tick_x:.2f}" y1="{top:.2f}" x2="{tick_x:.2f}" '
            f'y2="{top + bar_height:.2f}" stroke="{theme.surface}" stroke-width="1.5"/>'
        )

    cap = bar_height * 0.6
    if clipped_high:
        tip = width - pad / 2
        parts.append(
            f'<polygon points="{tip:.2f},{middle:.2f} {tip - cap:.2f},{middle - cap:.2f} '
            f'{tip - cap:.2f},{middle + cap:.2f}" fill="{color}"/>'
        )
    if clipped_low:
        tip = pad / 2
        parts.append(
            f'<polygon points="{tip:.2f},{middle:.2f} {tip + cap:.2f},{middle - cap:.2f} '
            f'{tip + cap:.2f},{middle + cap:.2f}" fill="{color}"/>'
        )

    return _svg(width, height, "".join(parts))


def forest_axis(
    *,
    domain: tuple[float, float],
    ref: float,
    fmt: Format,
    theme: Theme,
    width: int = 220,
    height: int = 22,
    pad: int = 3,
    target_ticks: int = 4,
) -> str:
    """Render the shared x-axis for a set of forest bars.

    Parameters
    ----------
    domain
        Shared x-domain.
    ref
        Reference value for the dashed line.
    fmt
        Callable used to label each tick.
    theme
        Supplies the axis colour and label size.
    width, height, pad
        Geometry in pixels.
    target_ticks
        Approximate number of ticks wanted.

    Returns
    -------
    str
        A complete ``<svg>`` element.
    """
    low, high = domain
    project = _projector(domain, width, pad)
    baseline = 4.0
    parts = [
        f'<line x1="{pad}" y1="{baseline:.2f}" x2="{width - pad}" y2="{baseline:.2f}" '
        f'stroke="{theme.axis}" stroke-width="0.75"/>'
    ]
    if low <= ref <= high:
        ref_x = project(ref)
        parts.append(
            f'<line x1="{ref_x:.2f}" y1="0" x2="{ref_x:.2f}" y2="{baseline:.2f}" '
            f'stroke="{theme.axis}" stroke-width="1" stroke-dasharray="2,2"/>'
        )
    for tick in nice_ticks(low, high, target_ticks):
        tick_x = project(tick)
        parts.append(
            f'<line x1="{tick_x:.2f}" y1="{baseline:.2f}" x2="{tick_x:.2f}" '
            f'y2="{baseline + 3:.2f}" stroke="{theme.axis}" stroke-width="0.75"/>'
        )
        parts.append(
            f'<text x="{tick_x:.2f}" y="{height - 2:.2f}" fill="{theme.axis}" '
            f'font-size="9" text-anchor="middle">{fmt(tick)}</text>'
        )
    return _svg(width, height, "".join(parts))
