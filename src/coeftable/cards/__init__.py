"""Experimental card layer. Not part of the public coeftable API yet.

The adornment vocabulary is the closed content contract card regions
resolve into; `render_adornment` is its only serializer.
"""

from coeftable.cards.adornments import (
    Adornment,
    Badge,
    Callout,
    CaptionRow,
    InlineSvg,
    KeyValuePopover,
    Legend,
    MetricValue,
    RuleStrip,
    SelectControl,
    TextBlock,
)
from coeftable.cards.card import Card, CardGrid
from coeftable.cards.chrome import DEFAULT_CHROME, CardChrome
from coeftable.cards.fragments import render_adornment
from coeftable.cards.measure import Anchor, MeasuredCard
from coeftable.cards.panel import MeasuredPanel, Pane, Panel, Row
from coeftable.cards.regions import (
    Diagnostics,
    Event,
    Events,
    Interval,
    Metric,
    Region,
    Trend,
    resolve_content,
)
from coeftable.cards.template import CardTemplate

__all__ = [
    "DEFAULT_CHROME",
    "Adornment",
    "Anchor",
    "Badge",
    "Callout",
    "CaptionRow",
    "Card",
    "CardChrome",
    "CardGrid",
    "CardTemplate",
    "Diagnostics",
    "Event",
    "Events",
    "InlineSvg",
    "Interval",
    "KeyValuePopover",
    "Legend",
    "MeasuredCard",
    "MeasuredPanel",
    "Metric",
    "MetricValue",
    "Pane",
    "Panel",
    "Region",
    "Row",
    "RuleStrip",
    "SelectControl",
    "TextBlock",
    "Trend",
    "render_adornment",
    "resolve_content",
]
