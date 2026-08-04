"""Number and confidence-interval formatting."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from coeftable.theme import Theme

type Format = Callable[[float], str]
type TimeFormat = Callable[[float], str]
type Layout = Literal["stacked", "inline", "value_only"]


def is_missing(value: float | None) -> bool:
    """Return True when *value* is None or NaN.

    Parameters
    ----------
    value
        Candidate value.

    Returns
    -------
    bool
        True when the value carries no information.
    """
    return value is None or (isinstance(value, float) and math.isnan(value))


def coerce_numeric(values: Iterable[Any], *, subject: str = "Value") -> list[float | None]:
    """Coerce raw backend values to `float | None`, `None` for anything missing.

    Handles `None` directly, and NaN uniformly as missing regardless of its
    source (plain `float`, numpy, `Decimal`) once coerced. Also recognises
    the missing-value sentinels narwhals' supported backends surface for
    non-float columns that `float()` cannot parse directly: pandas'
    nullable ``<NA>`` and ``NaT``.

    Parameters
    ----------
    values
        Raw values, e.g. a narwhals column's `.to_list()`.
    subject
        Identifies what is being coerced in the `TypeError` message raised
        for a value that is neither missing nor numeric, e.g. ``"Column 'x'"``.

    Returns
    -------
    list[float | None]
        One entry per input value.

    Raises
    ------
    TypeError
        When a value is neither a recognised missing sentinel nor coercible
        to `float`.
    """
    out: list[float | None] = []
    for value in values:
        if value is None:
            out.append(None)
            continue
        try:
            coerced = float(value)
        except (TypeError, ValueError):
            if str(value) in ("<NA>", "NaT"):
                out.append(None)
                continue
            raise TypeError(f"{subject} must be numeric; found {value!r}.") from None
        out.append(None if math.isnan(coerced) else coerced)
    return out


def compact_number(value: float) -> str:
    """Format a magnitude compactly, e.g. ``1.4k``, ``2.3M``, ``2.4B``.

    Parameters
    ----------
    value
        Value to format. The sign is preserved.

    Returns
    -------
    str
        Compact representation.
    """
    av = abs(value)
    if av >= 1_000_000_000:
        scaled = round(av / 1_000_000_000, 1)
        if scaled >= 1000:
            return f"{value / 1_000_000_000_000:.1f}T"
        return f"{value / 1_000_000_000:.1f}B"
    if av >= 1_000_000:
        scaled = round(av / 1_000_000, 1)
        if scaled >= 1000:
            return f"{value / 1_000_000_000:.1f}B"
        return f"{value / 1_000_000:.1f}M"
    if av >= 1_000:
        scaled = round(av / 1_000, 1)
        if scaled >= 1000:
            return f"{value / 1_000_000:.1f}M"
        return f"{value / 1_000:.1f}k"
    if av >= 1:
        scaled = round(av, 1)
        if scaled >= 1000:
            return f"{value / 1_000:.1f}k"
        return f"{value:.1f}"
    return f"{value:.2f}"


@dataclass(frozen=True)
class Number:
    """Format a float as a number.

    Parameters
    ----------
    decimals
        Digits after the decimal point. Ignored when *compact* is True.
    compact
        Use ``1.4k`` / ``2.3M`` style abbreviation.
    signed
        Prefix positive values with ``+``. Negatives always carry ``-``.
    prefix
        Text placed after the sign and before the digits, e.g. ``$``.
    suffix
        Text placed after the digits, e.g. ``x``.
    thousands
        Insert thousands separators.
    """

    decimals: int = 2
    compact: bool = False
    signed: bool = False
    prefix: str = ""
    suffix: str = ""
    thousands: bool = True

    def __call__(self, value: float) -> str:
        """Format *value*.

        Parameters
        ----------
        value
            Value to format.

        Returns
        -------
        str
            Formatted value.
        """
        magnitude = abs(value)
        if self.compact:
            body = compact_number(magnitude)
        else:
            spec = f",.{self.decimals}f" if self.thousands else f".{self.decimals}f"
            body = format(magnitude, spec)
        if value < 0:
            sign = "-"
        elif self.signed and value > 0:
            sign = "+"
        else:
            sign = ""
        return f"{sign}{self.prefix}{body}{self.suffix}"


@dataclass(frozen=True)
class Percent(Number):
    """Format a float as a percentage.

    Parameters
    ----------
    scale
        Multiplier applied before formatting. Leave at ``1.0`` when the data is
        already in percentage points; use ``100.0`` when it is a fraction.
    """

    decimals: int = 2
    signed: bool = True
    suffix: str = "%"
    thousands: bool = False
    scale: float = 1.0

    def __call__(self, value: float) -> str:
        """Format *value* as a percentage.

        Parameters
        ----------
        value
            Value to format.

        Returns
        -------
        str
            Formatted percentage.
        """
        return super().__call__(value * self.scale)


@dataclass(frozen=True)
class Currency(Number):
    """Format a float as currency, with the symbol inside the sign."""

    prefix: str = "$"


type CalendarStep = Literal["day", "month", "year"]


_MONTH_ABBR = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


@dataclass(frozen=True)
class DateAxis:
    """Format an epoch float as a short calendar label.

    The label's granularity follows `step`: ``"year"`` renders ``2026``,
    ``"month"`` renders ``Jan``, and ``"day"`` renders ``Jan 5``. There is no
    quarter granularity -- a quarterly axis is simply month ticks every
    three months, still labelled ``Jan``/``Apr``/``Jul``/``Oct``.

    `labels` cascades coarser components across an ordered tick set -- month,
    then year -- showing each only where it changes from the predecessor. A
    run of ticks inside one month never repeats the month name; a run inside
    one year never repeats the year. If the *entire* set never leaves one
    calendar year, the year is not shown anywhere, not even on the first
    tick -- it adds nothing a reader doesn't already know from context, and
    costs the most pixel-constrained rungs (day, month) their widest token
    for zero information. It only ever appears where a reader would
    otherwise be unable to tell which year a tick falls in: the first tick
    of a *multi*-year set, and every later tick whose year differs from its
    predecessor. A shown year is the compact two-digit token (``'26``) --
    the apostrophe is load-bearing, not decorative: a bare ``24`` on a
    day-rung axis would be indistinguishable from day-of-month 24. The year
    rung is the one exception and always renders the full four digits:
    every one of its ticks is a distinct year by construction, so there is
    nothing to cascade, and the pixel budget per tick is never tight there.
    `sparkline_axis`'s grouped super-tick row (`svg._super_row`) reuses this
    same cascade logic through the private `_cascade`, over each group's
    representative date rather than a rendered tick -- `labels` itself is a
    standalone public entry point for a caller with its own ordered tick set
    to format, not the renderer's only path through this logic.

    `__call__` formats a single value with no neighbours to diff against and
    no tick set to check for a year boundary, so unlike `labels` it always
    fully qualifies -- day step includes both month and year, month step
    includes year. Reach for `labels` whenever a whole tick set renders
    together; use `__call__` directly only for a single value in isolation.

    Parameters
    ----------
    step
        Tick granularity to render at.
    """

    step: CalendarStep = "month"

    def __call__(self, value: float) -> str:
        """Format *value* alone -- see the class docstring for why this always fully qualifies.

        Parameters
        ----------
        value
            Epoch seconds (UTC).

        Returns
        -------
        str
            Fully qualified calendar label at this instance's `step` granularity.
        """
        dt = datetime.fromtimestamp(value, tz=UTC)
        if self.step == "year":
            return str(dt.year)
        if self.step == "month":
            return f"{_MONTH_ABBR[dt.month - 1]} '{dt.year % 100:02d}"
        return f"{_MONTH_ABBR[dt.month - 1]} {dt.day} '{dt.year % 100:02d}"

    def labels(self, values: Sequence[float]) -> list[str]:
        """Format a full, ordered tick set, cascading month/year only where they change.

        Parameters
        ----------
        values
            Epoch seconds (UTC), in the order they will be rendered.

        Returns
        -------
        list of str
            One label per value, same length and order as `values`.
        """
        dts = [datetime.fromtimestamp(value, tz=UTC) for value in values]
        return self._cascade(dts, multi_year=len({dt.year for dt in dts}) > 1)

    def _cascade(self, dts: list[datetime], *, multi_year: bool) -> list[str]:
        """Shared cascade body, parameterised on whether *any* year label is shown at all.

        `labels` computes `multi_year` from exactly the values it was given,
        which is correct for a direct caller. `sparkline_axis`'s grouped
        super-tick row (`_super_row` in `svg.py`) needs a different source of
        truth: whether the *domain* spans multiple years, fixed once from
        the full, undropped group set, not recomputed from whichever subset
        survives a dropped label. Recomputing per subset would let dropping
        the one group that crosses a year boundary silently erase the fact
        that the axis spans multiple years at all -- the collision fix
        would end up hiding real information, not just noise.
        """
        out: list[str] = []
        prev: datetime | None = None
        for dt in dts:
            year_changed = multi_year and (prev is None or dt.year != prev.year)
            if self.step == "year":
                out.append(str(dt.year))
            elif self.step == "month":
                month = _MONTH_ABBR[dt.month - 1]
                out.append(f"{month} '{dt.year % 100:02d}" if year_changed else month)
            else:
                month_changed = prev is None or year_changed or dt.month != prev.month
                day = f"{_MONTH_ABBR[dt.month - 1]} {dt.day}" if month_changed else str(dt.day)
                out.append(f"{day} '{dt.year % 100:02d}" if year_changed else day)
            prev = dt
        return out


@dataclass(frozen=True)
class CIStyle:
    """Control how a point estimate and its interval are assembled.

    Parameters
    ----------
    layout
        ``"stacked"`` puts the interval on a muted second line, ``"inline"``
        keeps it on one line, ``"value_only"`` drops it.
    brackets
        Bracket pair for a two-sided interval. An unbounded side always uses a
        parenthesis regardless of this setting.
    separator
        Text between the two bounds.
    unbounded
        Symbol used for an absent bound.
    """

    layout: Layout = "stacked"
    brackets: tuple[str, str] = ("[", "]")
    separator: str = ", "
    unbounded: str = "∞"


def render_interval(
    value: float | None,
    lower: float | None,
    upper: float | None,
    *,
    fmt: Format,
    style: CIStyle,
    theme: Theme,
) -> str:
    """Render an estimate and its interval as an HTML fragment.

    Parameters
    ----------
    value
        Point estimate. A missing value renders *theme*. ``na_text``.
    lower, upper
        Interval bounds. A missing bound renders as unbounded on that side.
    fmt
        Callable applied to the estimate and each bound.
    style
        Assembly options.
    theme
        Supplies typography, muted colour and the missing-value text.

    Returns
    -------
    str
        HTML fragment safe to pass through **great_tables** markdown formatting.
    """
    if is_missing(value):
        return theme.na_text
    assert value is not None  # noqa: S101 - narrowed by is_missing
    point = f'<span style="font-size:{theme.value_size};font-weight:600">{fmt(value)}</span>'
    lower = None if is_missing(lower) else lower
    upper = None if is_missing(upper) else upper
    if style.layout == "value_only" or (lower is None and upper is None):
        return point
    open_bracket = "(" if lower is None else style.brackets[0]
    close_bracket = ")" if upper is None else style.brackets[1]
    low_text = f"\u2212{style.unbounded}" if lower is None else fmt(lower)
    high_text = style.unbounded if upper is None else fmt(upper)
    interval = f"{open_bracket}{low_text}{style.separator}{high_text}{close_bracket}"
    if style.layout == "inline":
        return (
            f'<span style="white-space:nowrap">{point} '
            f'<span style="color:{theme.muted}">{interval}</span></span>'
        )
    return (
        f'{point}<br><span style="font-size:{theme.ci_size};color:{theme.muted}">{interval}</span>'
    )
