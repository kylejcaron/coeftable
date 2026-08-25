"""Serialize adornments to HTML fragments.

The one place the closed adornment vocabulary meets HTML. Invariants:
no ``id=`` in any HTML this module emits (`InlineSvg` payloads are
producer-owned and may carry deterministic SVG-internal ids); every text
and theme value is escaped; `InlineSvg` payloads are verbatim; output is
deterministic; all geometry comes from `CardChrome` (colors from
`Theme`), and every text row declares the exact integer line-height
measurement assumes.
"""

from __future__ import annotations

import html
from typing import assert_never

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
    Variant,
)
from coeftable.cards.chrome import DEFAULT_CHROME, CardChrome, line_height
from coeftable.theme import DEFAULT, Theme

# Overlay-only geometry: the popover panel is absolutely positioned and
# excluded from measured footprints, so this is not a CardChrome field.
_POPOVER_PANEL_MIN_WIDTH = 160
_POPOVER_PANEL_BORDER = 1
_POPOVER_PANEL_PADDING = 6

# Paint-only geometry: border radius has no effect on the measured box.
_PILL_RADIUS = 999


def _esc(text: str) -> str:
    return html.escape(text, quote=True).replace("=", "&#61;")


def _row(size: int, color: str, chrome: CardChrome, extra: str = "") -> str:
    """Shared single-line row style: exact line-height, nowrap, clip-early."""
    return (
        f"color:{_esc(color)};font-size:{size}px;"
        f"line-height:{line_height(size, chrome)}px;white-space:nowrap;"
        f"overflow:hidden;text-overflow:ellipsis{extra}"
    )


def _variant_size(variant: Variant, chrome: CardChrome) -> int:
    match variant:
        case "title":
            return chrome.title_size
        case "subtitle":
            return chrome.subtitle_size
        case "body":
            return chrome.body_size
        case "caption":
            return chrome.caption_size


def _variant_color(variant: Variant, theme: Theme) -> str:
    return theme.text if variant in ("title", "body") else theme.muted


def _line_swatch(color: str, dash: str, chrome: CardChrome) -> str:
    return (
        f'<span style="display:inline-block;width:{chrome.swatch_width}px;'
        f"border-top:{chrome.swatch_thickness}px {_esc(dash)} {_esc(color)};"
        f'vertical-align:middle"></span>'
    )


def render_adornment(
    adornment: Adornment, *, theme: Theme = DEFAULT, chrome: CardChrome = DEFAULT_CHROME
) -> str:
    """Render one adornment as a self-contained HTML fragment."""
    match adornment:
        case TextBlock(text=text, variant=variant):
            size = _variant_size(variant, chrome)
            weight = ";font-weight:600" if variant == "title" else ""
            style = _row(size, _variant_color(variant, theme), chrome, weight)
            return f'<div style="{style}">{_esc(text)}</div>'
        case MetricValue(value=value, detail=detail, role=role):
            row_height = line_height(max(chrome.value_size, chrome.ci_size), chrome)
            out = (
                f'<div style="font-size:{chrome.value_size}px;'
                f"line-height:{row_height}px;white-space:nowrap;"
                f'overflow:hidden;text-overflow:ellipsis">'
                f'<span style="color:{_esc(theme.color(role))};'
                f'font-size:{chrome.value_size}px;font-weight:600">{_esc(value)}</span>'
            )
            if detail is not None:
                out += (
                    f'<span style="color:{_esc(theme.muted)};'
                    f"font-size:{chrome.ci_size}px;vertical-align:top;"
                    f'margin-left:{chrome.value_detail_gap}px">{_esc(detail)}</span>'
                )
            return out + "</div>"
        case InlineSvg(svg=svg):
            return svg
        case KeyValuePopover(label=label, items=items):
            item_line_height = line_height(chrome.control_size, chrome)
            rows = "".join(
                f'<div style="font-size:{chrome.control_size}px;'
                f'line-height:{item_line_height}px">'
                f'<span style="color:{_esc(theme.muted)}">{_esc(key)}</span> '
                f'<span style="color:{_esc(theme.text)}">{_esc(value)}</span></div>'
                for key, value in items
            )
            summary_style = _row(chrome.control_size, theme.text, chrome, ";cursor:pointer")
            return (
                '<details style="position:relative">'
                f'<summary style="{summary_style}">{_esc(label)}</summary>'
                f'<div style="position:absolute;left:0;top:100%;z-index:10;'
                f"min-width:{_POPOVER_PANEL_MIN_WIDTH}px;"
                f"background:{_esc(theme.surface)};"
                f"border:{_POPOVER_PANEL_BORDER}px solid {_esc(theme.rule)};"
                f"padding:{_POPOVER_PANEL_PADDING}px;"
                f'font-size:{chrome.control_size}px">{rows}</div></details>'
            )
        case SelectControl(label=label, options=options, selected=selected):
            rendered = "".join(
                f'<option value="{_esc(value)}"'
                f"{' selected' if value == selected else ''}>{_esc(text)}</option>"
                for value, text in options
            )
            row_height = line_height(chrome.control_size, chrome) + chrome.select_padding
            return (
                f'<label style="color:{_esc(theme.muted)};'
                f"font-size:{chrome.control_size}px;"
                f"line-height:{line_height(chrome.control_size, chrome)}px;"
                f"display:flex;align-items:center;column-gap:{chrome.swatch_gap}px;"
                f'height:{row_height}px;overflow:hidden;white-space:nowrap">'
                f'<span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;'
                f'width:calc(40% - {chrome.swatch_gap}px);flex:none">{_esc(label)}</span>'
                f'<select style="font-size:{chrome.control_size}px;'
                f"box-sizing:border-box;height:{line_height(chrome.control_size, chrome)}px;"
                f'line-height:{line_height(chrome.control_size, chrome)}px;width:60%;flex:none">'
                f"{rendered}</select>"
                "</label>"
            )
        case Badge(text=text, role=role):
            return (
                f'<span style="display:block;width:fit-content;'
                f"background:{_esc(theme.color(role))};"
                f"color:{_esc(theme.surface)};border-radius:{_PILL_RADIUS}px;"
                f"box-sizing:border-box;"
                f"padding:{chrome.chip_padding_y}px {chrome.chip_padding_x}px;"
                f"font-size:{chrome.chip_size}px;"
                f"line-height:{line_height(chrome.chip_size, chrome)}px;"
                f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%">'
                f"{_esc(text)}</span>"
            )
        case CaptionRow(text=text, color=color, dash=dash):
            marker = (
                ""
                if color is None
                else (
                    f"{_line_swatch(color, dash, chrome)}"
                    f'<span style="margin-left:{chrome.swatch_gap}px">'
                )
            )
            suffix = "" if color is None else "</span>"
            return (
                f'<div style="{_row(chrome.caption_size, theme.muted, chrome)}">'
                f"{marker}{_esc(text)}{suffix}</div>"
            )
        case Legend(entries=entries):
            chips = "".join(
                f'<span style="margin-right:{chrome.chip_gap}px;'
                f"font-size:{chrome.caption_size}px;"
                f'color:{_esc(theme.muted)}">'
                f'<span style="display:inline-block;width:{chrome.legend_swatch}px;'
                f"height:{chrome.legend_swatch}px;"
                f'background:{_esc(color)}"></span>'
                f'<span style="margin-left:{chrome.swatch_gap}px">{_esc(label)}</span></span>'
                for label, color in entries
            )
            style = _row(chrome.caption_size, theme.muted, chrome)
            return f'<div style="{style}">{chips}</div>'
        case RuleStrip(entries=entries):
            chips = "".join(
                f'<span style="margin-right:{chrome.chip_gap}px;'
                f"font-size:{chrome.caption_size}px;"
                f'color:{_esc(theme.muted)}">'
                f"{_line_swatch(color, dash, chrome)}"
                f'<span style="margin-left:{chrome.swatch_gap}px">{_esc(label)}</span></span>'
                for label, color, dash in entries
            )
            style = _row(chrome.caption_size, theme.muted, chrome)
            return f'<div style="{style}">{chips}</div>'
        case _:
            assert_never(adornment)
