"""``ProductFlow``: a domain builder for staged product-funnel reports.

Composes only public ``Card``, ``EventFlow``, and ``GraphReport`` contracts:
every step becomes a Card whose appearance and content are derived from its
kind, direction, and series; steps are placed on an ``EventFlow`` staged
canvas; and the whole thing is wrapped in a ``GraphReport`` with a title, an
edge-kind legend, and a note. The legend derives each kind's exact resolved
color and solid/dashed semantic category from the ``EventFlow`` styles.
``EdgeStyle.width`` and numeric dash periods remain rendered-edge-only
details rather than miniature legend styling.

The default theme matches :data:`~coeftable.theme.DEFAULT` except for the
prototype's translucent neutral stage band (``rgba(20,24,31,.035)``), so the
default 14px ``stage_inset`` reads against white card surfaces.
A caller-supplied theme -- ``DEFAULT`` included -- is used unchanged.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal, cast

from coeftable.cards import (
    DEFAULT_CHROME,
    Adornment,
    Badge,
    Card,
    CardAppearance,
    CardChrome,
    Diagnostics,
    Metric,
    Region,
    RuleStrip,
    TextBlock,
    Trend,
)
from coeftable.errors import SpecError
from coeftable.format import Format, Number, Percent
from coeftable.graph.event_flow import EventFlow
from coeftable.graph.model import EdgeKind, EdgeStyle, FlowEdge, StageSlot, _resolve_edge_styles
from coeftable.graph.report import GraphReport
from coeftable.theme import DEFAULT, Direction, Theme, role_for

type ProductStepKind = Literal["event", "decision", "terminal"]

_KINDS: tuple[ProductStepKind, ...] = ("event", "decision", "terminal")
_DIRECTIONS: tuple[Direction, ...] = ("higher_is_better", "lower_is_better", "neutral")
_LEGEND_KINDS: tuple[tuple[EdgeKind, str], ...] = (
    ("forward", "forward"),
    ("skip", "skip"),
    ("back", "loop / back"),
)
_DEFAULT_VALUE_FMT: Format = Number(compact=True)
_DEFAULT_CHANGE_FMT: Format = Percent(signed=True, decimals=1)
# ProductFlow's default uses the prototype's translucent neutral stage band.
# Explicit themes, including DEFAULT itself, bypass this default value.
_DEFAULT_THEME: Theme = replace(DEFAULT, band="rgba(20,24,31,.035)")


def _sequence(value: object, *, name: str) -> tuple[object, ...]:
    """Snapshot a public sequence and report malformed values consistently."""
    if isinstance(value, (str, bytes)):
        raise SpecError(f"{name} must be a sequence of entries, not a string")
    try:
        return tuple(cast(Sequence[object], value))
    except TypeError as error:
        raise SpecError(f"{name} must be a sequence") from error


def _non_empty_str(value: object, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise SpecError(f"{name} must be a non-empty str")


def _non_negative_int(value: object, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SpecError(f"{name} must be a non-negative int")


def _positive_int(value: object, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SpecError(f"{name} must be a positive int")


def _finite_number(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SpecError(f"{name} must be a finite number")
    if not math.isfinite(value):
        raise SpecError(f"{name} must be finite")
    return float(value)


def _optional_str(value: object, *, name: str) -> None:
    if value is not None and not isinstance(value, str):
        raise SpecError(f"{name} must be a str")


def _callable_fmt(value: object, *, name: str) -> None:
    if not callable(value):
        raise SpecError(f"{name} must be callable")


def _change(series: tuple[float, ...]) -> float:
    """Return the percent change from the first to the last series value."""
    return (series[-1] / series[0] - 1.0) * 100.0


def _trend_domain(series: tuple[float, ...]) -> tuple[float, float]:
    """Return a padded value domain: 20% of the series' own span on each side."""
    low, high = min(series), max(series)
    span = (high - low) or abs(high) or 1.0
    return (low - 0.2 * span, high + 0.2 * span)


@dataclass(frozen=True, slots=True)
class ProductStep:
    """One product-funnel card's identity, placement, and analytics inputs.

    ``series`` holds actual volumes in declared order -- no fixed period
    count, denominator step, or scaling convention is built in. A
    ``"decision"`` step carries no series; its card renders ``note`` as
    explanatory text instead of a metric/trend. ``share_of`` names another
    step whose current value this step's current value is expressed as a
    percentage of; that reference is validated by :func:`ProductFlow`, which
    alone has visibility into every other step.
    """

    id: str
    title: str
    stage: int
    lane: int
    subtitle: str = ""
    series: Sequence[float] = ()
    kind: ProductStepKind = "event"
    muted: bool = False
    direction: Direction = "higher_is_better"
    note: str | None = None
    share_of: str | None = None
    diagnostics: Sequence[tuple[str, float | str]] = ()

    def __post_init__(self) -> None:
        """Snapshot inputs and validate every intrinsic ProductStep invariant."""
        _non_empty_str(self.id, name="ProductStep.id")
        _non_empty_str(self.title, name="ProductStep.title")
        _non_negative_int(self.stage, name="ProductStep.stage")
        _non_negative_int(self.lane, name="ProductStep.lane")
        if not isinstance(self.subtitle, str):
            raise SpecError("ProductStep.subtitle must be a str")
        if self.kind not in _KINDS:
            raise SpecError("ProductStep.kind must be event, decision, or terminal")
        if self.direction not in _DIRECTIONS:
            raise SpecError("ProductStep.direction must be a valid Direction")
        if not isinstance(self.muted, bool):
            raise SpecError("ProductStep.muted must be a bool")

        series = tuple(
            _finite_number(value, name=f"ProductStep.series[{index}]")
            for index, value in enumerate(_sequence(self.series, name="ProductStep.series"))
        )
        for index, value in enumerate(series):
            if value < 0:
                raise SpecError(f"ProductStep.series[{index}] must be nonnegative")
        object.__setattr__(self, "series", series)

        if self.kind == "decision":
            if series:
                raise SpecError("ProductStep decision requires empty series")
            _non_empty_str(self.note, name="ProductStep decision note")
            if self.share_of is not None:
                raise SpecError("ProductStep decision must not set share_of")
            if self.muted:
                raise SpecError("ProductStep decision must not be muted")
        else:
            if self.note is not None:
                raise SpecError("ProductStep.note is only valid for a decision step")
            if len(series) < 2:
                raise SpecError("ProductStep.series must have at least two values")
            if series[0] <= 0:
                raise SpecError("ProductStep.series[0] must be strictly positive")
            if self.share_of is not None:
                _non_empty_str(self.share_of, name="ProductStep.share_of")

        diagnostics = _sequence(self.diagnostics, name="ProductStep.diagnostics")
        canonical_diagnostics: list[tuple[str, float | str]] = []
        for index, item in enumerate(diagnostics):
            entry = _sequence(item, name=f"ProductStep.diagnostics[{index}]")
            if len(entry) != 2:
                raise SpecError(f"ProductStep.diagnostics[{index}] must be a (label, value) pair")
            label, value = entry
            _non_empty_str(label, name=f"ProductStep.diagnostics[{index}][0]")
            resolved_value: float | str = (
                value
                if isinstance(value, str)
                else _finite_number(value, name=f"ProductStep.diagnostics[{index}][1]")
            )
            canonical_diagnostics.append((cast(str, label), resolved_value))
        object.__setattr__(self, "diagnostics", tuple(canonical_diagnostics))


def _card_appearance(step: ProductStep) -> CardAppearance:
    """Map a step's kind and muted flag onto the prototype's appearance chrome."""
    if step.kind == "decision":
        border, fill = "dashed", "transparent"
    elif step.kind == "terminal":
        border, fill = "strong", "surface"
    else:
        border, fill = "default", "surface"
    return CardAppearance(border=border, fill=fill, emphasis="muted" if step.muted else "default")


def _series_content(
    step: ProductStep,
    *,
    value_fmt: Format,
    change_fmt: Format,
    steps_by_id: Mapping[str, ProductStep],
    current_by_id: Mapping[str, float],
) -> tuple[Region | Adornment, ...]:
    """Build an event/terminal step's metric, badge, trend, and diagnostics."""
    series = cast(tuple[float, ...], step.series)
    current = series[-1]
    start = series[0]
    change = _change(series)
    role = role_for(change, change, 0.0, step.direction)
    items: list[tuple[str, float | str]] = [
        ("Now", value_fmt(current)),
        ("Start", value_fmt(start)),
        ("Change", change_fmt(change)),
    ]
    if step.share_of is not None:
        referenced = steps_by_id[step.share_of]
        share = current / current_by_id[referenced.id] * 100.0
        items.append((f"Share of {referenced.title}", change_fmt(share)))
    items.extend(step.diagnostics)
    content: tuple[Region | Adornment, ...] = (
        Metric(current, value_fmt, direction=step.direction, role=role),
        Badge(change_fmt(change), role=role),
        Trend(
            x=tuple(float(i) for i in range(len(series))),
            y=series,
            x_domain=(0.0, float(len(series) - 1)),
            domain=_trend_domain(series),
            fmt=value_fmt,
            direction=step.direction,
            role=role,
            show_axis=False,
        ),
        Diagnostics("stats", tuple(items)),
    )
    if step.kind == "terminal":
        content = (*content, Badge("terminal"))
    return content


def _build_card(
    step: ProductStep,
    *,
    value_fmt: Format,
    change_fmt: Format,
    card_width: int,
    chrome: CardChrome,
    theme: Theme,
    steps_by_id: Mapping[str, ProductStep],
    current_by_id: Mapping[str, float],
) -> Card:
    """Build one step's fully resolved Card: appearance, content, and geometry."""
    content: tuple[Region | Adornment, ...]
    if step.kind == "decision":
        content = (TextBlock(cast(str, step.note), variant="caption"),)
    else:
        content = _series_content(
            step,
            value_fmt=value_fmt,
            change_fmt=change_fmt,
            steps_by_id=steps_by_id,
            current_by_id=current_by_id,
        )
    return Card(
        title=step.title,
        content=content,
        subtitle=step.subtitle or None,
        width=card_width,
        chrome=chrome,
        theme=theme,
        appearance=_card_appearance(step),
    )


def _validate_stages(stages: Sequence[str]) -> tuple[str, ...]:
    """Canonicalize and validate a nonempty, uniquely named stage sequence."""
    entries = cast(tuple[str, ...], _sequence(stages, name="ProductFlow.stages"))
    if not entries:
        raise SpecError("ProductFlow.stages must not be empty")
    for index, stage_name in enumerate(entries):
        _non_empty_str(stage_name, name=f"ProductFlow.stages[{index}]")
    if len(set(entries)) != len(entries):
        raise SpecError("ProductFlow.stages must be unique")
    return entries


def _validate_steps(steps: Sequence[ProductStep], *, stage_count: int) -> tuple[ProductStep, ...]:
    """Canonicalize steps and validate cross-step id/stage-range invariants."""
    entries = cast(tuple[ProductStep, ...], _sequence(steps, name="ProductFlow.steps"))
    if not entries:
        raise SpecError("ProductFlow.steps must not be empty")
    for index, entry in enumerate(entries):
        if not isinstance(entry, ProductStep):
            raise SpecError(f"ProductFlow.steps[{index}] must be a ProductStep")
    step_ids = tuple(entry.id for entry in entries)
    if len(set(step_ids)) != len(step_ids):
        raise SpecError("ProductFlow.steps ids must be unique")
    for entry in entries:
        if entry.stage >= stage_count:
            raise SpecError(f"ProductStep {entry.id!r} stage is out of range")
    return entries


def _validate_share_references(
    steps: tuple[ProductStep, ...],
    *,
    steps_by_id: Mapping[str, ProductStep],
    current_by_id: Mapping[str, float],
) -> None:
    """Validate every ``share_of`` names a distinct, non-decision, nonzero step."""
    for entry in steps:
        if entry.share_of is None:
            continue
        if entry.share_of == entry.id:
            raise SpecError(f"ProductStep {entry.id!r} share_of must reference a distinct step")
        referenced = steps_by_id.get(entry.share_of)
        if referenced is None:
            raise SpecError(f"ProductStep {entry.id!r} share_of references an unknown step")
        if referenced.kind == "decision":
            raise SpecError(
                f"ProductStep {entry.id!r} share_of must reference a non-decision step"
            )
        if current_by_id[referenced.id] == 0:
            raise SpecError(f"ProductStep {entry.id!r} share_of references a zero denominator")


def _validate_edges(edges: Sequence[FlowEdge]) -> tuple[FlowEdge, ...]:
    """Canonicalize edges and validate every entry is a FlowEdge."""
    entries = cast(tuple[FlowEdge, ...], _sequence(edges, name="ProductFlow.edges"))
    for index, edge in enumerate(entries):
        if not isinstance(edge, FlowEdge):
            raise SpecError(f"ProductFlow.edges[{index}] must be a FlowEdge")
    return entries


def ProductFlow(
    stages: Sequence[str],
    steps: Sequence[ProductStep],
    edges: Sequence[FlowEdge],
    *,
    title: str | None = None,
    note: str | None = None,
    value_fmt: Format = _DEFAULT_VALUE_FMT,
    change_fmt: Format = _DEFAULT_CHANGE_FMT,
    card_width: int = 228,
    styles: Mapping[EdgeKind, EdgeStyle] | None = None,
    theme: Theme = _DEFAULT_THEME,
    chrome: CardChrome = DEFAULT_CHROME,
    dom_prefix: str = "product-flow",
    gap: int = 36,
    stage_inset: int = 14,
    stage_gap: int | None = 44,
) -> GraphReport:
    """Compose a staged product-funnel report from stages, steps, and edges.

    Every event/terminal step becomes a Card whose current value, change
    badge, ordinal trend, and diagnostics popover are derived from its own
    ``series``; a decision step's card instead renders its ``note`` as
    explanatory text. Steps are placed on an :func:`EventFlow` staged canvas
    labeled with ``stages``. The returned report's header carries an optional
    title, a legend deriving each edge kind's exact resolved color and
    solid/dashed semantic category from the ``EventFlow`` styles, and an
    optional note. ``EdgeStyle.width`` and numeric dash periods affect only
    rendered edges, not the categorical legend.

    The default ``theme`` equals :data:`~coeftable.theme.DEFAULT` except for
    the prototype's translucent neutral stage ``band``
    (``rgba(20,24,31,.035)``). A caller-supplied theme -- ``DEFAULT``
    included -- is used unchanged.

    ``stage_inset`` defaults to the prototype's 14px measured margin inside
    each stage column, centering every intrinsic-width card. ``stage_gap``
    defaults to 44px between padded stage bands, yielding the prototype's
    72px card-edge spacing; pass ``stage_gap=None`` for EventFlow's
    conservative automatic derivation or ``stage_inset=0`` for compact
    edge-to-edge bands.
    """
    stage_entries = _validate_stages(stages)
    step_entries = _validate_steps(steps, stage_count=len(stage_entries))
    edge_entries = _validate_edges(edges)

    _callable_fmt(value_fmt, name="ProductFlow.value_fmt")
    _callable_fmt(change_fmt, name="ProductFlow.change_fmt")
    _positive_int(card_width, name="ProductFlow.card_width")
    if not isinstance(theme, Theme):
        raise SpecError("ProductFlow.theme must be a Theme")
    resolved_theme = theme
    if not isinstance(chrome, CardChrome):
        raise SpecError("ProductFlow.chrome must be a CardChrome")
    _optional_str(title, name="ProductFlow.title")
    _optional_str(note, name="ProductFlow.note")

    steps_by_id = {entry.id: entry for entry in step_entries}
    current_by_id = {
        entry.id: cast(tuple[float, ...], entry.series)[-1]
        for entry in step_entries
        if entry.kind != "decision"
    }
    _validate_share_references(step_entries, steps_by_id=steps_by_id, current_by_id=current_by_id)

    cards = {
        entry.id: _build_card(
            entry,
            value_fmt=value_fmt,
            change_fmt=change_fmt,
            card_width=card_width,
            chrome=chrome,
            theme=resolved_theme,
            steps_by_id=steps_by_id,
            current_by_id=current_by_id,
        )
        for entry in step_entries
    }
    nodes = tuple((entry.id, cards[entry.id]) for entry in step_entries)
    placements = tuple(StageSlot(entry.id, entry.stage, entry.lane) for entry in step_entries)
    collapsible = tuple(
        entry.id
        for entry in step_entries
        if any(edge.src == entry.id and edge.kind in ("forward", "skip") for edge in edge_entries)
    )
    product_styles: dict[EdgeKind, EdgeStyle] = {
        "back": EdgeStyle(resolved_theme.unfavorable, dash=(2.0, 3.0))
    }
    if isinstance(styles, Mapping):
        product_styles.update(styles)
    flow_styles = (
        styles if styles is not None and not isinstance(styles, Mapping) else product_styles
    )

    graph = EventFlow(
        nodes,
        placements,
        edge_entries,
        stage_labels=stage_entries,
        styles=flow_styles,
        collapsible=collapsible,
        theme=resolved_theme,
        chrome=chrome,
        dom_prefix=dom_prefix,
        gap=gap,
        stage_inset=stage_inset,
        stage_gap=stage_gap,
    )

    resolved_styles = _resolve_edge_styles(graph.theme, graph.edge_styles)
    legend_entries = tuple(
        (
            label,
            resolved_styles[kind].stroke,
            "solid" if not resolved_styles[kind].dash else "dashed",
        )
        for kind, label in _LEGEND_KINDS
    )
    header: list[Adornment] = []
    if title is not None:
        header.append(TextBlock(title, variant="title"))
    header.append(RuleStrip(legend_entries))
    if note is not None:
        header.append(TextBlock(note, variant="caption"))
    return GraphReport(graph, header=tuple(header), font="system")


__all__ = ["ProductFlow", "ProductStep", "ProductStepKind"]
