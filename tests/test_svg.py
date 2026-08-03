import re
from itertools import pairwise

from coeftable.format import Number
from coeftable.svg import forest_axis, forest_bar, nice_ticks, sparkline_bar
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
        theme=DEFAULT,
        fmt=Number(decimals=1),
    )
    assert svg.startswith("<svg")
    assert svg.endswith("</svg>")
    assert "<polyline" in svg
    assert "<polygon" in svg
    assert "<circle" in svg
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
        theme=DEFAULT,
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
        theme=DEFAULT,
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
        theme=DEFAULT,
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
        theme=DEFAULT,
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
        theme=DEFAULT,
        fmt=Number(decimals=1),
        show_endpoint=False,
    )
    assert "<text" not in svg
    assert "<circle" in svg


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
        theme=DEFAULT,
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
        theme=DEFAULT,
        fmt=lambda _: "-12,345.6789%",
        endpoint_width=20,
    )
    label = re.search(r"<text[^>]*>([^<]+)</text>", svg)
    assert label
    assert label.group(1).endswith("\u2026")
    assert label.group(1) != "-12,345.6789%"


def test_sparkline_bar_endpoint_dot_lands_on_last_valid_point_after_trailing_gap():
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
        theme=DEFAULT,
        fmt=Number(decimals=1),
    )
    dot = re.search(r'<circle cx="([^"]+)" cy="([^"]+)"', svg)
    assert dot
    line = re.search(r'<polyline points="([^"]+)"', svg)
    assert line
    last_point = line.group(1).split(" ")[-1]
    assert f"{dot.group(1)},{dot.group(2)}" == last_point


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
        theme=DEFAULT,
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
    # with these same projected x-coordinates -- is deferred to Task 4, since
    # `sparkline_axis` does not exist yet.
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
        theme=DEFAULT,
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
        theme=DEFAULT,
        fmt=lambda _: "-12,345%",
    )

    assert endpoints(short) == endpoints(long)
