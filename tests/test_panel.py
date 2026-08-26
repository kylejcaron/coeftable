"""Contract tests for panel composition."""

import math
import re
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any, cast

import pytest

from coeftable.cards import (
    DEFAULT_CHROME,
    CardChrome,
    Event,
    Events,
    InlineSvg,
    KeyValuePopover,
    Metric,
    Pane,
    Panel,
    Row,
    TextBlock,
    Trend,
)
from coeftable.cards.adornments import Adornment
from coeftable.errors import SpecError
from coeftable.format import Number
from coeftable.plots import Trace, sparkline_axis, sparkline_multi
from coeftable.theme import BLUE, DEFAULT, Theme, role_for


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
        # The suppressions below are deliberate: invalid inputs must raise SpecError.
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

    empty_content = Panel((Pane("x", content=(Empty(),), width=200),))
    truly_empty = Panel((Pane("x", content=(), width=200),))
    assert empty_content.measure() == truly_empty.measure()
    assert empty_content.as_raw_html() == truly_empty.as_raw_html()


def test_rendering_is_deterministic_and_repr_html_matches():
    panel = _panel(content=(TextBlock("hello"),))
    assert panel.as_raw_html() == panel.as_raw_html()
    assert panel._repr_html_() == panel.as_raw_html()
    assert "<details" not in panel.as_raw_html()


def test_panel_module_does_not_import_plots():
    source = Path("src/coeftable/cards/panel.py").read_text()
    assert "coeftable.plots" not in source


def test_retention_fixture_reproduces_the_panel_through_public_api():
    """Build the two-pane retention report from one cohort matrix."""
    cohorts = 12
    sample_sizes = [2400, 2550, 2380, 2620, 2700, 2510, 2660, 2810, 2740, 2900, 2830, 2960]
    anchors: dict[str, list[float | None]] = {
        "D7": [0.421, 0.428, 0.419, 0.431, 0.425, 0.433, 0.462, 0.471, 0.468, 0.479, 0.474, 0.482],
        "D30": [
            0.252,
            0.249,
            0.255,
            0.251,
            0.257,
            0.254,
            0.259,
            0.263,
            0.258,
            0.266,
            0.261,
            0.267,
        ],
        "D90": [0.148, 0.151, 0.146, 0.153, 0.150, None, None, None, None, None, None, None],
    }
    pcts = Number(suffix="%", decimals=1, thousands=False)
    signed_points = Number(suffix=" pp", decimals=1, signed=True, thousands=False)
    event_color = DEFAULT.series_color(1)
    events = Events((Event("W7 onboarding revamp", event_color, dash="dashed", at=6.0),))

    def _se(proportion: float, n: int) -> float:
        return math.sqrt(proportion * (1.0 - proportion) / n)

    def _gradient(start: str, end: str, position: float) -> str:
        channels = tuple(
            round(
                int(start[index : index + 2], 16) * (1.0 - position)
                + int(end[index : index + 2], 16) * position
            )
            for index in (1, 3, 5)
        )
        return "#" + "".join(f"{channel:02X}" for channel in channels)

    def _inline_svg(svg: str, width: int) -> InlineSvg:
        root = re.search(r'<svg\b[^>]*\bwidth="(\d+)"[^>]*\bheight="(\d+)"', svg)
        assert root is not None
        assert int(root.group(1)) == width
        return InlineSvg(svg, width, int(root.group(2)))

    def _svg_height(svg: str) -> int:
        match = re.search(r'<svg\b[^>]*\bheight="(\d+)"', svg)
        assert match is not None
        return int(match.group(1))

    def _journey() -> tuple[InlineSvg, InlineSvg]:
        traces = []
        base_curve = [
            1.0,
            0.43,
            0.36,
            0.31,
            0.25,
            0.225,
            0.205,
            0.19,
            0.178,
            0.168,
            0.16,
            0.154,
            0.148,
        ]
        for cohort in range(cohorts):
            ages = list(range(1, cohorts + 1 - cohort))
            if len(ages) < 2:
                continue
            d7 = anchors["D7"][cohort]
            assert d7 is not None
            scale = d7 / base_curve[1]
            values = [base_curve[age] * scale * 100.0 for age in ages]
            traces.append(
                Trace(
                    x=[float(age) for age in ages],
                    y=values,
                    lower=values,
                    upper=values,
                    color=_gradient("#C9CDD3", "#2F4A6E", cohort / (cohorts - 1)),
                    show_ribbon=False,
                    label=f"W{cohort + 1}",
                )
            )
        width = 430
        inset = 3
        show_endpoint = False
        endpoint_width = 44
        spark = sparkline_multi(
            traces,
            x_domain=(1.0, float(cohorts)),
            domain=(12.0, 56.0),
            ref=None,
            ref_color=DEFAULT.muted,
            fmt=pcts,
            width=width,
            height=168,
            inset=inset,
            show_endpoint=show_endpoint,
            endpoint_width=endpoint_width,
            theme=DEFAULT,
        )

        def _week(value: float) -> str:
            return f"wk {value:g}"

        axis = sparkline_axis(
            x_domain=(1.0, float(cohorts)),
            fmt=_week,
            theme=DEFAULT,
            width=width,
            height=22,
            inset=inset,
            show_endpoint=show_endpoint,
            endpoint_width=endpoint_width,
        )
        return _inline_svg(spark, width), _inline_svg(axis, width)

    journey_spark, journey_axis = _journey()

    def _trend_row(label: str, values: list[float | None]) -> Row:
        observed = [
            (value, n) for value, n in zip(values, sample_sizes, strict=True) if value is not None
        ]
        (first, first_n), (last, last_n) = observed[0], observed[-1]
        delta = (last - first) * 100.0
        endpoint_2se = 2.0 * math.sqrt(_se(first, first_n) ** 2 + _se(last, last_n) ** 2) * 100.0
        lower_delta, upper_delta = delta - endpoint_2se, delta + endpoint_2se
        verdict = role_for(lower_delta, upper_delta, 0.0, "higher_is_better")
        lower = [
            None if value is None else (value - 2.0 * _se(value, n)) * 100.0
            for value, n in zip(values, sample_sizes, strict=True)
        ]
        upper = [
            None if value is None else (value + 2.0 * _se(value, n)) * 100.0
            for value, n in zip(values, sample_sizes, strict=True)
        ]
        observed_values = [value for value in values if value is not None]
        span = ((max(observed_values) - min(observed_values)) or 0.02) * 100.0
        lower_observed = [value for value in lower if value is not None]
        upper_observed = [value for value in upper if value is not None]
        domain = (
            min(lower_observed) - 0.3 * span,
            max(upper_observed) + 0.3 * span,
        )
        arrow = "▴" if delta >= 0.0 else "▾"
        delta_text = f"{arrow} {signed_points(delta)}"
        if verdict == "inconclusive":
            delta_text += " · ns"
        trend = Trend(
            x=tuple(float(index) for index in range(cohorts)),
            y=tuple(None if value is None else value * 100.0 for value in values),
            lower=tuple(lower),
            upper=tuple(upper),
            x_domain=(0.0, float(cohorts - 1)),
            domain=domain,
            fmt=pcts,
            direction="higher_is_better",
            role=verdict,
            height=30,
            show_axis=False,
            show_endpoint=False,
            inset=3,
            annotations=events.rules(),
        )
        return Row(
            (
                (TextBlock(label), 34),
                (TextBlock(pcts(observed[-1][0] * 100.0)), 52),
                (TextBlock(delta_text), 86),
                (trend, 240),
            ),
            gap=10,
        )

    trend_rows = tuple(_trend_row(label, values) for label, values in anchors.items())
    assert len(sample_sizes) == cohorts
    assert all(len(values) == cohorts for values in anchors.values())
    d7_first, d7_last = anchors["D7"][0], anchors["D7"][-1]
    d30_last = anchors["D30"][-1]
    assert d7_first is not None and d7_last is not None and d30_last is not None
    header = Row(
        (
            (TextBlock("Retention · weekly signup cohorts", variant="title"), 540),
            (Metric((d7_last - d7_first) * 100.0, signed_points), 180),
            (Metric(d30_last * 100.0, pcts), 160),
        ),
        gap=14,
    )
    assert tuple(width for _, width in header.cells) == (540, 180, 160)
    assert all(tuple(width for _, width in row.cells) == (34, 52, 86, 240) for row in trend_rows)
    journey = Pane(
        "The journey",
        subtitle="retention by weeks since signup, one curve per cohort",
        content=(
            journey_spark,
            journey_axis,
            TextBlock(
                "newest cohorts darker; shorter curve = younger cohort (censored). "
                "W12 has one point and is not drawn.",
                variant="caption",
            ),
        ),
        width=430,
    )
    trend = Pane(
        "The trend",
        subtitle="retention at fixed ages, by signup cohort",
        content=(
            *trend_rows,
            TextBlock(
                "ribbon = ±2se (binomial); ns = change within endpoint uncertainty",
                variant="caption",
            ),
        ),
        width=442,
    )
    panel = Panel(
        (journey, trend),
        header=(header,),
        footer=(
            events,
            TextBlock(
                "W7 onboarding revamp (applies to cohorts, so it marks the trend pane)",
                variant="caption",
            ),
        ),
    )

    measured = panel.measure()
    chrome = DEFAULT_CHROME
    html = panel.as_raw_html()
    svg_blocks = re.findall(r"<svg\b[^>]*>.*?</svg>", html, flags=re.DOTALL)
    journey_svgs = [svg for svg in svg_blocks if 'width="430"' in svg]
    trend_svgs = [svg for svg in svg_blocks if 'width="240"' in svg and 'height="30"' in svg]
    assert len(journey_svgs) == 2
    assert len(trend_svgs) == 3
    journey_svg = next(svg for svg in journey_svgs if 'height="168"' in svg)
    journey_axis_svg = next(svg for svg in journey_svgs if svg != journey_svg)
    journey_axis_height = _svg_height(journey_axis_svg)
    for svg in trend_svgs:
        assert "<text" not in svg  # compact rows: no axis, no endpoint label
        points = re.findall(r'<polyline[^>]*points="([^"]+)"', svg)
        assert points
        for chunk in points:
            for pair in chunk.split():
                y_value = float(pair.split(",")[1])
                assert 0.0 <= y_value <= 30.0  # projected data stays inside the plot box

    title_height = math.ceil(chrome.title_size * chrome.leading)
    subtitle_height = math.ceil(chrome.subtitle_size * chrome.leading)
    caption_height = math.ceil(chrome.caption_size * chrome.leading)
    header_height = math.ceil(max(chrome.value_size, chrome.ci_size) * chrome.leading)
    heading_height = title_height + chrome.gap + subtitle_height
    journey_content_height = 168 + chrome.gap + journey_axis_height + chrome.gap + caption_height
    journey_height = heading_height + chrome.header_gap + journey_content_height
    trend_row_height = 30
    trend_content_height = (
        trend_row_height
        + chrome.gap
        + trend_row_height
        + chrome.gap
        + trend_row_height
        + chrome.gap
        + caption_height
    )
    trend_height = heading_height + chrome.header_gap + trend_content_height
    footer_height = caption_height + chrome.gap + caption_height
    expected_height = (
        2 * (chrome.border_width + chrome.padding)
        + header_height
        + chrome.border_width
        + chrome.header_gap
        + max(journey_height, trend_height)
        + chrome.header_gap
        + chrome.border_width
        + footer_height
    )
    assert measured.width == 430 + 442 + 36 + 2 * (16 + 1) == 942
    assert measured.pane_heights == (journey_height, trend_height)
    assert measured.height == expected_height
    assert measured.height == 388

    shell_style = re.match(r'<div style="([^"]+)">', html)
    assert shell_style is not None
    assert f"width:{measured.width}px" in shell_style.group(1)
    assert f"height:{measured.height}px" in shell_style.group(1)

    journey_polylines = re.findall(r'<polyline points="([^"]+)"[^>]*stroke="([^"]+)"', journey_svg)
    assert len(journey_polylines) == 11
    endpoint_x = [float(points.split()[-1].split(",", 1)[0]) for points, _ in journey_polylines]
    assert endpoint_x == sorted(endpoint_x, reverse=True)
    expected_colors = [
        _gradient("#C9CDD3", "#2F4A6E", cohort / (cohorts - 1)) for cohort in range(cohorts - 1)
    ]
    assert [color for _, color in journey_polylines] == expected_colors
    assert sum(svg.count("<polygon ") for svg in trend_svgs) == 3
    assert all(svg.count("<polygon ") == 1 for svg in trend_svgs)
    trend_endpoints = [
        float(re.findall(r'<polyline points="([^"]+)"', svg)[-1].split()[-1].split(",", 1)[0])
        for svg in trend_svgs
    ]
    assert trend_endpoints[0] == trend_endpoints[1] > trend_endpoints[2]
    event_mark = (
        f'stroke="{event_color}" stroke-opacity="1.00" stroke-width="1.00" stroke-dasharray="2,2"'
    )
    assert html.count(event_mark) == 3
    assert f"border-top:{chrome.swatch_thickness}px dashed {event_color}" in html
    assert panel.header == (header,)
    assert html.count("· ns") == 2
