"""Contract tests for the staged graph layout's exact box placement."""

import re

import pytest

from coeftable.cards import Card
from coeftable.errors import SpecError
from coeftable.graph import Graph, Staged, StageSlot, Wire


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


def test_staged_layout_rejects_non_empty_wires_at_construction():
    """Staged has no wire geometry yet; construction must reject, not render-crash."""
    with pytest.raises(SpecError, match="EventFlow routing"):
        Graph(
            (("a", Card("A")), ("b", Card("B"))),
            Staged((StageSlot("a", 0, 0), StageSlot("b", 1, 0))),
            wires=(Wire("a-b", "a", "b"),),
        )


def test_staged_layout_requires_minimum_gap_for_collapsible_cards():
    with pytest.raises(SpecError, match=re.escape("Graph.gap must be at least 18")):
        Graph(
            (("a", Card("A")), ("b", Card("B"))),
            Staged((StageSlot("a", 0, 0), StageSlot("b", 1, 0))),
            collapsible=("a",),
            gap=17,
        )


def test_staged_layout_collapsible_adds_fold_nub_height_overhang():
    layout = Staged((StageSlot("a", 0, 0), StageSlot("b", 1, 0)))
    nodes = (("a", Card("A")), ("b", Card("B")))
    base_height = Graph(nodes, layout).measure().height
    folded_height = Graph(nodes, layout, collapsible=("a",)).measure().height
    assert folded_height == base_height + 2
