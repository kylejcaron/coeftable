"""Typed plot-annotation declarations and frame-aware resolution."""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import narwhals as nw

from coeftable._axis import _coerce_temporal
from coeftable.errors import SpecError
from coeftable.format import coerce_numeric

type Axis = Literal["x", "y"]
type AxisKind = Literal["numeric", "temporal"]
type Layer = Literal["underlay", "overlay"]
type Dash = Literal["solid", "dashed", "dotted"]
type AnnotationSource = int | float | dt.date | dt.datetime | str


def _validate_coordinate(value: AnnotationSource, *, name: str) -> None:
    """Validate a declaration's literal-or-field coordinate."""
    if isinstance(value, bool) or not isinstance(value, (int, float, dt.date, str)):
        raise SpecError(f"Annotation {name} must be a numeric/temporal literal or field name.")
    if isinstance(value, float) and not math.isfinite(value):
        raise SpecError(f"Annotation {name} must be finite.")


def _validate_unit_interval(value: float, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SpecError(f"Annotation {name} must be a finite number between 0 and 1.")
    if not 0.0 <= value <= 1.0:
        raise SpecError(f"Annotation {name} must be between 0 and 1.")


@dataclass(frozen=True)
class Rule:
    """A line annotation at one axis coordinate."""

    at: AnnotationSource
    axis: Axis
    layer: Layer = "overlay"
    affect_domain: bool = True
    color: str | None = None
    opacity: float = 1.0
    width: float = 1.0
    dash: Dash = "dashed"

    def __post_init__(self) -> None:
        """Validate declaration-only rule styling and coordinates."""
        _validate_coordinate(self.at, name="coordinate")
        if self.layer not in ("underlay", "overlay"):
            raise SpecError(
                f"Annotation layer must be 'underlay' or 'overlay'; got {self.layer!r}."
            )
        _validate_unit_interval(self.opacity, name="opacity")
        if isinstance(self.width, bool) or not isinstance(self.width, (int, float)):
            raise SpecError("Annotation width must be a finite positive number.")
        if not math.isfinite(self.width) or self.width <= 0:
            raise SpecError("Annotation width must be a finite positive number.")
        if self.dash not in ("solid", "dashed", "dotted"):
            raise SpecError(
                f"Annotation dash must be 'solid', 'dashed', or 'dotted'; got {self.dash!r}."
            )


@dataclass(frozen=True)
class Band:
    """A shaded interval annotation between two axis coordinates."""

    start: AnnotationSource
    end: AnnotationSource
    axis: Axis
    layer: Layer = "underlay"
    affect_domain: bool = True
    color: str | None = None
    opacity: float = 0.12

    def __post_init__(self) -> None:
        """Validate declaration-only band styling and coordinates."""
        _validate_coordinate(self.start, name="start")
        _validate_coordinate(self.end, name="end")
        if self.layer not in ("underlay", "overlay"):
            raise SpecError(
                f"Annotation layer must be 'underlay' or 'overlay'; got {self.layer!r}."
            )
        _validate_unit_interval(self.opacity, name="opacity")


type Annotation = Rule | Band


@dataclass(frozen=True)
class ResolvedRule:
    """A fully resolved line annotation."""

    at: float
    axis: Axis
    layer: Layer
    affect_domain: bool
    color: str | None
    opacity: float
    width: float
    dash: Dash


@dataclass(frozen=True)
class ResolvedBand:
    """A fully resolved interval annotation."""

    start: float
    end: float
    axis: Axis
    layer: Layer
    affect_domain: bool
    color: str | None
    opacity: float


type ResolvedAnnotation = ResolvedRule | ResolvedBand


@dataclass(frozen=True)
class PreparedAnnotations:
    """Resolved annotations grouped in frame-row order."""

    by_row: tuple[tuple[ResolvedAnnotation, ...], ...]


def annotation_sources(annotations: Sequence[Annotation]) -> tuple[str, ...]:
    """Return source-field names once, in declaration order."""
    sources: dict[str, None] = {}
    for annotation in annotations:
        coordinates = (
            (annotation.at,)
            if isinstance(annotation, Rule)
            else (annotation.start, annotation.end)
        )
        for coordinate in coordinates:
            if isinstance(coordinate, str):
                sources.setdefault(coordinate, None)
    return tuple(sources)


def _coerce_values(
    values: Sequence[Any],
    *,
    kind: AxisKind,
    context: str,
) -> list[float | None]:
    present = [value for value in values if value is not None]
    if kind == "numeric":
        if any(isinstance(value, (bool, dt.date)) for value in present):
            raise SpecError(f"{context} must be numeric for a numeric axis.")
        try:
            resolved = coerce_numeric(values, subject=context)
        except TypeError as error:
            raise SpecError(str(error)) from None
    elif kind == "temporal":
        if any(not isinstance(value, dt.date) for value in present):
            raise SpecError(f"{context} must be temporal for a temporal axis.")
        resolved = _coerce_temporal(values)
    else:
        raise SpecError(f"{context} has unsupported axis kind {kind!r}.")

    if any(value is not None and not math.isfinite(value) for value in resolved):
        raise SpecError(f"{context} must be finite.")
    return resolved


def prepare_annotations(
    annotations: Sequence[Annotation],
    frame: nw.DataFrame,
    *,
    axis_kinds: Mapping[Axis, AxisKind],
    plot_label: str,
    row_identities: Sequence[Any],
) -> PreparedAnnotations:
    """Resolve annotation literals and fields into one ordered tuple per row."""
    row_count = len(frame)
    if len(row_identities) != row_count:
        raise SpecError(
            f"{plot_label} annotation rows do not match the frame: "
            f"{len(row_identities)} identities for {row_count} rows."
        )

    source_cache: dict[str, list[Any]] = {}

    def values_for(
        source: AnnotationSource, *, kind: AxisKind, context: str
    ) -> list[float | None]:
        if isinstance(source, str):
            if source not in frame.columns:
                raise SpecError(f"{context} names missing column {source!r}.")
            if source not in source_cache:
                source_cache[source] = frame[source].to_list()
            raw = source_cache[source]
        else:
            raw = [source] * row_count
        return _coerce_values(raw, kind=kind, context=context)

    resolved_rows: list[list[ResolvedAnnotation]] = [[] for _ in range(row_count)]
    for index, annotation in enumerate(annotations):
        if annotation.axis not in axis_kinds:
            raise SpecError(
                f"{plot_label} annotation {index} uses unsupported axis {annotation.axis!r}."
            )
        kind = axis_kinds[annotation.axis]
        prefix = f"{plot_label} annotation {index}"
        if isinstance(annotation, Rule):
            positions = values_for(annotation.at, kind=kind, context=f"{prefix} at")
            for row, position in enumerate(positions):
                if position is not None:
                    resolved_rows[row].append(
                        ResolvedRule(
                            at=position,
                            axis=annotation.axis,
                            layer=annotation.layer,
                            affect_domain=annotation.affect_domain,
                            color=annotation.color,
                            opacity=annotation.opacity,
                            width=annotation.width,
                            dash=annotation.dash,
                        )
                    )
            continue

        starts = values_for(annotation.start, kind=kind, context=f"{prefix} start")
        ends = values_for(annotation.end, kind=kind, context=f"{prefix} end")
        for row, (start, end) in enumerate(zip(starts, ends, strict=True)):
            if start is None or end is None:
                continue
            if start > end:
                raise SpecError(
                    f"{prefix} row {row_identities[row]!r}: "
                    f"band start {start!r} must not exceed end {end!r}."
                )
            resolved_rows[row].append(
                ResolvedBand(
                    start=start,
                    end=end,
                    axis=annotation.axis,
                    layer=annotation.layer,
                    affect_domain=annotation.affect_domain,
                    color=annotation.color,
                    opacity=annotation.opacity,
                )
            )

    return PreparedAnnotations(by_row=tuple(tuple(marks) for marks in resolved_rows))


def domain_values(marks: Sequence[ResolvedAnnotation], *, axis: Axis) -> list[float]:
    """Return domain-affecting positions for one axis, preserving mark order."""
    values: list[float] = []
    for mark in marks:
        if mark.axis != axis or not mark.affect_domain:
            continue
        if isinstance(mark, ResolvedRule):
            values.append(mark.at)
        else:
            values.extend((mark.start, mark.end))
    return values
