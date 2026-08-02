"""Number and confidence-interval formatting."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal

from coeftable.theme import Theme

type Format = Callable[[float], str]
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
    low_text = f"-{style.unbounded}" if lower is None else fmt(lower)
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
