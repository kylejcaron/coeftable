import narwhals as nw
import pandas as pd
import polars as pl
import pytest

from coeftable.frame import resolve
from coeftable.spec import CoefTable, ColumnNotFoundError, SpecError

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


def test_color_rule_overrides_direction():
    from coeftable.theme import DEFAULT

    spec = base(pl.DataFrame(RAW), color_rule=lambda est, lo, hi, ref: "unfavorable")
    out = resolve(spec.forest("Plot", of="Lift %"))
    plots = nw.from_native(out.frame)["Plot"].to_list()
    assert DEFAULT.color("unfavorable") in plots[0]


def test_explicit_domain_overrides_scale():
    spec = base(pl.DataFrame(RAW))
    out = resolve(spec.forest("Plot", of="Lift %", domain=(-10.0, 10.0)))
    assert out.axis_rows


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


def test_duplicate_identity_rows_raise_spec_error():
    dup = dict(RAW) | {"metric": ["Revenue", "Revenue", "Revenue", "Latency"]}
    table = CoefTable(pl.DataFrame(dup), rows="metric", nest="variant").estimate(
        "Lift %", "rel", ci=("rel_lb", "rel_ub")
    )
    with pytest.raises(SpecError, match="Duplicate input row"):
        resolve(table)
