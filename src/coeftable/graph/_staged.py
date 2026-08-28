"""Pure staged box placement shared by the graph's staged layout."""

from __future__ import annotations


def staged_boxes(
    entries: tuple[tuple[str, int, int, int, int], ...],
    *,
    lane_gap: int,
    stage_gap: int,
    padding: int,
) -> tuple[int, int, tuple[tuple[str, tuple[int, int, int, int]], ...]]:
    """Place each `(card_id, stage, lane, width, height)` entry on a grid.

    Stage advances the canvas rightward: each stage's offset is the padding
    plus every prior stage's widest occupant plus one `stage_gap`. Lane
    advances the canvas downward the same way, using each lane's tallest
    occupant and `lane_gap`. Every box keeps its own width and height rather
    than the shared stage/lane maximum, and boxes are returned in input
    order.
    """
    stage_widths: dict[int, int] = {}
    lane_heights: dict[int, int] = {}
    for _card_id, stage, lane, width, height in entries:
        stage_widths[stage] = max(stage_widths.get(stage, 0), width)
        lane_heights[lane] = max(lane_heights.get(lane, 0), height)
    stage_x: dict[int, int] = {}
    cursor = padding
    for stage in range(len(stage_widths)):
        stage_x[stage] = cursor
        cursor += stage_widths[stage] + stage_gap
    lane_y: dict[int, int] = {}
    cursor_y = padding
    for lane in range(len(lane_heights)):
        lane_y[lane] = cursor_y
        cursor_y += lane_heights[lane] + lane_gap
    boxes = tuple(
        (card_id, (stage_x[stage], lane_y[lane], width, height))
        for card_id, stage, lane, width, height in entries
    )
    width = max(x + box_width for _, (x, _y, box_width, _height) in boxes) + padding
    height = max(y + box_height for _, (_x, y, _width, box_height) in boxes) + padding
    return width, height, boxes
