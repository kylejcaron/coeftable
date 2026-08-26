"""Built-in card regions resolved from author inputs into adornments."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol, cast, runtime_checkable

from coeftable.annotations import (
    Dash,
    ResolvedAnnotation,
    ResolvedBand,
    ResolvedRule,
    domain_values,
)
from coeftable.cards.adornments import (
    _DASHES,
    Adornment,
    Badge,
    CaptionRow,
    InlineSvg,
    KeyValuePopover,
    Legend,
    MetricValue,
    RuleStrip,
    SelectControl,
    TextBlock,
    _require_member,
    _require_nonempty_str,
    _require_optional_str,
    _require_str,
)
from coeftable.cards.chrome import CardChrome
from coeftable.errors import SpecError
from coeftable.format import DateAxis, Format, Number, TimeFormat, is_missing
from coeftable.svg import forest_axis, forest_bar, sparkline_axis, sparkline_bar
from coeftable.theme import Direction, Role, Theme, role_for

_DEFAULT_FORMAT = Number()

_DIRECTIONS = ("higher_is_better", "lower_is_better", "neutral")
_ROLES = ("favorable", "unfavorable", "inconclusive", "neutral")


_ADORNMENT_TYPES = (
    TextBlock,
    MetricValue,
    InlineSvg,
    KeyValuePopover,
    SelectControl,
    Badge,
    CaptionRow,
    Legend,
    RuleStrip,
)


@runtime_checkable
class Region(Protocol):
    """Anything that resolves author inputs into adornments."""

    def resolve(self, *, width: int, theme: Theme, chrome: CardChrome) -> tuple[Adornment, ...]:
        """Resolve into card adornments."""


def _require_finite_number(value: object, *, name: str, optional: bool = False) -> None:
    if value is None and optional:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecError(f"{name} must be a number, got {type(value).__name__}")
    if not math.isfinite(value):
        raise SpecError(f"{name} must be finite")


def _require_callable(value: object, *, name: str, optional: bool = False) -> None:
    if value is None and optional:
        return
    if not callable(value):
        raise SpecError(f"{name} must be callable, got {type(value).__name__}")


def _canonical(value: object, *, name: str) -> tuple[object, ...]:
    """Snapshot an input sequence while presenting malformed inputs as specs."""
    if isinstance(value, (str, bytes)):
        raise SpecError(f"{name} must be a sequence of entries, not a string")
    try:
        return tuple(cast(Iterable[object], value))
    except TypeError as error:
        raise SpecError(f"{name} must be a sequence") from error


def _set(obj: object, name: str, value: object) -> None:
    object.__setattr__(obj, name, value)


@dataclass(frozen=True, slots=True)
class Metric(Region):
    """A formatted headline value with optional interval detail and verdict."""

    value: float
    fmt: Format
    ci: tuple[float, float] | None = None
    ci_fmt: Format | None = None
    ref: float | None = None
    direction: Direction = "higher_is_better"
    role: Role | None = None

    def __post_init__(self) -> None:
        """Validate fields."""
        _require_finite_number(self.value, name="Metric.value")
        _require_callable(self.fmt, name="Metric.fmt")
        _require_callable(self.ci_fmt, name="Metric.ci_fmt", optional=True)
        if self.ci is not None:
            ci = _canonical(self.ci, name="Metric.ci")
            typed_ci = cast(tuple[float, float], ci)
            _set(self, "ci", typed_ci)
            if len(typed_ci) != 2:
                raise SpecError("Metric.ci must be a (lower, upper) pair")
            _require_finite_number(typed_ci[0], name="Metric.ci[0]")
            _require_finite_number(typed_ci[1], name="Metric.ci[1]")
            if typed_ci[0] > typed_ci[1]:
                raise SpecError("Metric.ci must be ordered (lower <= upper)")
        _require_finite_number(self.ref, name="Metric.ref", optional=True)
        _require_member(self.direction, _DIRECTIONS, name="Metric.direction")
        if self.role is not None:
            _require_member(self.role, _ROLES, name="Metric.role")

    def resolve(self, *, width: int, theme: Theme, chrome: CardChrome) -> tuple[MetricValue, ...]:
        """Resolve the headline and interval detail."""
        del width, theme, chrome
        if self.role is not None:
            role: Role = self.role
        elif self.ci is not None:
            role = role_for(self.ci[0], self.ci[1], self.ref, self.direction)
        else:
            role = "neutral"
        detail = None
        if self.ci is not None:
            ci_fmt = self.ci_fmt if self.ci_fmt is not None else self.fmt
            detail = f"[{ci_fmt(self.ci[0])}, {ci_fmt(self.ci[1])}]"
        return (MetricValue(self.fmt(self.value), detail=detail, role=role),)


@dataclass(frozen=True, slots=True)
class Diagnostics(Region):
    """Formatted key/value diagnostics behind a popover."""

    label: str
    items: Sequence[tuple[str, float | str]]
    fmt: Format = _DEFAULT_FORMAT
    key: str | None = None

    def __post_init__(self) -> None:
        """Validate fields."""
        _require_nonempty_str(self.label, name="Diagnostics.label")
        _require_callable(self.fmt, name="Diagnostics.fmt")
        _require_optional_str(self.key, name="Diagnostics.key")
        items = _canonical(self.items, name="Diagnostics.items")
        canonical_items = tuple(
            _canonical(item, name=f"Diagnostics.items[{index}]")
            for index, item in enumerate(items)
        )
        _set(self, "items", canonical_items)
        if not canonical_items:
            raise SpecError("Diagnostics.items must not be empty")
        for index, item in enumerate(canonical_items):
            if len(item) != 2:
                raise SpecError(f"Diagnostics.items[{index}] must be a (key, value) pair")
            _require_str(item[0], name=f"Diagnostics.items[{index}][0]")
            if not isinstance(item[1], str):
                _require_finite_number(item[1], name=f"Diagnostics.items[{index}][1]")

    def resolve(
        self, *, width: int, theme: Theme, chrome: CardChrome
    ) -> tuple[KeyValuePopover, ...]:
        """Resolve formatted diagnostics."""
        del width, theme, chrome
        formatted = tuple(
            (key, value if isinstance(value, str) else self.fmt(value))
            for key, value in self.items
        )
        return (KeyValuePopover(self.label, formatted, key=self.key),)


@dataclass(frozen=True, slots=True)
class Event:
    """One event presented as a strip chip or caption, never both.

    The containing :class:`Events` region selects the mutually exclusive
    presentation with ``captions``.  An optional ``at`` position also
    produces a plot rule, independently of whether the event is a chip or
    caption.
    """

    label: str
    color: str
    dash: Dash = "dotted"
    at: float | None = None

    def __post_init__(self) -> None:
        """Validate fields."""
        _require_nonempty_str(self.label, name="Event.label")
        _require_str(self.color, name="Event.color")
        _require_member(self.dash, _DASHES, name="Event.dash")
        _require_finite_number(self.at, name="Event.at", optional=True)


@dataclass(frozen=True, slots=True)
class Events(Region):
    """A rule strip or per-event captions derived from event declarations.

    The two presentations are alternatives: ``captions=False`` (default)
    resolves to a single ``RuleStrip``; ``captions=True`` resolves to one
    ``CaptionRow`` per event instead of the strip.
    """

    events: Sequence[Event]
    captions: bool = False

    def __post_init__(self) -> None:
        """Validate fields."""
        events = _canonical(self.events, name="Events.events")
        _set(self, "events", events)
        if not events:
            raise SpecError("Events.events must not be empty")
        for index, event in enumerate(events):
            if not isinstance(event, Event):
                raise SpecError(f"Events.events[{index}] must be an Event")
        if not isinstance(self.captions, bool):
            raise SpecError("Events.captions must be a bool")

    def rules(self):
        """Derive on-plot resolved rules for positioned events."""
        from coeftable.annotations import ResolvedRule

        return tuple(
            ResolvedRule(
                at=event.at,
                axis="x",
                layer="overlay",
                affect_domain=False,
                color=event.color,
                opacity=1.0,
                width=1.0,
                dash=event.dash,
            )
            for event in self.events
            if event.at is not None
        )

    def resolve(
        self, *, width: int, theme: Theme, chrome: CardChrome
    ) -> tuple[RuleStrip | CaptionRow, ...]:
        """Resolve a rule strip, or one caption per event when captions=True."""
        del width, theme, chrome
        if self.captions:
            return tuple(
                CaptionRow(event.label, color=event.color, dash=event.dash)
                for event in self.events
            )
        return (RuleStrip(tuple((event.label, event.color, event.dash) for event in self.events)),)


def resolve_content(
    items: Sequence[Region | Adornment], *, width: int, theme: Theme, chrome: CardChrome
) -> tuple[Adornment, ...]:
    """Flatten a mixed Region and Adornment sequence into adornments."""
    out: list[Adornment] = []
    for index, item in enumerate(items):
        if isinstance(item, _ADORNMENT_TYPES):
            out.append(item)
        elif isinstance(item, Region):
            out.extend(item.resolve(width=width, theme=theme, chrome=chrome))
        else:
            raise SpecError(
                f"content[{index}]: expected a Region or Adornment, got {type(item).__name__}"
            )
    return tuple(out)


def _require_bool(value: object, *, name: str) -> None:
    if not isinstance(value, bool):
        raise SpecError(f"{name} must be a bool, got {type(value).__name__}")


def _require_positive_int(value: object, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SpecError(f"{name} must be a positive int, got {type(value).__name__}")
    if value <= 0:
        raise SpecError(f"{name} must be a positive int")


def _require_nonnegative_int(value: object, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SpecError(f"{name} must be a non-negative int, got {type(value).__name__}")
    if value < 0:
        raise SpecError(f"{name} must be a non-negative int")


def _canonical_domain(value: object, *, name: str) -> tuple[float, float]:
    values = _canonical(value, name=name)
    if len(values) != 2:
        raise SpecError(f"{name} must be an ordered (low, high) pair")
    low, high = values
    _require_finite_number(low, name=f"{name}[0]")
    _require_finite_number(high, name=f"{name}[1]")
    low_number = cast(float, low)
    high_number = cast(float, high)
    if low_number > high_number:
        raise SpecError(f"{name} must be ordered (low <= high)")
    return (low_number, high_number)


def _validate_series(values: Sequence[object], *, name: str, allow_missing: bool) -> None:
    for index, value in enumerate(values):
        item_name = f"{name}[{index}]"
        if allow_missing and value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SpecError(f"{item_name} must be a finite number or missing")
        if allow_missing and is_missing(cast(float | None, value)):
            continue
        if not math.isfinite(value):
            raise SpecError(f"{item_name} must be finite")


def _svg_height(svg: str, *, name: str) -> int:
    match = re.search(r'<svg\b[^>]*\bheight="([0-9]+)"', svg)
    if match is None:
        raise SpecError(f"{name} emitted SVG without a numeric root height")
    return int(match.group(1))


@dataclass(frozen=True, slots=True)
class Trend(Region):
    """A line plot with an optional uncertainty ribbon and shared x-axis."""

    x: Sequence[float]
    y: Sequence[float | None]
    x_domain: tuple[float, float]
    domain: tuple[float, float]
    lower: Sequence[float | None] | None = None
    upper: Sequence[float | None] | None = None
    ref: float | None = None
    fmt: Format = _DEFAULT_FORMAT
    axis_fmt: Format | TimeFormat | None = None
    temporal: bool = False
    direction: Direction = "higher_is_better"
    role: Role | None = None
    height: int = 30
    show_axis: bool = True
    axis_height: int = 22
    show_endpoint: bool = True
    endpoint_width: int = 44
    inset: int = 3
    annotations: Sequence[ResolvedAnnotation] = ()

    def __post_init__(self) -> None:
        """Canonicalize and validate all intrinsic region inputs."""
        x = _canonical(self.x, name="Trend.x")
        y = _canonical(self.y, name="Trend.y")
        annotations = _canonical(self.annotations, name="Trend.annotations")
        _set(self, "x", x)
        _set(self, "y", y)
        _set(self, "annotations", annotations)
        if self.lower is not None:
            lower = _canonical(self.lower, name="Trend.lower")
            _set(self, "lower", lower)
        if self.upper is not None:
            upper = _canonical(self.upper, name="Trend.upper")
            _set(self, "upper", upper)

        if not x:
            raise SpecError("Trend.x must not be empty")
        if len(x) != len(y):
            raise SpecError("Trend.x and Trend.y must have the same length")
        _validate_series(x, name="Trend.x", allow_missing=False)
        _validate_series(y, name="Trend.y", allow_missing=True)
        if not any(not is_missing(cast(float | None, value)) for value in y):
            raise SpecError("Trend must have at least one drawable point")

        ribbon_lower = self.lower
        ribbon_upper = self.upper
        if (ribbon_lower is None) != (ribbon_upper is None):
            raise SpecError("Trend.lower and Trend.upper must be provided together")
        if ribbon_lower is not None and ribbon_upper is not None:
            if len(ribbon_lower) != len(x) or len(ribbon_upper) != len(x):
                raise SpecError("Trend.lower and Trend.upper must match Trend.x length")
            _validate_series(ribbon_lower, name="Trend.lower", allow_missing=True)
            _validate_series(ribbon_upper, name="Trend.upper", allow_missing=True)
            for index, (lower, upper) in enumerate(zip(ribbon_lower, ribbon_upper, strict=True)):
                if is_missing(lower) or is_missing(upper):
                    continue
                if cast(float, lower) > cast(float, upper):
                    raise SpecError(f"Trend.lower[{index}] must not exceed Trend.upper[{index}]")

        _set(self, "x_domain", _canonical_domain(self.x_domain, name="Trend.x_domain"))
        _set(self, "domain", _canonical_domain(self.domain, name="Trend.domain"))
        _require_finite_number(self.ref, name="Trend.ref", optional=True)
        _require_callable(self.fmt, name="Trend.fmt")
        _require_callable(self.axis_fmt, name="Trend.axis_fmt", optional=True)
        _require_bool(self.temporal, name="Trend.temporal")
        _require_member(self.direction, _DIRECTIONS, name="Trend.direction")
        if self.role is not None:
            _require_member(self.role, _ROLES, name="Trend.role")
        _require_positive_int(self.height, name="Trend.height")
        _require_bool(self.show_axis, name="Trend.show_axis")
        _require_positive_int(self.axis_height, name="Trend.axis_height")
        _require_bool(self.show_endpoint, name="Trend.show_endpoint")
        _require_positive_int(self.endpoint_width, name="Trend.endpoint_width")
        _require_positive_int(self.inset, name="Trend.inset")
        for index, annotation in enumerate(annotations):
            if not isinstance(annotation, (ResolvedRule, ResolvedBand)):
                raise SpecError(f"Trend.annotations[{index}] must be a resolved annotation")

    def resolve(self, *, width: int, theme: Theme, chrome: CardChrome) -> tuple[InlineSvg, ...]:
        """Render the sparkline and, when requested, its shared x-axis."""
        del chrome
        horizontal_span = (
            width - (self.endpoint_width if self.show_endpoint else 0) - 2 * self.inset
        )
        if horizontal_span < 1:
            raise SpecError(
                "Trend horizontal projection span must be at least 1 pixel: "
                f"width ({width}) - endpoint_width "
                f"({self.endpoint_width if self.show_endpoint else 0}) - "
                f"2*inset ({2 * self.inset}) "
                f"= {horizontal_span}"
            )
        vertical_span = self.height - 2 * self.inset
        if vertical_span < 1:
            raise SpecError(
                "Trend vertical projection span must be at least 1 pixel: "
                f"height ({self.height}) - 2*inset ({2 * self.inset}) = {vertical_span}"
            )
        for axis, domain in (("x", self.x_domain), ("y", self.domain)):
            for position in domain_values(self.annotations, axis=axis):  # type: ignore[arg-type]
                if not domain[0] <= position <= domain[1]:
                    raise SpecError(
                        f"Trend annotation position {position!r} on {axis}-axis lies "
                        f"outside domain {domain!r}; widen the {axis}-domain."
                    )

        ribbon_lower = self.lower
        ribbon_upper = self.upper
        if self.role is not None:
            role: Role = self.role
        elif ribbon_lower is None:
            role = "neutral"
        else:
            if ribbon_upper is None:
                raise SpecError("Trend.lower and Trend.upper must be provided together")
            role = "neutral"
            for index in range(len(self.x) - 1, -1, -1):
                if is_missing(self.x[index]) or is_missing(self.y[index]):
                    continue
                lower_value = (
                    None if is_missing(ribbon_lower[index]) else cast(float, ribbon_lower[index])
                )
                upper_value = (
                    None if is_missing(ribbon_upper[index]) else cast(float, ribbon_upper[index])
                )
                role = role_for(lower_value, upper_value, self.ref, self.direction)
                break

        if ribbon_lower is None:
            lower: Sequence[float | None] = (None,) * len(self.y)
            upper: Sequence[float | None] = (None,) * len(self.y)
        else:
            if ribbon_upper is None:
                raise SpecError("Trend.lower and Trend.upper must be provided together")
            lower = ribbon_lower
            upper = ribbon_upper
        spark_svg = sparkline_bar(
            self.x,
            self.y,
            lower,
            upper,
            x_domain=self.x_domain,
            domain=self.domain,
            ref=self.ref,
            color=theme.color(role),
            fmt=self.fmt,
            width=width,
            height=self.height,
            inset=self.inset,
            show_endpoint=self.show_endpoint,
            endpoint_width=self.endpoint_width,
            annotations=self.annotations,
            theme=theme,
        )
        spark = InlineSvg(spark_svg, width=width, height=self.height)
        if not self.show_axis:
            return (spark,)

        axis_fmt = self.axis_fmt
        if axis_fmt is None:
            axis_fmt = DateAxis() if self.temporal else Number()
        axis_svg = sparkline_axis(
            x_domain=self.x_domain,
            fmt=axis_fmt,
            theme=theme,
            temporal=self.temporal,
            width=width,
            height=self.axis_height,
            inset=self.inset,
            show_endpoint=self.show_endpoint,
            endpoint_width=self.endpoint_width,
        )
        axis = InlineSvg(axis_svg, width=width, height=_svg_height(axis_svg, name="Trend axis"))
        return (spark, axis)


@dataclass(frozen=True, slots=True)
class Interval(Region):
    """A forest interval bar with an optional shared x-axis."""

    estimate: float
    lower: float
    upper: float
    domain: tuple[float, float]
    ref: float = 0.0
    fmt: Format = _DEFAULT_FORMAT
    direction: Direction = "higher_is_better"
    role: Role | None = None
    height: int = 18
    show_axis: bool = True
    axis_height: int = 22
    inset: int = 3
    margin: int = 0

    def __post_init__(self) -> None:
        """Validate all intrinsic interval inputs."""
        _set(self, "domain", _canonical_domain(self.domain, name="Interval.domain"))
        _require_finite_number(self.estimate, name="Interval.estimate")
        _require_finite_number(self.lower, name="Interval.lower")
        _require_finite_number(self.upper, name="Interval.upper")
        if self.lower > self.upper:
            raise SpecError("Interval.lower must not exceed Interval.upper")
        _require_finite_number(self.ref, name="Interval.ref")
        _require_callable(self.fmt, name="Interval.fmt")
        _require_member(self.direction, _DIRECTIONS, name="Interval.direction")
        if self.role is not None:
            _require_member(self.role, _ROLES, name="Interval.role")
        _require_positive_int(self.height, name="Interval.height")
        _require_bool(self.show_axis, name="Interval.show_axis")
        _require_positive_int(self.axis_height, name="Interval.axis_height")
        _require_positive_int(self.inset, name="Interval.inset")
        _require_nonnegative_int(self.margin, name="Interval.margin")
        if self.margin != 0 and self.margin <= self.inset:
            raise SpecError(
                f"Interval.margin ({self.margin}) must be 0 or strictly greater than "
                f"Interval.inset ({self.inset})"
            )

    def resolve(self, *, width: int, theme: Theme, chrome: CardChrome) -> tuple[InlineSvg, ...]:
        """Render the forest bar and, when requested, its shared x-axis."""
        del chrome
        horizontal_span = width - 2 * (self.margin + self.inset)
        if horizontal_span < 1:
            raise SpecError(
                "Interval horizontal projection span must be at least 1 pixel: "
                f"width ({width}) - 2*(margin ({self.margin}) + inset ({self.inset})) "
                f"= {horizontal_span}"
            )
        role = self.role or role_for(self.lower, self.upper, self.ref, self.direction)
        bar_svg = forest_bar(
            self.estimate,
            self.lower,
            self.upper,
            domain=self.domain,
            ref=self.ref,
            color=theme.color(role),
            theme=theme,
            width=width,
            height=self.height,
            inset=self.inset,
            margin=self.margin,
        )
        bar = InlineSvg(bar_svg, width=width, height=self.height)
        if not self.show_axis:
            return (bar,)
        axis_svg = forest_axis(
            domain=self.domain,
            ref=self.ref,
            fmt=self.fmt,
            theme=theme,
            width=width,
            height=self.axis_height,
            inset=self.inset,
            margin=self.margin,
        )
        axis = InlineSvg(axis_svg, width=width, height=_svg_height(axis_svg, name="Interval axis"))
        return (bar, axis)
