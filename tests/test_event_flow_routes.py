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


def test_c_loop_bound_override_clears_a_wider_sibling_in_the_column():
    upward = route_c_loop(DST, (210, 0, 100, 60), offset=24, side="left", bound=150)
    assert upward.path == "M210,130 C126,130 126,30 210,30"
    assert upward.label_anchor == (126.0, 80.0)
    assert upward.bounds == (126.0, 30.0, 210.0, 130.0)

    downward = route_c_loop((210, 0, 100, 60), DST, offset=24, side="right", bound=400)
    assert downward.path == "M310,30 C424,30 424,130 310,130"
    assert downward.label_anchor == (424.0, 80.0)
    assert downward.bounds == (310.0, 30.0, 424.0, 130.0)


def test_skip_bow_bound_override_clears_a_taller_intervening_card():
    route = route_skip_bow(SRC, DST, offset=24, bound=0)
    assert route.path == "M110,50 C134,50 134,-24 160,-24 S186,130 210,130"
    assert route.label_anchor == (160.0, -24.0)
    assert route.bounds == (110.0, -24.0, 210.0, 130.0)


def test_back_sag_bound_override_clears_a_taller_intervening_card():
    route = route_back_sag(DST, SRC, offset=24, bound=200)
    assert route.path == "M210,130 C186,130 186,224 160,224 S134,50 110,50"
    assert route.label_anchor == (160.0, 224.0)
    assert route.bounds == (110.0, 50.0, 210.0, 224.0)
