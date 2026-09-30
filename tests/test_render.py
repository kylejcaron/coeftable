import random
import re
from html.parser import HTMLParser

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


def table_data_with(metric: str, variant: str):
    return pl.DataFrame(
        {
            **RAW,
            "metric": [metric, "Revenue", "Latency", "Latency"],
            "variant": [variant, "C", "B", "C"],
        }
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


def test_hostile_row_and_nest_labels_render_with_no_raw_tag_in_html():
    payload = "seg<img src=x onerror=alert(1)>"
    hostile = table_data_with(metric=f"m{payload}", variant=payload)
    html = (
        CoefTable(hostile, rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .gt()
        .as_raw_html()
    )
    assert "<img src=x onerror=alert(1)>" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html


def test_hostile_row_and_nest_labels_render_literally_in_latex():
    import warnings

    payload = "seg<img src=x onerror=alert(1)>"
    hostile = table_data_with(metric=f"m{payload}", variant=payload)
    gt = (
        CoefTable(hostile, rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .gt()
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        latex = gt.as_latex()
    assert "img src=x onerror=alert(1)" in latex
    assert "<img" not in latex


def test_markdown_bold_syntax_in_a_row_label_still_bolds():
    hostile = table_data_with(metric="**Revenue**", variant="B")
    html = (
        CoefTable(hostile, rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .gt()
        .as_raw_html()
    )
    assert "<strong>Revenue</strong>" in html or "<b>Revenue</b>" in html


class _Tags(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.starts: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag, attrs):
        self.starts.append((tag, dict(attrs)))


def _tags(markup: str) -> list[tuple[str, dict[str, str | None]]]:
    parser = _Tags()
    parser.feed(markup)
    return parser.starts


def _executable_urls(markup: str) -> list[str]:
    # What a browser would navigate to: entity-decoded by the parser, then
    # scheme-normalised by stripping ASCII whitespace/control characters.
    urls = []
    for _tag, attrs in _tags(markup):
        for name in ("href", "src", "xlink:href", "action", "formaction"):
            value = attrs.get(name)
            if value:
                normalised = "".join(ch for ch in value if ch > " ").lower()
                if normalised.startswith(("javascript:", "vbscript:", "data:")):
                    urls.append(value)
    return urls


DANGEROUS_LINKS = [
    "[x](javascript:alert(1))",
    "[x](JaVaScRiPt:alert(1))",
    "[x](&#106;avascript:alert(1))",
    "[x](&#x6A;avascript:alert(1))",
    "[x]( javascript:alert(1))",
    "[x](vbscript:msgbox(1))",
    "[x](data:text/html;base64,PHNjcmlwdD4=)",
    "![x](javascript:alert(1))",
    "<javascript:alert(1)>",
    "[x][r]\n\n[r]: javascript:alert(1)",
    "**[x](javascript:alert(1))**",
    "_[**x**](javascript:alert(1))_",
]


@pytest.mark.parametrize("label", DANGEROUS_LINKS)
def test_row_and_nest_labels_never_render_executable_link_targets(label):
    hostile = table_data_with(metric=label, variant=label)
    html = (
        CoefTable(hostile, rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .as_raw_html()
    )
    assert _executable_urls(html) == []


@pytest.mark.parametrize("label", DANGEROUS_LINKS)
def test_dangerous_links_in_labels_stay_inert_with_collapsible_groups(label):
    hostile = pl.DataFrame({**RAW, "metric": [label, label, "Latency", "Latency"]})
    html = (
        CoefTable(hostile, rows="metric", nest="variant", groups="area", collapsible_groups=True)
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .as_raw_html()
    )
    assert _executable_urls(html) == []


def _group_split_table(label: str) -> CoefTable:
    data = pl.DataFrame(
        {
            "area": [label, label],
            "metric": ["Revenue", "Revenue"],
            "arm": [label, "ok"],
            "rel": [1.0, 2.0],
            "rel_lb": [0.5, 1.0],
            "rel_ub": [1.5, 3.0],
        }
    )
    return CoefTable(data, rows="metric", groups="area", split_columns="arm").estimate(
        "Lift %", "rel", ci=("rel_lb", "rel_ub")
    )


@pytest.mark.parametrize("label", DANGEROUS_LINKS)
def test_group_and_split_labels_never_render_executable_link_targets(label):
    assert _executable_urls(_group_split_table(label).as_raw_html()) == []


def test_group_and_split_labels_render_raw_tags_as_text():
    payload = "<img src=x onerror=alert(1)>"
    html = _group_split_table(payload).as_raw_html()
    assert "img" not in {tag for tag, _ in _tags(html)}
    assert html.count("&lt;img src=x onerror=alert(1)&gt;") >= 2


def test_group_labels_escape_entities_once():
    data = pl.DataFrame(
        {
            "area": ["R&D", "R&D", "Ops"],
            "metric": ["A", "B", "A"],
            "rel": [1.0, 2.0, 3.0],
            "rel_lb": [0.5, 1.0, 2.0],
            "rel_ub": [1.5, 3.0, 4.0],
        }
    )
    html = (
        CoefTable(data, rows="metric", groups="area")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .as_raw_html()
    )
    assert "R&amp;D" in html
    assert "R&amp;amp;D" not in html


def test_group_labels_render_original_text_in_latex_and_escaped_in_html():
    import warnings

    label = "R&D <alpha>"
    data = pl.DataFrame(
        {
            "area": [label, label],
            "metric": ["A", "B"],
            "rel": [1.0, 2.0],
            "rel_lb": [0.5, 1.0],
            "rel_ub": [1.5, 3.0],
        }
    )
    gt = (
        CoefTable(data, rows="metric", groups="area")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .gt()
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        latex = gt.as_latex()
    assert "R\\&D <alpha>" in latex
    assert "&amp;" not in latex
    assert "R&amp;D &lt;alpha&gt;" in gt.as_raw_html()
    assert "<alpha>" not in gt.as_raw_html()


def test_group_labels_remain_literal_latex_with_special_characters():
    import warnings

    label = "50% budget_$#{}"
    data = pl.DataFrame({"group": [label], "metric": ["A"], "value": [1.0]})
    gt = CoefTable(data, rows="metric", groups="group").estimate("Value", "value").gt()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        latex = gt.as_latex()
    assert r"50\% budget\_\$\#\{\}" in latex
    assert label in gt.as_raw_html()


def test_plain_row_labels_are_bold_and_repeated_keys_stay_blank():
    html = table().as_raw_html()
    assert html.count("<b>Revenue</b>") == 1
    assert html.count("<b>Latency</b>") == 1


def test_ampersand_in_row_and_nest_labels_is_escaped_exactly_once():
    html = (
        CoefTable(table_data_with("A&B", "C&D"), rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .as_raw_html()
    )
    assert "<b>A&amp;B</b>" in html
    assert "C&amp;D" in html
    assert "&amp;amp;" not in html


def test_user_supplied_bold_tags_in_labels_do_not_become_markup():
    html = (
        CoefTable(table_data_with("<b>x</b>", "<b>y</b>"), rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .as_raw_html()
    )
    assert "&lt;b&gt;x&lt;/b&gt;" in html
    assert "&lt;b&gt;y&lt;/b&gt;" in html


def test_units_notation_in_row_and_nest_labels_still_formats():
    html = (
        CoefTable(
            table_data_with("Speed {{m s^-1}}", "{{m^2}} area"), rows="metric", nest="variant"
        )
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .as_raw_html()
    )
    assert "{{" not in html
    assert html.count("<sup") >= 2


@pytest.mark.parametrize(
    "label",
    [
        "[x](javascript:alert({{m}}))",
        '[x](https://e.com/{{m s^-1}}"onmouseover="alert(1))',
        "{{<img src=x onerror=alert(1)>}}",
        '{{"><script>alert(1)</script>}}',
        "<b>{{m}}</b>",
        "`{{[x](javascript:alert(1))}}`",
        "{{[x](javascript:alert(1))}}",
        "{{m^[x](javascript:alert(1))}}",
        "{{m_[x](javascript:alert(1))}}",
        "{{m_[_[x](javascript:alert(1))^[y](javascript:alert(2))]}}",
        "{{[x](JaVaScRiPt:alert(1)) [y](vbscript:x)}}",
        "`{{m}}` **{{[x](javascript:alert(1))}}**",
    ],
)
def test_units_notation_cannot_reopen_links_or_raw_html(label):
    html = (
        CoefTable(table_data_with(label, label), rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .as_raw_html()
    )
    starts = _tags(html)
    assert _executable_urls(html) == []
    assert not {tag for tag, _ in starts} & {"script", "img"}
    assert not {name for _, attrs in starts for name in attrs if name.startswith("on")}


@pytest.mark.parametrize(
    "notation",
    [
        "m s^-1",
        "m^2",
        "m_2",
        "m_2^3",
        "m_[0^3]",
        "%C6H12O6%",
        "J/mol",
        "/s",
        "kg m^-2",
        "x10^6",
        "um",
        "ohm",
        "degC",
        ":pm:5",
        "mol_solvent^-1",
        "m_[abc^def]",
        "(m s^-1)",
        "W m^-2 K^-1",
    ],
)
def test_ordinary_units_notation_matches_great_tables_rendering(notation):
    from great_tables._helpers import define_units

    html = (
        CoefTable(table_data_with(f"A {{{{{notation}}}}} B", "B"), rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .as_raw_html()
    )
    assert f"A {define_units(notation).to_html()} B" in html


def test_safe_markdown_inside_unit_leaves_is_kept_and_dangerous_links_dropped():
    label = "{{**kg** [docs](https://example.com) [x](javascript:alert(1)) s^-1}}"
    html = (
        CoefTable(table_data_with(label, "B"), rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .as_raw_html()
    )
    tags = {tag for tag, _ in _tags(html)}
    assert {"strong", "sup"} <= tags
    assert [a["href"] for t, a in _tags(html) if t == "a"].count("https://example.com") == 1
    assert _executable_urls(html) == []


def test_percent_and_entity_encoded_token_lookalikes_in_urls_stay_literal():
    label = "[a](https://e.com/%71%710z) [b](https://e.com/&#113;&#113;0z) {{m}} qq0z"
    html = (
        CoefTable(table_data_with(label, "B"), rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .as_raw_html()
    )
    hrefs = [a["href"] for t, a in _tags(html) if t == "a"]
    assert hrefs == ["https://e.com/%71%710z", "https://e.com/&#113;&#113;0z"]
    assert "qq0z" in html


def test_overlapping_marker_lookalikes_in_text_remain_literal():
    literal = "q0q0z q1q0z q0q1q1z Q2Q0z"
    html = (
        CoefTable(table_data_with(literal + " {{m}}", "B"), rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .as_raw_html()
    )
    assert literal in html


def test_units_parking_has_bounded_expansion_for_long_literal_runs():
    from coeftable.labels import _park_units

    label = "q" * 2000 + " {{m}}" * 2000
    parked, _, _ = _park_units(label)
    assert len(parked) <= 4 * len(label)


def test_units_inside_inline_code_stay_literal_text():
    html = (
        CoefTable(table_data_with("`{{m s^-1}}`", "B"), rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .as_raw_html()
    )
    assert "<code>{{m s^-1}}</code>" in html


@pytest.mark.parametrize("suffix", ["", " {{m}}", " `{{m s^-1}}` {{m^2}}"])
@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/%EE%80%800%EE%80%81",
        "https://example.com/%ee%80%800%ee%80%81",
        "https://example.com/qqq0z",
        "https://example.com/Q0zq1z",
        "https://example.com/q0q0z",
        "https://example.com/q0q1q0z",
        "https://example.com/Q0Q0z",
        "https://example.com/%710%710z",
        "https://example.com/&#113;0q0z",
    ],
)
def test_label_text_resembling_internal_tokens_is_left_alone(url, suffix):
    label = f"[literal]({url}){suffix}"
    html = (
        CoefTable(table_data_with(label, "B"), rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .as_raw_html()
    )
    hrefs = [attrs["href"] for tag, attrs in _tags(html) if tag == "a"]
    assert hrefs == [url]
    assert (">literal</a>" in html) is True


def test_units_inside_a_link_target_do_not_alter_the_link_or_break_the_attribute():
    label = '[l](https://e.com/{{m s^-1}}"x) {{m}}'
    html = (
        CoefTable(table_data_with(label, "B"), rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .as_raw_html()
    )
    assert not {name for tag, attrs in _tags(html) if tag == "a" for name in attrs} - {"href"}


def test_safe_links_and_markdown_in_labels_still_render():
    label = (
        "**Rev** _up_ `x` [docs](https://example.com/a?b=1&c=2) [rel](/path) [m](mailto:a@b.co)"
    )
    hostile = table_data_with(metric=label, variant=label)
    html = (
        CoefTable(hostile, rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .as_raw_html()
    )
    hrefs = [attrs["href"] for tag, attrs in _tags(html) if tag == "a"]
    assert "https://example.com/a?b=1&c=2" in hrefs
    assert "/path" in hrefs
    assert "mailto:a@b.co" in hrefs
    tags = {tag for tag, _ in _tags(html)}
    assert {"strong", "em", "code"} <= tags


@pytest.mark.parametrize(
    "raw",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "<a href=javascript:alert(1)>x</a>",
        "<svg onload=alert(1)>",
    ],
)
def test_raw_html_in_labels_is_shown_as_text_not_markup(raw):
    hostile = table_data_with(metric=raw, variant=raw)
    html = (
        CoefTable(hostile, rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .as_raw_html()
    )
    starts = _tags(html)
    assert not {tag for tag, _ in starts} & {"script", "img", "a"}
    assert not {name for _, attrs in starts for name in attrs} & {"onerror", "onload"}
    assert html.count(raw.replace("<", "&lt;").replace(">", "&gt;")) >= 2


def test_label_rendering_leaves_generated_svg_fragments_intact():
    hostile = table_data_with(metric="[x](javascript:alert(1))", variant="B")
    html = (
        CoefTable(hostile, rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .forest("Plot", of="Lift %")
        .as_raw_html()
    )
    tags = {tag for tag, _ in _tags(html)}
    assert {"svg", "rect"} <= tags
    assert _executable_urls(html) == []


def test_label_markup_roundtrips_as_text_in_latex():
    import warnings

    hostile = table_data_with(metric="**Rev**<b>x</b>", variant="A&B")
    gt = (
        CoefTable(hostile, rows="metric", nest="variant")
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
        .gt()
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        latex = gt.as_latex()
    assert "Rev" in latex
    assert "<b>" not in latex
    assert "A\\&B" in latex
