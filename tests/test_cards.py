"""Contract tests for the card adornment vocabulary and fragment renderer."""

import ast
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
from coeftable.cards.fragments import render_adornment
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


def test_metric_value_uses_role_color():
    html_out = render_adornment(MetricValue("+3.4%", role="favorable"), theme=DEFAULT)
    assert DEFAULT.favorable in html_out


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
        ("value_size", lambda: MetricValue("value")),
        ("ci_size", lambda: MetricValue("value", detail="interval")),
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
        "value-size",
        "ci-size",
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
