"""Inline SVG emitters for forest bars, sparklines, and their shared axes."""

from __future__ import annotations

import html
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from typing import NamedTuple

from coeftable.annotations import Layer, ResolvedAnnotation, ResolvedRule
from coeftable.format import _MONTH_ABBR, CalendarStep, DateAxis, Format, TimeFormat, is_missing
from coeftable.theme import DEFAULT, Theme

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

# 1970-01-01 (epoch) was a Thursday, 4 days before the *following* Monday
# (3 days after the preceding one), so an epoch-aligned 7-day grid lands on
# Thursdays -- an artifact, not a choice. Offsetting forward by 4 days
# realigns weekly and fortnightly ticks to Monday, the ISO-8601 week start.
_WEEK_PHASE = 4 * _SECONDS_PER_DAY


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


# Finest to coarsest. 2d/3d/14d close the density gap below the week rung --
# without them a 5-14 day span has nowhere to land except >=7 colliding day
# ticks or <3 sparse week ticks. Month multiples 1-6 divide 12 (ticks stay
# aligned within a year); 12 and up are whole years labelled by year alone.
_CALENDAR_RUNGS: tuple[_CalendarRung, ...] = (
    _CalendarRung("day", 0, _SECONDS_PER_DAY),
    _CalendarRung("day", 0, 2 * _SECONDS_PER_DAY),
    _CalendarRung("day", 0, 3 * _SECONDS_PER_DAY),
    _CalendarRung("day", 0, 7 * _SECONDS_PER_DAY),
    _CalendarRung("day", 0, 14 * _SECONDS_PER_DAY),
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


def _uniform_ticks(low: float, high: float, step: float, phase: float = 0.0) -> list[float]:
    """Evenly spaced ticks every `step` seconds, offset by `phase` (the day/week rung case)."""
    start = math.ceil((low - phase) / step) * step + phase
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
    # Any multiple of a week gets the Monday phase; sub-week day multiples
    # (2d, 3d) have no natural start-of-week to align to, so they stay
    # epoch-uniform -- every day is an equally valid boundary at that scale.
    phase = _WEEK_PHASE if rung.seconds % (7 * _SECONDS_PER_DAY) == 0 else 0.0
    return _uniform_ticks(low, high, rung.seconds, phase)


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


@dataclass(frozen=True)
class _PlotArea:
    """Projector and pixel bounds for one annotation-capable plot area."""

    x_domain: tuple[float, float] | None
    y_domain: tuple[float, float] | None
    project_x: Callable[[float], float] | None
    project_y: Callable[[float], float] | None
    left: float
    right: float
    top: float
    bottom: float


_DASH_ARRAY = {"solid": None, "dashed": "2,2", "dotted": "1,2"}


def _annotation_fragments(
    marks: Sequence[ResolvedAnnotation],
    *,
    area: _PlotArea,
    layer: Layer,
    theme: Theme,
) -> list[str]:
    """Project and emit one annotation layer inside `area`."""
    fragments: list[str] = []
    for mark in marks:
        if mark.layer != layer:
            continue

        if mark.axis == "x":
            domain, project = area.x_domain, area.project_x
        else:
            domain, project = area.y_domain, area.project_y
        if domain is None or project is None:
            raise RuntimeError(f"Cannot render a {mark.axis}-axis annotation for this plot.")

        low, high = domain
        color = html.escape(theme.axis if mark.color is None else mark.color, quote=True)
        if isinstance(mark, ResolvedRule):
            if not low <= mark.at <= high:
                continue
            point = project(mark.at)
            if mark.axis == "x":
                coordinates = (
                    f'x1="{point:.2f}" y1="{area.top:.2f}" x2="{point:.2f}" y2="{area.bottom:.2f}"'
                )
            else:
                coordinates = (
                    f'x1="{area.left:.2f}" y1="{point:.2f}" x2="{area.right:.2f}" y2="{point:.2f}"'
                )
            dash = _DASH_ARRAY[mark.dash]
            dash_attribute = "" if dash is None else f' stroke-dasharray="{dash}"'
            fragments.append(
                f'<line {coordinates} stroke="{color}" stroke-opacity="{mark.opacity:.2f}" '
                f'stroke-width="{mark.width:.2f}"{dash_attribute}/>'
            )
            continue

        start = max(mark.start, low)
        end = min(mark.end, high)
        if start > end:
            continue
        first, second = sorted((project(start), project(end)))
        if mark.axis == "x":
            geometry = (
                f'x="{first:.2f}" y="{area.top:.2f}" width="{second - first:.2f}" '
                f'height="{area.bottom - area.top:.2f}"'
            )
        else:
            geometry = (
                f'x="{area.left:.2f}" y="{first:.2f}" width="{area.right - area.left:.2f}" '
                f'height="{second - first:.2f}"'
            )
        fragments.append(f'<rect {geometry} fill="{color}" fill-opacity="{mark.opacity:.2f}"/>')
    return fragments


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


_MIN_LABEL_GAP = 2.0
# Minimum horizontal gap (px) required between adjacent label boxes for a
# calendar rung to be admitted by `_resolve_collisions`. Non-zero to absorb
# `_CHAR_WIDTH_RATIO`'s approximation error, not because 0px would look fine.


def _label_boxes_at(xs: list[float], texts: list[str], width: int) -> list[tuple[float, float]]:
    """Pixel `(left, right)` extent of each label already projected to `xs`.

    Shared by every collision check in this module -- tick-based (project a
    calendar/numeric position first, via `_label_boxes`) and position-based
    (a grouped super-tick's segment centre, which has no underlying tick to
    project) -- so all of them measure a label identically.
    """
    boxes: list[tuple[float, float]] = []
    for x, text in zip(xs, texts, strict=True):
        label_width = len(text) * 9.0 * _CHAR_WIDTH_RATIO
        anchor = _tick_anchor(x, text, width)
        if anchor == "start":
            left = x
        elif anchor == "end":
            left = x - label_width
        else:
            left = x - label_width / 2
        boxes.append((left, left + label_width))
    return boxes


def _label_boxes(
    ticks: list[float], texts: list[str], project: Callable[[float], float], width: int
) -> list[tuple[float, float]]:
    """Pixel `(left, right)` extent of each tick's label, including `_tick_anchor`'s edge shift.

    Shared by `_select_bare_rung`/`_super_row` and `_render_tick_axis` so a fit
    decision and the actual render can never disagree about where a label sits.
    """
    return _label_boxes_at([project(tick) for tick in ticks], texts, width)


def _fits(boxes: list[tuple[float, float]]) -> bool:
    """Return True when every adjacent pair of label boxes clears `_MIN_LABEL_GAP`."""
    return all(b2[0] - b1[1] >= _MIN_LABEL_GAP for b1, b2 in pairwise(boxes))


def _resolve_collisions(
    xs: list[float], make_texts: Callable[[list[int]], list[str]], width: int
) -> list[str] | None:
    """Resolve label text with a colliding outermost label dropped, or None if none fits.

    `make_texts(kept_indices)` (re)computes label text for whichever subset
    is actually being tried, every time -- dropping an outermost position
    lets it re-anchor context onto whichever position becomes the new first
    or last, so a survivor is never left silently unqualified by a
    neighbour that got dropped. Recomputing from scratch, not slicing the
    full-set labels, is what makes this correct: a bare day number two
    ticks in only reads safely if *its own* predecessor in the rendered set
    shares its month, not the predecessor in the discarded full set.

    Shared by `_select_bare_rung` (sub-row ticks, bare per-index lookup) and
    `_super_row` (grouped labels, recasts via `DateAxis._cascade` over
    group starts) -- one collision-and-drop policy for every row this
    module renders.

    `_tick_anchor` shifts an edge label inward to keep it on-canvas, and
    that shift alone can drag it into its neighbour -- so if the only
    collision involves the first or last position, drop that position's
    *label* (its mark still renders, where the caller draws one) rather
    than rejecting the whole arrangement for one over-dragged edge. Stops
    once fewer than 2 labels would remain, so a 2-position row is never
    blanked down to nothing.
    """
    n = len(xs)

    def arrangement(kept: list[int]) -> list[str] | None:
        kept_texts = make_texts(kept)
        boxes = _label_boxes_at([xs[i] for i in kept], kept_texts, width)
        if not _fits(boxes):
            return None
        out = [""] * n
        for i, text in zip(kept, kept_texts, strict=True):
            out[i] = text
        return out

    full = arrangement(list(range(n)))
    if full is not None:
        return full
    if n < 2:
        return None
    for drop in ([n - 1], [0], [0, n - 1]):
        if n - len(drop) < 2:
            break
        got = arrangement([i for i in range(n) if i not in drop])
        if got is not None:
            return got
    return None


def _bare_label(dt: datetime, step: CalendarStep) -> str:
    """Format `dt` at its own granularity alone, with no coarser context.

    Used only for the two-tier axis's sub-row: coarser context (month or
    year) lives entirely in the grouped super row above it, so the sub-row
    never needs to say more than its own single component.
    """
    if step == "year":
        return str(dt.year)
    if step == "month":
        return _MONTH_ABBR[dt.month - 1]
    return str(dt.day)


def _max_bare_ticks(rung_label: CalendarStep, width: int) -> int:
    """Upper bound on ticks any arrangement of one bare rung could ever admit.

    Lets `_select_bare_rung` skip a rung's datetime/label/collision pass --
    the expensive part of considering it -- once its tick count already
    exceeds what `width` could fit even packed at the rung's own shortest
    possible bare label (`"1"` for day, `"Jan"` for month, `"2024"` for
    year) and the minimum inter-label gap, allowing for the up-to-2 labels
    `_resolve_collisions` may drop from the edges to admit an otherwise
    colliding arrangement. A count beyond this bound (`_select_bare_rung`'s
    call adds the 2-label slack on top of what this returns) can never end
    up admitted -- skipping it changes no selection, only the wasted work
    of computing that it loses.
    """
    min_chars = {"day": 1, "month": 3, "year": 4}[rung_label]
    min_width = min_chars * 9.0 * _CHAR_WIDTH_RATIO
    return max(int((width + _MIN_LABEL_GAP) / (min_width + _MIN_LABEL_GAP)), 1)


def _select_bare_rung(
    low: float,
    high: float,
    target: int,
    *,
    project: Callable[[float], float],
    width: int,
    exclude: frozenset[CalendarStep] = frozenset(),
) -> tuple[_CalendarRung, list[float], list[str]] | None:
    """Pick the calendar rung whose *bare* labels best fit, for the two-tier sub-row.

    Every label is a single bare component (`_bare_label`) with no
    cascading -- narrower than a cascaded label at the same rung, so this
    searches the ladder independently of any cascade-aware selection.

    `exclude` drops whole rung labels (typically `{"year"}`) from
    consideration: a domain spanning multiple years must not let its sub-row
    land on year granularity, or there is nothing coarser left to group by
    in the super row above it -- see `sparkline_axis`.

    Returns None only for a degenerate domain (never for a valid one, since
    `exclude` never empties the whole ladder -- day and month rungs are
    always eligible). Callers passing a non-empty `exclude` should retry
    without it before treating None as truly unresolvable.
    """
    if not (math.isfinite(low) and math.isfinite(high)) or high <= low:
        return None
    best: tuple[tuple[int, int, int], _CalendarRung, list[float], list[str]] | None = None
    for index, rung in enumerate(_CALENDAR_RUNGS):
        if rung.label in exclude:
            continue
        ticks = _rung_ticks(low, high, rung)
        if not ticks or len(ticks) > _max_bare_ticks(rung.label, width) + 2:
            continue
        dts = [datetime.fromtimestamp(t, tz=UTC) for t in ticks]
        texts_all = [_bare_label(dt, rung.label) for dt in dts]
        xs = [project(t) for t in ticks]
        admitted = _resolve_collisions(xs, lambda kept, ta=texts_all: [ta[i] for i in kept], width)
        if admitted is None:
            continue
        shown = sum(1 for text in admitted if text)
        score = (abs(shown - target), -shown, index)
        if best is None or score < best[0]:
            best = (score, rung, ticks, admitted)
    if best is None:
        return None
    return best[1], best[2], best[3]


def _calendar_groups(low: float, high: float, step_months: int) -> list[tuple[datetime, datetime]]:
    """`(start, end)` bounds for every `step_months`-month period overlapping `[low, high]`.

    `step_months=1` gives calendar months, `step_months=12` gives calendar
    years -- both `_super_row`'s grouping levels, so one walk over the same
    `_month_index`/`_month_start` grid (already used by `_month_aligned_ticks`
    for the identical alignment problem on tick positions) covers both
    instead of two near-identical hand-rolled loops.
    """
    high_dt = datetime.fromtimestamp(high, tz=UTC)
    index = _month_index(datetime.fromtimestamp(low, tz=UTC))
    index -= index % step_months  # align to the step's own grid at or before low
    groups: list[tuple[datetime, datetime]] = []
    start = _month_start(index)
    while start < high_dt:
        index += step_months
        end = _month_start(index)
        groups.append((start, end))
        start = end
    return groups


def _super_row(
    sub_step: CalendarStep,
    low: float,
    high: float,
    *,
    project: Callable[[float], float],
    width: int,
) -> tuple[list[float], list[str]] | None:
    """Return grouped super-tick centres and labels for the two-tier axis's coarser row.

    Groups by month when the sub-row is daily, by year when it is monthly --
    the one level up `sub_step` implies. Returns None only when there is
    nothing coarser to group a yearly sub-row by (nothing else does: even a
    single group still renders, one label centred over the whole visible
    span -- see `sparkline_axis`, which always uses the two-tier layout
    rather than falling back to a single row when a group exists).

    Uses `_resolve_collisions` exactly as the sub-row does: a group's label
    centres over its true, domain-clipped pixel span (not its full calendar
    extent -- a January that only starts on the 17th still centres over the
    shorter visible sliver), and the same collision-and-drop policy governs
    it, recasting via `DateAxis._cascade` so a surviving label after a drop
    is never left unqualified by a neighbour that got dropped.
    """
    if sub_step == "day":
        groups = _calendar_groups(low, high, 1)
        group_step: CalendarStep = "month"
    elif sub_step == "month":
        groups = _calendar_groups(low, high, 12)
        group_step = "year"
    else:
        return None
    if not groups:
        return None
    starts = [start for start, _ in groups]
    centers = [
        project((max(start.timestamp(), low) + min(end.timestamp(), high)) / 2)
        for start, end in groups
    ]
    label = DateAxis(step=group_step)
    multi_year = len({start.year for start in starts}) > 1
    admitted = _resolve_collisions(
        centers,
        lambda kept: label._cascade([starts[i] for i in kept], multi_year=multi_year),
        width,
    )
    if admitted is None or not any(admitted):
        return None
    return centers, admitted


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


def _esc(text: str) -> str:
    """Escape `&`, `<` and `>` for safe embedding as `<text>` element content.

    Every tick, endpoint and legend label ultimately traces back to
    caller-controlled data (a `Format` callable's output, or a raw
    `series=` value via `str()`) -- unescaped, a label containing `&`/`<`/`>`
    would emit malformed SVG. Quotes are left alone; nothing here writes
    label text into an attribute value.
    """
    return html.escape(text, quote=False)


CLIP_MARGIN = 18
# Pixel reserve on each side of a forest bar's plotting region when its
# domain bucket contains clipped values -- the strip a `_fade_cap` bleeds
# into. Shared with `spec.Forest`, which decides per bucket whether to
# reserve it at all.


def _fade_id(color: str, flip: bool) -> str:
    """Return a deterministic id for a `_fade_cap` gradient.

    Same collision reasoning as `_hard_clip_id`: SVG ids share one
    namespace across an embedding page, so the id is built from the
    gradient's full content -- its colour and direction. Two calls share
    an id exactly when their gradients are identical, which makes any
    collision harmless.
    """
    safe = "".join(c if c.isalnum() else "_" for c in color)
    return f"fade{'l' if flip else 'r'}_{safe}"


def _fade_cap(
    x: float, top: float, fade_width: float, bar_height: int, color: str, *, flip: bool
) -> str:
    """Continue a clipped bar into the reserved margin as a gradient fade.

    The rectangle starts at the domain edge the bar clipped against and
    fades from the bar's own fill to transparent across `fade_width` px,
    reading as "extends beyond the axis" rather than ending abruptly.
    `flip=True` fades leftward for a low-edge clip.
    """
    gid = _fade_id(color, flip)
    x_attrs = 'x1="1" y1="0" x2="0" y2="0"' if flip else 'x1="0" y1="0" x2="1" y2="0"'
    return (
        f'<defs><linearGradient id="{gid}" {x_attrs}>'
        f'<stop offset="0" stop-color="{color}" stop-opacity="0.75"/>'
        f'<stop offset="1" stop-color="{color}" stop-opacity="0"/>'
        f"</linearGradient></defs>"
        f'<rect x="{x:.2f}" y="{top:.2f}" width="{fade_width:.2f}" '
        f'height="{bar_height}" fill="url(#{gid})"/>'
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
    inset: int = 3,
    margin: int = 0,
    annotations: Sequence[ResolvedAnnotation] = (),
) -> str:
    """Render one interval as an inline SVG bar.

    The bar spans the interval, a light tick marks the point estimate, and a
    dashed line marks `ref` when it falls inside `domain`.  A bound outside the
    domain, including an unbounded one, is clipped visibly rather than
    silently: with `margin=0` it draws to the edge with a triangular cap;
    with `margin > 0` the bars plot against the inner
    `[margin, width - margin]` region and a clipped bound continues into
    the margin as a gradient fade to transparent (see `_fade_cap`).

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
    annotations
        Resolved x-axis rules and bands rendered around the existing bar.
    width, height, bar_height, inset
        Geometry in pixels.
    margin
        Pixel reserve on each side of the plotting region for the fade
        treatment of clipped bounds. `0` (the default) keeps the full
        width for bars and marks clipping with triangular caps instead.

    Returns
    -------
    str
        A complete ``<svg>`` element.
    """
    low, high = domain
    plot_width = width - 2 * margin
    inner_project = _projector(domain, plot_width, inset)

    def project(v: float) -> float:
        return margin + inner_project(v)

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

    if margin:
        fade_width = float(margin - inset)
        if clipped_high:
            parts.append(_fade_cap(x1, top, fade_width, bar_height, color, flip=False))
        if clipped_low:
            parts.append(_fade_cap(x0 - fade_width, top, fade_width, bar_height, color, flip=True))
    else:
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
    if not annotations:
        return _svg(width, height, "".join(parts))
    area = _PlotArea(
        x_domain=domain,
        y_domain=None,
        project_x=project,
        project_y=None,
        left=margin + inset,
        right=width - margin - inset,
        top=0,
        bottom=height,
    )
    body = (
        _annotation_fragments(annotations, area=area, layer="underlay", theme=theme)
        + parts
        + _annotation_fragments(annotations, area=area, layer="overlay", theme=theme)
    )
    return _svg(width, height, "".join(body))


def _render_tick_axis(
    ticks: list[float],
    *,
    project: Callable[[float], float],
    texts: list[str],
    baseline: float,
    height: int,
    width: int,
    theme: Theme,
) -> list[str]:
    """Render each tick as a mark plus its (already formatted) label.

    `forest_axis` and `sparkline_axis` draw an identical tick mark and label
    per position; only the tick set and how `texts` was produced differ -- a
    plain `Format` call for `forest_axis`, `_select_bare_rung`'s bare
    per-component text (or `_super_row`'s grouped `DateAxis._cascade` call,
    for the two-tier super row) for a temporal `sparkline_axis`. `texts`
    must be the same length as `ticks`; a blank entry draws the tick mark
    with no label, which is how `_resolve_collisions` (via
    `_select_bare_rung`/`_super_row`) resolves an edge-label collision.
    """
    parts: list[str] = []
    for tick, text in zip(ticks, texts, strict=True):
        tick_x = project(tick)
        parts.append(
            f'<line x1="{tick_x:.2f}" y1="{baseline:.2f}" x2="{tick_x:.2f}" '
            f'y2="{baseline + 3:.2f}" stroke="{theme.axis}" stroke-width="0.75"/>'
        )
        if text:
            anchor = _tick_anchor(tick_x, text, width)
            parts.append(
                f'<text x="{tick_x:.2f}" y="{height - 2:.2f}" fill="{theme.axis}" '
                f'font-size="9" text-anchor="{anchor}">{_esc(text)}</text>'
            )
    return parts


def _dedupe_consecutive_labels(texts: list[str]) -> list[str]:
    """Blank any label whose text repeats its predecessor's, keeping the tick mark.

    A repeated label conveys no information and reads as a rendering bug --
    most often a numeric domain whose tick spacing is finer than the
    formatter's own precision (`Number(decimals=0)` rounding ticks at 0,
    0.25, 0.5, 0.75, 1.0 to "0", "0", "0", "1", "1"). Ticks stay exactly
    where `nice_ticks` put them; only the misleadingly-repeated text is
    dropped, mirroring how `_resolve_collisions` resolves a calendar-tick collision.
    Not used on `DateAxis.labels()`'s output -- its own cascade already
    guarantees no two adjacent calendar ticks format identically.
    """
    out: list[str] = []
    prev: str | None = None
    for text in texts:
        if text and text == prev:
            out.append("")
        else:
            out.append(text)
            if text:
                prev = text
    return out


_SUPER_ROW_OFFSET = 12.0
# Extra px reserved below the sub-row's own label baseline for the grouped
# month/year row -- see `_render_two_tier_axis`.


def _render_two_tier_axis(
    sub_ticks: list[float],
    sub_texts: list[str],
    super_centers: list[float],
    super_texts: list[str],
    *,
    project: Callable[[float], float],
    baseline: float,
    sub_height: int,
    width: int,
    theme: Theme,
) -> list[str]:
    """Render the two-row temporal axis.

    Bare sub-ticks near the spine, grouped month/year labels further out
    with no tick mark of their own, centred over the true pixel span each
    group covers.

    The sub-row is exactly `_render_tick_axis` at `height=sub_height` --
    unlabelled ticks read no differently switching between a one-row and a
    two-row axis, so it is not reimplemented here. The super row is a fixed
    offset further out, text-only.
    """
    parts = _render_tick_axis(
        sub_ticks,
        project=project,
        texts=sub_texts,
        baseline=baseline,
        height=sub_height,
        width=width,
        theme=theme,
    )
    super_y = sub_height - 2 + _SUPER_ROW_OFFSET
    for x, text in zip(super_centers, super_texts, strict=True):
        if text:
            parts.append(
                f'<text x="{x:.2f}" y="{super_y:.2f}" fill="{theme.muted}" '
                f'font-size="9" text-anchor="{_tick_anchor(x, text, width)}">{_esc(text)}</text>'
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
    margin: int = 0,
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
    margin
        Pixel reserve on each side matching the bars' own `margin`; the
        axis spine and projection span only the inner region so ticks
        stay aligned with the bars.
    target_ticks
        Approximate number of ticks wanted.

    Returns
    -------
    str
        A complete ``<svg>`` element.
    """
    low, high = domain
    inner_project = _projector(domain, width - 2 * margin, inset)

    def project(v: float) -> float:
        return margin + inner_project(v)

    baseline = 4.0
    parts = [
        f'<line x1="{margin + inset}" y1="{baseline:.2f}" '
        f'x2="{width - margin - inset}" y2="{baseline:.2f}" '
        f'stroke="{theme.axis}" stroke-width="0.75"/>'
    ]
    if low <= ref <= high:
        ref_x = project(ref)
        parts.append(
            f'<line x1="{ref_x:.2f}" y1="0" x2="{ref_x:.2f}" y2="{baseline:.2f}" '
            f'stroke="{theme.axis}" stroke-width="1" stroke-dasharray="2,2"/>'
        )
    ticks = nice_ticks(low, high, target_ticks)
    texts = _dedupe_consecutive_labels([fmt(t) for t in ticks])
    parts.extend(
        _render_tick_axis(
            ticks,
            project=project,
            texts=texts,
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


class Trace(NamedTuple):
    """One overlaid series inside a multi-series sparkline cell.

    Parameters
    ----------
    x, y
        Parallel point positions and estimates, equal length.
    lower, upper
        Parallel interval bounds, equal length to `x`/`y`.
    color
        Line, ribbon, endpoint, ghost-trace and clip-cap colour for this
        trace alone. The reference line uses `sparkline_multi`'s
        `ref_color`, not any trace's `color`.
    show_ribbon
        Draw this trace's uncertainty ribbon. `False` still draws the
        line; it only withholds the ribbon polygon.
    label
        Series identity, for the caller's legend. Unused by rendering.
    """

    x: Sequence[float | None]
    y: Sequence[float | None]
    lower: Sequence[float | None]
    upper: Sequence[float | None]
    color: str
    show_ribbon: bool
    label: str


def sparkline_multi(
    traces: Sequence[Trace],
    *,
    x_domain: tuple[float, float],
    domain: tuple[float, float],
    ref: float | None,
    ref_color: str,
    fmt: Format,
    width: int = 220,
    height: int = 30,
    inset: int = 3,
    show_endpoint: bool = True,
    endpoint_width: int = 44,
    show_clip_indicators: bool = True,
    annotations: Sequence[ResolvedAnnotation] = (),
    theme: Theme = DEFAULT,
) -> str:
    """Render one or more overlaid series as an inline SVG line plot.

    Generalises `sparkline_bar` to `N` traces sharing one `x_domain` and
    `domain`. All ribbons draw first (each in its own trace colour, gated
    by that trace's `show_ribbon`), then the single dashed reference line
    in `ref_color`, then all series lines on top, then one endpoint label
    per trace that has a line. Clipping, the ghost trace and the clip-cap
    marks are computed independently per trace and drawn in that trace's
    colour, so two traces clipping at overlapping x on the same edge
    still produce two distinct cap pairs rather than one merged pair in
    one trace's colour. The `<clipPath>` itself is geometry-derived
    (`domain`/`height`/`width` only) and is therefore shared and emitted
    at most once, regardless of how many traces clip.

    Parameters
    ----------
    traces
        One `Trace` per overlaid series. Each trace's gaps, out-of-domain
        clipping and clip-cap merging are independent of every other
        trace's -- misaligned gaps break each trace's own runs only.
    x_domain
        Shared x-domain for every trace's `x`. Always table-wide, never
        padded per row.
    domain
        Shared y-domain for every trace's `y`/`lower`/`upper` and for
        `ref`.
    ref
        Reference value for the horizontal dashed line, or `None` to
        draw no reference line.
    ref_color
        Colour of the single shared reference line.
    fmt
        Formats each trace's endpoint value label.
    width, height, inset
        Geometry in pixels.
    show_endpoint
        Draw each trace's endpoint value label. Every label anchors at
        the same `x=right_edge`; with several traces this is
        all-or-nothing and uncoordinated across traces -- two traces
        ending at nearby y-values render overlapping text, with no
        automatic vertical nudge (unlike `sparkline_axis`'s two-tier
        collision handling). Keep endpoints apart in the data, or turn
        this off, when traces crowd near the same value.
    endpoint_width
        Fixed pixel reserve carved out of `width` for endpoint labels,
        independent of any label's length. `sparkline_axis` must be given
        the same `width`, `inset`, `show_endpoint` and `endpoint_width`
        so its ticks project over the identical inner width and land
        under their points.
    show_clip_indicators
        Draw the clip-cap marks. The line/ribbon clipping and the ghost
        trace happen regardless of this flag -- turning it off only
        removes the cap marks, never the underlying clipping or the
        true-trajectory ghost.
    annotations
        Resolved x- and y-axis rules and bands rendered once around all traces.
    theme
        Supplies the fallback axis colour for annotations with `color=None`.

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

    per_trace = [
        (
            trace,
            _band_runs(trace.x, trace.y, trace.lower, trace.upper) if trace.show_ribbon else [],
            _line_runs(trace.x, trace.y),
        )
        for trace in traces
    ]
    any_runs = any(band_runs or line_runs for _, band_runs, line_runs in per_trace)

    ghost_parts: list[str] = []
    parts: list[str] = []
    trace_spans: list[list[tuple[float, float, str]]] = [[] for _ in per_trace]

    for (trace, band_runs, _), spans in zip(per_trace, trace_spans, strict=True):
        for run in band_runs:
            ghost, real, run_spans = _render_band_run(
                run,
                low=low,
                high=high,
                project_x=project_x,
                project_y=project_y,
                color=trace.color,
                clip_id=clip_id,
            )
            ghost_parts.extend(ghost)
            parts.extend(real)
            spans.extend(run_spans)

    if ref is not None and any_runs and low <= ref <= high:
        ref_y = project_y(ref)
        parts.append(
            f'<line x1="{inset}" y1="{ref_y:.2f}" x2="{right_edge}" y2="{ref_y:.2f}" '
            f'stroke="{ref_color}" stroke-width="1" stroke-dasharray="2,2"/>'
        )

    for (trace, _, line_runs), spans in zip(per_trace, trace_spans, strict=True):
        for run in line_runs:
            ghost, real, run_spans = _render_line_run(
                run,
                low=low,
                high=high,
                project_x=project_x,
                project_y=project_y,
                color=trace.color,
                clip_id=clip_id,
            )
            ghost_parts.extend(ghost)
            parts.extend(real)
            spans.extend(run_spans)

    for trace, _, line_runs in per_trace:
        if line_runs and show_endpoint:
            _, ey = line_runs[-1][-1]
            ey_px = project_y(_clamp(ey, low, high))
            label = _clip_label(fmt(ey), max(endpoint_width - 4, 4), 9.0)
            parts.append(
                f'<text x="{right_edge}" y="{ey_px + 3:.2f}" fill="{trace.color}" '
                f'font-size="9" text-anchor="end">{_esc(label)}</text>'
            )

    cap_parts: list[str] = []
    for (trace, _, __), spans in zip(per_trace, trace_spans, strict=True):
        if show_clip_indicators and spans:
            for start_x, end_x, edge in _merge_spans(spans):
                edge_y = top_edge if edge == "high" else bottom_edge
                for dy in (-0.5, 0.5):
                    cap_parts.append(
                        f'<line x1="{start_x - 3.0:.2f}" y1="{edge_y + dy:.2f}" '
                        f'x2="{end_x + 3.0:.2f}" y2="{edge_y + dy:.2f}" '
                        f'stroke="{trace.color}" stroke-width="0.5" stroke-opacity="0.45"/>'
                    )

    body = ghost_parts + parts + cap_parts
    if any(spans for spans in trace_spans):
        body.insert(
            0,
            f'<clipPath id="{clip_id}"><rect x="0" y="{top_edge:.2f}" width="{width}" '
            f'height="{bottom_edge - top_edge:.2f}"/></clipPath>',
        )
    if annotations:
        area = _PlotArea(
            x_domain=x_domain,
            y_domain=domain,
            project_x=project_x,
            project_y=project_y,
            left=inset,
            right=plot_width - inset,
            top=top_edge,
            bottom=bottom_edge,
        )
        body = (
            _annotation_fragments(annotations, area=area, layer="underlay", theme=theme)
            + body
            + _annotation_fragments(annotations, area=area, layer="overlay", theme=theme)
        )
    return _svg(width, height, "".join(body))


def sparkline_bar(
    x: Sequence[float | None],
    y: Sequence[float | None],
    lower: Sequence[float | None],
    upper: Sequence[float | None],
    *,
    x_domain: tuple[float, float],
    domain: tuple[float, float],
    ref: float | None,
    color: str,
    fmt: Format,
    width: int = 220,
    height: int = 30,
    inset: int = 3,
    show_endpoint: bool = True,
    endpoint_width: int = 44,
    show_clip_indicators: bool = True,
    annotations: Sequence[ResolvedAnnotation] = (),
    theme: Theme = DEFAULT,
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

    A one-trace delegate to `sparkline_multi`; kept for the ~20 existing
    call sites that pass flat parallel arrays and a single `color`.

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
        Reference value for the horizontal dashed line, or `None` to
        draw no reference line.
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
    annotations
        Resolved x- and y-axis rules and bands forwarded once to `sparkline_multi`.
    theme
        Supplies the fallback axis colour for annotations with `color=None`.

    Returns
    -------
    str
        A complete ``<svg>`` element.
    """
    return sparkline_multi(
        [Trace(x=x, y=y, lower=lower, upper=upper, color=color, show_ribbon=True, label="")],
        x_domain=x_domain,
        domain=domain,
        ref=ref,
        ref_color=color,
        fmt=fmt,
        width=width,
        height=height,
        inset=inset,
        show_endpoint=show_endpoint,
        endpoint_width=endpoint_width,
        show_clip_indicators=show_clip_indicators,
        annotations=annotations,
        theme=theme,
    )


_LEGEND_OFFSET = 20.0
# Vertical space reserved above the axis spine for the swatch+label chip
# row when `sparkline_axis` is given `legend=`. The existing axis content
# (ticks, temporal two-tier rows) renders unchanged, wrapped in a
# translate-down `<g>`, rather than every internal y-coordinate being
# recomputed against a shifted baseline.
_LEGEND_SWATCH = 8.0
_LEGEND_SWATCH_GAP = 4.0
_LEGEND_CHIP_GAP = 14.0
_LEGEND_MAX_LABEL_WIDTH = 60.0


def _render_legend(
    entries: Sequence[tuple[str, str]], *, width: int, inset: int, theme: Theme
) -> list[str]:
    """Render one swatch+label chip per `(label, color)` entry, left to right.

    Each label is ellipsized to `_LEGEND_MAX_LABEL_WIDTH` so one long name
    cannot dominate the row; a chip that still would not fit the remaining
    width -- including every chip after it -- is dropped entirely rather
    than overflowing the canvas.
    """
    parts: list[str] = []
    x = float(inset)
    right = width - inset
    y_swatch = (_LEGEND_OFFSET - _LEGEND_SWATCH) / 2
    y_text = _LEGEND_OFFSET / 2 + 3.0
    for label, color in entries:
        text = _clip_label(label, _LEGEND_MAX_LABEL_WIDTH, 9.0)
        text_width = len(text) * 9.0 * _CHAR_WIDTH_RATIO
        chip_width = _LEGEND_SWATCH + _LEGEND_SWATCH_GAP + text_width
        if x + chip_width > right:
            break
        parts.append(
            f'<rect x="{x:.2f}" y="{y_swatch:.2f}" width="{_LEGEND_SWATCH:.2f}" '
            f'height="{_LEGEND_SWATCH:.2f}" fill="{color}"/>'
        )
        text_x = x + _LEGEND_SWATCH + _LEGEND_SWATCH_GAP
        parts.append(
            f'<text x="{text_x:.2f}" y="{y_text:.2f}" fill="{theme.text}" '
            f'font-size="9" text-anchor="start">{_esc(text)}</text>'
        )
        x += chip_width + _LEGEND_CHIP_GAP
    return parts


def _wrap_axis_with_legend(
    width: int,
    content_height: int,
    body: str,
    *,
    legend: Sequence[tuple[str, str]] | None,
    inset: int,
    theme: Theme,
) -> str:
    """Finish `sparkline_axis`: prepend a legend row and grow `height`, or return `body` as-is."""
    if not legend:
        return _svg(width, content_height, body)
    chips = _render_legend(legend, width=width, inset=inset, theme=theme)
    offset = _LEGEND_OFFSET
    return _svg(
        width,
        content_height + int(offset),
        "".join(chips) + f'<g transform="translate(0, {offset:.2f})">{body}</g>',
    )


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
    legend: Sequence[tuple[str, str]] | None = None,
) -> str:
    """Render the shared x-axis footer for a column of sparkline rows.

    Parameters
    ----------
    x_domain
        Shared x-domain, table-wide -- see `sparkline_bar`'s `x_domain`.
    fmt
        Callable used to label each tick. When `temporal` is True and `fmt`
        is a `DateAxis`, the axis always renders two rows: bare sub-ticks
        near the spine (`_select_bare_rung`) plus a grouped month/year row
        further out (`_super_row`), each group centred over its true pixel
        span with no tick mark of its own -- even a domain confined to a
        single month or year still gets one group label, centred over the
        whole width, rather than folding that context into a tick label
        inline. The only case with no super row is a domain that itself
        spans years at year-tick granularity, where nothing is coarser to
        group by; that renders bare year ticks alone. Any other callable,
        temporal or not, is called once per tick exactly as given.
    theme
        Supplies the axis colour and label size.
    temporal
        Use calendar-aware selection (real month/quarter/year boundaries)
        instead of `nice_ticks` (decimal steps).
    width, height, inset
        Geometry in pixels. A two-row axis (see `fmt` above) adds a fixed
        offset to `height` for the grouped row; that addition is not
        configurable.
    target_ticks
        Approximate number of ticks wanted.
    show_endpoint, endpoint_width
        Must be given the same values passed to `sparkline_bar` for the same
        rows: both carve the same fixed reserve out of `width` so ticks
        project over the identical inner width and land under their points.
    legend
        `(label, color)` pairs for a series-overlay column, drawn as a
        swatch+label chip row above the axis spine; `height` grows by the
        reserved offset when set. `None` (the default) omits the row
        entirely and leaves `height` unchanged. Ticks project over the
        same inner width either way -- the legend only adds vertical
        space, never changes horizontal geometry.

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
    if temporal and isinstance(fmt, DateAxis):
        if not (math.isfinite(low) and math.isfinite(high)) or high < low:
            ticks, texts = [], []
        elif high == low:
            ticks, texts = [low], [fmt(low)]
        else:
            # A domain spanning multiple years must not let its sub-row land
            # on year granularity -- there would be nothing coarser left to
            # group by in the super row above it. Falls back to allowing it
            # only if excluding it leaves no rung that fits at all.
            exclude: frozenset[CalendarStep] = (
                frozenset({"year"}) if len(_calendar_groups(low, high, 12)) > 1 else frozenset()
            )
            bare = _select_bare_rung(
                low, high, target_ticks, project=project, width=width, exclude=exclude
            )
            if bare is None and exclude:
                bare = _select_bare_rung(low, high, target_ticks, project=project, width=width)
            if bare is None:
                ticks, texts = [], []
            else:
                rung, ticks, texts = bare
                super_row = _super_row(rung.label, low, high, project=project, width=width)
                if super_row is not None:
                    super_centers, super_texts = super_row
                    parts.extend(
                        _render_two_tier_axis(
                            ticks,
                            texts,
                            super_centers,
                            super_texts,
                            project=project,
                            baseline=baseline,
                            sub_height=height,
                            width=width,
                            theme=theme,
                        )
                    )
                    return _wrap_axis_with_legend(
                        width,
                        height + int(_SUPER_ROW_OFFSET),
                        "".join(parts),
                        legend=legend,
                        inset=inset,
                        theme=theme,
                    )
                # No super row could be built -- nothing coarser for a
                # year-granular sub-row, or (in principle) a collision
                # `_resolve_collisions` can't clear by dropping an edge.
                # Fall back to cascaded labels, not the bare sub-row text:
                # bare numbers alone carry no month/year context at all,
                # which is worse than the single-row cascade design this
                # replaced ever rendered.
                texts = DateAxis(step=rung.label).labels(ticks)
    elif temporal:
        ticks = calendar_ticks(low, high, target_ticks)
        texts = [fmt(t) for t in ticks]
    else:
        ticks = nice_ticks(low, high, target_ticks)
        texts = _dedupe_consecutive_labels([fmt(t) for t in ticks])
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
            texts=texts,
            baseline=baseline,
            height=height,
            width=width,
            theme=theme,
        )
    )
    return _wrap_axis_with_legend(
        width, height, "".join(parts), legend=legend, inset=inset, theme=theme
    )
