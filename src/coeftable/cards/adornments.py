"""Typed card-content vocabulary: the closed set card regions resolve into.

The renderer (`coeftable.cards.fragments`) knows exactly these nine types
and never branches on report type. Construction is the runtime contract
boundary for intrinsic field validity: every invalid value raises `SpecError`
here. Layout-dependent fit, including overflow and minimum widths, raises
`SpecError` during measurement instead.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Literal

from coeftable.annotations import Dash
from coeftable.errors import SpecError
from coeftable.theme import Role

type Variant = Literal["title", "subtitle", "body", "caption"]

_VARIANTS = ("title", "subtitle", "body", "caption")
_ROLES = ("favorable", "unfavorable", "inconclusive", "neutral")
_DASHES = ("solid", "dashed", "dotted")


def _require_str(value: object, *, name: str) -> None:
    if not isinstance(value, str):
        raise SpecError(f"{name} must be a str, got {type(value).__name__}")


def _require_nonempty_str(value: object, *, name: str) -> None:
    _require_str(value, name=name)
    if not value:
        raise SpecError(f"{name} must not be empty")


def _require_optional_str(value: object, *, name: str) -> None:
    if value is not None:
        _require_str(value, name=name)


def _require_int(value: object, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SpecError(f"{name} must be an int, got {type(value).__name__}")


def _require_member(value: object, allowed: tuple[str, ...], *, name: str) -> None:
    _require_str(value, name=name)
    if value not in allowed:
        raise SpecError(f"{name} must be one of {allowed}, got {value!r}")


def _require_entry_tuples(
    value: object, *, name: str, arity: int, dash_index: int | None = None
) -> None:
    """Validate a non-empty tuple of fixed-arity string tuples."""
    if not isinstance(value, tuple):
        raise SpecError(f"{name} must be a tuple, got {type(value).__name__}")
    if not value:
        raise SpecError(f"{name} must not be empty")
    for i, entry in enumerate(value):
        if not isinstance(entry, tuple) or len(entry) != arity:
            raise SpecError(f"{name}[{i}] must be a {arity}-tuple")
        for j, member in enumerate(entry):
            if j == dash_index:
                _require_member(member, _DASHES, name=f"{name}[{i}][{j}]")
            else:
                _require_str(member, name=f"{name}[{i}][{j}]")


@dataclass(frozen=True, slots=True)
class TextBlock:
    """A run of card text at one typographic variant, wrapping to max_lines."""

    text: str
    variant: Variant = "body"
    max_lines: int = 1

    def __post_init__(self) -> None:
        """Validate fields."""
        _require_str(self.text, name="TextBlock.text")
        _require_member(self.variant, _VARIANTS, name="TextBlock.variant")
        _require_int(self.max_lines, name="TextBlock.max_lines")
        if self.max_lines < 1:
            raise SpecError("TextBlock.max_lines must be >= 1")


@dataclass(frozen=True, slots=True)
class MetricValue:
    """A pre-formatted headline value with optional interval detail."""

    value: str
    detail: str | None = None
    role: Role = "neutral"

    def __post_init__(self) -> None:
        """Validate fields."""
        _require_nonempty_str(self.value, name="MetricValue.value")
        _require_optional_str(self.detail, name="MetricValue.detail")
        if self.detail == "":
            raise SpecError("MetricValue.detail must not be empty")
        _require_member(self.role, _ROLES, name="MetricValue.role")


@dataclass(frozen=True, slots=True)
class InlineSvg:
    """A complete pre-rendered ``<svg>`` element, passed through verbatim.

    The declared `width`/`height` are authoritative for later measurement
    and must equal the svg root's own attributes — a drawing that paints
    larger than it declares is exactly the footprint lie exact measurement
    exists to prevent. SVG-internal ids are owned by the producer and must
    be deterministic functions of content (as `coeftable.svg`'s are).
    """

    svg: str
    width: int
    height: int

    def __post_init__(self) -> None:
        """Validate fields."""
        _require_str(self.svg, name="InlineSvg.svg")
        _require_int(self.width, name="InlineSvg.width")
        _require_int(self.height, name="InlineSvg.height")
        if self.width <= 0 or self.height <= 0:
            raise SpecError("InlineSvg.width and InlineSvg.height must be positive")
        try:
            root = ET.fromstring(self.svg)  # noqa: S314
        except ET.ParseError as exc:
            raise SpecError(f"InlineSvg.svg must be well-formed XML: {exc}") from None
        tag = root.tag.rsplit("}", 1)[-1]
        if tag != "svg":
            raise SpecError(f"InlineSvg.svg root element must be <svg>, got <{tag}>")
        for attr, declared in (("width", self.width), ("height", self.height)):
            actual = root.get(attr)
            if actual is None:
                raise SpecError(f"InlineSvg.svg root must declare a {attr} attribute")
            if actual != str(declared):
                raise SpecError(
                    f"InlineSvg.{attr}={declared} does not match the svg root's {attr}={actual!r}"
                )


@dataclass(frozen=True, slots=True)
class KeyValuePopover:
    """A folded key/value overlay behind an always-visible summary label."""

    label: str
    items: tuple[tuple[str, str], ...]
    key: str | None = None

    def __post_init__(self) -> None:
        """Validate fields."""
        _require_nonempty_str(self.label, name="KeyValuePopover.label")
        _require_entry_tuples(self.items, name="KeyValuePopover.items", arity=2)
        _require_optional_str(self.key, name="KeyValuePopover.key")


@dataclass(frozen=True, slots=True)
class SelectControl:
    """A native select. Options are (value, label); selection is by value.

    `key` is a semantic handle for future state rules; state binds to
    (key, option value), never to labels, positions, or DOM ids. The
    renderer never emits `key`.
    """

    label: str
    options: tuple[tuple[str, str], ...]
    selected: str
    key: str | None = None

    def __post_init__(self) -> None:
        """Validate fields."""
        _require_nonempty_str(self.label, name="SelectControl.label")
        _require_entry_tuples(self.options, name="SelectControl.options", arity=2)
        _require_str(self.selected, name="SelectControl.selected")
        _require_optional_str(self.key, name="SelectControl.key")
        if self.key == "":
            raise SpecError("SelectControl.key must not be empty")
        values = [value for value, _ in self.options]
        if any("\r" in value or "\x00" in value for value in values):
            raise SpecError(
                "SelectControl.options values must not contain carriage returns or NUL bytes "
                "(they cannot survive an HTML attribute round-trip)"
            )
        if len(set(values)) != len(values):
            raise SpecError("SelectControl.options values must be unique")
        if self.selected not in values:
            raise SpecError(f"SelectControl.selected {self.selected!r} is not an option value")


@dataclass(frozen=True, slots=True)
class Badge:
    """A small semantic pill (e.g. an operator or disclaimer marker)."""

    text: str
    role: Role = "neutral"

    def __post_init__(self) -> None:
        """Validate fields."""
        _require_str(self.text, name="Badge.text")
        _require_member(self.role, _ROLES, name="Badge.role")


@dataclass(frozen=True, slots=True)
class CaptionRow:
    """A caption line with an optional colour-matched line marker."""

    text: str
    color: str | None = None
    dash: Dash = "dotted"

    def __post_init__(self) -> None:
        """Validate fields."""
        _require_str(self.text, name="CaptionRow.text")
        _require_optional_str(self.color, name="CaptionRow.color")
        _require_member(self.dash, _DASHES, name="CaptionRow.dash")


@dataclass(frozen=True, slots=True)
class Legend:
    """Swatch + label chips identifying series."""

    entries: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        """Validate fields."""
        _require_entry_tuples(self.entries, name="Legend.entries", arity=2)


@dataclass(frozen=True, slots=True)
class RuleStrip:
    """Chips identifying event rules: (label, color, dash) per rule."""

    entries: tuple[tuple[str, str, Dash], ...]

    def __post_init__(self) -> None:
        """Validate fields."""
        _require_entry_tuples(self.entries, name="RuleStrip.entries", arity=3, dash_index=2)


type Adornment = (
    TextBlock
    | MetricValue
    | InlineSvg
    | KeyValuePopover
    | SelectControl
    | Badge
    | CaptionRow
    | Legend
    | RuleStrip
)
