import polars as pl
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
