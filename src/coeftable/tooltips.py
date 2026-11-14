"""Immutable plot-inspection declarations and aligned plain-text formatting."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from coeftable.errors import SpecError
from coeftable.format import Format


@dataclass(frozen=True)
class TooltipField:
    """Bind an extra measure to a dataframe column, optionally renaming it."""

    source: str
    label: str | None = None
    fmt: Callable[[Any], str] = str

    def __post_init__(self) -> None:
        """Reject invalid field declarations before resolving data."""
        if not isinstance(self.source, str) or not self.source:
            raise SpecError("Tooltip field source must be a nonempty column name.")
        if self.label is not None and not isinstance(self.label, str):
            raise SpecError("Tooltip field label must be a string.")
        if not callable(self.fmt):
            raise SpecError("Tooltip field formatter must be callable.")


@dataclass(frozen=True)
class TooltipValues:
    """Supply one extra measure aligned to a direct plot's observations."""

    label: str
    values: Sequence[Any]
    fmt: Callable[[Any], str] = str

    def __post_init__(self) -> None:
        """Snapshot aligned values and validate their presentation declaration."""
        if not isinstance(self.label, str) or not callable(self.fmt):
            raise SpecError("Tooltip values require a string label and callable formatter.")
        try:
            object.__setattr__(self, "values", tuple(self.values))
        except TypeError as error:
            raise SpecError("Tooltip values must be a sequence.") from error


@dataclass(frozen=True)
class Tooltip:
    """Enable observation inspection with optional fields and value/x formatters.

    Fields bind dataframe columns; direct plots instead accept TooltipValues.
    Configured values are disclosed to the browser, including off-scale samples.
    """

    fields: Sequence[TooltipField] = ()
    fmt: Format | None = None
    x_fmt: Format | None = None

    def __post_init__(self) -> None:
        """Snapshot fields and validate optional formatters."""
        try:
            fields = tuple(self.fields)
        except TypeError as error:
            raise SpecError("Tooltip fields must be a sequence of TooltipField.") from error
        if not all(isinstance(field, TooltipField) for field in fields):
            raise SpecError("Tooltip fields must contain TooltipField declarations.")
        if any(fmt is not None and not callable(fmt) for fmt in (self.fmt, self.x_fmt)):
            raise SpecError("Tooltip formatters must be callable.")
        object.__setattr__(self, "fields", fields)


def format_tooltip_values(
    fields: Sequence[TooltipValues], *, size: int, context: str
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Validate alignment and format extras without formatting null/NaN values.

    Field order and duplicate labels are preserved. Formatter failures retain
    their original cause and report the field and plot/row context.
    """
    result: list[tuple[str, tuple[str, ...]]] = []
    for field in fields:
        if not isinstance(field, TooltipValues):
            raise SpecError(f"{context}: extras must be TooltipValues declarations.")
        if len(field.values) != size:
            raise SpecError(
                f"{context}: tooltip field {field.label!r} has {len(field.values)} values; "
                f"expected {size}."
            )
        texts: list[str] = []
        for value in field.values:
            backend_null = type(value).__module__.startswith("pandas.") and type(
                value
            ).__name__ in ("NAType", "NaTType")
            try:
                numeric_nan = math.isnan(value)
            except (TypeError, ValueError):
                numeric_nan = False
            if value is None or numeric_nan or backend_null:
                texts.append("—")
                continue
            try:
                text = field.fmt(value)
            except Exception as error:
                raise SpecError(
                    f"{context}: tooltip field {field.label!r} formatter failed."
                ) from error
            if not isinstance(text, str):
                raise SpecError(
                    f"{context}: tooltip field {field.label!r} formatter must return a string."
                )
            texts.append(text)
        result.append((field.label, tuple(texts)))
    return tuple(result)
