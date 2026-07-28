import re

from coeftable.format import Number
from coeftable.svg import forest_axis, forest_bar, nice_ticks
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
