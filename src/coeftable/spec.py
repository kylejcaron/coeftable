"""Column specifications and the table builder."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from coeftable.format import CIStyle, Format, Number
from coeftable.theme import DEFAULT, ColorRule, Direction, Theme

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
    width
        Bar width in pixels.
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
    width: int = 220
    show_axis: bool = True
    axis_fmt: Format | None = None


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
        width: int = 220,
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
        width
            Bar width in pixels.
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
                width=width,
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

        Raises
        ------
        NotImplementedError
            Rendering lives in `coeftable.render`, which is not yet available.
        """
        raise NotImplementedError("Rendering is not available yet.")

    def _repr_html_(self) -> str:
        return self.gt()._repr_html_()
