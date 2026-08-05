"""Colour roles, direction semantics and table chrome."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

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
)


DEFAULT = TEXTUAL
