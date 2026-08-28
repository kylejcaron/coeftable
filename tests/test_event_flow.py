"""Contract tests for the staged graph layout's exact box placement."""

import re

import pytest

from coeftable.cards import Card, CardChrome
from coeftable.errors import SpecError
from coeftable.graph import (
    Atom,
    ControlRef,
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
    # Default chrome: pill width = 2*8 + 5*11*0.6 = 49.0 exactly.
    assert EventFlow(
        (("a", Card("A")), ("b", Card("B"))),
        (StageSlot("a", 0, 0), StageSlot("b", 1, 0)),
        edges,
        stage_gap=49,
    )
    with pytest.raises(
        SpecError, match=re.escape("forward wire label pill is wider than Graph.layer_gap")
    ):
        EventFlow(
            (("a", Card("A")), ("b", Card("B"))),
            (StageSlot("a", 0, 0), StageSlot("b", 1, 0)),
            edges,
            stage_gap=48,
        )


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
