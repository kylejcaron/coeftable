"""Contract tests for panel composition."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest

from coeftable.cards import (
    DEFAULT_CHROME,
    CardChrome,
    InlineSvg,
    KeyValuePopover,
    Pane,
    Panel,
    Row,
    TextBlock,
    Trend,
)
from coeftable.cards.adornments import Adornment
from coeftable.errors import SpecError
from coeftable.theme import BLUE, Theme


class RecordingRegion:
    def __init__(self, name: str, calls: list[tuple[str, int, CardChrome, Theme]]) -> None:
        self.name = name
        self.calls = calls

    def resolve(self, *, width: int, theme: Theme, chrome: CardChrome) -> tuple[Adornment, ...]:
        self.calls.append((self.name, width, chrome, theme))
        return (TextBlock(self.name),)


def _panel(*, pane_width: int = 80, content=(), header=(), footer=()) -> Panel:
    return Panel(
        panes=(Pane("main", content=content, width=pane_width),),
        header=header,
        footer=footer,
    )


def test_panel_derives_width_and_exact_height_without_shared_stacks():
    panel = _panel(pane_width=80)
    measured = panel.measure()
    assert measured.width == 80 + 2 * (DEFAULT_CHROME.padding + DEFAULT_CHROME.border_width)
    assert measured.pane_heights == (19,)
    assert measured.height == 2 * (DEFAULT_CHROME.padding + DEFAULT_CHROME.border_width) + 19


def test_panel_box_model_counts_header_footer_dividers_only_when_nonempty():
    chrome = DEFAULT_CHROME
    row = Row(((TextBlock("h"), 80),))
    panel = _panel(pane_width=80, header=(row,), footer=(TextBlock("f"),))
    measured = panel.measure()
    expected = (
        2 * (chrome.border_width + chrome.padding)
        + 16
        + chrome.border_width
        + chrome.header_gap
        + 19
        + chrome.header_gap
        + chrome.border_width
        + 16
    )
    assert measured.height == expected


@pytest.mark.parametrize(
    "build",
    [
        lambda: Row(()),
        lambda: Row(((TextBlock("x"), 0),)),
        lambda: Row(((TextBlock("x"), -1),)),
        lambda: Row(((TextBlock("x"), True),)),
        lambda: Row(((TextBlock("x"), 1),), gap=0),
        lambda: Row(((TextBlock("x"), 1),), gap=True),
        lambda: Row(cast(Any, ((TextBlock("x"), 1, 2),))),
        lambda: Row(cast(Any, (([TextBlock("x"), 1],),))),
        lambda: Row(cast(Any, ((Row(((TextBlock("x"), 1),)), 1),))),
        lambda: Pane("", content=(), width=10),
        lambda: Pane("x", content=(), width=0),
        lambda: Pane("x", content=(), width=True),
        lambda: Panel(()),
        lambda: Panel((Pane("x", content=(), width=10), Pane("x", content=(), width=10))),
    ],
)
def test_panel_construction_validation(build):
    with pytest.raises(SpecError):
        build()


def test_row_canonicalizes_and_is_frozen_and_slotted():
    cells = [(TextBlock("x"), 20)]
    row = Row(cast(Any, cells))
    cells.append((TextBlock("y"), 20))
    assert row.cells == ((TextBlock("x"), 20),)
    with pytest.raises(FrozenInstanceError):
        cast(Any, row).cells = ()
    assert not hasattr(row, "__dict__")


def test_panel_canonicalizes_public_sequences_and_is_frozen_and_slotted():
    panes = [Pane("x", content=cast(Any, [TextBlock("x")]), width=40)]
    header = [TextBlock("h")]
    footer = [TextBlock("f")]
    panel = Panel(cast(Any, panes), header=cast(Any, header), footer=cast(Any, footer))
    panes.clear()
    header.clear()
    footer.clear()
    assert len(panel.panes) == 1 and panel.header and panel.footer
    assert not hasattr(panel, "__dict__")
    with pytest.raises(FrozenInstanceError):
        cast(Any, panel).panes = ()
    assert not hasattr(panel.panes[0], "__dict__")
    assert not hasattr(panel.measure(), "__dict__")


@pytest.mark.parametrize("where", ["content", "header", "footer"])
def test_rows_must_fit_their_container(where):
    too_wide = Row(((TextBlock("a"), 51), (TextBlock("b"), 50)), gap=1)
    kwargs = {where: (too_wide,)}
    with pytest.raises(SpecError):
        _panel(pane_width=80, **kwargs)


def test_header_and_footer_rows_use_derived_full_inner_width():
    row = Row(((TextBlock("a"), 60), (TextBlock("b"), 59)), gap=1)
    panel = Panel(
        (Pane("a", content=(), width=60), Pane("b", content=(), width=60)),
        gap=10,
        header=(row,),
    )
    assert panel.measure().width == 60 + 60 + 10 + 2 * (16 + 1)


def test_multiline_cell_stacks_and_row_height_uses_max_cell_height():
    trend = Trend(
        x=(0, 1),
        y=(1, 2),
        x_domain=(0, 1),
        domain=(0, 2),
        endpoint_width=20,
    )
    row = Row(((trend, 40), (TextBlock("short"), 40)))
    panel = _panel(pane_width=90, content=(row,))
    assert panel.measure().pane_heights == (19 + DEFAULT_CHROME.header_gap + 30 + 22 + 8,)
    assert "column-gap:10px" in panel.as_raw_html()


def test_regions_resolve_once_in_traversal_order_and_with_theme_repeats_it():
    calls: list[tuple[str, int, CardChrome, Theme]] = []
    header_region = RecordingRegion("header", calls)
    pane_region = RecordingRegion("pane", calls)
    cell_region = RecordingRegion("cell", calls)
    footer_region = RecordingRegion("footer", calls)
    panel = Panel(
        (Pane("main", content=(pane_region, Row(((cell_region, 25),))), width=50),),
        header=(header_region,),
        footer=(footer_region,),
    )
    inner = panel.measure().width - 2 * (DEFAULT_CHROME.padding + DEFAULT_CHROME.border_width)
    assert [(name, width) for name, width, _, _ in calls] == [
        ("header", inner),
        ("pane", 50),
        ("cell", 25),
        ("footer", inner),
    ]
    themed = panel.with_theme(BLUE)
    assert [(name, width) for name, width, _, _ in calls[4:]] == [
        ("header", inner),
        ("pane", 50),
        ("cell", 25),
        ("footer", inner),
    ]
    assert themed is not panel


def test_raw_adornment_is_not_resolved_and_popover_wrapper_overflows():
    popover = KeyValuePopover("details", (("key", "value"),))
    panel = _panel(
        pane_width=80,
        content=(popover, InlineSvg('<svg width="10" height="2"></svg>', 10, 2)),
    )
    html = panel.as_raw_html()
    assert "overflow:visible" in html
    assert "line-height:0" in html


def test_rendering_is_deterministic_and_repr_html_matches():
    panel = _panel(content=(TextBlock("hello"),))
    assert panel.as_raw_html() == panel.as_raw_html()
    assert panel._repr_html_() == panel.as_raw_html()
    assert "<details" not in panel.as_raw_html()


def test_panel_module_does_not_import_plots():
    source = Path("src/coeftable/cards/panel.py").read_text()
    assert "coeftable.plots" not in source
