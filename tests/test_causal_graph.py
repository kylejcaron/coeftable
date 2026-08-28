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
