"""Experimental card layer. Not part of the public coeftable API yet.

The adornment vocabulary is the closed content contract card regions
resolve into; `render_adornment` is its only serializer.
"""

from coeftable.cards.adornments import (
    Adornment,
    Badge,
    CaptionRow,
    InlineSvg,
    KeyValuePopover,
    Legend,
    MetricValue,
    RuleStrip,
    SelectControl,
    TextBlock,
)
from coeftable.cards.fragments import render_adornment

__all__ = [
    "Adornment",
    "Badge",
    "CaptionRow",
    "InlineSvg",
    "KeyValuePopover",
    "Legend",
    "MetricValue",
    "RuleStrip",
    "SelectControl",
    "TextBlock",
    "render_adornment",
]
