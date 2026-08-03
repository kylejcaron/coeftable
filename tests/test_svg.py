import re
from datetime import UTC, datetime
from itertools import pairwise

from coeftable.format import DateAxis, Number
from coeftable.svg import (
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
    # x=pad and, centred, loses its leading character off-canvas ("Jan" ->
    # "an"). Covers the sparkline_axis call site and its temporal branch.
    low = datetime(2024, 1, 1, tzinfo=UTC).timestamp()
    high = datetime(2024, 3, 1, tzinfo=UTC).timestamp()
    svg = sparkline_axis(x_domain=(low, high), fmt=DateAxis(), theme=DEFAULT, temporal=True)
    labels = re.findall(r'text-anchor="([^"]+)">([^<]*)</text>', svg)
    assert labels
    assert labels[0] == ("start", "Jan")


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


def test_sparkline_bar_flags_clipping_above_the_domain():
    # The original bug: y=300 against domain (0, 20) on a 30px canvas emitted
    # a literal y="-333.00", relying on the SVG viewBox to hide it.
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
    flags = re.findall(r'<polygon points="[^"]+" fill="[^"]+"/>', svg)
    assert len(flags) == 1
    assert 'y="-333.00"' not in svg
    coords = re.findall(r'points="([^"]+)"', svg)
    ys = [float(pair.split(",")[1]) for pts in coords for pair in pts.split(" ")]
    assert all(0.0 <= y_px <= 30.0 for y_px in ys)


def test_sparkline_bar_flags_clipping_below_the_domain():
    x = [0.0, 1.0, 2.0]
    y = [1.0, -300.0, 1.0]
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
    flags = re.findall(r'<polygon points="([^"]+)" fill="[^"]+"/>', svg)
    assert len(flags) == 1
    line = re.search(r'<polyline points="([^"]+)"', svg)
    assert line
    clamped_y = float(line.group(1).split(" ")[1].split(",")[1])
    flag_ys = [float(v.split(",")[1]) for v in flags[0].split(" ")]
    assert max(flag_ys) > clamped_y  # the low flag's tip sits below (larger pixel y) than the line


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


def test_sparkline_bar_distinguishes_a_clipped_point_from_a_genuine_gap():
    # index 1 is a genuine gap (NaN); index 3 has data, just off-scale. A gap
    # splits the polyline into a new run; a clip does not -- it only raises
    # the row-level flag -- so the two must be tellable apart from output.
    x = [0.0, 1.0, 2.0, 3.0, 4.0]
    y = [1.0, float("nan"), 1.0, 300.0, 1.0]
    svg = sparkline_bar(
        x,
        y,
        [None, None, None, None, None],
        [None, None, None, None, None],
        x_domain=(0.0, 4.0),
        domain=(0.0, 20.0),
        ref=0.0,
        color="#000",
        fmt=Number(decimals=1),
    )
    assert svg.count("<polyline") == 2  # the gap, and only the gap, splits the line
    flags = re.findall(r'<polygon points="[^"]+" fill="[^"]+"/>', svg)
    assert len(flags) == 1  # the clip, and only the clip, raises a flag


def test_sparkline_bar_a_long_clipped_run_still_raises_only_one_flag():
    # Five consecutive points sit far above the domain. The rejected
    # per-crossing design would have marked both the entry and exit of this
    # run (two marks); the real test is that flag count never scales with
    # how MANY points are clipped, only with which DIRECTIONS are -- a
    # noisy series oscillating in and out of a tight domain must not turn
    # into a wall of markers.
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
    flags = re.findall(r'<polygon points="[^"]+" fill="[^"]+"/>', svg)
    assert len(flags) == 1


def test_sparkline_bar_flag_survives_when_an_earlier_line_run_was_clipped():
    # The clip in the FIRST run must still be flagged even though the LAST
    # run scanned (after the gap) is entirely clean -- flags accumulate
    # with OR across every run, not just the last one visited.
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
    flags = re.findall(r'<polygon points="[^"]+" fill="[^"]+"/>', svg)
    assert len(flags) == 1


def test_sparkline_bar_flag_survives_when_an_earlier_band_run_was_clipped():
    x = [0.0, 1.0, 2.0, 3.0, 4.0]
    y = [1.0, 1.0, 1.0, 1.0, 1.0]
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
    flags = re.findall(r'<polygon points="[^"]+" fill="[^"]+"/>', svg)
    assert len(flags) == 1


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
    assert "<polyline" in svg  # still drawn, pinned to the edge -- not treated as a gap
    flags = re.findall(r'<polygon points="[^"]+" fill="[^"]+"/>', svg)
    assert len(flags) == 1  # one direction clipped, one flag -- even though nothing is in-domain
    coords = re.findall(r'points="([^"]+)"', svg)
    xs = [float(pair.split(",")[0]) for pts in coords for pair in pts.split(" ")]
    ys = [float(pair.split(",")[1]) for pts in coords for pair in pts.split(" ")]
    assert all(0.0 <= x_px <= 220.0 for x_px in xs)
    assert all(0.0 <= y_px <= 30.0 for y_px in ys)


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
    flags = re.findall(r'<polygon points="[^"]+" fill="[^"]+"/>', svg)
    assert len(flags) == 2


def test_sparkline_bar_ribbon_clips_lower_and_upper_independently():
    # Only the middle point's upper bound is out of domain; lower never
    # leaves it. The ribbon should pin just the upper edge and keep the
    # lower edge at its true, unclamped position throughout.
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
    assert svg.count("<polygon") == 2  # one ribbon fill plus one clip flag
    flags = re.findall(r'<polygon points="[^"]+" fill="[^"]+"/>', svg)
    assert len(flags) == 1
    band = re.search(r'<polygon points="([^"]+)" fill="[^"]+" fill-opacity="0.15"/>', svg)
    assert band
    # last three vertices are the reversed lower edge -- all three must share
    # one y, proving `lower` never moved even though `upper` was clipped
    lower_edge = band.group(1).split(" ")[3:]
    assert len({point.split(",")[1] for point in lower_edge}) == 1


def test_sparkline_bar_show_clip_indicators_false_suppresses_flags_only():
    # Turning the indicator off must never reintroduce the off-canvas
    # coordinate bug -- clamping stays mandatory regardless of this flag.
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
    assert re.findall(r'<polygon points="[^"]+" fill="[^"]+"/>', svg) == []
    coords = re.findall(r'points="([^"]+)"', svg)
    ys = [float(pair.split(",")[1]) for pts in coords for pair in pts.split(" ")]
    assert all(0.0 <= y_px <= 30.0 for y_px in ys)


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

    # Neither call overrides width/pad/show_endpoint/endpoint_width, so both
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
    assert "Jan" in svg
    assert "Feb" in svg


def test_sparkline_axis_temporal_labels_adapt_to_a_coarser_step_than_fmt_default():
    # sparkline_axis must override the label granularity to match whichever
    # ladder rung calendar_ticks actually picked, not whatever `step` the
    # caller happened to construct `fmt` with.
    low = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    high = datetime(2025, 1, 1, tzinfo=UTC).timestamp()
    svg = sparkline_axis(
        x_domain=(low, high),
        fmt=DateAxis(step="month"),
        theme=DEFAULT,
        temporal=True,
    )
    assert "2020" in svg
    assert "Jan" not in svg


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


def test_calendar_ticks_year_span_lands_on_quarter_boundaries():
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


def test_sparkline_axis_temporal_domain_honours_a_custom_callable_fmt():
    # A non-DateAxis callable is used exactly as given for temporal ticks
    # too -- sparkline_axis only overrides the granularity of a DateAxis.
    low = datetime(2020, 1, 1, tzinfo=UTC).timestamp()
    high = datetime(2025, 1, 1, tzinfo=UTC).timestamp()
    svg = sparkline_axis(x_domain=(low, high), fmt=lambda _: "X", theme=DEFAULT, temporal=True)
    labels = re.findall(r"<text[^>]*>([^<]+)</text>", svg)
    assert labels
    assert all(label == "X" for label in labels)
