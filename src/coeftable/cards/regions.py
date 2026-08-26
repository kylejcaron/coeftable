"""Built-in card regions resolved from author inputs into adornments."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol, cast, runtime_checkable

from coeftable.annotations import Dash
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
from coeftable.format import Format, Number
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
    ci: Sequence[float] | None = None
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
    """One declared event: strip chip, optional caption, optional plot rule."""

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
    """A rule strip and optional captions derived from event declarations."""

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
        """Resolve a rule strip and optionally a caption per event."""
        del width, theme, chrome
        strip = RuleStrip(tuple((event.label, event.color, event.dash) for event in self.events))
        if not self.captions:
            return (strip,)
        return (
            strip,
            *(
                CaptionRow(event.label, color=event.color, dash=event.dash)
                for event in self.events
            ),
        )


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
