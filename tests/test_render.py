import random
import re

import polars as pl
import pytest
from great_tables import GT

from coeftable.spec import CoefTable
from coeftable.theme import MONO, TEXTUAL

RAW = {
    "area": ["Core", "Core", "Ops", "Ops"],
    "metric": ["Revenue", "Revenue", "Latency", "Latency"],
    "variant": ["B", "C", "B", "C"],
    "rel": [3.4, -1.2, 0.5, 2.0],
    "rel_lb": [1.2, -4.0, -1.0, 0.8],
    "rel_ub": [5.7, 1.6, 2.0, 3.2],
}


def table(**kwargs):
    return CoefTable(pl.DataFrame(RAW), rows="metric", nest="variant", **kwargs).estimate(
        "Lift %", "rel", ci=("rel_lb", "rel_ub")
    )


def test_gt_returns_a_great_tables_object():
    assert isinstance(table().gt(), GT)


def test_header_text_appears_in_html():
    html = table().header("Results", "Q3").gt().as_raw_html()
    assert "Results" in html
    assert "Q3" in html


def test_inline_svg_survives_rendering():
    html = table().forest("Plot", of="Lift %").gt().as_raw_html()
    assert "<svg" in html
    assert "<rect" in html


def test_forest_column_gets_reduced_vertical_padding():
    html = table().forest("Plot", of="Lift %").gt().as_raw_html()
    assert "padding-top: 2px; padding-bottom: 2px;" in html


def test_default_forest_bar_svg_uses_the_stacked_layout_height():
    # Integration guard: unit tests on _plot_height() and forest_bar()
    # pass height explicitly and can't catch the height=_plot_height(...)
    # argument being dropped at its call site in frame.py -- that would
    # silently regress every real table back to an 18px SVG with a short
    # reference line, the exact bug this fix addresses.
    html = table().forest("Plot", of="Lift %").gt().as_raw_html()
    assert 'height="48"' in html
    assert 'y2="48"' in html


def test_inline_estimate_stays_nowrap_alongside_a_forest_column():
    from coeftable.format import CIStyle

    html = (
        CoefTable(pl.DataFrame(RAW), rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"), ci_style=CIStyle(layout="inline"))
        .forest("Plot", of="Lift %")
        .gt()
        .as_raw_html()
    )
    assert "white-space:nowrap" in html


def test_interval_markup_survives_rendering():
    html = table().gt().as_raw_html()
    assert "3.40" in html
    assert "<br" in html


def test_table_without_forest_emits_no_svg():
    html = table().gt().as_raw_html()
    assert "<svg" not in html


def test_split_columns_emit_spanner_labels():
    raw = {
        "metric": ["Revenue", "Revenue"],
        "method": ["OLS", "DiD"],
        "rel": [3.4, 3.1],
        "rel_lb": [1.2, 1.0],
        "rel_ub": [5.7, 5.2],
    }
    html = (
        CoefTable(pl.DataFrame(raw), rows="metric", split_columns="method")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .gt()
        .as_raw_html()
    )
    assert "OLS" in html
    assert "DiD" in html


def test_groups_emit_section_headers():
    html = table(groups="area").gt().as_raw_html()
    assert "Core" in html
    assert "Ops" in html


def test_theme_colours_reach_the_html():
    html = table().with_theme(MONO).forest("Plot", of="Lift %").gt().as_raw_html()
    assert MONO.color("favorable").lstrip("#").lower() in html.lower()


def test_repr_html_delegates_to_gt():
    assert "<table" in table()._repr_html_()


def test_textual_theme_omits_vertical_borders():
    html = table().with_theme(TEXTUAL).gt().as_raw_html()
    assert "border-left-style: none" in html
    assert "border-right-style: none" in html


def test_textual_theme_uses_border_color_for_structural_borders():
    # Structural rules (table frame, table body, column labels, row
    # groups) must stay visible even though header_bg is a near-white
    # title banner -- they should resolve to border_color, not header_bg.
    import re

    html = table(groups="area").with_theme(TEXTUAL).gt().as_raw_html()
    assert TEXTUAL.border_color is not None
    for selector in (".gt_table", ".gt_col_headings", ".gt_group_heading"):
        match = re.search(re.escape(selector) + r" \{[^}]+\}", html)
        assert match is not None, f"{selector} rule not found in rendered CSS"
        assert TEXTUAL.border_color.lower() in match.group(0).lower(), (
            f"{selector} does not use border_color"
        )
        assert TEXTUAL.header_bg.lower() not in match.group(0).lower(), (
            f"{selector} still leaks header_bg"
        )


def test_blue_theme_is_boxed():
    from coeftable.theme import BLUE

    html = table().with_theme(BLUE).gt().as_raw_html()
    assert "border-left-style: solid" in html
    assert "border-right-style: solid" in html


def test_collapsible_groups_reaches_as_raw_html_and_repr_html_but_not_gt():
    grouped = table(groups="area", collapsible_groups=True)
    assert "data-ct-group" in grouped.as_raw_html()
    assert "data-ct-group" in grouped._repr_html_()
    assert "data-ct-group" not in grouped.gt().as_raw_html()


def test_collapsible_groups_without_groups_is_byte_identical():
    # great_tables assigns a fresh random wrapper-div id per .gt() call, so
    # seed around each render to compare the transform's effect in isolation.
    random.seed(0)
    off = table(collapsible_groups=False).as_raw_html()
    random.seed(0)
    on = table(collapsible_groups=True).as_raw_html()
    assert on == off


def test_collapsible_groups_false_matches_plain_gt_render_byte_identical():
    grouped = table(groups="area")
    random.seed(0)
    with_flag = grouped.as_raw_html()
    random.seed(0)
    plain = grouped.gt().as_raw_html()
    assert with_flag == plain


def test_collapsible_transform_applied_exactly_once():
    html = table(groups="area", collapsible_groups=True).as_raw_html()
    assert html.count('<tr data-ct-group="1"') == 1


def test_with_theme_round_trips_collapsible_groups_flag():
    # Guards `_with`'s settings dict: a missing key here would silently
    # drop collapsible_groups on the next chain call.
    html = table(groups="area", collapsible_groups=True).with_theme(MONO).as_raw_html()
    assert "data-ct-group" in html


def test_repr_html_applies_transform_in_make_page_shape(monkeypatch: pytest.MonkeyPatch):
    # Positron infers make_page=True, wrapping the fragment in a full
    # <html><body> page rather than a bare <div>. The transform must still
    # find the wrapper div and scope its selectors to that div's uid.
    monkeypatch.setenv("POSITRON_VERSION", "1.0")
    html = table(groups="area", collapsible_groups=True)._repr_html_()
    match = re.search(r'<div\s+id="([^"]+)"', html)
    assert match is not None
    uid = match.group(1)
    assert f"#{uid} .ct-group-state" in html
    assert "data-ct-group" in html


def test_card_column_gets_exact_cell_presentation_only_on_card_cells():
    from coeftable.cards import Card

    frame = pl.DataFrame(
        {
            "metric": ["A", "A"],
            "method": ["OLS", "DiD"],
            "value": [1.0, 2.0],
            "low": [0.5, 1.5],
            "high": [1.5, 2.5],
        }
    )
    html = (
        CoefTable(frame, rows="metric", split_columns="method")
        .estimate("Estimate", "value", ci=("low", "high"))
        .card("Summary", cards=[Card("OLS"), Card("DiD")])
        .gt()
        .as_raw_html()
    )
    cells = re.findall(r"<td(?P<attrs>[^>]*)>(?P<body>.*?)</td>", html, flags=re.DOTALL)
    card_attrs = [attrs for attrs, body in cells if "<details open" in body]
    ordinary_attrs = [attrs for attrs, body in cells if "<details open" not in body]
    assert len(card_attrs) == 2
    assert ordinary_attrs

    def properties(attrs: str) -> dict[str, str]:
        style = re.search(r'style="(?P<value>[^"]*)"', attrs)
        if style is None:
            return {}
        return {
            name.strip(): value.strip()
            for declaration in style.group("value").split(";")
            if ":" in declaration
            for name, value in [declaration.split(":", 1)]
        }

    expected = {
        "padding": "8px",
        "vertical-align": "top",
        "overflow": "visible",
    }
    for attrs in card_attrs:
        actual = properties(attrs)
        assert {name: actual.get(name) for name in expected} == expected
    for attrs in ordinary_attrs:
        actual = properties(attrs)
        assert actual.get("padding") != "8px"
        assert actual.get("vertical-align") != "top"
        assert actual.get("overflow") != "visible"


def test_embedded_card_preserves_its_theme_across_table_entry_points():
    from coeftable.cards import Card, TextBlock
    from coeftable.theme import Theme

    card_theme = Theme(text="#123456", surface="#fefefe")
    card = Card("Card-owned", content=(TextBlock("theme-marker"),), theme=card_theme)
    embedded = table().with_theme(MONO).card("Summary", cards=[card, None, None, None])

    for html in (embedded.gt().as_raw_html(), embedded.as_raw_html(), embedded._repr_html_()):
        assert "Card-owned" in html
        assert "#123456" in html
        assert "<details open" in html


def test_each_public_render_starts_a_fresh_factory_resolution():
    from collections.abc import Mapping
    from typing import Any

    from coeftable.cards import Card

    calls: list[Mapping[str, Any]] = []

    def factory(row: Mapping[str, Any]) -> Card:
        calls.append(row)
        return Card(str(row["metric"]))

    embedded = CoefTable(
        pl.DataFrame({"metric": ["A", "B"]}),
        rows="metric",
    ).card("Summary", factory=factory)

    embedded.gt()
    assert len(calls) == 2
    embedded.as_raw_html()
    assert len(calls) == 4
    embedded._repr_html_()
    assert len(calls) == 6


def test_collapsible_groups_compose_with_nested_card_details():
    from coeftable.cards import Card, Diagnostics

    cards = [Card(str(i), content=(Diagnostics("details", (("n", i),)),)) for i in range(4)]
    html = (
        table(groups="area", collapsible_groups=True)
        .card(
            "Summary",
            cards=cards,
        )
        .as_raw_html()
    )
    assert 'data-ct-group="1"' in html
    assert html.count("<details open") == 4
    assert html.count('<details style="position:relative">') == 4
    assert "CardColumn" not in html
