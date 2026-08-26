"""Contract tests for the built-in card regions."""

import re
from dataclasses import replace
from typing import Any, TypedDict

import pytest

import coeftable as ct
from coeftable.annotations import ResolvedBand, ResolvedRule
from coeftable.cards import (
    DEFAULT_CHROME,
    CaptionRow,
    CardChrome,
    InlineSvg,
    MetricValue,
    RuleStrip,
    TextBlock,
)
from coeftable.cards.regions import (
    Diagnostics,
    Event,
    Events,
    Interval,
    Metric,
    Trend,
    resolve_content,
)
from coeftable.errors import SpecError
from coeftable.theme import DEFAULT, Theme


def _unchecked(value: object) -> Any:
    return value


class ResolveKw(TypedDict):
    """Parameters supplied to region resolution."""

    width: int
    theme: Theme
    chrome: CardChrome


RESOLVE_KW: ResolveKw = {"width": 220, "theme": DEFAULT, "chrome": DEFAULT_CHROME}


def test_metric_with_ci_resolves_value_detail_and_role():
    (adorn,) = Metric(3.4, ct.Percent(signed=True), ci=(1.2, 5.7), ref=0.0).resolve(**RESOLVE_KW)
    assert isinstance(adorn, MetricValue)
    assert adorn.value == ct.Percent(signed=True)(3.4)
    assert adorn.detail == f"[{ct.Percent(signed=True)(1.2)}, {ct.Percent(signed=True)(5.7)}]"
    assert adorn.role == "favorable"


def test_metric_ci_fmt_overrides_detail_formatting():
    (adorn,) = Metric(
        3.4, ct.Percent(signed=True), ci=(1.2, 5.7), ci_fmt=ct.Number(), ref=0.0
    ).resolve(**RESOLVE_KW)
    assert adorn.detail == f"[{ct.Number()(1.2)}, {ct.Number()(5.7)}]"


def test_metric_without_ci_is_neutral_with_no_detail():
    (adorn,) = Metric(3.4, ct.Number(), ref=0.0).resolve(**RESOLVE_KW)
    assert adorn.role == "neutral"
    assert adorn.detail is None


@pytest.mark.parametrize(
    "ci,direction,expected",
    [
        ((1.2, 5.7), "higher_is_better", "favorable"),
        ((-5.7, -1.2), "higher_is_better", "unfavorable"),
        ((-1.0, 1.0), "higher_is_better", "inconclusive"),
        ((1.2, 5.7), "lower_is_better", "unfavorable"),
    ],
)
def test_metric_role_paths(ci, direction, expected):
    (adorn,) = Metric(3.4, ct.Number(), ci=ci, ref=0.0, direction=direction).resolve(**RESOLVE_KW)
    assert adorn.role == expected


def test_metric_explicit_role_overrides():
    (adorn,) = Metric(3.4, ct.Number(), ci=(1.2, 5.7), ref=0.0, role="inconclusive").resolve(
        **RESOLVE_KW
    )
    assert adorn.role == "inconclusive"


@pytest.mark.parametrize(
    "build",
    [
        lambda: Metric(float("nan"), ct.Number()),
        lambda: Metric(True, ct.Number()),
        lambda: Metric(3.4, _unchecked("not callable")),
        lambda: Metric(3.4, ci=_unchecked(1), fmt=ct.Number()),
        lambda: Metric(3.4, ct.Number(), ci=(5.7, 1.2)),
        lambda: Metric(3.4, ct.Number(), ci=_unchecked((1.2,))),
        lambda: Metric(3.4, ct.Number(), ci=(1.2, float("inf"))),
        lambda: Metric(3.4, ct.Number(), ref=float("nan")),
        lambda: Metric(3.4, ct.Number(), direction=_unchecked("sideways")),
        lambda: Metric(3.4, ct.Number(), role=_unchecked("loud")),
        lambda: Metric(3.4, ct.Number(), ci=(1.2, 5.7), ci_fmt=_unchecked("nope")),
    ],
    ids=[
        "nan-value",
        "bool-value",
        "fmt-not-callable",
        "malformed-ci",
        "unordered-ci",
        "short-ci",
        "inf-ci",
        "nan-ref",
        "bad-direction",
        "bad-role",
        "bad-ci-fmt",
    ],
)
def test_metric_validation(build):
    with pytest.raises(SpecError):
        build()


def test_diagnostics_formats_numbers_and_passes_strings():
    (adorn,) = Diagnostics(
        "diagnostics", [("n", 412), ("estimator", "ATT")], fmt=ct.Number(), key="diag"
    ).resolve(**RESOLVE_KW)
    assert adorn.label == "diagnostics"
    assert adorn.items == (("n", ct.Number()(412)), ("estimator", "ATT"))
    assert adorn.key == "diag"


@pytest.mark.parametrize(
    "build",
    [
        lambda: Diagnostics("", [("k", 1)]),
        lambda: Diagnostics("d", []),
        lambda: Diagnostics("d", _unchecked(1)),
        lambda: Diagnostics("d", [("k", True)]),
        lambda: Diagnostics("d", [("k", float("nan"))]),
        lambda: Diagnostics("d", _unchecked([(1, "v")])),
        lambda: Diagnostics("d", _unchecked([1])),
        lambda: Diagnostics("d", _unchecked([("k", "v", "extra")])),
    ],
    ids=[
        "empty-label",
        "empty-items",
        "malformed-items",
        "bool-value",
        "nan-value",
        "nonstr-key",
        "malformed-item",
        "triple-item",
    ],
)
def test_diagnostics_validation(build):
    with pytest.raises(SpecError):
        build()


def test_events_resolve_captions_replace_strip():
    events = Events(
        [Event("launch", "#4C72B0", at=3.0), Event("incident", "#C44E52", dash="dashed")],
        captions=True,
    )
    cap1, cap2 = events.resolve(**RESOLVE_KW)
    assert not any(isinstance(item, RuleStrip) for item in (cap1, cap2))
    assert isinstance(cap1, CaptionRow) and cap1.text == "launch"
    assert cap1.color == "#4C72B0" and cap1.dash == "dotted"
    assert isinstance(cap2, CaptionRow) and cap2.text == "incident"
    assert cap2.dash == "dashed"


def test_events_rules_derive_from_positioned_events_only():
    events = Events([Event("launch", "#4C72B0", at=3.0), Event("nopos", "#111111")])
    rules = events.rules()
    assert len(rules) == 1
    rule = rules[0]
    assert (rule.at, rule.axis, rule.color, rule.dash) == (3.0, "x", "#4C72B0", "dotted")
    assert rule.affect_domain is False


@pytest.mark.parametrize(
    "build",
    [
        lambda: Events([]),
        lambda: Events(_unchecked(1)),
        lambda: Events([Event("", "#111111")]),
        lambda: Events([Event("x", "#111111", dash=_unchecked("wavy"))]),
        lambda: Events([Event("x", "#111111", at=float("nan"))]),
        lambda: Events(_unchecked(["not-an-event"])),
        lambda: Events([Event("x", "#111")], captions=_unchecked("yes")),
    ],
    ids=[
        "no-events",
        "malformed-events",
        "empty-label",
        "bad-dash",
        "nan-at",
        "nonevent-item",
        "bad-captions",
    ],
)
def test_events_validation(build):
    with pytest.raises(SpecError):
        build()


@pytest.mark.parametrize(
    "build",
    [
        lambda: Metric(1.0, ct.Number(), ci=_unchecked("ab")),
        lambda: Metric(1.0, ct.Number(), ci=_unchecked(b"ab")),
        lambda: Diagnostics("d", _unchecked(["kv"])),
        lambda: Events(_unchecked("xy")),
    ],
    ids=["str-ci", "bytes-ci", "str-item", "str-events"],
)
def test_str_container_guard_names_the_string(build):
    with pytest.raises(SpecError, match="not a string"):
        build()


def test_resolve_content_passthrough_is_identity_and_flattens_in_order():
    block = TextBlock("title", variant="title")
    metric = Metric(3.4, ct.Number())
    out = resolve_content([block, metric], **RESOLVE_KW)
    assert out[0] is block
    assert isinstance(out[1], MetricValue)
    assert len(out) == 2


def test_resolve_content_accepts_structural_third_party_regions():
    class Custom:
        def resolve(self, *, width, theme, chrome):
            return (TextBlock("custom"),)

    out = resolve_content([Custom()], **RESOLVE_KW)
    assert out == (TextBlock("custom"),)


def test_resolve_content_rejects_unknown_objects_with_index_and_type():
    with pytest.raises(SpecError) as excinfo:
        resolve_content(_unchecked([TextBlock("ok"), object()]), **RESOLVE_KW)
    assert "1" in str(excinfo.value)
    assert "object" in str(excinfo.value)


def test_canonicalization_snapshots_caller_lists():
    items = [("n", 412)]
    diag = Diagnostics("d", items)
    items.append(("mutated", 1))
    (adorn,) = diag.resolve(**RESOLVE_KW)
    assert adorn.items == (("n", ct.Number()(412)),)


def test_events_canonicalization_snapshots_caller_lists():
    source = [Event("launch", "#4C72B0")]
    events = Events(source)
    source.append(Event("mutated", "#C44E52"))
    (strip,) = events.resolve(**RESOLVE_KW)
    assert isinstance(strip, RuleStrip)
    assert strip.entries == (("launch", "#4C72B0", "dotted"),)


X = (0.0, 1.0, 2.0, 3.0)
Y = (0.3, 0.8, 1.1, 1.5)
LO = (-0.1, 0.3, 0.6, 0.9)
HI = (0.7, 1.3, 1.6, 2.1)


class TrendKw(TypedDict):
    """Parameters shared by Trend tests."""

    x: tuple[float, ...]
    y: tuple[float, ...]
    x_domain: tuple[float, float]
    domain: tuple[float, float]
    ref: float


TREND_KW: TrendKw = dict(x=X, y=Y, x_domain=(0.0, 3.0), domain=(-0.5, 2.5), ref=0.0)


def _svg_root_height(svg: str) -> int:
    match = re.search(r"<svg\b[^>]*\bheight=\"([0-9]+)\"", svg)
    assert match is not None
    return int(match.group(1))


def test_trend_with_ribbon_resolves_two_svgs_with_shared_width():
    spark, axis = Trend(lower=LO, upper=HI, **TREND_KW).resolve(**RESOLVE_KW)
    assert isinstance(spark, InlineSvg) and isinstance(axis, InlineSvg)
    assert spark.width == axis.width == 220
    assert spark.height == 30 and axis.height == 22


def test_trend_without_ribbon_emits_no_ribbon_polygon_and_is_neutral():
    (spark, _) = Trend(**TREND_KW).resolve(**RESOLVE_KW)
    assert "<polygon" not in spark.svg
    assert DEFAULT.neutral in spark.svg


def test_trend_ribbon_role_reads_last_fully_present_index():
    y = (0.3, 0.8, 1.1, None)
    lower = (LO[0], LO[1], LO[2], -0.5)
    upper = (HI[0], HI[1], HI[2], 0.5)
    (spark, _) = Trend(
        x=X,
        y=y,
        lower=lower,
        upper=upper,
        x_domain=(0.0, 3.0),
        domain=(-0.5, 2.5),
        ref=0.0,
    ).resolve(**RESOLVE_KW)
    assert DEFAULT.favorable in spark.svg
    assert DEFAULT.inconclusive not in spark.svg

    polygon = re.search(r'<polygon points="([^"]+)"', spark.svg)
    polyline = re.search(r'<polyline points="([^"]+)"', spark.svg)
    assert polygon is not None and polyline is not None
    polygon_points = polygon.group(1).split()
    polyline_points = polyline.group(1).split()
    assert len(polygon_points) > len(polyline_points)
    assert float(polygon_points[0].split(",", 1)[1]) == pytest.approx(17.4)


def test_trend_endpoint_one_sided_interval_drives_role():
    lower = (-0.1, -0.1, -0.1, 0.9)
    upper = (0.7, 1.3, 1.6, None)
    (spark, _) = Trend(lower=lower, upper=upper, **TREND_KW).resolve(**RESOLVE_KW)
    assert DEFAULT.favorable in spark.svg
    assert DEFAULT.inconclusive not in spark.svg


def test_trend_explicit_role_override_and_axis_toggle():
    (spark,) = Trend(role="unfavorable", show_axis=False, lower=LO, upper=HI, **TREND_KW).resolve(
        **RESOLVE_KW
    )
    assert isinstance(spark, InlineSvg)
    assert DEFAULT.unfavorable in spark.svg
    assert DEFAULT.favorable not in spark.svg


def test_trend_escapes_hostile_theme_favorable_color():
    theme = replace(DEFAULT, favorable='red" onclick="alert(1)')
    spark, _ = Trend(lower=LO, upper=HI, **TREND_KW).resolve(
        width=RESOLVE_KW["width"], theme=theme, chrome=RESOLVE_KW["chrome"]
    )
    assert isinstance(spark, InlineSvg)
    assert "&quot;" in spark.svg
    assert '" onclick="' not in spark.svg


def test_trend_lower_is_better_flips_role():
    (spark, _) = Trend(direction="lower_is_better", lower=LO, upper=HI, **TREND_KW).resolve(
        **RESOLVE_KW
    )
    assert DEFAULT.unfavorable in spark.svg
    assert DEFAULT.favorable not in spark.svg


def test_trend_spine_alignment_endpoint_on_and_off():
    for show_endpoint in (True, False):
        spark, axis = Trend(
            lower=LO,
            upper=HI,
            show_endpoint=show_endpoint,
            endpoint_width=60,
            inset=5,
            **TREND_KW,
        ).resolve(**RESOLVE_KW)
        plot = re.search(r'<polyline[^>]*points="([^"]+)"', spark.svg)
        assert plot is not None
        point_xs = [float(point.split(",", 1)[0]) for point in plot.group(1).split()]
        tick_xs = [
            float(value)
            for value in re.findall(r'<line x1="([0-9.]+)" y1="[0-9.]+" x2="\1"', axis.svg)
        ]
        assert point_xs and tick_xs
        assert abs(point_xs[0] - min(tick_xs)) < 0.01
        assert abs(point_xs[-1] - max(tick_xs)) < 0.01


def test_trend_axis_fmt_is_independent_of_endpoint_fmt():
    spark, axis = Trend(
        lower=LO,
        upper=HI,
        fmt=ct.Percent(signed=True),
        axis_fmt=ct.Currency(),
        **TREND_KW,
    ).resolve(**RESOLVE_KW)
    assert "%" in spark.svg
    assert "$" in axis.svg
    assert "$" not in spark.svg


def test_trend_temporal_axis_defaults_to_dateaxis_and_taller_root():
    import datetime as dt

    epoch = [dt.datetime(2024, 1, 1 + i).timestamp() for i in range(4)]
    _, axis = Trend(
        x=epoch,
        y=Y,
        x_domain=(epoch[0], epoch[-1]),
        domain=(-0.5, 2.5),
        ref=0.0,
        temporal=True,
    ).resolve(**RESOLVE_KW)
    assert axis.height == _svg_root_height(axis.svg)
    assert axis.height > 22


def test_trend_affect_domain_annotation_outside_domain_raises():
    band = ResolvedBand(
        start=10.0,
        end=12.0,
        axis="x",
        layer="underlay",
        affect_domain=True,
        color=None,
        opacity=0.2,
    )
    trend = Trend(annotations=(band,), lower=LO, upper=HI, **TREND_KW)
    with pytest.raises(SpecError) as excinfo:
        trend.resolve(**RESOLVE_KW)
    assert "domain" in str(excinfo.value)
    assert "10.0" in str(excinfo.value)


def test_trend_affect_domain_annotation_inside_domain_renders():
    rule = ResolvedRule(
        at=1.5,
        axis="x",
        layer="overlay",
        affect_domain=True,
        color="#4C72B0",
        opacity=1.0,
        width=1.0,
        dash="dotted",
    )
    spark, _ = Trend(annotations=(rule,), lower=LO, upper=HI, **TREND_KW).resolve(**RESOLVE_KW)
    assert "#4C72B0" in spark.svg


def test_trend_events_rules_render_on_plot():
    events = Events([Event("launch", "#4C72B0", at=1.5)])
    (spark, _) = Trend(annotations=events.rules(), lower=LO, upper=HI, **TREND_KW).resolve(
        **RESOLVE_KW
    )
    assert "#4C72B0" in spark.svg


def test_trend_canonicalization_snapshots_caller_lists():
    x = list(X)
    y = list(Y)
    lower = list(LO)
    upper = list(HI)
    annotations = [
        ResolvedRule(
            at=1.5,
            axis="x",
            layer="overlay",
            affect_domain=False,
            color="#4C72B0",
            opacity=1.0,
            width=1.0,
            dash="dotted",
        )
    ]
    trend = Trend(
        x=x,
        y=y,
        lower=lower,
        upper=upper,
        x_domain=(0.0, 3.0),
        domain=(-0.5, 2.5),
        annotations=annotations,
    )
    x.append(4.0)
    y.append(2.0)
    lower.append(1.0)
    upper.append(2.5)
    annotations.append(
        ResolvedRule(
            at=2.5,
            axis="x",
            layer="overlay",
            affect_domain=False,
            color="#C44E52",
            opacity=1.0,
            width=1.0,
            dash="dashed",
        )
    )
    spark, _ = trend.resolve(**RESOLVE_KW)
    assert "#C44E52" not in spark.svg
    assert len(trend.x) == len(trend.y) == 4
    assert trend.lower is not None and trend.upper is not None
    assert len(trend.lower) == len(trend.upper) == 4
    assert len(trend.annotations) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(x=(), y=(), x_domain=(0, 1), domain=(0, 1)),
        dict(x=X, y=Y[:3], x_domain=(0, 3), domain=(0, 1)),
        dict(x=X, y=Y, lower=LO, upper=None, x_domain=(0, 3), domain=(0, 1)),
        dict(x=X, y=Y, lower=HI, upper=LO, x_domain=(0, 3), domain=(0, 1)),
        dict(x=X, y=Y, lower=LO, upper=(0.7, 1.3, 1.6), x_domain=(0, 3), domain=(0, 1)),
        dict(x=X, y=Y, x_domain=(3, 0), domain=(0, 1)),
        dict(x=X, y=Y, x_domain=(0, 3), domain=(1, 0)),
        dict(x=X, y=(None, None, None, None), x_domain=(0, 3), domain=(0, 1)),
        dict(x=X, y=(0.3, float("inf"), 1.1, 1.5), x_domain=(0, 3), domain=(0, 1)),
        dict(
            x=X,
            y=Y,
            lower=(0.0, 0.3, float("-inf"), 0.9),
            upper=HI,
            x_domain=(0, 3),
            domain=(0, 1),
        ),
        dict(x=(0.0, True, 2.0, 3.0), y=Y, x_domain=(0, 3), domain=(0, 1)),
        dict(x=X, y=Y, x_domain=(0, 3), domain=(0, 1), fmt=_unchecked("fmt")),
        dict(x=X, y=Y, x_domain=(0, 3), domain=(0, 1), axis_fmt=_unchecked("fmt")),
        dict(x=X, y=Y, x_domain=(0, 3), domain=(0, 1), ref=float("nan")),
        dict(x=X, y=Y, x_domain=(0, 3), domain=(0, 1), direction=_unchecked("sideways")),
        dict(x=X, y=Y, x_domain=(0, 3), domain=(0, 1), role=_unchecked("loud")),
        dict(x=X, y=Y, x_domain=(0, 3), domain=(0, 1), temporal=_unchecked(1)),
        dict(x=X, y=Y, x_domain=(0, 3), domain=(0, 1), show_axis=_unchecked(1)),
        dict(x=X, y=Y, x_domain=(0, 3), domain=(0, 1), show_endpoint=_unchecked(1)),
        dict(x=X, y=Y, x_domain=(0, 3), domain=(0, 1), height=True),
        dict(x=X, y=Y, x_domain=(0, 3), domain=(0, 1), axis_height=True),
        dict(x=X, y=Y, x_domain=(0, 3), domain=(0, 1), axis_height=0),
        dict(x=X, y=Y, x_domain=(0, 3), domain=(0, 1), endpoint_width=True),
        dict(x=X, y=Y, x_domain=(0, 3), domain=(0, 1), endpoint_width=0),
        dict(x=X, y=Y, x_domain=(0, 3), domain=(0, 1), inset=True),
        dict(x=X, y=Y, x_domain=(0, 3), domain=(0, 1), inset=0),
        dict(x=X, y=Y, x_domain=(0, 3), domain=(0, 1), annotations=("rule",)),
    ],
    ids=[
        "empty",
        "ragged",
        "one-sided-ribbon",
        "inverted-ribbon",
        "ragged-lower-upper",
        "unordered-x-domain",
        "unordered-domain",
        "no-drawable-point",
        "inf-y",
        "inf-bound",
        "bool-x",
        "fmt-not-callable",
        "axis-fmt-not-callable",
        "nan-ref",
        "bad-direction",
        "bad-role",
        "non-bool-temporal",
        "non-bool-show-axis",
        "non-bool-show-endpoint",
        "bool-height",
        "bool-axis-height",
        "zero-axis-height",
        "bool-endpoint-width",
        "zero-endpoint-width",
        "bool-inset",
        "zero-inset",
        "non-annotation",
    ],
)
def test_trend_validation(kwargs):

    with pytest.raises(SpecError):
        Trend(**kwargs)


def test_trend_horizontal_projection_span_guard_boundaries():
    # horizontal_span = width - endpoint_width - 2*inset; defaults make
    # width=50 the rejected zero-span boundary and width=51 one-pixel.
    trend = Trend(**TREND_KW)
    with pytest.raises(SpecError, match="horizontal projection span"):
        trend.resolve(width=50, theme=DEFAULT, chrome=DEFAULT_CHROME)
    spark, _ = trend.resolve(width=51, theme=DEFAULT, chrome=DEFAULT_CHROME)
    assert isinstance(spark, InlineSvg)


def test_trend_vertical_projection_span_guard_boundaries():
    # vertical_span = height - 2*inset; defaults make height=6 the rejected
    # zero-span boundary and height=7 one-pixel.
    zero = Trend(height=6, **TREND_KW)
    with pytest.raises(SpecError, match="vertical projection span"):
        zero.resolve(**RESOLVE_KW)
    one = Trend(height=7, **TREND_KW)
    spark, _ = one.resolve(**RESOLVE_KW)
    assert isinstance(spark, InlineSvg)


def test_interval_horizontal_projection_span_guard_boundaries():
    # horizontal_span = width - 2*(margin + inset); margin=18 and inset=3
    # make width=42 the rejected zero-span boundary and width=43 one-pixel.
    zero = Interval(1.2, 0.4, 2.0, domain=(-1.0, 3.0), margin=18)
    with pytest.raises(SpecError, match="horizontal projection span"):
        zero.resolve(width=42, theme=DEFAULT, chrome=DEFAULT_CHROME)
    one = Interval(1.2, 0.4, 2.0, domain=(-1.0, 3.0), margin=18)
    bar, _ = one.resolve(width=43, theme=DEFAULT, chrome=DEFAULT_CHROME)
    assert isinstance(bar, InlineSvg)


def test_trend_nan_gaps_are_accepted():
    trend = Trend(
        x=X,
        y=(0.3, float("nan"), 1.1, 1.5),
        lower=(-0.1, float("nan"), 0.6, 0.9),
        upper=(0.7, float("nan"), 1.6, 2.1),
        x_domain=(0.0, 3.0),
        domain=(-0.5, 2.5),
    )
    spark, _ = trend.resolve(**RESOLVE_KW)
    assert "<polyline" in spark.svg


def test_interval_resolves_bar_and_axis_sharing_domain_and_margin():
    bar, axis = Interval(1.2, 0.4, 2.0, domain=(-1.0, 3.0), ref=0.0, margin=18).resolve(
        **RESOLVE_KW
    )
    from coeftable.cards import InlineSvg

    assert isinstance(bar, InlineSvg) and isinstance(axis, InlineSvg)
    assert bar.width == axis.width == 220
    assert DEFAULT.favorable in bar.svg


def test_interval_forest_alignment_with_nonzero_margin():
    bar, axis = Interval(1.0, -1.0, 3.0, domain=(-1.0, 3.0), ref=0.0, margin=18).resolve(
        **RESOLVE_KW
    )
    rect = re.search(r'<rect x="([0-9.]+)"[^>]*?width="([0-9.]+)"', bar.svg)
    tick_xs = [
        float(value)
        for value in re.findall(r'<line x1="([0-9.]+)" y1="[0-9.]+" x2="\1"', axis.svg)
    ]
    assert rect is not None and tick_xs
    x, rect_width = (float(value) for value in rect.groups())
    assert abs(x - (18 + 3)) < 0.01
    assert abs(x + rect_width - (220 - 18 - 3)) < 0.01
    assert abs(min(tick_xs) - x) < 0.01
    assert abs(max(tick_xs) - (x + rect_width)) < 0.01


def test_interval_role_and_axis_toggle():
    (bar,) = Interval(0.0, -1.0, 1.0, domain=(-2.0, 2.0), show_axis=False).resolve(**RESOLVE_KW)
    assert DEFAULT.inconclusive in bar.svg


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(estimate=1.0, lower=2.0, upper=0.5, domain=(0, 3)),
        dict(estimate=1.0, lower=0.5, upper=2.0, domain=(3, 0)),
        dict(estimate=float("nan"), lower=0.5, upper=2.0, domain=(0, 3)),
        dict(estimate=1.0, lower=float("nan"), upper=2.0, domain=(0, 3)),
        dict(estimate=1.0, lower=0.5, upper=float("nan"), domain=(0, 3)),
        dict(estimate=1.0, lower=0.5, upper=2.0, domain=(0, 3), ref=float("nan")),
        dict(estimate=1.0, lower=0.5, upper=2.0, domain=(0, 3), margin=-1),
        dict(estimate=1.0, lower=0.5, upper=2.0, domain=(0, 3), margin=1, inset=3),
        dict(estimate=1.0, lower=0.5, upper=2.0, domain=(0, 3), fmt=_unchecked("fmt")),
        dict(estimate=1.0, lower=0.5, upper=2.0, domain=(0, 3), direction=_unchecked("sideways")),
        dict(estimate=1.0, lower=0.5, upper=2.0, domain=(0, 3), role=_unchecked("loud")),
        dict(estimate=1.0, lower=0.5, upper=2.0, domain=(0, 3), show_axis=_unchecked(1)),
        dict(estimate=1.0, lower=0.5, upper=2.0, domain=(0, 3), height=True),
        dict(estimate=1.0, lower=0.5, upper=2.0, domain=(0, 3), axis_height=True),
        dict(estimate=1.0, lower=0.5, upper=2.0, domain=(0, 3), inset=True),
        dict(estimate=1.0, lower=0.5, upper=2.0, domain=(0, 3), inset=0),
    ],
    ids=[
        "inverted-bounds",
        "unordered-domain",
        "nan-estimate",
        "nan-lower",
        "nan-upper",
        "nan-ref",
        "negative-margin",
        "margin-not-greater-than-inset",
        "fmt-not-callable",
        "bad-direction",
        "bad-role",
        "non-bool-show-axis",
        "bool-height",
        "bool-axis-height",
        "bool-inset",
        "zero-inset",
    ],
)
def test_interval_validation(kwargs):
    with pytest.raises(SpecError):
        Interval(**kwargs)


def test_interval_margin_equal_to_inset_raises_with_exact_bounds():
    with pytest.raises(
        SpecError,
        match=r"Interval\.margin \(3\) must be 0 or strictly greater than Interval\.inset \(3\)",
    ):
        Interval(1.0, 0.5, 2.0, domain=(0.0, 3.0), margin=3, inset=3)


def test_interval_explicit_role_override():
    (bar,) = Interval(
        1.0, 0.5, 2.0, domain=(0.0, 3.0), role="unfavorable", show_axis=False
    ).resolve(**RESOLVE_KW)
    assert DEFAULT.unfavorable in bar.svg
    assert DEFAULT.favorable not in bar.svg


@pytest.mark.parametrize(
    ("region", "width", "message"),
    [
        (
            Trend(lower=LO, upper=HI, endpoint_width=220, **TREND_KW),
            220,
            "width \\(220\\).*endpoint_width \\(220\\).*inset \\(6\\).*= -6",
        ),
        (
            Trend(lower=LO, upper=HI, height=5, inset=3, **TREND_KW),
            220,
            "height \\(5\\).*inset \\(6\\).*= -1",
        ),
        (
            Interval(1.0, 0.5, 2.0, domain=(0.0, 3.0), margin=108),
            220,
            "width \\(220\\).*margin \\(108\\).*inset \\(3\\).*= -2",
        ),
        (
            Trend(lower=LO, upper=HI, endpoint_width=214, **TREND_KW),
            220,
            "width \\(220\\).*endpoint_width \\(214\\).*2\\*inset \\(6\\).*= 0",
        ),
    ],
    ids=[
        "trend-endpoint-reserve",
        "trend-vertical-inset",
        "interval-margin-reserve",
        "trend-zero-span",
    ],
)
def test_projection_guards_name_effective_spans(region, width, message):
    with pytest.raises(SpecError, match=message):
        region.resolve(width=width, theme=DEFAULT, chrome=DEFAULT_CHROME)
