import datetime as dt
import re

import narwhals as nw
import pandas as pd
import polars as pl
import pytest

from coeftable.format import CIStyle, DateAxis
from coeftable.frame import resolve
from coeftable.spec import (
    CoefTable,
    ColumnNotFoundError,
    Sparkline,
    SpecError,
    _bucket_domain,
    _clamp_domain,
    _pad_domain,
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


def test_domain_override_wins_over_scale():
    raw = {"metric": ["A", "B"], "lift": [[1.0, 2.0], [100.0, 200.0]]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", scale="row", domain=(-5.0, 5.0), ref=0.0
    )
    out = resolve(table)
    plots = nw.from_native(out.frame)["Trend"].to_list()
    # Wildly different magnitudes would give distinct row-scale domains, but
    # the explicit domain forces both onto the same one.
    assert _ref_line_y(plots[0]) == pytest.approx(_ref_line_y(plots[1]))


def test_clamp_domain_narrows_a_domain_that_exceeds_the_ceiling():
    assert _clamp_domain((-604.0, 904.0), ref=0.0, max_domain=20.0) == (-20.0, 20.0)


def test_clamp_domain_is_a_no_op_when_the_ceiling_is_wider_than_the_domain():
    assert _clamp_domain((-0.08, 1.08), ref=0.0, max_domain=20.0) == (-0.08, 1.08)


def test_clamp_domain_narrows_each_bound_independently():
    # Only the high bound exceeds the ceiling; the low bound, already
    # tighter than it, is left exactly as it was rather than pulled up.
    assert _clamp_domain((-0.8, 10.8), ref=0.0, max_domain=5.0) == (-0.8, 5.0)


def test_clamp_domain_never_widens_regardless_of_ceiling_size():
    for max_domain in (0.01, 1.0, 5.0, 20.0, 1000.0):
        low, high = _clamp_domain((-3.0, 4.0), ref=0.0, max_domain=max_domain)
        assert high - low <= 7.0


def test_clamp_domain_negative_max_domain_inverts_like_an_unvalidated_reversed_domain():
    # max_domain has no positivity validation, matching domain=(low, high)
    # itself, which is equally unvalidated (validate_columns has no shape
    # check for it either). Locking in the current, accepted, non-crashing
    # artifact rather than leaving it undocumented -- see _clamp_domain's
    # docstring for the precondition this violates.
    assert _clamp_domain((-0.08, 1.08), ref=0.0, max_domain=-5.0) == (5.0, -5.0)


def test_bucket_domain_override_wins_even_when_max_domain_is_set():
    assert _bucket_domain([100.0], 0.0, override=(-5.0, 5.0), max_domain=1.0) == (-5.0, 5.0)


def test_bucket_domain_applies_max_domain_only_on_the_auto_path():
    assert _bucket_domain([-500.0, 800.0], 0.0, override=None, max_domain=20.0) == (-20.0, 20.0)


def test_bucket_domain_without_max_domain_matches_plain_pad_domain():
    vals = [-500.0, 800.0]
    assert _bucket_domain(vals, 0.0, override=None, max_domain=None) == _pad_domain(vals, 0.0)


def test_max_domain_clamps_the_noisy_row_but_leaves_the_precise_row_unchanged():
    raw = {
        "metric": ["Precise", "Noisy"],
        "lift": [[0.5, 1.0, 0.8], [-500.0, 10.0, 800.0]],
    }

    def build(max_domain):
        kwargs = {} if max_domain is None else {"max_domain": max_domain}
        return CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
            "Trend", value="lift", ref=0.0, scale="row", **kwargs
        )

    plain = nw.from_native(resolve(build(None)).frame)["Trend"].to_list()
    clamped = nw.from_native(resolve(build(20.0)).frame)["Trend"].to_list()

    # Precise row: its own natural domain is already far tighter than the
    # ref +/- 20 ceiling, so max_domain changes nothing about its render.
    assert clamped[0] == plain[0]

    # Noisy row: its natural domain (padded from -500..800) blows past the
    # ceiling, so max_domain narrows it -- the series now clips in both
    # directions where it did not clip at all before.
    assert plain[1].count("<polygon") == 0
    assert clamped[1].count("<polygon") == 2


def test_max_domain_leaves_a_domain_already_tighter_than_the_ceiling_alone():
    raw = {"metric": ["A"], "lift": [[0.5, 1.0, 0.8]]}

    def build(max_domain):
        kwargs = {} if max_domain is None else {"max_domain": max_domain}
        return CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
            "Trend", value="lift", ref=0.0, **kwargs
        )

    plain = nw.from_native(resolve(build(None)).frame)["Trend"].to_list()
    clamped = nw.from_native(resolve(build(50.0)).frame)["Trend"].to_list()
    assert clamped == plain


def test_domain_wins_outright_over_max_domain_when_both_are_set():
    raw = {"metric": ["A"], "lift": [[-500.0, 10.0, 800.0]]}

    def build(max_domain):
        kwargs = {} if max_domain is None else {"max_domain": max_domain}
        return CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
            "Trend", value="lift", ref=0.0, domain=(-1000.0, 1000.0), **kwargs
        )

    # max_domain=1.0 would clamp to (-1, 1) if it won -- a drastic visual
    # change from the explicit (-1000, 1000) domain. It must not: domain=
    # is an absolute override and wins outright, exactly as it already does
    # over scale=.
    without = nw.from_native(resolve(build(None)).frame)["Trend"].to_list()
    with_ceiling = nw.from_native(resolve(build(1.0)).frame)["Trend"].to_list()
    assert with_ceiling == without


def test_max_domain_composes_with_scale_table_instead_of_overriding_it():
    raw = {
        "metric": ["Precise", "Noisy"],
        "lift": [[0.5, 1.0, 0.8], [-500.0, 10.0, 800.0]],
    }

    def build(max_domain):
        kwargs = {} if max_domain is None else {"max_domain": max_domain}
        return CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
            "Trend", value="lift", ref=0.0, scale="table", **kwargs
        )

    plain = nw.from_native(resolve(build(None)).frame)["Trend"].to_list()
    clamped = nw.from_native(resolve(build(20.0)).frame)["Trend"].to_list()

    # scale="table" keeps both rows on one shared domain, with or without a
    # ceiling -- max_domain narrows that shared domain in place; it does not
    # fall back to clamping each row's own domain independently.
    assert _ref_line_y(plain[0]) == pytest.approx(_ref_line_y(plain[1]))
    assert _ref_line_y(clamped[0]) == pytest.approx(_ref_line_y(clamped[1]))
    assert abs(_ref_line_y(plain[0]) - _ref_line_y(clamped[0])) > 0.5


def test_show_axis_false_emits_no_footer_row():
    raw = {"metric": ["A"], "lift": [[1.0, 2.0]]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", show_axis=False
    )
    out = resolve(table)
    assert out.axis_rows == []


def test_clip_indicators_default_on_for_a_domain_clipped_series():
    raw = {"metric": ["A"], "lift": [[1.0, 300.0, 1.0]]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", domain=(0.0, 20.0)
    )
    out = resolve(table)
    plots = nw.from_native(out.frame)["Trend"].to_list()
    data_cell = next(p for i, p in enumerate(plots) if i not in out.axis_rows)
    assert data_cell.count("<polygon") == 1


def test_clip_indicators_false_suppresses_the_flag():
    raw = {"metric": ["A"], "lift": [[1.0, 300.0, 1.0]]}
    table = CoefTable(pl.DataFrame(raw), rows="metric").sparkline(
        "Trend", value="lift", domain=(0.0, 20.0), show_clip_indicators=False
    )
    out = resolve(table)
    plots = nw.from_native(out.frame)["Trend"].to_list()
    data_cell = next(p for i, p in enumerate(plots) if i not in out.axis_rows)
    assert "<polygon" not in data_cell
    assert "<polyline" in data_cell


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
