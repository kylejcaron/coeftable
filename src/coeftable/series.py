"""Resolve sparkline series data from list columns or a companion frame.

A `Series` is the shared output of the two front doors described in the
design for the `Sparkline` column: naming list-valued columns directly on
the main frame, or naming scalar columns on a separate long "companion"
frame grouped into the same shape. Both paths funnel through
`_build_series`, so there is exactly one place that validates lengths,
coerces values and detects a temporal x -- callers only ever see a `Series`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, overload

import narwhals as nw

from coeftable._axis import _coerce_temporal, _detect_temporal
from coeftable.errors import SpecError
from coeftable.format import coerce_numeric


@dataclass(frozen=True)
class Series:
    """One resolved sparkline series: parallel points with an optional band.

    `x`, `y`, `lower` and `upper` are the same length. `y[i]` is `None` for
    a gap (breaks the line and ribbon into segments); `lower[i]`/`upper[i]`
    are `None` wherever no interval was declared or that point's bound is
    itself missing.

    Parameters
    ----------
    x
        Projection-ready x positions, already numeric. When `x_temporal` is
        True these are seconds since the Unix epoch (1970-01-01T00:00:00),
        computed as a naive elapsed-time delta rather than through a
        timezone-aware conversion -- so relative spacing between points is
        exact regardless of the host machine's local timezone, even though
        the absolute value is not guaranteed to match a true UTC timestamp
        for timezone-aware input.
    y
        Point estimates.
    lower, upper
        Interval bounds, or all-`None` when no `ci` was declared for this
        series.
    x_temporal
        True when `x` was sourced from a date/datetime/pyarrow-timestamp
        column (list column or companion frame) rather than a plain number.
        Lets a caller choose calendar ticks over decimal ticks without
        re-inspecting the source frame.
    """

    x: list[float | None]
    y: list[float | None]
    lower: list[float | None]
    upper: list[float | None]
    x_temporal: bool = False


def _nan_to_none(values: list[Any]) -> list[Any]:
    """Normalize float ``nan`` key values to ``None``.

    A pandas companion frame surfaces a null key-column cell as
    ``float('nan')``, while identities built from a polars/pyarrow main
    frame carry ``None`` for the same absence. ``nan != None`` (and
    ``nan != nan``), so an unnormalized key would never match its
    identity and the row would silently render blank. Collapsing ``nan``
    to ``None`` on both sides keeps the two aligned.
    """
    return [None if isinstance(v, float) and math.isnan(v) else v for v in values]


def _build_series(
    y_raw: list[Any],
    lower_raw: list[Any] | None,
    upper_raw: list[Any] | None,
    x_raw: list[Any] | None,
    *,
    row_key: Any,
) -> Series:
    """Validate one row's parallel raw lists and coerce them into a `Series`.

    The single choke point both front doors funnel through: list-column
    mode passes one frame row's list cells straight through; companion-frame
    mode passes lists assembled by grouping scalar rows. Either way, this is
    where lengths are checked, x's positional fallback and temporal
    detection happen, and values are coerced to `float | None`.

    Parameters
    ----------
    y_raw
        Raw values for this series' `value`.
    lower_raw, upper_raw
        Raw values for this series' `ci` bounds, or `None` when no `ci` was
        declared at all (as opposed to declared but empty).
    x_raw
        Raw values for this series' `x`, or `None` to fall back to a
        positional index `0..n-1`.
    row_key
        This series' row identity, used only to name the offending row in
        a `SpecError`.

    Returns
    -------
    Series
        The validated, coerced series.

    Raises
    ------
    SpecError
        When `y_raw`, either declared `ci` bound, or a declared `x` do not
        all have the same length.
    """
    lengths: dict[str, int] = {"value": len(y_raw)}
    if lower_raw is not None:
        lengths["lower"] = len(lower_raw)
    if upper_raw is not None:
        lengths["upper"] = len(upper_raw)
    if x_raw is not None:
        lengths["x"] = len(x_raw)
    if len(set(lengths.values())) > 1:
        detail = ", ".join(f"{name}={n}" for name, n in lengths.items())
        raise SpecError(f"Sparkline row {row_key!r}: value/ci/x lengths must match; got {detail}.")

    n = len(y_raw)
    x_temporal = x_raw is not None and _detect_temporal(x_raw)
    x: list[float | None]
    if x_raw is None:
        x = [float(i) for i in range(n)]
    elif x_temporal:
        x = _coerce_temporal(x_raw)
    else:
        x = coerce_numeric(x_raw, subject=f"Sparkline row {row_key!r} x")

    return Series(
        x=x,
        y=coerce_numeric(y_raw, subject=f"Sparkline row {row_key!r} value"),
        lower=(
            [None] * n
            if lower_raw is None
            else coerce_numeric(lower_raw, subject=f"Sparkline row {row_key!r} lower bound")
        ),
        upper=(
            [None] * n
            if upper_raw is None
            else coerce_numeric(upper_raw, subject=f"Sparkline row {row_key!r} upper bound")
        ),
        x_temporal=x_temporal,
    )


def _row_cell(column: list[Any], i: int) -> list[Any]:
    """Read one row's list cell, treating a missing (null) cell as empty."""
    cell = column[i]
    return cell if cell is not None else []


def resolve_list_series(
    frame: nw.DataFrame,
    row_keys: list[Any],
    *,
    value: str,
    ci: tuple[str, str] | None = None,
    x: str | None = None,
) -> list[Series]:
    """Resolve one `Series` per frame row from list-valued columns.

    The list-column front door: `value` (and `ci`, `x` when given) name
    list-valued columns already in the intended plotting order -- rows are
    never resorted here, matching nanoplot's raw-list convention.

    Parameters
    ----------
    frame
        The input frame, narwhals-wrapped.
    row_keys
        Per-row values of the table's `rows` column, aligned to `frame`;
        used only to name the offending row in a `SpecError`.
    value
        Frame column holding each row's list of y values.
    ci
        Frame columns holding each row's list of lower/upper bounds.
    x
        Frame column holding each row's list of x values. `None` falls back
        to a positional index `0..n-1` for each row.

    Returns
    -------
    list[Series]
        One `Series` per `frame` row, in frame order.

    Raises
    ------
    SpecError
        When a row's `value`, `ci` bound(s) or `x` lists have unequal
        length.
    """
    y_col = frame[value].to_list()
    lower_col = frame[ci[0]].to_list() if ci is not None else None
    upper_col = frame[ci[1]].to_list() if ci is not None else None
    x_col = frame[x].to_list() if x is not None else None

    series: list[Series] = []
    for i, row_key in enumerate(row_keys):
        y_raw = _row_cell(y_col, i)
        lower_raw = _row_cell(lower_col, i) if lower_col is not None else None
        upper_raw = _row_cell(upper_col, i) if upper_col is not None else None
        x_raw = _row_cell(x_col, i) if x_col is not None else None
        series.append(_build_series(y_raw, lower_raw, upper_raw, x_raw, row_key=row_key))
    return series


def _sorted_by_x(series: Series) -> Series:
    """Reorder a series' points by x ascending; a missing x sorts last.

    Sorts on the already-coerced `float | None` x values rather than the
    raw backend values, so a pandas `NaT`/`<NA>` -- not the `None` object,
    but not orderable against a real timestamp either -- reliably sorts
    last instead of only doing so by accident of input order.
    """
    order = sorted(range(len(series.x)), key=lambda i: (series.x[i] is None, series.x[i]))
    return Series(
        x=[series.x[i] for i in order],
        y=[series.y[i] for i in order],
        lower=[series.lower[i] for i in order],
        upper=[series.upper[i] for i in order],
        x_temporal=series.x_temporal,
    )


@overload
def resolve_companion_series(
    data: Any,
    identities: list[tuple[Any, Any, Any, Any]],
    *,
    rows: str | None,
    nest: str | None,
    groups: str | None,
    split_columns: str | None,
    value: str,
    ci: tuple[str, str] | None = None,
    x: str | None = None,
    series: None = None,
) -> dict[tuple[Any, Any, Any, Any], Series]: ...


@overload
def resolve_companion_series(
    data: Any,
    identities: list[tuple[Any, Any, Any, Any]],
    *,
    rows: str | None,
    nest: str | None,
    groups: str | None,
    split_columns: str | None,
    value: str,
    ci: tuple[str, str] | None = None,
    x: str | None = None,
    series: str,
) -> dict[tuple[Any, Any, Any, Any], list[tuple[Any, Series]]]: ...


def resolve_companion_series(
    data: Any,
    identities: list[tuple[Any, Any, Any, Any]],
    *,
    rows: str | None,
    nest: str | None,
    groups: str | None,
    split_columns: str | None,
    value: str,
    ci: tuple[str, str] | None = None,
    x: str | None = None,
    series: str | None = None,
) -> (
    dict[tuple[Any, Any, Any, Any], Series]
    | dict[tuple[Any, Any, Any, Any], list[tuple[Any, Series]]]
):
    """Resolve a `Series` (or per-arm `Series` list) per row identity from a companion frame.

    The companion-frame front door: `value` (and `ci`, `x` when given) name
    *scalar* columns in `data`, grouped by the same `(rows, nest, groups,
    split_columns)` identity the main table uses and collapsed into list
    form. Each group is sorted by `x` ascending (a missing `x` sorts last);
    when `x` is not given, points keep `data`'s row order and are indexed
    positionally, so there is nothing to sort.

    When `series` is given, each identity is further split by that
    column's value: the return type changes to one `(arm value, Series)`
    list per identity, sorted ascending on the arm value with `None`
    last (mirroring `_sorted_by_x`'s missing-last rule). An identity with
    no rows in `data` at all still resolves to an empty list, not a
    missing key.

    Parameters
    ----------
    data
        The companion frame: any frame narwhals can read.
    identities
        `(row key, nest key, group key, split key)` tuples the main table
        needs a series for, e.g. one per main-frame row. An identity absent
        from `data` gets an empty `Series` (renders as a blank cell,
        consistent with how `resolve` blanks a missing split).
    rows, nest, groups, split_columns
        The main table's layout-key column names, as declared on
        `CoefTable`; `None` mirrors `resolve`'s fallback for an undeclared
        key (`""` for `rows`, `None` for `nest`/`groups`/`split_columns`) so
        identities line up with the ones `resolve` computes for the main
        frame. `groups` is part of the identity because a row label may
        appear under more than one group; omitting it would merge every
        group's points into one series.
    value
        `data` column holding each point's y value.
    ci
        `data` columns holding each point's lower/upper bound.
    x
        `data` column holding each point's x value. `None` falls back to
        positional order within each group.
    series
        `data` column splitting each identity into overlaid arms. `None`
        (the default) resolves one `Series` per identity, as before.

    Returns
    -------
    dict[tuple[Any, Any, Any, Any], Series] or
    dict[tuple[Any, Any, Any, Any], list[tuple[Any, Series]]]
        One `Series` per requested identity when `series` is `None`;
        otherwise one `(arm value, Series)` list per identity.

    Raises
    ------
    SpecError
        Propagated from the shared row-building step; unreachable in
        practice here since a group's lists are always built in lockstep,
        but kept so both front doors share one validation path.
    """
    frame = nw.from_native(data, eager_only=True)
    n = len(frame)
    c_row_keys = _nan_to_none(frame[rows].to_list()) if rows else [""] * n
    c_nest_keys = _nan_to_none(frame[nest].to_list()) if nest else [None] * n
    c_group_keys = _nan_to_none(frame[groups].to_list()) if groups else [None] * n
    c_split_keys = _nan_to_none(frame[split_columns].to_list()) if split_columns else [None] * n
    y_all = frame[value].to_list()
    lower_all = frame[ci[0]].to_list() if ci is not None else None
    upper_all = frame[ci[1]].to_list() if ci is not None else None
    x_all = frame[x].to_list() if x is not None else None

    def build(indices: list[int], row_key: Any) -> Series:
        built = _build_series(
            [y_all[i] for i in indices],
            [lower_all[i] for i in indices] if lower_all is not None else None,
            [upper_all[i] for i in indices] if upper_all is not None else None,
            [x_all[i] for i in indices] if x_all is not None else None,
            row_key=row_key,
        )
        return _sorted_by_x(built) if x_all is not None else built

    if series is None:
        grouped: dict[tuple[Any, Any, Any, Any], list[int]] = {}
        for i in range(n):
            grouped.setdefault(
                (c_row_keys[i], c_nest_keys[i], c_group_keys[i], c_split_keys[i]), []
            ).append(i)

        out: dict[tuple[Any, Any, Any, Any], Series] = {}
        for identity in dict.fromkeys(identities):
            indices = grouped.get(identity)
            out[identity] = (
                Series(x=[], y=[], lower=[], upper=[], x_temporal=False)
                if not indices
                else build(indices, identity[0])
            )
        return out

    c_arm_keys = _nan_to_none(frame[series].to_list())
    arm_groups: dict[tuple[Any, Any, Any, Any, Any], list[int]] = {}
    arms_by_identity: dict[tuple[Any, Any, Any, Any], list[Any]] = {}
    for i in range(n):
        identity = (c_row_keys[i], c_nest_keys[i], c_group_keys[i], c_split_keys[i])
        arm_key = c_arm_keys[i]
        arm_groups.setdefault((*identity, arm_key), []).append(i)
        arms = arms_by_identity.setdefault(identity, [])
        if arm_key not in arms:
            arms.append(arm_key)

    out_multi: dict[tuple[Any, Any, Any, Any], list[tuple[Any, Series]]] = {}
    for identity in dict.fromkeys(identities):
        arm_keys = sorted(arms_by_identity.get(identity, []), key=lambda v: (v is None, v))
        out_multi[identity] = [
            (arm_key, build(arm_groups[(*identity, arm_key)], identity[0])) for arm_key in arm_keys
        ]
    return out_multi
