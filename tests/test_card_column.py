from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import narwhals as nw
import pandas as pd
import polars as pl
import pyarrow as pa
import pytest

from coeftable.cards import Card, TextBlock
from coeftable.errors import ColumnNotFoundError, SpecError
from coeftable.frame import resolve
from coeftable.spec import CardColumn, CoefTable


def _card(title: str) -> Card:
    return Card(title, content=(TextBlock(f"body:{title}"),), width=180)


def _resolved_values(table: CoefTable, column: str = "Summary") -> list[str]:
    resolved = resolve(table)
    return nw.from_native(resolved.frame)[column].to_list()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({}, "exactly one of cards= or factory="),
        ({"cards": [_card("A")], "factory": lambda row: None}, "exactly one"),
        ({"cards": [_card("A")], "by": "metric"}, "by= is only valid with mapping"),
        ({"cards": {"A": _card("A")}}, "mapping input requires by="),
        ({"cards": {"A": _card("A")}, "by": ()}, "by= must be"),
        ({"cards": {"A": _card("A")}, "by": ("metric", "metric")}, "unique"),
        ({"cards": {"A": _card("A")}, "by": ("metric", "")}, "non-empty"),
        ({"factory": 7}, "factory must be callable"),
        ({"cards": [object()]}, r"cards\[0\] must be a Card or None"),
        (
            {"cards": {"A": object()}, "by": "metric"},
            r"cards\['A'\] must be a Card or None",
        ),
    ],
)
def test_card_column_rejects_invalid_source_contract(kwargs: dict[str, Any], message: str):
    with pytest.raises(SpecError, match=message):
        CardColumn("Summary", **kwargs)


def test_card_column_snapshots_sequence_and_mapping_inputs():
    first = _card("A")
    second = _card("B")
    sequence = [first]
    mapping: dict[object, Card | None] = {"A": first}
    positional = CardColumn("Summary", cards=sequence)
    keyed = CardColumn("Summary", cards=mapping, by="metric")

    sequence[0] = second
    mapping["A"] = second

    assert positional.cards == (first,)
    keyed_cards = keyed.cards
    assert isinstance(keyed_cards, Mapping)
    assert not isinstance(keyed_cards, Sequence)
    assert keyed_cards["A"] is first
    assert keyed.by == ("metric",)


def test_mapping_sources_are_declared_and_other_modes_read_no_required_columns():
    assert tuple(CardColumn("Summary", cards={}, by=("metric", "variant")).sources()) == (
        "metric",
        "variant",
    )
    assert tuple(CardColumn("Summary", cards=[]).sources()) == ()
    assert tuple(CardColumn("Summary", factory=lambda row: None).sources()) == ()


def test_sequence_follows_source_indices_after_table_sorting():
    table = CoefTable(
        pl.DataFrame({"metric": ["B", "A"]}),
        rows="metric",
        sort_rows=True,
        columns=(CardColumn("Summary", cards=[_card("for-B"), _card("for-A")]),),
    )
    values = _resolved_values(table)
    assert "for-A" in values[0]
    assert "for-B" in values[1]


def test_sequence_length_must_match_source_rows():
    table = CoefTable(
        pl.DataFrame({"metric": ["A", "B"]}),
        rows="metric",
        columns=(CardColumn("Summary", cards=[_card("A")]),),
    )
    with pytest.raises(SpecError, match="expected 2 source rows, got 1"):
        resolve(table)


def test_mapping_supports_scalar_and_tuple_keys_blank_entries_and_reuse():
    scalar_frame = pl.DataFrame({"metric": ["A", "A", "B"], "variant": ["x", "y", "z"]})
    scalar = CoefTable(
        scalar_frame,
        rows="metric",
        nest="variant",
        columns=(CardColumn("Summary", cards={"A": _card("shared")}, by="metric"),),
    )
    scalar_values = _resolved_values(scalar)
    assert sum("shared" in value for value in scalar_values) == 2
    assert scalar_values[2] == ""

    tuple_keyed = CoefTable(
        pl.DataFrame({"metric": ["A", "A"], "variant": ["x", "y"]}),
        rows="metric",
        nest="variant",
        columns=(
            CardColumn(
                "Summary",
                cards={("A", "x"): _card("A/x"), ("unused", "key"): _card("unused")},
                by=("metric", "variant"),
            ),
        ),
    )
    tuple_values = _resolved_values(tuple_keyed)
    assert "A/x" in tuple_values[0]
    assert tuple_values[1] == ""
    assert all("unused" not in value for value in tuple_values)


def test_mapping_and_factory_normalize_pandas_nan_to_none():
    frame = pd.DataFrame({"metric": ["A", "B"], "lookup": [1.0, None]})
    keyed = CoefTable(
        frame,
        rows="metric",
        columns=(CardColumn("Summary", cards={None: _card("missing")}, by="lookup"),),
    )
    assert "missing" in _resolved_values(keyed)[1]

    seen: list[object] = []

    def factory(row: Mapping[str, Any]) -> None:
        seen.append(row["lookup"])
        return None

    generated = CoefTable(
        frame,
        rows="metric",
        columns=(CardColumn("Summary", factory=factory),),
    )
    resolve(generated)
    assert seen == [1.0, None]


def test_mapping_reports_missing_by_column_through_existing_error():
    table = CoefTable(
        pl.DataFrame({"metric": ["A"]}),
        rows="metric",
        columns=(CardColumn("Summary", cards={}, by="missing"),),
    )
    with pytest.raises(ColumnNotFoundError, match="missing"):
        resolve(table)


def test_mapping_reports_unhashable_source_key_with_context():
    table = CoefTable(
        pl.DataFrame({"metric": ["A"], "lookup": [["not", "hashable"]]}),
        rows="metric",
        columns=(CardColumn("Summary", cards={}, by="lookup"),),
    )
    with pytest.raises(
        SpecError,
        match=r"CardColumn 'Summary'.*source row 0.*by=\('lookup',\)",
    ):
        resolve(table)


def test_factory_receives_immutable_complete_rows_once_per_resolution():
    seen: list[Mapping[str, Any]] = []

    def factory(row: Mapping[str, Any]) -> Card:
        with pytest.raises(TypeError):
            row["metric"] = "changed"  # ty: ignore[invalid-assignment]
        seen.append(row)
        return _card(f"{row['metric']}:{row['value']}")

    table = CoefTable(
        pl.DataFrame({"metric": ["A", "B"], "method": ["OLS", "DiD"], "value": [1, 2]}),
        rows="metric",
        split_columns="method",
        columns=(CardColumn("Summary", factory=factory),),
    )
    resolved = resolve(table)
    assert [dict(row) for row in seen] == [
        {"metric": "A", "method": "OLS", "value": 1},
        {"metric": "B", "method": "DiD", "value": 2},
    ]
    native = nw.from_native(resolved.frame)
    rendered = [
        value
        for output_columns in resolved.spanners.values()
        for output_column in output_columns
        for value in native[output_column].to_list()
    ]
    assert sum("A:1" in value for value in rendered) == 1
    assert len(seen) == 2
    resolve(table)
    assert len(seen) == 4


def test_factory_rejects_bad_return_and_chains_exceptions():
    def bad_factory(row: Mapping[str, Any]) -> Any:
        return object()

    bad_return = CoefTable(
        pl.DataFrame({"metric": ["A"]}),
        rows="metric",
        columns=(CardColumn("Summary", factory=bad_factory),),
    )
    with pytest.raises(SpecError, match="factory returned object at source row 0"):
        resolve(bad_return)

    def explode(row: Mapping[str, Any]) -> Card:
        raise ValueError(f"bad {row['metric']}")

    raised = CoefTable(
        pl.DataFrame({"metric": ["A"]}),
        rows="metric",
        columns=(CardColumn("Summary", factory=explode),),
    )
    with pytest.raises(SpecError, match="factory failed at source row 0") as exc_info:
        resolve(raised)
    assert isinstance(exc_info.value.__cause__, ValueError)


def test_cell_uses_public_card_html_and_none_is_blank():
    card = _card("exact")
    table = CoefTable(
        pl.DataFrame({"metric": ["A", "B"]}),
        rows="metric",
        columns=(CardColumn("Summary", cards=[card, None]),),
    )
    assert _resolved_values(table) == [card.as_raw_html(), ""]


_MAKERS = {"pandas": pd.DataFrame, "polars": pl.DataFrame, "pyarrow": pa.table}


@pytest.mark.parametrize("backend", ["pandas", "polars", "pyarrow"])
@pytest.mark.parametrize("mode", ["sequence", "mapping", "factory"])
def test_public_builder_places_every_source_mode_across_backends(backend: str, mode: str):
    make = _MAKERS[backend]
    frame = make({"metric": ["B", "A"], "lookup": [2.0, 1.0]})
    calls: list[Mapping[str, Any]] = []
    base = CoefTable(frame, rows="metric", sort_rows=True)
    if mode == "sequence":
        table = base.card("Summary", cards=[_card("for-B"), _card("for-A")])
    elif mode == "mapping":
        table = base.card("Summary", cards={"A": _card("for-A")}, by="metric")
    else:

        def factory(row: Mapping[str, Any]) -> Card:
            calls.append(row)
            return _card(f"for-{row['metric']}")

        table = base.card("Summary", factory=factory)

    values = _resolved_values(table)
    assert "for-A" in values[0]
    if mode == "mapping":
        assert values[1] == ""
    else:
        assert "for-B" in values[1]
    if mode == "factory":
        assert len(calls) == 2
        assert all(set(row) == {"metric", "lookup"} for row in calls)


@pytest.mark.parametrize("backend", ["pandas", "polars", "pyarrow"])
def test_mapping_and_factory_nulls_are_backend_neutral(backend: str):
    make = _MAKERS[backend]
    frame = make({"metric": ["A", "B"], "lookup": [1.0, None]})
    keyed = CoefTable(frame, rows="metric").card(
        "Summary",
        cards={None: _card("missing")},
        by="lookup",
    )
    assert "missing" in _resolved_values(keyed)[1]

    seen: list[object] = []

    def factory(row: Mapping[str, Any]) -> None:
        seen.append(row["lookup"])
        return None

    resolve(CoefTable(frame, rows="metric").card("Summary", factory=factory))
    assert seen == [1.0, None]


def test_mapping_placement_survives_groups_nesting_splits_and_missing_intersections():
    frame = pl.DataFrame(
        {
            "area": ["Core", "Core", "Ops"],
            "metric": ["Revenue", "Revenue", "Latency"],
            "variant": ["B", "B", "C"],
            "method": ["OLS", "DiD", "OLS"],
        }
    )
    cards: dict[object, Card | None] = {
        ("Core", "Revenue", "OLS"): _card("core-revenue-ols"),
        ("Core", "Revenue", "DiD"): _card("core-revenue-did"),
        ("Ops", "Latency", "OLS"): _card("ops-latency-ols"),
    }
    resolved = resolve(
        CoefTable(
            frame,
            rows="metric",
            nest="variant",
            groups="area",
            split_columns="method",
        ).card("Summary", cards=cards, by=("area", "metric", "method"))
    )
    native = nw.from_native(resolved.frame)
    ols, did = resolved.spanners["OLS"][0], resolved.spanners["DiD"][0]
    assert "core-revenue-ols" in native[ols].to_list()[0]
    assert "core-revenue-did" in native[did].to_list()[0]
    assert "ops-latency-ols" in native[ols].to_list()[1]
    assert native[did].to_list()[1] == ""


def test_card_cells_stay_blank_on_generated_plot_footer_rows():
    frame = pl.DataFrame({"metric": ["A"], "estimate": [1.0], "low": [0.5], "high": [1.5]})
    resolved = resolve(
        CoefTable(frame, rows="metric")
        .estimate("Estimate", "estimate", ci=("low", "high"))
        .forest("Plot", of="Estimate")
        .card("Summary", cards=[_card("A")])
    )
    values = nw.from_native(resolved.frame)["Summary"].to_list()
    assert "A" in values[0]
    assert values[-1] == ""
    assert resolved.card_columns == ["Summary"]
