import pandas as pd
import polars as pl
import pytest

import coeftable as ct

RAW = {
    "area": ["Core", "Core", "Ops", "Ops"],
    "metric": ["Revenue", "Revenue", "Latency", "Latency"],
    "variant": ["B", "C", "B", "C"],
    "att": [12400.0, -3100.0, 40.0, 120.0],
    "att_lb": [4200.0, -9800.0, -80.0, 45.0],
    "att_ub": [20600.0, 3600.0, 160.0, 195.0],
    "rel": [3.4, -1.2, 0.5, 2.0],
    "rel_lb": [1.2, -4.0, -1.0, 0.8],
    "rel_ub": [5.7, 1.6, 2.0, 3.2],
}

ONE_LINE_RAW = {
    "metric": ["Revenue", "Latency"],
    "rel": [3.4, 0.5],
    "rel_lb": [1.2, -1.0],
    "rel_ub": [5.7, 2.0],
}


@pytest.mark.parametrize("frame", [pd.DataFrame(RAW), pl.DataFrame(RAW)])
def test_full_experiment_table_renders(frame):
    direction: dict[str, str] = {"Latency": "lower_is_better"}
    html = (
        ct.CoefTable(frame, rows="metric", nest="variant", groups="area")
        .estimate("Lift Amount", "att", ci=("att_lb", "att_ub"), fmt=ct.Number(compact=True))
        .estimate("Lift %", "rel", ci=("rel_lb", "rel_ub"), fmt=ct.Percent(signed=True))
        .forest("Lift Plot", of="Lift %", ref=0.0)
        .header("Experiment Results", "Q3 holdout")
        .with_direction(direction)  # type: ignore
        .gt()
        .as_raw_html()
    )
    assert "Experiment Results" in html
    assert "<svg" in html
    assert "12.4k" in html


def test_one_line_table_renders():
    html = (
        ct.CoefTable(
            pl.DataFrame(ONE_LINE_RAW),
            rows="metric",
            estimate="rel",
            ci=("rel_lb", "rel_ub"),
        )
        .gt()
        .as_raw_html()
    )
    assert "<table" in html


def test_every_public_symbol_is_exported():
    expected = {
        "CoefTable",
        "Estimate",
        "Forest",
        "Passthrough",
        "Number",
        "Percent",
        "Currency",
        "CIStyle",
        "Theme",
        "DEFAULT",
        "COLORBLIND",
        "MONO",
        "role_for",
        "SpecError",
        "ColumnNotFoundError",
        "__version__",
    }
    assert expected <= set(ct.__all__)
    for name in expected:
        assert hasattr(ct, name)


def test_package_does_not_import_matplotlib():
    import sys

    assert "matplotlib" not in sys.modules
    assert "plotnine" not in sys.modules
