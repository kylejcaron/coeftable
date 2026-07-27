"""Resolve a table specification and a frame into rendered cells."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import narwhals as nw

from coeftable.format import is_missing, render_interval
from coeftable.spec import (
    CoefTable,
    Column,
    ColumnNotFoundError,
    Estimate,
    Forest,
    Passthrough,
    validate_columns,
)
from coeftable.svg import forest_axis, forest_bar
from coeftable.theme import role_for

SPLIT_JOINER = "\u2009|\u2009"


@dataclass(frozen=True)
class Resolved:
    """A specification resolved against a frame, ready to render.

    Parameters
    ----------
    frame
        Native frame of rendered cell strings, in the caller's own backend.
    display_columns
        Output column names in display order, excluding layout columns.
    labels
        Mapping from output column name to the header text to show.
    spanners
        Mapping from split value to the output columns it spans.
    group_column
        Name of the row-group column, if any.
    band_rows, divider_rows, axis_rows
        Zero-based row indices for banding, dividers and axis rows.
    markdown_columns
        Output columns whose contents are HTML.
    """

    frame: Any
    display_columns: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    spanners: dict[str, list[str]] = field(default_factory=dict)
    group_column: str | None = None
    band_rows: list[int] = field(default_factory=list)
    divider_rows: list[int] = field(default_factory=list)
    axis_rows: list[int] = field(default_factory=list)
    markdown_columns: list[str] = field(default_factory=list)


def _required_columns(table: CoefTable) -> list[str]:
    names: list[str] = []
    for key in (table.rows, table.nest, table.groups, table.split_columns):
        if key is not None:
            names.append(key)
    for column in table.columns:
        if isinstance(column, Estimate):
            names.append(column.value)
            if column.ci is not None:
                names.extend(column.ci)
        elif isinstance(column, Passthrough):
            names.append(column.column)
    return names


def _check_columns(frame: nw.DataFrame, table: CoefTable) -> None:
    available = list(frame.columns)
    missing = [n for n in _required_columns(table) if n not in available]
    if missing:
        raise ColumnNotFoundError(
            f"Columns {missing} are not in the frame. Available columns: {available}."
        )


def _numeric(frame: nw.DataFrame, name: str) -> list[float | None]:
    values = frame[name].to_list()
    out: list[float | None] = []
    for value in values:
        if value is None:
            out.append(None)
            continue
        try:
            out.append(float(value))
        except (TypeError, ValueError):
            # Some missing-value sentinels (pd.NA, pd.NaT, masked arrays) are
            # not None but should be treated as missing rather than rejected.
            s = str(value)
            if s in ("<NA>", "NaT", "nan"):
                out.append(None)
            else:
                raise TypeError(
                    f"Column {name!r} must be numeric to be used as an estimate or "
                    f"bound; found {value!r}."
                ) from None
    return out


def _ordered_unique(values: list[Any], *, sort: bool) -> list[Any]:
    seen: list[Any] = []
    for value in values:
        if value not in seen:
            seen.append(value)
    return sorted(seen, key=str) if sort else seen


def _first_source(
    source_index: dict[tuple[tuple[Any, Any], Any], int],
    identity: tuple[Any, Any],
    splits: list[Any],
) -> int:
    """Return the input row backing `identity`, preferring the first split value.

    Split-column data is often sparse, so the first split value may have no row
    for a given identity. Falling back to any split keeps layout metadata such
    as the row-group value resolvable.
    """
    for split in splits:
        found = source_index.get((identity, split))
        if found is not None:
            return found
    raise KeyError(f"No input row for {identity!r} under any split value.")


def _finite(values: list[float | None]) -> list[float]:
    return [v for v in values if v is not None and math.isfinite(v)]


def _domain_key(column: Forest, row_key: Any, group: Any, split: Any) -> Any:
    match column.scale:
        case "table":
            return ("table",)
        case "row_group":
            return ("group", group)
        case "split_column":
            return ("split", split)
        case "row":
            return ("row", row_key)


def _pad_domain(values: list[float], ref: float) -> tuple[float, float]:
    if not values:
        return (ref - 1.0, ref + 1.0)
    low, high = min(values), max(values)
    low, high = min(low, ref), max(high, ref)
    if low == high:
        return (low - 1.0, high + 1.0)
    margin = (high - low) * 0.08
    return (low - margin, high + margin)


def resolve(table: CoefTable) -> Resolved:
    """Resolve `table` against its frame.

    Parameters
    ----------
    table
        The specification to resolve.

    Returns
    -------
    Resolved
        Rendered cells plus the layout metadata `render` needs.

    Raises
    ------
    ColumnNotFoundError
        When a named column is absent from the frame.
    TypeError
        When an estimate or bound column is not numeric.
    SpecError
        When the column specification is inconsistent.
    """
    validate_columns(table.columns)
    frame = nw.from_native(table.data, eager_only=True)
    _check_columns(frame, table)

    n = len(frame)
    row_keys = frame[table.rows].to_list() if table.rows else [""] * n
    nest_keys = frame[table.nest].to_list() if table.nest else [None] * n
    group_keys = frame[table.groups].to_list() if table.groups else [None] * n
    split_keys = frame[table.split_columns].to_list() if table.split_columns else [None] * n

    numeric: dict[str, list[float | None]] = {}
    verbatim: dict[str, list[Any]] = {}
    for column in table.columns:
        if isinstance(column, Estimate):
            numeric[column.value] = _numeric(frame, column.value)
            if column.ci is not None:
                for name in column.ci:
                    numeric[name] = _numeric(frame, name)
        elif isinstance(column, Passthrough):
            verbatim[column.column] = frame[column.column].to_list()

    # Forest domains, keyed by (forest label, domain key).
    domains: dict[tuple[str, Any], tuple[float, float]] = {}
    estimates = {c.label: c for c in table.columns if isinstance(c, Estimate)}
    for column in table.columns:
        if not isinstance(column, Forest):
            continue
        source = estimates[column.of]
        assert source.ci is not None  # noqa: S101 - guaranteed by validate_columns
        low_name, high_name = source.ci
        buckets: dict[Any, list[float]] = {}
        for i in range(n):
            key = _domain_key(column, row_keys[i], group_keys[i], split_keys[i])
            bucket = buckets.setdefault(key, [])
            bucket.extend(
                _finite([numeric[source.value][i], numeric[low_name][i], numeric[high_name][i]])
            )
        for key, values in buckets.items():
            domains[(column.label, key)] = column.domain or _pad_domain(values, column.ref)

    # Output row identity: one output row per (row key, nest key).
    identities = [(row_keys[i], nest_keys[i]) for i in range(n)]
    unique_rows = _ordered_unique([r for r, _ in identities], sort=table.sort_rows)
    ordered: list[tuple[Any, Any]] = []
    for row_key in unique_rows:
        for identity in identities:
            if identity[0] == row_key and identity not in ordered:
                ordered.append(identity)

    splits = _ordered_unique(split_keys, sort=table.sort_rows) if table.split_columns else [None]
    source_index = {(identities[i], split_keys[i]): i for i in range(n)}

    def output_name(column: Column, split: Any) -> str:
        return column.label if split is None else f"{split}{SPLIT_JOINER}{column.label}"

    display_columns: list[str] = []
    labels: dict[str, str] = {}
    spanners: dict[str, list[str]] = {}
    for split in splits:
        for column in table.columns:
            name = output_name(column, split)
            display_columns.append(name)
            labels[name] = column.label
            if split is not None:
                spanners.setdefault(str(split), []).append(name)

    cells: dict[str, list[str]] = {name: [] for name in display_columns}
    layout_rows: list[str] = []
    layout_nest: list[str] = []
    layout_group: list[Any] = []
    band_rows: list[int] = []
    divider_rows: list[int] = []
    axis_rows: list[int] = []
    emitted_axis: set[tuple[str, Any]] = set()

    def blank_row() -> None:
        for name in display_columns:
            cells[name].append("")

    previous_row_key: Any = None
    for position, (row_key, nest_key) in enumerate(ordered):
        first_of_key = row_key != previous_row_key
        if first_of_key and previous_row_key is not None:
            divider_rows.append(len(layout_rows))
        if unique_rows.index(row_key) % 2 == 0:
            band_rows.append(len(layout_rows))
        layout_rows.append(f"<b>{row_key}</b>" if first_of_key else "")
        layout_nest.append("" if nest_key is None else str(nest_key))
        layout_group.append(group_keys[_first_source(source_index, (row_key, nest_key), splits)])
        previous_row_key = row_key

        direction = table.direction_for(str(row_key))
        for split in splits:
            index = source_index.get(((row_key, nest_key), split))
            for column in table.columns:
                name = output_name(column, split)
                if index is None:
                    cells[name].append("")
                elif isinstance(column, Passthrough):
                    cells[name].append(str(verbatim[column.column][index]))
                elif isinstance(column, Estimate):
                    low, high = (None, None)
                    if column.ci is not None:
                        low = numeric[column.ci[0]][index]
                        high = numeric[column.ci[1]][index]
                    cells[name].append(
                        render_interval(
                            numeric[column.value][index],
                            low,
                            high,
                            fmt=column.fmt,
                            style=column.ci_style,
                            theme=table.theme,
                        )
                    )
                else:
                    source = estimates[column.of]
                    assert source.ci is not None  # noqa: S101
                    value = numeric[source.value][index]
                    low = numeric[source.ci[0]][index]
                    high = numeric[source.ci[1]][index]
                    if is_missing(value):
                        cells[name].append("")
                        continue
                    key = _domain_key(column, row_key, layout_group[-1], split)
                    domain = domains[(column.label, key)]
                    role = (
                        table.color_rule(value, low, high, column.ref)
                        if table.color_rule is not None
                        else role_for(low, high, column.ref, direction)
                    )
                    cells[name].append(
                        forest_bar(
                            value,
                            low,
                            high,
                            domain=domain,
                            ref=column.ref,
                            color=table.theme.color(role),
                            theme=table.theme,
                            width=column.width,
                        )
                    )

        # Emit axis rows after the last data row using each domain.
        pending: list[Forest] = []
        for column in table.columns:
            if not isinstance(column, Forest) or not column.show_axis:
                continue
            keys = {_domain_key(column, row_key, layout_group[-1], split) for split in splits}
            if any((column.label, k) in emitted_axis for k in keys):
                continue
            future = any(
                _domain_key(
                    column,
                    later_row,
                    group_keys[_first_source(source_index, (later_row, later_nest), splits)],
                    split,
                )
                in keys
                for later_row, later_nest in ordered[position + 1 :]
                for split in splits
            )
            if not future:
                pending.append(column)
        if pending:
            blank_row()
            layout_rows.append("")
            layout_nest.append("")
            layout_group.append(layout_group[-1])
            axis_rows.append(len(layout_rows) - 1)
            for column in pending:
                source = estimates[column.of]
                for split in splits:
                    key = _domain_key(column, row_key, layout_group[-1], split)
                    emitted_axis.add((column.label, key))
                    cells[output_name(column, split)][-1] = forest_axis(
                        domain=domains[(column.label, key)],
                        ref=column.ref,
                        fmt=column.axis_fmt or source.fmt,
                        theme=table.theme,
                        width=column.width,
                    )

    data: dict[str, list[Any]] = {}
    if table.groups:
        data[table.groups] = layout_group
    if table.rows:
        data[table.rows] = layout_rows
    if table.nest:
        data[table.nest] = layout_nest
    for name in display_columns:
        data[name] = cells[name]

    leading = [c for c in (table.groups, table.rows, table.nest) if c]
    markdown = [c for c in (table.rows, table.nest) if c] + display_columns

    return Resolved(
        frame=nw.from_dict(data, backend=nw.get_native_namespace(frame)).to_native(),
        display_columns=[*(leading[1:] if table.groups else leading), *display_columns],
        labels=labels,
        spanners=spanners,
        group_column=table.groups,
        band_rows=band_rows,
        divider_rows=divider_rows,
        axis_rows=axis_rows,
        markdown_columns=markdown,
    )
