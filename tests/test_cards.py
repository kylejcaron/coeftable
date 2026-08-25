"""Contract tests for the card adornment vocabulary and fragment renderer."""

import ast
import dataclasses
import re
from pathlib import Path
from typing import cast

import pytest

import coeftable.cards
from coeftable.cards.adornments import (
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
from coeftable.cards.chrome import DEFAULT_CHROME, CardChrome, line_height
from coeftable.cards.fragments import render_adornment
from coeftable.cards.measure import measure_card, resolve_rows, text_line_plan
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
        lambda: MetricValue("+1", detail=7),  # ty: ignore[invalid-argument-type]
        lambda: MetricValue("+1", role=7),  # ty: ignore[invalid-argument-type]
        lambda: Badge("x", role="loud"),  # ty: ignore[invalid-argument-type]
        lambda: Badge(None),  # ty: ignore[invalid-argument-type]
        lambda: Badge("x", role=7),  # ty: ignore[invalid-argument-type]
        lambda: CaptionRow("x", dash="wavy"),  # ty: ignore[invalid-argument-type]
        lambda: CaptionRow("x", color=7),  # ty: ignore[invalid-argument-type]
        lambda: CaptionRow(7),  # ty: ignore[invalid-argument-type]
        lambda: CaptionRow("x", dash=7),  # ty: ignore[invalid-argument-type]
    ],
    ids=[
        "bad-variant",
        "nonstr-text",
        "nonstr-variant",
        "bad-role",
        "nonstr-value",
        "nonstr-detail",
        "nonstr-role",
        "badge-bad-role",
        "badge-nonstr",
        "badge-nonstr-role",
        "bad-dash",
        "nonstr-color",
        "nonstr-caption-text",
        "nonstr-dash",
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
    badge_html = render_adornment(Badge("accounting"), theme=DEFAULT)

    assert "overflow:hidden;text-overflow:ellipsis" in metric_html
    assert "white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%" in badge_html


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
    assert f"height:{expected}px" in html_out
    assert "display:flex;align-items:center" in html_out
    assert "max-width:60%" in html_out


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
    "CaptionRow",
    "InlineSvg",
    "KeyValuePopover",
    "Legend",
    "MetricValue",
    "RuleStrip",
    "SelectControl",
    "TextBlock",
    "render_adornment",
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
    assert len(coeftable.cards.__all__) == 11
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
        {"leading": 3.5},
        {"char_width_ratio": 0.0},
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
        "huge-leading",
        "zero-ratio",
        "nan-data-ratio",
    ],
)
def test_chrome_validation_raises_spec_error(kwargs):
    with pytest.raises(SpecError):
        CardChrome(**kwargs)


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


def test_line_plan_normalizes_whitespace():
    assert text_line_plan("  a\tb\n\nc  ", budget=20, max_lines=3) == ("a b c",)


def test_line_plan_empty_text_is_one_blank_line():
    assert text_line_plan("", budget=10, max_lines=3) == ("",)


def test_line_plan_caps_and_ellipsizes_the_last_line():
    plan = text_line_plan("one two three four five", budget=9, max_lines=2)
    assert len(plan) == 2
    assert plan[1].endswith("…")
    assert len(plan[1]) <= 9


def test_wrapping_textblock_height_is_lines_times_line_height():
    block = TextBlock("alpha beta gamma delta epsilon", variant="body", max_lines=3)
    rows = resolve_rows((block,), usable=80, chrome=DEFAULT_CHROME, section="body")
    lh = line_height(DEFAULT_CHROME.body_size, DEFAULT_CHROME)
    assert sum(r.height for r in rows) % lh == 0
    assert len(rows) >= 2  # narrow width forces a wrap
    assert all(isinstance(r.adornment, TextBlock) for r in rows)


def test_metric_value_overflow_raises_with_fixes():
    with pytest.raises(SpecError) as excinfo:
        resolve_rows(
            (MetricValue("+123,456,789.00% " * 4),),
            usable=60,
            chrome=DEFAULT_CHROME,
            section="body",
        )
    message = str(excinfo.value)
    assert "MetricValue.value" in message
    assert "wider card" in message


def test_inline_svg_wider_than_usable_raises():
    with pytest.raises(SpecError):
        resolve_rows(
            (InlineSvg(SVG_OK, width=220, height=30),),
            usable=200,
            chrome=DEFAULT_CHROME,
            section="body",
        )


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
    assert chip == "+3.4%"
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
