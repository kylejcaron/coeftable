"""Row identity, ordering and footer scheduling for `resolve()`.

Everything here operates on plain row/nest/group/split values and opaque,
column-supplied domain keys; nothing in this module inspects which column
kind (`Estimate`, `Forest`, `Passthrough`) it is laying out.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from coeftable.spec import SpecError


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


@dataclass(frozen=True)
class Grid:
    """Row identity and ordering for one resolved table, independent of column kind.

    Parameters
    ----------
    ordered
        Output rows as `(row key, nest key)` identities, in display order.
    unique_rows
        Distinct row keys, in the same order banding and dividers key off.
    splits
        Distinct split-column values, in display order, or `[None]` when the
        table has no split column.
    source_index
        Maps `((row key, nest key), split)` to the input frame row backing it.
    row_group
        The row-group value for each `ordered` position, falling back across
        splits via `_first_source` when the first split has no data there.
    """

    ordered: list[tuple[Any, Any]]
    unique_rows: list[Any]
    splits: list[Any]
    source_index: dict[tuple[tuple[Any, Any], Any], int]
    row_group: list[Any]


def build_grid(
    row_keys: list[Any],
    nest_keys: list[Any],
    group_keys: list[Any],
    split_keys: list[Any],
    *,
    sort_rows: bool,
    has_splits: bool,
) -> Grid:
    """Compute row identity, display order and source lookup for one frame.

    Parameters
    ----------
    row_keys, nest_keys, group_keys, split_keys
        Per-input-row values, aligned to the frame's row order.
    sort_rows
        Sort unique row keys lexically instead of by first appearance.
    has_splits
        Whether the table declares a split column; when False every row
        belongs to the single implicit `None` split.

    Returns
    -------
    Grid
        Row identity, order and source lookup.

    Raises
    ------
    SpecError
        When the same (rows, nest, split_columns) combination appears more
        than once in the input frame.
    """
    n = len(row_keys)
    identities = [(row_keys[i], nest_keys[i]) for i in range(n)]
    unique_rows = _ordered_unique([r for r, _ in identities], sort=sort_rows)
    ordered: list[tuple[Any, Any]] = []
    for row_key in unique_rows:
        for identity in identities:
            if identity[0] == row_key and identity not in ordered:
                ordered.append(identity)

    splits = _ordered_unique(split_keys, sort=sort_rows) if has_splits else [None]
    source_index: dict[tuple[tuple[Any, Any], Any], int] = {}
    for i in range(n):
        key = (identities[i], split_keys[i])
        if key in source_index:
            row_label, nest_label = identities[i]
            extra = f", split={split_keys[i]!r}" if split_keys[i] is not None else ""
            raise SpecError(
                f"Duplicate input row for row={row_label!r}, nest={nest_label!r}{extra}"
                f" — each (rows, nest, split_columns) combination "
                f"must appear at most once."
            )
        source_index[key] = i

    row_group = [group_keys[_first_source(source_index, identity, splits)] for identity in ordered]

    return Grid(
        ordered=ordered,
        unique_rows=unique_rows,
        splits=splits,
        source_index=source_index,
        row_group=row_group,
    )


@dataclass(frozen=True)
class AssembledRows:
    """Final row layout: data rows interleaved with any scheduled footer rows.

    Parameters
    ----------
    layout_rows, layout_nest, layout_group
        Per-row values for the rows/nest/groups layout columns.
    band_rows, divider_rows, axis_rows
        Zero-based indices into the final row sequence.
    cells
        Rendered cell text per display column, one entry per final row.
    """

    layout_rows: list[str]
    layout_nest: list[str]
    layout_group: list[Any]
    band_rows: list[int]
    divider_rows: list[int]
    axis_rows: list[int]
    cells: dict[str, list[str]]


def assemble_rows(
    grid: Grid,
    display_columns: list[str],
    cell_values: dict[str, list[str]],
    footer_keys: dict[str, list[list[Any]]],
    render_footer: Callable[[dict[str, list[Any]]], dict[str, str]],
) -> AssembledRows:
    """Interleave rendered cells with footer rows, and lay out band/dividers.

    A column's footer fires immediately after the last row (in display order)
    whose domain key it shares -- "last" meaning no later row, at any split,
    carries a matching key. Checking that is O(rows^2 x splits): for every
    row, every still-open column's key set is compared against every later
    row's key set. This mirrors the lookahead that used to run inline in
    `resolve()`; it is not optimised.

    Parameters
    ----------
    grid
        Row identity and order, from `build_grid`.
    display_columns
        Output column names, in display order.
    cell_values
        Rendered cell text per display column, one entry per `grid.ordered`
        position (from calling each column's `cell` before this pass).
    footer_keys
        For each column label with a footer to schedule, its domain key per
        `(grid.ordered position, split index)`; see `Prepared.footer_keys`.
        Columns with nothing to schedule are absent.
    render_footer
        Called with the labels (with their keys) due at this row; returns
        the rendered footer text per display column.

    Returns
    -------
    AssembledRows
        The frame-ready layout columns, band/divider/axis indices and cells.
    """
    cells: dict[str, list[str]] = {name: [] for name in display_columns}
    layout_rows: list[str] = []
    layout_nest: list[str] = []
    layout_group: list[Any] = []
    band_rows: list[int] = []
    divider_rows: list[int] = []
    axis_rows: list[int] = []
    emitted: dict[str, set[Any]] = {label: set() for label in footer_keys}

    def blank_row() -> None:
        for name in display_columns:
            cells[name].append("")

    previous_row_key: Any = None
    for position, (row_key, nest_key) in enumerate(grid.ordered):
        first_of_key = row_key != previous_row_key
        if first_of_key and previous_row_key is not None:
            divider_rows.append(len(layout_rows))
        if grid.unique_rows.index(row_key) % 2 == 0:
            band_rows.append(len(layout_rows))
        layout_rows.append(f"<b>{row_key}</b>" if first_of_key else "")
        layout_nest.append("" if nest_key is None else str(nest_key))
        layout_group.append(grid.row_group[position])
        previous_row_key = row_key

        for name in display_columns:
            cells[name].append(cell_values[name][position])

        pending: dict[str, list[Any]] = {}
        for label, keys_by_position in footer_keys.items():
            keys = keys_by_position[position]
            key_set = set(keys)
            if key_set & emitted[label]:
                continue
            future = any(
                key in key_set
                for later_keys in keys_by_position[position + 1 :]
                for key in later_keys
            )
            if not future:
                pending[label] = keys

        if pending:
            blank_row()
            layout_rows.append("")
            layout_nest.append("")
            layout_group.append(layout_group[-1])
            axis_rows.append(len(layout_rows) - 1)
            for label, keys in pending.items():
                emitted[label].update(keys)
            for name, text in render_footer(pending).items():
                cells[name][-1] = text

    return AssembledRows(
        layout_rows=layout_rows,
        layout_nest=layout_nest,
        layout_group=layout_group,
        band_rows=band_rows,
        divider_rows=divider_rows,
        axis_rows=axis_rows,
        cells=cells,
    )
