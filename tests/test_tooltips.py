import pandas as pd
import pytest

from coeftable.errors import SpecError
from coeftable.tooltips import TooltipValues, format_tooltip_values


def test_missing_extras_bypass_formatter_and_preserve_field_order():
    def integer(value):
        return f"{int(value):,}"

    fields = [
        TooltipValues("Count", [1000, None, float("nan"), pd.NA, pd.NaT], fmt=integer),
        TooltipValues("Note", ["a", "b", "c", "<NA>", "NaT"]),
    ]
    assert format_tooltip_values(fields, size=5, context="row A") == (
        ("Count", ("1,000", "—", "—", "—", "—")),
        ("Note", ("a", "b", "c", "<NA>", "NaT")),
    )


def test_extra_length_mismatch_raises_spec_error():
    with pytest.raises(SpecError):
        format_tooltip_values([TooltipValues("Count", [1])], size=2, context="row A")


def test_nonstring_formatter_result_raises_spec_error():
    with pytest.raises(SpecError):
        format_tooltip_values(
            [TooltipValues("Count", [1], fmt=lambda value: value)], size=1, context="row A"
        )


def test_formatter_failure_preserves_original_cause():
    def broken(value):
        raise ValueError(value)

    with pytest.raises(SpecError) as error:
        format_tooltip_values([TooltipValues("Count", [1], fmt=broken)], size=1, context="row A")
    assert isinstance(error.value.__cause__, ValueError)
