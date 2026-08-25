"""Serialize adornments to HTML fragments.

The one place the closed adornment vocabulary meets HTML. Invariants:
no ``id=`` in anything this module emits (identity is minted later by the
state compiler; `InlineSvg` payloads are producer-owned); every text field
is escaped; output is deterministic; styling is inline from `Theme` until
card chrome exists.
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
from coeftable.theme import DEFAULT, Theme


def _esc(text: str) -> str:
    return html.escape(text, quote=True).replace("=", "&#61;")


def _text_style(variant: Variant, theme: Theme) -> str:
    match variant:
        case "title":
            return f"color:{_esc(theme.text)};font-weight:600;font-size:14px"
        case "subtitle":
            return f"color:{_esc(theme.muted)};font-size:12px"
        case "body":
            return f"color:{_esc(theme.text)};font-size:12px"
        case "caption":
            return f"color:{_esc(theme.muted)};font-size:11px"


def _line_swatch(color: str, dash: str) -> str:
    return (
        f'<span style="display:inline-block;width:14px;'
        f'border-top:2px {_esc(dash)} {_esc(color)};vertical-align:middle"></span>'
    )


def render_adornment(adornment: Adornment, *, theme: Theme = DEFAULT) -> str:
    """Render one adornment as a self-contained HTML fragment."""
    match adornment:
        case TextBlock(text=text, variant=variant):
            return f'<div style="{_text_style(variant, theme)}">{_esc(text)}</div>'
        case MetricValue(value=value, detail=detail, role=role):
            out = (
                f'<span style="color:{_esc(theme.color(role))};'
                f'font-size:{_esc(theme.value_size)};font-weight:600">{_esc(value)}</span>'
            )
            if detail is not None:
                out += (
                    f' <span style="color:{_esc(theme.muted)};'
                    f'font-size:{_esc(theme.ci_size)}">{_esc(detail)}</span>'
                )
            return out
        case InlineSvg(svg=svg):
            return svg
        case KeyValuePopover(label=label, items=items):
            rows = "".join(
                f'<div><span style="color:{_esc(theme.muted)}">{_esc(key)}</span> '
                f'<span style="color:{_esc(theme.text)}">{_esc(value)}</span></div>'
                for key, value in items
            )
            return (
                f'<details><summary style="color:{_esc(theme.text)};cursor:pointer">'
                f"{_esc(label)}</summary>"
                f'<div style="background:{_esc(theme.surface)};border:1px solid '
                f'{_esc(theme.rule)};padding:6px;font-size:11px">{rows}</div></details>'
            )
        case SelectControl(label=label, options=options, selected=selected):
            rendered = "".join(
                f'<option value="{_esc(value)}"'
                f"{' selected' if value == selected else ''}>{_esc(text)}</option>"
                for value, text in options
            )
            return (
                f'<label style="color:{_esc(theme.muted)};font-size:11px">{_esc(label)} '
                f'<select style="font-size:11px">{rendered}</select></label>'
            )
        case Badge(text=text, role=role):
            return (
                f'<span style="display:inline-block;background:{_esc(theme.color(role))};'
                f"color:{_esc(theme.surface)};border-radius:999px;padding:1px 8px;"
                f'font-size:10px">{_esc(text)}</span>'
            )
        case CaptionRow(text=text, color=color, dash=dash):
            marker = "" if color is None else _line_swatch(color, dash) + " "
            return (
                f'<div style="color:{_esc(theme.muted)};font-size:11px">{marker}{_esc(text)}</div>'
            )
        case Legend(entries=entries):
            chips = "".join(
                f'<span style="margin-right:10px;font-size:11px;'
                f'color:{_esc(theme.muted)}">'
                f'<span style="display:inline-block;width:8px;height:8px;'
                f'background:{_esc(color)}"></span> {_esc(label)}</span>'
                for label, color in entries
            )
            return f"<div>{chips}</div>"
        case RuleStrip(entries=entries):
            chips = "".join(
                f'<span style="margin-right:10px;font-size:11px;'
                f'color:{_esc(theme.muted)}">'
                f"{_line_swatch(color, dash)} {_esc(label)}</span>"
                for label, color, dash in entries
            )
            return f"<div>{chips}</div>"
        case _:
            assert_never(adornment)
