"""Horizontal panes composed into one measured panel shell."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import cast

from coeftable.cards.adornments import (
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
)
from coeftable.cards.chrome import DEFAULT_CHROME, CardChrome
from coeftable.cards.fragments import _esc, _wrap
from coeftable.cards.measure import RenderRow, resolve_rows
from coeftable.cards.regions import Region, _canonical, resolve_content
from coeftable.errors import SpecError
from coeftable.theme import DEFAULT, Theme

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


def _positive_int(value: object, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SpecError(f"{name} must be a positive int")


def _is_item(value: object) -> bool:
    return isinstance(value, _ADORNMENT_TYPES) or isinstance(value, Region)


def _validate_item(value: object, *, name: str) -> None:
    if not _is_item(value) and not isinstance(value, Row):
        raise SpecError(f"{name} must be a Region, Adornment, or Row")


@dataclass(frozen=True, slots=True)
class Row:
    """One horizontal line of independently measured cells."""

    cells: tuple[tuple[Region | Adornment, int], ...]
    gap: int = 10

    def __post_init__(self) -> None:
        """Canonicalize and validate the intrinsic row contract."""
        cells = _canonical(self.cells, name="Row.cells")
        if not cells:
            raise SpecError("Row.cells must not be empty")
        canonical: list[tuple[Region | Adornment, int]] = []
        for index, cell in enumerate(cells):
            if type(cell) is not tuple or len(cell) != 2:
                raise SpecError(f"Row.cells[{index}] must be an exact (item, width) pair")
            item, width = cell
            if isinstance(item, Row):
                raise SpecError(f"Row.cells[{index}] must not contain a nested Row")
            if not _is_item(item):
                raise SpecError(f"Row.cells[{index}][0] must be a Region or Adornment")
            _positive_int(width, name=f"Row.cells[{index}][1]")
            canonical.append((cast(Region | Adornment, item), cast(int, width)))
        _positive_int(self.gap, name="Row.gap")
        object.__setattr__(self, "cells", tuple(canonical))


@dataclass(frozen=True, slots=True)
class Pane:
    """A named vertical stack with a declared usable width."""

    title: str
    content: tuple[Region | Adornment | Row, ...]
    width: int
    subtitle: str | None = None

    def __post_init__(self) -> None:
        """Canonicalize and validate pane declarations."""
        if not isinstance(self.title, str) or not self.title:
            raise SpecError("Pane.title must be a non-empty str")
        if self.subtitle is not None and not isinstance(self.subtitle, str):
            raise SpecError("Pane.subtitle must be a str")
        _positive_int(self.width, name="Pane.width")
        content = _canonical(self.content, name="Pane.content")
        for index, item in enumerate(content):
            _validate_item(item, name=f"Pane.content[{index}]")
        object.__setattr__(self, "content", cast(tuple[Region | Adornment | Row, ...], content))


@dataclass(frozen=True, slots=True)
class MeasuredPanel:
    """The exact border-box footprint of a panel."""

    width: int
    height: int
    pane_heights: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _ResolvedContent:
    """Cached resolved rows for one plain item or one composed Row."""

    rows: tuple[RenderRow, ...] = ()
    cells: tuple[tuple[int, tuple[RenderRow, ...]], ...] = ()
    width: int = 0
    gap: int = 0
    height: int = 0


@dataclass(frozen=True, slots=True)
class _ResolvedEntry:
    """One stack entry and its inter-entry vertical spacing."""

    content: _ResolvedContent
    gap_above: int = 0


@dataclass(frozen=True, slots=True)
class _ResolvedPane:
    """A pane's cached heading, body, width, and measured height."""

    width: int
    heading: tuple[_ResolvedEntry, ...]
    content: tuple[_ResolvedEntry, ...]
    height: int


@dataclass(frozen=True, slots=True)
class _PanelLayout:
    """Everything needed by measurement and rendering after construction."""

    width: int
    inner_width: int
    header: tuple[_ResolvedEntry, ...]
    panes: tuple[_ResolvedPane, ...]
    footer: tuple[_ResolvedEntry, ...]
    measured: MeasuredPanel


def _rows_height(rows: tuple[RenderRow, ...]) -> int:
    return sum(row.height + row.gap_above for row in rows)


def _content_height(content: _ResolvedContent) -> int:
    if content.cells:
        return content.height
    return _rows_height(content.rows)


def _stack_height(stack: tuple[_ResolvedEntry, ...]) -> int:
    return sum(entry.gap_above + _content_height(entry.content) for entry in stack)


@dataclass(frozen=True, slots=True)
class Panel:
    """One bordered shell containing one or more named panes."""

    panes: tuple[Pane, ...]
    header: tuple[Region | Adornment | Row, ...] = ()
    footer: tuple[Region | Adornment | Row, ...] = ()
    gap: int = 36
    chrome: CardChrome = DEFAULT_CHROME
    theme: Theme = DEFAULT
    _layout: _PanelLayout = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Validate declarations and resolve every Region exactly once."""
        panes = _canonical(self.panes, name="Panel.panes")
        if not panes:
            raise SpecError("Panel.panes must not be empty")
        if any(not isinstance(pane, Pane) for pane in panes):
            raise SpecError("Panel.panes entries must be Pane instances")
        panes = tuple(cast(Pane, pane) for pane in panes)
        if len({pane.title for pane in panes}) != len(panes):
            raise SpecError("Panel.panes titles must be unique")
        header = _canonical(self.header, name="Panel.header")
        footer = _canonical(self.footer, name="Panel.footer")
        for name, entries in (("Panel.header", header), ("Panel.footer", footer)):
            for index, item in enumerate(entries):
                _validate_item(item, name=f"{name}[{index}]")
        _positive_int(self.gap, name="Panel.gap")
        if not isinstance(self.chrome, CardChrome):
            raise SpecError("Panel.chrome must be a CardChrome")
        if not isinstance(self.theme, Theme):
            raise SpecError("Panel.theme must be a Theme")
        header = cast(tuple[Region | Adornment | Row, ...], header)
        footer = cast(tuple[Region | Adornment | Row, ...], footer)
        object.__setattr__(self, "panes", panes)
        object.__setattr__(self, "header", header)
        object.__setattr__(self, "footer", footer)

        inner_width = sum(pane.width for pane in panes) + self.gap * (len(panes) - 1)
        header_layout = self._resolve_stack(header, width=inner_width, section="header")
        pane_layouts: list[_ResolvedPane] = []
        for index, pane in enumerate(panes):
            heading_items: tuple[Region | Adornment | Row, ...] = (
                TextBlock(pane.title, variant="title"),
            )
            if pane.subtitle is not None:
                heading_items += (TextBlock(pane.subtitle, variant="subtitle"),)
            heading = self._resolve_stack(
                heading_items, width=pane.width, section=f"panes[{index}].heading"
            )
            content = self._resolve_stack(
                pane.content, width=pane.width, section=f"panes[{index}].content"
            )
            pane_height = _stack_height(heading)
            if _stack_height(content):
                pane_height += self.chrome.header_gap
            pane_height += _stack_height(content)
            pane_layouts.append(
                _ResolvedPane(
                    width=pane.width,
                    heading=heading,
                    content=content,
                    height=pane_height,
                )
            )
        footer_layout = self._resolve_stack(footer, width=inner_width, section="footer")

        width = inner_width + 2 * (self.chrome.padding + self.chrome.border_width)
        height = 2 * (self.chrome.border_width + self.chrome.padding)
        height += _stack_height(header_layout)
        if _stack_height(header_layout):
            height += self.chrome.border_width + self.chrome.header_gap
        height += max(pane.height for pane in pane_layouts)
        if _stack_height(footer_layout):
            height += self.chrome.header_gap + self.chrome.border_width
        height += _stack_height(footer_layout)
        measured = MeasuredPanel(
            width=width,
            height=height,
            pane_heights=tuple(pane.height for pane in pane_layouts),
        )
        object.__setattr__(
            self,
            "_layout",
            _PanelLayout(
                width=width,
                inner_width=inner_width,
                header=header_layout,
                panes=tuple(pane_layouts),
                footer=footer_layout,
                measured=measured,
            ),
        )

    def _resolve_stack(
        self,
        items: Sequence[Region | Adornment | Row],
        *,
        width: int,
        section: str,
    ) -> tuple[_ResolvedEntry, ...]:
        """Resolve a stack in declaration order, preserving its cached geometry."""
        entries: list[_ResolvedEntry] = []
        has_output = False
        for index, item in enumerate(items):
            if isinstance(item, Row):
                row_width = sum(cell_width for _, cell_width in item.cells) + item.gap * (
                    len(item.cells) - 1
                )
                if row_width > width:
                    raise SpecError(
                        f"{section}[{index}]: Row width {row_width}px exceeds usable {width}px"
                    )
                cells: list[tuple[int, tuple[RenderRow, ...]]] = []
                for cell_index, (cell_item, cell_width) in enumerate(item.cells):
                    adornments = resolve_content(
                        (cell_item,), width=cell_width, theme=self.theme, chrome=self.chrome
                    )
                    rows = resolve_rows(
                        adornments,
                        usable=cell_width,
                        chrome=self.chrome,
                        section=f"{section}[{index}].cells[{cell_index}]",
                    )
                    cells.append((cell_width, rows))
                resolved = _ResolvedContent(
                    cells=tuple(cells),
                    width=row_width,
                    gap=item.gap,
                    height=max((_rows_height(rows) for _, rows in cells), default=0),
                )
            else:
                adornments = resolve_content(
                    (item,), width=width, theme=self.theme, chrome=self.chrome
                )
                rows = resolve_rows(
                    adornments,
                    usable=width,
                    chrome=self.chrome,
                    section=f"{section}[{index}]",
                )
                resolved = _ResolvedContent(rows=rows)
            gap_above = self.chrome.gap if has_output and _content_height(resolved) else 0
            entries.append(_ResolvedEntry(resolved, gap_above))
            has_output = has_output or _content_height(resolved) > 0
        return tuple(entries)

    def measure(self) -> MeasuredPanel:
        """Return this panel's cached exact border-box footprint."""
        return self._layout.measured

    def as_raw_html(self) -> str:
        """Render the cached panel layout as deterministic standalone HTML."""
        chrome = self.chrome
        layout = self._layout
        header_html = _render_stack(layout.header, theme=self.theme, chrome=chrome)
        pane_html = []
        for pane in layout.panes:
            heading_html = _render_stack(pane.heading, theme=self.theme, chrome=chrome)
            content_html = _render_stack(pane.content, theme=self.theme, chrome=chrome)
            content_block = ""
            if _stack_height(pane.content):
                content_block = (
                    f'<div style="height:{chrome.header_gap}px;margin:0;padding:0"></div>'
                    f"{content_html}"
                )
            pane_html.append(
                f'<div style="box-sizing:border-box;flex:0 0 {pane.width}px;width:{pane.width}px;'
                f'height:{pane.height}px;margin:0;padding:0;overflow:visible">'
                f"{heading_html}{content_block}</div>"
            )
        header_divider = ""
        if _stack_height(layout.header):
            header_divider = (
                f'<div style="box-sizing:border-box;'
                f"height:{chrome.header_gap + chrome.border_width}px;"
                f'border-bottom:{chrome.border_width}px solid {_esc(self.theme.rule)}"></div>'
            )
        footer_divider = ""
        if _stack_height(layout.footer):
            footer_divider = (
                f'<div style="box-sizing:border-box;'
                f"height:{chrome.header_gap + chrome.border_width}px;"
                f'border-top:{chrome.border_width}px solid {_esc(self.theme.rule)}"></div>'
            )
        footer_html = _render_stack(layout.footer, theme=self.theme, chrome=chrome)
        panes_html = (
            f'<div style="display:flex;align-items:flex-start;column-gap:{self.gap}px;">'
            f"{''.join(pane_html)}</div>"
        )
        return (
            f'<div style="box-sizing:border-box;width:{layout.width}px;'
            f"height:{layout.measured.height}px;margin:0;"
            f"padding:{chrome.padding}px;"
            f"border:{chrome.border_width}px solid {_esc(self.theme.rule)};"
            f'border-radius:{chrome.radius}px;background:{_esc(self.theme.surface)};overflow:visible">'
            f"{header_html}{header_divider}{panes_html}{footer_divider}{footer_html}</div>"
        )

    def _repr_html_(self) -> str:
        return self.as_raw_html()

    def with_theme(self, theme: Theme) -> Panel:
        """Return a copy that re-resolves Regions under ``theme``."""
        return replace(self, theme=theme)


def _render_stack(stack: tuple[_ResolvedEntry, ...], *, theme: Theme, chrome: CardChrome) -> str:
    """Render cached stack entries without recomputing geometry."""
    chunks: list[str] = []
    for entry in stack:
        content = entry.content
        if content.cells:
            cells = []
            for width, rows in content.cells:
                rows_html = "".join(_wrap(row, theme, chrome) for row in rows)
                cells.append(
                    f'<div style="box-sizing:border-box;flex:0 0 {width}px;width:{width}px;'
                    f'margin:0;padding:0;align-self:flex-start">{rows_html}</div>'
                )
            rendered = (
                f'<div style="display:flex;align-items:flex-start;column-gap:{content.gap}px;'
                f'width:{content.width}px;height:{content.height}px;margin:0;padding:0">'
                f"{''.join(cells)}</div>"
            )
        else:
            rendered = "".join(_wrap(row, theme, chrome) for row in content.rows)
        if entry.gap_above:
            rendered = f'<div style="margin-top:{entry.gap_above}px">{rendered}</div>'
        chunks.append(rendered)
    return "".join(chunks)
