"""Timeline events: cross-card markers for releases, campaigns, and incidents.

A `TimelineEvent` is declared once and fanned out to every card it affects
(`events_for`), each becoming an ordinary `coeftable.cards.Event` on that
card's captions and plot rules. `timeline_strip` renders a standalone,
full-width index of every event -- not a globally aligned axis, since graph
cards sit at different canvas positions and a shared x-axis across the tree
would misrepresent that.
"""

from __future__ import annotations

import html
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import cast

from coeftable.annotations import Dash
from coeftable.cards import Event, InlineSvg
from coeftable.errors import SpecError
from coeftable.svg import _CHAR_WIDTH_RATIO, _clip_label, _projector
from coeftable.theme import Theme

_DASHES = ("solid", "dashed", "dotted")
_DASH_ARRAY = {"solid": None, "dashed": "2,2", "dotted": "1,2"}

_INSET = 8
_TITLE_Y = 13.0
_LABEL_ROWS = (26.0, 44.0)
_SPINE_MARGIN = 24.0
_TICK_LEN = 4.0
_TICK_LABEL_OFFSET = 14.0
_CIRCLE_R = 3.5
_LABEL_FONT_SIZE = 10.0

# Half of the event label's stroke-width halo (`stroke-width="3"`), which
# paints outside the glyphs' own outline on every side. Kept clear of both
# canvas edges so the halo itself never bleeds past the declared width.
_LABEL_HALO = 1.5

# `_projector` divides the plotting span by `width - 2 * _INSET`; at or
# below this the span collapses to zero or goes negative, producing an
# inverted or degenerate projection. `_MIN_WIDTH` instead leaves a usable
# span of `2 * _INSET` px between the two insets.
_MIN_WIDTH = 4 * _INSET

# The spine sits `_SPINE_MARGIN` above the bottom edge. A usable strip needs
# the spine to clear the lower label row -- including the 4px gap where each
# event's stem begins -- with enough headroom left over to also fit the
# tick labels rendered `_TICK_LABEL_OFFSET` below the spine.
_MIN_HEIGHT = int(_LABEL_ROWS[-1]) + 4 + int(_SPINE_MARGIN) + int(_TICK_LABEL_OFFSET)


def _non_empty_str(value: object, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise SpecError(f"{name} must be a non-empty str")


def _finite(value: object, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecError(f"{name} must be a number, got {type(value).__name__}")
    if not math.isfinite(value):
        raise SpecError(f"{name} must be finite")


def _member(value: object, allowed: tuple[str, ...], *, name: str) -> None:
    if not isinstance(value, str) or value not in allowed:
        raise SpecError(f"{name} must be one of {allowed}, got {value!r}")


def _canonical(value: object, *, name: str) -> tuple[object, ...]:
    """Snapshot an input sequence while presenting malformed inputs as specs."""
    if isinstance(value, (str, bytes)):
        raise SpecError(f"{name} must be a sequence of entries, not a string")
    try:
        return tuple(cast(Iterable[object], value))
    except TypeError as error:
        raise SpecError(f"{name} must be a sequence") from error


def _esc(text: str) -> str:
    """Escape text for safe embedding as SVG attribute or element content."""
    return html.escape(text, quote=True)


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    """One global event, fanned out to every card it affects.

    Mirrors `coeftable.cards.Event` (`label`, `color`, `dash`, `at`) and adds
    `affects`: the node ids that receive this event's marker, on both the
    affected card's plot/captions (`events_for`) and the standalone timeline
    strip (`timeline_strip`).
    """

    at: float
    label: str
    color: str
    affects: tuple[str, ...]
    dash: Dash = "dotted"

    def __post_init__(self) -> None:
        """Validate fields."""
        _finite(self.at, name="TimelineEvent.at")
        _non_empty_str(self.label, name="TimelineEvent.label")
        _non_empty_str(self.color, name="TimelineEvent.color")
        affects = _canonical(self.affects, name="TimelineEvent.affects")
        object.__setattr__(self, "affects", affects)
        if not affects:
            raise SpecError("TimelineEvent.affects must not be empty")
        for index, node_id in enumerate(affects):
            _non_empty_str(node_id, name=f"TimelineEvent.affects[{index}]")
        if len(set(affects)) != len(affects):
            raise SpecError("TimelineEvent.affects must not contain duplicates")
        _member(self.dash, _DASHES, name="TimelineEvent.dash")


def events_for(events: Sequence[TimelineEvent], card_id: str) -> tuple[Event, ...]:
    """Select the events affecting `card_id`, mapped to card-facing `Event`s.

    Declaration order is preserved; a `card_id` matched by no event's
    `affects` returns an empty tuple.
    """
    return tuple(
        Event(label=event.label, color=event.color, dash=event.dash, at=event.at)
        for event in events
        if card_id in event.affects
    )


def _domain(value: tuple[float, float], *, name: str) -> tuple[float, float]:
    low, high = value
    _finite(low, name=f"{name}[0]")
    _finite(high, name=f"{name}[1]")
    if high < low:
        raise SpecError(f"{name} must be ordered (low <= high)")
    return (float(low), float(high))


def _validate_strip_size(width: int, height: int) -> None:
    if width <= _MIN_WIDTH:
        raise SpecError(f"timeline_strip.width must be greater than {_MIN_WIDTH}, got {width}")
    if height <= _MIN_HEIGHT:
        raise SpecError(f"timeline_strip.height must be greater than {_MIN_HEIGHT}, got {height}")


def _label_anchor_and_text(x: float, label: str, width: int) -> tuple[str, str]:
    """Choose a text-anchor and (possibly truncated) label for a pin at pixel `x`.

    Centring every label on its projected coordinate clips events near
    either domain edge -- the strip's viewport doesn't grow to fit text, so
    a boundary event's centred label runs straight off the canvas.

    When centring spills past exactly one edge, anchor away from it: at the
    start for a left spill, at the end for a right spill. When it spills
    past BOTH edges the label is wider than the strip, so neither side can
    show it whole; anchor to whichever side has more room, since anchoring
    to the cramped side would truncate to almost nothing. Truncate with an
    ellipsis as a last resort when the chosen side still cannot fit it.

    The pin, its stem, and its dot stay on `x` regardless -- only the text
    anchor moves.
    """
    half = len(label) * _LABEL_FONT_SIZE * _CHAR_WIDTH_RATIO / 2
    low, high = _LABEL_HALO, width - _LABEL_HALO
    overflows_left = x - half < low
    overflows_right = x + half > high
    if overflows_left and overflows_right:
        start_budget, end_budget = high - x, x - low
        if end_budget >= start_budget:
            anchor, budget = "end", end_budget
        else:
            anchor, budget = "start", start_budget
    elif overflows_left:
        anchor, budget = "start", high - x
    elif overflows_right:
        anchor, budget = "end", x - low
    else:
        anchor, budget = "middle", 2 * min(x - low, high - x)
    return anchor, _clip_label(label, max(budget, 0.0), _LABEL_FONT_SIZE)


def timeline_strip(
    events: Sequence[TimelineEvent],
    *,
    x_domain: tuple[float, float],
    width: int,
    theme: Theme,
    height: int = 96,
    title: str = "Timeline \u2014 releases, campaigns, incidents",
) -> InlineSvg:
    """Render a full-width strip indexing every event over `x_domain`.

    Draws a horizontal spine with one tick per integer step across
    `x_domain`, and per event a colour-matched dashed stem from a staggered
    label height down to an `r=3.5` dot on the spine. Labels alternate
    between two heights by event index to reduce collisions, and carry a
    `theme.surface` stroke halo so they stay legible over the spine and
    ticks. `title` renders as a caption at the top.

    Projects `at` to pixels with `coeftable.svg`'s own inset convention, so a
    marker on a card sparkline and a pin here agree. Raises `SpecError`
    naming the offending event's label if any `at` falls outside `x_domain`
    -- painting outside the declared box would break exact measurement.
    """
    events = tuple(events)
    low, high = _domain(x_domain, name="timeline_strip.x_domain")
    _validate_strip_size(width, height)
    project = _projector((low, high), width, _INSET)
    spine_y = height - _SPINE_MARGIN

    parts = [
        f'<text x="{_INSET:.2f}" y="{_TITLE_Y:.2f}" fill="{_esc(theme.text)}" '
        f'font-size="11" font-weight="600">{_esc(title)}</text>',
        f'<line x1="{_INSET:.2f}" y1="{spine_y:.2f}" x2="{width - _INSET:.2f}" '
        f'y2="{spine_y:.2f}" stroke="{_esc(theme.axis)}" stroke-width="1"/>',
    ]

    for tick in range(math.ceil(low), math.floor(high) + 1):
        x = project(float(tick))
        parts.append(
            f'<line x1="{x:.2f}" y1="{spine_y:.2f}" x2="{x:.2f}" '
            f'y2="{spine_y + _TICK_LEN:.2f}" stroke="{_esc(theme.axis)}" stroke-width="0.75"/>'
        )
        parts.append(
            f'<text x="{x:.2f}" y="{spine_y + _TICK_LABEL_OFFSET:.2f}" '
            f'fill="{_esc(theme.axis)}" font-size="9" text-anchor="middle">W{tick + 1}</text>'
        )

    for index, event in enumerate(events):
        if not low <= event.at <= high:
            raise SpecError(
                f"TimelineEvent {event.label!r} at={event.at} is outside x_domain {x_domain}"
            )
        x = project(event.at)
        label_y = _LABEL_ROWS[index % len(_LABEL_ROWS)]
        dash = _DASH_ARRAY[event.dash]
        dash_attribute = "" if dash is None else f' stroke-dasharray="{dash}"'
        parts.append(
            f'<line x1="{x:.2f}" y1="{label_y + 4:.2f}" x2="{x:.2f}" y2="{spine_y:.2f}" '
            f'stroke="{_esc(event.color)}" stroke-width="1"{dash_attribute}/>'
        )
        parts.append(
            f'<circle cx="{x:.2f}" cy="{spine_y:.2f}" r="{_CIRCLE_R:.1f}" '
            f'fill="{_esc(event.color)}"/>'
        )
        label = f"{event.label} \u00b7 W{int(event.at) + 1}"
        anchor, label = _label_anchor_and_text(x, label, width)
        parts.append(
            f'<text x="{x:.2f}" y="{label_y:.2f}" fill="{_esc(event.color)}" '
            f'font-size="{_LABEL_FONT_SIZE:.0f}" font-weight="700" text-anchor="{anchor}" '
            f'stroke="{_esc(theme.surface)}" stroke-width="3" '
            f'style="paint-order:stroke">{_esc(label)}</text>'
        )

    body = "".join(parts)
    svg = (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg">{body}</svg>'
    )
    return InlineSvg(svg, width=width, height=height)
