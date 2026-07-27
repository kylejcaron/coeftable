import math

import pytest

from coeftable.format import (
    CIStyle,
    Currency,
    Number,
    Percent,
    compact_number,
    is_missing,
    render_interval,
)
from coeftable.theme import DEFAULT


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2_400_000_000, "2.4B"),
        (2_300_000, "2.3M"),
        (1_400, "1.4k"),
        (12.34, "12.3"),
        (0.456, "0.46"),
    ],
)
def test_compact_number(value, expected):
    assert compact_number(value) == expected


def test_number_defaults_use_thousands_separator():
    assert Number()(1234.5) == "1,234.50"


def test_number_signed_prefixes_positive_only():
    assert Number(signed=True)(3.0) == "+3.00"
    assert Number(signed=True)(-3.0) == "-3.00"
    assert Number(signed=True)(0.0) == "0.00"


def test_negative_currency_puts_sign_before_symbol():
    assert Currency()(-5.0) == "-$5.00"


def test_percent_scale_converts_fractions():
    assert Percent(scale=100.0, decimals=1)(0.034) == "+3.4%"


def test_percent_defaults_treat_input_as_percentage_points():
    assert Percent(decimals=1)(3.4) == "+3.4%"


def test_is_missing_covers_none_and_nan():
    assert is_missing(None)
    assert is_missing(math.nan)
    assert not is_missing(0.0)


def test_render_interval_stacked_has_value_and_bracketed_ci():
    html = render_interval(3.4, 1.2, 5.7, fmt=Percent(decimals=1), style=CIStyle(), theme=DEFAULT)
    assert "+3.4%" in html
    assert "[+1.2%, +5.7%]" in html
    assert "<br>" in html


def test_render_interval_inline_layout_has_no_break():
    html = render_interval(
        3.4, 1.2, 5.7, fmt=Percent(decimals=1), style=CIStyle(layout="inline"), theme=DEFAULT
    )
    assert "<br>" not in html


def test_render_interval_value_only_omits_ci():
    html = render_interval(
        3.4, 1.2, 5.7, fmt=Percent(decimals=1), style=CIStyle(layout="value_only"), theme=DEFAULT
    )
    assert "1.2" not in html


def test_unbounded_upper_uses_asymmetric_bracket():
    html = render_interval(2.0, 1.0, None, fmt=Number(decimals=1), style=CIStyle(), theme=DEFAULT)
    assert "[1.0, \u221e)" in html


def test_unbounded_lower_uses_asymmetric_bracket():
    html = render_interval(2.0, None, 3.0, fmt=Number(decimals=1), style=CIStyle(), theme=DEFAULT)
    assert "(-\u221e, 3.0]" in html


def test_missing_value_renders_theme_na_text():
    assert (
        render_interval(None, 1.0, 2.0, fmt=Number(), style=CIStyle(), theme=DEFAULT)
        == DEFAULT.na_text
    )


def test_absent_ci_renders_point_estimate_only():
    html = render_interval(2.0, None, None, fmt=Number(decimals=1), style=CIStyle(), theme=DEFAULT)
    assert "2.0" in html
    assert "\u221e" not in html
