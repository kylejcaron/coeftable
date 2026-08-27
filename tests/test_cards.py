"""Contract tests for the card adornment vocabulary and fragment renderer."""

import ast
import dataclasses
import math
import re
from pathlib import Path
from typing import cast

import pytest

import coeftable.cards
from coeftable.cards.adornments import (
    Badge,
    Callout,
    CaptionRow,
    InlineSvg,
    KeyValuePopover,
    Legend,
    MetricValue,
    RuleStrip,
    SelectControl,
    TextBlock,
)
from coeftable.cards.chrome import DEFAULT_CHROME, CardChrome, line_height
from coeftable.cards.fragments import _esc, render_adornment
from coeftable.cards.measure import measure_card, resolve_rows, text_line_plan
from coeftable.cards.template import CardTemplate
from coeftable.errors import SpecError
from coeftable.theme import DEFAULT

SVG_OK = '<svg xmlns="http://www.w3.org/2000/svg" width="220" height="30"></svg>'


def _valid_instances():
    return [
        TextBlock("Revenue", variant="title"),
        TextBlock("Quarterly view", variant="subtitle"),
        TextBlock("Modeled on 412 accounts", variant="body"),
        TextBlock("Source: ledger v2", variant="caption"),
        MetricValue("+3.4%", detail="[1.2, 5.7]", role="favorable"),
        InlineSvg(SVG_OK, width=220, height=30),
        KeyValuePopover("diagnostics", (("n", "412"), ("sigma", "0.8"))),
        SelectControl(
            "Breakout",
            (("drivers", "By driver"), ("region", "By region")),
            selected="drivers",
            key="rev-breakout",
        ),
        Badge("accounting", role="neutral"),
        Callout("watch the confidence interval", role="unfavorable"),
        CaptionRow("v2.1 release", color="#4C72B0", dash="dotted"),
        Legend((("A", "#1F77B4"), ("B", "#FF7F0E"))),
        RuleStrip((("launch", "#4C72B0", "dotted"), ("incident", "#C44E52", "dashed"))),
    ]


def test_every_adornment_constructs_and_is_frozen():
    import dataclasses

    for adornment in _valid_instances():
        first_field = dataclasses.fields(adornment)[0].name
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(adornment, first_field, "nope")


def test_every_adornment_uses_slots_without_instance_dict():
    for adornment in _valid_instances():
        assert hasattr(type(adornment), "__slots__")
        assert not hasattr(adornment, "__dict__")


def test_adornments_are_hashable():
    assert len({*_valid_instances()}) == len(_valid_instances())


@pytest.mark.parametrize(
    "build",
    [
        lambda: TextBlock("x", variant="huge"),  # ty: ignore[invalid-argument-type]
        lambda: TextBlock(7),  # ty: ignore[invalid-argument-type]
        lambda: TextBlock("x", variant=7),  # ty: ignore[invalid-argument-type]
        lambda: MetricValue("+1", role="good"),  # ty: ignore[invalid-argument-type]
        lambda: MetricValue(3.4),  # ty: ignore[invalid-argument-type]
        lambda: MetricValue(""),
        lambda: MetricValue("+1", detail=7),  # ty: ignore[invalid-argument-type]
        lambda: MetricValue("+1", detail=""),
        lambda: MetricValue("+1", role=7),  # ty: ignore[invalid-argument-type]
        lambda: Badge("x", role="loud"),  # ty: ignore[invalid-argument-type]
        lambda: Badge(None),  # ty: ignore[invalid-argument-type]
        lambda: Badge("x", role=7),  # ty: ignore[invalid-argument-type]
        lambda: CaptionRow("x", dash="wavy"),  # ty: ignore[invalid-argument-type]
        lambda: CaptionRow("x", color=7),  # ty: ignore[invalid-argument-type]
        lambda: CaptionRow(7),  # ty: ignore[invalid-argument-type]
        lambda: CaptionRow("x", dash=7),  # ty: ignore[invalid-argument-type]
        lambda: TextBlock("x", max_lines=0),
        lambda: TextBlock("x", max_lines=True),  # bool-as-int
        lambda: TextBlock("x", max_lines=cast(int, 1.5)),  # float-as-int
    ],
    ids=[
        "bad-variant",
        "nonstr-text",
        "nonstr-variant",
        "bad-role",
        "nonstr-value",
        "empty-value",
        "nonstr-detail",
        "empty-detail",
        "nonstr-role",
        "badge-bad-role",
        "badge-nonstr",
        "badge-nonstr-role",
        "bad-dash",
        "nonstr-color",
        "nonstr-caption-text",
        "nonstr-dash",
        "zero-max-lines",
        "bool-max-lines",
        "float-max-lines",
    ],
)
def test_scalar_field_validation_raises_spec_error(build):
    with pytest.raises(SpecError):
        build()


@pytest.mark.parametrize(
    "build",
    [
        lambda: InlineSvg(7, width=220, height=30),  # ty: ignore[invalid-argument-type]
        lambda: InlineSvg("<div/>", width=10, height=10),
        lambda: InlineSvg("not xml <", width=10, height=10),
        lambda: InlineSvg(SVG_OK, width=100, height=30),  # width mismatch
        lambda: InlineSvg(SVG_OK, width=220, height=40),  # height mismatch
        lambda: InlineSvg(SVG_OK, width=0, height=30),
        lambda: InlineSvg(SVG_OK, width=220, height=0),
        lambda: InlineSvg(SVG_OK, width=True, height=30),  # bool-as-int
        lambda: InlineSvg(SVG_OK, width=220, height=True),  # bool-as-int
        lambda: InlineSvg(
            SVG_OK,
            width=cast(int, 220.0),
            height=30,
        ),  # float-as-int
        lambda: InlineSvg(
            SVG_OK,
            width=220,
            height=cast(int, 30.0),
        ),  # float-as-int
        lambda: InlineSvg(
            '<svg xmlns="http://www.w3.org/2000/svg" height="30"></svg>',
            width=220,
            height=30,
        ),  # missing width attr
        lambda: InlineSvg(
            '<svg xmlns="http://www.w3.org/2000/svg" width="220"></svg>',
            width=220,
            height=30,
        ),  # missing height attr
    ],
    ids=[
        "nonstr-svg",
        "non-svg-root",
        "malformed-xml",
        "width-mismatch",
        "height-mismatch",
        "zero-width",
        "zero-height",
        "bool-width",
        "bool-height",
        "float-width",
        "float-height",
        "missing-width-attr",
        "missing-height-attr",
    ],
)
def test_inline_svg_validation_raises_spec_error(build):
    with pytest.raises(SpecError):
        build()


def test_inline_svg_accepts_real_plot_output():
    from coeftable.plots import forest_bar
    from coeftable.theme import DEFAULT

    svg = forest_bar(
        1.2,
        0.4,
        2.0,
        domain=(-1.0, 3.0),
        ref=0.0,
        color=DEFAULT.favorable,
        theme=DEFAULT,
        width=220,
        height=18,
    )
    assert InlineSvg(svg, width=220, height=18).svg == svg


@pytest.mark.parametrize(
    "build",
    [
        lambda: KeyValuePopover("", (("k", "v"),)),
        lambda: KeyValuePopover(7, (("k", "v"),)),  # ty: ignore[invalid-argument-type]
        lambda: KeyValuePopover("d", ()),
        lambda: KeyValuePopover(
            "d",
            [("k", "v")],  # ty: ignore[invalid-argument-type]
        ),  # list, not tuple
        lambda: KeyValuePopover("d", (("k",),)),  # ty: ignore[invalid-argument-type]
        lambda: KeyValuePopover("d", (("k", 7),)),  # ty: ignore[invalid-argument-type]
        lambda: KeyValuePopover("d", ((7, "v"),)),  # ty: ignore[invalid-argument-type]
        lambda: KeyValuePopover(
            "d",
            (("k", "v"),),
            key=cast(str, 7),
        ),
        lambda: SelectControl("", (("a", "A"),), selected="a"),
        lambda: SelectControl(
            cast(str, 7),
            (("a", "A"),),
            selected="a",
        ),
        lambda: SelectControl("L", (), selected="a"),
        lambda: SelectControl("L", (("a", "A"), ("a", "B")), selected="a"),  # dup values
        lambda: SelectControl("L", (("a", "A"),), selected="b"),  # unknown value
        lambda: SelectControl("L", (("a", "A"),), selected=7),  # ty: ignore[invalid-argument-type]
        lambda: SelectControl("L", ((7, "A"),), selected="a"),  # ty: ignore[invalid-argument-type]
        lambda: SelectControl("L", (("a", 7),), selected="a"),  # ty: ignore[invalid-argument-type]
        lambda: SelectControl(
            "L",
            cast(tuple[tuple[str, str], ...], [("a", "A")]),
            selected="a",
        ),  # list
        lambda: SelectControl(
            "L",
            (("a", "A"),),
            selected="a",
            key="",
        ),
        lambda: SelectControl(
            "L",
            (("a", "A"),),
            selected="a",
            key=cast(str, 7),
        ),
        lambda: Legend(()),
        lambda: Legend((("A", "#111", "extra"),)),  # ty: ignore[invalid-argument-type]
        lambda: Legend(((7, "#111"),)),  # ty: ignore[invalid-argument-type]
        lambda: Legend((("A", 7),)),  # ty: ignore[invalid-argument-type]
        lambda: RuleStrip(()),
        lambda: RuleStrip((("x", "#111", "wavy"),)),  # ty: ignore[invalid-argument-type]  # bad dash
        lambda: RuleStrip((("x", "#111", 7),)),  # ty: ignore[invalid-argument-type]
        lambda: RuleStrip((("x", "#111"),)),  # ty: ignore[invalid-argument-type]
        lambda: RuleStrip(((7, "#111", "solid"),)),  # ty: ignore[invalid-argument-type]
        lambda: RuleStrip((("x", 7, "solid"),)),  # ty: ignore[invalid-argument-type]
    ],
    ids=[
        "popover-empty-label",
        "popover-nonstr-label",
        "popover-empty-items",
        "popover-list",
        "popover-arity",
        "popover-nonstr-value",
        "popover-nonstr-key",
        "popover-nonstr-field-key",
        "select-empty-label",
        "select-nonstr-label",
        "select-no-options",
        "select-dup-values",
        "select-unknown-selected",
        "select-nonstr-selected",
        "select-nonstr-option-value",
        "select-nonstr-option-label",
        "select-list",
        "select-empty-key",
        "select-nonstr-key",
        "legend-empty",
        "legend-arity",
        "legend-nonstr-label",
        "legend-nonstr-color",
        "rulestrip-empty",
        "rulestrip-bad-dash",
        "rulestrip-nonstr-dash",
        "rulestrip-arity",
        "rulestrip-nonstr-label",
        "rulestrip-nonstr-color",
    ],
)
def test_container_field_validation_raises_spec_error(build):
    with pytest.raises(SpecError):
        build()


HOSTILE = '<script>&"boom"</script>'
ESCAPED = "&lt;script&gt;&amp;&quot;boom&quot;&lt;/script&gt;"


def test_every_adornment_renders_nonempty_html():
    for adornment in _valid_instances():
        html_out = render_adornment(adornment, theme=DEFAULT)
        assert html_out
        assert html_out == render_adornment(adornment, theme=DEFAULT)  # determinism


def test_renderer_emits_no_dom_ids_outside_inline_svg():
    for adornment in _valid_instances():
        if isinstance(adornment, InlineSvg):
            continue
        assert not re.search(r"\bid=", render_adornment(adornment, theme=DEFAULT))


def test_inline_svg_gains_nothing_beyond_its_payload():
    svg = SVG_OK
    assert render_adornment(InlineSvg(svg, width=220, height=30), theme=DEFAULT) == svg


@pytest.mark.parametrize(
    "build",
    [
        lambda: TextBlock(HOSTILE),
        lambda: MetricValue(HOSTILE),
        lambda: MetricValue("+1", detail=HOSTILE),
        lambda: KeyValuePopover(HOSTILE, (("k", "v"),)),
        lambda: KeyValuePopover("d", ((HOSTILE, "v"),)),
        lambda: KeyValuePopover("d", (("k", HOSTILE),)),
        lambda: SelectControl(HOSTILE, (("a", "A"),), selected="a"),
        lambda: SelectControl("L", ((HOSTILE, "A"),), selected=HOSTILE),
        lambda: SelectControl("L", (("a", HOSTILE),), selected="a"),
        lambda: Badge(HOSTILE),
        lambda: Callout(HOSTILE),
        lambda: CaptionRow(HOSTILE),
        lambda: Legend(((HOSTILE, "#111"),)),
        lambda: RuleStrip(((HOSTILE, "#111", "solid"),)),
    ],
    ids=[
        "textblock",
        "metric-value",
        "metric-detail",
        "popover-label",
        "popover-key",
        "popover-value",
        "select-label",
        "select-value",
        "select-option-label",
        "badge",
        "callout",
        "caption",
        "legend-label",
        "rulestrip-label",
    ],
)
def test_every_text_position_is_escaped(build):
    html_out = render_adornment(build(), theme=DEFAULT)
    assert HOSTILE not in html_out
    assert ESCAPED in html_out


@pytest.mark.parametrize(
    "build",
    [
        lambda: CaptionRow("v2.1", color=THEME_HOSTILE),
        lambda: Legend((("A", THEME_HOSTILE),)),
        lambda: RuleStrip((("launch", THEME_HOSTILE, "dotted"),)),
    ],
    ids=["caption-color", "legend-color", "rulestrip-color"],
)
def test_every_color_position_is_attribute_escaped(build):
    html_out = render_adornment(build(), theme=DEFAULT)
    assert THEME_HOSTILE not in html_out
    assert not re.search(r"\bid=", html_out)
    assert THEME_HOSTILE_ESCAPED in html_out


def test_metric_value_uses_role_color():
    html_out = render_adornment(MetricValue("+3.4%", role="favorable"), theme=DEFAULT)
    assert DEFAULT.favorable in html_out


def test_metric_value_and_badge_clip_single_line_content():
    metric_html = render_adornment(MetricValue("+3.4%", detail="[1.2, 5.7]"), theme=DEFAULT)
    badge_html = render_adornment(Badge("x" * 1000), theme=DEFAULT)

    assert "overflow:hidden;text-overflow:ellipsis" in metric_html
    assert "white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%" in badge_html
    assert "box-sizing:border-box" in badge_html


def test_metric_detail_and_badge_stay_inside_measured_line_boxes():
    metric_html = render_adornment(MetricValue("+3.4%", detail="[1.2, 5.7]"), theme=DEFAULT)
    badge_html = render_adornment(Badge("accounting"), theme=DEFAULT)

    row_height = line_height(
        max(DEFAULT_CHROME.value_size, DEFAULT_CHROME.ci_size), DEFAULT_CHROME
    )
    assert (
        f'<div style="font-size:{DEFAULT_CHROME.value_size}px;'
        f"line-height:{row_height}px;" in metric_html
    )
    assert "vertical-align:top" in metric_html
    assert "display:block" in badge_html
    assert "width:fit-content" in badge_html
    assert "display:inline-block" not in badge_html


def test_select_marks_exactly_the_selected_option():
    control = SelectControl("Breakout", (("a", "Alpha"), ("b", "Beta")), selected="b")
    html_out = render_adornment(control, theme=DEFAULT)
    assert html_out.count(" selected>") == 1
    assert re.search(r'value="b"[^>]*selected>', html_out)


def test_select_has_a_programmatic_name():
    control = SelectControl("Breakout", (("a", "Alpha"),), selected="a")
    html_out = render_adornment(control, theme=DEFAULT)
    assert html_out.startswith("<label")
    assert html_out.endswith("</label>")
    assert "Breakout" in html_out
    assert "<select" in html_out
    assert html_out.index("<select") < html_out.index("</label>")
    assert html_out.rstrip().endswith("</select></label>")


def test_select_row_height_is_fixed_from_chrome():
    control = SelectControl("Breakout", (("a", "Alpha"),), selected="a")
    html_out = render_adornment(control, theme=DEFAULT)
    expected = (
        line_height(DEFAULT_CHROME.control_size, DEFAULT_CHROME) + DEFAULT_CHROME.select_padding
    )
    select_start = html_out.index("<select")
    select_tag = html_out[select_start : html_out.index(">", select_start) + 1]
    select_line_height = line_height(DEFAULT_CHROME.control_size, DEFAULT_CHROME)
    assert f"height:{expected}px" in html_out
    assert f"height:{select_line_height}px" in select_tag
    assert f"line-height:{select_line_height}px" in select_tag
    assert "box-sizing:border-box" in select_tag
    assert "width:60%" in select_tag
    assert "flex:none" in select_tag


def test_select_height_tracks_custom_control_size():
    chrome = dataclasses.replace(DEFAULT_CHROME, control_size=17)
    control = SelectControl("Breakout", (("a", "Alpha"),), selected="a")
    html_out = render_adornment(control, theme=DEFAULT, chrome=chrome)
    select_start = html_out.index("<select")
    select_tag = html_out[select_start : html_out.index(">", select_start) + 1]
    expected = line_height(chrome.control_size, chrome)
    assert f"height:{expected}px" in select_tag
    assert f"line-height:{expected}px" in select_tag


def test_select_row_height_tracks_select_padding():
    chrome = dataclasses.replace(DEFAULT_CHROME, select_padding=DEFAULT_CHROME.select_padding + 9)
    control = SelectControl("Breakout", (("a", "Alpha"),), selected="a")
    html_out = render_adornment(control, theme=DEFAULT, chrome=chrome)
    expected = line_height(chrome.control_size, chrome) + chrome.select_padding
    assert f"height:{expected}px" in html_out


def test_popover_is_a_native_details_element():
    popover = KeyValuePopover("diagnostics", (("n", "412"),))
    html_out = render_adornment(popover, theme=DEFAULT)
    assert html_out.startswith("<details")
    assert "<summary" in html_out
    summary_tag = html_out.split("</summary>", 1)[0]
    assert "display:block" in summary_tag
    assert "list-style:none" in summary_tag
    assert "text-decoration:underline" in summary_tag


def test_popover_panel_is_a_non_reflowing_overlay():
    popover = KeyValuePopover("diagnostics", (("n", "412"),))
    html_out = render_adornment(popover, theme=DEFAULT)
    details_open_tag = html_out[: html_out.index(">") + 1]
    assert "position:relative" in details_open_tag
    panel = html_out[html_out.index("</summary>") :]
    assert "position:absolute" in panel


def test_popover_item_rows_declare_line_height():
    popover = KeyValuePopover("diagnostics", (("n", "412"),))
    html_out = render_adornment(popover, theme=DEFAULT)
    panel = html_out[html_out.index("</summary>") :]

    assert re.search(r'<div style="font-size:\d+px;line-height:\d+px">', panel)


def test_renderer_does_not_emit_semantic_keys():
    controls = (
        SelectControl(
            "Breakout",
            (("a", "Alpha"),),
            selected="a",
            key="KEYSENTINEL1",
        ),
        KeyValuePopover("diagnostics", (("n", "412"),), key="KEYSENTINEL2"),
    )
    for control in controls:
        assert "KEYSENTINEL1" not in render_adornment(control, theme=DEFAULT)
        assert "KEYSENTINEL2" not in render_adornment(control, theme=DEFAULT)


@pytest.mark.parametrize(
    "field, build",
    [
        ("text", lambda: TextBlock("content")),
        ("muted", lambda: TextBlock("content", variant="subtitle")),
        ("surface", lambda: Badge("content")),
        ("rule", lambda: KeyValuePopover("details", (("k", "v"),))),
        ("favorable", lambda: MetricValue("value", role="favorable")),
        ("favorable", lambda: Badge("value", role="favorable")),
        ("unfavorable", lambda: MetricValue("value", role="unfavorable")),
        ("unfavorable", lambda: Badge("value", role="unfavorable")),
        ("inconclusive", lambda: MetricValue("value", role="inconclusive")),
        ("inconclusive", lambda: Badge("value", role="inconclusive")),
        ("neutral", lambda: MetricValue("value")),
        ("neutral", lambda: Badge("value")),
    ],
    ids=[
        "text",
        "muted",
        "surface",
        "rule",
        "favorable-metric",
        "favorable-badge",
        "unfavorable-metric",
        "unfavorable-badge",
        "inconclusive-metric",
        "inconclusive-badge",
        "neutral-metric",
        "neutral-badge",
    ],
)
def test_every_rendered_theme_value_is_escaped(field, build):
    import dataclasses

    hostile = dataclasses.replace(DEFAULT, **{field: HOSTILE})
    html_out = render_adornment(build(), theme=hostile)
    assert HOSTILE not in html_out
    assert ESCAPED in html_out


THEME_HOSTILE = 'red";id="THEMESENTINEL'
THEME_HOSTILE_ESCAPED = "red&quot;;id&#61;&quot;THEMESENTINEL"


def test_theme_values_are_attribute_escaped():
    import dataclasses

    hostile = dataclasses.replace(
        DEFAULT,
        text=THEME_HOSTILE,
        muted=THEME_HOSTILE,
        surface=THEME_HOSTILE,
        rule=THEME_HOSTILE,
        value_size=THEME_HOSTILE,
        ci_size=THEME_HOSTILE,
        favorable=THEME_HOSTILE,
        unfavorable=THEME_HOSTILE,
        inconclusive=THEME_HOSTILE,
        neutral=THEME_HOSTILE,
    )
    for adornment in _valid_instances():
        if isinstance(adornment, InlineSvg):
            continue
        html_out = render_adornment(adornment, theme=hostile)
        assert THEME_HOSTILE not in html_out
        assert not re.search(r"\bid=", html_out)
        assert THEME_HOSTILE_ESCAPED in html_out


def test_non_svg_fragments_use_inline_styles_only():
    for adornment in _valid_instances():
        if isinstance(adornment, InlineSvg):
            continue
        html_out = render_adornment(adornment, theme=DEFAULT)
        assert "class=" not in html_out
        assert "<style" not in html_out


EXPECTED_CARD_EXPORTS = {
    "Adornment",
    "Badge",
    "Callout",
    "CaptionRow",
    "InlineSvg",
    "KeyValuePopover",
    "Legend",
    "MetricValue",
    "RuleStrip",
    "SelectControl",
    "TextBlock",
    "render_adornment",
    "Anchor",
    "Card",
    "CardGrid",
    "CardChrome",
    "CardTemplate",
    "DEFAULT_CHROME",
    "Diagnostics",
    "Event",
    "Events",
    "Interval",
    "Metric",
    "Region",
    "resolve_content",
    "Trend",
    "MeasuredCard",
    "MeasuredPanel",
    "Pane",
    "Panel",
    "Row",
}

ALLOWED_CARDS_IMPORT_ROOTS = {
    "cards",
    "theme",
    "format",
    "svg",
    "annotations",
    "errors",
}


def test_cards_export_surface_is_exactly_the_promised_set():
    assert len(coeftable.cards.__all__) == 31

    assert set(coeftable.cards.__all__) == EXPECTED_CARD_EXPORTS
    for name in EXPECTED_CARD_EXPORTS:
        assert hasattr(coeftable.cards, name)


def test_cards_is_not_exported_from_the_top_level():
    import coeftable

    assert "cards" not in coeftable.__all__


def test_every_cards_module_imports_only_foundation_modules():
    package_dir = Path(coeftable.cards.__file__).parent
    src_root = package_dir.parent.parent
    modules = sorted(package_dir.rglob("*.py"))
    assert modules, "cards package has no modules to check"
    for module in modules:
        tree = ast.parse(module.read_text())
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    parts = alias.name.split(".")
                    if parts[0] == "coeftable":
                        imported_roots.add(parts[1] if len(parts) > 1 else "")
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0:
                    paths = [node.module.split(".")] if node.module else []
                else:
                    package = list(module.parent.relative_to(src_root).parts)
                    base = package[: len(package) - (node.level - 1)]
                    if node.module:
                        paths = [base + node.module.split(".")]
                    else:
                        paths = [[*base, alias.name] for alias in node.names]
                for parts in paths:
                    if parts[0] != "coeftable":
                        continue
                    if len(parts) > 1:
                        imported_roots.add(parts[1])
                    else:
                        imported_roots.update(alias.name for alias in node.names)
        leaked = imported_roots - ALLOWED_CARDS_IMPORT_ROOTS
        assert not leaked, f"{module.name} imports disallowed roots: {sorted(leaked)}"


def test_default_chrome_line_heights_round_up():
    assert line_height(14, DEFAULT_CHROME) == 19  # ceil(14 * 1.3) = ceil(18.2)
    assert line_height(15, DEFAULT_CHROME) == 20  # ceil(19.5)
    assert line_height(11, DEFAULT_CHROME) == 15  # ceil(14.3)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"padding": 0},
        {"padding": True},
        {"border_width": -1},
        {"title_size": 14.0},
        {"title_size": 1.5},
        {"border_width": 1.5},
        {"leading": 0.0},
        {"leading": 0.5},
        {"leading": 3.5},
        {"char_width_ratio": 0.0},
        {"swatch_thickness": 30},
        {"legend_swatch": 30},
        {"data_char_width_ratio": float("nan")},
    ],
    ids=[
        "zero-padding",
        "bool-padding",
        "negative-border",
        "float-size",
        "fractional-size",
        "fractional-border",
        "zero-leading",
        "subunit-leading",
        "huge-leading",
        "zero-ratio",
        "oversized-swatch",
        "oversized-legend-swatch",
        "nan-data-ratio",
    ],
)
def test_chrome_validation_raises_spec_error(kwargs):
    with pytest.raises(SpecError):
        CardChrome(**kwargs)


def test_default_chrome_passes_validation():
    assert CardChrome().legend_swatch <= CardChrome().caption_size


def test_every_text_row_declares_an_integer_line_height():
    for adornment in _valid_instances():
        if isinstance(adornment, InlineSvg):
            continue
        html_out = render_adornment(adornment, theme=DEFAULT)
        assert re.search(r"line-height:\d+px", html_out), type(adornment).__name__


def test_fragment_geometry_comes_from_chrome():
    big = CardChrome(
        title_size=28, caption_size=22, chip_size=20, swatch_width=30, legend_swatch=16
    )
    cases = [
        (TextBlock("t", variant="title"), f"font-size:{big.title_size}px"),
        (CaptionRow("c", color="#111"), f"width:{big.swatch_width}px"),
        (Legend((("A", "#111"),)), f"width:{big.legend_swatch}px"),
        (Badge("b"), f"font-size:{big.chip_size}px"),
    ]
    for adornment, expected in cases:
        html_out = render_adornment(adornment, theme=DEFAULT, chrome=big)
        assert expected in html_out, (type(adornment).__name__, expected)


def test_default_chrome_render_matches_default_call():
    for adornment in _valid_instances():
        assert render_adornment(adornment, theme=DEFAULT) == render_adornment(
            adornment, theme=DEFAULT, chrome=DEFAULT_CHROME
        )


def test_line_plan_wraps_greedily_at_the_budget():
    assert text_line_plan("alpha beta gamma", budget=11, max_lines=5) == (
        "alpha beta",
        "gamma",
    )


def test_line_plan_hard_splits_an_overlong_token():
    assert text_line_plan("abcdefghij", budget=4, max_lines=5) == (
        "abcd",
        "efgh",
        "ij",
    )


@pytest.mark.parametrize(
    ("text", "budget", "max_lines", "expected"),
    [
        ("ab cdefgh", 4, 1, ("ab cdefgh",)),
        ("abcdefghij", 4, 2, ("abcd", "efghij")),
        ("one two three", 7, 1, ("one two three",)),
        ("xy abcdefgh z", 4, 1, ("xy abcdefgh z",)),
        ("abcdef x", 4, 1, ("abcdef x",)),
    ],
)
def test_line_plan_tracks_line_start_continuation_flags(text, budget, max_lines, expected):
    assert text_line_plan(text, budget=budget, max_lines=max_lines) == expected


def test_line_plan_normalizes_whitespace():
    assert text_line_plan("  a\tb\n\nc  ", budget=20, max_lines=3) == ("a b c",)


def test_line_plan_empty_text_is_one_blank_line():
    assert text_line_plan("", budget=10, max_lines=3) == ("",)


def test_line_plan_cap_keeps_full_remainder_on_last_line():
    plan = text_line_plan("one two three four five", budget=9, max_lines=2)
    assert len(plan) == 2
    assert plan[0] == "one two"
    assert plan[1] == "three four five"


def test_line_plan_cap_joins_remainder_with_single_spaces():
    plan = text_line_plan("ab cd ef", budget=4, max_lines=1)
    assert plan == ("ab cd ef",)


def test_line_plan_cap_keeps_hard_split_tokens_intact():
    assert text_line_plan("abcdefghij", budget=4, max_lines=2) == ("abcd", "efghij")


def test_wrapping_textblock_height_is_lines_times_line_height():
    block = TextBlock("alpha beta gamma delta", variant="body", max_lines=3)
    caption = CaptionRow("caption")
    measured, _, rows, _ = measure_card(
        width=114,
        header=(),
        body=(block, caption),
        chrome=DEFAULT_CHROME,
    )
    lh = line_height(DEFAULT_CHROME.body_size, DEFAULT_CHROME)
    caption_h = line_height(DEFAULT_CHROME.caption_size, DEFAULT_CHROME)
    assert len(rows) == 3
    assert sum(r.height for r in rows[:2]) == 2 * lh
    assert [r.gap_above for r in rows] == [0, 0, DEFAULT_CHROME.gap]
    body_stack = 2 * lh + DEFAULT_CHROME.gap + caption_h
    expected_expanded = (
        2 * (DEFAULT_CHROME.border_width + DEFAULT_CHROME.padding)
        + DEFAULT_CHROME.header_gap
        + body_stack
    )
    assert measured.expanded_height == expected_expanded
    assert all(isinstance(r.adornment, TextBlock) for r in rows[:2])


def test_metric_value_overflow_names_section_and_field():
    with pytest.raises(SpecError) as excinfo:
        resolve_rows(
            (MetricValue("+123,456,789.00% " * 4),),
            usable=60,
            chrome=DEFAULT_CHROME,
            section="body",
        )
    message = str(excinfo.value)
    assert "body[0]" in message
    assert "MetricValue.value" in message
    assert "wider card" in message


def test_metric_value_overflow_with_detail_blames_value():
    with pytest.raises(SpecError) as excinfo:
        resolve_rows(
            (MetricValue("+123,456,789.00% " * 4, detail="[1.2, 5.7]"),),
            usable=60,
            chrome=DEFAULT_CHROME,
            section="body",
        )
    message = str(excinfo.value)
    assert "body[0]" in message
    assert "MetricValue.value" in message
    assert "wider card" in message


def test_metric_detail_overflow_names_section_index_and_detail_field():
    with pytest.raises(SpecError) as excinfo:
        resolve_rows(
            (
                TextBlock("context", variant="caption"),
                MetricValue("+3.4%", detail="[1.2, 5.7]"),
            ),
            usable=60,
            chrome=DEFAULT_CHROME,
            section="body",
        )
    message = str(excinfo.value)
    assert "body[1]" in message
    assert "MetricValue.detail" in message
    assert "wider card" in message


def test_inline_svg_wider_than_usable_raises():
    with pytest.raises(SpecError):
        resolve_rows(
            (InlineSvg(SVG_OK, width=220, height=30),),
            usable=200,
            chrome=DEFAULT_CHROME,
            section="body",
        )


@pytest.mark.parametrize(
    ("adornment", "usable"),
    [
        ("caption", 31),
        ("badge", 27),
        ("legend", 70),
    ],
)
def test_adornment_minimum_width_rejects_narrow_sections(adornment, usable):
    adornments = {
        "caption": (CaptionRow("caption", color="#111"),),
        "badge": (Badge("badge"),),
        "legend": (Legend((("Alpha", "#111"), ("Beta", "#222"))),),
    }
    with pytest.raises(SpecError) as excinfo:
        resolve_rows(
            adornments[adornment],
            usable=usable,
            chrome=DEFAULT_CHROME,
            section="body",
        )
    message = str(excinfo.value)
    assert "body[0]" in message
    assert "requires at least" in message
    assert "available" in message
    assert "wider card" in message


def test_one_character_legend_labels_fit_at_70px():
    rows = resolve_rows(
        (Legend((("A", "#111"), ("B", "#222"))),),
        usable=70,
        chrome=DEFAULT_CHROME,
        section="body",
    )
    assert isinstance(rows[0].adornment, Legend)
    assert rows[0].adornment.entries == (("A", "#111"), ("B", "#222"))


def test_chip_reservation_uses_char_width_estimate():
    usable = 250
    width = usable + 2 * (DEFAULT_CHROME.padding + DEFAULT_CHROME.border_width)
    _measured, _header_rows, _body_rows, chip = measure_card(
        width=width,
        header=(InlineSvg(SVG_OK, width=220, height=30),),
        body=(MetricValue("+3"),),
        chrome=DEFAULT_CHROME,
    )
    assert chip is None

    usable = 251
    width = usable + 2 * (DEFAULT_CHROME.padding + DEFAULT_CHROME.border_width)
    measured, header_rows, _body_rows, chip = measure_card(
        width=width,
        header=(InlineSvg(SVG_OK, width=220, height=30),),
        body=(MetricValue("+3"),),
        chrome=DEFAULT_CHROME,
    )
    assert measured.width == width
    assert isinstance(header_rows[0].adornment, InlineSvg)
    assert header_rows[0].adornment.width == 220
    assert chip == ("+3", "neutral")


def test_chip_reservation_falls_back_when_colored_caption_header_would_not_fit():
    usable = 70
    width = usable + 2 * (DEFAULT_CHROME.padding + DEFAULT_CHROME.border_width)
    measured, header_rows, _body_rows, chip = measure_card(
        width=width,
        header=(CaptionRow("header", color="#111"),),
        body=(MetricValue("+345"),),
        chrome=DEFAULT_CHROME,
    )
    assert measured.width == width
    assert chip is None
    assert isinstance(header_rows[0].adornment, CaptionRow)
    assert header_rows[0].adornment.text == "header"


def test_measured_card_invariants_hold():
    measured, _header_rows, _body_rows, chip = measure_card(
        width=252,
        header=(TextBlock("Revenue", variant="title"),),
        body=(
            MetricValue("+3.4%", detail="[1.2, 5.7]", role="favorable"),
            CaptionRow("weekly", color="#111"),
        ),
        chrome=DEFAULT_CHROME,
    )
    assert measured.collapsed_height <= measured.expanded_height
    assert measured.width == 252
    assert chip == ("+3.4%", "favorable")
    for anchor in measured.anchors:
        assert 0 <= anchor.x <= measured.width
        assert 0 <= anchor.y <= measured.collapsed_height
    names = [a.name for a in measured.anchors]
    assert names == ["in", "out"]


def test_chip_comes_from_body_never_header():
    _, _, _, chip = measure_card(
        width=252,
        header=(TextBlock("t", variant="title"), MetricValue("+9.9%", role="favorable")),
        body=(),
        chrome=DEFAULT_CHROME,
    )
    assert chip is None


def test_one_character_title_header_keeps_chip_at_reduced_width():
    chip_value = "+3"
    usable = 45
    width = usable + 2 * (DEFAULT_CHROME.padding + DEFAULT_CHROME.border_width)
    chip_width = len(chip_value) * DEFAULT_CHROME.value_size * DEFAULT_CHROME.data_char_width_ratio
    candidate = int(usable - chip_width - DEFAULT_CHROME.gap)
    assert chip_width <= usable / 2
    assert candidate >= 1

    measured, header_rows, _body_rows, chip = measure_card(
        width=width,
        header=(TextBlock("t", variant="title"),),
        body=(MetricValue(chip_value),),
        chrome=DEFAULT_CHROME,
    )
    assert measured.width == width
    assert chip == (chip_value, "neutral")
    assert isinstance(header_rows[0].adornment, TextBlock)
    assert header_rows[0].adornment.text == "t"


def test_chip_refused_when_candidate_is_less_than_one():
    chrome = CardChrome(gap=24)
    chip_value = "+3"
    usable = 45
    width = usable + 2 * (chrome.padding + chrome.border_width)
    chip_width = len(chip_value) * chrome.value_size * chrome.data_char_width_ratio
    candidate = int(usable - chip_width - chrome.gap)
    assert chip_width <= usable / 2
    assert candidate < 1

    _, _, _, chip = measure_card(
        width=width,
        header=(),
        body=(MetricValue(chip_value),),
        chrome=chrome,
    )
    assert chip is None


def test_bigger_chrome_measures_taller():
    header = (TextBlock("A title that will wrap somewhere", variant="title", max_lines=3),)
    body = (CaptionRow("caption"),)
    small = measure_card(width=252, header=header, body=body, chrome=DEFAULT_CHROME)[0]
    big = measure_card(
        width=252,
        header=header,
        body=body,
        chrome=CardChrome(title_size=24, caption_size=18),
    )[0]
    assert big.expanded_height > small.expanded_height
    assert big.collapsed_height > small.collapsed_height


def test_header_gap_absent_for_empty_body():
    header = (TextBlock("t", variant="title"),)
    with_body = measure_card(
        width=252, header=header, body=(CaptionRow("c"),), chrome=DEFAULT_CHROME
    )[0]
    without = measure_card(width=252, header=header, body=(), chrome=DEFAULT_CHROME)[0]
    caption_h = line_height(DEFAULT_CHROME.caption_size, DEFAULT_CHROME)
    assert with_body.expanded_height == (
        without.expanded_height + DEFAULT_CHROME.header_gap + caption_h
    )


def _template() -> CardTemplate:
    return CardTemplate(
        width=252,
        header=(TextBlock("Revenue", variant="title"),),
        body=(
            MetricValue("+3.4%", detail="[1.2, 5.7]", role="favorable"),
            CaptionRow("weekly", color="#4C72B0"),
        ),
    )


def test_template_shell_pins_measured_heights():
    template = _template()
    measured = template.measure()
    _, _, body_rows, _ = measure_card(
        width=template.width,
        header=template.header,
        body=template.body,
        chrome=template.chrome,
    )
    html_out = template.render(theme=DEFAULT)
    assert f"width:{measured.width}px" in html_out
    for row in body_rows:
        assert f"height:{row.height}px" in html_out
    assert "box-sizing:border-box" in html_out
    assert html_out.startswith("<details open")
    assert re.search(r"\bid=", html_out) is None
    assert (
        f"border-width:{DEFAULT_CHROME.border_width}px;"
        f"border-style:solid;border-color:{_esc(DEFAULT.rule)};"
    ) in html_out


def test_bottom_padding_lives_on_details_in_both_fold_states():
    html_out = _template().render(theme=DEFAULT)
    details_tag = html_out[: html_out.index(">") + 1]
    assert "padding:0 0 16px 0" in details_tag  # DEFAULT_CHROME.padding
    body_block = html_out.split("</summary>")[1]
    assert "padding:10px 16px 0 16px" in body_block  # header_gap, padding, bottom on details


def test_template_render_is_deterministic_and_measure_stable():
    template = _template()
    assert template.render(theme=DEFAULT) == template.render(theme=DEFAULT)
    assert template.measure() == template.measure()


def test_template_body_rows_are_fixed_height_and_clipped():
    template = CardTemplate(
        width=252,
        header=(TextBlock("Revenue", variant="title"),),
        body=(
            KeyValuePopover("diagnostics", (("n", "412"),)),
            CaptionRow("weekly"),
        ),
    )
    _, _, body_rows, _ = measure_card(
        width=template.width,
        header=template.header,
        body=template.body,
        chrome=template.chrome,
    )
    html_out = template.render(theme=DEFAULT)
    details_tag = html_out[: html_out.index(">") + 1]
    assert "overflow:visible" in details_tag
    body_marker = '<div style="box-sizing:border-box;margin:0;'
    body_block = html_out.split(body_marker, 1)[1].rsplit("</div></details>", 1)[0]
    wrappers = re.findall(r'<div style="height:(\d+)px;overflow:(hidden|visible)', body_block)
    expected = [
        (str(row.height), "visible" if isinstance(row.adornment, KeyValuePopover) else "hidden")
        for row in body_rows
    ]
    assert wrappers == expected


def test_summary_shows_the_chip():
    html_out = _template().render(theme=DEFAULT)
    summary = html_out.split("</summary>")[0]
    assert "+3.4%" in summary
    assert "[1.2, 5.7]" not in summary  # chip is value-only
    assert "box-sizing:content-box" in summary
    assert "min-width:0" in summary
    assert "<style>details[open]>summary>.ct-card-chip{display:none}</style>" in html_out
    assert html_out.index("<summary") < html_out.index("<style")
    chip_span = re.search(r'<span class="ct-card-chip" style="([^"]+)">\+3\.4%</span>', summary)
    assert chip_span is not None
    chip_style = chip_span.group(1)
    chip_est = math.ceil(
        len("+3.4%") * DEFAULT_CHROME.value_size * DEFAULT_CHROME.data_char_width_ratio
    )
    assert f"max-width:{chip_est}px" in chip_style
    assert f"color:{DEFAULT.favorable}" in chip_style
    assert f"column-gap:{DEFAULT_CHROME.gap}px" in summary
    assert "align-items:flex-start" in summary


def test_select_label_and_control_keep_explicit_flex_allocations():
    control = SelectControl(
        "A label long enough to clip",
        (("a", "An option with a long visible label"),),
        selected="a",
    )
    html_out = render_adornment(control, theme=DEFAULT)
    label_span = re.search(r"<span style=\"([^\"]+)\">", html_out)
    select_tag = html_out[
        html_out.index("<select") : html_out.index(">", html_out.index("<select")) + 1
    ]
    assert label_span is not None
    assert f"width:calc(40% - {DEFAULT_CHROME.swatch_gap}px)" in label_span.group(1)
    assert "flex:none" in label_span.group(1)
    assert "overflow:hidden;text-overflow:ellipsis;white-space:nowrap" in label_span.group(1)
    assert "width:60%" in select_tag
    assert "flex:none" in select_tag
    assert f"column-gap:{DEFAULT_CHROME.swatch_gap}px" in html_out


def test_long_select_label_keeps_measured_allocation():
    template = CardTemplate(
        width=252,
        header=(TextBlock("Revenue", variant="title"),),
        body=(
            SelectControl(
                "A label long enough to clip",
                (("a", "An option with a long visible label"),),
                selected="a",
            ),
        ),
    )
    html_out = template.render(theme=DEFAULT)
    assert f"width:calc(40% - {DEFAULT_CHROME.swatch_gap}px);flex:none" in html_out


def test_long_interactive_labels_are_rendered_in_full():
    select_label = 'Select "label" & a long original name'
    popover_label = 'Popover "label" & a long original name for diagnostics'
    template = CardTemplate(
        width=252,
        header=(TextBlock("Revenue", variant="title"),),
        body=(
            SelectControl(select_label, (("a", "Alpha"),), selected="a"),
            KeyValuePopover(popover_label, (("n", "412"),)),
        ),
    )
    _, _, body_rows, _ = measure_card(
        width=template.width,
        header=template.header,
        body=template.body,
        chrome=template.chrome,
    )
    html_out = template.render(theme=DEFAULT)
    assert cast(SelectControl, body_rows[0].adornment).label == select_label
    assert cast(KeyValuePopover, body_rows[1].adornment).label == popover_label
    assert _esc(select_label) in html_out
    assert _esc(popover_label) in html_out


def test_narrow_select_label_budget_raises():
    with pytest.raises(SpecError):
        resolve_rows(
            (SelectControl("Breakout", (("a", "Alpha"),), selected="a"),),
            usable=42,
            chrome=DEFAULT_CHROME,
            section="body",
        )


def test_popover_row_wrapper_allows_panel_to_escape():
    template = CardTemplate(
        width=252,
        header=(TextBlock("Revenue", variant="title"),),
        body=(
            KeyValuePopover("diagnostics", (("n", "412"),)),
            CaptionRow("weekly"),
        ),
    )
    _, _, body_rows, _ = measure_card(
        width=template.width,
        header=template.header,
        body=template.body,
        chrome=template.chrome,
    )
    html_out = template.render(theme=DEFAULT)
    assert f"height:{body_rows[0].height}px;overflow:visible;" in html_out
    assert f"height:{body_rows[1].height}px;overflow:hidden;" in html_out


def test_interactive_adornments_rejected_in_header():
    with pytest.raises(SpecError):
        CardTemplate(
            width=252,
            header=(SelectControl("B", (("a", "A"),), selected="a"),),
        )
    with pytest.raises(SpecError):
        CardTemplate(
            width=252,
            header=(KeyValuePopover("d", (("k", "v"),)),),
        )


def test_template_width_validation():
    with pytest.raises(SpecError):
        CardTemplate(width=-1, header=(TextBlock("x"),))
    with pytest.raises(SpecError):
        CardTemplate(width=20, header=(CaptionRow("t"),))
    with pytest.raises(SpecError):
        CardTemplate(width=True, header=(TextBlock("t"),))
    with pytest.raises(SpecError):
        CardTemplate(width=252, header=())


def test_structural_width_rejects_textblock_without_adornment_guard():
    with pytest.raises(SpecError) as excinfo:
        CardTemplate(width=30, header=(TextBlock("x"),))
    assert "shell overhead" in str(excinfo.value)


def test_empty_normalized_text_has_no_content_minimum():
    template = CardTemplate(width=35, header=(TextBlock("   "),))
    assert template.measure().width == 35


def test_narrow_popover_label_rejects_content_minimum():
    with pytest.raises(SpecError) as excinfo:
        CardTemplate(
            width=45,
            header=(TextBlock("x"),),
            body=(KeyValuePopover("long", (("k", "v"),)),),
        )
    assert "KeyValuePopover" in str(excinfo.value)


def test_textblock_content_minimum_rejects_at_the_boundary():
    # A nonempty TextBlock reserves min(len, 2) chars at its variant size:
    # required = 2 * char_width_ratio * title_size = 2 * 0.6 * 14 = 16.8px.
    required = 2 * DEFAULT_CHROME.char_width_ratio * DEFAULT_CHROME.title_size
    shell = 2 * (DEFAULT_CHROME.padding + DEFAULT_CHROME.border_width)
    # Largest integer usable width still below the minimum: ceil(16.8) - 1 = 16px.
    failing_usable = math.ceil(required) - 1
    assert failing_usable >= 1  # structural guard passes; the content minimum decides
    with pytest.raises(SpecError) as excinfo:
        CardTemplate(
            width=shell + failing_usable,
            header=(TextBlock("xy", variant="title"),),
        )
    assert "TextBlock" in str(excinfo.value)


def test_textblock_content_minimum_accepts_one_step_wider():
    # Smallest integer usable width honoring the 16.8px minimum: ceil(16.8) = 17px.
    required = 2 * DEFAULT_CHROME.char_width_ratio * DEFAULT_CHROME.title_size
    shell = 2 * (DEFAULT_CHROME.padding + DEFAULT_CHROME.border_width)
    width = shell + math.ceil(required)
    template = CardTemplate(width=width, header=(TextBlock("xy", variant="title"),))
    assert template.measure().width == width


def test_inline_svg_wrapper_contains_baseline():
    template = CardTemplate(
        width=254,
        header=(TextBlock("t", variant="title"),),
        body=(InlineSvg(SVG_OK, width=220, height=30),),
    )
    assert "line-height:0" in template.render(theme=DEFAULT)


def test_rendered_html_attributes_are_well_formed():
    templates = [
        CardTemplate(width=252, header=(TextBlock("t", variant="title"),)),
        CardTemplate(
            width=252,
            header=(TextBlock("t", variant="title"),),
            body=(KeyValuePopover("diagnostics", (("n", "412"),)),),
        ),
        CardTemplate(
            width=300,
            header=(TextBlock("t", variant="title"),),
            body=(InlineSvg(SVG_OK, width=220, height=30),),
        ),
        CardTemplate(
            width=252,
            header=(
                TextBlock("A title long enough to wrap onto lines", variant="title", max_lines=3),
            ),
        ),
    ]
    outputs = [template.render(theme=DEFAULT) for template in templates]
    outputs += [render_adornment(adornment, theme=DEFAULT) for adornment in _valid_instances()]
    for html_out in outputs:
        assert html_out.count('"') % 2 == 0
        assert len(re.findall(r'style="[^"]*"', html_out)) == html_out.count("style=")


def test_callout_wraps_and_caps_at_a_non_default_max_lines():
    text = (
        "trade-off: Users vs AOV (r=-0.73); Users vs Price (r=-0.61) across every region we tested"
    )
    max_lines = 2  # below the default of 3, so the cap must engage
    width = 200
    usable = width - 2 * (DEFAULT_CHROME.border_width + DEFAULT_CHROME.padding)
    inset = DEFAULT_CHROME.callout_accent + DEFAULT_CHROME.callout_inset
    budget = max(
        int((usable - inset) / (DEFAULT_CHROME.char_width_ratio * DEFAULT_CHROME.body_size)), 2
    )
    expected_lines = text_line_plan(text, budget=budget, max_lines=max_lines)
    assert len(expected_lines) == max_lines  # confirm the cap actually engages

    measured, _header_rows, rows, _chip = measure_card(
        width=width,
        header=(TextBlock("Revenue", variant="title"),),
        body=(Callout(text, role="unfavorable", max_lines=max_lines),),
        chrome=DEFAULT_CHROME,
    )
    row_h = line_height(DEFAULT_CHROME.body_size, DEFAULT_CHROME)
    title_h = line_height(DEFAULT_CHROME.title_size, DEFAULT_CHROME)
    assert len(rows) == max_lines
    assert [r.height for r in rows] == [row_h] * max_lines
    assert [cast(Callout, r.adornment).text for r in rows] == list(expected_lines)
    expected_expanded = (
        2 * (DEFAULT_CHROME.border_width + DEFAULT_CHROME.padding)
        + DEFAULT_CHROME.header_gap
        + title_h
        + max_lines * row_h
    )
    assert measured.expanded_height == expected_expanded


def test_callout_carries_its_role_colour():
    html_out = render_adornment(Callout("watch out", role="unfavorable"), theme=DEFAULT)
    assert DEFAULT.color("unfavorable") in html_out


def test_callout_rejects_invalid_fields():
    with pytest.raises(SpecError, match=r"Callout\.max_lines must be >= 1"):
        Callout("x", max_lines=0)
    with pytest.raises(SpecError, match=r"Callout\.text"):
        Callout(7)  # ty: ignore[invalid-argument-type]


def test_callout_too_narrow_for_its_accent_is_rejected():
    # The accent bar and inset consume width; a card too narrow must fail
    # loudly at construction rather than silently clipping to nothing. The
    # title stays trivially short so it is Callout's own guard under test,
    # not the title's.
    text = "a much longer warning"
    required = (
        DEFAULT_CHROME.callout_accent
        + DEFAULT_CHROME.callout_inset
        + min(len(text), 2) * DEFAULT_CHROME.char_width_ratio * DEFAULT_CHROME.body_size
    )
    shell = 2 * (DEFAULT_CHROME.padding + DEFAULT_CHROME.border_width)
    failing_usable = math.ceil(required) - 1
    with pytest.raises(SpecError) as excinfo:
        CardTemplate(
            width=shell + failing_usable,
            header=(TextBlock("x"),),
            body=(Callout(text),),
        )
    assert "Callout" in str(excinfo.value)
