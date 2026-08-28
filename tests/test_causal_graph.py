from typing import cast

import pytest

from coeftable.cards import Card
from coeftable.errors import SpecError
from coeftable.graph import CausalGraph, LayeredDag, Wire


def test_causal_graph_builds_a_collapsible_layered_diamond():
    graph = CausalGraph(
        tuple((node_id, Card(node_id)) for node_id in ("treatment", "m1", "m2", "outcome")),
        (
            Wire("t-m1", "treatment", "m1"),
            Wire("t-m2", "treatment", "m2"),
            Wire("m1-y", "m1", "outcome"),
            Wire("m2-y", "m2", "outcome"),
        ),
        dom_prefix="causal",
    )
    assert isinstance(graph.layout, LayeredDag)
    assert graph.collapsible == ("treatment", "m1", "m2")
    assert tuple(card_id for card_id, _ in graph.measure().boxes) == (
        "treatment",
        "m1",
        "m2",
        "outcome",
    )
    assert graph.as_raw_html().count('type="checkbox"') == 3
    boxes = dict(graph.measure().boxes)
    treatment_top = boxes["treatment"][1]
    m1_left, m1_top = boxes["m1"][0], boxes["m1"][1]
    m2_left, m2_top = boxes["m2"][0], boxes["m2"][1]
    outcome_top = boxes["outcome"][1]
    # Longest-path layering: treatment alone above the shared m1/m2 band,
    # outcome alone below it - exact y-layer equality/ordering, not just
    # the declaration-order box tuple every layout would satisfy.
    assert treatment_top < m1_top == m2_top < outcome_top
    # m1 and m2 share a layer but occupy distinct slots (columns).
    assert m1_left != m2_left


def test_causal_graph_snapshots_inputs_and_rejects_unknown_endpoints():
    nodes = [("a", Card("A")), ("b", Card("B"))]
    wires = [Wire("a-b", "a", "b")]
    graph = CausalGraph(nodes, wires)
    nodes.clear()
    wires.clear()
    assert len(graph.nodes) == 2
    assert len(graph.wires) == 1
    with pytest.raises(SpecError, match="known cards"):
        CausalGraph((("a", Card("A")),), (Wire("a-b", "a", "b"),))


def test_causal_graph_rejects_a_non_sequence_nodes_argument():
    with pytest.raises(SpecError, match=r"CausalGraph\.nodes must be a sequence"):
        CausalGraph(7, ())  # ty: ignore[invalid-argument-type]


def test_causal_graph_lets_graph_reject_malformed_entries():
    # Malformed wire/node entries must surface Graph's own SpecError
    # messages, not a raw TypeError/AttributeError from collapsible
    # inference reading fields off values it hasn't validated yet.
    with pytest.raises(SpecError, match=r"Graph\.wires\[0\] must be a Wire"):
        CausalGraph((("a", Card("A")),), (7,))  # ty: ignore[invalid-argument-type]
    with pytest.raises(SpecError, match=r"Graph\.nodes\[0\] must be an \(id, Card\) pair"):
        CausalGraph((7,), ())  # ty: ignore[invalid-argument-type]
    for malformed_id in (["a"], {"a": True}):
        with pytest.raises(SpecError, match=r"Graph\.nodes\[0\]\.id must be a non-empty str"):
            CausalGraph(
                cast("tuple[tuple[str, Card], ...]", ((malformed_id, Card("A")),)),
                (Wire("a-b", "a", "b"),),
            )


def test_causal_graph_derives_layer_gap_for_stacked_labeled_wires():
    # Both "left" and "right" are wire sources, so CausalGraph marks both
    # collapsible; their fold nubs then share layer 0's band with the two
    # labels stacked on "target". The old hardcoded default of 56 rejected
    # this exact shape (MetricTree's ladder derivation needs 57 here).
    nodes = (
        ("left", Card("Left")),
        ("right", Card("Right")),
        ("target", Card("Target")),
    )
    wires = (
        Wire("wl", "left", "target", label="overlapping"),
        Wire("wr", "right", "target", label="overlapping"),
    )
    graph = CausalGraph(nodes, wires)
    assert graph.collapsible == ("left", "right")
    assert graph.layer_gap == 57
    assert graph.measure().width > 0
    # Explicit overrides are still honored, including ones Graph itself
    # then rejects as too small for the same stacked-label geometry.
    with pytest.raises(SpecError, match="to fit stacked labels beside fold nubs"):
        CausalGraph(nodes, wires, layer_gap=56)
    assert CausalGraph(nodes, wires, layer_gap=100).layer_gap == 100
