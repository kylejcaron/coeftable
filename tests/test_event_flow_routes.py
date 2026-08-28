from coeftable.graph._routes import (
    route_across,
    route_back_sag,
    route_c_loop,
    route_skip_bow,
)

SRC = (10, 20, 100, 60)
DST = (210, 100, 100, 60)


def test_across_uses_right_and_left_midpoints():
    route = route_across(SRC, DST)
    assert route.path == "M110,50 C160,50 160,130 210,130"
    assert route.label_anchor == (160.0, 90.0)
    assert route.bounds == (110.0, 50.0, 210.0, 130.0)


def test_skip_bow_reserves_an_upper_corridor():
    route = route_skip_bow(SRC, DST, offset=24)
    assert route.path == "M110,50 C134,50 134,-4 160,-4 S186,130 210,130"
    assert route.label_anchor == (160.0, -4.0)
    assert route.bounds == (110.0, -4.0, 210.0, 130.0)


def test_back_sag_reserves_a_lower_corridor():
    route = route_back_sag(DST, SRC, offset=24)
    assert route.path == "M210,130 C186,130 186,184 160,184 S134,50 110,50"
    assert route.label_anchor == (160.0, 184.0)
    assert route.bounds == (110.0, 50.0, 210.0, 184.0)


def test_c_loop_uses_the_requested_exterior_side():
    upward = route_c_loop(DST, (210, 0, 100, 60), offset=24, side="left")
    assert upward.path == "M210,130 C186,130 186,30 210,30"
    assert upward.label_anchor == (186.0, 80.0)
    assert upward.bounds == (186.0, 30.0, 210.0, 130.0)

    downward = route_c_loop((210, 0, 100, 60), DST, offset=24, side="right")
    assert downward.path == "M310,30 C334,30 334,130 310,130"
    assert downward.label_anchor == (334.0, 80.0)
    assert downward.bounds == (310.0, 30.0, 334.0, 130.0)
