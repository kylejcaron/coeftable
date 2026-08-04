import re
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from coeftable.format import DateAxis, Number
from coeftable.svg import (
    _CALENDAR_TICK_FLOOR,
    _CHAR_WIDTH_RATIO,
    _MIN_LABEL_GAP,
    _SUPER_ROW_OFFSET,
    _bare_label,
    _calendar_groups,
    _fits,
    _label_boxes,
    _max_bare_ticks,
    _projector,
    _resolve_collisions,
    _select_bare_rung,
    _super_row,
    calendar_ticks,
    forest_axis,
    forest_bar,
    nice_ticks,
    sparkline_axis,
    sparkline_bar,
)
from coeftable.theme import DEFAULT


def test_nice_ticks_are_round_and_inside_domain():
    ticks = nice_ticks(0.0, 10.0)
    assert ticks
    assert all(0.0 <= t <= 10.0 for t in ticks)
    assert ticks == [round(t, 10) for t in ticks]


def test_nice_ticks_handles_degenerate_domain():
    assert nice_ticks(5.0, 5.0) == [5.0]
    assert nice_ticks(5.0, 1.0) == []


def test_nice_ticks_handles_negative_domain():
    ticks = nice_ticks(-10.0, -2.0)
    assert ticks
    assert all(-10.0 <= t <= -2.0 for t in ticks)


def test_forest_bar_is_well_formed_svg():
    svg = forest_bar(1.0, 0.5, 1.5, domain=(0.0, 2.0), ref=0.0, color="#55A868", theme=DEFAULT)
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert "<rect" in svg
    assert "#55A868" in svg


def test_forest_bar_reference_line_spans_the_passed_height():
    svg = forest_bar(
        1.0, 0.5, 1.5, domain=(0.0, 2.0), ref=0.0, color="#000", theme=DEFAULT, height=48
    )
    assert 'y1="0" x2="' in svg
    assert 'y2="48"' in svg
    assert 'height="48"' in svg


def test_forest_bar_draws_reference_line_only_when_inside_domain():
    inside = forest_bar(1.0, 0.5, 1.5, domain=(-1.0, 2.0), ref=0.0, color="#000", theme=DEFAULT)
    outside = forest_bar(1.0, 0.5, 1.5, domain=(0.5, 2.0), ref=0.0, color="#000", theme=DEFAULT)
    assert "stroke-dasharray" in inside
    assert "stroke-dasharray" not in outside


def test_forest_bar_caps_clipped_upper_bound():
    svg = forest_bar(1.0, 0.5, 99.0, domain=(0.0, 2.0), ref=0.0, color="#000", theme=DEFAULT)
    assert "<polygon" in svg


def test_forest_bar_treats_unbounded_upper_as_clipped():
    svg = forest_bar(1.0, 0.5, None, domain=(0.0, 2.0), ref=0.0, color="#000", theme=DEFAULT)
    assert "<polygon" in svg


def test_forest_bar_caps_clipped_lower_bound():
    svg = forest_bar(1.0, -99.0, 1.5, domain=(0.0, 2.0), ref=0.0, color="#000", theme=DEFAULT)
    assert "<polygon" in svg


def test_forest_bar_treats_unbounded_lower_as_clipped():
    svg = forest_bar(1.0, None, 1.5, domain=(0.0, 2.0), ref=0.0, color="#000", theme=DEFAULT)
    assert "<polygon" in svg


def test_forest_bar_without_clipping_has_no_cap():
    svg = forest_bar(1.0, 0.5, 1.5, domain=(0.0, 2.0), ref=0.0, color="#000", theme=DEFAULT)
    assert "<polygon" not in svg


def test_forest_bar_survives_zero_width_domain():
    svg = forest_bar(1.0, 1.0, 1.0, domain=(1.0, 1.0), ref=0.0, color="#000", theme=DEFAULT)
    assert svg.startswith("<svg")


def test_forest_bar_coordinates_are_two_decimals():
    svg = forest_bar(1.0, 0.5, 1.5, domain=(0.0, 3.0), ref=0.0, color="#000", theme=DEFAULT)
    for value in re.findall(r'x="([-\d.]+)"', svg):
        if "." in value:
            assert len(value.split(".")[1]) <= 2


def test_forest_axis_renders_tick_labels():
    svg = forest_axis(domain=(0.0, 10.0), ref=0.0, fmt=Number(decimals=0), theme=DEFAULT)
    assert "<text" in svg
    assert svg.startswith("<svg")


def test_forest_axis_anchors_a_tick_label_only_when_it_would_clip():
    # A wide label at the right edge overflows the canvas if centred, so it
    # anchors "end"; a one-character label at the left edge fits centred and
    # must stay "middle" -- anchoring purely by tick index would wrongly
    # shift it off its own tick mark.
    svg = forest_axis(domain=(0.0, 3000.0), ref=0.0, fmt=Number(decimals=0), theme=DEFAULT)
    labels = re.findall(r'text-anchor="([^"]+)">([^<]*)</text>', svg)
    assert labels
    assert labels[0] == ("middle", "0")
    assert labels[-1][0] == "end"


def test_sparkline_axis_anchors_a_clipping_temporal_tick_label():
    # The originally observed bug: a month label on the first tick sits at
    # x=inset and, centred, loses its leading character off-canvas ("Jan" ->
    # "an"). Covers the sparkline_axis call site and its two-tier sub-row.
    low = datetime(2024, 1, 1, tzinfo=UTC).timestamp()
    high = datetime(2024, 3, 1, tzinfo=UTC).timestamp()
    svg = sparkline_axis(
        x_domain=(low, high), fmt=DateAxis(), theme=DEFAULT, temporal=True, target_ticks=1
    )
    labels = re.findall(r'text-anchor="([^"]+)">([^<]*)</text>', svg)
    assert labels
    assert labels[0] == ("start", "Jan")


def test_sparkline_axis_falls_back_to_cascaded_labels_when_no_super_row_fits(
    monkeypatch: pytest.MonkeyPatch,
):
    # Defense in depth: if `_super_row` ever fails to admit any arrangement
    # (e.g. a collision `_resolve_collisions` can't clear by dropping an
    # edge -- confirmed unreachable via real calendar domains by a 6,000
    # case sweep, but not structurally impossible), the sub-row must not
    # fall back to bare, context-free numbers with no month/year anywhere.
    import coeftable.svg as svg_module

    def no_super_row(
        sub_step: object, low: float, high: float, *, project: object, width: int
    ) -> None:
        return None

    monkeypatch.setattr(svg_module, "_super_row", no_super_row)
    low = datetime(2024, 1, 17, tzinfo=UTC).timestamp()
    high = datetime(2024, 3, 17, tzinfo=UTC).timestamp()
    svg = sparkline_axis(
        x_domain=(low, high), fmt=DateAxis(), theme=DEFAULT, temporal=True, show_endpoint=False
    )
    assert 'height="22"' in svg  # no super row built -> single-row height
    labels = re.findall(r'text-anchor="[^"]+">([^<]*)</text>', svg)
    assert labels
    assert labels[0].startswith("Jan")  # cascaded, not a bare "17"


def test_max_bare_ticks_skip_bound_includes_the_edge_drop_slack():
    # `_resolve_collisions` can admit an arrangement with up to 2 labels
    # dropped from the edges (when they -- and only they -- collide with
    # their neighbour), so `_select_bare_rung`'s skip must allow a rung's
    # raw tick count up to `_max_bare_ticks(...) + 2`, not just the bound
    # itself, or it would wrongly exclude a genuinely admissible rung
    # before ever calling `_resolve_collisions` on it.
    #
    # Constructed directly: `bound` 1-char labels packed at exactly the
    # minimum pitch fill `width` with no slack, plus one extra label
    # crammed just inside each end -- close enough to collide with its
    # sole neighbour, nothing else. Reproducible with `bound=4`, `width=28`.
    width = 28
    bound = _max_bare_ticks("day", width)
    assert bound == 4
    min_width = 1 * 9.0 * _CHAR_WIDTH_RATIO
    pitch = min_width + _MIN_LABEL_GAP
    interior = [min_width / 2 + i * pitch for i in range(bound)]
    xs = [interior[0] - pitch * 0.3, *interior, interior[-1] + pitch * 0.3]
    texts = ["1"] * len(xs)
    n = len(xs)
    assert n == bound + 2
    admitted = _resolve_collisions(xs, lambda kept, t=texts: [t[i] for i in kept], width)
    assert admitted is not None  # only reachable by dropping both edges
    assert admitted[0] == "" and admitted[-1] == ""
    assert all(admitted[1:-1])


def test_sparkline_bar_is_well_formed_svg():
    x = [0.0, 1.0, 2.0]
    y = [1.0, 1.2, 0.9]
    lower = [0.8, 1.0, 0.7]
    upper = [1.2, 1.4, 1.1]
    svg = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 2.0),
        domain=(0.0, 2.0),
        ref=0.0,
        color="#55A868",
        fmt=Number(decimals=1),
    )
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert "<polyline" in svg
    assert "<polygon" in svg
    assert "#55A868" in svg


def test_sparkline_bar_ribbon_point_count_matches_series_length():
    x = [0.0, 1.0, 2.0, 3.0]
    y = [1.0, 1.2, 0.9, 1.1]
    lower = [0.5, 0.7, 0.4, 0.6]
    upper = [1.5, 1.7, 1.4, 1.6]
    svg = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 3.0),
        domain=(0.0, 2.0),
        ref=0.0,
        color="#4C72B0",
        fmt=Number(decimals=1),
    )
    match = re.search(r'<polygon points="([^"]+)"', svg)
    assert match
    points = match.group(1).split(" ")
    assert len(points) == 2 * len(x)


def test_sparkline_bar_gap_splits_ribbon_and_line_into_separate_runs():
    x = [0.0, 1.0, 2.0, 3.0]
    y = [1.0, float("nan"), 0.9, 1.1]
    lower = [0.5, 0.6, 0.4, 0.6]
    upper = [1.5, 1.6, 1.4, 1.6]
    svg = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 3.0),
        domain=(0.0, 2.0),
        ref=0.0,
        color="#4C72B0",
        fmt=Number(decimals=1),
    )
    assert svg.count("<polygon") == 2
    assert svg.count("<polyline") == 2


def test_sparkline_bar_draws_reference_line_only_when_inside_domain():
    x = [0.0, 1.0, 2.0]
    y = [1.0, 1.2, 0.9]
    lower = [0.8, 1.0, 0.7]
    upper = [1.2, 1.4, 1.1]
    inside = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 2.0),
        domain=(0.0, 2.0),
        ref=0.5,
        color="#000",
        fmt=Number(decimals=1),
    )
    outside = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 2.0),
        domain=(1.0, 2.0),
        ref=0.5,
        color="#000",
        fmt=Number(decimals=1),
    )
    assert "stroke-dasharray" in inside
    assert "stroke-dasharray" not in outside


def test_sparkline_bar_hides_endpoint_label_when_disabled():
    x = [0.0, 1.0, 2.0]
    y = [1.0, 1.2, 0.9]
    lower = [0.8, 1.0, 0.7]
    upper = [1.2, 1.4, 1.1]
    svg = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 2.0),
        domain=(0.0, 2.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
        show_endpoint=False,
    )
    assert "<text" not in svg


def test_sparkline_bar_all_missing_series_is_valid_and_empty():
    x = [0.0, 1.0, 2.0]
    y = [None, float("nan"), None]
    lower = [None, None, None]
    upper = [None, None, None]
    svg = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 2.0),
        domain=(-1.0, 1.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
    )
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert "<line" not in svg
    assert "<polyline" not in svg
    assert "<polygon" not in svg
    assert "<circle" not in svg
    assert "<text" not in svg


def test_sparkline_bar_clips_overlong_endpoint_label():
    x = [0.0, 1.0, 2.0]
    y = [1.0, 1.2, 0.9]
    lower = [0.8, 1.0, 0.7]
    upper = [1.2, 1.4, 1.1]
    svg = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 2.0),
        domain=(0.0, 2.0),
        ref=0.0,
        color="#000",
        fmt=lambda _: "-12,345.6789%",
        endpoint_width=20,
    )
    label = re.search(r"<text[^>]*>([^<]+)</text>", svg)
    assert label
    assert label.group(1).endswith("\u2026")
    assert label.group(1) != "-12,345.6789%"


def test_sparkline_bar_endpoint_label_anchors_on_last_valid_point_after_trailing_gap():
    x = [0.0, 1.0, 2.0]
    y = [1.0, 1.2, None]
    lower = [0.8, 1.0, None]
    upper = [1.2, 1.4, None]
    svg = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 2.0),
        domain=(0.0, 2.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
    )
    line = re.search(r'<polyline points="([^"]+)"', svg)
    assert line
    last_point_y = float(line.group(1).split(" ")[-1].split(",")[1])
    label = re.search(r'<text x="[^"]+" y="([^"]+)"', svg)
    assert label
    assert float(label.group(1)) == round(last_point_y + 3, 2)


def test_sparkline_bar_projects_true_x_not_index():
    # x jumps from 2 to 20 on the last point -- an index-based (not
    # x-value-based) projection would space every gap identically.
    x = [0.0, 1.0, 2.0, 20.0]
    y = [1.0, 1.3, 0.8, 1.5]
    lower = [0.8, 1.0, 0.6, 1.2]
    upper = [1.2, 1.6, 1.0, 1.8]
    svg = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 20.0),
        domain=(0.0, 2.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
        show_endpoint=False,
    )
    line = re.search(r'<polyline points="([^"]+)"', svg)
    assert line
    xs = [float(pair.split(",")[0]) for pair in line.group(1).split(" ")]
    gaps = [b - a for a, b in pairwise(xs)]
    assert gaps[0] == gaps[1]
    assert gaps[2] > gaps[0] * 5


def test_sparkline_bar_endpoint_reserve_is_label_length_independent():
    # The alignment invariant, direction one: rows whose endpoint labels
    # format to very different lengths must still share the same first/last
    # data x-coordinates, proving the endpoint reserve never depends on the
    # formatted label. Direction two -- that `sparkline_axis` ticks coincide
    # with these same projected x-coordinates -- is covered by
    # test_sparkline_axis_ticks_align_with_sparkline_bar_points below.
    x = [0.0, 1.0, 2.0]
    y = [1.0, 1.2, 0.9]
    lower = [0.8, 1.0, 0.7]
    upper = [1.2, 1.4, 1.1]

    def endpoints(svg: str) -> tuple[float, float]:
        line = re.search(r'<polyline points="([^"]+)"', svg)
        assert line
        xs = [float(pair.split(",")[0]) for pair in line.group(1).split(" ")]
        return xs[0], xs[-1]

    short = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 2.0),
        domain=(0.0, 2.0),
        ref=0.0,
        color="#000",
        fmt=lambda _: "1%",
    )
    long = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 2.0),
        domain=(0.0, 2.0),
        ref=0.0,
        color="#000",
        fmt=lambda _: "-12,345%",
    )

    assert endpoints(short) == endpoints(long)


def _cap_edge_count(svg: str) -> int:
    """Count distinct clip-cap brackets (each a 0.45-opacity double line) in a rendered SVG."""
    return svg.count('stroke-opacity="0.45"') // 2


def _real_polylines(svg: str) -> list[str]:
    """Extract each non-ghost line polyline's `points` attribute, in document order."""
    return re.findall(
        r'<polyline points="([^"]+)" fill="none" stroke="[^"]+" stroke-width="1.5"/>', svg
    )


def _ghost_polylines(svg: str) -> list[str]:
    """Extract each ghost (low-opacity) line polyline's `points` attribute."""
    return re.findall(
        r'<polyline points="([^"]+)" fill="none" stroke="[^"]+" '
        r'stroke-width="1.5" stroke-opacity="0.35"/>',
        svg,
    )


def test_sparkline_bar_clips_a_segment_at_the_exact_boundary_crossing():
    # Segment (0, 0) -> (1, 10) crosses domain high=5 at t = (5-0)/(10-0) =
    # 0.5, i.e. domain x=0.5. With x_domain=(0, 1), width=100, inset=0 the
    # projector is the identity times 100, so the crossing lands at pixel
    # x=50.00 exactly -- hand-computed, not read back from the
    # implementation under test.
    x = [0.0, 1.0]
    y = [0.0, 10.0]
    svg = sparkline_bar(
        x,
        y,
        [None, None],
        [None, None],
        x_domain=(0.0, 1.0),
        domain=(0.0, 5.0),
        ref=-999.0,
        color="#000",
        fmt=Number(decimals=1),
        width=100,
        height=30,
        inset=0,
        show_endpoint=False,
    )
    assert _real_polylines(svg) == ["0.00,30.00 50.00,0.00"]
    assert _ghost_polylines(svg) == ["0.00,30.00 100.00,-30.00"]
    # The cap spans the crossing (50.00) to the run's own end (100.00, the
    # last data point, since the line never re-enters bounds), padded 3px
    # past each end, straddling the domain's high edge (pixel y=0).
    caps = re.findall(
        r'<line x1="([\d.-]+)" y1="([\d.-]+)" x2="([\d.-]+)" y2="[\d.-]+" '
        r'stroke="[^"]+" stroke-width="0.5" stroke-opacity="0.45"/>',
        svg,
    )
    assert caps == [("47.00", "-0.50", "103.00"), ("47.00", "0.50", "103.00")]


def test_sparkline_bar_zigzag_clip_stays_one_polyline_per_in_bounds_run():
    # A single mid-series spike leaves and re-enters the domain -- a naive
    # per-segment implementation would draw the surrounding in-bounds
    # points as separate fragments, losing proper vertex joins and
    # notching visibly at x=1 and x=3. The fix groups each side into one
    # continuous polyline instead.
    x = [0.0, 1.0, 2.0, 3.0, 4.0]
    y = [1.0, 1.0, 20.0, 1.0, 1.0]
    svg = sparkline_bar(
        x,
        y,
        [None] * 5,
        [None] * 5,
        x_domain=(0.0, 4.0),
        domain=(0.0, 10.0),
        ref=-999.0,
        color="#000",
        fmt=Number(decimals=1),
        width=400,
        height=30,
        inset=0,
        show_endpoint=False,
    )
    real = _real_polylines(svg)
    assert len(real) == 2  # one continuous run before the spike, one after
    assert len(real[0].split(" ")) == 3  # (0,1), (1,1), and the crossing -- not fragmented
    assert len(real[1].split(" ")) == 3  # the other crossing, (3,1), and (4,1)
    ghost = _ghost_polylines(svg)
    assert len(ghost) == 1  # the whole raw run in one piece, unsplit
    assert len(ghost[0].split(" ")) == 5
    assert _cap_edge_count(svg) == 1  # one merged bracket, not two


def test_sparkline_bar_ghost_trace_and_real_line_connects_without_a_kink():
    # Spike up through the high edge and back down -- two crossings. If the
    # real line used different geometry than the ghost (e.g. a per-point
    # clamp instead of segment-boundary intersection) the two would
    # visibly kink apart right at the edge; with matching geometry the
    # real line's boundary endpoints must land exactly on the ghost's own
    # straight-line trajectory.
    x = [0.0, 1.0, 2.0]
    y = [0.0, 10.0, 0.0]
    svg = sparkline_bar(
        x,
        y,
        [None] * 3,
        [None] * 3,
        x_domain=(0.0, 2.0),
        domain=(0.0, 5.0),
        ref=-999.0,
        color="#000",
        fmt=Number(decimals=1),
        width=200,
        height=30,
        inset=0,
        show_endpoint=False,
    )
    assert _ghost_polylines(svg) == ["0.00,30.00 100.00,-30.00 200.00,30.00"]
    # Ghost segment (0,30)->(100,-30) crosses y=0 at t=0.5 -> x=50; segment
    # (100,-30)->(200,30) crosses y=0 at t=0.5 -> x=150. Both real pieces'
    # boundary endpoints land exactly there, at y=0.00.
    assert _real_polylines(svg) == ["0.00,30.00 50.00,0.00", "150.00,0.00 200.00,30.00"]


def test_sparkline_bar_hard_clip_path_only_appears_when_something_clips():
    x = [0.0, 1.0, 2.0]
    y = [1.0, 1.2, 0.9]
    lower = [0.8, 1.0, 0.7]
    upper = [1.2, 1.4, 1.1]
    no_clip = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 2.0),
        domain=(0.0, 2.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
    )
    assert "<clipPath" not in no_clip
    assert "clip-path=" not in no_clip

    clipped = sparkline_bar(
        [0.0, 1.0, 2.0],
        [1.0, 300.0, 1.0],
        [None] * 3,
        [None] * 3,
        x_domain=(0.0, 2.0),
        domain=(0.0, 20.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
    )
    assert "<clipPath" in clipped
    assert 'clip-path="url(#' in clipped


def test_sparkline_bar_real_layer_never_escapes_the_canvas_even_though_the_ghost_does():
    # The original bug: y=300 against domain (0, 20) on a 30px canvas
    # produced an off-canvas coordinate in the ONLY rendered line. Now the
    # ghost trace is DELIBERATELY allowed off-canvas (the SVG's own
    # viewport clips it visually) -- but the real, domain-clipped layer
    # must never carry a coordinate outside the canvas.
    x = [0.0, 1.0, 2.0]
    y = [1.0, 300.0, 1.0]
    svg = sparkline_bar(
        x,
        y,
        [None, None, None],
        [None, None, None],
        x_domain=(0.0, 2.0),
        domain=(0.0, 20.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
    )
    real_ys = [
        float(pair.split(",")[1]) for piece in _real_polylines(svg) for pair in piece.split(" ")
    ]
    assert all(0.0 <= y_px <= 30.0 for y_px in real_ys)
    ghost_ys = [
        float(pair.split(",")[1]) for piece in _ghost_polylines(svg) for pair in piece.split(" ")
    ]
    assert any(y_px < 0.0 or y_px > 30.0 for y_px in ghost_ys)  # legitimately off-canvas
    assert 'y="-333.00"' not in svg  # never a raw off-canvas XML attribute, only inside points=


def test_sparkline_bar_series_inside_domain_has_no_clip_flags():
    x = [0.0, 1.0, 2.0, 3.0]
    y = [1.0, 1.2, 0.9, 1.1]
    lower = [0.5, 0.7, 0.4, 0.6]
    upper = [1.5, 1.7, 1.4, 1.6]
    svg = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 3.0),
        domain=(0.0, 2.0),
        ref=0.0,
        color="#4C72B0",
        fmt=Number(decimals=1),
    )
    assert re.findall(r'<polygon points="[^"]+" fill="[^"]+"/>', svg) == []
    assert svg.count("<polygon") == 1  # only the ribbon fill, no clip flags


def test_sparkline_bar_gap_and_clip_are_independent_breaks():
    # index 1 is a genuine gap (NaN); index 3 has data, just off-scale. A
    # gap always splits _line_runs into a new run -- unrelated to this
    # redesign -- what matters here is that the clip inside the SECOND run
    # doesn't bleed into the first: only the run containing the clip gets
    # a ghost trace and a cap.
    x = [0.0, 1.0, 2.0, 3.0, 4.0]
    y = [1.0, float("nan"), 1.0, 300.0, 1.0]
    svg = sparkline_bar(
        x,
        y,
        [None] * 5,
        [None] * 5,
        x_domain=(0.0, 4.0),
        domain=(0.0, 20.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
    )
    assert len(_ghost_polylines(svg)) == 1  # only the post-gap run clips
    assert _cap_edge_count(svg) == 1


def test_sparkline_bar_isolated_clipped_point_with_no_segment_still_raises_a_cap():
    # index 0 is clipped but has no neighbour on either side (index 1 is a
    # gap) -- there is no line segment to compute a boundary crossing
    # from. Without special-casing this, a lone clipped point would
    # silently raise no cap at all, exactly the kind of under-communicated
    # clip this redesign exists to prevent.
    x = [0.0, 1.0, 2.0, 3.0, 4.0]
    y = [300.0, float("nan"), 1.0, 1.0, 1.0]
    svg = sparkline_bar(
        x,
        y,
        [None] * 5,
        [None] * 5,
        x_domain=(0.0, 4.0),
        domain=(0.0, 20.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
    )
    assert _cap_edge_count(svg) == 1


def test_sparkline_bar_isolated_clipped_ribbon_bound_with_no_segment_still_raises_a_cap():
    # Same isolated-point edge case, but the clip is on the ribbon's upper
    # bound rather than the point itself.
    x = [0.0, 1.0, 2.0, 3.0, 4.0]
    y = [1.0] * 5
    lower = [0.5, None, 0.5, 0.5, 0.5]
    upper = [300.0, None, 1.5, 1.5, 1.5]
    svg = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 4.0),
        domain=(0.0, 20.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
    )
    assert _cap_edge_count(svg) == 1


def test_sparkline_bar_isolated_clipped_point_no_segment_raises_a_cap_on_low_edge():
    # Mirror of the HIGH-edge case above: the isolated-point special case in
    # _out_of_bounds_spans branches on direction ("low" if y0 < low else
    # "high"), so a HIGH-only test cannot exercise this path.
    x = [0.0, 1.0, 2.0, 3.0, 4.0]
    y = [-300.0, float("nan"), 1.0, 1.0, 1.0]
    svg = sparkline_bar(
        x,
        y,
        [None] * 5,
        [None] * 5,
        x_domain=(0.0, 4.0),
        domain=(0.0, 20.0),
        ref=10.0,
        color="#000",
        fmt=Number(decimals=1),
    )
    assert _cap_edge_count(svg) == 1
    cap_ys = sorted(
        float(v)
        for v in re.findall(r'<line x1="[\d.-]+" y1="(-?[\d.]+)"[^>]*stroke-opacity="0.45"', svg)
    )
    assert cap_ys == [26.5, 27.5]  # bottom edge (inset=3, height=30 default)


def test_sparkline_bar_isolated_clipped_ribbon_bound_no_segment_raises_a_cap_on_low_edge():
    # Same isolated-point edge case as the ribbon test above, mirrored onto
    # the ribbon's lower bound.
    x = [0.0, 1.0, 2.0, 3.0, 4.0]
    y = [1.0] * 5
    lower = [-300.0, None, 0.5, 0.5, 0.5]
    upper = [1.5, None, 1.5, 1.5, 1.5]
    svg = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 4.0),
        domain=(0.0, 20.0),
        ref=10.0,
        color="#000",
        fmt=Number(decimals=1),
    )
    assert _cap_edge_count(svg) == 1
    cap_ys = sorted(
        float(v)
        for v in re.findall(r'<line x1="[\d.-]+" y1="(-?[\d.]+)"[^>]*stroke-opacity="0.45"', svg)
    )
    assert cap_ys == [26.5, 27.5]


def test_sparkline_bar_a_long_clipped_run_still_merges_into_one_span():
    # Five consecutive points sit far above the domain. A per-crossing
    # design would mark both the entry and exit of this run as separate
    # brackets; the real test is that a bracket count never scales with
    # how MANY points are clipped, only with how many separate contiguous
    # stretches (and directions) are -- a noisy series oscillating in and
    # out of a tight domain must not turn into a wall of markers.
    x = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    y = [1.0, 300.0, 310.0, 305.0, 295.0, 302.0, 1.0]
    svg = sparkline_bar(
        x,
        y,
        [None] * 7,
        [None] * 7,
        x_domain=(0.0, 6.0),
        domain=(0.0, 20.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
    )
    assert _cap_edge_count(svg) == 1


def test_sparkline_bar_flags_both_directions_when_the_series_clips_both():
    x = [0.0, 1.0, 2.0]
    y = [300.0, 1.0, -300.0]
    svg = sparkline_bar(
        x,
        y,
        [None, None, None],
        [None, None, None],
        x_domain=(0.0, 2.0),
        domain=(0.0, 20.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
    )
    assert _cap_edge_count(svg) == 2
    # The two brackets sit at the domain's two distinct edges (top and
    # bottom, inset=3 default height=30), not both piled on the same one.
    cap_ys = sorted(
        float(v)
        for v in re.findall(r'<line x1="[\d.-]+" y1="(-?[\d.]+)"[^>]*stroke-opacity="0.45"', svg)
    )
    assert cap_ys == [2.5, 3.5, 26.5, 27.5]


def test_sparkline_bar_ribbon_only_clip_raises_a_cap_even_when_the_point_stays_in_bounds():
    # The whole motivation for this redesign: a ribbon can be clamped to a
    # sliver of its true width while the point estimate itself stays
    # comfortably inside the domain. A point-only clip check would show no
    # indication of this at all.
    x = [0.0, 1.0, 2.0]
    y = [5.0, 5.0, 5.0]  # never leaves (0, 10)
    lower = [3.0, 3.0, 3.0]  # never leaves either
    upper = [7.0, 20.0, 7.0]  # the middle point's upper bound does
    svg = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 2.0),
        domain=(0.0, 10.0),
        ref=-999.0,
        color="#000",
        fmt=Number(decimals=1),
        width=200,
        height=30,
        inset=0,
        show_endpoint=False,
    )
    # The line itself never clips -- one plain polyline, no ghost line, no
    # wrapping.
    assert _real_polylines(svg) == ["0.00,15.00 100.00,15.00 200.00,15.00"]
    assert _ghost_polylines(svg) == []
    # The ribbon does clip -- a ghost ribbon and a cap both fire despite
    # the point-only view above showing nothing amiss.
    assert 'fill-opacity="0.06"' in svg
    assert _cap_edge_count(svg) == 1


def test_sparkline_bar_span_merging_coalesces_overlapping_line_and_ribbon_spans():
    # The line's own excursion (domain x in [5/7, 2+2/7]) and the ribbon's
    # upper-bound excursion (domain x in [1.375, 2.625]) overlap but have
    # different extents. Both clip the same "high" edge, so they must
    # merge into ONE bracket spanning their union, not draw as two
    # separate overlapping ones.
    x = [0.0, 1.0, 2.0, 3.0, 4.0]
    y = [5.0, 12.0, 12.0, 5.0, 5.0]
    lower = [3.0] * 5
    upper = [7.0, 7.0, 15.0, 7.0, 7.0]
    svg = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 4.0),
        domain=(0.0, 10.0),
        ref=-999.0,
        color="#000",
        fmt=Number(decimals=1),
        width=400,
        height=30,
        inset=0,
        show_endpoint=False,
    )
    assert _cap_edge_count(svg) == 1
    caps = re.findall(
        r'<line x1="([\d.-]+)" y1="[\d.-]+" x2="([\d.-]+)" y2="[\d.-]+" '
        r'stroke="[^"]+" stroke-width="0.5" stroke-opacity="0.45"/>',
        svg,
    )
    # Union start: the line's own earlier crossing at domain x=5/7, pixel
    # 500/7 = 71.43, padded -3px.
    assert float(caps[0][0]) == pytest.approx(500 / 7 - 3.0, abs=0.01)
    # Union end: the ribbon's later crossing at domain x=2.625, pixel
    # 262.5, padded +3px.
    assert float(caps[0][1]) == pytest.approx(262.5 + 3.0, abs=0.01)


def test_sparkline_bar_ribbon_clips_lower_and_upper_independently():
    # Only the middle point's upper bound is out of domain; lower never
    # leaves it. The clipped ribbon should pin just the upper edge and
    # keep the lower edge at its true, unclamped position throughout.
    x = [0.0, 1.0, 2.0]
    y = [1.0, 1.0, 1.0]
    lower = [0.5, 0.5, 0.5]
    upper = [1.5, 300.0, 1.5]
    svg = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 2.0),
        domain=(0.0, 20.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
    )
    assert _cap_edge_count(svg) == 1
    band = re.search(r'<polygon points="([^"]+)" fill="[^"]+" fill-opacity="0.15"/>', svg)
    assert band
    # The last three vertices are the reversed lower edge -- all three
    # must share one y, proving `lower` never moved even though `upper`
    # was clipped.
    lower_edge = band.group(1).split(" ")[-3:]
    assert len({point.split(",")[1] for point in lower_edge}) == 1


def test_sparkline_bar_series_entirely_outside_the_domain_still_renders():
    x = [0.0, 1.0, 2.0]
    y = [300.0, 310.0, 295.0]
    svg = sparkline_bar(
        x,
        y,
        [None, None, None],
        [None, None, None],
        x_domain=(0.0, 2.0),
        domain=(0.0, 20.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
    )
    # Nothing is ever truly in-bounds, so there is no "real" line to draw
    # -- only the ghost (the true trajectory) and a cap spanning the
    # whole run register the clip; this is not treated as a gap.
    assert _real_polylines(svg) == []
    assert len(_ghost_polylines(svg)) == 1
    assert _cap_edge_count(svg) == 1
    coords = re.findall(r'points="([^"]+)"', svg)
    xs = [float(pair.split(",")[0]) for pts in coords for pair in pts.split(" ")]
    assert all(0.0 <= x_px <= 220.0 for x_px in xs)


def test_sparkline_bar_ribbon_entirely_outside_the_domain_omits_the_real_polygon():
    # Sutherland-Hodgman clips in two stages (low, then high); a ribbon
    # entirely on ONE side empties out at whichever stage runs first for
    # that side, so both directions are exercised here.
    x = [0.0, 1.0, 2.0]
    y = [1.0, 1.0, 1.0]

    def clip_omits_real_polygon(lower, upper):
        svg = sparkline_bar(
            x,
            y,
            lower,
            upper,
            x_domain=(0.0, 2.0),
            domain=(0.0, 20.0),
            ref=0.0,
            color="#000",
            fmt=Number(decimals=1),
        )
        assert not re.search(r'<g clip-path="[^"]+"><polygon', svg)
        assert 'fill-opacity="0.06"' in svg
        assert _cap_edge_count(svg) == 1

    clip_omits_real_polygon([300.0, 310.0, 295.0], [305.0, 315.0, 300.0])  # entirely above
    clip_omits_real_polygon([-310.0, -315.0, -300.0], [-305.0, -300.0, -295.0])  # entirely below


def test_sparkline_bar_show_clip_indicators_false_suppresses_cap_only():
    # Turning the indicator off must never reintroduce the off-canvas
    # coordinate bug for the REAL layer, and must never hide the ghost
    # either -- clipping and the ghost trace stay mandatory regardless of
    # this flag; only the cap bracket is optional.
    x = [0.0, 1.0, 2.0]
    y = [1.0, 300.0, 1.0]
    svg = sparkline_bar(
        x,
        y,
        [None, None, None],
        [None, None, None],
        x_domain=(0.0, 2.0),
        domain=(0.0, 20.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
        show_clip_indicators=False,
    )
    assert _cap_edge_count(svg) == 0
    assert len(_ghost_polylines(svg)) == 1
    real = _real_polylines(svg)
    assert real  # the real (clipped) layer still renders
    real_ys = [float(pair.split(",")[1]) for piece in real for pair in piece.split(" ")]
    assert all(0.0 <= y_px <= 30.0 for y_px in real_ys)


def test_sparkline_bar_domain_override_produces_a_correctly_positioned_cap():
    # sparkline_bar is domain-provenance-agnostic -- it never knows whether
    # `domain` came from an explicit override, a max_domain= ceiling, or
    # autoscale="robust" (those compositions are covered at the CoefTable
    # level in test_sparkline.py, since sparkline_bar itself only ever
    # sees the final resolved tuple). Here: an explicit domain= must still
    # produce a cap sitting exactly at that domain's own projected high
    # edge -- inset px from the canvas top, since a value equal to `high`
    # always projects there regardless of the rest of the domain.
    x = [0.0, 1.0, 2.0]
    y = [1.0, 300.0, 1.0]
    svg = sparkline_bar(
        x,
        y,
        [None, None, None],
        [None, None, None],
        x_domain=(0.0, 2.0),
        domain=(0.0, 20.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
        height=30,
        inset=3,
    )
    cap_ys = sorted(
        float(v)
        for v in re.findall(r'<line x1="[\d.-]+" y1="(-?[\d.]+)"[^>]*stroke-opacity="0.45"', svg)
    )
    assert cap_ys == [2.5, 3.5]  # inset=3, offset +/- 0.5


def test_sparkline_axis_ticks_align_with_sparkline_bar_points():
    # The alignment invariant, direction two (see the comment in
    # test_sparkline_bar_endpoint_reserve_is_label_length_independent above):
    # for the same x_domain and show_endpoint setting, sparkline_axis's tick
    # x-coordinates must coincide with sparkline_bar's projected data
    # x-coordinates, or footer ticks drift out from under their points.
    x = [0.0, 1.0, 2.0]
    y = [1.0, 1.2, 0.9]
    lower = [0.8, 1.0, 0.7]
    upper = [1.2, 1.4, 1.1]

    bar_svg = sparkline_bar(
        x,
        y,
        lower,
        upper,
        x_domain=(0.0, 2.0),
        domain=(0.0, 2.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
    )
    line = re.search(r'<polyline points="([^"]+)"', bar_svg)
    assert line
    bar_xs = [float(pair.split(",")[0]) for pair in line.group(1).split(" ")]

    # Neither call overrides width/inset/show_endpoint/endpoint_width, so both
    # project over the identical reduced inner width.
    axis_svg = sparkline_axis(x_domain=(0.0, 2.0), fmt=Number(decimals=0), theme=DEFAULT)
    tick_xs = [
        float(v)
        for v in re.findall(r'<line x1="([-\d.]+)" y1="4.00" x2="[-\d.]+" y2="7.00"', axis_svg)
    ]

    # nice_ticks(0.0, 2.0) includes both domain endpoints, which are also
    # sparkline_bar's first and last data x-values here.
    assert bar_xs[0] in tick_xs
    assert bar_xs[-1] in tick_xs


def test_sparkline_axis_numeric_domain_matches_forest_axis_tick_positions():
    domain = (0.0, 10.0)
    forest_svg = forest_axis(domain=domain, ref=0.0, fmt=Number(decimals=0), theme=DEFAULT)
    # forest_axis has no endpoint reserve, so show_endpoint=False is needed
    # for sparkline_axis to project over the same full width.
    axis_svg = sparkline_axis(
        x_domain=domain, fmt=Number(decimals=0), theme=DEFAULT, show_endpoint=False
    )
    tick_re = re.compile(r'<line x1="([-\d.]+)" y1="4.00" x2="[-\d.]+" y2="7.00"')
    forest_ticks = tick_re.findall(forest_svg)
    assert forest_ticks
    assert forest_ticks == tick_re.findall(axis_svg)


def test_sparkline_axis_renders_calendar_labels_for_temporal_domain():
    low = datetime(2024, 1, 1, tzinfo=UTC).timestamp()
    high = datetime(2025, 3, 1, tzinfo=UTC).timestamp()
    svg = sparkline_axis(
        x_domain=(low, high),
        fmt=DateAxis(),
        theme=DEFAULT,
        temporal=True,
        target_ticks=14,
    )
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    # This domain spans 14 months, so it renders the two-tier axis: bare
    # month names on the sub-row, full years grouped on the row above.
    assert "2024" in svg
    assert "2025" in svg


def test_sparkline_axis_shows_the_year_once_for_a_single_calendar_year():
    low = datetime(2024, 1, 1, tzinfo=UTC).timestamp()
    high = datetime(2024, 8, 1, tzinfo=UTC).timestamp()
    svg = sparkline_axis(
        x_domain=(low, high),
        fmt=DateAxis(),
        theme=DEFAULT,
        temporal=True,
        target_ticks=14,
    )
    # Every tick falls in 2024 -- the sub-row never repeats it (bare month
    # names only), but the grouped row above still shows it once. The
    # two-tier layout always nests, even a single group, so there is no
    # reason to suppress a lone year the way an inline single-row token
    # would have needed to.
    labels = re.findall(r'text-anchor="[^"]+">([^<]*)</text>', svg)
    assert labels[:-1] == ["Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug"]
    assert labels[-1] == "2024"


def test_sparkline_axis_temporal_labels_adapt_to_a_coarser_step_than_fmt_default():
    # sparkline_axis's bare-rung selection can override the label
    # granularity entirely, not just whatever `step` the caller happened to
    # construct `fmt` with.
    low = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    high = datetime(2025, 1, 1, tzinfo=UTC).timestamp()
    svg = sparkline_axis(
        x_domain=(low, high),
        fmt=DateAxis(step="month"),
        theme=DEFAULT,
        temporal=True,
    )
    labels = re.findall(r'text-anchor="[^"]+">([^<]*)</text>', svg)
    assert labels
    # A 5-year span lands on year granularity -- not the caller's requested
    # month step, which would render bare "Jan" labels with no year at all.
    assert all(re.fullmatch(r"\d{4}", text) for text in labels)


def test_calendar_ticks_14_month_span_lands_on_month_boundaries():
    low = datetime(2024, 1, 1, tzinfo=UTC).timestamp()
    high = datetime(2025, 3, 1, tzinfo=UTC).timestamp()
    ticks = calendar_ticks(low, high, target=14)
    assert len(ticks) > 4
    assert all(datetime.fromtimestamp(t, tz=UTC).day == 1 for t in ticks)


def test_calendar_ticks_5_year_span_lands_on_year_boundaries():
    low = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    high = datetime(2025, 1, 1, tzinfo=UTC).timestamp()
    ticks = calendar_ticks(low, high)
    dates = [datetime.fromtimestamp(t, tz=UTC) for t in ticks]
    assert len(dates) > 1
    assert all(d.month == 1 and d.day == 1 for d in dates)


def test_calendar_ticks_sub_month_span_falls_back_to_day_step():
    low = datetime(2024, 1, 1, tzinfo=UTC).timestamp()
    high = datetime(2024, 1, 4, tzinfo=UTC).timestamp()
    ticks = calendar_ticks(low, high)
    assert ticks
    gaps = [b - a for a, b in pairwise(ticks)]
    assert all(gap == 86_400.0 for gap in gaps)


def test_calendar_ticks_sub_week_span_falls_back_to_week_step():
    low = datetime(2024, 1, 1, tzinfo=UTC).timestamp()
    high = datetime(2024, 1, 22, tzinfo=UTC).timestamp()
    ticks = calendar_ticks(low, high)
    assert len(ticks) > 1
    gaps = [b - a for a, b in pairwise(ticks)]
    assert all(gap == 7 * 86_400.0 for gap in gaps)


def test_calendar_ticks_year_span_lands_on_every_third_month_boundary():
    low = datetime(2024, 1, 1, tzinfo=UTC).timestamp()
    high = datetime(2025, 1, 1, tzinfo=UTC).timestamp()
    ticks = calendar_ticks(low, high, target=5)
    dates = [datetime.fromtimestamp(t, tz=UTC) for t in ticks]
    assert len(dates) >= 4
    assert any(d.month in (4, 7, 10) for d in dates)
    assert all(d.month in (1, 4, 7, 10) and d.day == 1 for d in dates)


def test_calendar_ticks_handles_degenerate_domain():
    low = datetime(2024, 6, 15, tzinfo=UTC).timestamp()
    assert calendar_ticks(low, low) == [low]
    assert calendar_ticks(low + 86_400.0, low) == []


def test_calendar_ticks_skips_a_boundary_before_the_domain_starts():
    # low falls in January (already on the year-tier alignment grid) but
    # not on the 1st, so the year boundary at 2020-01-01 itself precedes
    # low -- the first tick must be the next one, not that one.
    low = datetime(2020, 1, 15, tzinfo=UTC).timestamp()
    high = datetime(2025, 1, 15, tzinfo=UTC).timestamp()
    ticks = calendar_ticks(low, high)
    dates = [datetime.fromtimestamp(t, tz=UTC) for t in ticks]
    assert dates[0] == datetime(2021, 1, 1, tzinfo=UTC)
    assert all(d.month == 1 and d.day == 1 for d in dates)


def test_calendar_ticks_meets_the_density_floor_across_ladder_boundaries():
    # Average rung length vs. target picks week for the 6-10 day range and
    # month for the 29-31 day range, but those rungs can cross as few as
    # one real boundary over such a short span -- average length says
    # nothing about how many boundaries actually fall inside the domain.
    # Every span straddling a ladder boundary must still clear the floor.
    low = datetime(2024, 1, 1, tzinfo=UTC).timestamp()
    for days in (3, 6, 7, 10, 25, 28, 29, 31, 60, 90, 200, 400, 1000):
        high = low + days * 86_400.0
        ticks = calendar_ticks(low, high)
        assert len(ticks) >= _CALENDAR_TICK_FLOOR, f"{days}d span: only {len(ticks)} ticks"
        dates = [datetime.fromtimestamp(t, tz=UTC) for t in ticks]
        assert all(d.hour == 0 and d.minute == 0 and d.second == 0 for d in dates), (
            f"{days}d span: a tick landed off a real calendar-day boundary"
        )


def test_calendar_ticks_recovers_density_for_a_6_to_7_day_span():
    # Originally reported: a week-long window picked the week rung, which
    # crosses at most one boundary in 6-7 days and rendered a single tick.
    # The exact rung the wider ladder lands on is not the point -- only that
    # an ordinary short span still clears the density floor on real,
    # uniformly spaced day boundaries.
    low = datetime(2024, 1, 1, tzinfo=UTC).timestamp()
    for days in (6, 7):
        high = low + days * 86_400.0
        ticks = calendar_ticks(low, high)
        assert len(ticks) >= _CALENDAR_TICK_FLOOR
        gaps = {b - a for a, b in pairwise(ticks)}
        assert len(gaps) == 1
        assert gaps.pop() % 86_400.0 == 0


def test_calendar_ticks_recovers_density_for_a_29_day_span():
    # Originally reported: 2024-01-01 to 2024-01-30 picked the month rung
    # by average length (raw 7.25d vs. a 30.4375d month) and rendered a
    # single tick, even though the week rung was available and fits four.
    low = datetime(2024, 1, 1, tzinfo=UTC).timestamp()
    high = datetime(2024, 1, 30, tzinfo=UTC).timestamp()
    ticks = calendar_ticks(low, high)
    assert len(ticks) >= _CALENDAR_TICK_FLOOR
    gaps = [b - a for a, b in pairwise(ticks)]
    assert all(gap == 7 * 86_400.0 for gap in gaps)


def test_sparkline_axis_temporal_domain_honours_a_custom_callable_fmt():
    # A non-DateAxis callable is used exactly as given for temporal ticks
    # too -- sparkline_axis only overrides the granularity of a DateAxis.
    low = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    high = datetime(2025, 1, 1, tzinfo=UTC).timestamp()
    svg = sparkline_axis(x_domain=(low, high), fmt=lambda _: "X", theme=DEFAULT, temporal=True)
    labels = re.findall(r"<text[^>]*>([^<]+)</text>", svg)
    assert labels
    assert all(label == "X" for label in labels)


def test_calendar_ticks_new_ladder_rungs_cover_the_5_to_14_day_band():
    # 2d/3d/14d rungs exist specifically to close the gap between week (too
    # sparse under 15 days) and day (too dense over 6 days) -- confirm the
    # ladder actually lands on one of them, not just carries it unused.
    low = datetime(2024, 1, 17, tzinfo=UTC).timestamp()
    seen_steps = set()
    for days in range(5, 15):
        high = low + days * 86_400.0
        ticks = calendar_ticks(low, high)
        gaps = {b - a for a, b in pairwise(ticks)}
        assert len(gaps) == 1
        seen_steps.add(gaps.pop())
    assert seen_steps & {2 * 86_400.0, 3 * 86_400.0}


def test_calendar_ticks_weekly_grid_aligns_to_monday():
    # Epoch-aligned weekly ticks land on Thursdays -- an artifact of
    # 1970-01-01, not a choice. The grid is phase-shifted to the ISO week
    # start instead.
    low = datetime(2024, 1, 1, tzinfo=UTC).timestamp()
    high = datetime(2024, 3, 1, tzinfo=UTC).timestamp()
    ticks = calendar_ticks(low, high, target=8)  # forces the week rung
    dates = [datetime.fromtimestamp(t, tz=UTC) for t in ticks]
    assert dates
    assert all(d.weekday() == 0 for d in dates)  # Monday == 0


def test_super_row_recascades_the_surviving_group_label_after_a_drop():
    # A domain whose finest admissible month-group arrangement must drop an
    # edge group's label to clear a collision -- here the one that would
    # anchor the year. `multi_year` is pinned from the full, undropped
    # group set specifically so that dropping it does not silently erase
    # the fact that the domain spans two years: some surviving label must
    # still carry each year that appears anywhere in the underlying data.
    low = datetime(2024, 10, 15, tzinfo=UTC).timestamp()
    high = datetime(2025, 2, 15, tzinfo=UTC).timestamp()
    width = 160
    project = _projector((low, high), width, 3)
    result = _super_row("day", low, high, project=project, width=width)
    assert result is not None
    _centers, admitted = result
    assert "" in admitted  # this domain's collision does drop one group's label
    shown = [text for text in admitted if text]
    assert any("'24" in text for text in shown)
    assert any("'25" in text for text in shown)


def test_sparkline_axis_numeric_labels_never_collide():
    # The same collision property, but for the plain numeric axis a
    # non-temporal x column renders through (nice_ticks + a Number format --
    # e.g. "days since start" as a bare float, not a calendar date).
    fmt = Number(decimals=0)
    for high in (1.0, 5.0, 14.0, 30.0, 90.0, 365.0, 1000.0, 5000.0, 123_456.0):
        for width in (220, 160):
            project = _projector((0.0, high), width, 3)
            ticks = nice_ticks(0.0, high, 4)
            texts = [fmt(t) for t in ticks]
            boxes = _label_boxes(ticks, texts, project, width)
            assert _fits(boxes), f"numeric collision: high={high} width={width} labels={texts}"


def test_bare_label_shows_only_its_own_component():
    value = datetime(2026, 4, 15, tzinfo=UTC)
    assert _bare_label(value, "day") == "15"
    assert _bare_label(value, "month") == "Apr"
    assert _bare_label(value, "year") == "2026"


def test_calendar_groups_covers_every_month_the_domain_touches():
    low = datetime(2024, 1, 17, tzinfo=UTC).timestamp()
    high = datetime(2024, 3, 17, tzinfo=UTC).timestamp()
    groups = _calendar_groups(low, high, 1)
    assert [start.month for start, _ in groups] == [1, 2, 3]
    assert all(start.day == 1 for start, _ in groups)


def test_calendar_groups_covers_every_year_the_domain_touches():
    low = datetime(2024, 6, 1, tzinfo=UTC).timestamp()
    high = datetime(2026, 6, 1, tzinfo=UTC).timestamp()
    groups = _calendar_groups(low, high, 12)
    assert [start.year for start, _ in groups] == [2024, 2025, 2026]
    assert all(start.month == 1 and start.day == 1 for start, _ in groups)


def test_super_row_renders_a_single_group_centred_over_the_whole_span():
    # A day sub-row confined to one month, and a month sub-row confined to
    # one year, both still get one group label -- the two-tier layout
    # always nests, even when there is only one group to show.
    low = datetime(2024, 1, 17, tzinfo=UTC).timestamp()
    high = datetime(2024, 1, 30, tzinfo=UTC).timestamp()
    project = _projector((low, high), 220, 3)
    result = _super_row("day", low, high, project=project, width=220)
    assert result is not None
    _centers, texts = result
    assert texts == ["Jan"]

    low = datetime(2024, 1, 17, tzinfo=UTC).timestamp()
    high = datetime(2024, 7, 17, tzinfo=UTC).timestamp()
    project = _projector((low, high), 220, 3)
    result = _super_row("month", low, high, project=project, width=220)
    assert result is not None
    _centers, texts = result
    assert texts == ["2024"]


def test_super_row_none_for_year_sub_step():
    # Nothing is coarser than a year to group a yearly sub-row by.
    low = datetime(2024, 1, 1, tzinfo=UTC).timestamp()
    high = datetime(2030, 1, 1, tzinfo=UTC).timestamp()
    project = _projector((low, high), 220, 3)
    assert _super_row("year", low, high, project=project, width=220) is None


def test_super_row_groups_months_without_a_year_token_within_one_year():
    low = datetime(2024, 1, 17, tzinfo=UTC).timestamp()
    high = datetime(2024, 3, 17, tzinfo=UTC).timestamp()
    project = _projector((low, high), 220, 3)
    result = _super_row("day", low, high, project=project, width=220)
    assert result is not None
    _centers, texts = result
    assert [t for t in texts if t] == ["Jan", "Feb", "Mar"]


def test_super_row_groups_years_always_full_four_digits():
    low = datetime(2024, 1, 17, tzinfo=UTC).timestamp()
    high = datetime(2026, 1, 17, tzinfo=UTC).timestamp()
    project = _projector((low, high), 220, 3)
    result = _super_row("month", low, high, project=project, width=220)
    assert result is not None
    _centers, texts = result
    assert [t for t in texts if t] == ["2024", "2025", "2026"]


def test_super_row_group_centres_on_its_true_clipped_span():
    # January only starts on the 17th in this domain -- the group's centre
    # must reflect the visible sliver, not the full calendar month.
    low = datetime(2024, 1, 17, tzinfo=UTC).timestamp()
    high = datetime(2024, 3, 17, tzinfo=UTC).timestamp()
    project = _projector((low, high), 220, 3)
    result = _super_row("day", low, high, project=project, width=220)
    assert result is not None
    centers, _texts = result
    # The clipped January sliver (17th-31st, 14 days) is far narrower than
    # February or March (full calendar months) -- its centre sits closer to
    # the domain's left edge than an even three-way split would put it.
    even_third = 3 + (220 - 6) / 3 / 2
    assert centers[0] < even_third


def test_select_bare_rung_labels_have_no_cascaded_context():
    low = datetime(2024, 1, 17, tzinfo=UTC).timestamp()
    high = datetime(2024, 1, 30, tzinfo=UTC).timestamp()
    project = _projector((low, high), 220, 3)
    result = _select_bare_rung(low, high, 4, project=project, width=220)
    assert result is not None
    rung, _ticks, texts = result
    assert rung.label == "day"
    # Bare day numbers only -- no month name anywhere, unlike the cascaded
    # single-row design's first label.
    assert all(t == "" or t.isdigit() for t in texts)


def test_sparkline_axis_renders_two_tier_for_a_multi_month_domain():
    low = datetime(2024, 1, 17, tzinfo=UTC).timestamp()
    high = datetime(2024, 3, 17, tzinfo=UTC).timestamp()
    svg = sparkline_axis(
        x_domain=(low, high), fmt=DateAxis(), theme=DEFAULT, temporal=True, show_endpoint=False
    )
    # Two rows cost a fixed height addition over the single-row default.
    assert f'height="{22 + int(_SUPER_ROW_OFFSET)}"' in svg
    texts = re.findall(r"<text[^>]*>([^<]+)</text>", svg)
    # Bare sub-tick day numbers, with "Jan"/"Feb"/"Mar" living only in the
    # grouped row -- no sub-tick label carries a month name.
    assert any(t.isdigit() for t in texts)
    assert {"Jan", "Feb", "Mar"} <= set(texts)


def test_sparkline_axis_nests_even_a_single_group():
    # A domain confined to a single month still gets the two-tier layout --
    # one group label ("Jan"), centred over the whole width, rather than
    # folding it into the first tick inline.
    low = datetime(2024, 1, 17, tzinfo=UTC).timestamp()
    high = datetime(2024, 1, 30, tzinfo=UTC).timestamp()
    svg = sparkline_axis(
        x_domain=(low, high), fmt=DateAxis(), theme=DEFAULT, temporal=True, show_endpoint=False
    )
    assert f'height="{22 + int(_SUPER_ROW_OFFSET)}"' in svg
    labels = re.findall(r'text-anchor="[^"]+">([^<]*)</text>', svg)
    assert labels
    assert labels[-1] == "Jan"
    # The sub-row is bare -- no label repeats the month inline.
    assert all(text.isdigit() for text in labels[:-1])


def test_sparkline_axis_two_tier_rows_never_collide():
    # The same collision property as the single-row design, but exercised
    # end-to-end through sparkline_axis for domains that actually trigger
    # the two-tier layout, checking each row independently (they are
    # vertically separated, so only within-row collisions matter).
    def row_boxes(items: list[tuple[float, str, str]]) -> list[tuple[float, float]]:
        boxes = []
        for x, anchor, text in items:
            w = len(text) * 9.0 * _CHAR_WIDTH_RATIO
            left = x if anchor == "start" else (x - w if anchor == "end" else x - w / 2)
            boxes.append((left, left + w))
        return boxes

    starts = [
        datetime(2024, 1, 17, tzinfo=UTC),
        datetime(2024, 12, 20, tzinfo=UTC),
        datetime(2023, 2, 28, tzinfo=UTC),
    ]
    spans_days = (*range(1, 15), 31, 60, 91, 182, 366, 425, 731, 851, 1155)
    layouts = ((220, True), (220, False), (160, True))
    for start in starts:
        for days in spans_days:
            low = start.timestamp()
            high = (start + timedelta(days=days)).timestamp()
            for width, show_endpoint in layouts:
                svg = sparkline_axis(
                    x_domain=(low, high),
                    fmt=DateAxis(),
                    theme=DEFAULT,
                    temporal=True,
                    width=width,
                    show_endpoint=show_endpoint,
                )
                items = re.findall(
                    r'<text x="([-\d.]+)" y="([-\d.]+)"[^>]*text-anchor="([^"]+)">([^<]*)</text>',
                    svg,
                )
                by_row: dict[str, list[tuple[float, str, str]]] = {}
                for x, y, anchor, text in items:
                    by_row.setdefault(y, []).append((float(x), anchor, text))
                for y, row in by_row.items():
                    assert _fits(row_boxes(row)), (
                        f"collision: start={start.date()} days={days} width={width} "
                        f"show_endpoint={show_endpoint} row_y={y} labels={row}"
                    )
