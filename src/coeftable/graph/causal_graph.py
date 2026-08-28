"""Thin builder for prepared cards in a causal DAG."""

from __future__ import annotations

from collections.abc import Sequence

from coeftable.cards import Card, CardChrome
from coeftable.cards.chrome import DEFAULT_CHROME
from coeftable.graph.model import Graph, LayeredDag, Wire
from coeftable.theme import DEFAULT, Theme


def CausalGraph(
    nodes: Sequence[tuple[str, Card]],
    wires: Sequence[Wire],
    *,
    theme: Theme = DEFAULT,
    chrome: CardChrome = DEFAULT_CHROME,
    dom_prefix: str = "g0",
    gap: int = 36,
    layer_gap: int = 56,
) -> Graph:
    """Build a collapsible layered DAG from prepared cards and wires."""
    node_entries = tuple(nodes)
    wire_entries = tuple(wires)
    outgoing = {wire.src for wire in wire_entries}
    collapsible = tuple(node_id for node_id, _ in node_entries if node_id in outgoing)
    return Graph(
        nodes=node_entries,
        layout=LayeredDag(),
        wires=wire_entries,
        collapsible=collapsible,
        theme=theme,
        chrome=chrome,
        dom_prefix=dom_prefix,
        gap=gap,
        layer_gap=layer_gap,
    )


__all__ = ["CausalGraph"]
