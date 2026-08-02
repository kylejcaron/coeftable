"""Column specifications and the table builder."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol

import narwhals as nw

from coeftable.format import CIStyle, Format, Number, coerce_numeric, is_missing, render_interval
from coeftable.svg import forest_axis, forest_bar
from coeftable.theme import DEFAULT, ColorRule, Direction, Theme, role_for

if TYPE_CHECKING:
    from great_tables import GT

type Scale = Literal["table", "row_group", "split_column", "row"]

# Module-level singletons: frozen and shared, so they are safe as argument
# defaults where ruff B008 forbids a constructor call.
_DEFAULT_FMT = Number()
_DEFAULT_CI_STYLE = CIStyle()


class SpecError(ValueError):
    """Raised when a table specification is internally inconsistent."""


class ColumnNotFoundError(KeyError):
    """Raised when a specification names a column absent from the frame."""


@dataclass(frozen=True)
class Scan:
    """Frame-level context available to `ColumnKind.prepare`.

    Parameters
    ----------
    frame
        The input frame, narwhals-wrapped.
    columns
        Every declared column, in display order -- lets a column look up
        another one it depends on, e.g. `Forest.of`.
    row_keys, group_keys, split_keys
        Per-input-row values, aligned to `frame`'s row order.
    """

    frame: nw.DataFrame
    columns: tuple[Column, ...]
    row_keys: list[Any]
    group_keys: list[Any]
    split_keys: list[Any]


@dataclass(frozen=True)
class Prepared:
    """Per-column state from `prepare()`, threaded back through `cell`/`footer`.

    `payload` holds whatever a column kind needs privately; it is opaque to
    `resolve()` and to `grid.py`. `footer_key`, when set, maps this column's
    `(row key, row-group value, split)` for one output row to an opaque
    domain key, driving the shared footer-scheduling pass in `grid.py`;
    `None` means this column has nothing to schedule.
    """

    payload: Any
    footer_key: Callable[[Any, Any, Any], Any] | None = None


@dataclass(frozen=True)
class Cell:
    """Context passed to `ColumnKind.cell` to render one cell.

    Parameters
    ----------
    prepared
        This column's own state, from `prepare()`.
    index
        Input frame row backing this cell.
    row_key, group, split
        This cell's row key, row-group value and split value.
    direction
        Favourable direction for this row.
    color_rule
        Table-wide override for role resolution, if any.
    theme
        Colour and typography.
    """

    prepared: Prepared
    index: int
    row_key: Any
    group: Any
    split: Any
    direction: Direction
    color_rule: ColorRule | None
    theme: Theme


@dataclass(frozen=True)
class Footer:
    """Context passed to `ColumnKind.footer` when a domain key is complete.

    Parameters
    ----------
    prepared
        This column's own state, from `prepare()`.
    key
        The domain key that is now complete.
    theme
        Colour and typography.
    """

    prepared: Prepared
    key: Any
    theme: Theme


class ColumnKind(Protocol):
    """Structural interface for a declared column.

    `resolve()` drives every column through the same four seams: which frame
    columns it reads (`sources`), the state it precomputes once (`prepare`),
    one rendered cell (`cell`), and an optional footer row (`footer`) --
    e.g. `Forest`'s shared axis.
    """

    label: str

    def sources(self) -> Iterable[str]:
        """Frame columns this column reads."""
        ...

    def prepare(self, scan: Scan) -> Prepared:
        """Precompute state shared across this column's cells."""
        ...

    def cell(self, ctx: Cell) -> str:
        """Render one cell."""
        ...

    def footer(self, ctx: Footer) -> str | None:
        """Render a footer row for a completed domain key, or None."""
        ...


def _numeric(frame: nw.DataFrame, name: str) -> list[float | None]:
    return coerce_numeric(frame[name].to_list(), subject=f"Column {name!r}")


@dataclass(frozen=True)
class _EstimateState:
    value: list[float | None]
    low: list[float | None] | None
    high: list[float | None] | None


@dataclass(frozen=True)
class Estimate:
    """A column rendering a point estimate and its interval.

    Parameters
    ----------
    label
        Column header, and the name a `Forest` binds to.
    value
        Frame column holding the point estimate.
    ci
        Frame columns holding the lower and upper bounds, or None.
    fmt
        Callable applied to the estimate and both bounds.
    ci_style
        Assembly options for the rendered cell.
    """

    label: str
    value: str
    ci: tuple[str, str] | None = None
    fmt: Format = _DEFAULT_FMT
    ci_style: CIStyle = _DEFAULT_CI_STYLE

    def sources(self) -> Iterable[str]:
        """Frame columns this column reads."""
        names = [self.value]
        if self.ci is not None:
            names.extend(self.ci)
        return names

    def prepare(self, scan: Scan) -> Prepared:
        """Precompute the numeric value and bound columns."""
        value = _numeric(scan.frame, self.value)
        low: list[float | None] | None = None
        high: list[float | None] | None = None
        if self.ci is not None:
            low = _numeric(scan.frame, self.ci[0])
            high = _numeric(scan.frame, self.ci[1])
        return Prepared(payload=_EstimateState(value=value, low=low, high=high))

    def cell(self, ctx: Cell) -> str:
        """Render the point estimate and its interval."""
        state: _EstimateState = ctx.prepared.payload
        low = state.low[ctx.index] if state.low is not None else None
        high = state.high[ctx.index] if state.high is not None else None
        return render_interval(
            state.value[ctx.index], low, high, fmt=self.fmt, style=self.ci_style, theme=ctx.theme
        )

    def footer(self, ctx: Footer) -> str | None:
        """`Estimate` has no footer row."""
        return None


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


def _pad_domain(
    values: list[float], ref: float, *, symmetric: bool = False
) -> tuple[float, float]:
    if not values:
        return (ref - 1.0, ref + 1.0)
    low, high = min(values), max(values)
    low, high = min(low, ref), max(high, ref)
    if low == high:
        return (low - 1.0, high + 1.0)
    margin = (high - low) * 0.08
    low, high = low - margin, high + margin
    if symmetric:
        half = max(ref - low, high - ref)
        return (ref - half, ref + half)
    return (low, high)


# Content height (px) a forest bar needs to fill its row for each CI
# layout, measured against the theme's default font sizes. Approximate but
# close enough that the reference line spans the row instead of a short
# segment centred in a taller cell; `Forest.height` overrides this per column.
_LAYOUT_HEIGHTS = {"stacked": 48, "inline": 34, "value_only": 34}


def _forest_height(column: Forest, source: Estimate) -> int:
    if column.height is not None:
        return column.height
    return _LAYOUT_HEIGHTS.get(source.ci_style.layout, 18)


def _estimate_by_label(columns: tuple[Column, ...], label: str) -> Estimate:
    for column in columns:
        if isinstance(column, Estimate) and column.label == label:
            return column
    raise KeyError(label)  # pragma: no cover - guaranteed by validate_columns


@dataclass(frozen=True)
class _ForestState:
    domains: dict[Any, tuple[float, float]]
    source: Estimate
    value: list[float | None]
    low: list[float | None]
    high: list[float | None]


@dataclass(frozen=True)
class Forest:
    """A column rendering an inline SVG interval bar.

    Parameters
    ----------
    label
        Column header.
    of
        Label of the `Estimate` this plot visualises.
    ref
        Reference value for the dashed line and for role resolution.
    scale
        Which set of bars share an x-domain.
    domain
        Explicit domain, overriding `scale`.
    symmetric
        When `domain` is not set, symmetrize the auto-computed domain
        around `ref` instead of fitting tightly to the data.
    width
        Bar width in pixels.
    height
        Bar row height in pixels.  `None` (the default) picks a height
        that fills the row based on the bound estimate's `ci_style.layout`
        so the reference line spans the full cell instead of a short
        segment centred in a taller row.
    show_axis
        Emit an axis row for each distinct domain.
    axis_fmt
        Callable labelling axis ticks; defaults to the bound estimate's `fmt`.
    """

    label: str
    of: str
    ref: float = 0.0
    scale: Scale = "table"
    domain: tuple[float, float] | None = None
    symmetric: bool = False
    width: int = 220
    height: int | None = None
    show_axis: bool = True
    axis_fmt: Format | None = None

    def sources(self) -> Iterable[str]:
        """`Forest` reads no frame column directly; it derives from its source estimate."""
        return ()

    def prepare(self, scan: Scan) -> Prepared:
        """Compute this column's per-key domains, and its footer schedule if `show_axis`."""
        source = _estimate_by_label(scan.columns, self.of)
        assert source.ci is not None  # noqa: S101 - guaranteed by validate_columns
        source_state: _EstimateState = source.prepare(scan).payload
        assert source_state.low is not None and source_state.high is not None  # noqa: S101
        value, low, high = source_state.value, source_state.low, source_state.high

        buckets: dict[Any, list[float]] = {}
        for i in range(len(scan.row_keys)):
            key = _domain_key(self, scan.row_keys[i], scan.group_keys[i], scan.split_keys[i])
            buckets.setdefault(key, []).extend(_finite([value[i], low[i], high[i]]))
        domains = {
            key: self.domain or _pad_domain(vals, self.ref, symmetric=self.symmetric)
            for key, vals in buckets.items()
        }

        def footer_key(row_key: Any, group: Any, split: Any) -> Any:
            return _domain_key(self, row_key, group, split)

        return Prepared(
            payload=_ForestState(domains=domains, source=source, value=value, low=low, high=high),
            footer_key=footer_key if self.show_axis else None,
        )

    def cell(self, ctx: Cell) -> str:
        """Render an interval bar, coloured by role, against its shared domain."""
        state: _ForestState = ctx.prepared.payload
        value = state.value[ctx.index]
        low = state.low[ctx.index]
        high = state.high[ctx.index]
        if is_missing(value):
            return ""
        key = _domain_key(self, ctx.row_key, ctx.group, ctx.split)
        domain = state.domains[key]
        role = (
            ctx.color_rule(value, low, high, self.ref)
            if ctx.color_rule is not None
            else role_for(low, high, self.ref, ctx.direction)
        )
        return forest_bar(
            value,
            low,
            high,
            domain=domain,
            ref=self.ref,
            color=ctx.theme.color(role),
            theme=ctx.theme,
            width=self.width,
            height=_forest_height(self, state.source),
        )

    def footer(self, ctx: Footer) -> str | None:
        """Render the shared axis for a completed domain."""
        state: _ForestState = ctx.prepared.payload
        return forest_axis(
            domain=state.domains[ctx.key],
            ref=self.ref,
            fmt=self.axis_fmt or state.source.fmt,
            theme=ctx.theme,
            width=self.width,
        )


@dataclass(frozen=True)
class Passthrough:
    """A column rendering a frame column verbatim.

    Parameters
    ----------
    label
        Column header.
    column
        Frame column to display.
    """

    label: str
    column: str

    def sources(self) -> Iterable[str]:
        """Frame columns this column reads."""
        return (self.column,)

    def prepare(self, scan: Scan) -> Prepared:
        """Read the column verbatim."""
        return Prepared(payload=scan.frame[self.column].to_list())

    def cell(self, ctx: Cell) -> str:
        """Render the value verbatim."""
        return str(ctx.prepared.payload[ctx.index])

    def footer(self, ctx: Footer) -> str | None:
        """`Passthrough` has no footer row."""
        return None


type Column = Estimate | Forest | Passthrough


def validate_columns(columns: tuple[Column, ...]) -> None:
    """Check a column specification for internal consistency.

    Parameters
    ----------
    columns
        Declared columns, in display order.

    Raises
    ------
    SpecError
        When no columns are declared, labels collide, a `Forest` names an
        undeclared estimate, or a `Forest` is bound to a CI-less estimate.
    """
    if not columns:
        raise SpecError("Table has no columns; declare at least one.")

    seen: set[str] = set()
    for column in columns:
        if column.label in seen:
            raise SpecError(f"Table has duplicate column label {column.label!r}.")
        seen.add(column.label)

    estimates = {c.label: c for c in columns if isinstance(c, Estimate)}
    for column in columns:
        if not isinstance(column, Forest):
            continue
        target = estimates.get(column.of)
        if target is None:
            raise SpecError(
                f"Forest column {column.label!r} references estimate {column.of!r}, "
                f"which is not declared. Declared estimates: {sorted(estimates)}."
            )
        if target.ci is None:
            raise SpecError(
                f"Forest column {column.label!r} references estimate {column.of!r}, "
                "which has no confidence interval to plot."
            )


class CoefTable:
    """A specification for a summary table over a frame of estimates.

    Immutable by convention: every chain method returns a new instance.

    Parameters
    ----------
    data
        Any frame narwhals can read: pandas, polars or pyarrow. A plain dict is
        not accepted; narwhals has no backend to build from.
    rows
        Frame column whose values become the leading row label.
    nest
        Frame column stacked beneath each row key.
    groups
        Frame column driving row-group section headers.
    split_columns
        Frame column whose values repeat the declared columns side by side.
    columns
        Declared columns, in display order.
    estimate, ci
        Sugar declaring a single `Estimate` labelled ``"Estimate"``, prepended
        before any `columns` entries.
    direction
        Which side of a reference counts as favorable, table-wide or per row key.
    color_rule
        Callable overriding role resolution entirely.
    theme
        Colour and typography.
    title, subtitle
        Header text.
    sort_rows
        Sort row keys lexically instead of by first appearance.
    """

    def __init__(
        self,
        data: Any,
        *,
        rows: str | None = None,
        nest: str | None = None,
        groups: str | None = None,
        split_columns: str | None = None,
        columns: Iterable[Column] = (),
        estimate: str | None = None,
        ci: tuple[str, str] | None = None,
        direction: Direction | Mapping[str, Direction] = "higher_is_better",
        color_rule: ColorRule | None = None,
        theme: Theme = DEFAULT,
        title: str = "",
        subtitle: str = "",
        sort_rows: bool = False,
    ) -> None:
        declared = tuple(columns)
        if estimate is not None:
            declared = (Estimate("Estimate", estimate, ci=ci), *declared)
        self.data = data
        self.rows = rows
        self.nest = nest
        self.groups = groups
        self.split_columns = split_columns
        self.columns = declared
        self.direction = direction
        self.color_rule = color_rule
        self.theme = theme
        self.title = title
        self.subtitle = subtitle
        self.sort_rows = sort_rows
        if declared:
            validate_columns(declared)

    def _with(self, **changes: Any) -> CoefTable:
        settings: dict[str, Any] = {
            "rows": self.rows,
            "nest": self.nest,
            "groups": self.groups,
            "split_columns": self.split_columns,
            "columns": self.columns,
            "direction": self.direction,
            "color_rule": self.color_rule,
            "theme": self.theme,
            "title": self.title,
            "subtitle": self.subtitle,
            "sort_rows": self.sort_rows,
        }
        settings.update(changes)
        return CoefTable(self.data, **settings)

    def _add(self, column: Column) -> CoefTable:
        return self._with(columns=(*self.columns, column))

    def estimate(
        self,
        label: str,
        value: str,
        *,
        ci: tuple[str, str] | None = None,
        fmt: Format = _DEFAULT_FMT,
        ci_style: CIStyle = _DEFAULT_CI_STYLE,
    ) -> CoefTable:
        """Append an estimate column.

        Parameters
        ----------
        label
            Column header, and the name a `Forest` binds to.
        value
            Frame column holding the point estimate.
        ci
            Frame columns holding the lower and upper bounds.
        fmt
            Callable applied to the estimate and both bounds.
        ci_style
            Assembly options for the rendered cell.

        Returns
        -------
        CoefTable
            A new table with the column appended.
        """
        return self._add(Estimate(label, value, ci=ci, fmt=fmt, ci_style=ci_style))

    def forest(
        self,
        label: str,
        *,
        of: str,
        ref: float = 0.0,
        scale: Scale = "table",
        domain: tuple[float, float] | None = None,
        symmetric: bool = False,
        width: int = 220,
        height: int | None = None,
        show_axis: bool = True,
        axis_fmt: Format | None = None,
    ) -> CoefTable:
        """Append a forest-plot column bound to an existing estimate.

        Parameters
        ----------
        label
            Column header.
        of
            Label of the `Estimate` to visualise.
        ref
            Reference value for the dashed line and role resolution.
        scale
            Which set of bars share an x-domain.
        domain
            Explicit domain, overriding `scale`.
        symmetric
            When `domain` is not set, symmetrize the auto-computed domain
            around `ref` instead of fitting tightly to the data.
        width
            Bar width in pixels.
        height
            Bar row height in pixels. `None` (the default) picks a height
            that fills the row based on the bound estimate's
            `ci_style.layout`.
        show_axis
            Emit an axis row per distinct domain.
        axis_fmt
            Callable labelling axis ticks.

        Returns
        -------
        CoefTable
            A new table with the column appended.
        """
        return self._add(
            Forest(
                label,
                of=of,
                ref=ref,
                scale=scale,
                domain=domain,
                symmetric=symmetric,
                width=width,
                height=height,
                show_axis=show_axis,
                axis_fmt=axis_fmt,
            )
        )

    def passthrough(self, label: str, column: str) -> CoefTable:
        """Append a column rendered verbatim from the frame.

        Parameters
        ----------
        label
            Column header.
        column
            Frame column to display.

        Returns
        -------
        CoefTable
            A new table with the column appended.
        """
        return self._add(Passthrough(label, column))

    def header(self, title: str, subtitle: str = "") -> CoefTable:
        """Set the header text.

        Parameters
        ----------
        title
            Title line.
        subtitle
            Subtitle line.

        Returns
        -------
        CoefTable
            A new table with the header set.
        """
        return self._with(title=title, subtitle=subtitle)

    def with_theme(self, theme: Theme) -> CoefTable:
        """Replace the theme.

        Parameters
        ----------
        theme
            Theme to use.

        Returns
        -------
        CoefTable
            A new table using `theme`.
        """
        return self._with(theme=theme)

    def with_direction(self, direction: Direction | Mapping[str, Direction]) -> CoefTable:
        """Replace the direction semantics.

        Parameters
        ----------
        direction
            Table-wide direction, or a mapping from row key to direction.

        Returns
        -------
        CoefTable
            A new table using `direction`.
        """
        return self._with(direction=direction)

    def direction_for(self, row_key: str) -> Direction:
        """Resolve the direction applying to a row key.

        Parameters
        ----------
        row_key
            Value of the `rows` column.

        Returns
        -------
        Direction
            The direction for that row, defaulting to ``"higher_is_better"``.
        """
        if isinstance(self.direction, Mapping):
            return self.direction.get(row_key, "higher_is_better")
        return self.direction

    def gt(self) -> GT:
        """Render to a `great_tables` object.

        Returns
        -------
        GT
            The rendered table.
        """
        from coeftable.render import to_gt

        return to_gt(self)

    def _repr_html_(self) -> str:
        return self.gt()._repr_html_()
