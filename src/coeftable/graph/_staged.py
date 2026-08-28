"""Pure staged box placement shared by the graph's staged layout."""

from __future__ import annotations


def staged_boxes(
    entries: tuple[tuple[str, int, int, int, int], ...],
    *,
    lane_gap: int,
    stage_gap: int,
    padding: int,
    top_padding: int | None = None,
    stage_inset: int = 0,
) -> tuple[int, int, tuple[tuple[str, tuple[int, int, int, int]], ...]]:
    """Place each `(card_id, stage, lane, width, height)` entry on a grid.

    Stage advances the canvas rightward: each stage's offset is the padding
    plus every prior stage's widest occupant, twice `stage_inset`, plus one
    `stage_gap`. Every card keeps its own intrinsic width and height rather
    than the shared stage/lane maximum, and boxes are returned in input
    order. `top_padding`, when given, replaces `padding` only as the
    initial y cursor (and thus the final height's outer margin); x padding
    is always `padding`, so a caller reserving vertical header space never
    shifts stage columns horizontally.

    `stage_inset` is a nonnegative horizontal margin reserved inside each
    stage column, on both sides of that column's widest card: the column's
    measured width is `widest_card_width + 2 * stage_inset`, and every card
    in it -- including narrower ones -- is horizontally centered inside
    that padded column rather than left-aligned to the column's edge. The
    leading and trailing inset are part of the canvas width and of
    `stage_gap`'s spacing between columns, so `stage_gap` remains the empty
    distance between two adjacent *padded* column bounds. `stage_inset=0`
    is handled as its own left-aligned case rather than centering with a
    zero margin, so every card -- not only each stage's widest one --
    keeps the exact prior placement, route geometry, and canvas footprint.
    """
    top = padding if top_padding is None else top_padding
    stage_widths: dict[int, int] = {}
    lane_heights: dict[int, int] = {}
    for _card_id, stage, lane, width, height in entries:
        stage_widths[stage] = max(stage_widths.get(stage, 0), width)
        lane_heights[lane] = max(lane_heights.get(lane, 0), height)
    stage_x: dict[int, int] = {}
    cursor = padding
    for stage in range(len(stage_widths)):
        stage_x[stage] = cursor
        cursor += stage_widths[stage] + 2 * stage_inset + stage_gap
    lane_y: dict[int, int] = {}
    cursor_y = top
    for lane in range(len(lane_heights)):
        lane_y[lane] = cursor_y
        cursor_y += lane_heights[lane] + lane_gap
    boxes = tuple(
        (
            card_id,
            (
                stage_x[stage]
                if stage_inset == 0
                else stage_x[stage] + stage_inset + (stage_widths[stage] - width) // 2,
                lane_y[lane],
                width,
                height,
            ),
        )
        for card_id, stage, lane, width, height in entries
    )
    width = (
        max(stage_x[stage] + stage_widths[stage] + 2 * stage_inset for stage in stage_widths)
        + padding
    )
    height = max(y + box_height for _, (_x, y, _width, box_height) in boxes) + padding
    return width, height, boxes
