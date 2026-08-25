"""Contract tests for the card adornment vocabulary and fragment renderer."""

import re
from typing import cast

import pytest

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


def test_adornments_are_hashable():
    assert len({*_valid_instances()}) == len(_valid_instances())


@pytest.mark.parametrize(
    "build",
    [
        lambda: TextBlock("x", variant="huge"),  # ty: ignore[invalid-argument-type]
        lambda: TextBlock(7),  # ty: ignore[invalid-argument-type]
        lambda: MetricValue("+1", role="good"),  # ty: ignore[invalid-argument-type]
        lambda: MetricValue(3.4),  # ty: ignore[invalid-argument-type]
        lambda: MetricValue("+1", detail=7),  # ty: ignore[invalid-argument-type]
        lambda: Badge("x", role="loud"),  # ty: ignore[invalid-argument-type]
        lambda: Badge(None),  # ty: ignore[invalid-argument-type]
        lambda: CaptionRow("x", dash="wavy"),  # ty: ignore[invalid-argument-type]
        lambda: CaptionRow("x", color=7),  # ty: ignore[invalid-argument-type]
    ],
    ids=[
        "bad-variant",
        "nonstr-text",
        "bad-role",
        "nonstr-value",
        "nonstr-detail",
        "badge-bad-role",
        "badge-nonstr",
        "bad-dash",
        "nonstr-color",
    ],
)
def test_scalar_field_validation_raises_spec_error(build):
    with pytest.raises(SpecError):
        build()


@pytest.mark.parametrize(
    "build",
    [
        lambda: InlineSvg("<div/>", width=10, height=10),
        lambda: InlineSvg("not xml <", width=10, height=10),
        lambda: InlineSvg(SVG_OK, width=100, height=30),  # width mismatch
        lambda: InlineSvg(SVG_OK, width=220, height=40),  # height mismatch
        lambda: InlineSvg(SVG_OK, width=0, height=30),
        lambda: InlineSvg(SVG_OK, width=True, height=30),  # bool-as-int
        lambda: InlineSvg(
            SVG_OK,
            width=cast(int, 220.0),
            height=30,
        ),  # float-as-int
        lambda: InlineSvg(
            '<svg xmlns="http://www.w3.org/2000/svg" height="30"></svg>',
            width=220,
            height=30,
        ),  # missing width attr
    ],
    ids=[
        "non-svg-root",
        "malformed-xml",
        "width-mismatch",
        "height-mismatch",
        "zero-width",
        "bool-width",
        "float-width",
        "missing-width-attr",
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
        lambda: KeyValuePopover("d", ()),
        lambda: KeyValuePopover(
            "d",
            [("k", "v")],  # ty: ignore[invalid-argument-type]
        ),  # list, not tuple
        lambda: KeyValuePopover("d", (("k",),)),  # ty: ignore[invalid-argument-type]
        lambda: KeyValuePopover("d", (("k", 7),)),  # ty: ignore[invalid-argument-type]
        lambda: SelectControl("", (("a", "A"),), selected="a"),
        lambda: SelectControl("L", (), selected="a"),
        lambda: SelectControl("L", (("a", "A"), ("a", "B")), selected="a"),  # dup values
        lambda: SelectControl("L", (("a", "A"),), selected="b"),  # unknown value
        lambda: SelectControl(
            "L",
            cast(tuple[tuple[str, str], ...], [("a", "A")]),
            selected="a",
        ),  # list
        lambda: Legend(()),
        lambda: Legend((("A", "#111", "extra"),)),  # ty: ignore[invalid-argument-type]
        lambda: RuleStrip(()),
        lambda: RuleStrip((("x", "#111", "wavy"),)),  # bad dash
        lambda: RuleStrip((("x", "#111"),)),  # ty: ignore[invalid-argument-type]
    ],
    ids=[
        "popover-empty-label",
        "popover-empty-items",
        "popover-list",
        "popover-arity",
        "popover-nonstr",
        "select-empty-label",
        "select-no-options",
        "select-dup-values",
        "select-unknown-selected",
        "select-list",
        "legend-empty",
        "legend-arity",
        "rulestrip-empty",
        "rulestrip-bad-dash",
        "rulestrip-arity",
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
    assert "Breakout" in html_out
    assert "<select" in html_out


def test_popover_is_a_native_details_element():
    popover = KeyValuePopover("diagnostics", (("n", "412"),))
    html_out = render_adornment(popover, theme=DEFAULT)
    assert html_out.startswith("<details>")
    assert "<summary" in html_out


def test_theme_values_are_attribute_escaped():
    import dataclasses

    hostile = dataclasses.replace(
        DEFAULT,
        text='";id="injected',
        muted='";id="injected',
        favorable='";id="injected',
    )
    for adornment in _valid_instances():
        if isinstance(adornment, InlineSvg):
            continue
        html_out = render_adornment(adornment, theme=hostile)
        assert not re.search(r"\bid=", html_out)
