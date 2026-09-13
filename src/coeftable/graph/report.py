"""A graph with exactly measured furniture stacked above and below it."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from math import ceil
from typing import Literal, cast

from coeftable.cards import (
    Adornment,
    CardChrome,
    InlineSvg,
    KeyValuePopover,
    MetricValue,
    render_adornment,
)

# `resolve_rows` and `RenderRow` carry no leading underscore in
# `coeftable.cards.measure` (unlike `_canonical` below); they are
# package-level, not user-facing, so importing them across this same
# distribution's package boundary reuses the one card-geometry model
# instead of inventing a second one for report sections.
#
# `_est` and `_minimum_inline_width` do carry a leading underscore, but they
# are the one place chrome-specific legibility math lives per adornment
# kind. Re-deriving that math here — instead of importing it — is exactly
# how a section's required width and `resolve_rows`'s own minimum-width
# check would drift apart, so the private names are reused rather than
# mirrored.
from coeftable.cards.measure import RenderRow, _est, _minimum_inline_width, resolve_rows
from coeftable.errors import SpecError
from coeftable.graph.model import Graph
from coeftable.theme import Theme


def _canonical(value: object, *, name: str) -> tuple[object, ...]:
    """Snapshot an input sequence while presenting malformed inputs as specs.

    Mirrors `coeftable.cards.regions._canonical`: that helper is private to
    the cards package, so this report module keeps its own copy rather than
    reaching across a package boundary for a leading-underscore name.
    """
    if isinstance(value, (str, bytes)):
        raise SpecError(f"{name} must be a sequence of entries, not a string")
    try:
        return tuple(cast(Iterable[object], value))
    except TypeError as error:
        raise SpecError(f"{name} must be a sequence") from error


def _adornment_natural_width(adornment: Adornment, *, chrome: CardChrome) -> int:
    """Return the modelled pixel width floor an adornment needs.

    `InlineSvg` contributes its declared width, which is exact. `MetricValue`
    never wraps, so its content dictates a floor, but that floor is an
    estimate from the character-width ratio rather than a real text
    measurement. Everything else contributes the minimum legible width from
    `_minimum_inline_width`, measure.py's single source of truth for that
    floor; those types then either wrap or clip according to their own kind,
    so the value here is a lower bound and not a prediction of their final
    rendered width.
    """
    if isinstance(adornment, InlineSvg):
        return adornment.width
    if isinstance(adornment, MetricValue):
        ratio = chrome.data_char_width_ratio
        width = _est(adornment.value, chrome.value_size, ratio)
        if adornment.detail is not None:
            width += chrome.value_detail_gap + _est(adornment.detail, chrome.ci_size, ratio)
        return ceil(width)
    minimum = _minimum_inline_width(adornment, chrome)
    return 0 if minimum is None else ceil(minimum)


def _section_natural_width(adornments: tuple[Adornment, ...], *, chrome: CardChrome) -> int:
    """Return the width a section's non-wrapping or minimum-width content requires."""
    width = 0
    for adornment in adornments:
        width = max(width, _adornment_natural_width(adornment, chrome=chrome))
    return width


def _section_height(rows: tuple[RenderRow, ...]) -> int:
    """Sum of measured row heights plus the inter-row gaps between them."""
    return sum(row.height + row.gap_above for row in rows)


def _render_row(row: RenderRow, *, theme: Theme, chrome: CardChrome) -> str:
    """Render one exact-height section row, preserving measured spacing."""
    gap = f";margin-top:{row.gap_above}px" if row.gap_above else ""
    svg_containment = ";line-height:0" if isinstance(row.adornment, InlineSvg) else ""
    overflow = "visible" if isinstance(row.adornment, KeyValuePopover) else "hidden"
    rendered = render_adornment(row.adornment, theme=theme, chrome=chrome)
    return (
        f'<div style="height:{row.height}px;overflow:{overflow};'
        f'margin:0{gap}{svg_containment}">{rendered}</div>'
    )


def _render_section(rows: tuple[RenderRow, ...], *, theme: Theme, chrome: CardChrome) -> str:
    return "".join(_render_row(row, theme=theme, chrome=chrome) for row in rows)


@dataclass(frozen=True, slots=True)
class MeasuredReport:
    """Exact outer geometry of a rendered report."""

    width: int
    height: int
    graph_top: int


@dataclass(frozen=True, slots=True)
class GraphReport:
    """Stack adornments, a graph canvas, then more adornments."""

    graph: Graph
    header: tuple[Adornment, ...] = ()
    footer: tuple[Adornment, ...] = ()
    gap: int = 16
    font: Literal["inherit", "system"] = "inherit"
    _measured: MeasuredReport = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate and cache the exact composite geometry."""
        if not isinstance(self.graph, Graph):
            raise SpecError("GraphReport.graph must be a Graph")
        if not isinstance(self.gap, int) or isinstance(self.gap, bool) or self.gap < 0:
            raise SpecError("GraphReport.gap must be a non-negative int")
        if self.font not in ("inherit", "system"):
            raise SpecError("GraphReport.font must be inherit or system")
        object.__setattr__(self, "header", _canonical(self.header, name="GraphReport.header"))
        object.__setattr__(self, "footer", _canonical(self.footer, name="GraphReport.footer"))
        object.__setattr__(self, "_measured", self._compute())

    def _rows(self, *, width: int) -> tuple[tuple[RenderRow, ...], tuple[RenderRow, ...]]:
        """Resolve header and footer adornments at a given outer width."""
        chrome = self.graph.chrome
        header_rows = resolve_rows(
            self.header, usable=width, chrome=chrome, section="GraphReport.header"
        )
        footer_rows = resolve_rows(
            self.footer, usable=width, chrome=chrome, section="GraphReport.footer"
        )
        return header_rows, footer_rows

    def _compute(self) -> MeasuredReport:
        """Derive the composite's exact outer geometry from its parts."""
        graph_measured = self.graph.measure()
        chrome = self.graph.chrome
        width = max(
            graph_measured.width,
            _section_natural_width(self.header, chrome=chrome),
            _section_natural_width(self.footer, chrome=chrome),
        )
        header_rows, footer_rows = self._rows(width=width)
        header_height = _section_height(header_rows)
        footer_height = _section_height(footer_rows)
        graph_top = header_height + self.gap if header_rows else 0
        height = (
            header_height
            + (self.gap if header_rows else 0)
            + graph_measured.height
            + (self.gap if footer_rows else 0)
            + footer_height
        )
        return MeasuredReport(width=width, height=height, graph_top=graph_top)

    def measure(self) -> MeasuredReport:
        """Return this report's cached exact geometry."""
        return self._measured

    def as_raw_html(self) -> str:
        """Render the report as deterministic standalone HTML."""
        measured = self._measured
        theme = self.graph.theme
        chrome = self.graph.chrome
        header_rows, footer_rows = self._rows(width=measured.width)
        header_html = _render_section(header_rows, theme=theme, chrome=chrome)
        graph_html = self.graph.as_raw_html()
        if header_rows:
            graph_html = f'<div style="margin-top:{self.gap}px">{graph_html}</div>'
        footer_html = _render_section(footer_rows, theme=theme, chrome=chrome)
        if footer_rows:
            footer_html = f'<div style="margin-top:{self.gap}px">{footer_html}</div>'
        font = (
            ";font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif"
            if self.font == "system"
            else ""
        )
        return (
            f'<div style="position:relative;box-sizing:border-box;'
            f'width:{measured.width}px;height:{measured.height}px;margin:0;padding:0{font}">'
            f"{header_html}{graph_html}{footer_html}</div>"
        )

    def _repr_html_(self) -> str:
        """Render for notebook display."""
        return self.as_raw_html()
