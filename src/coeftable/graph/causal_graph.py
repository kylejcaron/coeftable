"""Thin builder for prepared cards in a causal DAG."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from coeftable.cards import DEFAULT_CHROME, Card, CardChrome
from coeftable.errors import SpecError
from coeftable.graph.model import Graph, LayeredDag, Wire
from coeftable.theme import DEFAULT, Theme


def _sequence(value: object, *, name: str) -> tuple[object, ...]:
    """Snapshot a public sequence, deferring per-entry shape checks to Graph."""
    try:
        return tuple(cast(Sequence[object], value))
    except TypeError as error:
        raise SpecError(f"{name} must be a sequence") from error


def CausalGraph(
    nodes: Sequence[tuple[str, Card]],
    wires: Sequence[Wire],
    *,
    theme: Theme = DEFAULT,
    chrome: CardChrome = DEFAULT_CHROME,
    dom_prefix: str = "g0",
    gap: int = 36,
    layer_gap: int | None = None,
) -> Graph:
    """Build a collapsible layered DAG from prepared cards and wires.

    ``layer_gap`` defaults to a derived value that always fits the deepest
    possible labeled stack, using the same ladder arithmetic as
    ``MetricTree``. Malformed ``nodes``/``wires`` entries are left for
    ``Graph`` to reject with its own ``SpecError`` messages; this builder
    only inspects entries that are already safe to inspect.
    """
    node_values = _sequence(nodes, name="CausalGraph.nodes")
    wire_values = _sequence(wires, name="CausalGraph.wires")
    outgoing = {wire.src for wire in wire_values if isinstance(wire, Wire)}
    collapsible = tuple(
        entry[0]
        for entry in node_values
        if isinstance(entry, Sequence)
        and not isinstance(entry, (str, bytes))
        and len(entry) == 2
        and entry[0] in outgoing
    )
    if layer_gap is None:
        if not isinstance(chrome, CardChrome):
            # The derived gap reads chrome metrics before Graph validates it.
            raise SpecError("CausalGraph chrome must be a CardChrome")
        labeled_indegree: dict[str, int] = {}
        for wire in wire_values:
            if isinstance(wire, Wire) and wire.label is not None:
                labeled_indegree[wire.dst] = labeled_indegree.get(wire.dst, 0) + 1
        max_stack = max(labeled_indegree.values(), default=1) - 1
        label_offset = chrome.caption_size + 2
        label_step = chrome.caption_size + 4
        layer_gap = max(
            56,
            18 + label_offset + chrome.caption_size + label_step * max_stack,
        )
    return Graph(
        nodes=cast("tuple[tuple[str, Card], ...]", node_values),
        layout=LayeredDag(),
        wires=cast("tuple[Wire, ...]", wire_values),
        collapsible=cast("tuple[str, ...]", collapsible),
        theme=theme,
        chrome=chrome,
        dom_prefix=dom_prefix,
        gap=gap,
        layer_gap=layer_gap,
    )


__all__ = ["CausalGraph"]
