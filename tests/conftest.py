import polars as pl
import pytest

from coeftable import CoefTable, Tooltip, TooltipField


@pytest.fixture
def inspection_table():
    main = pl.DataFrame({"metric": ["A", "Missing"], "n": [999, 888]})
    history = pl.DataFrame(
        {
            "metric": ["A", "A", "A", "Missing", "Elsewhere"],
            "arm": ["drawn", "drawn", "missing", "missing", "absent"],
            "x": [4, 0, 2, 2, 1],
            "y": [5, 1, None, None, 3],
            "lower": [4, 0, 1, 1, 2],
            "upper": [6, 2, 3, 3, 4],
            "n": [30, 10, 20, 40, 50],
        }
    )
    return CoefTable(main, rows="metric").sparkline(
        "Trend",
        value="y",
        x="x",
        ci=("lower", "upper"),
        data=history,
        series="arm",
        show_ribbon=True,
        ylim=(0, 3),
        tooltip=Tooltip(fields=[TooltipField("n")]),
    )
