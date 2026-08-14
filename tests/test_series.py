import datetime as dt

import narwhals as nw
import pandas as pd
import polars as pl
import pyarrow as pa
import pytest

from coeftable.series import Series, resolve_companion_series, resolve_list_series
from coeftable.spec import SpecError

_MAKERS = {"pandas": pd.DataFrame, "polars": pl.DataFrame, "pyarrow": pa.table}


@pytest.fixture(params=["pandas", "polars", "pyarrow"])
def make(request):
    """A native-frame constructor for the parametrized backend."""
    return _MAKERS[request.param]


def _frame(make, raw: dict) -> nw.DataFrame:
    return nw.from_native(make(raw), eager_only=True)


LIST_RAW = {
    "metric": ["Revenue", "Latency"],
    "y": [[10.0, 20.0, 30.0], [40.0, 50.0]],
    "lb": [[9.0, 19.0, 29.0], [39.0, 49.0]],
    "ub": [[11.0, 21.0, 31.0], [41.0, 51.0]],
    "x": [[0.0, 1.0, 2.0], [0.0, 1.0]],
}

# The same data as LIST_RAW, as a long companion frame -- deliberately out of
# x order per group, so the "one path" test below also exercises the
# sort-by-x step rather than passing by coincidence of input order.
COMPANION_RAW = {
    "metric": ["Revenue", "Revenue", "Revenue", "Latency", "Latency"],
    "day": [2, 0, 1, 1, 0],
    "y": [30.0, 10.0, 20.0, 50.0, 40.0],
    "lb": [29.0, 9.0, 19.0, 49.0, 39.0],
    "ub": [31.0, 11.0, 21.0, 51.0, 41.0],
}


def test_list_columns_round_trip(make):
    series = resolve_list_series(
        _frame(make, LIST_RAW), ["Revenue", "Latency"], value="y", ci=("lb", "ub"), x="x"
    )
    assert series[0] == Series(
        x=[0.0, 1.0, 2.0], y=[10.0, 20.0, 30.0], lower=[9.0, 19.0, 29.0], upper=[11.0, 21.0, 31.0]
    )
    assert series[1] == Series(
        x=[0.0, 1.0], y=[40.0, 50.0], lower=[39.0, 49.0], upper=[41.0, 51.0]
    )


def test_list_columns_without_ci_or_x_use_defaults(make):
    raw = {"metric": ["Revenue"], "y": [[5.0, 6.0, 7.0]]}
    series = resolve_list_series(_frame(make, raw), ["Revenue"], value="y")[0]
    assert series.x == [0.0, 1.0, 2.0]
    assert series.lower == [None, None, None]
    assert series.upper == [None, None, None]
    assert series.x_temporal is False


def test_companion_frame_matches_list_columns(make):
    """The "one path" claim: a shuffled long frame collapses to the same
    Series as the equivalent, already-ordered list columns.
    """
    list_series = resolve_list_series(
        _frame(make, LIST_RAW), ["Revenue", "Latency"], value="y", ci=("lb", "ub"), x="x"
    )
    companion = resolve_companion_series(
        make(COMPANION_RAW),
        [("Revenue", None, None, None), ("Latency", None, None, None)],
        rows="metric",
        nest=None,
        groups=None,
        split_columns=None,
        value="y",
        ci=("lb", "ub"),
        x="day",
    )
    assert companion[("Revenue", None, None, None)] == list_series[0]
    assert companion[("Latency", None, None, None)] == list_series[1]


def test_missing_identity_in_companion_frame_yields_empty_series(make):
    result = resolve_companion_series(
        make(COMPANION_RAW),
        [("Revenue", None, None, None), ("Ghost", None, None, None)],
        rows="metric",
        nest=None,
        groups=None,
        split_columns=None,
        value="y",
    )
    assert result[("Ghost", None, None, None)] == Series(
        x=[], y=[], lower=[], upper=[], x_temporal=False
    )


def test_companion_frame_groups_by_nest_and_split(make):
    """Two rows sharing a row key but differing by nest or split resolve to
    distinct series -- the identity tuple is (row, nest, split), not just row.
    """
    raw = {
        "metric": ["Revenue", "Revenue", "Revenue", "Revenue"],
        "variant": ["A", "A", "B", "B"],
        "region": ["US", "EU", "US", "EU"],
        "day": [0, 0, 0, 0],
        "y": [1.0, 2.0, 3.0, 4.0],
    }
    result = resolve_companion_series(
        make(raw),
        [
            ("Revenue", "A", None, "US"),
            ("Revenue", "A", None, "EU"),
            ("Revenue", "B", None, "US"),
            ("Revenue", "B", None, "EU"),
        ],
        rows="metric",
        nest="variant",
        groups=None,
        split_columns="region",
        value="y",
    )
    assert result[("Revenue", "A", None, "US")].y == [1.0]
    assert result[("Revenue", "A", None, "EU")].y == [2.0]
    assert result[("Revenue", "B", None, "US")].y == [3.0]
    assert result[("Revenue", "B", None, "EU")].y == [4.0]


def test_companion_frame_without_x_keeps_row_order(make):
    raw = {"metric": ["Revenue", "Revenue"], "y": [20.0, 10.0]}
    result = resolve_companion_series(
        make(raw),
        [("Revenue", None, None, None)],
        rows="metric",
        nest=None,
        groups=None,
        split_columns=None,
        value="y",
    )
    series = result[("Revenue", None, None, None)]
    assert series.x == [0.0, 1.0]
    assert series.y == [20.0, 10.0]


def test_ragged_value_and_x_length_raises_spec_error_naming_row_key(make):
    raw = {"metric": ["Revenue"], "y": [[1.0, 2.0, 3.0]], "x": [[0.0, 1.0]]}
    with pytest.raises(SpecError, match="Revenue"):
        resolve_list_series(_frame(make, raw), ["Revenue"], value="y", x="x")


def test_ragged_ci_bound_length_raises_spec_error(make):
    raw = {
        "metric": ["Latency"],
        "y": [[1.0, 2.0, 3.0]],
        "lb": [[0.5, 1.5]],
        "ub": [[1.5, 2.5, 3.5]],
    }
    with pytest.raises(SpecError, match="Latency"):
        resolve_list_series(_frame(make, raw), ["Latency"], value="y", ci=("lb", "ub"))


def test_nan_and_none_in_list_column_become_none(make):
    raw = {"metric": ["Revenue"], "y": [[1.0, float("nan"), None, 3.0]]}
    series = resolve_list_series(_frame(make, raw), ["Revenue"], value="y")[0]
    assert series.y == [1.0, None, None, 3.0]


def test_nullable_pandas_sentinels_become_none():
    """Pandas-specific: `<NA>` (nullable Float64) and `NaT` are not `None`
    but must still normalise to it, matching `_numeric`'s existing sentinel
    handling. The `NaT` case also regression-guards sort-by-x: `NaT` is not
    orderable against a real timestamp, so it must still sort last even
    though it is not the `None` object either.
    """
    pdf = pd.DataFrame(
        {"metric": ["Revenue", "Revenue"], "y": pd.array([1.0, None], dtype="Float64")}
    )
    result = resolve_companion_series(
        pdf,
        [("Revenue", None, None, None)],
        rows="metric",
        nest=None,
        groups=None,
        split_columns=None,
        value="y",
    )
    assert result[("Revenue", None, None, None)].y == [1.0, None]

    pdf2 = pd.DataFrame(
        {
            "metric": ["Revenue", "Revenue"],
            "day": pd.to_datetime([None, "2024-01-01"]),
            "y": [1.0, 2.0],
        }
    )
    result2 = resolve_companion_series(
        pdf2,
        [("Revenue", None, None, None)],
        rows="metric",
        nest=None,
        groups=None,
        split_columns=None,
        value="y",
        x="day",
    )
    series = result2[("Revenue", None, None, None)]
    assert series.x_temporal is True
    expected_first = (dt.datetime(2024, 1, 1) - dt.datetime(1970, 1, 1)).total_seconds()
    assert series.x == [expected_first, None]
    assert series.y == [2.0, 1.0]


def test_pandas_companion_null_key_matches_none_identity():
    """A pandas companion frame surfaces a null key cell as `float('nan')`,
    while identities from the main frame carry `None`. Without normalising
    both sides to `None`, `nan != None` misses the group and the row
    silently renders an empty series -- the data-loss bug this guards.
    """
    companion = pd.DataFrame(
        {"metric": ["A", "A"], "variant": ["X", None], "y_val": [100.0, 200.0]}
    )
    result = resolve_companion_series(
        companion,
        [("A", "X", None, None), ("A", None, None, None)],
        rows="metric",
        nest="variant",
        groups=None,
        split_columns=None,
        value="y_val",
    )
    assert result[("A", "X", None, None)].y == [100.0]
    assert result[("A", None, None, None)].y == [200.0]


def test_temporal_x_normalises_with_correct_relative_spacing(make):
    dates = [dt.date(2024, 1, 1), dt.date(2024, 1, 2), dt.date(2024, 1, 12)]
    raw = {"metric": ["Revenue"], "y": [[1.0, 2.0, 3.0]], "x": [dates]}
    series = resolve_list_series(_frame(make, raw), ["Revenue"], value="y", x="x")[0]

    assert series.x_temporal is True
    x0, x1, x2 = series.x
    assert x0 is not None
    assert x1 is not None
    assert x2 is not None
    day = 86400.0
    assert x1 - x0 == day
    assert x2 - x1 == 10 * day
    expected_first = (dt.datetime(2024, 1, 1) - dt.datetime(1970, 1, 1)).total_seconds()
    assert x0 == expected_first


def test_null_point_in_temporal_x_list_becomes_none(make):
    """A gap inside an otherwise-temporal x list stays a gap, not a crash."""
    dates = [dt.date(2024, 1, 1), None, dt.date(2024, 1, 3)]
    raw = {"metric": ["Revenue"], "y": [[1.0, 2.0, 3.0]], "x": [dates]}
    series = resolve_list_series(_frame(make, raw), ["Revenue"], value="y", x="x")[0]

    assert series.x_temporal is True
    assert series.x[1] is None
    x0, x2 = series.x[0], series.x[2]
    assert x0 is not None
    assert x2 is not None
    assert x2 - x0 == 2 * 86400.0


def test_timezone_aware_x_normalises_through_utc(make):
    """Two instants expressed in different UTC offsets still project to the
    correct real elapsed time apart -- not the difference in their
    wall-clock hour fields.
    """
    t0 = dt.datetime(2024, 1, 1, 12, 0, tzinfo=dt.UTC)
    # 13:00+02:00 is the same instant as 11:00 UTC, one hour before t0.
    t1 = dt.datetime(2024, 1, 1, 13, 0, tzinfo=dt.timezone(dt.timedelta(hours=2)))
    raw = {"metric": ["Revenue"], "y": [[1.0, 2.0]], "x": [[t0, t1]]}
    series = resolve_list_series(_frame(make, raw), ["Revenue"], value="y", x="x")[0]

    assert series.x_temporal is True
    x0, x1 = series.x
    assert x0 is not None
    assert x1 is not None
    assert x0 - x1 == 3600.0


def test_series_arg_groups_each_identity_into_per_arm_series(make):
    raw = {
        "metric": ["Revenue", "Revenue", "Revenue", "Revenue"],
        "arm": ["control", "control", "treatment", "treatment"],
        "day": [0, 1, 0, 1],
        "y": [1.0, 2.0, 10.0, 20.0],
    }
    result = resolve_companion_series(
        make(raw),
        [("Revenue", None, None, None)],
        rows="metric",
        nest=None,
        groups=None,
        split_columns=None,
        value="y",
        x="day",
        series="arm",
    )
    arms = dict(result[("Revenue", None, None, None)])
    assert arms["control"].y == [1.0, 2.0]
    assert arms["treatment"].y == [10.0, 20.0]


def test_series_arg_sorts_arms_ascending_with_none_last(make):
    raw = {
        "metric": ["Revenue"] * 4,
        "arm": ["b", None, "a", "c"],
        "y": [2.0, 4.0, 1.0, 3.0],
    }
    result = resolve_companion_series(
        make(raw),
        [("Revenue", None, None, None)],
        rows="metric",
        nest=None,
        groups=None,
        split_columns=None,
        value="y",
        series="arm",
    )
    arm_keys = [key for key, _ in result[("Revenue", None, None, None)]]
    assert arm_keys == ["a", "b", "c", None]


def test_series_arg_independent_gaps_per_arm(make):
    # control has a gap at day 1; treatment has no gaps -- each arm's own
    # `Series` must reflect only its own missing points.
    raw = {
        "metric": ["Revenue"] * 6,
        "arm": ["control", "control", "control", "treatment", "treatment", "treatment"],
        "day": [0, 1, 2, 0, 1, 2],
        "y": [1.0, None, 3.0, 10.0, 20.0, 30.0],
    }
    result = resolve_companion_series(
        make(raw),
        [("Revenue", None, None, None)],
        rows="metric",
        nest=None,
        groups=None,
        split_columns=None,
        value="y",
        x="day",
        series="arm",
    )
    arms = dict(result[("Revenue", None, None, None)])
    assert arms["control"].y == [1.0, None, 3.0]
    assert arms["treatment"].y == [10.0, 20.0, 30.0]


def test_series_arg_identity_with_no_rows_resolves_empty_list(make):
    raw = {"metric": ["Revenue"], "arm": ["control"], "y": [1.0]}
    result = resolve_companion_series(
        make(raw),
        [("Revenue", None, None, None), ("Ghost", None, None, None)],
        rows="metric",
        nest=None,
        groups=None,
        split_columns=None,
        value="y",
        series="arm",
    )
    assert result[("Ghost", None, None, None)] == []
