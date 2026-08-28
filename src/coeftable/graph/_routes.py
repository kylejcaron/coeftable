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


def route_skip_bow(src: Box, dst: Box, *, offset: float) -> Route:
    sx, sy = _right(src)
    dx, dy = _left(dst)
    middle = (sx + dx) / 2
    corridor = min(src[1], dst[1]) - offset
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


def route_back_sag(src: Box, dst: Box, *, offset: float) -> Route:
    sx, sy = _left(src)
    dx, dy = _right(dst)
    middle = (sx + dx) / 2
    corridor = max(src[1] + src[3], dst[1] + dst[3]) + offset
    path = (
        f"M{_n(sx)},{_n(sy)} C{_n(sx - offset)},{_n(sy)} "
        f"{_n(sx - offset)},{_n(corridor)} {_n(middle)},{_n(corridor)} "
        f"S{_n(dx + offset)},{_n(dy)} {_n(dx)},{_n(dy)}"
    )
    xs = (sx, sx - offset, dx + offset, dx)
    return Route(path, (middle, corridor), (min(xs), min(sy, dy), max(xs), corridor))


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
