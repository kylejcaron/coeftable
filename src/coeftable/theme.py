"""Colour roles, direction semantics and table chrome."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from numbers import Real
from typing import Literal

from coeftable.errors import SpecError

type Role = Literal["favorable", "unfavorable", "inconclusive", "neutral"]
type Direction = Literal["higher_is_better", "lower_is_better", "neutral"]
type ColorRule = Callable[[float | None, float | None, float | None, float | None], Role]


@dataclass(frozen=True)
class Theme:
    """Colour, typography and chrome slots for a table.

    Roles are named by meaning rather than by colour so that a palette can be
    swapped without the calling code implying a value judgement.

    Parameters
    ----------
    favorable, unfavorable, inconclusive, neutral
        Colours for the four semantic roles.
    header_bg, header_fg, column_label_bg
        Title, subtitle and column-label chrome.
    band
        Fill for alternating row-key blocks.
    surface
        Table background; also the colour of the estimate tick inside a bar.
    rule, axis, muted, text
        Divider, axis, secondary-text and body-text colours.
    value_size, ci_size, table_font_size
        CSS font sizes.
    na_text
        Text substituted for a missing estimate.
    border_style
        ``"boxed"`` draws a solid rule on all four table sides (the
        default). ``"minimal"`` drops the left and right rules for a more
        textual, publication-style layout with only top and bottom rules.
    border_color
        Colour used for structural table chrome: the heading divider,
        column-label rules, row-group borders, and the table frame
        (including the table-body top rule).  If `None` (the default),
        ``header_bg`` is reused so that these borders and the title
        banner share a colour.  Set this independently to keep the title
        banner light while still drawing visible chrome rules.  Does
        *not* affect ``rule``, which styles lighter dividers within the
        body-row region (nest-key separators, forest-plot axis lines).
    series_palette
        Categorical colours cycled across the arms of a multi-series
        sparkline (see ``series_color``). Independent of ``Role``: a
        role encodes a value judgement about one interval, this scale
        encodes arm identity and carries no such judgement.
    dotplot_palette
        Two opaque six-digit hex colours for low/high values in optional dotplot
        gradients. Independent of significance roles; choose endpoints with
        adequate contrast against ``surface``.
    """

    favorable: str = "#55A868"
    unfavorable: str = "#C44E52"
    inconclusive: str = "#8C8C8C"
    neutral: str = "#4C72B0"

    header_bg: str = "#4C72B0"
    header_fg: str = "#FFFFFF"
    column_label_bg: str = "#8FA9CE"
    band: str = "#F2F5FA"
    surface: str = "#FFFFFF"
    rule: str = "#C7C8CD"
    axis: str = "#72767E"
    muted: str = "#72767E"
    text: str = "#343538"

    value_size: str = "15px"
    ci_size: str = "11px"
    table_font_size: str = "16px"
    na_text: str = "\u2014"
    border_style: Literal["boxed", "minimal"] = "boxed"
    border_color: str | None = None
    # tab10 (D3/matplotlib's default qualitative palette): high-contrast,
    # well-tested for line charts at small sizes.
    series_palette: tuple[str, ...] = (
        "#1F77B4",
        "#FF7F0E",
        "#2CA02C",
        "#D62728",
        "#9467BD",
        "#8C564B",
        "#E377C2",
        "#7F7F7F",
        "#BCBD22",
        "#17BECF",
    )
    dotplot_palette: tuple[str, str] = ("#3366AA", "#AA3377")

    def color(self, role: Role) -> str:
        """Return the colour registered for `role`.

        Parameters
        ----------
        role
            Semantic role.

        Returns
        -------
        str
            Hex colour string.
        """
        match role:
            case "favorable":
                return self.favorable
            case "unfavorable":
                return self.unfavorable
            case "inconclusive":
                return self.inconclusive
            case "neutral":
                return self.neutral
            case _:
                raise ValueError(f"Unknown role: {role!r}")

    def series_color(self, index: int) -> str:
        """Return the categorical colour for series `index`.

        Cycles modulo ``len(series_palette)`` so an arbitrary number of
        series always resolves to a colour.

        Parameters
        ----------
        index
            Zero-based, table-wide position of the series in its
            resolved order.

        Returns
        -------
        str
            Hex colour string.

        Raises
        ------
        ValueError
            If ``series_palette`` is empty or `index` is negative.
        """
        if not self.series_palette:
            raise ValueError("Theme.series_palette must not be empty")
        if index < 0:
            raise ValueError(f"series_color index must be non-negative, got {index}")
        return self.series_palette[index % len(self.series_palette)]

    def dotplot_color(self, value: float, domain: tuple[float, float]) -> str:
        """Map an original value onto an opaque, clamped sRGB colour ramp."""
        return self._dotplot_color_scale(domain)(value)

    def _dotplot_color_scale(self, domain: tuple[float, float]) -> Callable[[float], str]:
        """Validate and decode endpoints once for a rendered group of dots."""
        bounds = _dotplot_color_domain(True, domain, domain)
        assert bounds is not None  # noqa: S101 - gradient is enabled
        low, high = bounds
        span = high - low
        palette = self.dotplot_palette
        if (
            not isinstance(palette, (tuple, list))
            or len(palette) != 2
            or any(
                not isinstance(c, str) or re.fullmatch(r"#[0-9a-fA-F]{6}", c) is None
                for c in palette
            )
        ):
            raise SpecError("Dotplot palette requires two opaque six-digit hex colours")
        start, end = (tuple(int(c[i : i + 2], 16) for i in (1, 3, 5)) for c in palette)

        def color(value: float) -> str:
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise SpecError("Dotplot colour value must be finite")
            value = float(value)
            if value <= low:
                t = 0.0
            elif value >= high:
                t = 1.0
            elif math.isfinite(span):
                t = (value - low) / span
            else:
                t = (value / 2 - low / 2) / (high / 2 - low / 2)
            return "#" + "".join(
                f"{round(a + (b - a) * t):02x}" for a, b in zip(start, end, strict=True)
            )

        return color


def _dotplot_color_domain(
    gradient: bool,
    color_domain: tuple[float, float] | None,
    domain: tuple[float, float],
) -> tuple[float, float] | None:
    """Validate optional value colouring consistently across public surfaces."""
    if not isinstance(gradient, bool):
        raise SpecError("Dotplot gradient must be a bool")
    if not gradient:
        if color_domain is not None:
            raise SpecError("Dotplot color_domain requires gradient=True")
        return None
    bounds = domain if color_domain is None else color_domain
    if (
        not isinstance(bounds, (tuple, list))
        or len(bounds) != 2
        or any(
            isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(v) for v in bounds
        )
        or bounds[0] >= bounds[1]
    ):
        raise SpecError("Dotplot color_domain must have finite increasing endpoints")
    return (float(bounds[0]), float(bounds[1]))


def role_for(
    lower: float | None,
    upper: float | None,
    ref: float | None,
    direction: Direction,
) -> Role:
    """Map an interval to a semantic role.

    An interval lying entirely on one side of `ref` is favorable or unfavorable
    according to `direction`; one that spans `ref`, or that is unbounded on the
    deciding side, is inconclusive. A `direction` of ``"neutral"`` always yields
    ``"neutral"``, so a table making no directional claim does not look like a
    table full of null results. `ref=None` also always yields ``"neutral"``:
    "favorable" has no definition without a reference to compare against.

    Parameters
    ----------
    lower, upper
        Interval bounds. `None` means unbounded on that side.
    ref
        Reference value the interval is compared against. `None` means there
        is no reference, so the role is always `"neutral"`.
    direction
        Which side of `ref` counts as favorable.

    Returns
    -------
    Role
        The resolved role.
    """
    if direction == "neutral" or ref is None:
        return "neutral"
    if lower is not None and lower > ref:
        return "favorable" if direction == "higher_is_better" else "unfavorable"
    if upper is not None and upper < ref:
        return "unfavorable" if direction == "higher_is_better" else "favorable"
    return "inconclusive"


BLUE = Theme()

COLORBLIND = Theme(
    favorable="#0072B2",
    unfavorable="#D55E00",
    inconclusive="#999999",
    neutral="#0072B2",
    header_bg="#0072B2",
    column_label_bg="#7FB8DC",
    band="#EEF5FA",
    # Okabe-Ito: colour-blind-safe under all common CVD types.
    series_palette=(
        "#E69F00",
        "#56B4E9",
        "#009E73",
        "#F0E442",
        "#CC79A7",
        "#000000",
    ),
)

MONO = Theme(
    # Grayscale-only: direction is never colour-coded (favorable and
    # unfavorable share a shade), but significance is. A result whose
    # interval clears the reference (favorable/unfavorable) renders in a
    # dark, high-contrast gray; an inconclusive result is rendered in a
    # light gray to visually recede; neutral (no directional claim) sits
    # in between.
    favorable="#2B2B2B",
    unfavorable="#2B2B2B",
    inconclusive="#B0B0B0",
    neutral="#6E6E6E",
    header_bg="#343538",
    column_label_bg="#72767E",
    band="#F4F4F4",
    # Grayscale ramp -- MONO never sprouts hues, even for series identity.
    series_palette=(
        "#1A1A1A",
        "#4D4D4D",
        "#808080",
        "#A6A6A6",
        "#CCCCCC",
    ),
    dotplot_palette=("#444444", "#777777"),
)

TEXTUAL = Theme(
    # A quieter, publication-style theme: a muted palette, a light title
    # banner, no row banding, and borders confined to the top and bottom
    # rules -- closer to a printed table than a dashboard.
    favorable="#2E7D32",
    unfavorable="#C62828",
    inconclusive="#9E9E9E",
    neutral="#455A64",
    header_bg="#F5F5F5",
    header_fg="#1A1A1A",
    column_label_bg="#FAFAFA",
    band="#FFFFFF",
    surface="#FFFFFF",
    rule="#E0E0E0",
    axis="#616161",
    muted="#757575",
    text="#212121",
    border_style="minimal",
    border_color="#A8A8A8",
    # ColorBrewer Set2: softer/pastel than tab10, so overlaid ribbons
    # don't fight the muted publication aesthetic for attention.
    series_palette=(
        "#66C2A5",
        "#FC8D62",
        "#8DA0CB",
        "#E78AC3",
        "#A6D854",
        "#FFD92F",
        "#E5C494",
        "#B3B3B3",
    ),
)


DEFAULT = TEXTUAL
