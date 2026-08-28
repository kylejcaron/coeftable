"""Contract tests for the staged graph layout's exact box placement."""

import re
from typing import cast

import pytest

from coeftable.cards import Card, CardChrome, TextBlock
from coeftable.errors import SpecError
from coeftable.graph import (
    Atom,
    ControlRef,
    EdgeKind,
    EdgeStyle,
    EventFlow,
    FlowEdge,
    Graph,
    Slot,
    Slotted,
    Staged,
    StageSlot,
    StateRule,
    Wire,
)
from coeftable.graph._routes import route_across, route_back_sag, route_skip_bow
from coeftable.graph.model import _stage_extents, _stage_gap_midpoint, _stage_vertical_extents


def _rects_overlap(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> bool:
    """Return whether two (x, y, width, height) rects share any interior area."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _assert_pill_bounds_inside(graph: Graph) -> None:
    """Assert every flow pill's full rectangle, not just its anchor, fits the canvas."""
    measured = graph.measure()
    for _wire_id, (px, py, pw, ph) in graph._layout.flow_pills:
        assert px >= 0
        assert py >= 0
        assert px + pw <= measured.width
        assert py + ph <= measured.height


def _painted_pill_rect(
    rect: tuple[float, float, float, float], graph: Graph
) -> tuple[float, float, float, float]:
    """Expand a flow pill's nominal rect by its rendered border halo."""
    x, y, width, height = rect
    halo = graph.chrome.border_width / 2
    return (x - halo, y - halo, width + 2 * halo, height + 2 * halo)


def _nub_rect(anchor: tuple[float, float, str]) -> tuple[float, float, float, float]:
    """Return a staged collapsible card's 18x18 right-edge fold nub rect."""
    x, y, side = anchor
    assert side == "right"
    return (x, y - 9.0, 18.0, 18.0)


def _path_points(path_d: str) -> list[tuple[float, float]]:
    """Extract every (x, y) coordinate pair from a rendered SVG path string."""
    numbers = [float(token) for token in re.findall(r"-?\d+(?:\.\d+)?", path_d)]
    return list(zip(numbers[0::2], numbers[1::2], strict=True))


def _point_inside_box(point: tuple[float, float], box: tuple[float, float, float, float]) -> bool:
    """Return whether ``point`` lies strictly inside ``box``, not merely on its edge.

    A route's own endpoints sit exactly on their source/destination box's
    edge; a strict inequality excludes that expected touch while still
    catching a genuine interior crossing of an unrelated card.
    """
    px, py = point
    bx, by, bw, bh = box
    return bx < px < bx + bw and by < py < by + bh


_PATH_CMD_RE = re.compile(r"([MLC])\s*([^MLC]*)")


def _sample_path_points(path_d: str, steps: int = 200) -> list[tuple[float, float]]:
    """Densely sample every M/L/C segment of a rendered SVG path.

    Unlike `_path_points`, which only returns each segment's own anchor
    and control coordinates, this walks the actual curve at many ``t``
    values — a continuous cubic can dip well below its own control hull's
    extreme points partway through a segment, so only the sampled curve
    itself can prove no intersection with an intervening card.
    """
    points: list[tuple[float, float]] = []
    current = (0.0, 0.0)
    for letter, rest in _PATH_CMD_RE.findall(path_d):
        values = [float(token) for token in re.findall(r"-?\d+(?:\.\d+)?", rest)]
        if letter == "M":
            current = (values[0], values[1])
            points.append(current)
        elif letter == "L":
            current = (values[0], values[1])
            points.append(current)
        else:  # "C"
            p0 = current
            c1, c2, end = (values[0], values[1]), (values[2], values[3]), (values[4], values[5])
            for step in range(1, steps + 1):
                t = step / steps
                mt = 1 - t
                x = mt**3 * p0[0] + 3 * mt**2 * t * c1[0] + 3 * mt * t**2 * c2[0] + t**3 * end[0]
                y = mt**3 * p0[1] + 3 * mt**2 * t * c1[1] + 3 * mt * t**2 * c2[1] + t**3 * end[1]
                points.append((x, y))
            current = end
    return points


def test_staged_layout_places_cards_left_to_right_and_top_to_bottom():
    graph = Graph(
        (("a", Card("A", width=100)), ("b", Card("B", width=120)), ("c", Card("C", width=80))),
        Staged((StageSlot("a", 0, 0), StageSlot("b", 1, 0), StageSlot("c", 1, 1))),
        gap=20,
        layer_gap=40,
    )
    boxes = dict(graph.measure().boxes)
    assert boxes["b"][0] == boxes["a"][0] + boxes["a"][2] + 40
    assert boxes["c"][0] == boxes["b"][0]
    assert boxes["c"][1] == boxes["b"][1] + boxes["b"][3] + 20


@pytest.mark.parametrize(
    "slots, message",
    [
        ((StageSlot("a", 0, 0),), "cover graph node ids exactly once"),
        ((StageSlot("a", 1, 0), StageSlot("b", 1, 1)), "dense from zero"),
        ((StageSlot("a", 0, 1), StageSlot("b", 1, 1)), "dense from zero"),
        ((StageSlot("a", 0, 0), StageSlot("b", 0, 0)), "share a stage/lane"),
    ],
)
def test_staged_layout_rejects_invalid_positions(slots, message):
    with pytest.raises(SpecError, match=message):
        Graph((("a", Card("A")), ("b", Card("B"))), Staged(slots))


def test_staged_graph_wires_require_a_flow_kind_at_construction():
    """Graph is authoritative for staged wire kinds even without EventFlow."""
    with pytest.raises(SpecError, match="must declare a flow kind"):
        Graph(
            (("a", Card("A")), ("b", Card("B"))),
            Staged((StageSlot("a", 0, 0), StageSlot("b", 1, 0))),
            wires=(Wire("a-b", "a", "b"),),
        )


def test_flow_wire_kind_requires_a_staged_layout():
    with pytest.raises(SpecError, match="flow wire kinds require a Staged layout"):
        Graph(
            (("a", Card("A")), ("b", Card("B"))),
            Slotted((Slot("a", 0, 0), Slot("b", 1, 0))),
            wires=(Wire("a-b", "a", "b", kind="forward"),),
        )


def test_staged_layout_requires_minimum_layer_gap_for_collapsible_cards():
    with pytest.raises(SpecError, match=re.escape("Graph.layer_gap must be at least 18")):
        Graph(
            (("a", Card("A")), ("b", Card("B"))),
            Staged((StageSlot("a", 0, 0), StageSlot("b", 1, 0))),
            collapsible=("a",),
            layer_gap=17,
        )


def test_staged_layout_lane_gap_has_no_collapsible_minimum():
    """Every staged nub now folds along the right edge, so only layer_gap guards it."""
    assert Graph(
        (("a", Card("A")), ("b", Card("B"))),
        Staged((StageSlot("a", 0, 0), StageSlot("b", 1, 0))),
        collapsible=("a",),
        gap=1,
        layer_gap=18,
    )


def test_staged_layout_reserves_nub_width_only_for_last_stage_collapsible_cards():
    layout = Staged((StageSlot("a", 0, 0), StageSlot("b", 1, 0), StageSlot("c", 1, 1)))
    nodes = (
        ("a", Card("A", width=100)),
        ("b", Card("B", width=100)),
        ("c", Card("C", width=100)),
    )
    base_width = Graph(nodes, layout).measure().width
    non_last_stage_width = Graph(nodes, layout, collapsible=("a",)).measure().width
    last_stage_width = Graph(nodes, layout, collapsible=("b", "c")).measure().width

    assert non_last_stage_width == base_width
    # The canvas's trailing padding already absorbs most of the 18px nub
    # reservation; only the shortfall beyond it grows the canvas.
    assert last_stage_width == base_width + 2


def test_staged_layout_final_stage_nub_uses_actual_box_width_not_stage_max():
    layout = Staged((StageSlot("a", 0, 0), StageSlot("narrow", 1, 0), StageSlot("wide", 1, 1)))
    nodes = (
        ("a", Card("A")),
        ("narrow", Card("Narrow", width=90)),
        ("wide", Card("Wide", width=220)),
    )
    base = Graph(nodes, layout).measure()
    x, _y, box_width, _height = dict(base.boxes)["narrow"]
    assert x + box_width + 18 < base.width

    narrow_collapsed = Graph(nodes, layout, collapsible=("narrow",)).measure()
    assert narrow_collapsed.width == base.width


def test_wireless_staged_collapsible_uses_right_edge_nub_css():
    layout = Staged((StageSlot("a", 0, 0), StageSlot("b", 1, 0)))
    nodes = (("a", Card("A")), ("b", Card("B")))
    graph = Graph(nodes, layout, collapsible=("a", "b"), dom_prefix="wireless")
    html = graph.as_raw_html()
    assert "left:100%;top:50%;transform:translateY(-50%)" in html
    assert "left:50%;transform:translateX(-50%);top:100%" not in html


def _flow(*edges: FlowEdge):
    return EventFlow(
        (("a", Card("A")), ("b", Card("B")), ("c", Card("C"))),
        (StageSlot("a", 0, 0), StageSlot("b", 1, 0), StageSlot("c", 0, 1)),
        edges,
        collapsible=("a",),
        dom_prefix="flow",
    )


def test_event_flow_excludes_back_edges_from_visibility_topology():
    graph = _flow(
        FlowEdge("a-b", "a", "b", "forward", "next"),
        FlowEdge("b-c", "b", "c", "back", "retry"),
    )
    assert graph.visibility == ("a-b",)
    assert graph.wires[0].kind == "forward"
    assert graph.wires[1].kind == "back"


def test_event_flow_rejects_kind_geometry_mismatch():
    with pytest.raises(SpecError, match="skip edge must advance by more than one stage"):
        _flow(FlowEdge("a-b", "a", "b", "skip"))


def test_event_flow_snapshots_custom_styles():
    styles = {"back": EdgeStyle("#123456", width=2.0, dash=(2.0, 3.0))}
    graph = _flow(FlowEdge("b-c", "b", "c", "back", "retry"))
    customized = EventFlow(
        graph.nodes,
        (StageSlot("a", 0, 0), StageSlot("b", 1, 0), StageSlot("c", 0, 1)),
        (FlowEdge("b-c", "b", "c", "back", "retry"),),
        styles=styles,  # ty: ignore[invalid-argument-type]
    )
    styles.clear()
    assert dict(customized.edge_styles)["back"].stroke == "#123456"


def test_unknown_wire_ids_are_rejected_from_explicit_visibility_and_hide_wires():
    with pytest.raises(SpecError, match=re.escape("Graph.visibility references an unknown wire")):
        Graph(
            (("a", Card("A")), ("b", Card("B"))),
            Staged((StageSlot("a", 0, 0), StageSlot("b", 1, 0))),
            wires=(Wire("a-b", "a", "b", kind="forward"),),
            visibility=("nope",),
        )
    with pytest.raises(
        SpecError, match=re.escape("Graph.rules hide_wires must reference known wires")
    ):
        Graph(
            (("a", Card("A")), ("b", Card("B"))),
            Staged((StageSlot("a", 0, 0), StageSlot("b", 1, 0))),
            wires=(Wire("a-b", "a", "b", kind="forward"),),
            collapsible=("a",),
            rules=(StateRule((Atom(ControlRef("a"), "checked"),), hide_wires=("nope",)),),
        )


def test_back_wire_ids_are_rejected_as_paint_only_from_visibility_and_hide_wires():
    with pytest.raises(
        SpecError, match=re.escape("Graph.visibility cannot select a paint-only back wire")
    ):
        Graph(
            (("a", Card("A")), ("b", Card("B")), ("c", Card("C"))),
            Staged((StageSlot("a", 0, 0), StageSlot("b", 1, 0), StageSlot("c", 0, 1))),
            wires=(
                Wire("a-b", "a", "b", kind="forward"),
                Wire("b-c", "b", "c", kind="back"),
            ),
            visibility=("a-b", "b-c"),
        )
    with pytest.raises(
        SpecError,
        match=re.escape("Graph.rules hide_wires cannot target a paint-only back wire"),
    ):
        Graph(
            (("a", Card("A")), ("b", Card("B")), ("c", Card("C"))),
            Staged((StageSlot("a", 0, 0), StageSlot("b", 1, 0), StageSlot("c", 0, 1))),
            wires=(
                Wire("a-b", "a", "b", kind="forward"),
                Wire("b-c", "b", "c", kind="back"),
            ),
            visibility=("a-b",),
            collapsible=("a",),
            rules=(StateRule((Atom(ControlRef("a"), "checked"),), hide_wires=("b-c",)),),
        )


def test_hide_cards_rule_hides_the_back_wire_touching_the_hidden_card():
    graph = Graph(
        (("a", Card("A")), ("b", Card("B")), ("c", Card("C"))),
        Staged((StageSlot("a", 0, 0), StageSlot("b", 1, 0), StageSlot("c", 0, 1))),
        wires=(
            Wire("a-b", "a", "b", kind="forward"),
            Wire("b-c", "b", "c", kind="back"),
        ),
        visibility=("a-b",),
        collapsible=("a",),
        rules=(StateRule((Atom(ControlRef("a"), "checked"),), hide_cards=("c",)),),
        dom_prefix="touch",
    )
    assert graph._compiled.rules == (
        (
            ("#touch-nub-0:checked",),
            ("touch-card-1", "touch-card-2", "touch-edge-0", "touch-edge-1"),
        ),
    )


def test_event_flow_renders_styles_pills_and_right_edge_nubs():
    graph = _flow(
        FlowEdge("a-b", "a", "b", "forward", "continue"),
        FlowEdge("b-c", "b", "c", "back", "retry"),
    )
    html = graph.as_raw_html()
    assert (
        f'text-anchor="middle" dominant-baseline="middle" fill="{graph.theme.axis}" '
        f'style="font-size:{graph.chrome.caption_size}px">continue</text>'
    ) in html
    assert ">retry</text>" in html
    assert 'stroke-dasharray="2 3"' in html
    assert "left:100%;top:50%;transform:translateY(-50%)" in html
    assert "<script" not in html


def test_event_flow_paths_and_pills_stay_inside_measured_canvas():
    graph = _flow(
        FlowEdge("a-b", "a", "b", "forward", "continue"),
        FlowEdge("b-c", "b", "c", "back", "retry"),
    )
    measured = graph.measure()
    for _wire_id, (_path, anchor) in graph._layout.wire_geometry:
        assert 0 <= anchor[0] <= measured.width
        assert 0 <= anchor[1] <= measured.height
    _assert_pill_bounds_inside(graph)


def test_event_flow_omits_the_legacy_marker_def():
    """Every flow wire declares a kind, so the unused legacy marker never renders."""
    graph = _flow(
        FlowEdge("a-b", "a", "b", "forward", "continue"),
        FlowEdge("b-c", "b", "c", "back", "retry"),
    )
    html = graph.as_raw_html()
    assert f'id="{graph.dom_prefix}-arrow"' not in html
    assert f'id="{graph.dom_prefix}-arrow-forward"' in html
    assert f'id="{graph.dom_prefix}-arrow-back"' in html


def test_back_wire_hides_via_either_collapsed_endpoint():
    """A back edge is endpoint-based paint suppression: either end can hide it."""
    graph = EventFlow(
        (("a", Card("A")), ("b", Card("B")), ("c", Card("C"))),
        (StageSlot("a", 0, 0), StageSlot("b", 1, 0), StageSlot("c", 0, 1)),
        (
            FlowEdge("a-b", "a", "b", "forward"),
            FlowEdge("b-a", "b", "a", "back", "retry"),
        ),
        collapsible=("a", "b"),
        dom_prefix="collapse",
    )
    assert graph._compiled.rules == (
        (
            ("#collapse-nub-0:checked",),
            ("collapse-card-1", "collapse-edge-0", "collapse-edge-1"),
        ),
        (("#collapse-nub-1:checked",), ("collapse-edge-1",)),
    )


def test_forward_wire_label_pill_rejected_when_wider_than_layer_gap():
    edges = (FlowEdge("a-b", "a", "b", "forward", "hello"),)
    # Default chrome: pill half-width = (2*8 + 5*11*0.6)/2 = 24.5, painted +0.5px
    # border halo = 25.0. No loop pools on either side, so the centered pill
    # alone drives the requirement: 2*(0 + chip_gap(10) + 25.0) = 70 exactly.
    assert EventFlow(
        (("a", Card("A")), ("b", Card("B"))),
        (StageSlot("a", 0, 0), StageSlot("b", 1, 0)),
        edges,
        stage_gap=70,
    )
    with pytest.raises(
        SpecError,
        match=re.escape(
            "Graph.layer_gap must be at least 70px between stage 0 and stage 1 but is 69px"
        ),
    ):
        EventFlow(
            (("a", Card("A")), ("b", Card("B"))),
            (StageSlot("a", 0, 0), StageSlot("b", 1, 0)),
            edges,
            stage_gap=69,
        )


def test_forward_wire_label_pill_reserves_extra_width_for_a_collapsible_source():
    edges = (FlowEdge("a-b", "a", "b", "forward", "hello"),)
    # A collapsible source stage's right-edge nub reaches the shared
    # `_NUB_RESERVE` 18px regardless of any loop pool, so the centered pill
    # must clear whichever of {nub, opposing loop} reaches furthest:
    # 2*(18 + chip_gap(10) + 25.0) = 106 exactly.
    assert EventFlow(
        (("a", Card("A")), ("b", Card("B"))),
        (StageSlot("a", 0, 0), StageSlot("b", 1, 0)),
        edges,
        collapsible=("a",),
        stage_gap=106,
    )
    with pytest.raises(
        SpecError,
        match=re.escape(
            "Graph.layer_gap must be at least 106px between stage 0 and stage 1 but is 105px"
        ),
    ):
        EventFlow(
            (("a", Card("A")), ("b", Card("B"))),
            (StageSlot("a", 0, 0), StageSlot("b", 1, 0)),
            edges,
            collapsible=("a",),
            stage_gap=105,
        )


def test_forward_pill_clears_a_sibling_lanes_collapsible_nub():
    """A stage-wide nub reserve still applies to a pill from a non-collapsible sibling.

    The physical fold nub occupies the gap regardless of which lane's card
    sourced a given forward pill, so `b`'s outgoing pill must still clear
    `a`'s nub even though `b` itself is not collapsible — the historical
    bug only widened the gap for a collapsible wire's *own* pill.
    """
    nodes = (("a", Card("A")), ("b", Card("B")), ("c", Card("C")))
    slots = (StageSlot("a", 0, 0), StageSlot("b", 0, 1), StageSlot("c", 1, 0))
    edges = (FlowEdge("b-c", "b", "c", "forward", "go"),)
    # Pill half-width for "go" = (2*8 + 2*11*0.6)/2 = 14.6, painted 15.1.
    # 2*(18 + 10 + 15.1) = 86.2 exactly.
    graph = EventFlow(nodes, slots, edges, collapsible=("a",), dom_prefix="sib", stage_gap=87)
    pill = dict(graph._layout.flow_pills)["b-c"]
    nub_anchor = dict(graph._layout.nub_anchors)["a"]
    assert not _rects_overlap(_nub_rect(nub_anchor), _painted_pill_rect(pill, graph))
    with pytest.raises(
        SpecError,
        match=re.escape(
            "Graph.layer_gap must be at least 86.2px between stage 0 and stage 1 but is 86px"
        ),
    ):
        EventFlow(nodes, slots, edges, collapsible=("a",), dom_prefix="sibbad", stage_gap=86)


def test_event_flow_default_stage_gap_derives_enough_room_for_a_collapsible_source_pill():
    # Pill half-width for "continue" = (2*8 + 8*11*0.6)/2 = 34.4, painted 34.9.
    # 2*(18 + chip_gap(10) + 34.9) = 125.8, ceiled to 126 and floored at 108
    # only if smaller — 126 > 108, so the derived default is 126 exactly.
    graph = EventFlow(
        (("a", Card("A")), ("b", Card("B"))),
        (StageSlot("a", 0, 0), StageSlot("b", 1, 0)),
        (FlowEdge("a-b", "a", "b", "forward", "continue"),),
        collapsible=("a",),
    )
    assert graph.layer_gap == 126
    pill = dict(graph._layout.flow_pills)["a-b"]
    nub_anchor = dict(graph._layout.nub_anchors)["a"]
    assert not _rects_overlap(_nub_rect(nub_anchor), _painted_pill_rect(pill, graph))


def test_event_flow_default_stage_gap_is_never_smaller_than_108():
    # Nothing occupies the gap, so the planner requires 0 — the floor wins.
    graph = EventFlow(
        (("a", Card("A")), ("b", Card("B"))),
        (StageSlot("a", 0, 0), StageSlot("b", 1, 0)),
        (FlowEdge("a-b", "a", "b", "forward"),),
    )
    assert graph.layer_gap == 108


def test_skip_route_offset_beyond_padding_expands_the_canvas():
    chrome = CardChrome(chip_gap=50)
    nodes = (
        ("a", Card("A", chrome=chrome)),
        ("b", Card("B", chrome=chrome)),
        ("c", Card("C", chrome=chrome)),
    )
    slots = (StageSlot("a", 0, 0), StageSlot("b", 1, 0), StageSlot("c", 2, 0))
    graph = EventFlow(
        nodes,
        slots,
        (FlowEdge("a-b", "a", "b", "forward"), FlowEdge("a-c", "a", "c", "skip")),
        gap=18,
        stage_gap=18,
        chrome=chrome,
        dom_prefix="tight",
    )
    baseline = EventFlow(
        nodes,
        slots,
        (FlowEdge("a-b", "a", "b", "forward"),),
        gap=18,
        stage_gap=18,
        chrome=chrome,
        dom_prefix="base",
    ).measure()
    measured = graph.measure()
    assert measured.height > baseline.height
    for _card_id, (x, y, _width, _height) in measured.boxes:
        assert x >= 0
        assert y >= 0
    for _wire_id, (_path, anchor) in graph._layout.wire_geometry:
        assert 0 <= anchor[0] <= measured.width
        assert 0 <= anchor[1] <= measured.height
    _assert_pill_bounds_inside(graph)


def test_back_route_offset_beyond_padding_expands_the_canvas():
    chrome = CardChrome(chip_gap=50)
    nodes = (
        ("a", Card("A", chrome=chrome)),
        ("b", Card("B", chrome=chrome)),
        ("c", Card("C", chrome=chrome)),
    )
    slots = (StageSlot("a", 0, 0), StageSlot("b", 1, 0), StageSlot("c", 2, 0))
    graph = EventFlow(
        nodes,
        slots,
        (
            FlowEdge("a-b", "a", "b", "forward"),
            FlowEdge("b-c", "b", "c", "forward"),
            FlowEdge("c-a", "c", "a", "back"),
        ),
        gap=18,
        stage_gap=18,
        chrome=chrome,
        dom_prefix="tightback",
    )
    baseline = EventFlow(
        nodes,
        slots,
        (FlowEdge("a-b", "a", "b", "forward"), FlowEdge("b-c", "b", "c", "forward")),
        gap=18,
        stage_gap=18,
        chrome=chrome,
        dom_prefix="base2",
    ).measure()
    measured = graph.measure()
    assert measured.height > baseline.height
    for _card_id, (x, y, _width, _height) in measured.boxes:
        assert x >= 0
        assert y >= 0
    for _wire_id, (_path, anchor) in graph._layout.wire_geometry:
        assert 0 <= anchor[0] <= measured.width
        assert 0 <= anchor[1] <= measured.height
    _assert_pill_bounds_inside(graph)


def test_same_stage_back_wires_loop_left_and_right_without_overlapping_cards():
    nodes = (("a", Card("A")), ("b", Card("B")), ("c", Card("C")))
    slots = (StageSlot("a", 0, 0), StageSlot("b", 0, 1), StageSlot("c", 0, 2))
    graph = EventFlow(
        nodes,
        slots,
        (
            FlowEdge("b-a", "b", "a", "back", "retry"),
            FlowEdge("a-c", "a", "c", "back", "resume"),
        ),
        dom_prefix="loops",
    )
    boxes = tuple(box for _card_id, box in graph.measure().boxes)
    pills = dict(graph._layout.flow_pills)
    left_pill = pills["b-a"]
    right_pill = pills["a-c"]
    left_of_cards = min(box[0] for box in boxes)
    right_of_cards = max(box[0] + box[2] for box in boxes)
    assert left_pill[0] + left_pill[2] <= left_of_cards
    assert right_pill[0] >= right_of_cards
    for box in boxes:
        assert not _rects_overlap(left_pill, box)
        assert not _rects_overlap(right_pill, box)
    _assert_pill_bounds_inside(graph)


def test_multiple_same_side_c_loops_pack_into_disjoint_tracks():
    nodes = (("a", Card("A")), ("b", Card("B")), ("c", Card("C")))
    slots = (StageSlot("a", 0, 0), StageSlot("b", 0, 1), StageSlot("c", 0, 2))
    graph = EventFlow(
        nodes,
        slots,
        (
            FlowEdge("b-a", "b", "a", "back", "retry"),
            FlowEdge("c-a", "c", "a", "back", "restart"),
        ),
        dom_prefix="stacked",
    )
    boxes = tuple(box for _card_id, box in graph.measure().boxes)
    pills = dict(graph._layout.flow_pills)
    first_pill = pills["b-a"]
    second_pill = pills["c-a"]
    assert not _rects_overlap(first_pill, second_pill)
    for box in boxes:
        assert not _rects_overlap(first_pill, box)
        assert not _rects_overlap(second_pill, box)
    _assert_pill_bounds_inside(graph)


def test_thick_edge_style_widths_stay_inside_the_measured_canvas():
    nodes = (("a", Card("A")), ("b", Card("B")), ("c", Card("C")))
    slots = (StageSlot("a", 0, 0), StageSlot("b", 1, 0), StageSlot("c", 2, 0))
    styles = {
        "forward": EdgeStyle("#000000", width=12.0),
        "skip": EdgeStyle("#000000", width=18.0, dash=(5.0, 3.0)),
        "back": EdgeStyle("#000000", width=24.0, dash=(2.0, 3.0)),
    }
    graph = EventFlow(
        nodes,
        slots,
        (
            FlowEdge("a-b", "a", "b", "forward"),
            FlowEdge("b-c", "b", "c", "forward"),
            FlowEdge("a-c", "a", "c", "skip", "jump"),
            FlowEdge("c-a", "c", "a", "back", "retry"),
        ),
        styles=styles,  # ty: ignore[invalid-argument-type]
        dom_prefix="thick",
    )
    measured = graph.measure()
    _assert_pill_bounds_inside(graph)
    wires_by_id = {wire.id: wire for wire in graph.wires}
    for wire_id, (path_d, _anchor) in graph._layout.wire_geometry:
        half = styles[cast(EdgeKind, wires_by_id[wire_id].kind)].width / 2
        for x, y in _path_points(path_d):
            assert x - half >= -1e-6
            assert x + half <= measured.width + 1e-6
            assert y - half >= -1e-6
            assert y + half <= measured.height + 1e-6


def test_back_sag_clears_a_taller_intervening_stage_card():
    """A back edge's sag must clear every stage it spans, not just its own two boxes."""
    tall = Card(
        "Middle",
        content=(
            TextBlock("one"),
            TextBlock("two"),
            TextBlock("three"),
            TextBlock("four"),
            TextBlock("five"),
        ),
    )
    nodes = (("start", Card("Start")), ("middle", tall), ("end", Card("End")))
    slots = (StageSlot("start", 0, 0), StageSlot("middle", 1, 0), StageSlot("end", 2, 0))
    graph = EventFlow(
        nodes,
        slots,
        (FlowEdge("end-start", "end", "start", "back", "retry"),),
        dom_prefix="span",
    )
    boxes = dict(graph.measure().boxes)
    middle_box = boxes["middle"]
    (path_d, _anchor) = dict(graph._layout.wire_geometry)["end-start"]
    points = _path_points(path_d)
    pill = dict(graph._layout.flow_pills)["end-start"]
    for box in boxes.values():
        for point in points:
            assert not _point_inside_box(point, box)
        assert not _rects_overlap(pill, box)
    # The taller intervening card is the binding constraint, not the wire's
    # own shorter endpoints: prove the sag actually reaches past it.
    corridor_y = max(y for _x, y in points)
    assert corridor_y > middle_box[1] + middle_box[3]
    _assert_pill_bounds_inside(graph)


def test_stacked_back_tracks_clear_a_taller_intervening_lane():
    """Packed offsets stack on top of a per-wire span bound, never inside it."""
    tall = Card(
        "B1",
        content=(
            TextBlock("one"),
            TextBlock("two"),
            TextBlock("three"),
            TextBlock("four"),
            TextBlock("five"),
        ),
    )
    nodes = (("a", Card("A")), ("b0", Card("B0")), ("b1", tall), ("c", Card("C")))
    slots = (
        StageSlot("a", 0, 0),
        StageSlot("b0", 1, 0),
        StageSlot("b1", 1, 1),
        StageSlot("c", 2, 0),
    )
    graph = EventFlow(
        nodes,
        slots,
        (
            FlowEdge("c-a", "c", "a", "back", "retry"),
            FlowEdge("b0-a", "b0", "a", "back", "reset"),
        ),
        dom_prefix="stack",
    )
    boxes = dict(graph.measure().boxes)
    wire_geometry = dict(graph._layout.wire_geometry)
    pills = dict(graph._layout.flow_pills)
    for wire_id in ("c-a", "b0-a"):
        points = _path_points(wire_geometry[wire_id][0])
        pill = pills[wire_id]
        for box in boxes.values():
            for point in points:
                assert not _point_inside_box(point, box)
            assert not _rects_overlap(pill, box)
    assert not _rects_overlap(pills["c-a"], pills["b0-a"])
    _assert_pill_bounds_inside(graph)


def test_same_stage_c_loop_pill_rejected_when_wider_than_an_explicit_stage_gap_at_interior_stage():
    nodes = (("s", Card("S")), ("p", Card("P")), ("q", Card("Q")))
    slots = (StageSlot("s", 0, 0), StageSlot("p", 1, 0), StageSlot("q", 1, 1))
    edges = (FlowEdge("q-p", "q", "p", "back", "retry payment"),)
    # A lone left-loop pool has no opposing occupant, so it may touch its own
    # stage boundary exactly: offset(60.9) + painted half(51.4) = 112.3.
    # Omitting `stage_gap` would always derive enough room, so this must
    # pass an explicit, deliberately insufficient gap to trigger rejection.
    graph = EventFlow(nodes, slots, edges, dom_prefix="ok", stage_gap=113)
    _assert_pill_bounds_inside(graph)
    with pytest.raises(
        SpecError,
        match=re.escape(
            "Graph.layer_gap must be at least 112.3px between stage 0 and stage 1 but is 112px"
        ),
    ):
        EventFlow(nodes, slots, edges, dom_prefix="long", stage_gap=112)


def test_same_stage_c_loop_exterior_pool_ignores_the_stage_gap_bound():
    """The outermost pool (first stage's left loop) has open canvas, not a neighbor."""
    nodes = (("p", Card("P")), ("q", Card("Q")), ("s", Card("S")))
    slots = (StageSlot("p", 0, 0), StageSlot("q", 0, 1), StageSlot("s", 1, 0))
    graph = EventFlow(
        nodes,
        slots,
        (FlowEdge("q-p", "q", "p", "back", "retry payment"),),
        dom_prefix="ext",
    )
    _assert_pill_bounds_inside(graph)


def test_same_stage_c_loop_accumulated_tracks_exact_boundary_and_rejection():
    """Two 5-char-labeled tracks in one interior pool reach exactly 118.5px."""

    def build(stage_gap: int) -> Graph:
        nodes = (("s", Card("S")), ("p", Card("P")), ("q", Card("Q")), ("r", Card("R")))
        slots = (
            StageSlot("s", 0, 0),
            StageSlot("p", 1, 0),
            StageSlot("q", 1, 1),
            StageSlot("r", 1, 2),
        )
        return EventFlow(
            nodes,
            slots,
            (
                FlowEdge("q-p", "q", "p", "back", "abcde"),
                FlowEdge("r-q", "r", "q", "back", "fghij"),
            ),
            stage_gap=stage_gap,
            dom_prefix="acc",
        )

    graph = build(119)
    pills = dict(graph._layout.flow_pills)
    assert not _rects_overlap(
        _painted_pill_rect(pills["q-p"], graph), _painted_pill_rect(pills["r-q"], graph)
    )
    _assert_pill_bounds_inside(graph)
    with pytest.raises(
        SpecError,
        match=re.escape(
            "Graph.layer_gap must be at least 118.5px between stage 0 and stage 1 but is 118px"
        ),
    ):
        build(118)


def _coincident_y_fixture() -> tuple[
    tuple[tuple[str, Card], ...], tuple[StageSlot, ...], tuple[FlowEdge, ...]
]:
    """A forward pill and a right-loop pill share both a src card and a paint y.

    `a` (lane 0) sources both a same-stage right loop to `e` (lane 1) and a
    forward edge to `f` (lane 1, next stage): lane rows are shared across
    every stage, so both pills' y — the average of their own lane-0/lane-1
    endpoints — land on the exact same value, without either route knowing
    the other exists.
    """
    nodes = (("a", Card("A")), ("e", Card("E")), ("f", Card("F")))
    slots = (StageSlot("a", 0, 0), StageSlot("e", 0, 1), StageSlot("f", 1, 1))
    edges = (
        FlowEdge("a-f", "a", "f", "forward", "go now"),
        FlowEdge("a-e", "a", "e", "back", "retry"),
    )
    return nodes, slots, edges


def test_default_stage_gap_keeps_a_forward_pill_and_right_loop_disjoint_at_coincident_y():
    nodes, slots, edges = _coincident_y_fixture()
    graph = EventFlow(nodes, slots, edges, dom_prefix="coin")
    # The 196px derived default comes from the exact same private planner
    # `Graph` itself validates an explicit `stage_gap` against (asserted via
    # `graph.layer_gap` and the boundary test below, not hand-derived here).
    pills = dict(graph._layout.flow_pills)
    forward_pill, loop_pill = pills["a-f"], pills["a-e"]
    assert forward_pill[1] == loop_pill[1]  # the coincident y this fixture forces
    assert graph.layer_gap == 196
    assert not _rects_overlap(
        _painted_pill_rect(forward_pill, graph), _painted_pill_rect(loop_pill, graph)
    )
    _assert_pill_bounds_inside(graph)


def test_coincident_y_fixture_explicit_boundary_passes_and_one_pixel_fails():
    nodes, slots, edges = _coincident_y_fixture()
    graph = EventFlow(nodes, slots, edges, dom_prefix="coinok", stage_gap=196)
    assert graph.layer_gap == 196
    with pytest.raises(
        SpecError,
        match=re.escape(
            "Graph.layer_gap must be at least 195.6px between stage 0 and stage 1 but is 195px"
        ),
    ):
        EventFlow(nodes, slots, edges, dom_prefix="coinbad", stage_gap=195)


def test_stage_gap_enforces_chip_gap_between_a_neighboring_stage_nub_and_a_left_loop():
    """A collapsible source's nub and the *next* stage's own left loop share a gap."""
    nodes = (("a", Card("A")), ("p", Card("P")), ("q", Card("Q")))
    slots = (StageSlot("a", 0, 0), StageSlot("p", 1, 0), StageSlot("q", 1, 1))
    edges = (FlowEdge("q-p", "q", "p", "back", "retry"),)
    # The 87.5px requirement comes from the exact same private planner
    # `Graph` itself validates an explicit `stage_gap` against (asserted via
    # the boundary test below, not hand-derived here).
    graph = EventFlow(nodes, slots, edges, collapsible=("a",), dom_prefix="nubloop", stage_gap=88)
    pill = dict(graph._layout.flow_pills)["q-p"]
    nub_anchor = dict(graph._layout.nub_anchors)["a"]
    assert not _rects_overlap(_nub_rect(nub_anchor), _painted_pill_rect(pill, graph))
    with pytest.raises(
        SpecError,
        match=re.escape(
            "Graph.layer_gap must be at least 87.5px between stage 0 and stage 1 but is 87px"
        ),
    ):
        EventFlow(nodes, slots, edges, collapsible=("a",), dom_prefix="nubloopbad", stage_gap=87)


def test_stage_gap_enforces_chip_gap_between_opposing_left_and_right_loop_pools():
    """A left stage's right loop and a right stage's left loop share one gap."""
    nodes = (("a", Card("A")), ("b", Card("B")), ("c", Card("C")), ("d", Card("D")))
    slots = (
        StageSlot("a", 0, 0),
        StageSlot("b", 0, 1),
        StageSlot("c", 1, 0),
        StageSlot("d", 1, 1),
    )
    edges = (
        FlowEdge("b-a", "b", "a", "back", "retry"),
        FlowEdge("d-c", "d", "c", "back", "retry"),
    )
    graph = EventFlow(nodes, slots, edges, dom_prefix="opp", stage_gap=60)
    pills = dict(graph._layout.flow_pills)
    assert not _rects_overlap(
        _painted_pill_rect(pills["b-a"], graph), _painted_pill_rect(pills["d-c"], graph)
    )
    with pytest.raises(
        SpecError,
        match=re.escape(
            "Graph.layer_gap must be at least 59.5px between stage 0 and stage 1 but is 59px"
        ),
    ):
        EventFlow(nodes, slots, edges, dom_prefix="oppbad", stage_gap=59)


def test_stage_gap_uses_the_furthest_reaching_painted_extent_for_a_thick_labeled_style():
    """A thick back stroke paints past its own pill, so the stroke half-width wins."""
    chrome = CardChrome(border_width=8)
    styles = {"back": EdgeStyle("#000000", width=140.0)}
    nodes = (
        ("s", Card("S", chrome=chrome)),
        ("p", Card("P", chrome=chrome)),
        ("q", Card("Q", chrome=chrome)),
    )
    slots = (StageSlot("s", 0, 0), StageSlot("p", 1, 0), StageSlot("q", 1, 1))
    edges = (FlowEdge("q-p", "q", "p", "back", "x"),)
    # Pill half for "x" (1 char) is only (2*8+1*11*0.6)/2 = 11.3, painted with
    # the inflated 4px halo = 15.3 — dwarfed by half the 140px stroke (70).
    # offset(21.3) + max(15.3, 70) = 91.3.
    graph = EventFlow(
        nodes,
        slots,
        edges,
        styles=styles,  # ty: ignore[invalid-argument-type]
        chrome=chrome,
        dom_prefix="thick",
        stage_gap=92,
    )
    _assert_no_wire_samples_enter_any_card(graph)
    with pytest.raises(
        SpecError,
        match=re.escape(
            "Graph.layer_gap must be at least 91.3px between stage 0 and stage 1 but is 91px"
        ),
    ):
        EventFlow(
            nodes,
            slots,
            edges,
            styles=styles,  # ty: ignore[invalid-argument-type]
            chrome=chrome,
            dom_prefix="thickbad",
            stage_gap=91,
        )


def _all_wire_samples(graph: Graph) -> dict[str, list[tuple[float, float]]]:
    """Densely sample every wire's actual rendered curve, not just its anchors."""
    wire_geometry = dict(graph._layout.wire_geometry)
    return {
        wire_id: _sample_path_points(path_d)
        for wire_id, (path_d, _anchor) in wire_geometry.items()
    }


def _assert_no_wire_samples_enter_any_card(graph: Graph) -> None:
    """Assert every wire's densely sampled curve never enters a card's interior."""
    boxes = dict(graph.measure().boxes)
    for wire_id, points in _all_wire_samples(graph).items():
        for card_id, box in boxes.items():
            for point in points:
                assert not _point_inside_box(point, box), (
                    f"wire {wire_id!r} sample {point} enters card {card_id!r} box {box}"
                )


def test_back_sag_gated_route_clears_a_taller_intervening_card_that_a_continuous_bow_grazes():
    """The historical bug: a continuous bow only touches its corridor at one
    instant, so an intervening card positioned off that instant can still be
    grazed even though the corridor height itself clears it. Confirm the
    same boxes actually graze under the old, continuous two-cubic bow, then
    confirm the graph-integrated (gated) route no longer does.
    """
    tall = Card(
        "Middle",
        content=(
            TextBlock("one"),
            TextBlock("two"),
            TextBlock("three"),
            TextBlock("four"),
            TextBlock("five"),
            TextBlock("six"),
            TextBlock("seven"),
            TextBlock("eight"),
        ),
    )
    nodes = (
        ("start", Card("Start")),
        ("mid1", Card("Mid1")),
        ("mid2", tall),
        ("end", Card("End")),
    )
    slots = (
        StageSlot("start", 0, 0),
        StageSlot("mid1", 1, 0),
        StageSlot("mid2", 2, 0),
        StageSlot("end", 3, 0),
    )
    graph = EventFlow(
        nodes, slots, (FlowEdge("end-start", "end", "start", "back", "retry"),), dom_prefix="graze"
    )
    boxes = dict(graph.measure().boxes)
    (path_d, _anchor) = dict(graph._layout.wire_geometry)["end-start"]

    # The fixed, graph-integrated route: no sampled point enters any card.
    for card_id, box in boxes.items():
        for point in _sample_path_points(path_d):
            assert not _point_inside_box(point, box), (
                f"gated sample {point} enters {card_id!r} box {box}"
            )
    _assert_pill_bounds_inside(graph)

    # The old, continuous bow (no gates) computed from the same resolved
    # boxes and bound: proves the graze this fix eliminates was real, not
    # a hypothetical worst case.
    low_stage, high_stage = 0, 3
    slot_by_id = {slot.card_id: slot for slot in slots}
    bottom = max(
        _stage_vertical_extents(boxes, slot_by_id)[stage][1]
        for stage in range(low_stage, high_stage + 1)
    )
    pure = route_back_sag(boxes["end"], boxes["start"], offset=24, bound=bottom)
    pure_hits = [
        point
        for point in _sample_path_points(pure.path)
        if _point_inside_box(point, boxes["mid2"])
    ]
    assert pure_hits, "expected the continuous bow to graze the tall intervening card"


def test_skip_bow_gated_route_clears_unequal_height_intervening_cards():
    """A skip's gated route stays clear even when an early intervening card
    towers over its later, shorter siblings.
    """
    tall = Card(
        "Tall",
        content=(
            TextBlock("one"),
            TextBlock("two"),
            TextBlock("three"),
            TextBlock("four"),
            TextBlock("five"),
            TextBlock("six"),
            TextBlock("seven"),
            TextBlock("eight"),
        ),
    )
    nodes = (
        ("start", Card("Start")),
        ("mid1", tall),
        ("mid2", Card("Mid2")),
        ("end", Card("End")),
    )
    slots = (
        StageSlot("start", 0, 0),
        StageSlot("mid1", 1, 0),
        StageSlot("mid2", 2, 0),
        StageSlot("end", 3, 0),
    )
    graph = EventFlow(
        nodes, slots, (FlowEdge("start-end", "start", "end", "skip", "jump"),), dom_prefix="sgraze"
    )
    _assert_no_wire_samples_enter_any_card(graph)
    _assert_pill_bounds_inside(graph)


def test_multiple_packed_tracks_gated_routes_clear_every_card_and_stay_disjoint():
    """Two packed back tracks around an unequal-height intervening lane: every
    wire's actual curve must clear every card, and their pills must stay
    disjoint from each other and from every card, at every packed offset.
    """
    tall = Card(
        "B1",
        content=(
            TextBlock("one"),
            TextBlock("two"),
            TextBlock("three"),
            TextBlock("four"),
            TextBlock("five"),
        ),
    )
    nodes = (("a", Card("A")), ("b0", Card("B0")), ("b1", tall), ("c", Card("C")))
    slots = (
        StageSlot("a", 0, 0),
        StageSlot("b0", 1, 0),
        StageSlot("b1", 1, 1),
        StageSlot("c", 2, 0),
    )
    graph = EventFlow(
        nodes,
        slots,
        (
            FlowEdge("c-a", "c", "a", "back", "retry"),
            FlowEdge("b0-a", "b0", "a", "back", "reset"),
        ),
        dom_prefix="packed",
    )
    _assert_no_wire_samples_enter_any_card(graph)
    pills = dict(graph._layout.flow_pills)
    assert not _rects_overlap(pills["c-a"], pills["b0-a"])
    _assert_pill_bounds_inside(graph)


def _left_anchor(box: tuple[float, float, float, float]) -> tuple[float, float]:
    x, y, _width, height = box
    return (float(x), y + height / 2)


def _right_anchor(box: tuple[float, float, float, float]) -> tuple[float, float]:
    x, y, width, height = box
    return (float(x + width), y + height / 2)


def _assert_horizontal_destination_tangent(
    points: list[tuple[float, float]], dst_anchor: tuple[float, float]
) -> None:
    """A route's final approach into its destination anchor is (near-)flat.

    Every gated route's last real segment either is a straight horizontal
    line into the anchor (a trailing stage-edge run) or a cubic whose own
    final control point shares the anchor's own y — so its last sampled
    point before the anchor itself sits far closer to the anchor's own y
    than its x, proving a horizontal, not oblique, arrival.
    """
    dst_x, dst_y = dst_anchor
    assert points[-1] == pytest.approx((dst_x, dst_y))
    prev_x, prev_y = points[-2]
    if (prev_x, prev_y) == pytest.approx((dst_x, dst_y)):
        prev_x, prev_y = points[-3]
    assert abs(prev_y - dst_y) < 0.5
    assert abs(prev_x - dst_x) > abs(prev_y - dst_y)


def _assert_flow_geometry_gated_at_stage_edges(
    graph: Graph, wire_dst_anchors: dict[str, tuple[float, float]]
) -> None:
    """Assert every universal stage-gate guarantee for a graph's flow wires.

    No sampled curve point enters any card or any collapsible card's nub,
    no pill overlaps any card, any nub, or any other pill, every wire
    arrives at its own destination anchor with a horizontal tangent, and
    every pill sits fully inside the measured canvas.
    """
    boxes = dict(graph.measure().boxes)
    nub_boxes = {
        card_id: (nx, ny - 9.0, 18.0, 18.0)
        for card_id, (nx, ny, _side) in graph._layout.nub_anchors
    }
    pills = dict(graph._layout.flow_pills)
    for wire_id, points in _all_wire_samples(graph).items():
        for card_id, box in boxes.items():
            for point in points:
                assert not _point_inside_box(point, box), (
                    f"wire {wire_id!r} sample {point} enters card {card_id!r} box {box}"
                )
        for nub_owner, nub in nub_boxes.items():
            for point in points:
                assert not _point_inside_box(point, nub), (
                    f"wire {wire_id!r} sample {point} enters {nub_owner!r}'s nub {nub}"
                )
        _assert_horizontal_destination_tangent(points, wire_dst_anchors[wire_id])
    pill_ids = list(pills)
    for index, wire_id in enumerate(pill_ids):
        pill = pills[wire_id]
        for box in boxes.values():
            assert not _rects_overlap(pill, box)
        for nub in nub_boxes.values():
            assert not _rects_overlap(pill, nub)
        for other_id in pill_ids[index + 1 :]:
            assert not _rects_overlap(pill, pills[other_id])
    _assert_pill_bounds_inside(graph)


def test_right_c_loop_pill_clears_same_stage_collapsible_nubs():
    nodes = (
        ("source", Card("Source")),
        ("collapsible", Card("Collapsible")),
        ("destination", Card("Destination")),
    )
    slots = (
        StageSlot("source", 0, 0),
        StageSlot("collapsible", 0, 1),
        StageSlot("destination", 0, 2),
    )
    graph = EventFlow(
        nodes,
        slots,
        (FlowEdge("loop", "source", "destination", "back", "retry"),),
        collapsible=("collapsible",),
        dom_prefix="nub-loop",
    )
    measured = graph.measure()
    boxes = dict(measured.boxes)
    right_nubs = [
        (nx, ny - 9.0, 18.0, 18.0)
        for _card_id, (nx, ny, side) in graph._layout.nub_anchors
        if side == "right"
    ]
    pill = dict(graph._layout.flow_pills)["loop"]
    assert right_nubs
    for nub in right_nubs:
        assert not _rects_overlap(pill, nub)
    for x, y, width, height in boxes.values():
        assert 0 <= x <= x + width <= measured.width
        assert 0 <= y <= y + height <= measured.height
    for points in _all_wire_samples(graph).values():
        for x, y in points:
            assert 0 <= x <= measured.width
            assert 0 <= y <= measured.height
    _assert_flow_geometry_gated_at_stage_edges(
        graph, {"loop": _right_anchor(boxes["destination"])}
    )


def test_forward_and_skip_gated_routes_clear_a_wider_source_stage_sibling():
    """A forward or skip wire's source card can be far narrower than a
    sibling sharing its own stage on another lane. Without a flat run out
    to the stage's own outer edge first, the route's curve — still inside
    that stage's occupied column — drifts toward the destination's own
    height and grazes the wider sibling long before reaching the physical
    inter-stage gap.
    """
    wide = Card("Wide", width=280)
    narrow = Card("Narrow", width=60)
    midf = Card("MidF")
    end = Card("End")
    nodes = (("wide", wide), ("narrow", narrow), ("midf", midf), ("end", end))
    slots = (
        StageSlot("wide", 0, 0),
        StageSlot("narrow", 0, 1),
        StageSlot("midf", 1, 0),
        StageSlot("end", 2, 0),
    )
    graph = EventFlow(
        nodes,
        slots,
        (
            FlowEdge("narrow-midf", "narrow", "midf", "forward", "go"),
            FlowEdge("narrow-end", "narrow", "end", "skip", "jump"),
        ),
        collapsible=("wide",),
        dom_prefix="wsib",
    )
    boxes = dict(graph.measure().boxes)
    _assert_flow_geometry_gated_at_stage_edges(
        graph,
        {
            "narrow-midf": _left_anchor(boxes["midf"]),
            "narrow-end": _left_anchor(boxes["end"]),
        },
    )

    # Confirm the graze this fix eliminates was real: reconstruct the prior
    # (gated-but-not-edge-anchored) shape from the same resolved boxes and
    # prove it actually enters the wide sibling.
    wide_box = boxes["wide"]
    pure_forward = route_across(boxes["narrow"], boxes["midf"])
    forward_hits = [
        point
        for point in _sample_path_points(pure_forward.path)
        if _point_inside_box(point, wide_box)
    ]
    assert forward_hits, "expected the ungated forward cubic to graze the wider sibling"
    pure_skip = route_skip_bow(boxes["narrow"], boxes["end"], offset=24, bound=wide_box[1])
    skip_hits = [
        point
        for point in _sample_path_points(pure_skip.path)
        if _point_inside_box(point, wide_box)
    ]
    assert skip_hits, "expected the ungated skip bow to graze the wider sibling"


def test_back_gated_route_clears_a_wider_destination_stage_sibling():
    """A back wire's destination card can be far narrower than a sibling
    sharing its own stage on another lane. The sag's final approach must
    reach the stage's own outer edge before turning in, or it grazes the
    wider sibling while still inside that stage's occupied column.
    """
    narrow = Card("Narrow", width=60)
    wide = Card("Wide", width=280)
    mid = Card("Mid")
    src = Card("Src")
    nodes = (("narrow", narrow), ("wide", wide), ("mid", mid), ("src", src))
    slots = (
        StageSlot("narrow", 0, 0),
        StageSlot("wide", 0, 1),
        StageSlot("mid", 1, 0),
        StageSlot("src", 2, 0),
    )
    graph = EventFlow(
        nodes,
        slots,
        (FlowEdge("src-narrow", "src", "narrow", "back", "retry"),),
        collapsible=("wide",),
        dom_prefix="bsib",
    )
    boxes = dict(graph.measure().boxes)
    _assert_flow_geometry_gated_at_stage_edges(
        graph, {"src-narrow": _right_anchor(boxes["narrow"])}
    )

    wide_box = boxes["wide"]
    slot_by_id = {slot.card_id: slot for slot in slots}
    stage_extents = _stage_extents(boxes, slot_by_id)
    src_gate = _stage_gap_midpoint(stage_extents, 1, 2)
    dst_gate = _stage_gap_midpoint(stage_extents, 0, 1)
    gated_no_edges = route_back_sag(
        boxes["src"],
        boxes["narrow"],
        offset=24,
        bound=wide_box[1] + wide_box[3],
        src_gate=src_gate,
        dst_gate=dst_gate,
    )
    hits = [
        point
        for point in _sample_path_points(gated_no_edges.path)
        if _point_inside_box(point, wide_box)
    ]
    assert hits, "expected the edge-less gated sag to still graze the wider sibling"


def test_c_loop_gated_route_clears_a_wider_intervening_lane_sibling():
    """A same-stage back loop's own two endpoints can both be far narrower
    than a third card sharing the same stage between them on another
    lane. Both endpoint runs must reach the stage's own outer edge before
    the turning cubic, whose own hull must then stay entirely outside it.
    """
    a = Card("A", width=60)
    wide = Card("Wide", width=280)
    b = Card("B", width=60)
    nxt = Card("Next")
    nodes = (("a", a), ("wide", wide), ("b", b), ("nxt", nxt))
    slots = (
        StageSlot("a", 0, 0),
        StageSlot("wide", 0, 1),
        StageSlot("b", 0, 2),
        StageSlot("nxt", 1, 0),
    )
    graph = EventFlow(
        nodes,
        slots,
        (FlowEdge("a-b", "a", "b", "back", "loop"),),
        dom_prefix="csib",
    )
    boxes = dict(graph.measure().boxes)
    _assert_flow_geometry_gated_at_stage_edges(graph, {"a-b": _right_anchor(boxes["b"])})

    wide_box = boxes["wide"]
    corridor = boxes["wide"][0] + boxes["wide"][2] + 24
    sx, sy = _right_anchor(boxes["a"])
    dx, dy = _right_anchor(boxes["b"])
    old_path = f"M{sx:g},{sy:g} C{corridor:g},{sy:g} {corridor:g},{dy:g} {dx:g},{dy:g}"
    hits = [point for point in _sample_path_points(old_path) if _point_inside_box(point, wide_box)]
    assert hits, "expected the old single-cubic loop to graze the wider intervening sibling"
