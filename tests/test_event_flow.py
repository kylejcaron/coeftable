"""Contract tests for the staged graph layout's exact box placement."""

import re

import pytest

from coeftable.cards import Card, TextBlock
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


def test_staged_layout_requires_minimum_gap_for_collapsible_cards():
    with pytest.raises(SpecError, match=re.escape("Graph.gap must be at least 18")):
        Graph(
            (("a", Card("A")), ("b", Card("B"))),
            Staged((StageSlot("a", 0, 0), StageSlot("b", 1, 0))),
            collapsible=("a",),
            gap=17,
        )


def test_staged_layout_adds_nub_overhang_only_for_last_lane_collapsible_cards():
    layout = Staged((StageSlot("a", 0, 0), StageSlot("b", 1, 0), StageSlot("c", 1, 1)))
    nodes = (("a", Card("A")), ("b", Card("B")), ("c", Card("C")))
    base_height = Graph(nodes, layout).measure().height
    upper_lane_height = Graph(nodes, layout, collapsible=("a", "b")).measure().height
    last_lane_height = Graph(nodes, layout, collapsible=("c",)).measure().height

    assert upper_lane_height == base_height
    assert last_lane_height == base_height + 2


def test_staged_layout_short_final_lane_nub_uses_actual_box_bottom():
    layout = Staged((StageSlot("short", 0, 0), StageSlot("tall", 1, 0)))
    nodes = (
        ("short", Card("Short")),
        ("tall", Card("Tall", content=(TextBlock("First"), TextBlock("Second")))),
    )
    base = Graph(nodes, layout).measure()
    _x, y, _width, box_height = dict(base.boxes)["short"]

    assert y + box_height + 18 <= base.height
    assert Graph(nodes, layout, collapsible=("short",)).measure().height == base.height


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


def test_back_wire_ids_are_rejected_from_explicit_visibility_and_hide_wires():
    with pytest.raises(SpecError, match=re.escape("Graph.visibility references an unknown wire")):
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
        SpecError, match=re.escape("Graph.rules hide_wires must reference known wires")
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


def test_hide_cards_rule_is_not_rejected_for_a_card_touched_by_a_back_wire():
    assert Graph(
        (("a", Card("A")), ("b", Card("B")), ("c", Card("C"))),
        Staged((StageSlot("a", 0, 0), StageSlot("b", 1, 0), StageSlot("c", 0, 1))),
        wires=(
            Wire("a-b", "a", "b", kind="forward"),
            Wire("b-c", "b", "c", kind="back"),
        ),
        visibility=("a-b",),
        collapsible=("a",),
        rules=(StateRule((Atom(ControlRef("a"), "checked"),), hide_cards=("c",)),),
    )


def test_event_flow_renders_styles_pills_and_right_edge_nubs():
    graph = _flow(
        FlowEdge("a-b", "a", "b", "forward", "continue"),
        FlowEdge("b-c", "b", "c", "back", "retry"),
    )
    html = graph.as_raw_html()
    assert ">continue</text>" in html
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
