import datetime as dt
import re

import narwhals as nw
import pandas as pd
import polars as pl
import pytest

from coeftable.format import CIStyle, DateAxis
from coeftable.frame import resolve
from coeftable.spec import (
    Cell,
    CoefTable,
    ColumnNotFoundError,
    Sparkline,
    SpecError,
    _bucket_domain,
    _clamp_domain,
    _pad_domain,
    _resolve_role,
    _robust_domain,
    validate_columns,
)
from coeftable.theme import DEFAULT

# The motivating experiment table: lift % over dates, ref=0, nested variants
# under each metric, grouped by area. Revenue stays small and entirely
# positive; Latency swings from negative to strongly positive and is ~20x
# the magnitude -- distinct enough that a shared y-domain (scale="table")
# is visibly different from a per-metric one (scale="row").
DATES = [dt.date(2024, 1, 1), dt.date(2024, 1, 8), dt.date(2024, 1, 15)]

RAW = {
    "area": ["Core", "Core", "Ops", "Ops"],
    "metric": ["Revenue", "Revenue", "Latency", "Latency"],
    "variant": ["B", "C", "B", "C"],
    "date": [DATES, DATES, DATES, DATES],
    "lift": [
        [1.0, 1.5, 2.0],
        [0.5, 0.8, 1.2],
        [-10.0, 0.0, 30.0],
        [20.0, 25.0, 28.0],
    ],
    "lift_lb": [
        [0.5, 1.0, 1.5],
        [0.0, 0.3, 0.7],
        [-15.0, -5.0, 20.0],
        [10.0, 15.0, 18.0],
    ],
    "lift_ub": [
        [1.5, 2.0, 2.5],
        [1.0, 1.3, 1.7],
        [-5.0, 5.0, 40.0],
        [30.0, 35.0, 38.0],
    ],
}


def motivating_table(data, **kwargs):
    return CoefTable(data, rows="metric", nest="variant", groups="area", **kwargs)


@pytest.fixture(params=["pandas", "polars"])
def data(request):
    if request.param == "pandas":
        return pd.DataFrame(RAW)
    return pl.DataFrame(RAW)


# A second, small table dedicated to role resolution: "Up" ends clearly above
# ref, "Mixed" ends straddling it.
ROLE_RAW = {
    "metric": ["Up", "Mixed"],
    "lift": [[1.0, 2.0, 5.0], [3.0, -1.0, 0.5]],
    "lift_lb": [[0.5, 1.0, 3.0], [1.0, -3.0, -1.5]],
    "lift_ub": [[1.5, 3.0, 7.0], [5.0, 1.0, 2.5]],
}


def role_table(**kwargs):
    return CoefTable(pl.DataFrame(ROLE_RAW), rows="metric", **kwargs).sparkline(
        "Trend", value="lift", ci=("lift_lb", "lift_ub"), ref=0.0
    )


def _ref_line_y(svg: str) -> float:
    """Extract the dashed reference line's y-pixel from a rendered sparkline SVG."""
    match = re.search(r'<line x1="(-?[\d.]+)" y1="(-?[\d.]+)"[^>]*stroke-dasharray="2,2"', svg)
    assert match is not None, f"no reference line in {svg!r}"
    return float(match.group(2))


def _polyline_ys(svg: str) -> list[float]:
    """Extract the polyline's y-pixels, in point order, from a rendered SVG."""
    match = re.search(r'<polyline points="([^"]+)"', svg)
    assert match is not None, f"no polyline in {svg!r}"
    return [float(pair.split(",")[1]) for pair in match.group(1).split(" ")]


def _cap_edges(svg: str) -> int:
    """Count distinct clip-cap brackets (each is a 0.45-opacity double line) in a rendered SVG."""
    return svg.count('stroke-opacity="0.45"') // 2


# A baseline hovering around 1.0x with one point spiking to 300x during a
# since-recovered incident -- index 3 of 6, not the last point. The
# motivating case for autoscale="robust": tightly fit, the single spike
# forces a domain wide enough that the other five points collapse to a
# sub-pixel line.
_SPIKE_LIFT = [1.0, 1.05, 0.95, 300.0, 1.02, 0.98]
_SPIKE_NON_OUTLIER_INDICES = [0, 1, 2, 4, 5]


def spike_table(**kwargs):
    raw = {"metric": ["A"], "lift": [_SPIKE_LIFT]}
    return CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", ref=1.0, **kwargs
    )


def test_motivating_table_renders_end_to_end(data):
    out = resolve(
        motivating_table(data).sparkline(
            "Trend", value="lift", ci=("lift_lb", "lift_ub"), x="date", ref=0.0
        )
    )
    frame = nw.from_native(out.frame)
    assert len(frame.rows()) == 5  # 4 data rows + 1 shared axis row
    plots = frame["Trend"].to_list()
    data_rows = [p for i, p in enumerate(plots) if i not in out.axis_rows]
    assert len(data_rows) == 4
    assert all("<svg" in p and "<polyline" in p for p in data_rows)


def test_row_scale_gives_each_metric_its_own_y_domain_while_nest_shares_one(data):
    out = resolve(
        motivating_table(data).sparkline(
            "Trend", value="lift", ci=("lift_lb", "lift_ub"), x="date", ref=0.0, scale="row"
        )
    )
    plots = nw.from_native(out.frame)["Trend"].to_list()
    revenue_b, revenue_c, latency_b, latency_c = (_ref_line_y(plots[i]) for i in range(4))
    # Nested variants of the same metric share a domain...
    assert revenue_b == pytest.approx(revenue_c)
    assert latency_b == pytest.approx(latency_c)
    # ...but distinct metrics get distinct, visibly different domains.
    assert revenue_b != pytest.approx(latency_b)


def test_table_scale_gives_all_rows_one_y_domain(data):
    out = resolve(
        motivating_table(data).sparkline(
            "Trend", value="lift", ci=("lift_lb", "lift_ub"), x="date", ref=0.0, scale="table"
        )
    )
    plots = nw.from_native(out.frame)["Trend"].to_list()
    ref_ys = [_ref_line_y(plots[i]) for i in range(4)]
    assert ref_ys[0] == pytest.approx(ref_ys[1])
    assert ref_ys[0] == pytest.approx(ref_ys[2])
    assert ref_ys[0] == pytest.approx(ref_ys[3])


@pytest.mark.parametrize("scale", ["row", "table", "row_group", "split_column"])
def test_exactly_one_axis_row_regardless_of_scale(data, scale):
    # Unlike Forest, x is always shared table-wide, so every scale setting
    # schedules exactly one footer row for the whole column.
    out = resolve(
        motivating_table(data).sparkline(
            "Trend", value="lift", ci=("lift_lb", "lift_ub"), x="date", scale=scale
        )
    )
    assert len(out.axis_rows) == 1


def test_exactly_one_axis_row_with_split_columns():
    # footer() fires once per split value at the SAME triggering row --
    # "one axis row" means one row, not one footer() call.
    raw = {
        "metric": ["Revenue", "Revenue"],
        "method": ["OLS", "DiD"],
        "lift": [[1.0, 2.0], [3.0, 4.0]],
    }
    table = CoefTable(pl.DataFrame(raw), rows="metric", split_columns="method").sparkline(
        "Trend", value="lift"
    )
    out = resolve(table)
    assert len(out.axis_rows) == 1
    assert set(out.spanners) == {"OLS", "DiD"}


def test_sparkline_output_columns_join_plot_columns(data):
    out = resolve(motivating_table(data).sparkline("Trend", value="lift", x="date"))
    assert out.plot_columns == ["Trend"]


def test_straddling_last_interval_is_inconclusive():
    out = resolve(role_table())
    plots = nw.from_native(out.frame)["Trend"].to_list()
    assert DEFAULT.color("inconclusive") in plots[1]


def test_clearly_favorable_last_interval_renders_favorable():
    out = resolve(role_table())
    plots = nw.from_native(out.frame)["Trend"].to_list()
    assert DEFAULT.color("favorable") in plots[0]


def test_lower_is_better_flips_the_same_row_to_unfavorable():
    out = resolve(role_table(direction="lower_is_better"))
    plots = nw.from_native(out.frame)["Trend"].to_list()
    assert DEFAULT.color("unfavorable") in plots[0]


def test_gt_html_contains_expected_svg_count():
    raw = {"metric": ["A", "B", "C"], "lift": [[1.0, 2.0], [3.0, 1.0], [0.5, 0.8]]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline("Trend", value="lift")
    html = table.gt().as_raw_html()
    assert html.count("<svg") == 4  # 3 data rows + 1 shared axis row


def test_sparkline_height_defaults_to_thirty_without_any_estimate():
    raw = {"metric": ["A"], "lift": [[1.0, 2.0]]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline("Trend", value="lift")
    html = table.gt().as_raw_html()
    assert 'height="30"' in html


def test_sparkline_height_uses_tallest_estimate_ci_layout_on_the_table():
    raw = {
        "metric": ["A"],
        "mean1": [1.0],
        "lb1": [0.5],
        "ub1": [1.5],
        "mean2": [2.0],
        "lb2": [1.5],
        "ub2": [2.5],
        "lift": [[1.0, 2.0]],
    }
    table = (
        CoefTable(pl.DataFrame(raw), rows="metric")
        .estimate("Inline", "mean1", ci=("lb1", "ub1"), ci_style=CIStyle(layout="inline"))
        .estimate("Stacked", "mean2", ci=("lb2", "ub2"))  # default layout is "stacked" -> 48
        .sparkline("Trend", value="lift")
    )
    html = table.gt().as_raw_html()
    assert 'height="48"' in html


def test_forest_still_sizes_to_its_own_bound_estimate_not_the_table_wide_tallest():
    # The more-specific case _plot_height must keep working: a Forest sizes
    # against ITS bound estimate, even when a taller one exists elsewhere.
    raw = {
        "metric": ["A"],
        "mean1": [1.0],
        "lb1": [0.5],
        "ub1": [1.5],
        "mean2": [2.0],
        "lb2": [1.5],
        "ub2": [2.5],
    }
    table = (
        CoefTable(pl.DataFrame(raw), rows="metric")
        .estimate("Inline", "mean1", ci=("lb1", "ub1"), ci_style=CIStyle(layout="inline"))
        .estimate("Stacked", "mean2", ci=("lb2", "ub2"))
        .forest("Plot", of="Inline")
    )
    html = table.gt().as_raw_html()
    assert 'height="34"' in html
    assert 'height="48"' not in html


def test_sparkline_height_explicit_override_wins():
    raw = {"metric": ["A"], "lift": [[1.0, 2.0]]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline("Trend", value="lift", height=99)
    html = table.gt().as_raw_html()
    assert 'height="99"' in html


def test_companion_frame_front_door_renders_end_to_end():
    """Exercises Scan.nest_keys: the identity (row, nest, split) must match
    what the companion frame groups by, or this row wouldn't resolve at all.
    """
    raw = {"metric": ["Revenue", "Latency"], "variant": ["B", "B"]}
    companion = pd.DataFrame(
        {
            "metric": ["Revenue", "Revenue", "Latency", "Latency"],
            "variant": ["B", "B", "B", "B"],
            "day": [0, 1, 0, 1],
            "lift": [1.0, 2.0, 10.0, 20.0],
        }
    )
    table = CoefTable(pl.DataFrame(raw), rows="metric", nest="variant").sparkline(
        "Trend", value="lift", x="day", data=companion
    )
    out = resolve(table)
    plots = nw.from_native(out.frame)["Trend"].to_list()
    data_rows = [p for i, p in enumerate(plots) if i not in out.axis_rows]
    assert len(data_rows) == 2
    assert all("<svg" in p and "<polyline" in p for p in data_rows)


def test_companion_frame_null_nest_key_resolves_not_blank():
    """A null nest key on the main frame carries `None` (polars); the
    companion frame's null cell in the same key column surfaces as pandas's
    `nan`. The two only match once both are normalised to `None` -- the main
    frame here is deliberately polars, not pandas, so its `None` cannot
    coincidentally share pandas's cached nan singleton and mask a broken
    normalisation.
    """
    raw = pl.DataFrame({"metric": ["A", "A"], "variant": ["X", None]})
    companion = pd.DataFrame(
        {
            "metric": ["A", "A", "A", "A"],
            "variant": ["X", "X", None, None],
            "day": [0, 1, 0, 1],
            "lift": [1.0, 2.0, 10.0, 20.0],
        }
    )
    table = CoefTable(raw, rows="metric", nest="variant").sparkline(
        "Trend", value="lift", x="day", data=companion
    )
    out = resolve(table)
    plots = nw.from_native(out.frame)["Trend"].to_list()
    data_rows = [p for i, p in enumerate(plots) if i not in out.axis_rows]
    assert len(data_rows) == 2
    assert all("<polyline" in p for p in data_rows)


def test_companion_frame_missing_identity_renders_blank_cell():
    raw = {"metric": ["Revenue", "Ghost"]}
    companion = pd.DataFrame({"metric": ["Revenue", "Revenue"], "lift": [1.0, 2.0]})
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", data=companion
    )
    out = resolve(table)
    plots = nw.from_native(out.frame)["Trend"].to_list()
    assert "<svg" in plots[0]
    assert plots[1] == ""


def test_companion_frame_missing_column_raises_column_not_found_error():
    raw = {"metric": ["Revenue"]}
    companion = pd.DataFrame({"metric": ["Revenue", "Revenue"], "lift": [1.0, 2.0]})
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="typo", data=companion
    )
    with pytest.raises(ColumnNotFoundError, match="typo"):
        resolve(table)


def test_companion_frame_missing_layout_key_raises_column_not_found_error():
    raw = {"metric": ["Revenue"]}
    companion = pd.DataFrame({"wrong_key": ["Revenue", "Revenue"], "lift": [1.0, 2.0]})
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", data=companion
    )
    with pytest.raises(ColumnNotFoundError, match="metric"):
        resolve(table)


def test_empty_series_renders_a_blank_cell():
    raw = {"metric": ["A", "B"], "lift": [[1.0, 2.0], []]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline("Trend", value="lift")
    out = resolve(table)
    plots = nw.from_native(out.frame)["Trend"].to_list()
    assert plots[1] == ""


def test_trailing_gap_colours_from_the_last_valid_point_not_the_gap():
    # A raw index -1 lookup would find the missing point and blank the
    # cell; the endpoint sparkline_bar draws terminates at the last
    # *valid* point, so colour resolution must match that, not the gap.
    raw = {
        "metric": ["A"],
        "lift": [[1.0, 5.0, None]],
        "lift_lb": [[0.5, 3.0, None]],
        "lift_ub": [[1.5, 7.0, None]],
    }
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", ci=("lift_lb", "lift_ub"), ref=0.0
    )
    out = resolve(table)
    plots = nw.from_native(out.frame)["Trend"].to_list()
    assert plots[0] != ""
    assert DEFAULT.color("favorable") in plots[0]


def test_all_missing_series_renders_a_blank_cell():
    raw = {"metric": ["A"], "lift": [[None, None]]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline("Trend", value="lift")
    out = resolve(table)
    plots = nw.from_native(out.frame)["Trend"].to_list()
    assert plots[0] == ""


def test_ylim_override_wins_over_scale():
    raw = {"metric": ["A", "B"], "lift": [[1.0, 2.0], [100.0, 200.0]]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", scale="row", ylim=(-5.0, 5.0), ref=0.0
    )
    out = resolve(table)
    plots = nw.from_native(out.frame)["Trend"].to_list()
    # Wildly different magnitudes would give distinct row-scale domains, but
    # the explicit ylim forces both onto the same one.
    assert _ref_line_y(plots[0]) == pytest.approx(_ref_line_y(plots[1]))


@pytest.mark.parametrize(
    ("domain", "max_domain", "expected"),
    [
        # Exceeds the ceiling on both sides -- both bounds narrow.
        ((-604.0, 904.0), 20.0, (-20.0, 20.0)),
        # Already narrower than the ceiling -- left untouched.
        ((-0.08, 1.08), 20.0, (-0.08, 1.08)),
        # Only the high bound exceeds the ceiling; the low bound, already
        # tighter than it, is left exactly as it was rather than pulled up.
        ((-0.8, 10.8), 5.0, (-0.8, 5.0)),
    ],
)
def test_clamp_domain_narrows_only_the_bounds_that_exceed_the_ceiling(
    domain, max_domain, expected
):
    assert _clamp_domain(domain, ref=0.0, max_domain=max_domain) == expected


def test_clamp_domain_never_widens_regardless_of_ceiling_size():
    for max_domain in (0.01, 1.0, 5.0, 20.0, 1000.0):
        low, high = _clamp_domain((-3.0, 4.0), ref=0.0, max_domain=max_domain)
        assert high - low <= 7.0


def test_bucket_domain_override_wins_even_when_max_domain_is_set():
    assert _bucket_domain([100.0], 0.0, override=(-5.0, 5.0), max_domain=1.0) == (-5.0, 5.0)


def test_bucket_domain_applies_max_domain_only_on_the_auto_path():
    assert _bucket_domain([-500.0, 800.0], 0.0, override=None, max_domain=20.0) == (-20.0, 20.0)


def test_bucket_domain_without_max_domain_matches_plain_pad_domain():
    vals = [-500.0, 800.0]
    assert _bucket_domain(vals, 0.0, override=None, max_domain=None) == _pad_domain(vals, 0.0)


def test_max_ylim_clamps_the_noisy_row_but_leaves_the_precise_row_unchanged():
    raw = {
        "metric": ["Precise", "Noisy"],
        "lift": [[0.5, 1.0, 0.8], [-500.0, 10.0, 800.0]],
    }

    def build(max_ylim):
        kwargs = {} if max_ylim is None else {"max_ylim": max_ylim}
        return CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
            "Trend", value="lift", ref=0.0, scale="row", **kwargs
        )

    plain = nw.from_native(resolve(build(None)).frame)["Trend"].to_list()
    clamped = nw.from_native(resolve(build(20.0)).frame)["Trend"].to_list()

    # Precise row: its own natural domain is already far tighter than the
    # ref +/- 20 ceiling, so max_ylim changes nothing about its render.
    assert clamped[0] == plain[0]
    # Noisy row: its natural domain (padded from -500..800) blows past the
    # ceiling, so max_ylim narrows it -- the series now clips in both
    # directions where it did not clip at all before.
    assert _cap_edges(plain[1]) == 0
    assert _cap_edges(clamped[1]) == 2


def test_max_ylim_leaves_a_domain_already_tighter_than_the_ceiling_alone():
    raw = {"metric": ["A"], "lift": [[0.5, 1.0, 0.8]]}

    def build(max_ylim):
        kwargs = {} if max_ylim is None else {"max_ylim": max_ylim}
        return CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
            "Trend", value="lift", ref=0.0, **kwargs
        )

    plain = nw.from_native(resolve(build(None)).frame)["Trend"].to_list()
    clamped = nw.from_native(resolve(build(50.0)).frame)["Trend"].to_list()
    assert clamped == plain


def test_ylim_wins_outright_over_max_ylim_when_both_are_set():
    raw = {"metric": ["A"], "lift": [[-500.0, 10.0, 800.0]]}

    def build(max_ylim):
        kwargs = {} if max_ylim is None else {"max_ylim": max_ylim}
        return CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
            "Trend", value="lift", ref=0.0, ylim=(-1000.0, 1000.0), **kwargs
        )

    # max_ylim=1.0 would clamp to (-1, 1) if it won -- a drastic visual
    # change from the explicit (-1000, 1000) ylim. It must not: ylim=
    # is an absolute override and wins outright, exactly as it already does
    # over scale=.
    without = nw.from_native(resolve(build(None)).frame)["Trend"].to_list()
    with_ceiling = nw.from_native(resolve(build(1.0)).frame)["Trend"].to_list()
    assert with_ceiling == without


def test_max_ylim_composes_with_scale_table_instead_of_overriding_it():
    raw = {
        "metric": ["Precise", "Noisy"],
        "lift": [[0.5, 1.0, 0.8], [-500.0, 10.0, 800.0]],
    }

    def build(max_ylim):
        kwargs = {} if max_ylim is None else {"max_ylim": max_ylim}
        return CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
            "Trend", value="lift", ref=0.0, scale="table", **kwargs
        )

    plain = nw.from_native(resolve(build(None)).frame)["Trend"].to_list()
    clamped = nw.from_native(resolve(build(20.0)).frame)["Trend"].to_list()

    # scale="table" keeps both rows on one shared domain, with or without a
    # ceiling -- max_ylim narrows that shared domain in place; it does not
    # fall back to clamping each row's own domain independently.
    assert _ref_line_y(plain[0]) == pytest.approx(_ref_line_y(plain[1]))
    assert _ref_line_y(clamped[0]) == pytest.approx(_ref_line_y(clamped[1]))
    assert abs(_ref_line_y(plain[0]) - _ref_line_y(clamped[0])) > 0.5


def test_robust_domain_short_series_falls_back_to_pad_domain():
    values = [1.0, 2.0, 1.5]  # fewer than 4 pooled values -- no meaningful quartiles
    assert _robust_domain(values, 0.0) == _pad_domain(values, 0.0)


def test_robust_domain_degenerate_spread_falls_back_to_pad_domain():
    values = [2.0, 2.0, 2.0, 2.0, 2.0]  # zero IQR, e.g. all-identical values
    assert _robust_domain(values, 0.0) == _pad_domain(values, 0.0)


def test_robust_domain_excludes_a_spike_the_fence_flags_as_an_outlier():
    tight = _pad_domain(_SPIKE_LIFT, 1.0)
    robust = _robust_domain(_SPIKE_LIFT, 1.0)
    # _pad_domain, forced to contain every value, stretches to fit the
    # spike; the fence discounts it entirely, so it lands outside the
    # robust domain, which stays two orders of magnitude tighter.
    assert not (robust[0] <= 300.0 <= robust[1])
    assert (robust[1] - robust[0]) < (tight[1] - tight[0]) / 100


def test_robust_domain_has_no_anchor_override_and_cannot_be_bypassed():
    # The anchor-forcing parameter this test used to cover is gone
    # entirely -- _robust_domain now takes exactly (values, ref). There
    # is no longer any way to force an excluded outlier back into the
    # domain; this locks in the fix, so silently reintroducing an
    # anchors kwarg -- even an optional, default-off one -- would
    # resurrect the exact bug this task fixes rather than pass silently.
    stale_kwargs = {"anchors": [300.0]}
    with pytest.raises(TypeError):
        _robust_domain(_SPIKE_LIFT, 1.0, **stale_kwargs)


def test_robust_domain_forces_ref_into_the_domain():
    values = [10.0, 10.5, 9.5, 10.2, 9.8, 10.1]
    low, high = _robust_domain(values, 0.0)
    assert low <= 0.0 <= high


def test_pad_domain_ref_none_excludes_zero_when_data_is_far_from_it():
    low, high = _pad_domain([282.3, 378.2], ref=None)
    assert (low, high) == pytest.approx(
        (282.3 - (378.2 - 282.3) * 0.08, 378.2 + (378.2 - 282.3) * 0.08)
    )
    assert not (low <= 0.0 <= high)


def test_pad_domain_ref_zero_still_forces_inclusion():
    low, high = _pad_domain([282.3, 378.2], ref=0.0)
    assert low <= 0.0 <= high


def test_pad_domain_ref_none_empty_values_falls_back_to_unit_domain():
    assert _pad_domain([], ref=None) == (-1.0, 1.0)


def test_pad_domain_ref_none_single_value_pads_by_one():
    assert _pad_domain([5.0], ref=None) == (4.0, 6.0)


def test_pad_domain_symmetric_requires_ref():
    with pytest.raises(ValueError):
        _pad_domain([1.0, 2.0], ref=None, symmetric=True)


def test_robust_domain_ref_none_fences_outliers_and_excludes_zero():
    values = [282.3, 378.2, 300.1, 350.0, 900.0]  # 900.0 is the outlier
    low, high = _robust_domain(values, ref=None)
    assert not (900.0 <= high)
    assert not (low <= 0.0 <= high)


def test_clamp_domain_requires_ref():
    with pytest.raises(ValueError):
        _clamp_domain((-3.0, 4.0), ref=None, max_domain=1.0)


def _stub_cell(*, direction="higher_is_better", color_rule=None):
    return Cell(
        prepared=None,  # ty: ignore[invalid-argument-type]
        index=0,
        row_key=None,
        group=None,
        split=None,
        direction=direction,
        color_rule=color_rule,
        theme=DEFAULT,
    )


def test_resolve_role_ref_none_without_color_rule_is_neutral():
    ctx = _stub_cell()
    assert _resolve_role(ctx, 1.0, 0.5, 1.5, None) == "neutral"


def test_resolve_role_ref_none_forwards_to_color_rule_override():
    seen_refs = []

    def rule(value, low, high, ref):
        seen_refs.append(ref)
        return "unfavorable"

    ctx = _stub_cell(color_rule=rule)
    assert _resolve_role(ctx, 1.0, 0.5, 1.5, None) == "unfavorable"
    assert seen_refs == [None]


# Absolute-valued series, two row groups, no value anywhere near 0 -- the
# motivating case for ref=None: with a forced-zero domain this data would
# be compressed into a sliver of each cell.
_ABS_GROUP_RAW = {
    "area": ["Core", "Core", "Ops", "Ops"],
    "metric": ["Revenue", "Users", "Latency", "Errors"],
    "value": [
        [282.3, 300.1, 320.0],
        [350.0, 360.0, 378.2],
        [900.0, 910.0, 920.0],
        [950.0, 960.0, 970.0],
    ],
}


def test_sparkline_ref_none_end_to_end_draws_no_line_and_colours_neutral():
    ref_none = CoefTable(pl.DataFrame(_ABS_GROUP_RAW), rows="metric", groups="area").sparkline(
        "Trend", value="value", ref=None, scale="row_group", show_axis=False
    )
    ref_zero = CoefTable(pl.DataFrame(_ABS_GROUP_RAW), rows="metric", groups="area").sparkline(
        "Trend", value="value", ref=0.0, scale="row_group", show_axis=False
    )
    none_plots = nw.from_native(resolve(ref_none).frame)["Trend"].to_list()
    zero_plots = nw.from_native(resolve(ref_zero).frame)["Trend"].to_list()

    # ref=None: no dashed reference line anywhere, and every cell resolves
    # neutral -- "favorable" has no meaning without a reference.
    assert all("stroke-dasharray" not in p for p in none_plots)
    assert all(DEFAULT.color("neutral") in p for p in none_plots)
    assert all(DEFAULT.color("favorable") not in p for p in none_plots)
    assert all(DEFAULT.color("unfavorable") not in p for p in none_plots)

    # ref=0.0 still forces the domain to include 0 and draws the line --
    # unaffected by the widened type.
    assert all("stroke-dasharray" in p for p in zero_plots)


def test_sparkline_ref_none_color_rule_override_still_resolves():
    def rule(value, low, high, ref):
        return "unfavorable"

    table = CoefTable(
        pl.DataFrame(_ABS_GROUP_RAW), rows="metric", groups="area", color_rule=rule
    ).sparkline("Trend", value="value", ref=None, show_axis=False)
    plots = nw.from_native(resolve(table).frame)["Trend"].to_list()
    assert all(DEFAULT.color("unfavorable") in p for p in plots)


def test_sparkline_max_ylim_with_ref_none_raises_spec_error():
    with pytest.raises(SpecError, match="Trend"):
        CoefTable(pl.DataFrame(_ABS_GROUP_RAW), rows="metric", groups="area").sparkline(
            "Trend", value="value", ref=None, max_ylim=20.0
        )


def _strip_stroke_color(svg: str) -> str:
    """Normalize a rendered SVG's stroke colour so geometry-only diffs are comparable."""
    return re.sub(r'stroke="#[0-9A-Fa-f]{6}"', 'stroke="X"', svg)


def test_sparkline_show_ref_false_domain_matches_ref_none_domain():
    # show_ref=False routes the same ref=None domain path as Task 1 --
    # geometry (everything but colour) must be identical to ref=None.
    show_ref_false = CoefTable(
        pl.DataFrame(_ABS_GROUP_RAW), rows="metric", groups="area"
    ).sparkline(
        "Trend", value="value", ref=0.0, show_ref=False, scale="row_group", show_axis=False
    )
    ref_none = CoefTable(pl.DataFrame(_ABS_GROUP_RAW), rows="metric", groups="area").sparkline(
        "Trend", value="value", ref=None, scale="row_group", show_axis=False
    )
    show_ref_false_plots = nw.from_native(resolve(show_ref_false).frame)["Trend"].to_list()
    ref_none_plots = nw.from_native(resolve(ref_none).frame)["Trend"].to_list()
    assert [_strip_stroke_color(p) for p in show_ref_false_plots] == [
        _strip_stroke_color(p) for p in ref_none_plots
    ]


def test_sparkline_show_ref_false_still_colours_against_ref():
    # Unlike ref=None, show_ref=False keeps ref as a colour anchor: "Up"'s
    # last point sits clearly above ref=0.0, so it still resolves
    # favorable, not neutral.
    table = CoefTable(pl.DataFrame(ROLE_RAW), rows="metric").sparkline(
        "Trend", value="lift", ci=("lift_lb", "lift_ub"), ref=0.0, show_ref=False
    )
    plots = nw.from_native(resolve(table).frame)["Trend"].to_list()
    assert DEFAULT.color("favorable") in plots[0]
    assert DEFAULT.color("neutral") not in plots[0]


def test_sparkline_show_ref_true_default_is_unchanged():
    explicit = CoefTable(pl.DataFrame(ROLE_RAW), rows="metric").sparkline(
        "Trend", value="lift", ci=("lift_lb", "lift_ub"), ref=0.0, show_ref=True
    )
    default = role_table()
    assert (
        nw.from_native(resolve(explicit).frame)["Trend"].to_list()
        == nw.from_native(resolve(default).frame)["Trend"].to_list()
    )


def test_sparkline_show_ref_false_is_a_noop_when_ref_is_none():
    with_show_ref_false = CoefTable(
        pl.DataFrame(_ABS_GROUP_RAW), rows="metric", groups="area"
    ).sparkline("Trend", value="value", ref=None, show_ref=False, show_axis=False)
    without = CoefTable(pl.DataFrame(_ABS_GROUP_RAW), rows="metric", groups="area").sparkline(
        "Trend", value="value", ref=None, show_ref=True, show_axis=False
    )
    assert (
        nw.from_native(resolve(with_show_ref_false).frame)["Trend"].to_list()
        == nw.from_native(resolve(without).frame)["Trend"].to_list()
    )


def test_sparkline_max_ylim_with_show_ref_false_raises_the_same_spec_error_as_ref_none():
    with pytest.raises(SpecError, match="Trend") as none_exc:
        CoefTable(pl.DataFrame(_ABS_GROUP_RAW), rows="metric", groups="area").sparkline(
            "Trend", value="value", ref=None, max_ylim=20.0
        )
    with pytest.raises(SpecError, match="Trend") as show_ref_exc:
        CoefTable(pl.DataFrame(_ABS_GROUP_RAW), rows="metric", groups="area").sparkline(
            "Trend", value="value", ref=0.0, show_ref=False, max_ylim=20.0
        )
    assert str(none_exc.value) == str(show_ref_exc.value)


def test_bucket_domain_tight_is_the_default_and_matches_pad_domain():
    plain = _bucket_domain(_SPIKE_LIFT, 1.0, override=None, max_domain=None)
    assert plain == _pad_domain(_SPIKE_LIFT, 1.0)


def test_bucket_domain_robust_then_max_domain_clamps_further():
    robust_only = _bucket_domain(
        _SPIKE_LIFT, 1.0, override=None, max_domain=None, autoscale="robust"
    )
    robust_clamped = _bucket_domain(
        _SPIKE_LIFT, 1.0, override=None, max_domain=0.03, autoscale="robust"
    )
    assert robust_clamped != robust_only
    assert robust_clamped == _clamp_domain(robust_only, 1.0, 0.03)


def test_autoscale_default_is_tight_and_unchanged():
    # No autoscale= at all must render byte-for-byte identically to
    # explicitly requesting "tight" -- the default did not change meaning.
    default = nw.from_native(resolve(spike_table()).frame)["Trend"].to_list()
    tight = nw.from_native(resolve(spike_table(autoscale="tight")).frame)["Trend"].to_list()
    assert default == tight


def test_autoscale_robust_keeps_the_bulk_of_a_spiking_series_legible():
    tight_plot = nw.from_native(resolve(spike_table()).frame)["Trend"].to_list()[0]
    robust_out = resolve(spike_table(autoscale="robust"))
    robust_plot = nw.from_native(robust_out.frame)["Trend"].to_list()[0]

    def extent(svg):
        ys = _polyline_ys(svg)
        picked = [ys[i] for i in _SPIKE_NON_OUTLIER_INDICES]
        return max(picked) - min(picked)

    # Default (tight): the domain stretches to fit the spike (~350 units),
    # so the other five points collapse to a sub-pixel line.
    assert extent(tight_plot) < 1.0
    # autoscale="robust": the fence discounts the spike, so those same
    # five points now span most of the plot's 24px usable height.
    assert extent(robust_plot) > 10.0

    # The spike is still drawn -- clipped to the domain edge -- and raises
    # a clip-cap bracket under the robust fit; not under tight, which is
    # by construction wide enough to contain every point unclipped.
    assert _cap_edges(tight_plot) == 0
    assert _cap_edges(robust_plot) == 1


def test_autoscale_robust_single_row_last_point_is_the_outlier_clips_and_flags():
    raw = {"metric": ["A"], "lift": [[1.0, 1.05, 0.95, 300.0]]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", ref=1.0, autoscale="robust"
    )
    plot = nw.from_native(resolve(table).frame)["Trend"].to_list()[0]
    # 300.0 is both the IQR fence's only excluded outlier and this row's
    # own last point. There is no anchor mechanism left to protect it:
    # the line still draws -- clipped to the domain's edge, not hidden --
    # and raises exactly one clip-cap bracket, the same clip-then-flag
    # mechanism a ylim=/max_ylim= overflow already uses.
    assert "<polyline" in plot
    assert _cap_edges(plot) == 1


def test_autoscale_robust_keeps_the_bulk_legible_when_the_outlier_is_the_last_point():
    # The test above deliberately keeps its spike off the last index, so
    # it passes no matter how a last-plotted outlier is handled. This is
    # the case the old anchor-forcing design got wrong: the outlier IS
    # the row's own last point -- the value the anchor union always
    # forced back into the domain, silently collapsing "robust" to the
    # same domain as "tight" whenever it mattered most. With the anchor
    # gone, this case now gets the same legibility win.
    raw = {"metric": ["A"], "lift": [[1.0, 1.05, 0.95, 1.02, 0.98, 300.0]]}
    tight_table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", ref=1.0
    )
    robust_table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", ref=1.0, autoscale="robust"
    )
    tight_plot = nw.from_native(resolve(tight_table).frame)["Trend"].to_list()[0]
    robust_plot = nw.from_native(resolve(robust_table).frame)["Trend"].to_list()[0]

    def extent(svg):
        ys = _polyline_ys(svg)[:5]  # every point except the spike itself
        return max(ys) - min(ys)

    assert extent(tight_plot) < 1.0
    assert extent(robust_plot) > 10.0
    assert _cap_edges(tight_plot) == 0
    assert _cap_edges(robust_plot) == 1


def test_autoscale_robust_multi_row_bucket_narrows_around_the_bulk_and_flags_the_outlier():
    raw = {
        "metric": ["Clean", "Spiking"],
        "lift": [[1.0, 1.05, 0.95, 1.02], [1.0, 1.05, 0.95, 300.0]],
    }
    tight_table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", ref=1.0, scale="table"
    )
    robust_table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", ref=1.0, scale="table", autoscale="robust"
    )
    tight_plots = nw.from_native(resolve(tight_table).frame)["Trend"].to_list()
    robust_plots = nw.from_native(resolve(robust_table).frame)["Trend"].to_list()

    def extent(svg):
        ys = _polyline_ys(svg)
        return max(ys) - min(ys)

    # Both rows share one scale="table" bucket, so under "tight" -- forced
    # to fit "Spiking"'s 300.0 -- "Clean"'s own tightly-clustered points
    # collapse to a sub-pixel line even though it has no outlier of its
    # own.
    assert extent(tight_plots[0]) < 1.0
    # With the anchor-forcing gone, the shared robust fence discounts
    # 300.0 and narrows around the bulk of BOTH rows' data -- "Clean" now
    # visibly benefits from a domain it never had to fight to get.
    assert extent(robust_plots[0]) > 10.0
    # "Spiking"'s own last point is the excluded outlier: it clips to the
    # narrower shared domain's edge and raises a clip-cap bracket, same
    # as the single-row case.
    assert _cap_edges(robust_plots[1]) == 1
    # "Clean" has no outlier of its own, and the narrower domain still
    # comfortably contains its whole series, so it raises no flag.
    assert _cap_edges(robust_plots[0]) == 0
    # Still exactly one resolved domain for the bucket: both rows'
    # reference lines land at the same pixel.
    assert _ref_line_y(robust_plots[0]) == pytest.approx(_ref_line_y(robust_plots[1]))


def test_autoscale_robust_multi_row_bucket_with_an_empty_sibling_still_resolves():
    # The anchor-tracking loop this test used to guard against crashing
    # on ("_last_point returns None for an empty series") is gone
    # entirely -- there is nothing left in prepare() that inspects a
    # row's last point at all. What remains worth covering: pooling an
    # empty sibling into a shared bucket must still resolve cleanly
    # under autoscale="robust".
    raw = {"metric": ["Empty", "Spiking"], "lift": [[], [1.0, 1.05, 0.95, 300.0]]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", ref=1.0, scale="table", autoscale="robust"
    )
    plots = nw.from_native(resolve(table).frame)["Trend"].to_list()
    # The empty row contributes nothing to the bucket and renders blank,
    # as it always has.
    assert plots[0] == ""
    # "Spiking" is still the bucket's sole outlier: it clips to the
    # fitted domain's edge and raises a clip-cap bracket, exactly as it
    # would with no empty sibling present.
    assert _cap_edges(plots[1]) == 1


def test_autoscale_robust_composes_with_max_ylim():
    robust_only = nw.from_native(resolve(spike_table(autoscale="robust")).frame)[
        "Trend"
    ].to_list()[0]
    robust_clamped_table = spike_table(autoscale="robust", max_ylim=0.03)
    robust_clamped = nw.from_native(resolve(robust_clamped_table).frame)["Trend"].to_list()[0]
    # The robust fit alone already excludes the spike (one clip-cap
    # bracket). A tighter max_ylim ceiling then narrows that further
    # still, clipping two more of the surviving inlier points -- one high,
    # one low -- each opening its own separate bracket since neither is
    # adjacent to the spike's, proving the ceiling runs as a second pass
    # after the robust fit, not instead of it.
    assert _cap_edges(robust_only) == 1
    assert _cap_edges(robust_clamped) == 3


def test_autoscale_robust_clip_does_not_change_the_rendered_colour():
    # Domain choice must never change which colour a row gets -- only
    # how much of the plot area is spent on which part of the series.
    # cell() resolves colour from the row's raw last point (_last_point),
    # never from state.domains[key] -- proven here, not just reasoned
    # about: same data, same colour, under both "tight" (never clips)
    # and "robust" (clips this exact point).
    raw = {
        "metric": ["A"],
        "lift": [[1.0, 1.05, 0.95, 300.0]],
        "lift_lb": [[0.9, 0.95, 0.85, 299.9]],
        "lift_ub": [[1.1, 1.15, 1.05, 300.1]],
    }
    tight_table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", ci=("lift_lb", "lift_ub"), ref=0.0
    )
    robust_table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", ci=("lift_lb", "lift_ub"), ref=0.0, autoscale="robust"
    )
    tight_plot = nw.from_native(resolve(tight_table).frame)["Trend"].to_list()[0]
    robust_plot = nw.from_native(resolve(robust_table).frame)["Trend"].to_list()[0]

    # The last point's own interval (299.9, 300.1) sits far above
    # ref=0.0, so the row resolves "favorable" -- identically under both
    # domains.
    assert DEFAULT.color("favorable") in tight_plot
    assert DEFAULT.color("favorable") in robust_plot

    # "tight" is, by construction, wide enough to contain every point --
    # its one polygon is only the CI ribbon fill, and it raises no
    # clip-cap. "robust" fences the same last point out of the domain, so
    # it clips (adding a ghost trace and a clipped ribbon polygon) and
    # raises a clip-cap bracket -- proving the colour match above isn't
    # just because nothing actually clipped under "robust".
    assert robust_plot.count("<polygon") > tight_plot.count("<polygon")
    assert _cap_edges(tight_plot) == 0
    assert _cap_edges(robust_plot) == 1


def test_show_axis_false_emits_no_footer_row():
    raw = {"metric": ["A"], "lift": [[1.0, 2.0]]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", show_axis=False
    )
    out = resolve(table)
    assert out.axis_rows == []


def test_clip_indicators_default_on_for_a_ylim_clipped_series():
    raw = {"metric": ["A"], "lift": [[1.0, 300.0, 1.0]]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", ylim=(0.0, 20.0)
    )
    out = resolve(table)
    plots = nw.from_native(out.frame)["Trend"].to_list()
    data_cell = next(p for i, p in enumerate(plots) if i not in out.axis_rows)
    assert _cap_edges(data_cell) == 1


def test_clip_indicators_false_suppresses_the_flag():
    raw = {"metric": ["A"], "lift": [[1.0, 300.0, 1.0]]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", ylim=(0.0, 20.0), show_clip_indicators=False
    )
    out = resolve(table)
    plots = nw.from_native(out.frame)["Trend"].to_list()
    data_cell = next(p for i, p in enumerate(plots) if i not in out.axis_rows)
    # The cap bracket disappears...
    assert _cap_edges(data_cell) == 0
    # ...but the underlying boundary clipping and ghost trace are
    # unconditional -- turning the indicator off never reintroduces the
    # off-canvas coordinate bug, and never hides the true trajectory.
    assert "<polyline" in data_cell
    assert 'stroke-opacity="0.35"' in data_cell


def test_show_endpoint_defaults_to_false():
    raw = {"metric": ["A"], "lift": [[1.0, 2.0]]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline("Trend", value="lift")
    out = resolve(table)
    plots = nw.from_native(out.frame)["Trend"].to_list()
    data_cell = next(p for i, p in enumerate(plots) if i not in out.axis_rows)
    assert "<text" not in data_cell


def test_temporal_x_produces_calendar_axis_labels():
    dates = [dt.date(2024, 1, 1), dt.date(2024, 2, 1), dt.date(2024, 3, 1)]
    raw = {"metric": ["A"], "lift": [[1.0, 2.0, 3.0]], "date": [dates]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", x="date", axis_fmt=DateAxis()
    )
    out = resolve(table)
    footer = nw.from_native(out.frame)["Trend"].to_list()[out.axis_rows[0]]
    assert any(month in footer for month in ("Jan", "Feb", "Mar"))


def test_temporal_x_defaults_to_calendar_axis_labels_without_explicit_axis_fmt():
    dates = [dt.date(2024, 1, 1), dt.date(2024, 2, 1), dt.date(2024, 3, 1)]
    raw = {"metric": ["A"], "lift": [[1.0, 2.0, 3.0]], "date": [dates]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline("Trend", value="lift", x="date")
    out = resolve(table)
    footer = nw.from_native(out.frame)["Trend"].to_list()[out.axis_rows[0]]
    assert any(month in footer for month in ("Jan", "Feb", "Mar"))
    assert "1704" not in footer


def test_sparkline_ci_must_be_a_pair():
    with pytest.raises(SpecError, match="pair"):
        validate_columns(
            (Sparkline("Trend", value="lift", ci=("lb", "ub", "extra")),)  # ty: ignore[invalid-argument-type]
        )


def test_sparkline_without_ci_is_valid():
    validate_columns((Sparkline("Trend", value="lift"),))
