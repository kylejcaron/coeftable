"""Contract tests for panel composition."""

import re
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
from coeftable.theme import BLUE, DEFAULT, Theme


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
        lambda: Row(((object(), 10),)),  # ty: ignore[invalid-argument-type]
        lambda: Row(((TextBlock("x"), 0),)),
        lambda: Row(((TextBlock("x"), -1),)),
        lambda: Row(((TextBlock("x"), True),)),
        lambda: Row(((TextBlock("x"), 1),), gap=0),
        lambda: Row(((TextBlock("x"), 1),), gap=-1),
        lambda: Row(((TextBlock("x"), 1),), gap=True),
        lambda: Row(cast(Any, ((TextBlock("x"), 1, 2),))),
        lambda: Row(cast(Any, (([TextBlock("x"), 1],),))),
        lambda: Row(cast(Any, ((Row(((TextBlock("x"), 1),)), 1),))),
        lambda: Pane("", content=(), width=10),
        lambda: Pane("x", content=(object(),), width=10),  # ty: ignore[invalid-argument-type]
        lambda: Pane("x", content=(), width=0),
        lambda: Pane("x", content=(), width=-1),
        lambda: Pane("x", content=(), width=True),
        lambda: Panel(()),
        lambda: Panel((object(),)),  # ty: ignore[invalid-argument-type]
        lambda: Panel((Pane("x", content=(), width=10), Pane("x", content=(), width=10))),
        lambda: _panel(header=(object(),)),
        lambda: _panel(footer=(object(),)),
        lambda: Panel((Pane("x", content=(), width=10),), gap=0),
        lambda: Panel((Pane("x", content=(), width=10),), gap=-1),
        lambda: Panel((Pane("x", content=(), width=10),), gap=True),
        # ty: ignore is deliberate: invalid inputs must raise SpecError.
        lambda: Panel(
            (Pane("x", content=(), width=10),),
            chrome=object(),  # ty: ignore[invalid-argument-type]
        ),
        lambda: Panel(
            (Pane("x", content=(), width=10),),
            theme=object(),  # ty: ignore[invalid-argument-type]
        ),
    ],
)
def test_panel_construction_validation(build):
    with pytest.raises(SpecError):
        build()


def test_public_sequences_are_snapshotted_and_all_contract_types_are_frozen():
    row_source = [(TextBlock("cell"), 20)]
    row = Row(cast(Any, row_source))
    row_item = row_source[0][0]
    pane_source = [TextBlock("body")]
    pane = Pane("x", content=cast(Any, pane_source), width=40)
    pane_item = pane_source[0]
    panes_source = [pane]
    header_source = [TextBlock("header")]
    header_item = header_source[0]
    footer_source = [TextBlock("footer")]
    footer_item = footer_source[0]
    panel = Panel(
        cast(Any, panes_source),
        header=cast(Any, header_source),
        footer=cast(Any, footer_source),
    )
    themed = panel.with_theme(BLUE)
    row_source.append((TextBlock("later"), 20))
    pane_source.append(TextBlock("later"))
    panes_source.clear()
    header_source.clear()
    footer_source.clear()
    assert row.cells == ((row_item, 20),)
    assert pane.content == (pane_item,)
    assert panel.panes == (pane,)
    assert panel.header == (header_item,)
    assert panel.footer == (footer_item,)
    assert themed.panes == (pane,)
    assert themed.header == (header_item,)
    assert themed.footer == (footer_item,)
    for obj, attr in (
        (row, "cells"),
        (pane, "content"),
        (panel, "panes"),
        (panel.measure(), "width"),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(cast(Any, obj), attr, ())
    assert not hasattr(row, "__dict__")
    assert not hasattr(pane, "__dict__")
    assert not hasattr(panel, "__dict__")
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
    html = panel.as_raw_html()
    composed_row = re.search(
        r'<div style="display:flex;align-items:flex-start;column-gap:10px;width:90px;'
        r'height:(\d+)px;margin:0;padding:0">',
        html,
    )
    assert composed_row is not None
    assert int(composed_row.group(1)) == 30 + 22 + 8
    assert "align-items:flex-start" in html
    assert "align-self:flex-start" in html


def test_regions_resolve_once_in_traversal_order_and_with_theme_repeats_it():
    calls: list[tuple[str, int, CardChrome, Theme]] = []
    header_region = RecordingRegion("header", calls)
    pane_region = RecordingRegion("pane", calls)
    cell_region = RecordingRegion("cell", calls)
    footer_region = RecordingRegion("footer", calls)
    row = Row(((cell_region, 25),))
    pane = Pane("main", content=(pane_region, row), width=50)
    panel = Panel((pane,), header=(header_region,), footer=(footer_region,))
    inner = panel.measure().width - 2 * (DEFAULT_CHROME.padding + DEFAULT_CHROME.border_width)
    expected_default = [
        ("header", inner, DEFAULT_CHROME, DEFAULT),
        ("pane", 50, DEFAULT_CHROME, DEFAULT),
        ("cell", 25, DEFAULT_CHROME, DEFAULT),
        ("footer", inner, DEFAULT_CHROME, DEFAULT),
    ]
    assert calls == expected_default
    assert panel.header[0] is header_region
    assert panel.panes[0] is pane
    assert panel.panes[0].content[0] is pane_region
    assert panel.panes[0].content[1] is row
    assert panel.panes[0].content[1].cells[0][0] is cell_region
    assert panel.footer[0] is footer_region
    panel.as_raw_html()
    panel.measure()
    assert calls == expected_default
    themed = panel.with_theme(BLUE)
    expected_blue = [
        ("header", inner, DEFAULT_CHROME, BLUE),
        ("pane", 50, DEFAULT_CHROME, BLUE),
        ("cell", 25, DEFAULT_CHROME, BLUE),
        ("footer", inner, DEFAULT_CHROME, BLUE),
    ]
    assert calls == expected_default + expected_blue
    assert themed.header[0] is header_region
    assert themed.panes[0] is pane
    assert themed.panes[0].content[0] is pane_region
    assert themed.panes[0].content[1] is row
    assert themed.panes[0].content[1].cells[0][0] is cell_region
    assert themed.footer[0] is footer_region
    themed.as_raw_html()
    themed.measure()
    assert calls == expected_default + expected_blue
    assert themed is not panel


def test_raw_adornment_row_wrappers_match_overflow_contract():
    popover = KeyValuePopover("details", (("key", "value"),))
    panel = _panel(
        pane_width=80,
        content=(
            popover,
            TextBlock("normal"),
            InlineSvg('<svg width="10" height="2"></svg>', 10, 2),
        ),
    )
    html = panel.as_raw_html()
    assert re.search(r'<div style="height:\d+px;overflow:visible;margin:0"><details', html)
    assert re.search(
        r'<div style="height:\d+px;overflow:hidden;margin:0"><div style="color:', html
    )
    assert "line-height:0" in html


def test_empty_resolving_regions_produce_no_dividers_or_gaps():
    class Empty:
        def resolve(self, *, width, theme, chrome):
            """Resolve to nothing, exercising the resolved-emptiness gates."""
            return ()

    pane = Pane("x", content=(TextBlock("body"),), width=200)
    bare = Panel((pane,))
    phantom = Panel((pane,), header=(Empty(),), footer=(Empty(),))
    assert phantom.measure() == bare.measure()
    assert phantom.as_raw_html().count("border-bottom") == bare.as_raw_html().count(
        "border-bottom"
    )
    assert phantom.as_raw_html().count("border-top") == bare.as_raw_html().count("border-top")


def test_rendering_is_deterministic_and_repr_html_matches():
    panel = _panel(content=(TextBlock("hello"),))
    assert panel.as_raw_html() == panel.as_raw_html()
    assert panel._repr_html_() == panel.as_raw_html()
    assert "<details" not in panel.as_raw_html()


def test_panel_module_does_not_import_plots():
    source = Path("src/coeftable/cards/panel.py").read_text()
    assert "coeftable.plots" not in source
