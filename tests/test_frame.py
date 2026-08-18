import re

import narwhals as nw
import pandas as pd
import polars as pl
import pytest

from coeftable import Band, Rule
from coeftable.format import CIStyle
from coeftable.frame import _pad_domain, _plot_height, resolve
from coeftable.spec import CoefTable, ColumnNotFoundError, Estimate, Forest, Scan, SpecError

RAW = {
    "area": ["Core", "Core", "Core", "Core"],
    "metric": ["Revenue", "Revenue", "Latency", "Latency"],
    "variant": ["B", "C", "B", "C"],
    "rel": [3.4, -1.2, 0.5, 2.0],
    "rel_lb": [1.2, -4.0, -1.0, 0.8],
    "rel_ub": [5.7, 1.6, 2.0, 3.2],
}


def base(data, **kwargs):
    return CoefTable(data, rows="metric", nest="variant", **kwargs).estimate(
        "Lift %", "rel", ci=("rel_lb", "rel_ub")
    )


def _forest_state(table: CoefTable):
    frame = nw.from_native(table.data, eager_only=True)
    count = len(frame)
    scan = Scan(
        frame=frame,
        columns=table.columns,
        row_keys=frame[table.rows].to_list() if table.rows else [""] * count,
        nest_keys=frame[table.nest].to_list() if table.nest else [None] * count,
        group_keys=frame[table.groups].to_list() if table.groups else [None] * count,
        split_keys=(
            frame[table.split_columns].to_list() if table.split_columns else [None] * count
        ),
        rows=table.rows,
        nest=table.nest,
        groups=table.groups,
        split_columns=table.split_columns,
    )
    forest = next(column for column in table.columns if isinstance(column, Forest))
    return forest.prepare(scan).payload


@pytest.fixture(params=["pandas", "polars"])
def data(request):
    if request.param == "pandas":
        return pd.DataFrame(RAW)
    return pl.DataFrame(RAW)


def test_plain_dict_is_rejected_with_a_clear_error():
    """narwhals has no backend to build from, so a dict cannot be ingested."""
    with pytest.raises(TypeError, match="dict"):
        resolve(base(dict(RAW)))


def test_resolves_for_every_backend(data):
    out = resolve(base(data))
    assert out.display_columns
    assert len(nw.from_native(out.frame).rows()) == 4


def test_repeated_row_keys_are_blanked(data):
    out = resolve(base(data))
    frame = nw.from_native(out.frame)
    assert frame["metric"].to_list() == ["<b>Revenue</b>", "", "<b>Latency</b>", ""]


def test_row_order_follows_first_appearance(data):
    out = resolve(base(data))
    frame = nw.from_native(out.frame)
    assert frame["variant"].to_list() == ["B", "C", "B", "C"]


def test_sort_rows_orders_lexically(data):
    out = resolve(base(data, sort_rows=True))
    frame = nw.from_native(out.frame)
    assert frame["metric"].to_list()[0] == "<b>Latency</b>"


def test_banding_alternates_by_row_key(data):
    out = resolve(base(data))
    assert out.band_rows == [0, 1]


def test_divider_marks_each_new_row_key_after_the_first(data):
    out = resolve(base(data))
    assert out.divider_rows == [2]


def test_forest_adds_one_axis_row_for_a_table_scale(data):
    out = resolve(base(data).forest("Plot", of="Lift %", scale="table"))
    frame = nw.from_native(out.frame)
    assert len(out.axis_rows) == 1
    assert len(frame.rows()) == 5


def test_row_scale_adds_one_axis_row_per_row_key(data):
    out = resolve(base(data).forest("Plot", of="Lift %", scale="row"))
    assert len(out.axis_rows) == 2


def test_show_axis_false_emits_no_axis_row(data):
    out = resolve(base(data).forest("Plot", of="Lift %", show_axis=False))
    assert out.axis_rows == []
    assert len(nw.from_native(out.frame).rows()) == 4


def test_no_forest_means_no_axis_row(data):
    out = resolve(base(data))
    assert out.axis_rows == []


def test_split_columns_produces_spanners_and_widened_frame():
    raw = {
        "metric": ["Revenue", "Revenue"],
        "method": ["OLS", "DiD"],
        "rel": [3.4, 3.1],
        "rel_lb": [1.2, 1.0],
        "rel_ub": [5.7, 5.2],
    }
    table = CoefTable(pl.DataFrame(raw), rows="metric", split_columns="method").estimate(
        "Lift %", "rel", ci=("rel_lb", "rel_ub")
    )
    out = resolve(table)
    assert set(out.spanners) == {"OLS", "DiD"}
    assert len(nw.from_native(out.frame).rows()) == 1
    assert all(out.labels[c] == "Lift %" for cols in out.spanners.values() for c in cols)


def test_groups_column_is_reported():
    out = resolve(base(pl.DataFrame(RAW), groups="area"))
    assert out.group_column == "area"


def _group_spanning_row_key_table():
    # "Revenue" spans both "US" and "EU" groups. Rows are laid out group-major,
    # so the US block (v1, v2, v4) comes first and the EU block (v3) second --
    # the same order `great_tables` renders them in. Shared by both the
    # row-label and divider tests below, which assert different facets of the
    # same resolved table.
    raw = pd.DataFrame(
        [
            {"metric": "Revenue", "variant": "v1", "region": "US", "val": 1.0},
            {"metric": "Revenue", "variant": "v2", "region": "US", "val": 2.0},
            {"metric": "Revenue", "variant": "v3", "region": "EU", "val": 3.0},
            {"metric": "Latency", "variant": "v4", "region": "US", "val": 4.0},
        ]
    )
    table = CoefTable(raw, rows="metric", nest="variant", groups="region").passthrough(
        "Val", "val"
    )
    return resolve(table)


def test_row_label_survives_groupname_col_reordering_a_row_keys_nest_values():
    # The row-label blanking decision must be scoped per rendered group,
    # not per pre-group physical adjacency, or the second group's
    # occurrence blanks out entirely even though it starts a brand new
    # section.
    out = _group_spanning_row_key_table()
    frame = nw.from_native(out.frame)
    # Layout order is group-major: US (Revenue,v1) (Revenue,v2) (Latency,v4),
    # then EU (Revenue,v3). The second Revenue row (v2) is a legitimate
    # same-group repeat and still blanks; the EU occurrence starts a NEW group
    # block and must show its label again.
    assert frame["metric"].to_list() == [
        "<b>Revenue</b>",
        "",
        "<b>Latency</b>",
        "<b>Revenue</b>",
    ]


def test_dividers_land_on_true_within_group_key_transitions_not_group_boundaries():
    # `divider_rows` is scoped per group the same way row-label blanking
    # is: EU's first row (Revenue, v3) starts a brand new group block, so
    # it gets no spurious divider (the group-heading chrome already marks
    # that boundary) -- but Latency's row inside the *same* US group as
    # the two Revenue rows before it is a genuine key transition and must
    # still get one.
    out = _group_spanning_row_key_table()
    # Latency (index 2) is a genuine within-US key transition and gets one.
    # EU's Revenue (index 3) starts a brand new group block, so it does not.
    assert out.divider_rows == [2]


def test_row_label_may_appear_under_more_than_one_group():
    # A row label under two groups is one row per (group, label) pair. Before
    # the group joined row identity this raised SpecError, because identity was
    # (rows, nest) only and "Revenue" collided with itself across regions.
    raw = pd.DataFrame(
        [
            {"metric": "Revenue", "region": "US", "val": 1.0},
            {"metric": "Revenue", "region": "EU", "val": 2.0},
            {"metric": "Signups", "region": "US", "val": 3.0},
            {"metric": "Signups", "region": "EU", "val": 4.0},
        ]
    )
    out = resolve(CoefTable(raw, rows="metric", groups="region").passthrough("Val", "val"))
    frame = nw.from_native(out.frame)
    assert frame["region"].to_list() == ["US", "US", "EU", "EU"]
    # Each group block re-shows the label rather than blanking the repeat.
    assert frame["metric"].to_list() == [
        "<b>Revenue</b>",
        "<b>Signups</b>",
        "<b>Revenue</b>",
        "<b>Signups</b>",
    ]
    # Every cell resolves against its own (label, group) row: a stale identity
    # lookup would blank or cross-wire one group. US(1.0, 3.0), EU(2.0, 4.0).
    assert frame["Val"].to_list() == ["1.0", "3.0", "2.0", "4.0"]


def test_striping_alternates_when_input_interleaves_groups():
    # Rows arrive interleaved across groups, so laying out by row label alone
    # would put both Growth rows on the same stripe parity and leave the whole
    # Onboarding block unstriped once `great_tables` regrouped them.
    raw = pd.DataFrame(
        [
            {"metric": "Revenue", "area": "Growth", "val": 1.0},
            {"metric": "Retention", "area": "Onboarding", "val": 2.0},
            {"metric": "Signups", "area": "Growth", "val": 3.0},
            {"metric": "Churn", "area": "Onboarding", "val": 4.0},
        ]
    )
    out = resolve(CoefTable(raw, rows="metric", groups="area").passthrough("Val", "val"))
    frame = nw.from_native(out.frame)
    # Layout order is the rendered order, so the indices below are the ones a
    # reader sees: Growth(Revenue, Signups) then Onboarding(Retention, Churn).
    assert frame["area"].to_list() == ["Growth", "Growth", "Onboarding", "Onboarding"]
    assert out.band_rows == [0, 2]


def test_duplicate_rows_within_one_group_still_raise():
    # Widening identity with the group must not weaken the check: same label,
    # same nest and same group is still a genuine duplicate.
    raw = pd.DataFrame(
        [
            {"metric": "Revenue", "region": "US", "val": 1.0},
            {"metric": "Revenue", "region": "US", "val": 2.0},
        ]
    )
    table = CoefTable(raw, rows="metric", groups="region").passthrough("Val", "val")
    with pytest.raises(SpecError, match="Duplicate input row"):
        resolve(table)


def test_missing_value_column_raises_with_available_columns():
    table = CoefTable(pl.DataFrame(RAW), rows="metric").estimate("A", "nope")
    with pytest.raises(ColumnNotFoundError, match="nope"):
        resolve(table)


def test_missing_rows_column_raises():
    table = CoefTable(pl.DataFrame(RAW), rows="nope").estimate("A", "rel")
    with pytest.raises(ColumnNotFoundError, match="nope"):
        resolve(table)


def test_non_numeric_estimate_column_raises_type_error():
    table = CoefTable(pl.DataFrame(RAW), rows="metric").estimate("A", "variant")
    with pytest.raises(TypeError, match="variant"):
        resolve(table)


def test_direction_mapping_flips_bar_colour():
    from coeftable.theme import DEFAULT

    spec = base(pl.DataFrame(RAW), direction={"Latency": "lower_is_better"})
    out = resolve(spec.forest("Plot", of="Lift %"))
    frame = nw.from_native(out.frame)
    plots = frame["Plot"].to_list()
    assert DEFAULT.color("favorable") in plots[0]
    assert DEFAULT.color("unfavorable") in plots[3]


def test_row_group_scale_emits_one_axis_row_per_group():
    """Regression: the axis lookahead must resolve each future row's own group."""
    raw = dict(RAW) | {"area": ["Core", "Core", "Ops", "Ops"]}
    spec = base(pl.DataFrame(raw), groups="area")
    out = resolve(spec.forest("Plot", of="Lift %", scale="row_group"))
    assert len(out.axis_rows) == 2


def test_split_column_scale_emits_one_axis_row_per_split():
    raw = {
        "metric": ["Revenue", "Revenue", "Latency", "Latency"],
        "method": ["OLS", "DiD", "OLS", "DiD"],
        "rel": [3.4, 3.1, 0.5, 0.4],
        "rel_lb": [1.2, 1.0, -1.0, -0.9],
        "rel_ub": [5.7, 5.2, 2.0, 1.8],
    }
    table = CoefTable(pl.DataFrame(raw), rows="metric", split_columns="method").estimate(
        "Lift %", "rel", ci=("rel_lb", "rel_ub")
    )
    out = resolve(table.forest("Plot", of="Lift %", scale="split_column"))
    assert len(out.axis_rows) == 1


def test_sparse_split_data_resolves():
    """Regression: a row absent for the first split value must not raise."""
    raw = {
        "metric": ["Revenue", "Revenue", "Latency"],
        "method": ["OLS", "DiD", "OLS"],
        "rel": [3.4, 3.1, 0.5],
        "rel_lb": [1.2, 1.0, -1.0],
        "rel_ub": [5.7, 5.2, 2.0],
    }
    table = CoefTable(
        pl.DataFrame(raw), rows="metric", split_columns="method", sort_rows=True
    ).estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"))
    out = resolve(table)
    assert len(nw.from_native(out.frame).rows()) == 2


def test_forest_field_rule_targets_exactly_one_row():
    raw = pl.DataFrame(
        {
            "metric": ["Revenue", "Latency"],
            "est": [1.0, 1.0],
            "low": [0.5, 0.5],
            "high": [1.5, 1.5],
            "target": [1.25, None],
        }
    )
    table = (
        CoefTable(raw, rows="metric")
        .estimate("Effect", "est", ci=("low", "high"))
        .forest(
            "Plot",
            of="Effect",
            annotations=(Rule("target", axis="x", color="#123456"),),
            show_axis=False,
        )
    )
    plots = nw.from_native(resolve(table).frame)["Plot"].to_list()
    assert "#123456" in plots[0]
    assert "#123456" not in plots[1]
    assert all(plot.count("stroke-dasharray") >= 1 for plot in plots)


def test_forest_annotation_source_missing_from_frame_raises_before_preparation():
    table = (
        CoefTable(
            pl.DataFrame({"metric": ["Revenue"], "est": [1.0], "low": [0.5], "high": [1.5]}),
            rows="metric",
        )
        .estimate("Effect", "est", ci=("low", "high"))
        .forest("Plot", of="Effect", annotations=(Rule("target", axis="x"),))
    )
    with pytest.raises(ColumnNotFoundError, match="target"):
        resolve(table)


def test_forest_rejects_y_axis_annotations_during_column_validation():
    expected = (
        "Forest column 'Plot' annotation 0 uses axis='y'; forest plots support axis='x' only."
    )
    with pytest.raises(SpecError, match=re.escape(expected)):
        (
            CoefTable(
                pl.DataFrame({"metric": ["Revenue"], "est": [1.0], "low": [0.5], "high": [1.5]}),
                rows="metric",
            )
            .estimate("Effect", "est", ci=("low", "high"))
            .forest("Plot", of="Effect", annotations=(Rule(1.0, axis="y"),))
        )


def test_forest_literal_band_renders_in_every_nonempty_row():
    raw = pl.DataFrame(
        {
            "metric": ["Revenue", "Latency"],
            "est": [1.0, 1.0],
            "low": [0.5, 0.5],
            "high": [1.5, 1.5],
        }
    )
    table = (
        CoefTable(raw, rows="metric")
        .estimate("Effect", "est", ci=("low", "high"))
        .forest("Plot", of="Effect", annotations=(Band(1.1, 1.2, axis="x", color="#abcdef"),))
    )
    plots = nw.from_native(resolve(table).frame)["Plot"].to_list()
    assert sum("#abcdef" in plot for plot in plots) == 2


@pytest.mark.parametrize(
    ("scale", "expanded_key", "unexpanded_key"),
    [
        ("table", ("table",), None),
        ("row_group", ("group", "Core"), ("group", "Ops")),
        ("split_column", ("split", "OLS"), ("split", "DiD")),
        ("row", ("row", "Revenue"), ("row", "Latency")),
    ],
)
def test_forest_annotation_expands_the_eligible_scale_bucket(scale, expanded_key, unexpanded_key):
    raw = pl.DataFrame(
        {
            "area": ["Core", "Ops"],
            "metric": ["Revenue", "Latency"],
            "method": ["OLS", "DiD"],
            "est": [1.0, 1.0],
            "low": [0.5, 0.5],
            "high": [1.5, 1.5],
            "target": [10.0, None],
        }
    )
    table = (
        CoefTable(raw, rows="metric", groups="area", split_columns="method")
        .estimate("Effect", "est", ci=("low", "high"))
        .forest("Plot", of="Effect", scale=scale, annotations=(Rule("target", axis="x"),))
    )
    domains = _forest_state(table).domains
    assert domains[expanded_key][1] > 10.0
    if unexpanded_key is not None:
        assert domains[unexpanded_key][1] < 2.0


def test_forest_annotation_that_does_not_affect_domain_keeps_bucket_tight():
    raw = pl.DataFrame(
        {
            "metric": ["Revenue"],
            "est": [1.0],
            "low": [0.5],
            "high": [1.5],
        }
    )
    table = (
        CoefTable(raw, rows="metric")
        .estimate("Effect", "est", ci=("low", "high"))
        .forest(
            "Plot",
            of="Effect",
            annotations=(Rule(10.0, axis="x", affect_domain=False),),
        )
    )
    assert _forest_state(table).domains[("table",)] == pytest.approx((-0.12, 1.62))


def test_forest_symmetric_domain_includes_annotation_around_reference():
    raw = pl.DataFrame(
        {
            "metric": ["Revenue"],
            "est": [1.0],
            "low": [0.5],
            "high": [1.5],
        }
    )
    table = (
        CoefTable(raw, rows="metric")
        .estimate("Effect", "est", ci=("low", "high"))
        .forest(
            "Plot",
            of="Effect",
            ref=2.0,
            symmetric=True,
            annotations=(Rule(10.0, axis="x"),),
        )
    )
    low, high = _forest_state(table).domains[("table",)]
    assert high > 10.0
    assert high - 2.0 == pytest.approx(2.0 - low)


def test_forest_explicit_ylim_clips_and_omits_annotations_beyond_it():
    raw = pl.DataFrame(
        {
            "metric": ["Revenue"],
            "est": [1.0],
            "low": [0.5],
            "high": [1.5],
        }
    )
    table = (
        CoefTable(raw, rows="metric")
        .estimate("Effect", "est", ci=("low", "high"))
        .forest(
            "Plot",
            of="Effect",
            ylim=(0.0, 2.0),
            annotations=(
                Rule(3.0, axis="x", color="#ff0000"),
                Band(1.5, 3.0, axis="x", color="#00ff00"),
            ),
        )
    )
    plot = nw.from_native(resolve(table).frame)["Plot"].to_list()[0]
    assert _forest_state(table).domains == {("table",): (0.0, 2.0)}
    assert "#ff0000" not in plot
    assert "#00ff00" in plot


def test_forest_annotations_do_not_fill_blank_cells_or_expand_from_them():
    raw = pl.DataFrame(
        {
            "metric": ["Revenue", "Latency"],
            "est": [1.0, None],
            "low": [0.5, 0.5],
            "high": [1.5, 1.5],
            "target": [None, 10.0],
        }
    )
    table = (
        CoefTable(raw, rows="metric")
        .estimate("Effect", "est", ci=("low", "high"))
        .forest("Plot", of="Effect", annotations=(Rule("target", axis="x"),))
    )
    plots = nw.from_native(resolve(table).frame)["Plot"].to_list()
    assert plots[1] == ""
    assert _forest_state(table).domains[("table",)][1] < 2.0


def test_color_rule_overrides_direction():
    from coeftable.theme import DEFAULT

    spec = base(pl.DataFrame(RAW), color_rule=lambda est, lo, hi, ref: "unfavorable")
    out = resolve(spec.forest("Plot", of="Lift %"))
    plots = nw.from_native(out.frame)["Plot"].to_list()
    assert DEFAULT.color("unfavorable") in plots[0]


def test_explicit_ylim_overrides_scale():
    spec = base(pl.DataFrame(RAW))
    out = resolve(spec.forest("Plot", of="Lift %", ylim=(-10.0, 10.0)))
    assert out.axis_rows


def test_pad_domain_default_is_not_symmetric():
    low, high = _pad_domain([1.0, 5.0, -3.0, 1.0], ref=0.0)
    assert (low, high) == (-3.64, 5.64)
    assert low != -high


def test_pad_domain_symmetric_centers_on_ref():
    low, high = _pad_domain([1.0, 5.0, -3.0, 1.0], ref=0.0, symmetric=True)
    assert (low, high) == (-5.64, 5.64)
    assert low == -high


def test_pad_domain_symmetric_respects_nonzero_ref():
    low, high = _pad_domain([2.0, 8.0], ref=5.0, symmetric=True)
    assert high - 5.0 == 5.0 - low


def test_forest_symmetric_flag_resolves_without_error():
    spec = base(pl.DataFrame(RAW))
    out = resolve(spec.forest("Plot", of="Lift %", ref=0.0, symmetric=True))
    assert out.axis_rows


def test_explicit_ylim_wins_over_symmetric():
    spec = base(pl.DataFrame(RAW))
    out = resolve(spec.forest("Plot", of="Lift %", ylim=(-10.0, 10.0), symmetric=True))
    assert out.axis_rows


OUTLIER_RAW = {
    "area": ["Core"] * 4,
    "metric": ["A", "B", "C", "Rare"],
    "variant": ["B", "B", "B", "B"],
    "rel": [0.5, -0.2, 0.1, 300.0],
    "rel_lb": [0.3, -0.5, -0.1, 220.0],
    "rel_ub": [0.7, 0.1, 0.3, 410.0],
}


def test_forest_autoscale_robust_discounts_outlier_and_flags_bucket_clipped():
    table = base(pl.DataFrame(OUTLIER_RAW)).forest("Plot", of="Lift %", autoscale="robust")
    state = _forest_state(table)
    (domain,) = state.domains.values()
    assert domain[1] < 220.0
    assert state.clipped == set(state.domains)


def test_forest_autoscale_tight_default_fits_outlier_with_no_clip():
    table = base(pl.DataFrame(OUTLIER_RAW)).forest("Plot", of="Lift %")
    state = _forest_state(table)
    (domain,) = state.domains.values()
    assert domain[1] >= 410.0
    assert state.clipped == frozenset()


def test_forest_autoscale_robust_composes_with_symmetric():
    table = base(pl.DataFrame(OUTLIER_RAW)).forest(
        "Plot", of="Lift %", ref=0.0, autoscale="robust", symmetric=True
    )
    state = _forest_state(table)
    (domain,) = state.domains.values()
    assert domain[0] == -domain[1]
    assert domain[1] < 220.0


def test_forest_explicit_ylim_wins_over_robust_and_still_flags_clipping():
    table = base(pl.DataFrame(OUTLIER_RAW)).forest(
        "Plot", of="Lift %", autoscale="robust", ylim=(-1.0, 1.0)
    )
    state = _forest_state(table)
    (domain,) = state.domains.values()
    assert domain == (-1.0, 1.0)
    assert state.clipped == set(state.domains)


def test_forest_clipped_bucket_renders_margin_fade_in_html():
    table = base(pl.DataFrame(OUTLIER_RAW)).forest("Plot", of="Lift %", autoscale="robust")
    html = table.gt()._repr_html_()
    assert "linearGradient" in html


def test_forest_unclipped_table_renders_no_fade_in_html():
    table = base(pl.DataFrame(RAW)).forest("Plot", of="Lift %")
    html = table.gt()._repr_html_()
    assert "linearGradient" not in html


def test_plot_height_picks_stacked_layout_default():
    estimate = Estimate("Lift %", "rel", ci=("lb", "ub"))
    forest = Forest("Plot", of="Lift %")
    assert _plot_height((estimate,), forest.height) == 48


def test_plot_height_picks_shorter_default_for_single_line_layouts():
    estimate = Estimate("Lift %", "rel", ci=("lb", "ub"), ci_style=CIStyle(layout="inline"))
    forest = Forest("Plot", of="Lift %")
    assert _plot_height((estimate,), forest.height) == 34


def test_plot_height_explicit_override_wins():
    estimate = Estimate("Lift %", "rel", ci=("lb", "ub"))
    forest = Forest("Plot", of="Lift %", height=100)
    assert _plot_height((estimate,), forest.height) == 100


def test_plot_columns_tracks_forest_columns():
    spec = base(pl.DataFrame(RAW))
    out = resolve(spec.forest("Plot", of="Lift %"))
    assert out.plot_columns == ["Plot"]


def test_table_without_plot_columns_has_none():
    out = resolve(base(pl.DataFrame(RAW)))
    assert out.plot_columns == []


def test_passthrough_renders_the_frame_column_verbatim():
    spec = base(pl.DataFrame(RAW)).passthrough("Area", "area")
    out = resolve(spec)
    assert nw.from_native(out.frame)["Area"].to_list()[0] == "Core"


def test_column_not_found_error_lists_available_columns():
    table = CoefTable(pl.DataFrame(RAW), rows="metric").estimate("A", "nope")
    with pytest.raises(ColumnNotFoundError, match="Available columns"):
        resolve(table)


def test_nullable_pandas_dtype_treated_as_missing():
    import pandas as pd

    from coeftable.theme import DEFAULT

    pdf = pd.DataFrame({"metric": ["a", "b"], "rel": pd.array([None, 1.2], dtype="Float64")})
    table = CoefTable(pdf, rows="metric").estimate("E", "rel")
    out = resolve(table)
    frame = nw.from_native(out.frame)
    assert frame["E"].to_list()[0] == DEFAULT.na_text


def test_layout_column_collision_raises_spec_error():
    table = CoefTable(pl.DataFrame(RAW), rows="metric").estimate(
        "metric", "rel", ci=("rel_lb", "rel_ub")
    )
    with pytest.raises(SpecError, match="collides with layout"):
        resolve(table)


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"rows": "metric", "nest": "metric"}, "rows= and nest="),
        ({"rows": "metric", "groups": "metric"}, "rows= and groups="),
        ({"nest": "metric", "groups": "metric"}, "nest= and groups="),
    ],
)
def test_two_layout_roles_naming_one_column_raise_spec_error(kwargs, expected):
    # The output frame is keyed by column name, so two roles sharing a name
    # means one role's values are silently overwritten by the other's. The
    # message must name both roles and the offending column, so that it says
    # which column to rename.
    table = CoefTable(pl.DataFrame(RAW), **kwargs).estimate(
        "Lift %", "rel", ci=("rel_lb", "rel_ub")
    )
    with pytest.raises(SpecError, match=rf"{expected}.*'metric'"):
        resolve(table)


def test_distinct_layout_roles_resolve():
    table = CoefTable(pl.DataFrame(RAW), rows="metric", nest="variant", groups="area").estimate(
        "Lift %", "rel", ci=("rel_lb", "rel_ub")
    )
    assert resolve(table).group_column == "area"


def test_duplicate_identity_rows_raise_spec_error():
    dup = dict(RAW) | {"metric": ["Revenue", "Revenue", "Revenue", "Latency"]}
    table = CoefTable(pl.DataFrame(dup), rows="metric", nest="variant").estimate(
        "Lift %", "rel", ci=("rel_lb", "rel_ub")
    )
    with pytest.raises(SpecError, match="Duplicate input row"):
        resolve(table)


def test_ordered_unique_dedupes_distinct_nan_objects():
    from coeftable.grid import _ordered_unique

    # Two separately-constructed nan objects are not identical, so a
    # dedupe that leaned on CPython's `in` identity fast-path would keep
    # both. They must collapse to a single representative.
    values = [1.0, float("nan"), 2.0, float("nan"), 1.0]
    result = _ordered_unique(values, sort=False)
    nans = [v for v in result if isinstance(v, float) and v != v]
    non_nans = [v for v in result if not (isinstance(v, float) and v != v)]
    assert len(nans) == 1
    assert non_nans == [1.0, 2.0]
