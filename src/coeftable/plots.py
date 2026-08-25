"""Standalone inline-plot primitives.

The public face of coeftable's SVG layer: render a forest bar, sparkline,
or shared axis as a complete ``<svg>`` string without building a table.
These are the same emitters `CoefTable` uses for its plot columns, so a
standalone plot and a table column are styled identically under one
`Theme`.

Every function returns a complete ``<svg>…</svg>`` element ready for
embedding in HTML. Colors come from `Theme` roles (`theme.favorable`,
`coeftable.role_for`); formatters are any ``Callable[[float], str]``,
including `coeftable.Number` and `coeftable.Percent`. `ResolvedRule` and
`ResolvedBand` add reference lines and shaded intervals via the
``annotations=`` parameters.
"""

from coeftable.annotations import ResolvedBand, ResolvedRule
from coeftable.svg import (
    Trace,
    forest_axis,
    forest_bar,
    sparkline_axis,
    sparkline_bar,
    sparkline_multi,
)

__all__ = [
    "ResolvedBand",
    "ResolvedRule",
    "Trace",
    "forest_axis",
    "forest_bar",
    "sparkline_axis",
    "sparkline_bar",
    "sparkline_multi",
]
