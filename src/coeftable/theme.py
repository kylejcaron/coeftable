"""Colour roles, direction semantics and table chrome."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

type Role = Literal["favorable", "unfavorable", "inconclusive", "neutral"]
type Direction = Literal["higher_is_better", "lower_is_better", "neutral"]
type ColorRule = Callable[[float | None, float | None, float | None, float], Role]


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


def role_for(
    lower: float | None,
    upper: float | None,
    ref: float,
    direction: Direction,
) -> Role:
    """Map an interval to a semantic role.

    An interval lying entirely on one side of `ref` is favorable or unfavorable
    according to `direction`; one that spans `ref`, or that is unbounded on the
    deciding side, is inconclusive. A `direction` of ``"neutral"`` always yields
    ``"neutral"``, so a table making no directional claim does not look like a
    table full of null results.

    Parameters
    ----------
    lower, upper
        Interval bounds. `None` means unbounded on that side.
    ref
        Reference value the interval is compared against.
    direction
        Which side of `ref` counts as favorable.

    Returns
    -------
    Role
        The resolved role.
    """
    if direction == "neutral":
        return "neutral"
    if lower is not None and lower > ref:
        return "favorable" if direction == "higher_is_better" else "unfavorable"
    if upper is not None and upper < ref:
        return "unfavorable" if direction == "higher_is_better" else "favorable"
    return "inconclusive"


DEFAULT = Theme()

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
    favorable="#4A4A4A",
    unfavorable="#4A4A4A",
    inconclusive="#4A4A4A",
    neutral="#4A4A4A",
    header_bg="#343538",
    column_label_bg="#72767E",
    band="#F4F4F4",
)
