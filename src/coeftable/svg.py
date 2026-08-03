"""Inline SVG emitters for forest bars, sparklines, and their shared axes."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from datetime import UTC, datetime

from coeftable.format import CalendarStep, DateAxis, Format, TimeFormat, is_missing
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


_CALENDAR_STEPS: tuple[CalendarStep, ...] = ("day", "week", "month", "quarter", "year")
_CALENDAR_STEP_SECONDS: dict[CalendarStep, float] = {
    "day": 86_400.0,
    "week": 7 * 86_400.0,
    "month": 30.4375 * 86_400.0,
    "quarter": 91.3125 * 86_400.0,
    "year": 365.25 * 86_400.0,
}


def _select_calendar_step(span: float, target: int) -> CalendarStep:
    """Pick the finest ladder rung whose average length still fits `target` ticks."""
    raw = span / max(target, 1)
    return next(
        (step for step in _CALENDAR_STEPS if raw <= _CALENDAR_STEP_SECONDS[step]),
        "year",
    )


def _uniform_ticks(low: float, high: float, step: float) -> list[float]:
    """Evenly spaced ticks every `step` seconds -- the day/week case of `calendar_ticks`."""
    start = math.ceil(low / step) * step
    count = math.floor((high - start) / step) + 1
    return [round(start + i * step, 6) for i in range(max(count, 0))]


def _month_index(dt: datetime) -> int:
    """Linear month count (`year * 12 + month0`), used as a step-aligned grid."""
    return dt.year * 12 + (dt.month - 1)


def _month_start(index: int) -> datetime:
    """First-of-month UTC datetime for a `_month_index` value."""
    year, month0 = divmod(index, 12)
    return datetime(year, month0 + 1, 1, tzinfo=UTC)


def _month_aligned_ticks(low: datetime, high: datetime, step_months: int) -> list[float]:
    """Ticks every `step_months` months, spanning ``[low, high]``.

    A month index is a multiple of `step_months` exactly at quarter starts
    (Jan/Apr/Jul/Oct) when `step_months` is 3 and at year starts (Jan) when
    it is 12, since 12 is divisible by both -- no separate quarter/year
    alignment rule is needed beyond this one grid.
    """
    start_index = -(-_month_index(low) // step_months) * step_months
    start = _month_start(start_index)
    if start < low:
        start_index += step_months
        start = _month_start(start_index)
    ticks: list[float] = []
    index, dt = start_index, start
    while dt <= high:
        ticks.append(dt.timestamp())
        index += step_months
        dt = _month_start(index)
    return ticks


def calendar_ticks(low: float, high: float, target: int = 4) -> list[float]:
    """Return epoch-second tick positions on real day/week/month/quarter/year boundaries.

    Selects a step from a fixed ladder (day, week, month, quarter, year)
    based on the span, then walks real calendar boundaries for that step.
    Months run 28-31 days, so month/quarter/year ticks use calendar
    arithmetic rather than a fixed number of seconds; `nice_ticks` is not
    involved anywhere in this path.

    Parameters
    ----------
    low, high
        Domain bounds, epoch seconds (UTC).
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
    step = _select_calendar_step(high - low, target)
    if step == "day":
        return _uniform_ticks(low, high, 86_400.0)
    if step == "week":
        return _uniform_ticks(low, high, 7 * 86_400.0)
    step_months = {"month": 1, "quarter": 3, "year": 12}[step]
    low_dt = datetime.fromtimestamp(low, tz=UTC)
    high_dt = datetime.fromtimestamp(high, tz=UTC)
    return _month_aligned_ticks(low_dt, high_dt, step_months)


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


def _tick_anchor(tick_x: float, label: str, width: int, font_size: float = 9.0) -> str:
    """Anchor a tick label inward only when centring it would clip the canvas.

    A centred label whose half-width extends past `0` or `width` is cut off
    by the SVG boundary. Anchoring by tick *index* would over-correct: tick
    generators start at `ceil(low / step) * step`, so the first tick can sit
    a long way inside the left edge and needs no correction at all. Gate on
    the projected position and the label's own estimated width instead, using
    the same character-width approximation as `_clip_label`.
    """
    half = len(label) * font_size * 0.6 / 2
    if tick_x - half < 0:
        return "start"
    if tick_x + half > width:
        return "end"
    return "middle"


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
        if is_missing(xi) or is_missing(yi):
            _flush()
            continue
        assert xi is not None and yi is not None  # noqa: S101 - is_missing narrows NaN, not None
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
        if is_missing(xi) or is_missing(yi) or is_missing(li) or is_missing(ui):
            _flush()
            continue
        assert xi is not None and li is not None and ui is not None  # noqa: S101
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
        text = fmt(tick)
        parts.append(
            f'<line x1="{tick_x:.2f}" y1="{baseline:.2f}" x2="{tick_x:.2f}" '
            f'y2="{baseline + 3:.2f}" stroke="{theme.axis}" stroke-width="0.75"/>'
        )
        parts.append(
            f'<text x="{tick_x:.2f}" y="{height - 2:.2f}" fill="{theme.axis}" '
            f'font-size="9" text-anchor="{_tick_anchor(tick_x, text, width)}">{text}</text>'
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
        Line, ribbon, endpoint and reference-line colour, resolved from the
        last point's interval by the caller.
    fmt
        Formats the endpoint value label.
    width, height, pad
        Geometry in pixels.
    show_endpoint
        Draw the endpoint value label.
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
            f'stroke="{color}" stroke-width="1" stroke-dasharray="2,2"/>'
        )

    for run in line_runs:
        pts = " ".join(f"{project_x(xi):.2f},{project_y(yi):.2f}" for xi, yi in run)
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.5"/>')

    if line_runs and show_endpoint:
        _, ey = line_runs[-1][-1]
        ey_px = project_y(ey)
        label = _clip_label(fmt(ey), max(endpoint_width - 4, 4), 9.0)
        parts.append(
            f'<text x="{right_edge}" y="{ey_px + 3:.2f}" fill="{color}" '
            f'font-size="9" text-anchor="end">{label}</text>'
        )

    return _svg(width, height, "".join(parts))


def sparkline_axis(
    *,
    x_domain: tuple[float, float],
    fmt: Format | TimeFormat,
    theme: Theme,
    temporal: bool = False,
    width: int = 220,
    height: int = 22,
    pad: int = 3,
    target_ticks: int = 4,
    show_endpoint: bool = True,
    endpoint_width: int = 44,
) -> str:
    """Render the shared x-axis footer for a column of sparkline rows.

    Parameters
    ----------
    x_domain
        Shared x-domain, table-wide -- see `sparkline_bar`'s `x_domain`.
    fmt
        Callable used to label each tick. When `temporal` is True and `fmt`
        is a `DateAxis`, a copy with `step` set to whichever rung
        `calendar_ticks` picked for this domain is used instead, so the
        label granularity always matches the ticks being drawn. Any other
        callable, temporal or not, is called exactly as given.
    theme
        Supplies the axis colour and label size.
    temporal
        Use `calendar_ticks` (real month/quarter/year boundaries) instead of
        `nice_ticks` (decimal steps).
    width, height, pad
        Geometry in pixels.
    target_ticks
        Approximate number of ticks wanted.
    show_endpoint, endpoint_width
        Must be given the same values passed to `sparkline_bar` for the same
        rows: both carve the same fixed reserve out of `width` so ticks
        project over the identical inner width and land under their points.

    Returns
    -------
    str
        A complete ``<svg>`` element.
    """
    low, high = x_domain
    plot_width = width - endpoint_width if show_endpoint else width
    project = _projector(x_domain, plot_width, pad)
    baseline = 4.0
    parts = [
        f'<line x1="{pad}" y1="{baseline:.2f}" x2="{plot_width - pad}" y2="{baseline:.2f}" '
        f'stroke="{theme.axis}" stroke-width="0.75"/>'
    ]
    if temporal:
        ticks = calendar_ticks(low, high, target_ticks)
        if isinstance(fmt, DateAxis):
            step = _select_calendar_step(high - low, target_ticks)
            label = dataclasses.replace(fmt, step=step)
        else:
            label = fmt
    else:
        ticks = nice_ticks(low, high, target_ticks)
        label = fmt
    for tick in ticks:
        tick_x = project(tick)
        text = label(tick)
        parts.append(
            f'<line x1="{tick_x:.2f}" y1="{baseline:.2f}" x2="{tick_x:.2f}" '
            f'y2="{baseline + 3:.2f}" stroke="{theme.axis}" stroke-width="0.75"/>'
        )
        parts.append(
            f'<text x="{tick_x:.2f}" y="{height - 2:.2f}" fill="{theme.axis}" '
            f'font-size="9" text-anchor="{_tick_anchor(tick_x, text, width)}">{text}</text>'
        )
    return _svg(width, height, "".join(parts))
