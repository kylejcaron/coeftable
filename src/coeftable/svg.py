"""Inline SVG emitters for forest bars, sparklines, and their shared axes."""

from __future__ import annotations

import math
from collections.abc import Sequence

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


def _line_runs(
    x: Sequence[float | None], y: Sequence[float | None]
) -> list[list[tuple[float, float]]]:
    """Group `(x, y)` pairs into runs, breaking at each missing `x` or `y`."""
    runs: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []

    def _flush() -> None:
        nonlocal current
        if current:
            runs.append(current)
            current = []

    for xi, yi in zip(x, y, strict=True):
        if xi is None or yi is None:
            _flush()
            continue
        if math.isnan(xi) or math.isnan(yi):
            _flush()
            continue
        current.append((xi, yi))
    _flush()
    return runs


def _band_runs(
    x: Sequence[float | None],
    y: Sequence[float | None],
    lower: Sequence[float | None],
    upper: Sequence[float | None],
) -> list[list[tuple[float, float, float]]]:
    """Group `(x, lower, upper)` triples into runs, breaking at any missing value.

    A run also breaks wherever `y` is missing -- a gap in the estimate drops
    its interval too, even when `lower`/`upper` are themselves still present.
    """
    runs: list[list[tuple[float, float, float]]] = []
    current: list[tuple[float, float, float]] = []

    def _flush() -> None:
        nonlocal current
        if current:
            runs.append(current)
            current = []

    for xi, yi, li, ui in zip(x, y, lower, upper, strict=True):
        if xi is None or yi is None or li is None or ui is None:
            _flush()
            continue
        if math.isnan(xi) or math.isnan(yi) or math.isnan(li) or math.isnan(ui):
            _flush()
            continue
        current.append((xi, li, ui))
    _flush()
    return runs


def _clip_label(text: str, max_width: float, font_size: float) -> str:
    """Truncate `text` with an ellipsis so it fits `max_width` px.

    Approximates each character as `0.6 * font_size` px wide -- accurate
    enough to stop an overlong endpoint label from overrunning its reserved
    strip. The strip itself never widens to fit the label.
    """
    budget = max(int(max_width / (font_size * 0.6)), 1)
    if len(text) <= budget:
        return text
    if budget == 1:
        return text[0]
    return text[: budget - 1] + "\u2026"


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


def sparkline_bar(
    x: Sequence[float | None],
    y: Sequence[float | None],
    lower: Sequence[float | None],
    upper: Sequence[float | None],
    *,
    x_domain: tuple[float, float],
    domain: tuple[float, float],
    ref: float,
    color: str,
    theme: Theme,
    fmt: Format,
    width: int = 220,
    height: int = 30,
    pad: int = 3,
    show_endpoint: bool = True,
    endpoint_width: int = 44,
) -> str:
    """Render one series as an inline SVG line plot with an uncertainty ribbon.

    A gap (`None`/NaN) in `x` or `y` breaks both the ribbon and the series
    line into separate segments rather than joining across it; there is no
    option to bridge a gap. `lower`/`upper` follow the same rule for the
    ribbon alone, so a series with no declared interval (`lower`/`upper` all
    missing) simply draws no ribbon. A series with no valid point at all
    still returns a complete, empty ``<svg>`` rather than raising.

    Parameters
    ----------
    x, y
        Parallel point positions and estimates, equal length.
    lower, upper
        Parallel interval bounds, equal length to `x`/`y`.
    x_domain
        Shared x-domain for `x`. Always table-wide, never padded per row.
    domain
        Shared y-domain for `y`, `lower`, `upper` and `ref`.
    ref
        Reference value for the horizontal dashed line.
    color
        Line, ribbon and endpoint colour, resolved from the last point's
        interval by the caller.
    theme
        Supplies the reference-line colour.
    fmt
        Formats the endpoint value label.
    width, height, pad
        Geometry in pixels.
    show_endpoint
        Draw the endpoint value label. The endpoint dot itself is always
        drawn when the series has a last valid point.
    endpoint_width
        Fixed pixel reserve carved out of `width` for the endpoint label,
        independent of the formatted label's length. `sparkline_axis` must
        be given the same `width`, `pad`, `show_endpoint` and
        `endpoint_width` so its ticks project over the identical inner width
        and land under their points.

    Returns
    -------
    str
        A complete ``<svg>`` element.
    """
    low, high = domain
    right_edge = width - pad
    plot_width = width - endpoint_width if show_endpoint else width
    project_x = _projector(x_domain, plot_width, pad)
    project_up = _projector(domain, height, pad)

    def project_y(value: float) -> float:
        return height - project_up(value)

    parts: list[str] = []

    band_runs = _band_runs(x, y, lower, upper)
    for run in band_runs:
        top = " ".join(f"{project_x(xi):.2f},{project_y(ui):.2f}" for xi, _li, ui in run)
        bottom = " ".join(
            f"{project_x(xi):.2f},{project_y(li):.2f}" for xi, li, _ui in reversed(run)
        )
        parts.append(f'<polygon points="{top} {bottom}" fill="{color}" fill-opacity="0.15"/>')

    line_runs = _line_runs(x, y)

    if (line_runs or band_runs) and low <= ref <= high:
        ref_y = project_y(ref)
        parts.append(
            f'<line x1="{pad}" y1="{ref_y:.2f}" x2="{right_edge}" y2="{ref_y:.2f}" '
            f'stroke="{theme.axis}" stroke-width="1" stroke-dasharray="2,2"/>'
        )

    for run in line_runs:
        pts = " ".join(f"{project_x(xi):.2f},{project_y(yi):.2f}" for xi, yi in run)
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.5"/>')

    if line_runs:
        ex, ey = line_runs[-1][-1]
        ex_px, ey_px = project_x(ex), project_y(ey)
        parts.append(f'<circle cx="{ex_px:.2f}" cy="{ey_px:.2f}" r="2.5" fill="{color}"/>')
        if show_endpoint:
            label = _clip_label(fmt(ey), max(endpoint_width - 4, 4), 9.0)
            parts.append(
                f'<text x="{right_edge}" y="{ey_px + 3:.2f}" fill="{color}" '
                f'font-size="9" text-anchor="end">{label}</text>'
            )

    return _svg(width, height, "".join(parts))
