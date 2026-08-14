import datetime as dt
from dataclasses import FrozenInstanceError

import narwhals as nw
import polars as pl
import pytest

from coeftable.annotations import (
    Band,
    ResolvedBand,
    ResolvedRule,
    Rule,
    annotation_sources,
    domain_values,
    prepare_annotations,
)
from coeftable.errors import SpecError


def _frame(**columns):
    return nw.from_native(pl.DataFrame(columns))


def test_annotation_sources_are_deduplicated_in_declaration_order():
    marks = (Rule("target", axis="x"), Band("low", "target", axis="x"))
    assert annotation_sources(marks) == ("target", "low")


def test_declarations_are_immutable():
    mark = Rule(1.0, axis="x")
    with pytest.raises(FrozenInstanceError):
        mark.at = 2.0  # ty: ignore[invalid-assignment]


def test_prepare_numeric_field_omits_missing_row_and_preserves_order():
    prepared = prepare_annotations(
        (Rule("target", axis="x"), Band(0.5, 1.5, axis="x")),
        _frame(target=[2.0, None]),
        axis_kinds={"x": "numeric"},
        plot_label="Plot",
        row_identities=[("A", None, None, None), ("B", None, None, None)],
    )
    assert [type(mark).__name__ for mark in prepared.by_row[0]] == [
        "ResolvedRule",
        "ResolvedBand",
    ]
    assert [type(mark).__name__ for mark in prepared.by_row[1]] == ["ResolvedBand"]
    assert domain_values(prepared.by_row[0], axis="x") == [2.0, 0.5, 1.5]


def test_prepare_temporal_literal_uses_epoch_seconds():
    prepared = prepare_annotations(
        (Rule(dt.date(1970, 1, 2), axis="x"),),
        _frame(metric=["A"]),
        axis_kinds={"x": "temporal"},
        plot_label="Trend",
        row_identities=[("A", None, None, None)],
    )
    mark = prepared.by_row[0][0]
    assert isinstance(mark, ResolvedRule)
    assert mark.at == 86_400.0


def test_reversed_field_band_names_plot_annotation_and_row():
    with pytest.raises(
        SpecError,
        match=r"Plot.*annotation 0.*row.*A.*start.*end",
    ):
        prepare_annotations(
            (Band("low", "high", axis="x"),),
            _frame(low=[2.0], high=[1.0]),
            axis_kinds={"x": "numeric"},
            plot_label="Plot",
            row_identities=[("A", None, None, None)],
        )


@pytest.mark.parametrize(
    ("factory", "match"),
    [
        (lambda: Rule(1.0, axis="x", layer="middle"), "layer"),  # ty: ignore[invalid-argument-type]
        (lambda: Rule(1.0, axis="x", dash="dotdash"), "dash"),  # ty: ignore[invalid-argument-type]
        (lambda: Rule(1.0, axis="x", opacity=1.1), "opacity"),
        (lambda: Rule(1.0, axis="x", width=0.0), "width"),
        (lambda: Rule(True, axis="x"), "coordinate"),
        (lambda: Rule(float("inf"), axis="x"), "finite"),
        (lambda: Band(0.0, float("nan"), axis="x"), "finite"),
    ],
    ids=["layer", "dash", "opacity", "width", "boolean", "infinite", "nan"],
)
def test_declaration_validation_rejects_invalid_values(factory, match):
    with pytest.raises(SpecError, match=match):
        factory()


@pytest.mark.parametrize(
    ("mark", "axis_kinds", "match"),
    [
        (Rule(1.0, axis="y"), {"x": "numeric"}, "axis"),
        (Rule(dt.date(1970, 1, 2), axis="x"), {"x": "numeric"}, "numeric"),
        (Rule(1.0, axis="x"), {"x": "temporal"}, "temporal"),
    ],
    ids=["unsupported_axis", "temporal_on_numeric", "numeric_on_temporal"],
)
def test_prepare_rejects_axis_and_kind_mismatches(mark, axis_kinds, match):
    with pytest.raises(SpecError, match=match):
        prepare_annotations(
            (mark,),
            _frame(metric=["A"]),
            axis_kinds=axis_kinds,
            plot_label="Plot",
            row_identities=[("A", None, None, None)],
        )


def test_prepare_skips_band_when_one_field_endpoint_is_missing():
    prepared = prepare_annotations(
        (Band("start", "end", axis="x"),),
        _frame(start=[1.0, 2.0], end=[None, 3.0]),
        axis_kinds={"x": "numeric"},
        plot_label="Plot",
        row_identities=[("A", None, None, None), ("B", None, None, None)],
    )
    assert prepared.by_row[0] == ()
    mark = prepared.by_row[1][0]
    assert isinstance(mark, ResolvedBand)
    assert mark.start == 2.0
    assert mark.end == 3.0


def test_domain_values_excludes_marks_that_do_not_affect_domain():
    prepared = prepare_annotations(
        (Rule(1.0, axis="x", affect_domain=False), Band(2.0, 3.0, axis="x")),
        _frame(metric=["A"]),
        axis_kinds={"x": "numeric"},
        plot_label="Plot",
        row_identities=[("A", None, None, None)],
    )
    assert domain_values(prepared.by_row[0], axis="x") == [2.0, 3.0]


def test_non_finite_field_values_are_rejected():
    with pytest.raises(SpecError, match="finite"):
        prepare_annotations(
            (Rule("target", axis="x"),),
            _frame(target=[float("inf")]),
            axis_kinds={"x": "numeric"},
            plot_label="Plot",
            row_identities=[("A", None, None, None)],
        )


def test_duplicate_and_coincident_marks_are_preserved_in_declaration_order():
    prepared = prepare_annotations(
        (Rule(1.0, axis="x"), Rule(1.0, axis="x"), Band(1.0, 1.0, axis="x")),
        _frame(metric=["A"]),
        axis_kinds={"x": "numeric"},
        plot_label="Plot",
        row_identities=[("A", None, None, None)],
    )
    assert domain_values(prepared.by_row[0], axis="x") == [1.0, 1.0, 1.0, 1.0]
