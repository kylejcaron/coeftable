"""Pure SVG route geometry for resolved graph boxes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type Box = tuple[int, int, int, int]
type Point = tuple[float, float]


@dataclass(frozen=True, slots=True)
class Route:
    path: str
    label_anchor: Point
    bounds: tuple[float, float, float, float]


def _n(value: float) -> str:
    return f"{value:g}"


def _right(box: Box) -> Point:
    x, y, width, height = box
    return (x + width, y + height / 2)


def _left(box: Box) -> Point:
    x, y, _width, height = box
    return (x, y + height / 2)


def route_across(src: Box, dst: Box) -> Route:
    sx, sy = _right(src)
    dx, dy = _left(dst)
    middle = (sx + dx) / 2
    path = f"M{_n(sx)},{_n(sy)} C{_n(middle)},{_n(sy)} {_n(middle)},{_n(dy)} {_n(dx)},{_n(dy)}"
    return Route(
        path, (middle, (sy + dy) / 2), (min(sx, dx), min(sy, dy), max(sx, dx), max(sy, dy))
    )


def _bow_control(anchor: float, offset: float, gate: float) -> float:
    """Return a bow control coordinate clamped so it never crosses ``gate``.

    A packed offset can grow arbitrarily wide when many wires share one
    corridor; clamping here keeps the whole control hull inside the empty
    inter-stage gap next to ``anchor``'s own stage, regardless of how far
    the raw offset would otherwise push the unclamped control point.
    """
    if gate >= anchor:
        return min(anchor + offset, gate)
    return max(anchor - offset, gate)


def _gap_bowed_route(
    sx: float,
    sy: float,
    dx: float,
    dy: float,
    *,
    corridor: float,
    offset: float,
    src_gate: float,
    dst_gate: float,
) -> Route:
    """Bow into each endpoint's own empty gap, then cross flat at ``corridor``.

    A continuous two-cubic bow only touches its corridor height at one
    instant (the shared midpoint), so anywhere else along its width it
    sits below that height — grazing an intervening stage shorter than
    the one that set the corridor. Splitting the route instead confines
    each cubic's control hull to ``sx``..``src_gate`` or ``dst_gate``..
    ``dx``: the empty gap immediately next to its own endpoint's stage,
    which holds no cards at any height. A flat straight line then covers
    every intervening stage at a constant ``corridor`` height, which the
    caller already raised (or lowered) enough to clear all of them.
    """
    c1 = _bow_control(sx, offset, src_gate)
    c2 = _bow_control(dx, offset, dst_gate)
    path = (
        f"M{_n(sx)},{_n(sy)} C{_n(c1)},{_n(sy)} {_n(c1)},{_n(corridor)} "
        f"{_n(src_gate)},{_n(corridor)} L{_n(dst_gate)},{_n(corridor)} "
        f"C{_n(c2)},{_n(corridor)} {_n(c2)},{_n(dy)} {_n(dx)},{_n(dy)}"
    )
    xs = (sx, c1, src_gate, dst_gate, c2, dx)
    ys = (sy, corridor, dy)
    label_anchor = ((src_gate + dst_gate) / 2, corridor)
    return Route(path, label_anchor, (min(xs), min(ys), max(xs), max(ys)))


def route_skip_bow(
    src: Box,
    dst: Box,
    *,
    offset: float,
    bound: float | None = None,
    src_gate: float | None = None,
    dst_gate: float | None = None,
) -> Route:
    """Route a skip edge's bow above ``src`` and ``dst``.

    ``bound`` overrides the corridor's base edge; pass the minimum top
    across every stage the wire spans (not just its own two endpoints) so
    the bow clears every card sharing an intervening stage, not only
    ``src`` and ``dst``. Omitting it falls back to the two boxes' own tops.

    ``src_gate`` and ``dst_gate`` anchor the bow to the empty inter-stage
    gap immediately after ``src``'s stage and immediately before ``dst``'s
    stage: pass the midpoint of each gap's per-stage left/right extents
    (see `model.py`'s `_flow_route`) so the curved portions never reach
    past that empty gap into a neighboring stage's cards, leaving only a
    flat straight line to cross every intervening stage. Omitting either
    keeps the original, continuous two-cubic bow unchanged.
    """
    sx, sy = _right(src)
    dx, dy = _left(dst)
    top = min(src[1], dst[1]) if bound is None else bound
    corridor = top - offset
    if src_gate is None or dst_gate is None:
        middle = (sx + dx) / 2
        path = (
            f"M{_n(sx)},{_n(sy)} C{_n(sx + offset)},{_n(sy)} "
            f"{_n(sx + offset)},{_n(corridor)} {_n(middle)},{_n(corridor)} "
            f"S{_n(dx - offset)},{_n(dy)} {_n(dx)},{_n(dy)}"
        )
        xs = (sx, sx + offset, dx - offset, dx)
        return Route(
            path,
            (middle, corridor),
            (min(xs), min(corridor, sy, dy), max(xs), max(corridor, sy, dy)),
        )
    return _gap_bowed_route(
        sx, sy, dx, dy, corridor=corridor, offset=offset, src_gate=src_gate, dst_gate=dst_gate
    )


def route_back_sag(
    src: Box,
    dst: Box,
    *,
    offset: float,
    bound: float | None = None,
    src_gate: float | None = None,
    dst_gate: float | None = None,
) -> Route:
    """Route a back edge's sag below ``src`` and ``dst``.

    ``bound`` overrides the corridor's base edge; pass the maximum bottom
    across every stage the wire spans (not just its own two endpoints) so
    the sag clears every card sharing an intervening stage, not only
    ``src`` and ``dst``. Omitting it falls back to the two boxes' own
    bottoms.

    ``src_gate`` and ``dst_gate`` anchor the sag to the empty inter-stage
    gap immediately before ``src``'s stage and immediately after ``dst``'s
    stage: pass the midpoint of each gap's per-stage left/right extents
    (see `model.py`'s `_flow_route`) so the curved portions never reach
    past that empty gap into a neighboring stage's cards, leaving only a
    flat straight line to cross every intervening stage. Omitting either
    keeps the original, continuous two-cubic sag unchanged.
    """
    sx, sy = _left(src)
    dx, dy = _right(dst)
    bottom = max(src[1] + src[3], dst[1] + dst[3]) if bound is None else bound
    corridor = bottom + offset
    if src_gate is None or dst_gate is None:
        middle = (sx + dx) / 2
        path = (
            f"M{_n(sx)},{_n(sy)} C{_n(sx - offset)},{_n(sy)} "
            f"{_n(sx - offset)},{_n(corridor)} {_n(middle)},{_n(corridor)} "
            f"S{_n(dx + offset)},{_n(dy)} {_n(dx)},{_n(dy)}"
        )
        xs = (sx, sx - offset, dx + offset, dx)
        return Route(path, (middle, corridor), (min(xs), min(sy, dy), max(xs), corridor))
    return _gap_bowed_route(
        sx, sy, dx, dy, corridor=corridor, offset=offset, src_gate=src_gate, dst_gate=dst_gate
    )


def route_c_loop(
    src: Box,
    dst: Box,
    *,
    offset: float,
    side: Literal["left", "right"],
    bound: float | None = None,
) -> Route:
    """Route a same-stage loop around ``side``.

    ``bound`` overrides the corridor's base edge; pass the whole stage
    column's own outer edge (not just this wire's two endpoints) so the
    loop clears every sibling card sharing that column, not only ``src``
    and ``dst``. Omitting it falls back to the two boxes' own edges.
    """
    if side == "left":
        sx, sy = _left(src)
        dx, dy = _left(dst)
        edge = min(src[0], dst[0]) if bound is None else bound
        corridor = edge - offset
    else:
        sx, sy = _right(src)
        dx, dy = _right(dst)
        edge = max(src[0] + src[2], dst[0] + dst[2]) if bound is None else bound
        corridor = edge + offset
    middle_y = (sy + dy) / 2
    path = f"M{_n(sx)},{_n(sy)} C{_n(corridor)},{_n(sy)} {_n(corridor)},{_n(dy)} {_n(dx)},{_n(dy)}"
    return Route(
        path,
        (corridor, middle_y),
        (min(corridor, sx, dx), min(sy, dy), max(corridor, sx, dx), max(sy, dy)),
    )
