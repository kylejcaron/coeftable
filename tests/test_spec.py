import pytest

from coeftable.format import Number, Percent
from coeftable.spec import (
    CoefTable,
    ColumnNotFoundError,
    Estimate,
    Forest,
    Passthrough,
    Sparkline,
    SpecError,
    _domain_key,
    validate_columns,
)
from coeftable.theme import MONO, Direction

DATA = {"metric": ["a"], "mean": [1.0], "lb": [0.5], "ub": [1.5]}


def test_constructor_sugar_declares_one_estimate():
    table = CoefTable(DATA, rows="metric", estimate="mean", ci=("lb", "ub"))
    assert len(table.columns) == 1
    column = table.columns[0]
    assert isinstance(column, Estimate)
    assert column.label == "Estimate"
    assert column.value == "mean"
    assert column.ci == ("lb", "ub")


def test_chain_methods_append_in_call_order():
    table = (
        CoefTable(DATA, rows="metric")
        .estimate("A", "mean", ci=("lb", "ub"))
        .estimate("B", "mean", fmt=Percent())
        .forest("Plot", of="A")
        .passthrough("Note", "metric")
    )
    assert [c.label for c in table.columns] == ["A", "B", "Plot", "Note"]


def test_sugar_is_prepended_before_columns_argument():
    table = CoefTable(
        DATA,
        rows="metric",
        estimate="mean",
        ci=("lb", "ub"),
        columns=[Estimate("Later", "mean")],
    )
    assert [c.label for c in table.columns] == ["Estimate", "Later"]


def test_chain_does_not_mutate_the_original():
    base = CoefTable(DATA, rows="metric").estimate("A", "mean")
    extended = base.estimate("B", "mean")
    assert len(base.columns) == 1
    assert len(extended.columns) == 2
    assert base is not extended


def test_header_and_theme_and_direction_are_chainable():
    table = (
        CoefTable(DATA, rows="metric")
        .estimate("A", "mean")
        .header("Title", "Subtitle")
        .with_theme(MONO)
        .with_direction("lower_is_better")
    )
    assert table.title == "Title"
    assert table.subtitle == "Subtitle"
    assert table.theme is MONO
    assert table.direction == "lower_is_better"


def test_forest_referencing_unknown_estimate_is_a_spec_error():
    with pytest.raises(SpecError, match="Plot"):
        validate_columns((Estimate("A", "mean", ci=("lb", "ub")), Forest("Plot", of="Nope")))


def test_forest_bound_to_ci_less_estimate_is_a_spec_error():
    with pytest.raises(SpecError, match="confidence interval"):
        validate_columns((Estimate("A", "mean"), Forest("Plot", of="A")))


def test_duplicate_labels_are_a_spec_error():
    with pytest.raises(SpecError, match="duplicate"):
        validate_columns((Estimate("A", "mean"), Passthrough("A", "metric")))


def test_no_columns_is_a_spec_error():
    with pytest.raises(SpecError, match="no columns"):
        validate_columns(())


def test_valid_spec_passes_validation():
    validate_columns((Estimate("A", "mean", ci=("lb", "ub")), Forest("Plot", of="A")))


def test_inverted_sparkline_domain_is_a_spec_error():
    with pytest.raises(SpecError, match=r"'S'.*strictly increasing.*100.0, 1.0"):
        validate_columns((Sparkline("S", value="mean", domain=(100.0, 1.0)),))


def test_inverted_forest_domain_is_a_spec_error():
    with pytest.raises(SpecError, match=r"'Plot'.*strictly increasing.*100.0, 1.0"):
        validate_columns(
            (Estimate("A", "mean", ci=("lb", "ub")), Forest("Plot", of="A", domain=(100.0, 1.0)))
        )


def test_equal_domain_bounds_are_a_spec_error():
    with pytest.raises(SpecError, match="strictly increasing"):
        validate_columns((Sparkline("S", value="mean", domain=(5.0, 5.0)),))


@pytest.mark.parametrize("bad", [-5, 0])
def test_non_positive_max_domain_is_a_spec_error(bad):
    with pytest.raises(SpecError, match=rf"'S'.*max_domain must be > 0.*{bad}"):
        validate_columns((Sparkline("S", value="mean", max_domain=bad),))


def test_valid_domain_and_max_domain_pass_validation():
    validate_columns((Sparkline("S", value="mean", domain=(1.0, 100.0), max_domain=None),))
    validate_columns((Sparkline("T", value="mean", max_domain=5),))


def test_domain_key_rejects_unknown_scale():
    bogus = Sparkline("S", value="mean")
    object.__setattr__(bogus, "scale", "galaxy")
    with pytest.raises(SpecError, match="unknown scale"):
        _domain_key(bogus, "row", "group", "split")


def test_specs_are_frozen_and_hashable():
    assert isinstance(hash(Estimate("A", "mean")), int)
    assert Estimate("A", "mean") == Estimate("A", "mean")


def test_estimate_default_format_is_number():
    assert isinstance(Estimate("A", "mean").fmt, Number)


def test_column_not_found_error_is_available():
    assert issubclass(ColumnNotFoundError, Exception)


def test_direction_for_scalar_direction():
    table = CoefTable(DATA, rows="metric", estimate="mean").estimate("A", "mean")
    assert table.direction_for("a") == "higher_is_better"


def test_direction_for_mapping_lookup():
    direction: dict[str, Direction] = {"revenue": "lower_is_better"}
    table = CoefTable(
        DATA,
        rows="metric",
        estimate="mean",
        direction=direction,
    )
    assert table.direction_for("revenue") == "lower_is_better"


def test_direction_for_mapping_default_fallback():
    direction: dict[str, Direction] = {"revenue": "lower_is_better"}
    table = CoefTable(
        DATA,
        rows="metric",
        estimate="mean",
        direction=direction,
    )
    assert table.direction_for("other") == "higher_is_better"
