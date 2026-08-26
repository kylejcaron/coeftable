"""Deterministic HTML renderer for the experimental graph layer."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from coeftable.theme import Theme

if TYPE_CHECKING:
    from coeftable.graph.model import Graph, _GraphLayout
    from coeftable.graph.state import _CompiledState
    from coeftable.theme import Role


def _esc(value: str) -> str:
    """Escape a value for an HTML or SVG attribute/text node."""
    return html.escape(value, quote=True).replace("=", "&#61;")


def _number(value: float | int) -> str:
    """Serialize geometry without meaningless trailing decimal places."""
    return f"{value:g}"


def _label_color(theme: Theme, label_role: Role | None, label_color: str | None) -> str:
    """Resolve a wire label's semantic, explicit, or muted color."""
    if label_role is not None:
        return theme.color(label_role)
    if label_color is not None:
        return label_color
    return theme.muted


def _wire_svg(graph: Graph, layout: _GraphLayout, compiled: _CompiledState) -> str:
    """Render the underlay SVG from the graph's cached geometry."""
    measured = layout.measured
    boxes = dict(measured.boxes)
    anchors = dict(layout.anchors)
    axis = _esc(graph.theme.axis)
    surface = _esc(graph.theme.surface)
    marker_id = f"{graph.dom_prefix}-arrow"
    fragments = [
        (
            f'<svg width="{measured.width}" height="{measured.height}" '
            f'viewBox="0 0 {measured.width} {measured.height}" '
            f'style="position:absolute;left:0;top:0;width:{measured.width}px;'
            f'height:{measured.height}px;margin:0;padding:0;overflow:visible" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<defs><marker id="{marker_id}" markerWidth="8" markerHeight="8" '
            f'refX="6" refY="3" orient="auto" markerUnits="strokeWidth">'
            f'<path d="M 0 0 L 6 3 L 0 6 z" fill="{axis}"/></marker></defs>'
        )
    ]
    for wire, wire_dom_id in zip(graph.wires, compiled.wire_dom_ids, strict=True):
        src_left, src_top, _src_width, src_height = boxes[wire.src]
        dst_left, dst_top, _dst_width, _dst_height = boxes[wire.dst]
        _, (out_x, out_y) = anchors[wire.src]
        in_x, in_y = anchors[wire.dst][0]
        x0 = src_left + out_x
        y0 = src_top + out_y
        x1 = dst_left + in_x
        y1 = dst_top + in_y
        my = (src_top + src_height + dst_top) / 2
        path = (
            f'<path d="M {_number(x0)},{_number(y0)} C {_number(x0)},{_number(my)} '
            f'{_number(x1)},{_number(my)} {_number(x1)},{_number(y1 - 3)}" '
            f'fill="none" stroke="{axis}" stroke-width="1.5" marker-end="url(#{marker_id})"/>'
        )
        label = ""
        if wire.label is not None:
            t = 0.5
            inverse = 1 - t
            label_x = (
                inverse**3 * x0 + 3 * inverse**2 * t * x0 + 3 * inverse * t**2 * x1 + t**3 * x1
            )
            label_y = (
                inverse**3 * y0
                + 3 * inverse**2 * t * my
                + 3 * inverse * t**2 * my
                + t**3 * (y1 - 3)
                - 10
            )
            label = (
                f'<text x="{_number(label_x)}" y="{_number(label_y)}" text-anchor="middle" '
                f'fill="{_esc(_label_color(graph.theme, wire.label_role, wire.label_color))}" '
                f'style="paint-order:stroke;stroke:{surface};stroke-width:4px;'
                f'stroke-linejoin:round">{_esc(wire.label)}</text>'
            )
        fragments.append(f'<g id="{wire_dom_id}">{path}{label}</g>')
    fragments.append("</svg>")
    return "".join(fragments)


def _nub_markup(
    graph: Graph, layout: _GraphLayout, compiled: _CompiledState
) -> tuple[dict[str, str], str]:
    """Render each checkbox nub for its card and its sibling glyph rules."""
    boxes = dict(layout.measured.boxes)
    markup: dict[str, str] = {}
    rules: list[str] = []
    for card_id, nub_id in compiled.nub_dom_ids.items():
        _left, _top, width, height = boxes[card_id]
        markup[card_id] = (
            f'<input type="checkbox" id="{nub_id}" style="display:none">'
            f'<label for="{nub_id}" style="position:absolute;left:{_number((width - 18) / 2)}px;'
            f"top:{_number(height)}px;width:18px;height:18px;box-sizing:border-box;"
            f"display:flex;align-items:center;justify-content:center;border:1px solid "
            f"{_esc(graph.theme.axis)};border-radius:50%;background:{_esc(graph.theme.surface)};"
            f'color:{_esc(graph.theme.axis)};font-size:13px;line-height:16px;cursor:pointer">'
            f"<span>+</span><span>−</span></label>"
        )
        rules.extend(
            (
                f"#{nub_id} + label span:last-child{{display:none}}",
                f"#{nub_id}:checked + label span:first-child{{display:none}}",
                f"#{nub_id}:checked + label span:last-child{{display:inline}}",
            )
        )
    return markup, "".join(rules)


def _state_style(graph: Graph, compiled: _CompiledState, nub_rules: str) -> str:
    """Serialize the compiler's rules without deriving any new selectors."""
    styles: list[str] = []
    canvas = f".{graph.dom_prefix}-canvas"
    for conditions, targets in compiled.rules:
        prefix = canvas + "".join(f":has({condition})" for condition in conditions)
        selector_list = ",".join(f"{prefix} #{target}" for target in targets)
        styles.append(f"{selector_list}{{display:none}}")
    styles.append(nub_rules)
    return f"<style>{''.join(styles)}</style>" if styles else ""


def render_graph(graph: Graph) -> str:
    """Render a graph from its cached layout and compiled state."""
    layout = graph._layout
    measured = layout.measured
    compiled = graph._compiled
    svg = _wire_svg(graph, layout, compiled) if graph.wires else ""
    nubs, nub_rules = _nub_markup(graph, layout, compiled)
    cards_html: list[str] = []
    boxes = dict(measured.boxes)
    for (card_id, card), card_dom_id in zip(graph.nodes, compiled.card_dom_ids, strict=True):
        left, top, width, height = boxes[card_id]
        control_dom_ids = compiled.control_dom_ids.get(card_id)
        cards_html.append(
            f'<div id="{card_dom_id}" style="position:absolute;left:{_number(left)}px;'
            f'top:{_number(top)}px;width:{_number(width)}px;height:{_number(height)}px">'
            f"{card.as_raw_html(control_dom_ids=control_dom_ids)}{nubs.get(card_id, '')}</div>"
        )
    style = _state_style(graph, compiled, nub_rules) if (compiled.rules or nub_rules) else ""
    return (
        f'<div class="{graph.dom_prefix}-canvas" style="position:relative;box-sizing:border-box;'
        f'width:{measured.width}px;height:{measured.height}px;margin:0;padding:0;overflow:visible">'
        f"{svg}{''.join(cards_html)}{style}</div>"
    )


__all__ = ["render_graph"]
