"""Inline SVG emitters for forest bars, sparklines, and their shared axes."""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from itertools import pairwise
from typing import NamedTuple

from coeftable.format import CalendarStep, DateAxis, Format, TimeFormat, is_missing
from coeftable.theme import Theme

_TICK_STEPS = (1.0, 2.0, 2.5, 5.0, 10.0)

# Mean glyph width as a fraction of font size, for the sans-serif stack these
# SVGs render in. Approximate by design: it only needs to be good enough to
# decide whether a label would overrun a boundary, never to lay text out.
_CHAR_WIDTH_RATIO = 0.6


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


_SECONDS_PER_DAY = 86_400.0
_SECONDS_PER_MONTH = 30.4375 * _SECONDS_PER_DAY


class _CalendarRung(NamedTuple):
    """One candidate calendar tick granularity.

    `months > 0` steps every whole number of months (ticks always land on
    real first-of-month boundaries); `months == 0` steps every `seconds`
    (the sub-monthly day/week rungs). `label` is how `DateAxis` renders it.
    There is no separate quarter or year rung -- a quarter is `months=3`,
    a year `months=12` -- so month multiples that divide 12 stay year
    aligned and multiples of 12 fall on January.
    """

    label: CalendarStep
    months: int
    seconds: float

    @property
    def average_seconds(self) -> float:
        """Mean length of one step, for comparing against the target spacing."""
        return self.months * _SECONDS_PER_MONTH if self.months else self.seconds


# Finest to coarsest. Month multiples 1-6 divide 12 (ticks stay aligned
# within a year); 12 and up are whole years labelled by year alone.
_CALENDAR_RUNGS: tuple[_CalendarRung, ...] = (
    _CalendarRung("day", 0, _SECONDS_PER_DAY),
    _CalendarRung("day", 0, 7 * _SECONDS_PER_DAY),
    _CalendarRung("month", 1, 0.0),
    _CalendarRung("month", 2, 0.0),
    _CalendarRung("month", 3, 0.0),
    _CalendarRung("month", 6, 0.0),
    _CalendarRung("year", 12, 0.0),
    _CalendarRung("year", 24, 0.0),
    _CalendarRung("year", 60, 0.0),
    _CalendarRung("year", 120, 0.0),
)

# Minimum tick count a rung must actually produce over the domain before
# `_select_calendar_rung` will settle on it. A rung's *average* step length
# can fit `target` neatly while producing almost no ticks -- a 29-day span
# divided by target=4 lands on month by average length, but a 29-day window
# contains exactly one month boundary. Below this floor the axis reads as
# empty, so selection steps to the next finer rung instead.
_CALENDAR_TICK_FLOOR = 3


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


def _rung_ticks(low: float, high: float, rung: _CalendarRung) -> list[float]:
    """Tick positions for one rung, on real calendar boundaries."""
    if rung.months:
        low_dt = datetime.fromtimestamp(low, tz=UTC)
        high_dt = datetime.fromtimestamp(high, tz=UTC)
        return _month_aligned_ticks(low_dt, high_dt, rung.months)
    return _uniform_ticks(low, high, rung.seconds)


def _select_calendar_rung(low: float, high: float, target: int) -> _CalendarRung:
    """Pick a rung close to `target` ticks without underflowing the floor.

    Starts from the finest rung whose *average* length still fits `target`
    ticks, then steps to progressively finer rungs while the rung's *actual*
    tick count over ``[low, high]`` is below `_CALENDAR_TICK_FLOOR`. Average
    length alone ignores where the domain falls against real calendar
    boundaries, so it can pick a rung that only crosses one boundary in the
    whole span.
    """
    raw = (high - low) / max(target, 1)
    index = next(
        (i for i, rung in enumerate(_CALENDAR_RUNGS) if raw <= rung.average_seconds),
        len(_CALENDAR_RUNGS) - 1,
    )
    while index > 0 and len(_rung_ticks(low, high, _CALENDAR_RUNGS[index])) < _CALENDAR_TICK_FLOOR:
        index -= 1
    return _CALENDAR_RUNGS[index]


def calendar_ticks(low: float, high: float, target: int = 4) -> list[float]:
    """Return epoch-second tick positions on real calendar boundaries.

    Picks a granularity for the span -- days, weeks, or every N months (with
    a quarter being every 3 months and a year every 12) -- close to `target`
    ticks, then walks real calendar boundaries at that granularity. Months
    run 28-31 days, so monthly-and-up ticks use calendar arithmetic rather
    than a fixed number of seconds; `nice_ticks` is not involved here.

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
    return _rung_ticks(low, high, _select_calendar_rung(low, high, target))


def _projector(domain: tuple[float, float], width: int, inset: int):
    low, high = domain
    span = high - low
    if span <= 0:
        span = 1.0
    inner = width - 2 * inset

    def project(value: float) -> float:
        return inset + (value - low) / span * inner

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
    half = len(label) * font_size * _CHAR_WIDTH_RATIO / 2
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


def _clamp(value: float, low: float, high: float) -> float:
    """Pin *value* inside `[low, high]`.

    Used for the endpoint label's pixel position -- a single point always
    needs *some* in-bounds spot to sit at. Line/ribbon clipping instead
    uses `_clip_line_run`/`_clip_band_polygon`, which cut at the true
    boundary crossing rather than pinning a point in place.
    """
    return min(high, max(low, value))


def _segment_crossings(
    x0: float, y0: float, x1: float, y1: float, low: float, high: float
) -> list[tuple[float, float]]:
    """Split one line segment at each `low`/`high` crossing via linear interpolation.

    Returns `[(x0, y0), (x1, y1)]` with one point inserted per boundary the
    segment actually crosses, in domain-value space (not pixels) -- callers
    project after clipping, never before. A segment that never crosses
    either bound is returned unchanged.
    """
    points = [(x0, y0), (x1, y1)]
    for bound in (low, high):
        split: list[tuple[float, float]] = [points[0]]
        for (xa, ya), (xb, yb) in pairwise(points):
            if (ya - bound) * (yb - bound) < 0:
                t = (bound - ya) / (yb - ya)
                split.append((xa + t * (xb - xa), bound))
            split.append((xb, yb))
        points = split
    return points


def _clip_line_run(
    run: list[tuple[float, float]], low: float, high: float
) -> list[list[tuple[float, float]]]:
    """Split `run` into its maximal in-bounds sub-runs, clipped to `[low, high]`.

    Each sub-run's boundary endpoints come from `_segment_crossings`, not a
    per-point clamp, so the drawn approach angle into a clip matches the
    real trajectory. A sub-run must be rendered as one continuous polyline,
    never one `<line>` per clipped sub-segment -- fragmenting further loses
    proper vertex joins and reintroduces a visible notch at every zigzag
    point. Operates and returns in domain-value space; the caller projects
    afterward.
    """
    sub_runs: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for (x0, y0), (x1, y1) in pairwise(run):
        pts = _segment_crossings(x0, y0, x1, y1, low, high)
        for (xa, ya), (xb, yb) in pairwise(pts):
            if low <= (ya + yb) / 2 <= high:
                if not current:
                    current.append((xa, ya))
                current.append((xb, yb))
            elif current:
                sub_runs.append(current)
                current = []
    if current:
        sub_runs.append(current)
    return sub_runs


def _clip_band_polygon(
    poly: list[tuple[float, float]], low: float, high: float
) -> list[tuple[float, float]]:
    """Clip a ribbon polygon to `[low, high]` via Sutherland-Hodgman.

    `poly` and the result are `(x, value)` vertices in raw domain-value
    space -- this must run before projecting to pixels, never after. Pixel
    y is inverted relative to domain value (a larger domain value projects
    to a *smaller* pixel y), so running this same "keep above/below" logic
    on already-projected coordinates silently keeps the wrong side.
    """

    def _clip_edge(
        points: list[tuple[float, float]], bound: float, keep_above: bool
    ) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for i, cur in enumerate(points):
            prev = points[i - 1]
            cur_in = cur[1] >= bound if keep_above else cur[1] <= bound
            prev_in = prev[1] >= bound if keep_above else prev[1] <= bound
            if cur_in:
                if not prev_in:
                    t = (bound - prev[1]) / (cur[1] - prev[1])
                    out.append((prev[0] + t * (cur[0] - prev[0]), bound))
                out.append(cur)
            elif prev_in:
                t = (bound - prev[1]) / (cur[1] - prev[1])
                out.append((prev[0] + t * (cur[0] - prev[0]), bound))
        return out

    clipped = _clip_edge(poly, low, keep_above=True)
    if not clipped:
        return []
    return _clip_edge(clipped, high, keep_above=False)


def _out_of_bounds_spans(
    points: list[tuple[float, float]],
    low: float,
    high: float,
    project_x: Callable[[float], float],
) -> list[tuple[float, float, str]]:
    """Return the pixel x-ranges where `points` (domain-value space) sits outside `[low, high]`.

    Each returned `(start_x, end_x, edge)` covers one contiguous
    out-of-bounds stretch; `edge` is `"low"` or `"high"` for the bound it
    clipped against, and `start_x`/`end_x` are the projected
    `_segment_crossings` boundary positions, not the surrounding data
    points' own x. A lone point with no neighbour to form a segment (e.g.
    an isolated value flanked by gaps on both sides) still contributes a
    zero-width span at its own position when it is itself out of bounds --
    without this, a genuinely clipped point that never got a chance to
    cross a boundary would silently raise no cap at all. Returns `[]` when
    `points` never leaves the domain.
    """
    if len(points) < 2:
        if len(points) == 1:
            x0, y0 = points[0]
            if not (low <= y0 <= high):
                px = project_x(x0)
                return [(px, px, "low" if y0 < low else "high")]
        return []
    spans: list[tuple[float, float, str]] = []
    edge: str | None = None
    start_x = 0.0
    for (x0, y0), (x1, y1) in pairwise(points):
        pts = _segment_crossings(x0, y0, x1, y1, low, high)
        for (xa, ya), (_xb, yb) in pairwise(pts):
            mid = (ya + yb) / 2
            out_edge = None if low <= mid <= high else ("low" if mid < low else "high")
            if out_edge is not None:
                if edge != out_edge:
                    if edge is not None:
                        spans.append((start_x, project_x(xa), edge))
                    edge = out_edge
                    start_x = project_x(xa)
            elif edge is not None:
                spans.append((start_x, project_x(xa), edge))
                edge = None
    if edge is not None:
        spans.append((start_x, project_x(points[-1][0]), edge))
    return spans


def _merge_spans(spans: list[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    """Coalesce overlapping/adjacent spans that share the same edge.

    Several consecutive clipped points -- or a point clipping alongside its
    own ribbon bound -- naturally produce several overlapping spans;
    merging them is what turns that into the single continuous bracket the
    cap actually draws, never a cluster of overlapping marks. Spans on
    different edges never merge together.
    """
    by_edge: dict[str, list[tuple[float, float]]] = {}
    for start, end, edge in spans:
        by_edge.setdefault(edge, []).append((start, end))
    merged: list[tuple[float, float, str]] = []
    for edge, ranges in by_edge.items():
        ranges.sort()
        coalesced = [ranges[0]]
        for start, end in ranges[1:]:
            last_start, last_end = coalesced[-1]
            if start <= last_end:
                coalesced[-1] = (last_start, max(last_end, end))
            else:
                coalesced.append((start, end))
        merged.extend((start, end, edge) for start, end in coalesced)
    return merged


def _hard_clip_id(width: int, top_edge: float, bottom_edge: float) -> str:
    """Return a deterministic id for the hard-clip safety net's `<clipPath>`.

    SVG ids share one namespace across an entire embedding page (e.g. a
    table rendered row by row), so a literal id must never collide between
    two calls with *different* clip rectangles. The id is built directly
    from the rectangle's geometry -- its width and its top/bottom edges
    rounded to 3 decimal places -- as a plain format string, with the
    `.`/`-` characters those numbers introduce mapped to id-safe ones.
    Two calls therefore produce the same id exactly when they name the
    same clip rectangle (to sub-pixel precision), so any shared id is
    always harmless because the clip it references is identical.
    """
    raw = f"clip{width}_{top_edge:.3f}_{bottom_edge:.3f}"
    return raw.replace("-", "m").replace(".", "_")


def _clip_label(text: str, max_width: float, font_size: float) -> str:
    """Truncate `text` with an ellipsis so it fits `max_width` px.

    Approximates each character as `_CHAR_WIDTH_RATIO * font_size` px wide --
    accurate enough to stop an overlong endpoint label from overrunning its
    reserved strip. The strip itself never widens to fit the label.
    """
    budget = max(int(max_width / (font_size * _CHAR_WIDTH_RATIO)), 1)
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
    inset: int = 3,
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
    width, height, bar_height, inset
        Geometry in pixels.

    Returns
    -------
    str
        A complete ``<svg>`` element.
    """
    low, high = domain
    project = _projector(domain, width, inset)
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
        tip = width - inset / 2
        parts.append(
            f'<polygon points="{tip:.2f},{middle:.2f} {tip - cap:.2f},{middle - cap:.2f} '
            f'{tip - cap:.2f},{middle + cap:.2f}" fill="{color}"/>'
        )
    if clipped_low:
        tip = inset / 2
        parts.append(
            f'<polygon points="{tip:.2f},{middle:.2f} {tip + cap:.2f},{middle - cap:.2f} '
            f'{tip + cap:.2f},{middle + cap:.2f}" fill="{color}"/>'
        )

    return _svg(width, height, "".join(parts))


def _render_tick_axis(
    ticks: list[float],
    *,
    project: Callable[[float], float],
    label: Format | TimeFormat,
    baseline: float,
    height: int,
    width: int,
    theme: Theme,
) -> list[str]:
    """Render each tick as a mark plus a label, shared by both axis emitters.

    `forest_axis` and `sparkline_axis` draw an identical tick mark and
    label per position; only the tick set and the labelling callable
    differ. `label` is applied to each raw tick value to produce its text.
    """
    parts: list[str] = []
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
    return parts


def forest_axis(
    *,
    domain: tuple[float, float],
    ref: float,
    fmt: Format,
    theme: Theme,
    width: int = 220,
    height: int = 22,
    inset: int = 3,
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
    width, height, inset
        Geometry in pixels.
    target_ticks
        Approximate number of ticks wanted.

    Returns
    -------
    str
        A complete ``<svg>`` element.
    """
    low, high = domain
    project = _projector(domain, width, inset)
    baseline = 4.0
    parts = [
        f'<line x1="{inset}" y1="{baseline:.2f}" x2="{width - inset}" y2="{baseline:.2f}" '
        f'stroke="{theme.axis}" stroke-width="0.75"/>'
    ]
    if low <= ref <= high:
        ref_x = project(ref)
        parts.append(
            f'<line x1="{ref_x:.2f}" y1="0" x2="{ref_x:.2f}" y2="{baseline:.2f}" '
            f'stroke="{theme.axis}" stroke-width="1" stroke-dasharray="2,2"/>'
        )
    parts.extend(
        _render_tick_axis(
            nice_ticks(low, high, target_ticks),
            project=project,
            label=fmt,
            baseline=baseline,
            height=height,
            width=width,
            theme=theme,
        )
    )
    return _svg(width, height, "".join(parts))


def _render_band_run(
    run: list[tuple[float, float, float]],
    *,
    low: float,
    high: float,
    project_x: Callable[[float], float],
    project_y: Callable[[float], float],
    color: str,
    clip_id: str,
) -> tuple[list[str], list[str], list[tuple[float, float, str]]]:
    """Render one ribbon run into ghost, real and clip-span parts.

    Returns the fainter true-trajectory ghost polygon (empty when the run
    stays in bounds), the opaque in-domain polygon (clipped when it
    crosses an edge), and the out-of-bounds spans that drive the clip
    caps. The caller layers ghost beneath real and feeds the spans to the
    shared cap pass.
    """
    ghost: list[str] = []
    real: list[str] = []
    upper_pts = [(xi, ui) for xi, _li, ui in run]
    lower_pts = [(xi, li) for xi, li, _ui in run]
    spans = _out_of_bounds_spans(upper_pts, low, high, project_x) + _out_of_bounds_spans(
        lower_pts, low, high, project_x
    )
    top = " ".join(f"{project_x(xi):.2f},{project_y(ui):.2f}" for xi, ui in upper_pts)
    bottom = " ".join(f"{project_x(xi):.2f},{project_y(li):.2f}" for xi, li in reversed(lower_pts))
    if spans:
        ghost.append(f'<polygon points="{top} {bottom}" fill="{color}" fill-opacity="0.06"/>')
        clipped = _clip_band_polygon(upper_pts + list(reversed(lower_pts)), low, high)
        if clipped:
            band_pts = " ".join(f"{project_x(px):.2f},{project_y(pv):.2f}" for px, pv in clipped)
            real.append(
                f'<g clip-path="url(#{clip_id})"><polygon points="{band_pts}" '
                f'fill="{color}" fill-opacity="0.15"/></g>'
            )
    else:
        real.append(f'<polygon points="{top} {bottom}" fill="{color}" fill-opacity="0.15"/>')
    return ghost, real, spans


def _render_line_run(
    run: list[tuple[float, float]],
    *,
    low: float,
    high: float,
    project_x: Callable[[float], float],
    project_y: Callable[[float], float],
    color: str,
    clip_id: str,
) -> tuple[list[str], list[str], list[tuple[float, float, str]]]:
    """Render one series-line run into ghost, real and clip-span parts.

    Mirrors `_render_band_run` for the estimate line: a translucent ghost
    polyline of the true trajectory when it clips, the opaque in-domain
    polyline pieces (clipped to the domain edge), and the out-of-bounds
    spans for the cap pass.
    """
    ghost: list[str] = []
    real: list[str] = []
    spans = _out_of_bounds_spans(run, low, high, project_x)
    pts = " ".join(f"{project_x(xi):.2f},{project_y(yi):.2f}" for xi, yi in run)
    if spans:
        ghost.append(
            f'<polyline points="{pts}" fill="none" stroke="{color}" '
            f'stroke-width="1.5" stroke-opacity="0.35"/>'
        )
        clipped_pieces = "".join(
            '<polyline points="'
            + " ".join(f"{project_x(cx):.2f},{project_y(cy):.2f}" for cx, cy in piece)
            + f'" fill="none" stroke="{color}" stroke-width="1.5"/>'
            for piece in _clip_line_run(run, low, high)
        )
        if clipped_pieces:
            real.append(f'<g clip-path="url(#{clip_id})">{clipped_pieces}</g>')
    else:
        real.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.5"/>')
    return ghost, real, spans


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
    inset: int = 3,
    show_endpoint: bool = True,
    endpoint_width: int = 44,
    show_clip_indicators: bool = True,
) -> str:
    """Render one series as an inline SVG line plot with an uncertainty ribbon.

    A gap (`None`/NaN) in `x` or `y` breaks both the ribbon and the series
    line into separate segments rather than joining across it; there is no
    option to bridge a gap. `lower`/`upper` follow the same rule for the
    ribbon alone, so a series with no declared interval (`lower`/`upper` all
    missing) simply draws no ribbon. A series with no valid point at all
    still returns a complete, empty ``<svg>`` rather than raising.

    A point outside `domain` is not a gap -- the data exists, it is merely
    off-scale. The line and ribbon are clipped to the domain rectangle at
    the exact pixel where they cross its edge (segment/polygon boundary
    intersection, not a per-point clamp), so the drawn approach angle into
    a clip matches the real trajectory instead of visually flattening into
    it; the opaque (real) layer stays pinned inside the domain rectangle
    and never escapes the canvas regardless. `lower` and `upper` clip
    independently, so a bound that stays inside `domain` keeps its true
    position even while the other is pinned. A fainter "ghost" trace of
    the true, unclamped line and ribbon is always drawn underneath
    wherever a clip occurs, continuing past the domain edge on its own
    real trajectory -- it deliberately *may* carry off-canvas coordinates;
    the outer `<svg>` viewport clips those visually, so the ghost never
    bleeds into surrounding content even though its own coordinates are
    unbounded. It carries the real shape of what got clipped, not just
    the fact that it happened.

    When `show_clip_indicators` is set, a thin double line marks each
    contiguous clipped stretch against the domain edge it clipped -- one
    line pair per stretch, spanning its true pixel x-range (padded 3px past
    each end), not a fixed-width tick centred on one point. Several
    consecutive clipped points merge into one bracket rather than a
    cluster of overlapping marks. The trigger is ribbon-aware: it fires on
    `lower`/`upper` leaving `domain` even when the point estimate itself
    stays inside it, since a ribbon can be clamped to a sliver of its true
    width while its point stays comfortably in view.

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
        Line, ribbon, endpoint, reference-line, ghost-trace and clip-cap
        colour, resolved from the last point's interval by the caller.
    fmt
        Formats the endpoint value label.
    width, height, inset
        Geometry in pixels.
    show_endpoint
        Draw the endpoint value label.
    endpoint_width
        Fixed pixel reserve carved out of `width` for the endpoint label,
        independent of the formatted label's length. `sparkline_axis` must
        be given the same `width`, `inset`, `show_endpoint` and
        `endpoint_width` so its ticks project over the identical inner width
        and land under their points.
    show_clip_indicators
        Draw the clip-cap marks described above. The line/ribbon clipping
        and the ghost trace happen regardless of this flag -- turning it
        off only removes the cap marks, never the underlying clipping or
        the true-trajectory ghost.

    Returns
    -------
    str
        A complete ``<svg>`` element.
    """
    low, high = domain
    right_edge = width - inset
    plot_width = width - endpoint_width if show_endpoint else width
    project_x = _projector(x_domain, plot_width, inset)
    project_up = _projector(domain, height, inset)

    def project_y(value: float) -> float:
        return height - project_up(value)

    top_edge = project_y(high)
    bottom_edge = project_y(low)
    clip_id = _hard_clip_id(width, top_edge, bottom_edge)

    parts: list[str] = []
    ghost_parts: list[str] = []
    raw_spans: list[tuple[float, float, str]] = []

    band_runs = _band_runs(x, y, lower, upper)
    for run in band_runs:
        ghost, real, spans = _render_band_run(
            run,
            low=low,
            high=high,
            project_x=project_x,
            project_y=project_y,
            color=color,
            clip_id=clip_id,
        )
        ghost_parts.extend(ghost)
        parts.extend(real)
        raw_spans.extend(spans)

    line_runs = _line_runs(x, y)

    if (line_runs or band_runs) and low <= ref <= high:
        ref_y = project_y(ref)
        parts.append(
            f'<line x1="{inset}" y1="{ref_y:.2f}" x2="{right_edge}" y2="{ref_y:.2f}" '
            f'stroke="{color}" stroke-width="1" stroke-dasharray="2,2"/>'
        )

    for run in line_runs:
        ghost, real, spans = _render_line_run(
            run,
            low=low,
            high=high,
            project_x=project_x,
            project_y=project_y,
            color=color,
            clip_id=clip_id,
        )
        ghost_parts.extend(ghost)
        parts.extend(real)
        raw_spans.extend(spans)

    if line_runs and show_endpoint:
        _, ey = line_runs[-1][-1]
        ey_px = project_y(_clamp(ey, low, high))
        label = _clip_label(fmt(ey), max(endpoint_width - 4, 4), 9.0)
        parts.append(
            f'<text x="{right_edge}" y="{ey_px + 3:.2f}" fill="{color}" '
            f'font-size="9" text-anchor="end">{label}</text>'
        )

    cap_parts: list[str] = []
    if show_clip_indicators and raw_spans:
        for start_x, end_x, edge in _merge_spans(raw_spans):
            edge_y = top_edge if edge == "high" else bottom_edge
            for dy in (-0.5, 0.5):
                cap_parts.append(
                    f'<line x1="{start_x - 3.0:.2f}" y1="{edge_y + dy:.2f}" '
                    f'x2="{end_x + 3.0:.2f}" y2="{edge_y + dy:.2f}" '
                    f'stroke="{color}" stroke-width="0.5" stroke-opacity="0.45"/>'
                )

    body = ghost_parts + parts + cap_parts
    if raw_spans:
        body.insert(
            0,
            f'<clipPath id="{clip_id}"><rect x="0" y="{top_edge:.2f}" width="{width}" '
            f'height="{bottom_edge - top_edge:.2f}"/></clipPath>',
        )
    return _svg(width, height, "".join(body))


def sparkline_axis(
    *,
    x_domain: tuple[float, float],
    fmt: Format | TimeFormat,
    theme: Theme,
    temporal: bool = False,
    width: int = 220,
    height: int = 22,
    inset: int = 3,
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
    width, height, inset
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
    project = _projector(x_domain, plot_width, inset)
    baseline = 4.0
    parts = [
        f'<line x1="{inset}" y1="{baseline:.2f}" x2="{plot_width - inset}" y2="{baseline:.2f}" '
        f'stroke="{theme.axis}" stroke-width="0.75"/>'
    ]
    if temporal:
        ticks = calendar_ticks(low, high, target_ticks)
        if isinstance(fmt, DateAxis) and ticks:
            rung = _select_calendar_rung(low, high, target_ticks)
            years = {datetime.fromtimestamp(t, tz=UTC).year for t in ticks}
            label = dataclasses.replace(fmt, step=rung.label, show_year=len(years) > 1)
        else:
            label = fmt
    else:
        ticks = nice_ticks(low, high, target_ticks)
        label = fmt
    # The anchor boundary is `width`, not `plot_width`: what we are avoiding is
    # the canvas cutting a label off, and the canvas is the full `width`. The
    # endpoint reserve past `plot_width` is empty on a footer row -- the
    # endpoint label only ever appears on data rows -- so a last tick label
    # reaching into it neither clips nor collides, and keeping it centred
    # leaves it aligned on its own tick mark.
    parts.extend(
        _render_tick_axis(
            ticks,
            project=project,
            label=label,
            baseline=baseline,
            height=height,
            width=width,
            theme=theme,
        )
    )
    return _svg(width, height, "".join(parts))
