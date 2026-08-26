"""Resolve a table specification and a frame into rendered cells."""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any

import narwhals as nw

from coeftable.grid import assemble_rows, build_grid
from coeftable.spec import (
    Cell,
    CoefTable,
    Column,
    ColumnNotFoundError,
    Footer,
    Forest,
    Prepared,
    Scan,
    Sparkline,
    SpecError,
    validate_columns,
)
from coeftable.spec import _pad_domain as _pad_domain
from coeftable.spec import _plot_height as _plot_height

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
    shared_axis_rows
        Subset of `axis_rows` whose axis is table-wide (`scale in
        {"table", "split_column"}`) rather than per-group or per-row-key
        -- see `assemble_rows`. `render.py` marks only these for
        `collapsible.py` to leave untagged; the rest stay tied to
        whichever group they belong to.
    markdown_columns
        Output columns whose contents are HTML.
    plot_columns
        Output columns rendering a `Forest` bar or `Sparkline` line plot,
        so the renderer can trim their cell padding to let the SVG fill
        the row.
    """

    frame: Any
    display_columns: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    spanners: dict[str, list[str]] = field(default_factory=dict)
    group_column: str | None = None
    band_rows: list[int] = field(default_factory=list)
    divider_rows: list[int] = field(default_factory=list)
    axis_rows: list[int] = field(default_factory=list)
    shared_axis_rows: list[int] = field(default_factory=list)
    markdown_columns: list[str] = field(default_factory=list)
    plot_columns: list[str] = field(default_factory=list)


def _required_columns(table: CoefTable) -> list[str]:
    names: list[str] = []
    for key in (table.rows, table.nest, table.groups, table.split_columns):
        if key is not None:
            names.append(key)
    for column in table.columns:
        names.extend(column.sources())
    return names


def _check_columns(frame: nw.DataFrame, table: CoefTable) -> None:
    available = list(frame.columns)
    missing = [n for n in _required_columns(table) if n not in available]
    if missing:
        raise ColumnNotFoundError(
            f"Columns {missing} are not in the frame. Available columns: {available}."
        )


def resolve(table: CoefTable) -> Resolved:  # noqa: C901
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

    # A column label colliding with a layout key silently overwrites the
    # layout column in the output frame. Catch it here at spec-check time.
    layout_keys = {n for n in (table.rows, table.nest, table.groups) if n is not None}
    for column in table.columns:
        if column.label in layout_keys:
            raise SpecError(
                f"Column label {column.label!r} collides with layout column "
                f"(rows/nest/groups key {column.label!r}); choose a different label."
            )

    # Two layout roles naming the same column collide in the output frame,
    # which `resolve()` builds keyed by column name -- the later write
    # silently discards the earlier role's values, so the table renders with
    # one role's layout missing. Reject it rather than emit a corrupt table.
    roles = [("rows", table.rows), ("nest", table.nest), ("groups", table.groups)]
    named = [(role, key) for role, key in roles if key is not None]
    for (first_role, first_key), (second_role, second_key) in combinations(named, 2):
        if first_key == second_key:
            raise SpecError(
                f"Layout keys {first_role}= and {second_role}= both name column "
                f"{first_key!r}; each layout role needs its own column."
            )

    # The overlaid `series` dimension cannot also be a table axis: the
    # table's row structure already spends whichever of these an
    # identity maps to, so naming the same column both ways is
    # ambiguous about which grouping wins.
    axis_keys = {n for n in (table.rows, table.nest, table.groups, table.split_columns) if n}
    for column in table.columns:
        if (
            isinstance(column, Sparkline)
            and column.series is not None
            and column.series in axis_keys
        ):
            raise SpecError(
                f"Sparkline column {column.label!r} series={column.series!r} collides "
                "with a table layout key (rows/nest/groups/split_columns); the "
                "overlaid dimension cannot also be a table axis."
            )

    frame = nw.from_native(table.data, eager_only=True)
    _check_columns(frame, table)

    n = len(frame)
    row_keys = frame[table.rows].to_list() if table.rows else [""] * n
    nest_keys = frame[table.nest].to_list() if table.nest else [None] * n
    group_keys = frame[table.groups].to_list() if table.groups else [None] * n
    split_keys = frame[table.split_columns].to_list() if table.split_columns else [None] * n

    scan = Scan(
        frame=frame,
        columns=table.columns,
        row_keys=row_keys,
        nest_keys=nest_keys,
        group_keys=group_keys,
        split_keys=split_keys,
        rows=table.rows,
        nest=table.nest,
        groups=table.groups,
        split_columns=table.split_columns,
    )
    prepared: list[Prepared] = [column.prepare(scan) for column in table.columns]

    grid = build_grid(
        row_keys,
        nest_keys,
        group_keys,
        split_keys,
        sort_rows=table.sort_rows,
        has_splits=table.split_columns is not None,
    )

    def output_name(column: Column, split: Any) -> str:
        return column.label if split is None else f"{split}{SPLIT_JOINER}{column.label}"

    display_columns: list[str] = []
    labels: dict[str, str] = {}
    spanners: dict[str, list[str]] = {}
    plot_columns: list[str] = []
    for split in grid.splits:
        for column in table.columns:
            name = output_name(column, split)
            display_columns.append(name)
            labels[name] = column.label
            if split is not None:
                spanners.setdefault(str(split), []).append(name)
            if isinstance(column, (Forest, Sparkline)):
                plot_columns.append(name)

    # Cell pass: one call to `column.cell` per (row, split, column).
    cell_values: dict[str, list[str]] = {name: [] for name in display_columns}
    for position, (row_key, nest_key, identity_group) in enumerate(grid.ordered):
        direction = table.direction_for(str(row_key))
        group = grid.row_group[position]
        for split in grid.splits:
            index = grid.source_index.get(((row_key, nest_key, identity_group), split))
            for column, prep in zip(table.columns, prepared, strict=True):
                name = output_name(column, split)
                if index is None:
                    cell_values[name].append("")
                    continue
                ctx = Cell(
                    prepared=prep,
                    index=index,
                    row_key=row_key,
                    group=group,
                    split=split,
                    direction=direction,
                    color_rule=table.color_rule,
                    theme=table.theme,
                )
                cell_values[name].append(column.cell(ctx))

    # Footer pass: interleave axis rows wherever a column's domain closes.
    column_by_label: dict[str, Column] = {}
    prepared_by_label: dict[str, Prepared] = {}
    footer_keys: dict[str, list[list[Any]]] = {}
    for column, prep in zip(table.columns, prepared, strict=True):
        column_by_label[column.label] = column
        prepared_by_label[column.label] = prep
        if prep.footer_key is not None:
            key_fn = prep.footer_key
            footer_keys[column.label] = [
                [key_fn(row_key, group, split) for split in grid.splits]
                for (row_key, _nest, group) in grid.ordered
            ]
    # A footer's domain is table-wide only when the column itself says so
    # (see `Prepared.shared_footer`) -- inferring it from `scale` would be
    # wrong for `Sparkline`, whose x-axis footer_key is always constant
    # regardless of `scale` (that setting only buckets each row's own
    # y-domain, never the shared axis's closing scope).
    shared_footer_labels = {
        label for label in footer_keys if prepared_by_label[label].shared_footer
    }

    def render_footer(pending: dict[str, list[Any]]) -> dict[str, str]:
        out: dict[str, str] = {}
        for label, keys in pending.items():
            column = column_by_label[label]
            prep = prepared_by_label[label]
            for split_idx, split in enumerate(grid.splits):
                ctx = Footer(prepared=prep, key=keys[split_idx], theme=table.theme)
                text = column.footer(ctx)
                if text is not None:
                    out[output_name(column, split)] = text
        return out

    assembled = assemble_rows(
        grid, display_columns, cell_values, footer_keys, render_footer, shared_footer_labels
    )

    data: dict[str, list[Any]] = {}
    if table.groups:
        data[table.groups] = assembled.layout_group
    if table.rows:
        data[table.rows] = assembled.layout_rows
    if table.nest:
        data[table.nest] = assembled.layout_nest
    for name in display_columns:
        data[name] = assembled.cells[name]

    leading = [c for c in (table.groups, table.rows, table.nest) if c]
    markdown = [c for c in (table.rows, table.nest) if c] + display_columns

    return Resolved(
        frame=nw.from_dict(data, backend=nw.get_native_namespace(frame)).to_native(),
        display_columns=[*(leading[1:] if table.groups else leading), *display_columns],
        labels=labels,
        spanners=spanners,
        group_column=table.groups,
        band_rows=assembled.band_rows,
        divider_rows=assembled.divider_rows,
        axis_rows=assembled.axis_rows,
        shared_axis_rows=assembled.shared_axis_rows,
        markdown_columns=markdown,
        plot_columns=plot_columns,
    )
