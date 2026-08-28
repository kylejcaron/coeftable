from coeftable.graph._routes import (
    route_across,
    route_back_sag,
    route_c_loop,
    route_down,
    route_skip_bow,
)

SRC = (10, 20, 100, 60)
DST = (210, 100, 100, 60)


def test_across_uses_right_and_left_midpoints():
    route = route_across(SRC, DST)
    assert route.path == "M110,50 C160,50 160,130 210,130"
    assert route.label_anchor == (160.0, 90.0)
    assert route.bounds == (110.0, 50.0, 210.0, 130.0)


def test_across_gates_reach_each_stage_edge_before_the_cubic():
    """With both edges, flat runs carry the cubic out of each stage's own
    column before it curves, so a wider sibling on another lane never
    falls under the curve's own vertical drift.
    """
    route = route_across(SRC, DST, src_edge=150, dst_edge=180)
    assert route.path == "M110,50 L150,50 C165,50 165,130 180,130 L210,130"
    assert route.label_anchor == (165.0, 90.0)
    assert route.bounds == (110.0, 50.0, 210.0, 130.0)


def test_across_missing_either_edge_keeps_the_pure_continuous_cubic():
    """Each edge acts independently: supplying one still anchors the cubic
    there while the other end stays at its own box's own anchor.
    """
    only_src = route_across(SRC, DST, src_edge=150)
    assert only_src.path == "M110,50 L150,50 C180,50 180,130 210,130"
    only_dst = route_across(SRC, DST, dst_edge=180)
    assert only_dst.path == "M110,50 C145,50 145,130 180,130 L210,130"
    pure = route_across(SRC, DST)
    assert pure.path == "M110,50 C160,50 160,130 210,130"


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
    """A ``bound`` also gates the route: flat runs reach the stage's own
    outer edge before the turning cubic, whose own hull then sits
    entirely outside it (never re-entering the stage's own column).
    """
    upward = route_c_loop(DST, (210, 0, 100, 60), offset=24, side="left", bound=150)
    assert upward.path == "M210,130 L150,130 C126,130 126,30 150,30 L210,30"
    assert upward.label_anchor == (126.0, 80.0)
    assert upward.bounds == (126.0, 30.0, 210.0, 130.0)

    downward = route_c_loop((210, 0, 100, 60), DST, offset=24, side="right", bound=400)
    assert downward.path == "M310,30 L400,30 C424,30 424,130 400,130 L310,130"
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


def test_skip_bow_gates_bow_within_each_endpoint_gap_then_cross_flat():
    """With gates, the bow only curves inside each endpoint's own gap.

    Everything between the two gates is a flat straight line at the
    corridor height, so an intervening stage anywhere between the gates
    is cleared by construction, not by a continuous curve that only
    touches the corridor height at one instant.
    """
    route = route_skip_bow(SRC, DST, offset=10, bound=0, src_gate=130, dst_gate=170)
    assert route.path == "M110,50 C120,50 120,-10 130,-10 L170,-10 C200,-10 200,130 210,130"
    assert route.label_anchor == (150.0, -10.0)
    assert route.bounds == (110.0, -10.0, 210.0, 130.0)


def test_skip_bow_gates_clamp_a_packed_offset_to_the_gap_boundary():
    """A packed offset wide enough to overshoot a gate is clamped to it.

    Without this clamp, a large packed offset would push a control point
    (and thus the curve) straight through the neighboring stage's cards.
    """
    route = route_skip_bow(SRC, DST, offset=100, bound=0, src_gate=130, dst_gate=170)
    assert route.path == "M110,50 C130,50 130,-100 130,-100 L170,-100 C170,-100 170,130 210,130"
    assert route.label_anchor == (150.0, -100.0)
    assert route.bounds == (110.0, -100.0, 210.0, 130.0)


def test_back_sag_gates_bow_within_each_endpoint_gap_then_cross_flat():
    route = route_back_sag(DST, SRC, offset=24, bound=200, src_gate=170, dst_gate=70)
    assert route.path == "M210,130 C186,130 186,224 170,224 L70,224 C86,224 86,50 110,50"
    assert route.label_anchor == (120.0, 224.0)
    assert route.bounds == (70.0, 50.0, 210.0, 224.0)


def test_back_sag_gates_clamp_a_packed_offset_to_the_gap_boundary():
    route = route_back_sag(DST, SRC, offset=200, bound=200, src_gate=170, dst_gate=70)
    assert route.path == "M210,130 C170,130 170,400 170,400 L70,400 C70,400 70,50 110,50"
    assert route.label_anchor == (120.0, 400.0)
    assert route.bounds == (70.0, 50.0, 210.0, 400.0)


def test_skip_bow_edges_reach_the_stage_boundary_before_the_gated_bow():
    """``src_edge``/``dst_edge`` add a flat run from each card's own anchor
    out to its stage's own outer edge before the already-gated bow into
    its gate begins, clearing a wider sibling sharing that stage on
    another lane.
    """
    route = route_skip_bow(
        SRC, DST, offset=10, bound=0, src_gate=130, dst_gate=170, src_edge=115, dst_edge=195
    )
    assert route.path == (
        "M110,50 L115,50 C125,50 125,-10 130,-10 L170,-10 C185,-10 185,130 195,130 L210,130"
    )
    assert route.label_anchor == (150.0, -10.0)
    assert route.bounds == (110.0, -10.0, 210.0, 130.0)


def test_skip_bow_edges_have_no_effect_without_both_gates():
    """Edges only matter once the route is already gated by both gates."""
    with_edges = route_skip_bow(SRC, DST, offset=24, src_edge=115, dst_edge=195)
    pure = route_skip_bow(SRC, DST, offset=24)
    assert with_edges.path == pure.path


def test_back_sag_edges_reach_the_stage_boundary_before_the_gated_sag():
    route = route_back_sag(
        DST, SRC, offset=24, bound=200, src_gate=170, dst_gate=70, src_edge=205, dst_edge=105
    )
    assert route.path == (
        "M210,130 L205,130 C181,130 181,224 170,224 L70,224 C81,224 81,50 105,50 L110,50"
    )
    assert route.label_anchor == (120.0, 224.0)
    assert route.bounds == (70.0, 50.0, 210.0, 224.0)


def test_back_sag_edges_have_no_effect_without_both_gates():
    with_edges = route_back_sag(DST, SRC, offset=24, src_edge=205, dst_edge=105)
    pure = route_back_sag(DST, SRC, offset=24)
    assert with_edges.path == pure.path


def test_skip_bow_missing_either_gate_keeps_the_pure_continuous_bow():
    """Supplying only one gate falls back to the original two-cubic bow."""
    only_src = route_skip_bow(SRC, DST, offset=24, src_gate=130)
    only_dst = route_skip_bow(SRC, DST, offset=24, dst_gate=170)
    pure = route_skip_bow(SRC, DST, offset=24)
    assert only_src.path == pure.path
    assert only_dst.path == pure.path


def test_down_uses_bottom_and_top_midpoints_when_lane_widths_match():
    upper = (10, 20, 100, 60)
    lower = (10, 200, 100, 60)
    route = route_down(upper, lower)
    assert route.path == "M60,80 C60,140 60,140 60,200"
    assert route.label_anchor == (60.0, 140.0)
    assert route.bounds == (60.0, 80.0, 60.0, 200.0)


def test_down_centers_the_control_hull_between_unequal_lane_widths():
    """Every card keeps its own width rather than its stage's shared max, so
    a same-stage source and destination can have different centers; the
    cubic's controls still sit directly beneath each anchor, not on some
    shared column x."""
    narrow = (40, 20, 100, 60)
    wide = (40, 200, 140, 60)
    route = route_down(narrow, wide)
    assert route.path == "M90,80 C90,140 110,140 110,200"
    assert route.label_anchor == (100.0, 140.0)
    assert route.bounds == (90.0, 80.0, 110.0, 200.0)
